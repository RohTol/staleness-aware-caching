"""
Portfolio Rebalancing workflow — "Which of my holdings should I rebalance?"

Shape: parallel price lookups → compute_risk → decide

    fetch_price(AAPL)  ─┬─→  compute_risk  →  decide
    fetch_price(GOOG)  ─┤                ↗
    fetch_price(MSFT)  ─┘
                        └──→  compute_tax(AAPL)  →  decide

Executed sequentially (no async), but conceptually parallel — all three price
calls are at step=0 since none depends on another.

Downstream dependents (from DAG edges):
    get_price(AAPL)  → 3  (risk, tax, decide)
    get_price(GOOG)  → 2  (risk, decide)
    get_price(MSFT)  → 2  (risk, decide)

Key property: AAPL has a larger blast radius than GOOG/MSFT even though all
three price calls have the same change rate. This isolates downstream_dependents
as the variable — independent of change rate.
"""

import operator
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, StateGraph

from client import call_fresh, call_gateway

TICKERS = ["AAPL", "GOOG", "MSFT"]
TARGET_WEIGHTS = {"AAPL": 0.4, "GOOG": 0.3, "MSFT": 0.3}
REBALANCE_THRESHOLD = 0.05  # rebalance if allocation drifts > 5%

_CTX: dict[str, dict] = {
    "fetch_price_AAPL": {"workflow_step": 0, "downstream_dependents": 3},
    "fetch_price_GOOG": {"workflow_step": 0, "downstream_dependents": 2},
    "fetch_price_MSFT": {"workflow_step": 0, "downstream_dependents": 2},
}


class PortfolioState(TypedDict):
    prices: dict[str, float]
    price_versions: dict[str, Optional[int]]
    risk_metric: Optional[float]
    tax_liability: Optional[float]
    decision: Optional[str]
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


def build_graph(gateway_url: str, simulator_url: str, use_cache: bool = True):

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
            return {
                "prices": {**state.get("prices", {}), ticker: result["value"]},
                "price_versions": {**state.get("price_versions", {}), ticker: result.get("version")},
                "call_log": [_log_entry(node, "price", args, result)],
            }

        fn.__name__ = node
        return fn

    def compute_risk_and_tax(state: PortfolioState) -> dict:
        prices = state["prices"]
        total_value = sum(prices.values())
        if total_value == 0:
            return {"risk_metric": 0.0, "tax_liability": 0.0}

        # Risk metric: max allocation drift from target weights
        max_drift = max(
            abs(prices[t] / total_value - TARGET_WEIGHTS[t])
            for t in TICKERS
            if t in prices
        )

        # Tax liability: simplified — proportional to AAPL value (highest gain assumption)
        aapl_price = prices.get("AAPL", 0.0)
        tax_liability = aapl_price * 0.15  # 15% capital gains estimate

        return {"risk_metric": max_drift, "tax_liability": tax_liability}

    def decide(state: PortfolioState) -> dict:
        prices = state["prices"]
        total_value = sum(prices.values())
        if total_value == 0:
            return {"decision": "HOLD_ALL"}

        to_rebalance = [
            t for t in TICKERS
            if t in prices and abs(prices[t] / total_value - TARGET_WEIGHTS[t]) > REBALANCE_THRESHOLD
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
    g.add_edge("fetch_price_GOOG", "fetch_price_MSFT")
    g.add_edge("fetch_price_MSFT", "compute_risk_and_tax")
    g.add_edge("compute_risk_and_tax", "decide")
    g.add_edge("decide", END)

    initial_state: PortfolioState = {
        "prices": {},
        "price_versions": {},
        "risk_metric": None,
        "tax_liability": None,
        "decision": None,
        "call_log": [],
    }

    return g.compile(), initial_state
