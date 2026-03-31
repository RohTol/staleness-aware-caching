"""
Investment Decision workflow — "Should I buy, sell, or hold AAPL?"

Shape: linear chain with conditional branch

    fetch_price(AAPL)                      step=0, deps=3
        ↓
    IF price dropped > 2% vs reference:
        fetch_news_sentiment(AAPL)         step=1, deps=1  →  decide (SELL / HOLD)
    ELSE:
        fetch_trend(AAPL)                  step=1, deps=1  →  decide (SELL / BUY / HOLD)

Downstream dependents are statically derived from the DAG (all reachable nodes,
counting both branches). fetch_price feeds: the branch decision, one conditional
call (sentiment or trend), and the final decide node = 3.

Key property: fetch_price gates branching. A stale price doesn't just return a
wrong number — it can send the agent down the wrong branch entirely, suppressing
the correct downstream call.
"""

import operator
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, StateGraph

from client import call_fresh, call_gateway

TICKER = "AAPL"
REFERENCE_PRICE = 180.0       # fixed baseline for the price-drop threshold
PRICE_DROP_THRESHOLD = 0.02   # 2%

# Statically defined workflow context for each tool-calling node.
# downstream_dependents = count of all DAG nodes reachable from this node.
_CTX: dict[str, dict] = {
    "fetch_price":          {"workflow_step": 0, "downstream_dependents": 3},
    "fetch_news_sentiment": {"workflow_step": 1, "downstream_dependents": 1},
    "fetch_trend":          {"workflow_step": 1, "downstream_dependents": 1},
}


class InvestmentState(TypedDict):
    price: Optional[float]
    trend: Optional[float]
    news_sentiment: Optional[float]
    decision: Optional[str]
    # Each tool-calling node appends one entry. Annotated[list, operator.add]
    # tells LangGraph to merge by concatenation rather than overwrite.
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
    """
    use_cache=True  → calls go through the gateway (respects policy: hit/miss/bypass)
    use_cache=False → calls go directly to the simulator (ground truth run)
    """

    def _call(node: str, tool: str, args: dict) -> dict:
        ctx = _CTX[node]
        if use_cache:
            return call_gateway(
                gateway_url, tool, args,
                ctx["workflow_step"], ctx["downstream_dependents"],
            )
        return call_fresh(simulator_url, tool, args)

    def fetch_price(state: InvestmentState) -> dict:
        args = {"ticker": TICKER}
        result = _call("fetch_price", "price", args)
        return {
            "price": result["value"],
            "call_log": [_log_entry("fetch_price", "price", args, result)],
        }

    def fetch_news_sentiment(state: InvestmentState) -> dict:
        args = {"ticker": TICKER}
        result = _call("fetch_news_sentiment", "news_sentiment", args)
        return {
            "news_sentiment": result["value"],
            "call_log": [_log_entry("fetch_news_sentiment", "news_sentiment", args, result)],
        }

    def fetch_trend(state: InvestmentState) -> dict:
        args = {"ticker": TICKER}
        result = _call("fetch_trend", "trend", args)
        return {
            "trend": result["value"],
            "call_log": [_log_entry("fetch_trend", "trend", args, result)],
        }

    def decide(state: InvestmentState) -> dict:
        price = state["price"]
        pct_change = (price - REFERENCE_PRICE) / REFERENCE_PRICE
        if pct_change < -PRICE_DROP_THRESHOLD:
            sentiment = state.get("news_sentiment") or 0.0
            decision = "SELL" if sentiment < -0.3 else "HOLD"
        else:
            trend = state.get("trend") or REFERENCE_PRICE
            if price > trend * 1.05:
                decision = "SELL"
            elif price < trend * 0.98:
                decision = "BUY"
            else:
                decision = "HOLD"
        return {"decision": decision}

    def route_after_price(state: InvestmentState) -> str:
        pct_change = (state["price"] - REFERENCE_PRICE) / REFERENCE_PRICE
        return "fetch_news_sentiment" if pct_change < -PRICE_DROP_THRESHOLD else "fetch_trend"

    g = StateGraph(InvestmentState)
    g.add_node("fetch_price", fetch_price)
    g.add_node("fetch_news_sentiment", fetch_news_sentiment)
    g.add_node("fetch_trend", fetch_trend)
    g.add_node("decide", decide)

    g.set_entry_point("fetch_price")
    g.add_conditional_edges(
        "fetch_price",
        route_after_price,
        {"fetch_news_sentiment": "fetch_news_sentiment", "fetch_trend": "fetch_trend"},
    )
    g.add_edge("fetch_news_sentiment", "decide")
    g.add_edge("fetch_trend", "decide")
    g.add_edge("decide", END)

    initial_state: InvestmentState = {
        "price": None,
        "trend": None,
        "news_sentiment": None,
        "decision": None,
        "call_log": [],
    }

    return g.compile(), initial_state
