#!/bin/bash
# Run all three caching policy experiments for the portfolio_rebalancing workflow.
#
# Assumes the API simulator is already running on localhost:8001.
# Resets the simulator to row 0 before each experiment so all three
# policies see the same price sequence.
#
# Usage:
#   bash run_portfolio_experiments.sh            # default 2000 rows per experiment
#   TARGET_ROWS=1000 bash run_portfolio_experiments.sh

set -e

TARGET_ROWS=${TARGET_ROWS:-2000}

PYTHON="/home/rohtol/cse585/agent/venv/bin/python3"
GW_DIR="/home/rohtol/cse585/cache_gateway"
AGENT_DIR="/home/rohtol/cse585/agent"

GW_PID=""
AGENT_PID=""

cleanup() {
    [ -n "$GW_PID" ]    && kill "$GW_PID"    2>/dev/null || true
    [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null || true
}
trap cleanup EXIT

run_experiment() {
    local policy=$1
    local csv_file="results/port_${policy}_v1.csv"

    echo ""
    echo "========================================"
    echo "  policy : $policy"
    echo "  output : $csv_file"
    echo "  target : $TARGET_ROWS rows"
    echo "========================================"

    mkdir -p "$AGENT_DIR/results"

    # Reset simulator price playback to row 0
    curl -s -X POST http://localhost:8001/reset > /dev/null
    echo "  simulator reset to row 0"

    # Start gateway
    GW_PID=""
    (cd "$GW_DIR" && GW_POLICY=$policy "$PYTHON" main.py) &
    GW_PID=$!
    sleep 2
    echo "  gateway started (pid=$GW_PID, policy=$policy)"

    # Start agent (portfolio_rebalancing: one trial per interval, no ticker loop)
    AGENT_PID=""
    (cd "$AGENT_DIR" && AGENT_WORKFLOW=portfolio_rebalancing AGENT_OUTPUT_CSV="$csv_file" "$PYTHON" main.py) &
    AGENT_PID=$!
    echo "  agent started (pid=$AGENT_PID)"

    # Poll until TARGET_ROWS data rows collected (header line doesn't count)
    echo -n "  rows collected: "
    while true; do
        sleep 5
        if [ -f "$AGENT_DIR/$csv_file" ]; then
            total_lines=$(wc -l < "$AGENT_DIR/$csv_file")
            data_rows=$(( total_lines - 1 ))
            echo -n "${data_rows} "
            if [ "$data_rows" -ge "$TARGET_ROWS" ]; then
                echo ""
                break
            fi
        fi
    done

    kill "$GW_PID" "$AGENT_PID" 2>/dev/null || true
    wait "$GW_PID" "$AGENT_PID" 2>/dev/null || true
    GW_PID=""
    AGENT_PID=""
    echo "  experiment complete → $csv_file"
}

run_experiment "none"
run_experiment "fixed_ttl"
run_experiment "workflow_aware"

echo ""
echo "========================================"
echo "  ANALYSIS"
echo "========================================"
cd "$AGENT_DIR"
"$PYTHON" analyze.py \
    "results/port_none_v1.csv" \
    "results/port_fixed_ttl_v1.csv" \
    "results/port_workflow_aware_v1.csv"
