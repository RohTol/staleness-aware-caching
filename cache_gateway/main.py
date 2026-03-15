"""
Cache Gateway

Agents call POST /v1/tools/invoke with a tool call + workflow context.
The gateway checks the cache (depending on policy), calls the API simulator
on a miss, and returns the result.

Request:
  {
    "tool":                  "price" | "trend" | "weather" | "news_sentiment",
    "args":                  {"ticker": "AAPL"} | {"city": "NYC"},
    "workflow_step":         0,   # topological depth in the LangGraph DAG
    "downstream_dependents": 2    # nodes reachable from this node in the DAG
  }

Response: same as the API simulator response, plus cache metadata:
  {
    "tool":            ...,
    "key":             ...,
    "value":           ...,
    "version":         ...,
    "last_changed_at": ...,
    "cache_status":    "hit" | "miss" | "bypass",
    "ttl_s":           30.0   (0 if bypass)
  }

Metrics endpoint:
  GET /metrics  — hit rate, total hits, total misses, upstream call count
"""

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict

from cache import Cache
from config import Settings
from policy import get_policy, WorkflowAwareTTLPolicy


settings = Settings()
policy = get_policy(settings)
cache = Cache()
upstream_calls: int = 0

app = FastAPI(title="Cache Gateway", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ToolInvokeRequest(BaseModel):
    tool: str
    args: Dict[str, Any]
    workflow_step: int = 0
    downstream_dependents: int = 0


# ---------------------------------------------------------------------------
# Upstream call
# ---------------------------------------------------------------------------

async def call_upstream(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    global upstream_calls
    upstream_calls += 1
    url = f"{settings.simulator_url}/{tool}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=args, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code,
                                detail=f"Upstream error: {e.response.text}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=503,
                                detail=f"Upstream unreachable: {str(e)}")


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@app.post("/v1/tools/invoke")
async def invoke_tool(req: ToolInvokeRequest):
    # No-cache policy: skip cache entirely
    if not policy.should_cache():
        data = await call_upstream(req.tool, req.args)
        return {**data, "cache_status": "bypass", "ttl_s": 0}

    # Check cache
    cached = cache.get(req.tool, req.args)
    if cached is not None:
        return {**cached, "cache_status": "hit"}

    # Cache miss: call upstream, store result
    data = await call_upstream(req.tool, req.args)
    ttl = policy.get_ttl(req.tool, req.workflow_step, req.downstream_dependents)
    cache.set(req.tool, req.args, data, ttl)
    return {**data, "cache_status": "miss", "ttl_s": ttl}


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------

@app.get("/metrics")
async def metrics():
    base = {
        "policy":         settings.policy,
        "hits":           cache.hits,
        "misses":         cache.misses,
        "hit_rate":       round(cache.hit_rate, 4),
        "upstream_calls": upstream_calls,
    }
 
    # For workflow_aware, add a TTL preview table so you can sanity-check
    # at a glance what TTLs are actually being assigned for each combination
    # of tool x downstream_dependents x workflow_step.  Useful when tuning
    # GW_WA_POSITION_WEIGHT and GW_WA_MIN_TTL_FRACTION.
    if isinstance(policy, WorkflowAwareTTLPolicy):
        tools = ["price", "trend", "weather", "news_sentiment"]
        preview = {}
        for tool in tools:
            preview[tool] = {
                # Show TTL for 1/2/3 dependents at step 0 (root) and step 1 (non-root)
                "step0_deps1": policy.get_ttl(tool, workflow_step=0, downstream_dependents=1),
                "step0_deps2": policy.get_ttl(tool, workflow_step=0, downstream_dependents=2),
                "step0_deps3": policy.get_ttl(tool, workflow_step=0, downstream_dependents=3),
                "step1_deps1": policy.get_ttl(tool, workflow_step=1, downstream_dependents=1),
                "step1_deps2": policy.get_ttl(tool, workflow_step=1, downstream_dependents=2),
                "step1_deps3": policy.get_ttl(tool, workflow_step=1, downstream_dependents=3),
            }
            
        base["ttl_preview"] = preview
        base["wa_config"] = {
            "position_weight":  settings.wa_position_weight,
            "min_ttl_fraction": settings.wa_min_ttl_fraction,
        }
 
    return base


@app.get("/health")
async def health():
    return {"status": "ok", "policy": settings.policy}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=False)
