# Staleness-Aware Caching for Agentic LLM Tool Calls

**Archit Kumar · Maaz Hussain · Divya Pothavajhyula · Rohan Tolani**
*Department of Computer Science and Engineering, University of Michigan*

> Full paper: [`CSE_585_Final_Paper.pdf`](CSE_585_Final_Paper.pdf)

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
{tool, args,             STALE / FRESH   GET /weather?city=
 workflow_step,                          GET /trend?ticker=
 downstream_deps}                        GET /news_sentiment?ticker=
```

The **LangGraph Agent** defines each task as a DAG of tool-call nodes. `workflow_step` and `downstream_dependents` are derived automatically from the graph structure — no manual annotation required.

The **Cache Gateway** intercepts every tool call, checks the in-memory cache, and applies one of three pluggable policies. The active policy is selected at startup via `GW_POLICY`.

The **API Simulator** mimics real dynamic APIs: values evolve via a Poisson background loop, prices replay from a CSV for reproducibility, and every response includes `version`/`last_changed_at` for ground-truth staleness tracking.

---

## Contributions

1. **Problem identification** — why caching in agentic workflows differs from conventional caching: stale values can change which branch the agent takes, not just which number it returns.
2. **Simulation infrastructure** — a reproducible end-to-end testbed with two structurally distinct financial workflows and a deterministic price-replay mechanism.
3. **Empirical finding** — high-fanout nodes cause disproportionately more decision errors when stale; the `news_sentiment` branch of the investment-decision workflow shows a 7.3× higher mismatch rate than the `trend` branch under fixed TTL.
4. **Workflow-aware TTL policy** — a formula that tightens TTLs based on `downstream_dependents` and `workflow_step`, reducing decision mismatches ~2× across two structurally different workflows while remaining 2.5× faster than no-cache.

---

## Components

### 1. API Simulator (`api_simulator/`)

A FastAPI server mimicking dynamic external tool APIs. Values change continuously via a Poisson update loop; prices replay from a CSV so experiments are reproducible. Every response includes `version` and `last_changed_at` for ground-truth staleness measurement. A `/reset` endpoint restarts the price sequence from row 0 between policy runs.

**Endpoints:**
- `GET /price?ticker=<ticker>` — current stock price (~1 change per 20s)
- `GET /news_sentiment?ticker=<ticker>` — sentiment score in [-1, 1] (~1 change per 50s)
- `GET /trend?ticker=<ticker>` — 30-day moving average (~1 change per 15 min)
- `GET /weather?city=<city>` — current temperature (~1 change per 3 min)
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
| `state.py` | Per-key state and background Poisson update loop. Prices use multiplicative random walk; weather uses additive drift. |
| `main.py` | FastAPI app. Injects lognormal latency and 2% random 503 errors. Token-bucket rate limiter when enabled. |

**Key config vars:**

| Variable | Default | Effect |
|---|---|---|
| `SIM_PRICE_CHANGE_RATE` | `0.05` | ~1 price change per 20s |
| `SIM_SENTIMENT_CHANGE_RATE` | `0.02` | ~1 sentiment change per 50s |
| `SIM_WEATHER_CHANGE_RATE` | `0.005` | ~1 weather change per 3 min |
| `SIM_TREND_CHANGE_RATE` | `0.001` | ~1 trend change per 15 min |
| `SIM_ERROR_RATE` | `0.02` | 2% of requests return 503 |

**Run it:**
```bash
cd api_simulator
pip install -r requirements.txt
python3 main.py
```

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

**Run it:**
```bash
cd cache_gateway
pip install -r requirements.txt

GW_POLICY=none python3 main.py          # no-cache baseline
GW_POLICY=fixed_ttl python3 main.py     # standard baseline
GW_POLICY=workflow_aware python3 main.py  # our contribution

# Check TTL preview and hit metrics
curl http://localhost:8002/metrics | python3 -m json.tool
```

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

**Run it:**
```bash
cd agent
pip install -r requirements.txt

# Default: investment_decision, 100 trials
python3 main.py

# Portfolio rebalancing
AGENT_WORKFLOW=portfolio_rebalancing AGENT_N_TRIALS=50 python3 main.py

# Save results to CSV
AGENT_OUTPUT_CSV=results/test.csv python3 main.py
```

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

**Key findings:**

**1. 56% fewer decision errors** — workflow_aware cuts the mismatch rate from 2.7% → 1.2% while remaining 2.5× faster than no-cache.

**2. Wrong-branch routing errors eliminated entirely.** Workflow_aware tightens the price TTL from 20s → 6.7s at the root node. Under fixed_ttl, 27.3% of mismatches are wrong-branch errors where a stale price routes the agent to the wrong branch and suppresses the correct downstream call. Workflow_aware reduces this to zero.

| Mismatch type | `fixed_ttl` | `workflow_aware` |
|---|---|---|
| Wrong-branch (stale price → wrong routing) | 15/55 (27.3%) | **0/24 (0.0%)** |
| Same-branch (stale leaf → wrong decision) | 40/55 (72.7%) | 24/24 (100%) |

**3. Branch-level breakdown:**

| Branch | `fixed_ttl` mismatch rate | `workflow_aware` mismatch rate |
|---|---|---|
| `news_sentiment` | 11.9% (26/219) | 0.5% (1/215) — **96% reduction** |
| `trend` | 1.6% (29/1785) | 1.3% (23/1793) — **19% reduction** |

The 7.3× disparity between branches under fixed_ttl is direct evidence that staleness impact depends on DAG position, not just change rate.

---

### Workflow 2: Portfolio Rebalancing (parallel fan-in)

3 stocks (AAPL, GOOG, NVDA); all at step=0, same change rate. AAPL has 3 downstream dependents (risk + tax + decide); GOOG and NVDA have 2 (risk + decide). Decision: rebalance any stock whose price drifted >0.5% from its reference.

| Policy | Hit Rate | Mismatch Rate | Avg Latency |
|---|---|---|---|
| `none` (baseline) | 0.0% | **0.3%** | 336.8 ms |
| `fixed_ttl` | 97.1% | **6.5%** | 89.3 ms |
| `workflow_aware` | 91.6% | **3.3%** | 110.9 ms |

**Key findings:**

**1. 50% fewer decision errors** — consistent with the investment_decision result despite a completely different DAG shape.

**2. Fan-in amplification.** The 6.5% fixed_ttl error rate (vs. 2.7% for investment_decision) shows how stale prices from any of three independent nodes compound into errors in the single shared decision. Workflow_aware concentrates tightening on AAPL (3 deps) more than GOOG/NVDA (2 deps each), suppressing this amplification.

**3. Hit rate ≠ correctness.** Fixed_ttl achieves 97.1% hit rate here yet produces the highest mismatch rate of any policy. A naive operator maximizing hit rate would select the worst configuration for correctness.

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

### How to Reproduce

```bash
# 1. Start the simulator (keep running throughout)
cd api_simulator && python3 main.py

# 2. Investment decision (11 tickers, 3 policies, ~2000 trials each)
cd .. && bash run_experiments.sh

# 3. Portfolio rebalancing (AAPL/GOOG/NVDA, 3 policies)
bash run_portfolio_experiments.sh

# 4. Analyze
cd agent
./venv/bin/python3 analyze.py results/results_none_v2.csv results/results_fixed_ttl_v2.csv results/results_workflow_aware_v2.csv
./venv/bin/python3 analyze.py results/port_none_v1.csv results/port_fixed_ttl_v1.csv results/port_workflow_aware_v1.csv
```

For a faster test run:
```bash
TARGET_ROWS=500 bash run_experiments.sh
```

The experiment scripts start/stop the gateway automatically per policy and call `/reset` between policies to replay the same price sequence.

---

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

## Discussion and Limitations

Workflow-aware caching is most impactful for agents that repeatedly make sequential calls to dynamic external APIs — financial assistants querying live market data, travel planners fetching real-time weather, customer-support agents retrieving account details, and research agents pulling recent news.

**Limitations (from the paper):**

- **Deterministic workflows.** Agents follow fixed decision rules rather than calling a real LLM. Real LLM agents introduce reasoning variability that could make staleness impact higher or lower than measured here.
- **Heuristic formula.** The dependency factor and position weight are reasonable proxies for staleness impact but are not proven optimal for all workflow shapes or data sources.
- **Static DAG assumption.** The policy requires the workflow DAG to be known at invocation time. Agents that generate plans dynamically cannot provide `downstream_dependents` without additional infrastructure.

---

## Future Work

- **Real LLM integration** — connect to an actual LLM (Claude, GPT-4) to observe how data staleness interacts with agentic reasoning and whether outdated context suppresses or compounds hallucinations.
- **Adaptive TTL learning** — replace the hand-tuned formula with an online learner that observes live DAG traces, data volatility, and mismatch feedback to adjust TTLs automatically without manual intervention.
- **Multi-agent cache sharing** — characterize how staleness propagates laterally across agents sharing a cache, and whether per-agent TTL policies are needed to prevent one agent's stale hit from corrupting another's correctness.
- **Staleness budget formalization** — given a tolerable mismatch rate, allocate TTLs optimally across the DAG as a constrained optimization problem (LP or bandit methods).

---

## Repository Structure

```
cse-585-project/
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
├── run_portfolio_experiments.sh  # Portfolio rebalancing: all 3 policies
└── CSE_585_Final_Paper.pdf     # Full paper
```
