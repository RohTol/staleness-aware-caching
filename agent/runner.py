"""
ExperimentRunner — runs N trials of a workflow and collects per-call staleness metrics.

For each trial:
  1. Run workflow through the gateway (cached run) → decision + call_log
  2. For every cache HIT in call_log, fetch fresh version immediately from simulator
     → record is_stale = (hit_version < fresh_version)
  3. Run same workflow directly against simulator (fresh run) → ground_truth_decision
  4. Record correctness: cached_decision == ground_truth_decision

Primary metric: staleness rate at cache hit, segmented by downstream_dependents tier.
Secondary metric: correctness rate (cached decision matches ground truth).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from client import call_fresh
from config import settings


@dataclass
class TrialResult:
    trial_id: int
    cached_decision: str
    fresh_decision: str
    is_correct: bool
    # One entry per tool call made during the cached run.
    calls: list[dict] = field(default_factory=list)


def _check_staleness(simulator_url: str, call: dict) -> dict:
    """
    For a single call_log entry, fetch the current version from the simulator
    and determine whether the cached value was stale.
    Returns the entry enriched with is_stale and fresh_version.
    """
    if call["cache_status"] != "hit":
        return {**call, "is_stale": False, "fresh_version": call.get("version")}

    fresh = call_fresh(simulator_url, call["tool"], call["args"])
    hit_version = call.get("version") or 0
    fresh_version = fresh.get("version") or 0
    return {
        **call,
        "is_stale": hit_version < fresh_version,
        "fresh_version": fresh_version,
    }


def run_trial(
    trial_id: int,
    workflow_module: Any,
    gateway_url: str,
    simulator_url: str,
) -> TrialResult:
    # Cached run (goes through gateway, potentially stale)
    cached_graph, cached_initial = workflow_module.build_graph(
        gateway_url, simulator_url, use_cache=True
    )
    cached_state = cached_graph.invoke(cached_initial)

    # Enrich call log with staleness flags
    enriched_calls = [
        _check_staleness(simulator_url, c)
        for c in cached_state.get("call_log", [])
    ]

    # Fresh run (bypasses gateway, always correct — ground truth)
    fresh_graph, fresh_initial = workflow_module.build_graph(
        gateway_url, simulator_url, use_cache=False
    )
    fresh_state = fresh_graph.invoke(fresh_initial)

    cached_decision = cached_state.get("decision", "UNKNOWN")
    fresh_decision = fresh_state.get("decision", "UNKNOWN")

    return TrialResult(
        trial_id=trial_id,
        cached_decision=cached_decision,
        fresh_decision=fresh_decision,
        is_correct=cached_decision == fresh_decision,
        calls=enriched_calls,
    )


def run_experiment(
    workflow_module: Any,
    n_trials: int,
    gateway_url: str = settings.gateway_url,
    simulator_url: str = settings.simulator_url,
) -> list[TrialResult]:
    results = []
    for i in range(n_trials):
        result = run_trial(i, workflow_module, gateway_url, simulator_url)
        results.append(result)
        print(f"trial {i+1}/{n_trials}  cached={result.cached_decision}  "
              f"fresh={result.fresh_decision}  correct={result.is_correct}")
    return results


def compute_metrics(results: list[TrialResult]) -> dict:
    """
    Aggregate staleness and correctness metrics across all trials.

    Staleness by fanout tier is the primary metric:
      For each downstream_dependents value seen, report:
        - hit_count, stale_hit_count, staleness_rate
    """
    total = len(results)
    correct = sum(r.is_correct for r in results)

    all_calls = [c for r in results for c in r.calls]
    hits = [c for c in all_calls if c["cache_status"] == "hit"]

    # Staleness rate by downstream_dependents tier
    tiers: dict[int, dict] = {}
    for c in hits:
        deps = c["downstream_dependents"]
        if deps not in tiers:
            tiers[deps] = {"hits": 0, "stale": 0}
        tiers[deps]["hits"] += 1
        if c.get("is_stale"):
            tiers[deps]["stale"] += 1

    staleness_by_tier = {
        deps: {
            "hits": v["hits"],
            "stale_hits": v["stale"],
            "staleness_rate": round(v["stale"] / v["hits"], 3) if v["hits"] else 0.0,
        }
        for deps, v in sorted(tiers.items())
    }

    total_calls = len(all_calls)
    total_hits = len(hits)

    return {
        "n_trials": total,
        "correctness_rate": round(correct / total, 3) if total else 0.0,
        "hit_rate": round(total_hits / total_calls, 3) if total_calls else 0.0,
        "total_api_calls": total_calls - total_hits,
        "staleness_by_downstream_dependents": staleness_by_tier,
    }
