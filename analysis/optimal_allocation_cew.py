"""Optimal allocation under the CEW-primary framework (2026-06-10).

Applies the portfolio-optimization objective agreed on 2026-06-10
(memory: project-portfolio-optimization-objective):

    maximize    median CEW (CRRA gamma=2, delta=0.02)
    subject to  success_rate >= 0.90
                P(path funded_ratio < 0.5) <= 0.01   (severe-failure tail)
    tie-break   consumption-path Ulcer Index (lower is better)

Setup (user request 2026-06-10):
  - Data: JST pooled ALL (equal-probability, current product semantics),
    start_year=1900, 50-year horizon, 2000 sims, seed=42 (common random
    numbers: one bootstrap shared across all allocations).
  - Withdrawal: risk-based guardrail, v2 aggressive tier F
    (target=0.80 / upper=0.99 / lower=0.70 / adj=0.05 / amount / mr=1)
    plus a target=0.85 variant (lower=0.75, gap=10pp per user philosophy).
  - Allocation grid: dom_stock/global_stock/dom_bond simplex, 10pp steps.

Output:
  analysis/output/optimal_allocation/cew_results.csv
  analysis/output/optimal_allocation/cew_summary.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import load_returns_data, get_country_dfs
from simulator.sweep import pregenerate_raw_scenarios, raw_to_combined
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate

# ─────────────── parameters ────────────────────────────────────────────────
INITIAL_PORTFOLIO = 1_000_000.0
NUM_SIMS = 2_000
RETIREMENT_YEARS = 50
MIN_BLOCK = 5
MAX_BLOCK = 15
SEED = 42
ALLOCATION_STEP = 0.10
START_YEAR = 1900
EXPENSE = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}
CONSUMPTION_FLOOR = 0.50

# Guardrail variants: (target, lower); shared upper/adj/mode/mr from tier F
GR_VARIANTS = [(0.80, 0.70), (0.85, 0.75)]
GR_UPPER = 0.99
GR_ADJ = 0.05
GR_MODE = "amount"
GR_MIN_REMAIN = 1

# Objective constraints
SR_FLOOR = 0.90
SEVERE_FAIL_MAX = 0.01   # P(path funded_ratio < 0.5)
CEW_NEAR_OPTIMAL = 0.02  # within 2% of best median CEW

GAMMA = 2.0
DELTA = 0.02

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────── metrics ───────────────────────────────────────────────────

def compute_cew(wds: np.ndarray, gamma: float = GAMMA, delta: float = DELTA) -> np.ndarray:
    """Certainty-equivalent withdrawal per path (same as guardrail_v2_phase2)."""
    n_years = wds.shape[1]
    safe = np.maximum(wds, 1e-10)
    weights = (1.0 / (1.0 + delta)) ** np.arange(n_years)
    weights = weights / weights.sum()
    if abs(gamma - 1.0) < 1e-9:
        u = np.log(safe)
        mu = (u * weights[np.newaxis, :]).sum(axis=1)
        return np.exp(mu)
    u = safe ** (1.0 - gamma) / (1.0 - gamma)
    mu = (u * weights[np.newaxis, :]).sum(axis=1)
    return (mu * (1.0 - gamma)) ** (1.0 / (1.0 - gamma))


def per_path_funded_ratio(traj: np.ndarray, years: int) -> np.ndarray:
    """Per-path funded ratio, same depletion semantics as compute_funded_ratio."""
    depleted = traj[:, 1:] <= 0
    any_dep = depleted.any(axis=1)
    dep_year = np.where(
        any_dep, np.argmax(depleted, axis=1).astype(float) + 1.0, float(years)
    )
    return np.minimum(dep_year / years, 1.0)


def consumption_ulcer(wds: np.ndarray) -> np.ndarray:
    """Ulcer index per path on the withdrawal (consumption) trajectory.

    Drawdown measured against the running max of real withdrawals; depleted
    years keep wd=0 and thus count as 100% drawdown, as they should.
    """
    runmax = np.maximum.accumulate(wds, axis=1)
    runmax = np.maximum(runmax, 1e-10)
    dd = (runmax - wds) / runmax
    return np.sqrt(np.mean(dd**2, axis=1))


def gen_allocations(step: float) -> list[tuple[float, float, float]]:
    out = []
    steps = int(round(1.0 / step))
    for a in range(steps + 1):
        for b in range(steps + 1 - a):
            c = steps - a - b
            out.append((a * step, b * step, c * step))
    return out


def alloc_tag(a: float, b: float, c: float) -> str:
    return f"{int(round(a*100)):02d}/{int(round(b*100)):02d}/{int(round(c*100)):02d}"


# ─────────────── pipeline ──────────────────────────────────────────────────

def main() -> None:
    print(f"[bootstrap] pooled ALL equal-prob, start={START_YEAR}, "
          f"{NUM_SIMS} sims x {RETIREMENT_YEARS}y, seed={SEED}")
    df_all = load_returns_data()
    country_dfs = get_country_dfs(df_all, START_YEAR)
    returns_df = df_all[df_all["Year"] >= START_YEAR].reset_index(drop=True)
    raw = pregenerate_raw_scenarios(
        expense_ratios=EXPENSE,
        retirement_years=RETIREMENT_YEARS,
        min_block=MIN_BLOCK, max_block=MAX_BLOCK,
        num_simulations=NUM_SIMS,
        returns_df=returns_df,
        seed=SEED,
        country_dfs=country_dfs, country_weights=None,  # None = equal probability
    )

    allocs = gen_allocations(ALLOCATION_STEP)
    rows: list[dict] = []
    t0 = time.time()
    for i, (w_ds, w_gs, w_db) in enumerate(allocs):
        real_returns = raw_to_combined(
            raw,
            {"domestic_stock": w_ds, "global_stock": w_gs, "domestic_bond": w_db},
            leverage=1.0,
        )
        rate_grid, table = build_success_rate_table(real_returns)

        for target, lower in GR_VARIANTS:
            _, init_wd, traj, wds, _ = run_guardrail_simulation(
                scenarios=real_returns,
                target_success=target,
                upper_guardrail=GR_UPPER,
                lower_guardrail=lower,
                adjustment_pct=GR_ADJ,
                retirement_years=RETIREMENT_YEARS,
                min_remaining_years=GR_MIN_REMAIN,
                table=table, rate_grid=rate_grid,
                adjustment_mode=GR_MODE,
                initial_portfolio=INITIAL_PORTFOLIO,
            )
            sr = compute_success_rate(traj, RETIREMENT_YEARS)
            fr_paths = per_path_funded_ratio(traj, RETIREMENT_YEARS)
            severe_fail = float(np.mean(fr_paths < 0.5))
            cew = compute_cew(wds)
            ulcer = consumption_ulcer(wds)
            eff_fr, eff_sr = compute_effective_funded_ratio(
                wds, init_wd, RETIREMENT_YEARS,
                consumption_floor=CONSUMPTION_FLOOR, trajectories=traj,
            )
            min_wd = np.min(wds, axis=1)  # includes post-depletion zeros
            finals = traj[:, -1]
            n10 = max(1, int(0.1 * len(finals)))

            rows.append({
                "alloc": alloc_tag(w_ds, w_gs, w_db),
                "domestic_stock": round(w_ds, 4),
                "global_stock": round(w_gs, 4),
                "domestic_bond": round(w_db, 4),
                "target": target,
                "lower": lower,
                "init_swr": init_wd / INITIAL_PORTFOLIO,
                "init_wd": init_wd,
                "success_rate": sr,
                "severe_fail_prob": severe_fail,
                "median_cew": float(np.median(cew)),
                "p10_cew": float(np.percentile(cew, 10)),
                "median_ulcer": float(np.median(ulcer)),
                "p90_ulcer": float(np.percentile(ulcer, 90)),
                "eff_funded_ratio": eff_fr,
                "eff_success_rate": eff_sr,
                "p10_min_wd": float(np.percentile(min_wd, 10)),
                "median_final": float(np.median(finals)),
                "cvar_10_final": float(np.mean(np.sort(finals)[:n10])),
                "mean_years_below_floor": float(
                    np.mean((wds < init_wd * CONSUMPTION_FLOOR).sum(axis=1))
                ),
            })
        if (i + 1) % 10 == 0:
            print(f"  alloc {i+1}/{len(allocs)}  ({time.time()-t0:.0f}s)")

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "cew_results.csv", index=False)
    print(f"Wrote {OUTPUT_DIR / 'cew_results.csv'} ({len(df)} rows, "
          f"{time.time()-t0:.0f}s)")

    write_summary(df)


def write_summary(df: pd.DataFrame) -> None:
    lines: list[str] = []
    add = lines.append
    add("# Optimal Allocation under CEW-Primary Objective (2026-06-10)")
    add("")
    add(f"Data: JST pooled ALL (equal prob), start={START_YEAR}, "
        f"{RETIREMENT_YEARS}y, {NUM_SIMS} sims, seed={SEED} (shared bootstrap)")
    add(f"Guardrail: upper={GR_UPPER}, adj={GR_ADJ}, mode={GR_MODE}, "
        f"mr={GR_MIN_REMAIN}; variants={GR_VARIANTS}")
    add(f"Objective: max median CEW (gamma={GAMMA}, delta={DELTA}) "
        f"s.t. success_rate >= {SR_FLOOR}, P(FR<0.5) <= {SEVERE_FAIL_MAX}; "
        f"tie-break median consumption Ulcer")
    add("")

    for target, lower in GR_VARIANTS:
        sub = df[(df["target"] == target) & (df["lower"] == lower)].copy()
        feasible = sub[
            (sub["success_rate"] >= SR_FLOOR)
            & (sub["severe_fail_prob"] <= SEVERE_FAIL_MAX)
        ].copy()
        add(f"## target={target} / lower={lower}")
        add("")
        add(f"Feasible allocations: {len(feasible)}/{len(sub)} "
            f"(success_rate >= {SR_FLOOR} & severe_fail <= {SEVERE_FAIL_MAX})")
        add("")
        if feasible.empty:
            relaxed = sub.sort_values("success_rate", ascending=False).head(5)
            add("**No feasible allocation.** Closest by success_rate:")
            add("")
            add("| Alloc | success | severe_fail | median_CEW | init_SWR |")
            add("|---|---|---|---|---|")
            for _, r in relaxed.iterrows():
                add(f"| {r['alloc']} | {r['success_rate']:.3f} | "
                    f"{r['severe_fail_prob']:.3f} | ${r['median_cew']:,.0f} | "
                    f"{r['init_swr']:.2%} |")
            add("")
            continue

        feasible = feasible.sort_values(
            ["median_cew", "median_ulcer"], ascending=[False, True]
        )
        best_cew = feasible["median_cew"].iloc[0]
        feasible["near_optimal"] = (
            feasible["median_cew"] >= best_cew * (1 - CEW_NEAR_OPTIMAL)
        )

        add("Top 10 by median CEW (tie-break: lower Ulcer):")
        add("")
        add("| Alloc | median_CEW | p10_CEW | Ulcer(med) | success | "
            "severe_fail | init_SWR | eff_FR | P10_min_wd | near_opt |")
        add("|---|---|---|---|---|---|---|---|---|---|")
        for _, r in feasible.head(10).iterrows():
            add(f"| {r['alloc']} | ${r['median_cew']:,.0f} | "
                f"${r['p10_cew']:,.0f} | {r['median_ulcer']:.3f} | "
                f"{r['success_rate']:.3f} | {r['severe_fail_prob']:.3f} | "
                f"{r['init_swr']:.2%} | {r['eff_funded_ratio']:.3f} | "
                f"${r['p10_min_wd']:,.0f} | "
                f"{'Y' if r['near_optimal'] else ''} |")
        add("")
        n_near = int(feasible["near_optimal"].sum())
        add(f"Near-optimal set (CEW within {CEW_NEAR_OPTIMAL:.0%} of best): "
            f"{n_near} allocations")
        add("")

        infeasible = sub[~sub.index.isin(feasible.index)]
        if not infeasible.empty:
            top_excluded = infeasible.sort_values(
                "median_cew", ascending=False
            ).head(3)
            add("Highest-CEW allocations EXCLUDED by constraints (for contrast):")
            add("")
            add("| Alloc | median_CEW | success | severe_fail | init_SWR |")
            add("|---|---|---|---|---|")
            for _, r in top_excluded.iterrows():
                add(f"| {r['alloc']} | ${r['median_cew']:,.0f} | "
                    f"{r['success_rate']:.3f} | {r['severe_fail_prob']:.3f} | "
                    f"{r['init_swr']:.2%} |")
            add("")

    text = "\n".join(lines)
    (OUTPUT_DIR / "cew_summary.md").write_text(text)
    print(f"Wrote {OUTPUT_DIR / 'cew_summary.md'}")
    print()
    print(text)


if __name__ == "__main__":
    main()
