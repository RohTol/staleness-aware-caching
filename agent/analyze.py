"""
Analyze experiment results across the three caching policies.

Usage:
    python3 analyze.py                          # uses default filenames
    python3 analyze.py results_none.csv results_fixed_ttl.csv results_workflow_aware.csv
"""

import csv
import sys
from collections import defaultdict


def load(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def analyze(rows: list[dict], label: str) -> None:
    total = len(rows)
    if total == 0:
        print(f"\n{label}: no data")
        return

    hits        = [r for r in rows if r["hit_or_miss"] == "hit"]
    misses      = [r for r in rows if r["hit_or_miss"] == "miss"]
    bypasses    = [r for r in rows if r["hit_or_miss"] == "bypass"]
    mismatches  = [r for r in rows if r["matched"] == "False"]

    hit_rate      = len(hits) / total
    mismatch_rate = len(mismatches) / total

    latencies = [float(r["cached_latency_ms"]) for r in rows if r.get("cached_latency_ms")]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    # Mismatch breakdown by branch
    mm_by_branch: dict[str, int] = defaultdict(int)
    total_by_branch: dict[str, int] = defaultdict(int)
    for r in rows:
        total_by_branch[r["branch_taken"]] += 1
    for r in mismatches:
        mm_by_branch[r["branch_taken"]] += 1

    # Hit rate breakdown by branch
    hits_by_branch: dict[str, int] = defaultdict(int)
    for r in hits:
        hits_by_branch[r["branch_taken"]] += 1

    # Decision distribution (fresh)
    decision_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        decision_counts[r["fresh_decision"]] += 1

    print(f"\n{'='*55}")
    print(f"  {label}  (n={total})")
    print(f"{'='*55}")
    print(f"  hit rate        : {hit_rate:.1%}  ({len(hits)} hits, {len(misses)} misses, {len(bypasses)} bypasses)")
    print(f"  mismatch rate   : {mismatch_rate:.1%}  ({len(mismatches)} mismatches)")
    print(f"  avg latency     : {avg_latency:.0f}ms / trial")

    print(f"\n  mismatches by branch:")
    for branch in sorted(total_by_branch):
        n_total = total_by_branch[branch]
        n_mm    = mm_by_branch.get(branch, 0)
        n_hits  = hits_by_branch.get(branch, 0)
        print(f"    {branch:<18}  mismatches={n_mm}/{n_total} ({n_mm/n_total:.1%})  "
              f"hits={n_hits}/{n_total} ({n_hits/n_total:.1%})")

    print(f"\n  fresh decision distribution:")
    for decision, count in sorted(decision_counts.items(), key=lambda x: -x[1]):
        print(f"    {decision:<8}  {count:>4}  ({count/total:.1%})")


def compare(all_data: dict[str, list[dict]]) -> None:
    """Print a compact side-by-side comparison table."""
    print(f"\n\n{'='*55}")
    print("  SUMMARY COMPARISON")
    print(f"{'='*55}")
    print(f"  {'policy':<20}  {'hit rate':>9}  {'mismatch rate':>14}  {'mismatches':>10}  {'avg latency':>12}")
    print(f"  {'-'*20}  {'-'*9}  {'-'*14}  {'-'*10}  {'-'*12}")
    for label, rows in all_data.items():
        total = len(rows)
        if total == 0:
            continue
        hits       = sum(1 for r in rows if r["hit_or_miss"] == "hit")
        mismatches = sum(1 for r in rows if r["matched"] == "False")
        lats       = [float(r["cached_latency_ms"]) for r in rows if r.get("cached_latency_ms")]
        avg_lat    = sum(lats) / len(lats) if lats else 0.0
        print(f"  {label:<20}  {hits/total:>9.1%}  {mismatches/total:>14.1%}  {mismatches:>10}/{total}  {avg_lat:>10.0f}ms")


def main():
    files = sys.argv[1:] if len(sys.argv) > 1 else [
        "results_none.csv",
        "results_fixed_ttl.csv",
        "results_workflow_aware.csv",
    ]

    labels = {
        "results_none.csv":           "none (baseline)",
        "results_fixed_ttl.csv":      "fixed_ttl",
        "results_workflow_aware.csv": "workflow_aware",
    }

    all_data: dict[str, list[dict]] = {}
    for path in files:
        label = labels.get(path, path)
        try:
            rows = load(path)
            all_data[label] = rows
            analyze(rows, label)
        except FileNotFoundError:
            print(f"\n[skip] {path} not found")

    if len(all_data) > 1:
        compare(all_data)


if __name__ == "__main__":
    main()
