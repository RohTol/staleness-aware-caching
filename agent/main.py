"""
Entry point — continuous experiment runner.

Runs the investment_decision workflow for every ticker every 20 seconds and
appends results to a CSV file.  The gateway policy (none / fixed_ttl /
workflow_aware) is read from GW_POLICY on the gateway side; this script just
queries /metrics to record whichever policy is active.

Usage:
    # Run indefinitely, all tickers, current gateway policy
    python main.py

    # Stop after 50 total trials (across all tickers)
    AGENT_N_TRIALS=50 python main.py

    # Custom output file
    AGENT_OUTPUT_CSV=run_fixed_ttl.csv python main.py

    # Legacy: batch mode for a single workflow (uses n_trials as a count)
    AGENT_WORKFLOW=portfolio_rebalancing AGENT_N_TRIALS=20 python main.py

The gateway policy is set on the gateway side (GW_POLICY env var), not here.
Run once per policy and compare the output CSVs.
"""

import json
import os
import sys
import time

import httpx

from config import settings
from runner import (
    compute_metrics,
    run_experiment,
    run_trial,
    write_csv_header,
    write_csv_row,
)
from thresholds import TICKER_REFERENCE_PRICES, TICKERS

INTERVAL_SECONDS = settings.interval_seconds


def _load_workflow(name: str):
    if name == "investment_decision":
        from workflows import investment_decision
        return investment_decision
    if name == "portfolio_rebalancing":
        from workflows import portfolio_rebalancing
        return portfolio_rebalancing
    print(f"Unknown workflow: {name}. Choose from: investment_decision, portfolio_rebalancing",
          file=sys.stderr)
    sys.exit(1)


def _get_gateway_policy(gateway_url: str) -> str:
    """Fetch the active policy name from the gateway /metrics endpoint."""
    try:
        r = httpx.get(f"{gateway_url}/metrics", timeout=5.0)
        r.raise_for_status()
        return r.json().get("policy", "unknown")
    except Exception as e:
        print(f"  [warn] could not reach gateway /metrics: {e}")
        return "unknown"


def run_continuously(workflow_module, gateway_url: str, simulator_url: str,
                     output_csv: str, max_trials: int = 0) -> None:
    """
    Loop forever (or until max_trials total trials have been recorded).

    Each iteration:
      1. Refresh the policy name from the gateway.
      2. Run one trial per ticker.
      3. Write each result to the CSV immediately.
      4. Sleep the remainder of the 20-second interval.
    """
    is_new_file = not os.path.exists(output_csv)
    if is_new_file:
        write_csv_header(output_csv)

    trial_id = 0
    interval_num = 0

    while True:
        if max_trials > 0 and trial_id >= max_trials:
            print(f"\nReached max_trials={max_trials}. Stopping.")
            break

        interval_start = time.time()
        interval_num += 1
        policy = _get_gateway_policy(gateway_url)
        print(f"\n--- interval {interval_num} | policy={policy} ---")

        for ticker in TICKERS:
            if max_trials > 0 and trial_id >= max_trials:
                break

            ref_price = TICKER_REFERENCE_PRICES.get(ticker, 180.0)
            try:
                result = run_trial(
                    trial_id=trial_id,
                    workflow_module=workflow_module,
                    gateway_url=gateway_url,
                    simulator_url=simulator_url,
                    ticker=ticker,
                    reference_price=ref_price,
                    caching_policy=policy,
                )
                write_csv_row(result, output_csv)
                trial_id += 1
                match_str = "✓" if result.is_correct else "✗"
                print(
                    f"  {ticker:<5} idx={result.interval_index:>4} "
                    f"branch={result.branch_taken:<15} "
                    f"fresh={result.fresh_decision:<5} "
                    f"cached={result.cached_decision:<5} "
                    f"{match_str}  price={result.price_cache_status}"
                )
            except Exception as e:
                print(f"  {ticker:<5} ERROR: {e}")

        elapsed = time.time() - interval_start
        sleep_time = max(0.0, INTERVAL_SECONDS - elapsed)
        print(f"  round took {elapsed:.1f}s, sleeping {sleep_time:.1f}s → {output_csv}")
        if sleep_time > 0:
            time.sleep(sleep_time)


def main():
    workflow_module = _load_workflow(settings.workflow)

    print(f"workflow   : {settings.workflow}")
    print(f"n_trials   : {settings.n_trials} (0 = unlimited)")
    print(f"gateway    : {settings.gateway_url}")
    print(f"simulator  : {settings.simulator_url}")
    print(f"output csv : {settings.output_csv}")

    if settings.workflow == "investment_decision":
        print(f"tickers    : {TICKERS}")
        print(f"ref prices : { {t: TICKER_REFERENCE_PRICES[t] for t in TICKERS} }")
        print()
        run_continuously(
            workflow_module,
            gateway_url=settings.gateway_url,
            simulator_url=settings.simulator_url,
            output_csv=settings.output_csv,
            max_trials=settings.n_trials,
        )
    else:
        # Legacy batch mode for portfolio_rebalancing (or any other workflow)
        if settings.n_trials == 0:
            print("Set AGENT_N_TRIALS to a positive number for batch mode.", file=sys.stderr)
            sys.exit(1)
        print()
        results = run_experiment(
            workflow_module,
            n_trials=settings.n_trials,
            gateway_url=settings.gateway_url,
            simulator_url=settings.simulator_url,
        )
        metrics = compute_metrics(results)
        print()
        print("=== metrics ===")
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
