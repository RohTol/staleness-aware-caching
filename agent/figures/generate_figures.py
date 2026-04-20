"""
Generate all poster figures for CSE 585 project.

Usage:
    python3 agent/figures/generate_figures.py

Writes 4 PNGs to agent/figures/output/:
    hero_mismatch.png        — grouped bar: mismatch rate by policy × workflow
    latency_tradeoff.png     — scatter: latency vs. correctness
    hit_rate_disconnect.png  — scatter: hit rate vs. mismatch rate
    branch_breakdown.png     — grouped bar: per-branch mismatch for investment workflow
"""

import csv
import os
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
RESULTS_DIR = Path(__file__).parent.parent / "results"
OUTPUT_DIR  = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

INV_FILES = {
    "No Cache":        RESULTS_DIR / "results_none_v2.csv",
    "Fixed TTL":       RESULTS_DIR / "results_fixed_ttl_v2.csv",
    "Workflow-Aware":  RESULTS_DIR / "results_workflow_aware_v2.csv",
}
PORT_FILES = {
    "No Cache":        RESULTS_DIR / "port_none_v1.csv",
    "Fixed TTL":       RESULTS_DIR / "port_fixed_ttl_v1.csv",
    "Workflow-Aware":  RESULTS_DIR / "port_workflow_aware_v1.csv",
}

# ---------------------------------------------------------------------------
# University of Michigan palette
# ---------------------------------------------------------------------------
UM_BLUE  = "#00274C"
UM_MAIZE = "#FFCB05"
GRAY     = "#9EA2A2"
RED_ACCENT = "#CC0000"

# Policy colors — none (gray), fixed_ttl (maize), workflow_aware (blue)
POLICY_COLORS = {
    "No Cache":       GRAY,
    "Fixed TTL":      UM_MAIZE,
    "Workflow-Aware": UM_BLUE,
}

POLICY_ORDER = ["No Cache", "Fixed TTL", "Workflow-Aware"]

plt.rcParams.update({
    "font.family":  "DejaVu Sans",
    "font.size":    13,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.labelweight": "bold",
})


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------
def load(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def stats(rows: list[dict]) -> dict:
    total = len(rows)
    hits       = sum(1 for r in rows if r["hit_or_miss"] == "hit")
    mismatches = sum(1 for r in rows if r["matched"] == "False")
    lats       = [float(r["cached_latency_ms"]) for r in rows if r.get("cached_latency_ms")]
    avg_lat    = sum(lats) / len(lats) if lats else 0.0
    return {
        "total":          total,
        "hit_rate":       hits / total,
        "mismatch_rate":  mismatches / total,
        "correctness":    1 - mismatches / total,
        "avg_latency":    avg_lat,
    }


def branch_mismatch(rows: list[dict]) -> dict[str, dict]:
    """Return per-branch {total, mismatches, mismatch_rate} for investment workflow."""
    total_by   = defaultdict(int)
    mm_by      = defaultdict(int)
    for r in rows:
        b = r["branch_taken"]
        total_by[b] += 1
        if r["matched"] == "False":
            mm_by[b] += 1
    return {
        b: {"total": total_by[b], "mismatches": mm_by[b],
            "mismatch_rate": mm_by[b] / total_by[b]}
        for b in total_by
    }


# ---------------------------------------------------------------------------
# Load all data
# ---------------------------------------------------------------------------
inv_data  = {label: load(path) for label, path in INV_FILES.items()}
port_data = {label: load(path) for label, path in PORT_FILES.items()}

inv_stats  = {label: stats(rows) for label, rows in inv_data.items()}
port_stats = {label: stats(rows) for label, rows in port_data.items()}


# ===========================================================================
# Figure 1 — Hero: Mismatch Rate Comparison
# ===========================================================================
def fig_hero_mismatch():
    fig, ax = plt.subplots(figsize=(11, 6.5))

    x         = np.array([0.0, 1.0])          # two workflow groups
    n_bars    = len(POLICY_ORDER)
    bar_w     = 0.22
    offsets   = np.linspace(-(n_bars - 1) / 2 * bar_w,
                             (n_bars - 1) / 2 * bar_w, n_bars)

    datasets = [inv_stats, port_stats]
    labels   = ["Investment Decision", "Portfolio Rebalancing"]

    for i, policy in enumerate(POLICY_ORDER):
        vals = [ds[policy]["mismatch_rate"] * 100 for ds in datasets]
        bars = ax.bar(x + offsets[i], vals, bar_w,
                      color=POLICY_COLORS[policy],
                      edgecolor="white", linewidth=1.2,
                      label=policy, zorder=3)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.08,
                    f"{val:.1f}%",
                    ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=14, fontweight="bold")
    ax.set_ylabel("Decision Mismatch Rate (%)", fontsize=14)
    ax.set_ylim(0, max(port_stats["Fixed TTL"]["mismatch_rate"] * 100 * 1.2, 8))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}%"))
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_title("Workflow-Aware TTL Reduces Decision Errors by ~2×",
                 fontsize=16, fontweight="bold", pad=14)

    legend = ax.legend(title="Caching Policy", fontsize=12, title_fontsize=12,
                       framealpha=0.9, loc="upper left")
    legend.get_frame().set_edgecolor(GRAY)

    fig.tight_layout()
    out = OUTPUT_DIR / "hero_mismatch.png"
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"  saved: {out}")
    plt.close(fig)


# ===========================================================================
# Figure 2 — Latency-Correctness Tradeoff
# ===========================================================================
def fig_latency_tradeoff():
    fig, ax = plt.subplots(figsize=(7.5, 5.5))

    markers  = {"Investment Decision": "o", "Portfolio Rebalancing": "s"}
    wf_data  = {"Investment Decision": inv_stats, "Portfolio Rebalancing": port_stats}
    offsets_map = {
        # (workflow, policy): (dx, dy) for label nudge
        ("Investment Decision",  "No Cache"):       (-4,  0.05),
        ("Investment Decision",  "Fixed TTL"):      ( 4,  0.05),
        ("Investment Decision",  "Workflow-Aware"): ( 4, -0.07),
        ("Portfolio Rebalancing","No Cache"):        (-4,  0.05),
        ("Portfolio Rebalancing","Fixed TTL"):       ( 4, -0.07),
        ("Portfolio Rebalancing","Workflow-Aware"):  ( 4,  0.05),
    }

    for wf_label, ds in wf_data.items():
        for policy in POLICY_ORDER:
            lat  = ds[policy]["avg_latency"]
            corr = ds[policy]["correctness"] * 100
            ax.scatter(lat, corr,
                       marker=markers[wf_label],
                       s=140, color=POLICY_COLORS[policy],
                       edgecolors=UM_BLUE, linewidths=0.8, zorder=5)
            dx, dy = offsets_map.get((wf_label, policy), (4, 0.04))
            ha = "left" if dx >= 0 else "right"
            short = policy.replace("Workflow-Aware", "WF-Aware")
            ax.annotate(f"{short}\n({wf_label[:3]}...)",
                        xy=(lat, corr), xytext=(dx, dy),
                        textcoords="offset points",
                        fontsize=9, color=UM_BLUE, ha=ha)

    # Legend: workflows (shape) and policies (color)
    shape_handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=GRAY,
                   markeredgecolor=UM_BLUE, markersize=9, label="Investment Decision"),
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor=GRAY,
                   markeredgecolor=UM_BLUE, markersize=9, label="Portfolio Rebalancing"),
    ]
    color_handles = [
        mpatches.Patch(color=POLICY_COLORS[p], label=p) for p in POLICY_ORDER
    ]
    all_handles = shape_handles + [plt.Line2D([0],[0],color="none")] + color_handles
    ax.legend(handles=all_handles, loc="lower right", fontsize=9,
              title="● Investment  ■ Portfolio  |  color = Policy")

    ax.set_xlabel("Avg Latency per Trial (ms)", fontsize=13)
    ax.set_ylabel("Decision Correctness (%)",   fontsize=13)
    ax.set_title("Latency–Correctness Tradeoff", fontsize=14, fontweight="bold", pad=10)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}%"))

    ax.grid(linestyle="--", alpha=0.35)
    fig.tight_layout()
    out = OUTPUT_DIR / "latency_tradeoff.png"
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"  saved: {out}")
    plt.close(fig)


# ===========================================================================
# Figure 3 — Hit Rate ≠ Correctness
# ===========================================================================
def fig_hit_rate_disconnect():
    fig, ax = plt.subplots(figsize=(7.5, 5.5))

    markers = {"Investment Decision": "o", "Portfolio Rebalancing": "s"}
    wf_data = {"Investment Decision": inv_stats, "Portfolio Rebalancing": port_stats}
    label_nudge = {
        ("Investment Decision",  "No Cache"):        (5,  2),
        ("Investment Decision",  "Fixed TTL"):        (5, -3),
        ("Investment Decision",  "Workflow-Aware"):   (5,  2),
        ("Portfolio Rebalancing","No Cache"):          (5, -3),
        ("Portfolio Rebalancing","Fixed TTL"):         (5,  2),
        ("Portfolio Rebalancing","Workflow-Aware"):    (5, -3),
    }

    for wf_label, ds in wf_data.items():
        for policy in POLICY_ORDER:
            hr  = ds[policy]["hit_rate"] * 100
            mm  = ds[policy]["mismatch_rate"] * 100
            sc  = ax.scatter(hr, mm,
                             marker=markers[wf_label],
                             s=140, color=POLICY_COLORS[policy],
                             edgecolors=UM_BLUE, linewidths=0.8, zorder=5)
            dx, dy = label_nudge.get((wf_label, policy), (5, 2))
            short = policy.replace("Workflow-Aware", "WF-Aware")
            ax.annotate(f"{short}\n({wf_label[:4]}...)",
                        xy=(hr, mm),
                        xytext=(dx, dy), textcoords="offset points",
                        fontsize=9, color=UM_BLUE)

    ax.set_xlabel("Cache Hit Rate (%)",           fontsize=13)
    ax.set_ylabel("Decision Mismatch Rate (%)",   fontsize=13)
    ax.set_title("Hit Rate Is a Poor Proxy for Correctness",
                 fontsize=14, fontweight="bold", pad=10)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}%"))

    shape_handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=GRAY,
                   markeredgecolor=UM_BLUE, markersize=9, label="Investment Decision"),
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor=GRAY,
                   markeredgecolor=UM_BLUE, markersize=9, label="Portfolio Rebalancing"),
    ]
    color_handles = [
        mpatches.Patch(color=POLICY_COLORS[p], label=p) for p in POLICY_ORDER
    ]
    leg1 = ax.legend(handles=shape_handles, loc="upper left",  fontsize=9, title="Workflow")
    ax.add_artist(leg1)
    ax.legend(handles=color_handles, loc="lower right", fontsize=9, title="Policy")

    ax.grid(linestyle="--", alpha=0.35)
    fig.tight_layout()
    out = OUTPUT_DIR / "hit_rate_disconnect.png"
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"  saved: {out}")
    plt.close(fig)


# ===========================================================================
# Figure 4 — Branch-Level Breakdown (investment decision only)
# ===========================================================================
def error_type_breakdown(rows: list[dict]) -> dict:
    """Return counts of wrong-branch vs same-branch mismatches."""
    wrong_branch = sum(
        1 for r in rows
        if r["matched"] == "False" and r["cached_branch_taken"] != r["branch_taken"]
    )
    same_branch = sum(
        1 for r in rows
        if r["matched"] == "False" and r["cached_branch_taken"] == r["branch_taken"]
    )
    total = len(rows)
    return {
        "wrong_branch":      wrong_branch,
        "same_branch":       same_branch,
        "wrong_branch_rate": wrong_branch / total * 100,
        "same_branch_rate":  same_branch  / total * 100,
    }


def fig_branch_breakdown():
    fixed_rows = inv_data["Fixed TTL"]
    aware_rows = inv_data["Workflow-Aware"]

    fixed_et = error_type_breakdown(fixed_rows)
    aware_et = error_type_breakdown(aware_rows)

    policies      = ["Fixed TTL", "Workflow-Aware"]
    wrong_vals    = [fixed_et["wrong_branch_rate"], aware_et["wrong_branch_rate"]]
    same_vals     = [fixed_et["same_branch_rate"],  aware_et["same_branch_rate"]]
    colors_wrong  = [UM_MAIZE, UM_MAIZE]
    colors_same   = [UM_BLUE,  UM_BLUE]

    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    x     = np.array([0.0, 1.0])
    bar_w = 0.45

    b_wrong = ax.bar(x, wrong_vals, bar_w,
                     color=RED_ACCENT, edgecolor="white", linewidth=1.2,
                     label="Wrong-branch routing", zorder=3)
    b_same  = ax.bar(x, same_vals, bar_w,
                     bottom=wrong_vals,
                     color=UM_MAIZE, edgecolor="white", linewidth=1.2,
                     label="Same-branch wrong decision", zorder=3)

    # label each segment
    for bar, val in zip(b_wrong, wrong_vals):
        if val > 0.05:
            ax.text(bar.get_x() + bar.get_width() / 2,
                    val / 2,
                    f"{val:.1f}%",
                    ha="center", va="center", fontsize=11, fontweight="bold", color="white")

    for bar, bot, val in zip(b_same, wrong_vals, same_vals):
        if val > 0.05:
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bot + val / 2,
                    f"{val:.1f}%",
                    ha="center", va="center", fontsize=11, fontweight="bold", color=UM_BLUE)

    # total mismatch label on top
    for i, (w, s) in enumerate(zip(wrong_vals, same_vals)):
        ax.text(x[i], w + s + 0.1, f"{w+s:.1f}%",
                ha="center", va="bottom", fontsize=12, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(policies, fontsize=14, fontweight="bold")
    ax.set_ylabel("Mismatch Rate (%)", fontsize=13)
    ax.set_ylim(0, max(f + s for f, s in zip(wrong_vals, same_vals)) * 1.35)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}%"))
    ax.set_title("Mismatch Cause: Wrong-Branch Routing vs. Stale Decision",
                 fontsize=13, fontweight="bold", pad=10)
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.legend(fontsize=12, framealpha=0.9)

    fig.tight_layout()
    out = OUTPUT_DIR / "branch_breakdown.png"
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"  saved: {out}")
    plt.close(fig)


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    print("Generating figures...")
    fig_hero_mismatch()
    fig_latency_tradeoff()
    fig_hit_rate_disconnect()
    fig_branch_breakdown()
    print(f"\nDone. All figures in: {OUTPUT_DIR}/")
