
"""
Portfolio Rebalancing workflow — "Which of my holdings should I rebalance?"

Shape: parallel price lookups → compute_risk → decide

    fetch_price(AAPL)  ─┬─→  compute_risk  →  decide
    fetch_price(GOOG)  ─┤                ↗
    fetch_price(NVDA)  ─┘
                        └──→  compute_tax(AAPL)  →  decide

Executed sequentially (no async), but conceptually parallel — all three price
calls are at step=0 since none depends on another.

Downstream dependents (from DAG edges):
    get_price(AAPL)  → 3  (risk, tax, decide)
    get_price(GOOG)  → 2  (risk, decide)
    get_price(NVDA)  → 2  (risk, decide)

Key property: AAPL has a larger blast radius than GOOG/NVDA even though all
three price calls have the same change rate. This isolates downstream_dependents
as the variable — independent of change rate.
"""

import operator
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, StateGraph

from client import call_fresh, call_gateway

TICKERS = ["AAPL", "GOOG", "NVDA"]
# Rebalance if any stock has drifted > 0.5% from its reference price.
# Calibrated to match inter-row price volatility in compressed_stocks_data.csv
# so stale cached prices (off by ~0.5-1%) can flip a rebalance decision.
REBALANCE_THRESHOLD = 0.005  # 0.5% drift from reference price → rebalance

# Reference prices: median of compressed_stocks_data.csv for each ticker.
# Decisions are based on how much current prices have moved from here.
REFERENCE_PRICES = {"AAPL": 253.40, "GOOG": 287.46, "NVDA": 174.53}

_CTX: dict[str, dict] = {
    "fetch_price_AAPL": {"workflow_step": 0, "downstream_dependents": 3},
    "fetch_price_GOOG": {"workflow_step": 0, "downstream_dependents": 2},
    "fetch_price_NVDA": {"workflow_step": 0, "downstream_dependents": 2},
}


class PortfolioState(TypedDict):
    prices: dict[str, float]
    price_versions: dict[str, Optional[int]]
    risk_metric: Optional[float]
    tax_liability: Optional[float]
    decision: Optional[str]
    branch_taken: Optional[str]    # always "portfolio" — signals no branching to runner
    interval_index: Optional[int]  # AAPL price version (canonical row reference)
    simulated_time: Optional[str]  # AAPL last_changed_at
    call_log: Annotated[list[dict], operator.add]


def _log_entry(node: str, tool: str, args: dict, result: dict) -> dict:
    ctx = _CTX[node]
    return {
        "node": node,
        "tool": tool,
        "args": args,
        "value": result["value"],
        "version": result.get("version"),
        "cache_status": result.get("cache_status", "bypass"),
        "workflow_step": ctx["workflow_step"],
        "downstream_dependents": ctx["downstream_dependents"],
    }


def build_graph(gateway_url: str, simulator_url: str, use_cache: bool = True, **_kwargs):

    def _call(node: str, tool: str, args: dict) -> dict:
        ctx = _CTX[node]
        if use_cache:
            return call_gateway(
                gateway_url, tool, args,
                ctx["workflow_step"], ctx["downstream_dependents"],
            )
        return call_fresh(simulator_url, tool, args)

    def _fetch_price(ticker: str):
        node = f"fetch_price_{ticker}"

        def fn(state: PortfolioState) -> dict:
            args = {"ticker": ticker}
            result = _call(node, "price", args)
            update: dict = {
                "prices": {**state.get("prices", {}), ticker: result["value"]},
                "price_versions": {**state.get("price_versions", {}), ticker: result.get("version")},
                "call_log": [_log_entry(node, "price", args, result)],
            }
            # AAPL is the canonical reference row (highest fanout, fetched first)
            if ticker == "AAPL":
                update["interval_index"] = result.get("version")
                update["simulated_time"] = result.get("last_changed_at")
            return update

        fn.__name__ = node
        return fn

    def compute_risk_and_tax(state: PortfolioState) -> dict:
        prices = state["prices"]

        # Risk metric: max price drift from reference across all holdings
        drifts = {
            t: abs(prices[t] - REFERENCE_PRICES[t]) / REFERENCE_PRICES[t]
            for t in TICKERS if t in prices
        }
        max_drift = max(drifts.values()) if drifts else 0.0

        # Tax liability: proportional to AAPL drift (highest fanout, highest blast radius)
        aapl_drift = drifts.get("AAPL", 0.0)
        tax_liability = aapl_drift * 1000.0  # arbitrary scale for reporting

        return {"risk_metric": max_drift, "tax_liability": tax_liability}

    def decide(state: PortfolioState) -> dict:
        prices = state["prices"]

        # Rebalance any holding whose price has drifted > threshold from reference.
        # Stale cached prices (off by ~0.5-1%) can flip this per-ticker decision.
        to_rebalance = [
            t for t in TICKERS
            if t in prices
            and abs(prices[t] - REFERENCE_PRICES[t]) / REFERENCE_PRICES[t] > REBALANCE_THRESHOLD
        ]
        decision = f"REBALANCE:{','.join(sorted(to_rebalance))}" if to_rebalance else "HOLD_ALL"
        return {"decision": decision}

    g = StateGraph(PortfolioState)
    for ticker in TICKERS:
        g.add_node(f"fetch_price_{ticker}", _fetch_price(ticker))
    g.add_node("compute_risk_and_tax", compute_risk_and_tax)
    g.add_node("decide", decide)

    g.set_entry_point("fetch_price_AAPL")
    g.add_edge("fetch_price_AAPL", "fetch_price_GOOG")
    g.add_edge("fetch_price_GOOG", "fetch_price_NVDA")
    g.add_edge("fetch_price_NVDA", "compute_risk_and_tax")
    g.add_edge("compute_risk_and_tax", "decide")
    g.add_edge("decide", END)

    initial_state: PortfolioState = {
        "prices": {},
        "price_versions": {},
        "risk_metric": None,
        "tax_liability": None,
        "decision": None,
        "branch_taken": "portfolio",
        "interval_index": None,
        "simulated_time": None,
        "call_log": [],
    }

    return g.compile(), initial_state
