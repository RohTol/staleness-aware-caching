"""
ExperimentRunner — runs trials of a workflow and collects per-call staleness metrics.

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

import csv as csv_module
import os
from dataclasses import dataclass, field
from typing import Any

from client import call_fresh
from config import settings

CSV_COLUMNS = [
    "ticker",
    "simulated_time",
    "interval_index",
    "caching_policy",
    "fresh_decision",
    "cached_decision",
    "matched",
    "branch_taken",
    "hit_or_miss",
]


@dataclass
class TrialResult:
    ticker: str
    trial_id: int
    interval_index: int        # CSV row index (= price version from simulator)
    simulated_time: str        # last_changed_at from the price response (fresh run)
    caching_policy: str        # policy name from gateway /metrics
    cached_decision: str
    fresh_decision: str
    is_correct: bool
    branch_taken: str          # branch taken in the fresh (ground-truth) run
    price_cache_status: str    # "hit", "miss", or "bypass" for the price call
    # One entry per tool call made during the cached run, enriched with staleness.
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
    ticker: str = "AAPL",
    reference_price: float = 180.0,
    caching_policy: str = "unknown",
) -> TrialResult:
    # Cached run (goes through gateway, potentially stale)
    cached_graph, cached_initial = workflow_module.build_graph(
        gateway_url, simulator_url, use_cache=True,
        ticker=ticker, reference_price=reference_price,
    )
    cached_state = cached_graph.invoke(cached_initial)

    # Enrich call log with staleness flags
    enriched_calls = [
        _check_staleness(simulator_url, c)
        for c in cached_state.get("call_log", [])
    ]

    # Price call status from cached run (first entry in call_log is always fetch_price)
    cached_calls = cached_state.get("call_log", [])
    price_call = next((c for c in cached_calls if c["tool"] == "price"), {})
    price_cache_status = price_call.get("cache_status", "unknown")

    # Fresh run (bypasses gateway, always correct — ground truth)
    fresh_graph, fresh_initial = workflow_module.build_graph(
        gateway_url, simulator_url, use_cache=False,
        ticker=ticker, reference_price=reference_price,
    )
    fresh_state = fresh_graph.invoke(fresh_initial)

    cached_decision = cached_state.get("decision", "UNKNOWN")
    fresh_decision = fresh_state.get("decision", "UNKNOWN")

    # Metadata from the fresh run's price result (canonical interval reference)
    interval_index = fresh_state.get("interval_index") or -1
    simulated_time = fresh_state.get("simulated_time") or ""
    branch_taken = fresh_state.get("branch_taken") or "unknown"

    return TrialResult(
        ticker=ticker,
        trial_id=trial_id,
        interval_index=interval_index,
        simulated_time=simulated_time,
        caching_policy=caching_policy,
        cached_decision=cached_decision,
        fresh_decision=fresh_decision,
        is_correct=cached_decision == fresh_decision,
        branch_taken=branch_taken,
        price_cache_status=price_cache_status,
        calls=enriched_calls,
    )


def write_csv_header(output_csv: str) -> None:
    """Write CSV header. Call once before the first row."""
    with open(output_csv, "w", newline="") as f:
        csv_module.DictWriter(f, fieldnames=CSV_COLUMNS).writeheader()


def write_csv_row(result: TrialResult, output_csv: str) -> None:
    """Append one result row to the CSV (opens in append mode)."""
    with open(output_csv, "a", newline="") as f:
        writer = csv_module.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writerow({
            "ticker":          result.ticker,
            "simulated_time":  result.simulated_time,
            "interval_index":  result.interval_index,
            "caching_policy":  result.caching_policy,
            "fresh_decision":  result.fresh_decision,
            "cached_decision": result.cached_decision,
            "matched":         result.is_correct,
            "branch_taken":    result.branch_taken,
            "hit_or_miss":     result.price_cache_status,
        })


def run_experiment(
    workflow_module: Any,
    n_trials: int,
    gateway_url: str = settings.gateway_url,
    simulator_url: str = settings.simulator_url,
) -> list[TrialResult]:
    """Backward-compatible batch experiment runner (no ticker parameterization)."""
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
