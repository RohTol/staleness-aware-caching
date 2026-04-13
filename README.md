# Correctness-Aware Caching for Agentic LLM Tool Calls

## Project Overview

LLM agents solve tasks by making sequential tool calls — fetching a stock price, checking the weather, looking up a trend — and using those results to reason toward a final answer. Caching these tool results is a natural way to reduce cost and latency. But caching introduces staleness, and in agentic workflows, stale data doesn't just return a slightly wrong value: it can steer the agent's reasoning in the wrong direction across multiple downstream steps, producing an incorrect final answer.

The problem with existing caching approaches is that they optimize for the wrong metrics. Hit rate and staleness age are easy to measure, but they don't tell you whether the agent got the right answer. A cache can have a 90% hit rate and still produce wrong answers the majority of the time, if the hits happen to be on tool calls whose results have changed.

**Our contribution:** We show empirically that staleness impact is not uniform across a LangGraph workflow — it depends on where in the workflow a tool call sits. Tool calls with more downstream dependents cause disproportionately more damage when stale. We use this insight to design a workflow-aware TTL policy that tightens TTLs at high-fanout positions, reducing staleness exposure where it matters most at the same API cost as fixed-TTL baselines. Correctness motivates the work: stale data in agentic workflows leads to wrong answers. But the primary contribution is the staleness non-uniformity finding and the policy that exploits it.

---

## What We're Building

The project has three main components working together:

```
LangGraph Agent  →  Cache Gateway  →  API Simulator
(DAG of tool         (policy logic)    (dynamic backend)
 call nodes)

POST /v1/tools/invoke    HIT / MISS      GET /price?ticker=
{tool, args,             STALE / FRESH   GET /weather?city=
 workflow_step,                          GET /trend?ticker=
 downstream_deps}                        GET /news_sentiment?ticker=
```

A **LangGraph Agent** defines each task as a DAG of tool call nodes. LangGraph's graph structure gives us workflow context for free — downstream dependent count is derived directly from the graph edges, and workflow step is the node's topological depth. We run multiple concurrent agent instances to generate realistic cache sharing across agents.

The **Cache Gateway** sits between the agent and the external tools. It intercepts every tool call, checks the cache, returns a hit if valid, and calls upstream on a miss. It implements multiple pluggable policies that use different strategies to decide when a cached result is fresh enough to return.

The **API Simulator** is a fake external backend that mimics real dynamic APIs. Values change over time at configurable rates, and every response includes version metadata so we can measure staleness precisely against ground truth.

---

## The Central Experiment

We run the same agent tasks under three cache policies and measure how often the agent produces the correct final answer compared to a no-cache baseline.

**Example task:** "Should I buy, sell, or hold AAPL?"

```
Step 1: get_price(AAPL)        ← current price, changes frequently
Step 2: get_trend(AAPL)        ← 30-day moving average, changes slowly
Step 3: decide based on        ← (current - avg) / avg > threshold
         (step 1, step 2)
```

Ground truth is computed by running the same workflow with fully fresh data. Correctness is whether the cached-data decision matches.

Notice that staleness in Step 1 (current price, high change rate) will corrupt the decision far more often than staleness in Step 2 (30-day trend, low change rate). A policy that treats both tool calls identically will over-cache Step 1 and under-utilize the cache on Step 2. A workflow-aware policy can do better.

---

## Components

### 1. API Simulator (`api_simulator/`) ✅

A FastAPI server that mimics dynamic external tool APIs. Values change continuously over time via a background update loop, and every response includes version metadata so the cache layer can measure staleness with ground-truth precision.

**Endpoints:**
- `GET /price?ticker=<ticker>` — current stock price (~1 change per 20s)
- `GET /news_sentiment?ticker=<ticker>` — news sentiment score in [-1, 1] (~1 change per 50s)
- `GET /weather?city=<city>` — current temperature (~1 change per 3 min)
- `GET /trend?ticker=<ticker>` — 30-day moving average (~1 change per 15 min)
- `GET /health` — liveness check

**Sample response:**
```json
{
  "tool": "price",
  "key": "AMZN",
  "value": 173.21,
  "version": 47,
  "last_changed_at": "2026-03-09T14:12:22Z"
}
```

**Files:**

| File | Description |
|---|---|
| `config.py` | All configurable knobs as env vars (prefixed `SIM_`). Change rates, latency params, error rate, rate limit. |
| `state.py` | Per-key state and background Poisson update loop. Each key has `value`, `version`, and `last_changed_at`. Weather drifts via random walk; prices via multiplicative random walk. |
| `main.py` | FastAPI app. Injects lognormal latency and random 503 errors on each request. Token-bucket rate limiter when enabled. |

**Key config vars:**

| Variable | Default | Effect |
|---|---|---|
| `SIM_PRICE_CHANGE_RATE` | `0.05` | ~1 price change per 20s |
| `SIM_SENTIMENT_CHANGE_RATE` | `0.02` | ~1 sentiment change per 50s |
| `SIM_WEATHER_CHANGE_RATE` | `0.005` | ~1 weather change per 3 min |
| `SIM_TREND_CHANGE_RATE` | `0.001` | ~1 trend change per 15 min |
| `SIM_ERROR_RATE` | `0.02` | 2% of requests return 503 |
| `SIM_RATE_LIMIT_RPS` | `0` | Rate limit (0 = disabled) |

**Run it:**
```bash
cd api_simulator
pip install -r requirements.txt
python3 main.py
# or override config:
SIM_PRICE_CHANGE_RATE=0.1 SIM_ERROR_RATE=0.05 python3 main.py
```

---

### 2. Cache Gateway (`cache_gateway/`) ✅

An HTTP gateway that agents call via `POST /v1/tools/invoke`. Implements pluggable caching policies and sits between the agent and the API simulator. Policy is selected at startup via env var — each experiment run is a single policy so metrics are clean.

**Request format:**
```json
{
  "tool": "price",
  "args": {"ticker": "AAPL"},
  "workflow_step": 0,
  "downstream_dependents": 3
}
```

`workflow_step` and `downstream_dependents` are derived automatically from the LangGraph DAG structure — not manually annotated.

**Response format:** same as the API simulator, plus cache metadata:
```json
{
  "tool": "price",
  "key": "AAPL",
  "value": 182.34,
  "version": 47,
  "last_changed_at": "2026-03-13T14:12:22Z",
  "cache_status": "hit",
  "ttl_s": 20.0
}
```

`cache_status` is `"hit"`, `"miss"`, or `"bypass"` (no-cache policy).

**Policies (selected via `GW_POLICY` env var):**
- `none` — always calls upstream, never caches. Correctness baseline.
- `fixed_ttl` — one TTL per tool type, ignores workflow position entirely. Standard baseline equivalent to what Redis does out of the box.
- `workflow_aware` — TTL tightened for calls with more downstream dependents and higher change rates.

**Files:**

| File | Description |
|---|---|
| `config.py` | All knobs as env vars (prefixed `GW_`). Policy selection, per-tool TTLs, simulator URL. |
| `cache.py` | In-memory cache store. Key is `(tool, frozenset(args))`. Tracks hits/misses, evicts expired entries on read. |
| `policy.py` | Policy classes. `NoCachePolicy` bypasses cache entirely. `FixedTTLPolicy` returns per-tool TTL, intentionally ignores workflow context. `WorkflowAwareTTLPolicy` tightens TTL based on downstream dependent count and workflow position. |
| `main.py` | FastAPI gateway. Routes `POST /v1/tools/invoke` through cache logic and upstream calls. `GET /metrics` returns hit rate and upstream call count. |

**Key config vars:**

| Variable | Default | Effect |
|---|---|---|
| `GW_POLICY` | `none` | `none`, `fixed_ttl`, or `workflow_aware` |
| `GW_TTL_PRICE_S` | `20.0` | Base TTL for price calls |
| `GW_TTL_SENTIMENT_S` | `45.0` | Base TTL for news_sentiment calls |
| `GW_TTL_WEATHER_S` | `180.0` | Base TTL for weather calls |
| `GW_TTL_TREND_S` | `600.0` | Base TTL for trend calls |
| `GW_SIMULATOR_URL` | `http://localhost:8001` | API simulator address |
| `GW_WA_POSITION_WEIGHT` | `1.5` | (`workflow_aware` only) Extra tightening multiplier for step-0 (root) calls. Root calls gate branching — a stale root sends the agent down the wrong branch entirely. Set to `1.0` to disable position-based tightening. |
| `GW_WA_MIN_TTL_FRACTION` | `0.2` | (`workflow_aware` only) Floor on TTL as a fraction of the base. Prevents over-tightening — e.g. price TTL never goes below 4s no matter how many dependents a call has. |

**Run it:**
```bash
cd cache_gateway
pip install -r requirements.txt

# No-cache baseline
GW_POLICY=none python3 main.py

# Fixed TTL
GW_POLICY=fixed_ttl python3 main.py

# Workflow-aware TTL (our contribution)
GW_POLICY=workflow_aware python3 main.py
 
# Workflow-aware with custom tuning (optional)
GW_POLICY=workflow_aware GW_WA_POSITION_WEIGHT=2.0 GW_WA_MIN_TTL_FRACTION=0.1 python3 main.py

# Test it (with simulator running on 8001)
curl -X POST http://localhost:8002/v1/tools/invoke \
  -H "Content-Type: application/json" \
  -d '{"tool":"price","args":{"ticker":"AAPL"},"workflow_step":0,"downstream_dependents":3}'

# Check metrics
# When running workflow_aware, /metrics includes a ttl_preview table showing the exact
# TTL assigned for every tool × workflow_step × downstream_dependents combination.
# Useful for sanity-checking the policy before running experiments.
curl http://localhost:8002/metrics | python3 -m json.tool
```

---

### 3. LangGraph Agent (`agent/`) ✅

Defines agent tasks as LangGraph DAGs and executes them against the cache gateway. Workflow context (`workflow_step`, `downstream_dependents`) is statically derived from the DAG structure and passed to the gateway on every tool call — no manual annotation needed.

**Task types:**
- **Investment decision** — price → conditional news_sentiment or trend → buy/sell/hold
- **Portfolio rebalancing** — price × 3 (fan-in) → risk/tax computation → rebalance decision

For each trial, the agent runs the workflow twice: once through the gateway (potentially stale) and once directly against the simulator (always fresh). The fresh run is ground truth. Staleness is detected per-call by comparing the version number returned by the gateway hit against the current version fetched immediately after from the simulator.

**Files:**

| File | Description |
|---|---|
| `config.py` | Env vars (prefixed `AGENT_`). Gateway URL, simulator URL, n_trials, workflow selection. |
| `client.py` | `call_gateway()` and `call_fresh()` — thin HTTP clients for the gateway and simulator. |
| `workflows/investment_decision.py` | Branching chain workflow. `fetch_price` gates branch to `fetch_news_sentiment` or `fetch_trend`. |
| `workflows/portfolio_rebalancing.py` | Fan-in workflow. Three parallel price fetches → compute_risk/tax → decide. |
| `runner.py` | `run_experiment()` runs N trials. `compute_metrics()` aggregates staleness by fanout tier and correctness rate. |
| `main.py` | Entry point. Prints per-trial results and final metrics JSON. |

**Run it:**
```bash
cd agent
pip install -r requirements.txt

# Default: investment_decision, 100 trials
python3 main.py

# Portfolio rebalancing, 50 trials
AGENT_WORKFLOW=portfolio_rebalancing AGENT_N_TRIALS=50 python3 main.py
```

The gateway policy is set on the gateway side (`GW_POLICY`). Run the agent once per policy and compare `staleness_by_downstream_dependents` in the output.

---

## Experimental Results

All experiments ran from the same starting point in the price CSV (row 0) with mutable simulator state reset between policies. ~2000 trials per policy per workflow.

---

### Workflow 1: Investment Decision (branching / fan-out)

11 tickers, routing threshold calibrated to 0.5% so stale prices can cross the branch boundary.

| Policy | Hit Rate | Mismatch Rate | Avg Latency |
|---|---|---|---|
| `none` (baseline) | 0% | **0.0%** | 280ms |
| `fixed_ttl` | 79.9% | **2.7%** | 79ms |
| `workflow_aware` | 49.6% | **1.2%** | 110ms |

**Key findings:**

**1. Workflow-aware reduces decision errors by 2.25× vs. fixed TTL** (2.7% → 1.2%), while staying 2.5× faster than no-cache and retaining nearly half the hit rate.

**2. Wrong-branch routing errors eliminated entirely.** workflow_aware tightens the price TTL at the root node (step=0, deps=3) from 20s → 6.7s. Under fixed_ttl, 27.3% of mismatches are wrong-branch errors — a stale price routes the agent to the wrong branch, suppressing the correct downstream call. Workflow-aware reduces this to zero.

| Mismatch type | fixed_ttl | workflow_aware |
|---|---|---|
| Wrong-branch (stale price → wrong routing) | 15/55 (27.3%) | **0/24 (0.0%)** |
| Same-branch (stale leaf value → wrong decision) | 40/55 (72.7%) | 24/24 (100%) |

**3. Branch-level breakdown:**

| Branch | fixed_ttl mismatch rate | workflow_aware mismatch rate |
|---|---|---|
| news_sentiment | 11.9% (26/219) | 0.5% (1/215) — **96% reduction** |
| trend | 1.6% (29/1785) | 1.3% (23/1793) — **19% reduction** |

**4. Residual 1.2% mismatches** in workflow_aware come entirely from stale leaf nodes (step=1, deps=1) — intentionally not tightened.

---

### Workflow 2: Portfolio Rebalancing (fan-in)

3 stocks (AAPL, GOOG, NVDA), all at step=0 with the same change rate. AAPL has 3 downstream dependents (risk + tax + decide); GOOG and NVDA have 2 (risk + decide). Decision: rebalance any stock whose price has drifted >0.5% from its reference price.

| Policy | Hit Rate | Mismatch Rate | Avg Latency |
|---|---|---|---|
| `none` (baseline) | 0% | **0.3%** | 337ms |
| `fixed_ttl` | 97.1% | **6.5%** | 89ms |
| `workflow_aware` | 91.6% | **3.2%** | 111ms |

**Key findings:**

**1. Workflow-aware reduces mismatches 2× vs. fixed TTL** (6.5% → 3.2%), consistent with the investment_decision result despite a completely different DAG shape.

**2. No wrong-branch errors by construction** — fan-in workflows have no conditional routing, so all mismatches are decision-level (stale price → wrong rebalance call per ticker). This isolates the downstream_dependents variable cleanly: the only structural difference between AAPL and GOOG/NVDA is fanout, not change rate.

**3. The 2× mismatch reduction is driven by AAPL.** workflow_aware tightens AAPL's TTL more aggressively than GOOG/NVDA because it has more downstream dependents — a stale AAPL price corrupts both the risk metric and the tax computation. GOOG/NVDA staleness only corrupts the risk metric.

**Caveat:** fixed_ttl hits 97.1% here (vs 79.9% on investment_decision) because portfolio rebalancing has no branching — the same three price keys are fetched every trial, so the cache warms up quickly and stays warm. The high hit rate amplifies the mismatch rate.

---

### How to Reproduce

```bash
# Start the simulator (keep running throughout)
cd api_simulator && python3 main.py

# Investment decision (11 tickers, 3 policies)
cd .. && bash run_experiments.sh

# Portfolio rebalancing (AAPL/GOOG/NVDA, 3 policies)
bash run_portfolio_experiments.sh

# Analyze
cd agent
python3 analyze.py results/results_none_v2.csv results/results_fixed_ttl_v2.csv results/results_workflow_aware_v2.csv
python3 analyze.py results/port_none_v1.csv results/port_fixed_ttl_v1.csv results/port_workflow_aware_v1.csv
```

---

## Next Steps (Research Roadmap)

**Near-term validation:**
- **Visualizations** — matplotlib charts for the mismatch rate comparison, latency tradeoff curve, and staleness duration distribution for use in slides/paper.

**Longer-term research directions:**
- **Real LLM integration** — connect to an actual LLM (Claude, GPT-4) and measure how staleness in tool results propagates through LLM reasoning chains. Current agent logic is deterministic; the interesting question is whether LLMs are more or less robust to stale inputs than deterministic decision rules.
- **Adaptive TTL learning** — replace hand-tuned per-position TTLs with an online learner that observes staleness/mismatch feedback and adjusts TTLs automatically. The workflow-aware policy is a hand-crafted prior; the goal is to learn it from data.
- **Staleness budget allocation** — formalize the problem: given a tolerable mismatch rate budget, allocate TTLs optimally across the DAG. Opens up principled optimization framing (LP, bandit methods).
- **Generalization to arbitrary DAGs** — auto-derive the TTL policy from any LangGraph DAG at runtime purely from graph structure, rather than per-workflow hand-coding. This is what makes the contribution broadly deployable.
- **Multi-agent cache sharing** — when concurrent agents share a cache, one agent's stale hit can corrupt another agent's correctness. Characterize how staleness propagates across agents and whether per-agent TTL policies are needed.

---

## Poster Outline

> Structure for the CSE585 poster presentation. Required sections: abstract, motivation/problem, solution, evaluation, next steps.

### Abstract
Caching tool call results in LLM agentic workflows reduces cost and latency, but stale cached data can silently corrupt agent decisions. We show that staleness impact is non-uniform across a workflow DAG — tool calls at high-fanout positions cause disproportionately more decision errors when stale. We evaluate this across two workflow topologies (branching fan-out and parallel fan-in) and design a workflow-aware TTL policy that exploits DAG structure, reducing decision mismatches by ~2× over a standard fixed-TTL cache across both workflows while retaining most of the latency benefit.

### 1. Motivation / Problem
- LLM agents make sequential tool calls (price lookups, news sentiment, trends) and cache results to reduce API cost and latency.
- Standard caches treat all tool calls identically — same TTL regardless of where the call sits in the workflow.
- **Key insight:** a stale result at a branching root node sends the agent down the *wrong branch entirely*, suppressing all downstream calls. A stale leaf value only corrupts one final output. Position matters.
- No existing caching policy accounts for workflow structure when setting TTLs.

### 2. Solution
- **Workflow-aware TTL policy:** tighten TTLs at nodes with more downstream dependents and higher topological importance.
- TTL formula: `TTL = base_ttl / (1 + α * downstream_deps) * position_weight`
- Downstream dependent count and workflow step are derived automatically from the LangGraph DAG — no manual annotation.
- Three policies compared: `none` (always fresh), `fixed_ttl` (standard baseline), `workflow_aware` (our contribution).

### 3. Evaluation
- **Two workflows:** `investment_decision` (branching/fan-out, 11 tickers) and `portfolio_rebalancing` (fan-in, AAPL/GOOG/NVDA)
- **Setup:** ~2000 trials per policy per workflow, ground truth from simultaneous fresh API calls
- **Metric:** mismatch rate (cached-data decision ≠ fresh-data decision)

**Investment Decision** (branching — stale root can cause wrong routing):

| Policy | Hit Rate | Mismatch Rate | Avg Latency |
|---|---|---|---|
| `none` | 0% | 0.0% | 280ms |
| `fixed_ttl` | 79.9% | 2.7% | 79ms |
| `workflow_aware` | 49.6% | **1.2%** | 110ms |

**Portfolio Rebalancing** (fan-in — isolates downstream_dependents independent of change rate):

| Policy | Hit Rate | Mismatch Rate | Avg Latency |
|---|---|---|---|
| `none` | 0% | 0.3% | 337ms |
| `fixed_ttl` | 97.1% | 6.5% | 89ms |
| `workflow_aware` | 91.6% | **3.2%** | 111ms |

- **2× fewer decision errors** vs. fixed_ttl across both workflows
- **Wrong-branch routing eliminated entirely** in investment_decision (fixed_ttl: 27.3% of mismatches were wrong-branch; workflow_aware: 0%)
- Only ~25–39% slower than fixed_ttl, 2.5–3× faster than no-cache

### 4. Next Steps
See [Research Roadmap](#next-steps-research-roadmap) above. Key priorities: real LLM integration, adaptive TTL learning, staleness budget formalization.
