# Correctness-Aware Caching for Agentic LLM Tool Calls

## Project Overview

LLM agents solve tasks by making sequential tool calls — fetching a stock price, checking the weather, looking up a trend — and using those results to reason toward a final answer. Caching these tool results is a natural way to reduce cost and latency. But caching introduces staleness, and in agentic workflows, stale data doesn't just return a slightly wrong value: it can steer the agent's reasoning in the wrong direction across multiple downstream steps, producing an incorrect final answer.

The problem with existing caching approaches is that they optimize for the wrong metrics. Hit rate and staleness age are easy to measure, but they don't tell you whether the agent got the right answer. A cache can have a 90% hit rate and still produce wrong answers the majority of the time, if the hits happen to be on tool calls whose results have changed.

**Our contribution:** We show empirically that conventional cache metrics are poor proxies for agent answer correctness, and that staleness impact is not uniform — it depends on where in the workflow a tool call sits. Tool calls that many downstream steps depend on are far more damaging when stale than leaf-node calls. We use this insight to design a workflow-aware TTL policy that allocates tighter TTLs to high-impact tool calls, achieving better correctness at the same API cost as fixed-TTL baselines.

---

## What We're Building

The project has three main components working together:

```
Agent Runner  →  Cache Gateway  →  API Simulator
(multi-step        (policy logic)    (dynamic backend)
 workflows)

POST /v1/tools/invoke    HIT / MISS      GET /price?ticker=
{tool, args,             STALE / FRESH   GET /weather?city=
 workflow_step,
 downstream_deps}
```

An **Agent Runner** executes structured multi-step tasks. Each task requires several sequential tool calls, and the results of earlier calls feed into later ones. The agent runner knows the workflow structure and annotates each tool call with its position and how many downstream steps depend on it.

The **Cache Gateway** sits between the agent and the external tools. It intercepts every tool call, checks the cache, returns a hit if valid, and calls upstream on a miss. It implements multiple pluggable policies that use different strategies to decide when a cached result is fresh enough to return.

The **API Simulator** is a fake external backend that mimics real dynamic APIs. Values change over time at configurable rates (stock prices change fast, weather changes slowly), and every response includes version metadata so we can measure staleness precisely.

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
- `GET /weather?city=<city>` — returns current temperature for a city
- `GET /price?ticker=<ticker>` — returns current price for a ticker
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
| `SIM_WEATHER_CHANGE_RATE` | `0.005` | ~1 weather change per 3 min |
| `SIM_PRICE_CHANGE_RATE` | `0.05` | ~1 price change per 20s |
| `SIM_ERROR_RATE` | `0.02` | 2% of requests return 503 |
| `SIM_RATE_LIMIT_RPS` | `0` | Rate limit (0 = disabled) |
| `SIM_WEATHER_LATENCY_MEAN_MS` | `80` | Mean weather response latency |
| `SIM_PRICE_LATENCY_MEAN_MS` | `40` | Mean price response latency |

**Run it:**
```bash
cd api_simulator
pip install -r requirements.txt
python3 main.py
# or override config:
SIM_PRICE_CHANGE_RATE=0.1 SIM_ERROR_RATE=0.05 python3 main.py
```

---

### 2. Cache Gateway (`cache_gateway/`) 🚧

An HTTP gateway that agents call via `POST /v1/tools/invoke`. Implements pluggable caching policies and sits between the agent and the API simulator.

Each request carries workflow context so the policy layer can make position-aware decisions:

```json
{
  "tool": "price",
  "args": {"ticker": "AAPL"},
  "workflow_step": 1,
  "downstream_dependents": 2
}
```

**Policies:**
- **No cache** — baseline, always hits upstream, always correct
- **Fixed TTL** — single global TTL per tool type, ignores workflow position
- **Workflow-aware TTL** *(our contribution)* — TTL is tightened for tool calls with more downstream dependents and higher observed change rates

**Planned features:** per-policy correctness tracking, Prometheus metrics, stale-while-revalidate.

---

### 3. Agent Runner (`agent/`) 🚧

Executes structured multi-step agent tasks against the cache gateway. Tasks are defined as workflow DAGs — each step specifies which tool to call, what it depends on, and how its output feeds into downstream steps.

**Task types:**
- **Trading decision** — price + trend → buy/sell/hold (2 tool calls, sequential dependency)
- **Travel advisory** — weather + price (flight cost) → go/don't go (2 parallel + 1 merge step)

For each task, the runner executes it twice: once via the cache gateway (potentially stale) and once directly against the API simulator (always fresh). The fresh result is ground truth. Correctness is whether both agree.

---

## Evaluation Plan

For each policy × task type, report:

- **Correctness rate** — % of agent decisions matching ground truth (primary metric)
- **External API QPS** — proxy for cost
- **Cache hit rate** — shown alongside correctness to demonstrate the disconnect
- **Staleness age** — shown alongside correctness to demonstrate the disconnect

**Key result we expect to show:** Fixed TTL achieves similar or higher hit rates than workflow-aware TTL, but lower correctness — because it over-caches the wrong tool calls. This demonstrates that hit rate is a misleading optimization target in agentic settings.

**Money plot:** Pareto frontier of API cost vs. correctness across policies. Workflow-aware TTL should dominate fixed TTL on this frontier.
