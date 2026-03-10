# Freshness-Aware Caching for Dynamic Agent Tools

## Project Overview

LLM agents increasingly call external tools — weather APIs, stock feeds, search endpoints — to ground their responses in real-world data. Unlike static LLM outputs, these tool results change over time and require correctness guarantees. Naively caching them risks serving stale data; never caching them wastes API calls and adds latency.

This project designs and evaluates a **freshness-aware caching policy framework** for dynamic agent tool calls under concurrency. We focus on exact-match caching for dynamic external APIs, and study the tradeoff between API cost, response latency, and staleness under realistic agentic traffic patterns (Zipf key popularity, bursty arrivals, hot-key stampedes).

**Our contribution:** A per-key adaptive TTL policy that incorporates observed change rate and request demand — outperforming fixed-TTL baselines on cost and staleness under high concurrency.

---

## Architecture

```
k6 load generator  →  Cache Gateway  →  API Simulator
(agent traffic)       (policy logic)     (dynamic backend)

POST /v1/tools/invoke    HIT / MISS       GET /weather?city=
{tool, args, max_age_s}  STALE / REFRESH  GET /price?ticker=
```

- **k6** simulates concurrent agents sending tool-call requests with freshness constraints
- **Cache Gateway** implements pluggable caching policies and calls the simulator on misses
- **API Simulator** is the fake external backend — values change over time with versioning

---

## Components

### 1. API Simulator (`api_simulator/`) ✅

A FastAPI server that mimics dynamic external tool APIs. Values change continuously over time, and every response includes version metadata so the cache layer can measure staleness with ground-truth precision.

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

**Policies to implement:**
- **No cache** — baseline, always hits upstream
- **Fixed TTL** — baseline, single global TTL per tool
- **Adaptive TTL** *(our contribution)* — per-key TTL derived from observed change rate and request demand

**Planned features:** single-flight (request coalescing), stale-while-revalidate, per-request freshness constraints, Prometheus metrics.

---

### 3. Load Generator (`k6/`) 🚧

k6 scripts that simulate concurrent agent traffic against the cache gateway.

**Workloads:**
- **Hot-key stampede** — 70% traffic on 20 keys, TTL expiry triggers herd effect
- **Bursty traffic** — 200 RPS baseline, spike to 1000 RPS every 60s
- **Long-tail** — Zipf s=1.2 over 50k keys, tests cost efficiency of adaptive TTL

**Traffic model:** Zipf key distribution, open-loop constant-arrival-rate, optional workflow sessions (correlated key sequences).

---

## Evaluation Plan

For each policy × workload, report:

- p50 / p95 / p99 latency
- External API QPS (cost)
- Cache hit rate
- Staleness: age violations and version drift
- Stampede metrics: redundant refreshes avoided, max waiters per key

**Money plot:** Pareto frontier of API cost vs. staleness across policies.
