"""
HTTP clients for the cache gateway and API simulator.

call_gateway  — routes through the cache (hit/miss/bypass depending on policy)
call_fresh    — bypasses the gateway entirely, always hits the simulator directly
"""

import httpx
from typing import Any

_TOOL_PATHS: dict[str, str] = {
    "price":          "/price",
    "trend":          "/trend",
    "weather":        "/weather",
    "news_sentiment": "/news_sentiment",
}


def call_gateway(
    gateway_url: str,
    tool: str,
    args: dict[str, Any],
    workflow_step: int,
    downstream_dependents: int,
) -> dict:
    r = httpx.post(
        f"{gateway_url}/v1/tools/invoke",
        json={
            "tool": tool,
            "args": args,
            "workflow_step": workflow_step,
            "downstream_dependents": downstream_dependents,
        },
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()


def call_fresh(simulator_url: str, tool: str, args: dict[str, Any]) -> dict:
    """Call simulator directly, bypassing the cache. Used for ground truth."""
    path = _TOOL_PATHS[tool]
    r = httpx.get(f"{simulator_url}{path}", params=args, timeout=10.0)
    r.raise_for_status()
    data = r.json()
    data["cache_status"] = "bypass"
    return data
