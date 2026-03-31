"""
Entry point.

Usage:
    # Investment decision, 100 trials, workflow-aware policy running on gateway
    AGENT_WORKFLOW=investment_decision AGENT_N_TRIALS=100 python main.py

    # Portfolio rebalancing
    AGENT_WORKFLOW=portfolio_rebalancing AGENT_N_TRIALS=50 python main.py

The gateway policy is set on the gateway side (GW_POLICY env var), not here.
Run experiments once per policy, compare the metrics output.
"""

import json
import sys

from config import settings
from runner import compute_metrics, run_experiment

WORKFLOWS = {
    "investment_decision": None,
    "portfolio_rebalancing": None,
}


def _load_workflow(name: str):
    if name == "investment_decision":
        from workflows import investment_decision
        return investment_decision
    if name == "portfolio_rebalancing":
        from workflows import portfolio_rebalancing
        return portfolio_rebalancing
    print(f"Unknown workflow: {name}. Choose from: {list(WORKFLOWS)}", file=sys.stderr)
    sys.exit(1)


def main():
    workflow_module = _load_workflow(settings.workflow)

    print(f"workflow     : {settings.workflow}")
    print(f"n_trials     : {settings.n_trials}")
    print(f"gateway      : {settings.gateway_url}")
    print(f"simulator    : {settings.simulator_url}")
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
