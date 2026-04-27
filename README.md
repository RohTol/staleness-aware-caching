# Staleness-Aware Caching for Agentic LLM Tool Calls

**Archit Kumar · Maaz Hussain · Divya Pothavajhyula · Rohan Tolani**

---

## Table of Contents

- [Abstract](#abstract)
- [Overview](#overview)
- [Components](#components)
  - [1. API Simulator](#1-api-simulator-api_simulator)
  - [2. Cache Gateway](#2-cache-gateway-cache_gateway)
  - [3. LangGraph Agent](#3-langgraph-agent-agent)
- [Experimental Results](#experimental-results)
  - [Workflow 1: Investment Decision](#workflow-1-investment-decision-branching-fan-out)
  - [Workflow 2: Portfolio Rebalancing](#workflow-2-portfolio-rebalancing-parallel-fan-in)
  - [Latency–Correctness Tradeoff](#latencycorrectness-tradeoff)
- [Setup](#setup)
- [How to Reproduce](#how-to-reproduce)
- [Running a Single Policy Manually](#running-a-single-policy-manually)
- [Repository Structure](#repository-structure)

---

## Abstract

Modern LLM agents solve tasks through sequences of external tool calls. Caching these results reduces latency and cost, but stale outputs can propagate through multi-step workflows and corrupt final decisions. We evaluate this problem using a dynamic simulator with price, trend, and news-sentiment APIs across two representative workflows: an investment-decision task (branching fan-out) and a portfolio-rebalancing task (parallel fan-in). We find that staleness impact is **non-uniform** — stale tool outputs near high-fanout or early decision points cause substantially more downstream errors than stale outputs near leaf nodes. We propose a **workflow-aware TTL policy** that assigns shorter TTLs to calls with more downstream dependents and to earlier workflow steps, reducing staleness-induced decision errors by ~2× over fixed-TTL baselines while retaining most of the latency benefit of caching.

---

## Overview

The project has three main components working together:

```
LangGraph Agent  →  Cache Gateway  →  API Simulator
(DAG of tool         (policy logic)    (dynamic backend)
 call nodes)

POST /v1/tools/invoke    HIT / MISS      GET /price?ticker=
{tool, args,             STALE / FRESH   GET /news_sentiment?ticker=
 workflow_step,                          GET /trend?ticker=
 downstream_deps}                        
```

The **LangGraph Agent** defines each task as a DAG of tool-call nodes. `workflow_step` and `downstream_dependents` are derived automatically from the graph structure — no manual annotation required.

The **Cache Gateway** intercepts every tool call, checks the in-memory cache, and applies one of three pluggable policies. The active policy is selected at startup via `GW_POLICY`.

The **API Simulator** mimics real dynamic APIs: values evolve via a Poisson background loop, prices replay from a CSV for reproducibility, and every response includes `version`/`last_changed_at` for ground-truth staleness tracking.

---

## Components

### 1. API Simulator (`api_simulator/`)

A FastAPI server mimicking dynamic external tool APIs. Values change continuously via a Poisson update loop; prices replay from a CSV so experiments are reproducible. Every response includes `version` and `last_changed_at` for ground-truth staleness measurement. A `/reset` endpoint restarts the price sequence from row 0 between policy runs.

**Endpoints:**
- `GET /price?ticker=<ticker>` — current stock price (~1 change per 20s)
- `GET /news_sentiment?ticker=<ticker>` — sentiment score in [-1, 1] (~1 change per 50s)
- `GET /trend?ticker=<ticker>` — 30-day moving average (~1 change per 15 min)
- `GET /health` — liveness check
- `GET /reset` — restart price replay from row 0

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
| `config.py` | All configurable knobs as `SIM_*` env vars. Change rates, latency params, error rate, rate limit. |
| `state.py` | Per-key state and background Poisson update loop. Prices use multiplicative random walk. |
| `main.py` | FastAPI app. Injects lognormal latency and 2% random 503 errors. Token-bucket rate limiter when enabled. |

**Key config vars:**

| Variable | Default | Effect |
|---|---|---|
| `SIM_PRICE_CHANGE_RATE` | `0.05` | ~1 price change per 20s |
| `SIM_SENTIMENT_CHANGE_RATE` | `0.02` | ~1 sentiment change per 50s |
| `SIM_TREND_CHANGE_RATE` | `0.001` | ~1 trend change per 15 min |
| `SIM_ERROR_RATE` | `0.02` | 2% of requests return 503 |

---

### 2. Cache Gateway (`cache_gateway/`)

An HTTP gateway on port 8002. Accepts `POST /v1/tools/invoke` with `{tool, args, workflow_step, downstream_dependents}`, checks the in-memory cache, and calls upstream on a miss. Policy is selected at startup via `GW_POLICY`.

**Request format:**
```json
{
  "tool": "price",
  "args": {"ticker": "AAPL"},
  "workflow_step": 0,
  "downstream_dependents": 3
}
```

**Response format:** same as the API simulator, plus cache metadata:
```json
{
  "tool": "price",
  "key": "AAPL",
  "value": 182.34,
  "version": 47,
  "last_changed_at": "2026-03-13T14:12:22Z",
  "cache_status": "hit",
  "ttl_s": 6.7
}
```

**Policies (selected via `GW_POLICY` env var):**
- `none` — always calls upstream, never caches. Correctness upper bound / latency lower bound.
- `fixed_ttl` — one TTL per tool type, ignores workflow position entirely. Equivalent to standard Redis caching.
- `workflow_aware` — tightens TTL at high-fanout and root positions. Our contribution.

**Workflow-Aware TTL formula:**

```
δ = log₂(1 + downstream_dependents)
ω = 1.5  if workflow_step == 0, else 1.0
TTL = clamp(base_ttl / (δ × ω),  0.2 × base_ttl,  base_ttl)
```

A call with 3 downstream dependents at the root (step=0) receives `TTL = base_ttl / (log₂(4) × 1.5) = base_ttl / 3`, so the 20s price TTL is tightened to ≈6.7s. The 0.2× floor prevents over-tightening (price never falls below 4s).

**Files:**

| File | Description |
|---|---|
| `config.py` | All knobs as `GW_*` env vars. Policy selection, per-tool TTLs, simulator URL, `workflow_aware` tuning params. |
| `cache.py` | In-memory cache keyed by `(tool, frozenset(args))`. Lazy eviction on read, hit/miss counters. |
| `policy.py` | `NoCachePolicy`, `FixedTTLPolicy`, `WorkflowAwareTTLPolicy`. To add a policy: subclass `Policy` and register in `get_policy()`. |
| `main.py` | FastAPI gateway. `GET /metrics` returns hit rate, call counts, and a TTL preview table for `workflow_aware`. |

**Key config vars:**

| Variable | Default | Effect |
|---|---|---|
| `GW_POLICY` | `none` | `none`, `fixed_ttl`, or `workflow_aware` |
| `GW_TTL_PRICE_S` | `20.0` | Base TTL for price calls |
| `GW_TTL_SENTIMENT_S` | `45.0` | Base TTL for news_sentiment calls |
| `GW_TTL_TREND_S` | `600.0` | Base TTL for trend calls |
| `GW_WA_POSITION_WEIGHT` | `1.5` | (`workflow_aware`) Extra tightening for step-0 root nodes. Set to `1.0` to disable. |
| `GW_WA_MIN_TTL_FRACTION` | `0.2` | (`workflow_aware`) Floor as a fraction of base TTL. |

---

### 3. LangGraph Agent (`agent/`)

Defines agent tasks as LangGraph DAGs and runs trials against the cache gateway. `workflow_step` and `downstream_dependents` are derived automatically from the DAG edges at invocation time — no manual annotation.

Each trial runs the workflow **twice**: once through the gateway (potentially stale) and once directly against the simulator (always fresh). A **mismatch** is recorded when the two final decisions disagree. Staleness is also measured per-call by comparing the version number from the gateway hit against the current version fetched from the simulator.

**Workflows:**
- **Investment Decision** (`investment_decision`) — branching fan-out: `fetch_price` (root, 3 deps) → conditional `fetch_news_sentiment` or `fetch_trend` → `decide`. Run across 11 tickers.
- **Portfolio Rebalancing** (`portfolio_rebalancing`) — parallel fan-in: three price fetches (AAPL: 3 deps, GOOG/NVDA: 2 deps each) → `compute_risk`/`compute_tax` → `decide`.

**Files:**

| File | Description |
|---|---|
| `config.py` | `AGENT_*` env vars: gateway URL, simulator URL, n_trials, workflow selection, output CSV path. |
| `client.py` | `call_gateway()` and `call_fresh()` — thin HTTP clients for the gateway and simulator. |
| `workflows/investment_decision.py` | Branching chain. `fetch_price` gates routing to `fetch_news_sentiment` or `fetch_trend`. |
| `workflows/portfolio_rebalancing.py` | Fan-in. Three parallel price fetches → risk/tax computation → decision. |
| `runner.py` | Trial loop. `compute_metrics()` aggregates staleness by fanout tier and mismatch rate. |
| `analyze.py` | Cross-policy comparison from CSV outputs. Produces tables and figures. |
| `thresholds.py` | Routing/decision thresholds calibrated to make stale mismatches observable. |

---

## Experimental Results

All experiments replay the same deterministic price sequence (via `/reset` between policies) with ~2000 trials per policy per workflow (~12,000 total runs). The primary metric is **decision mismatch rate**: the fraction of trials where the cached-path decision diverges from the fresh ground-truth decision.

Hit rate and mismatch rate are **orthogonal** in agentic systems — a 97% hit rate can coexist with a 6.5% decision error rate. Mismatch rate is the correct objective here.

---

### Workflow 1: Investment Decision (branching fan-out)

11 tickers; routing threshold calibrated to 0.5% so stale prices can cross the branch boundary. `fetch_price` sits at step=0 with 3 downstream dependents.

| Policy | Hit Rate | Mismatch Rate | Avg Latency |
|---|---|---|---|
| `none` (baseline) | 0.0% | **0.0%** | 280.5 ms |
| `fixed_ttl` | 79.9% | **2.7%** | 79.3 ms |
| `workflow_aware` | 49.6% | **1.2%** | 110.2 ms |

---

### Workflow 2: Portfolio Rebalancing (parallel fan-in)

3 stocks (AAPL, GOOG, NVDA); all at step=0, same change rate. AAPL has 3 downstream dependents (risk + tax + decide); GOOG and NVDA have 2 (risk + decide). Decision: rebalance any stock whose price drifted >0.5% from its reference.

| Policy | Hit Rate | Mismatch Rate | Avg Latency |
|---|---|---|---|
| `none` (baseline) | 0.0% | **0.3%** | 336.8 ms |
| `fixed_ttl` | 97.1% | **6.5%** | 89.3 ms |
| `workflow_aware` | 91.6% | **3.3%** | 110.9 ms |

---

### Latency–Correctness Tradeoff

Workflow_aware is the **only policy** that simultaneously achieves <120 ms average latency and <1.5% mismatch rate across both workflows:

| Policy | Latency (invest.) | Correctness (invest.) | Latency (portf.) | Correctness (portf.) |
|---|---|---|---|---|
| `none` | 280.5 ms | 100.0% | 336.8 ms | 99.7% |
| `fixed_ttl` | 79.3 ms | 97.3% | 89.3 ms | 93.5% |
| `workflow_aware` | 110.2 ms | **98.8%** | 110.9 ms | **96.7%** |

Fixed_ttl is 39% faster than workflow_aware but inflicts 2× more errors. Workflow_aware accepts this modest latency premium in exchange for halving the error rate.

---

## Setup

Create the shared venv the experiment scripts rely on (run once after cloning, from the repo root):

```bash
python3 -m venv agent/venv
agent/venv/bin/pip install -r agent/requirements.txt
agent/venv/bin/pip install -r cache_gateway/requirements.txt
agent/venv/bin/pip install -r api_simulator/requirements.txt
```

## How to Reproduce

```bash
# 1. Start the simulator (keep running throughout)
cd api_simulator && python3 main.py

# 2. Investment decision (11 tickers, 3 policies, ~2000 trials each)
cd .. && bash run_experiments.sh

# 3. Portfolio rebalancing (AAPL/GOOG/NVDA, 3 policies)
bash run_portfolio_experiments.sh

# 4. Analyze (both scripts run this automatically at the end)
cd agent
./venv/bin/python3 analyze.py results/results_none_v2.csv results/results_fixed_ttl_v2.csv results/results_workflow_aware_v2.csv
./venv/bin/python3 analyze.py results/port_none_v1.csv results/port_fixed_ttl_v1.csv results/port_workflow_aware_v1.csv
```

Both scripts automatically start/stop the gateway per policy, call `/reset` between policies to replay the same price sequence, and run `analyze.py` when all three policies finish.

**Note:** The repo includes pre-committed result CSVs (`_v2` / `_v1`). If you want to run fresh experiments without overwriting them, set a new suffix:
```bash
SUFFIX=v3 bash run_experiments.sh
```

**Script env vars:**

| Variable | Script | Default | Effect |
|---|---|---|---|
| `TARGET_ROWS` | both | `2000` | Trials to collect per policy before moving to the next |
| `SUFFIX` | `run_experiments.sh` | `v2` | Output filename suffix (`results_{policy}_{suffix}.csv`) |

For a faster test run:
```bash
TARGET_ROWS=500 SUFFIX=v3 bash run_experiments.sh
```

## Running a Single Policy Manually

```bash
# Terminal 1: simulator
cd api_simulator && python3 main.py

# Terminal 2: gateway with chosen policy
cd cache_gateway
GW_POLICY=workflow_aware ./venv/bin/python3 main.py  # or: none, fixed_ttl

# Terminal 3: agent
cd agent
AGENT_WORKFLOW=investment_decision AGENT_OUTPUT_CSV=results/test.csv ./venv/bin/python3 main.py
```

---

## Repository Structure

```
staleness-aware-caching/
├── api_simulator/          # Dynamic API backend (FastAPI, port 8001)
│   ├── main.py
│   ├── state.py
│   └── config.py
├── cache_gateway/          # Caching proxy with pluggable policies (FastAPI, port 8002)
│   ├── main.py
│   ├── policy.py
│   ├── cache.py
│   └── config.py
├── agent/                  # LangGraph agent, trial runner, and analysis
│   ├── workflows/
│   │   ├── investment_decision.py
│   │   └── portfolio_rebalancing.py
│   ├── runner.py
│   ├── analyze.py
│   ├── thresholds.py
│   ├── results/            # CSV outputs from experiment runs
│   └── figures/            # Generated plots
├── run_experiments.sh          # Investment decision: all 3 policies
└── run_portfolio_experiments.sh  # Portfolio rebalancing: all 3 policies
```
