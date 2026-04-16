# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CSE585 research project: **workflow-aware TTL caching for LangGraph agentic tool calls**. The central finding is that staleness impact is non-uniform across a workflow DAG — high-fanout nodes cause disproportionately more decision errors when stale. The `workflow_aware` policy exploits this by tightening TTLs at high-fanout positions.

## Running Experiments

All three components must run concurrently. The shared Python venv lives at `agent/venv/`.

```bash
# 1. Start API simulator (keep running throughout all experiments)
cd api_simulator && python3 main.py

# 2. Run investment_decision experiments (all 3 policies sequentially)
bash run_experiments.sh                    # ~2000 trials per policy
TARGET_ROWS=500 bash run_experiments.sh    # faster run for testing

# 3. Run portfolio_rebalancing experiments
bash run_portfolio_experiments.sh

# 4. Analyze results
cd agent
./venv/bin/python3 analyze.py results/results_none_v2.csv results/results_fixed_ttl_v2.csv results/results_workflow_aware_v2.csv
./venv/bin/python3 analyze.py results/port_none_v1.csv results/port_fixed_ttl_v1.csv results/port_workflow_aware_v1.csv
```

The experiment scripts start/stop the gateway automatically per policy. They require the simulator to already be running on `localhost:8001` and call `/reset` between policies to replay the same price sequence.

### Running a single policy manually

```bash
# Terminal 1: simulator
cd api_simulator && python3 main.py

# Terminal 2: gateway with chosen policy
cd cache_gateway && GW_POLICY=workflow_aware ./venv/bin/python3 main.py   # or: none, fixed_ttl

# Terminal 3: agent
cd agent && AGENT_WORKFLOW=investment_decision AGENT_OUTPUT_CSV=results/test.csv ./venv/bin/python3 main.py
```

## Architecture

```
LangGraph Agent  →  Cache Gateway (port 8002)  →  API Simulator (port 8001)
agent/               cache_gateway/                api_simulator/
```

### API Simulator (`api_simulator/`)

FastAPI server serving four tools: `price`, `trend`, `weather`, `news_sentiment`. Values update via a Poisson background loop; prices use a multiplicative random walk, weather uses an additive drift. Every response includes `version` and `last_changed_at` for ground-truth staleness measurement. Price data is replayed from a CSV (not random) so experiments are reproducible — `/reset` restarts from row 0.

Key files: `state.py` (value update loop), `main.py` (FastAPI routes + latency injection), `config.py` (all knobs as `SIM_*` env vars).

### Cache Gateway (`cache_gateway/`)

FastAPI gateway on port 8002. Accepts `POST /v1/tools/invoke` with `{tool, args, workflow_step, downstream_dependents}`, checks the in-memory cache, and calls upstream on a miss. Policy is selected at startup via `GW_POLICY`.

Key files:
- `policy.py` — three policy classes (`NoCachePolicy`, `FixedTTLPolicy`, `WorkflowAwareTTLPolicy`). To add a policy, subclass `Policy` and register in `get_policy()`.
- `cache.py` — in-memory store keyed by `(tool, frozenset(args))`, lazy eviction on read.
- `config.py` — all knobs as `GW_*` env vars including per-tool base TTLs and `workflow_aware` tuning params.

`WorkflowAwareTTLPolicy` formula:
```
dep_factor     = log2(1 + downstream_dependents)
position_boost = GW_WA_POSITION_WEIGHT  if workflow_step == 0 else 1.0
adjusted_ttl   = base_ttl / (dep_factor * position_boost)
final_ttl      = clamp(adjusted_ttl, GW_WA_MIN_TTL_FRACTION * base_ttl, base_ttl)
```

### Agent (`agent/`)

Defines workflows as LangGraph DAGs and runs trials. `workflow_step` and `downstream_dependents` are derived statically from DAG edges — not manually annotated. Each trial runs the workflow twice: once through the gateway and once directly against the simulator (ground truth). Staleness is detected by comparing version numbers.

Key files:
- `workflows/investment_decision.py` — branching chain: `fetch_price` → conditional `fetch_news_sentiment` or `fetch_trend` → decide.
- `workflows/portfolio_rebalancing.py` — fan-in: three parallel price fetches → `compute_risk`/`compute_tax` → decide.
- `runner.py` — trial loop and metrics aggregation (`staleness_by_downstream_dependents`, mismatch rate).
- `analyze.py` — cross-policy comparison from CSV outputs.
- `thresholds.py` — routing/decision thresholds calibrated to make stale mismatches observable.

## Key Config Variables

| Component | Var | Default | Effect |
|---|---|---|---|
| simulator | `SIM_PRICE_CHANGE_RATE` | `0.05` | ~1 price change/20s |
| gateway | `GW_POLICY` | `none` | `none`, `fixed_ttl`, `workflow_aware` |
| gateway | `GW_WA_POSITION_WEIGHT` | `1.5` | Extra TTL tightening for step-0 (root) nodes |
| gateway | `GW_WA_MIN_TTL_FRACTION` | `0.2` | Floor: prevents over-tightening (e.g. price never < 4s) |
| agent | `AGENT_WORKFLOW` | `investment_decision` | `investment_decision` or `portfolio_rebalancing` |
| agent | `AGENT_OUTPUT_CSV` | — | Path for per-trial CSV output |

## Results Location

`agent/results/` — CSV files named `results_{policy}_{suffix}.csv` (investment decision) and `port_{policy}_v1.csv` (portfolio). `agent/figures/` — generated plots.
