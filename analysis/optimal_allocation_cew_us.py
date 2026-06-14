"""Optimal allocation under the CEW-primary framework — US FIRE_dataset_intl.

Re-runs the 2026-06-10 CEW-primary optimization (optimal_allocation_cew.py,
JST pooled ALL) with the US-perspective dataset:

  - Data: data/FIRE_dataset_intl.csv (Shiller-based US Stock / US Bond /
    US Inflation 1871-2025; International Stock = real MSCI from 1970,
    JST Global_Stock level-wedge-calibrated backfill pre-1970).
  - Single-country bootstrap (no pooling) — USD perspective throughout.
  - Three start-year variants to answer "is 1970 the right start?":
      1900 (primary, window-matched to the JST pooled study),
      1871 (full sample), 1970 (user's hypothesis; 56y source window).

Objective / constraints / guardrail setup identical to the JST study:

    maximize    median CEW (CRRA gamma=2, delta=0.02)
    subject to  success_rate >= 0.90
                P(path funded_ratio < 0.5) <= 0.01
    tie-break   consumption-path Ulcer Index

Output:
  analysis/output/optimal_allocation/cew_us_results.csv
  analysis/output/optimal_allocation/cew_us_summary.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import load_returns_by_source
from simulator.sweep import pregenerate_raw_scenarios, raw_to_combined
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate

from optimal_allocation_cew import (
    INITIAL_PORTFOLIO, NUM_SIMS, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK,
    SEED, ALLOCATION_STEP, EXPENSE, CONSUMPTION_FLOOR,
    GR_VARIANTS, GR_UPPER, GR_ADJ, GR_MODE, GR_MIN_REMAIN,
    SR_FLOOR, SEVERE_FAIL_MAX, CEW_NEAR_OPTIMAL,
    compute_cew, per_path_funded_ratio, consumption_ulcer,
    gen_allocations, alloc_tag,
)

DATA_SOURCE = "fire_dataset_intl"
START_YEARS = [1900, 1871, 1929, 1950, 1970]

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_grid(returns_df: pd.DataFrame, start_year: int, seed: int) -> list[dict]:
    sub = returns_df[returns_df["Year"] >= start_year].reset_index(drop=True)
    print(f"[bootstrap] {DATA_SOURCE} single-country, start={start_year} "
          f"(n={len(sub)}y), {NUM_SIMS} sims x {RETIREMENT_YEARS}y, seed={seed}")
    raw = pregenerate_raw_scenarios(
        expense_ratios=EXPENSE,
        retirement_years=RETIREMENT_YEARS,
        min_block=MIN_BLOCK, max_block=MAX_BLOCK,
        num_simulations=NUM_SIMS,
        returns_df=sub,
        seed=seed,
        country_dfs=None, country_weights=None,  # single-country bootstrap
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
            min_wd = np.min(wds, axis=1)
            finals = traj[:, -1]
            n10 = max(1, int(0.1 * len(finals)))

            rows.append({
                "start_year": start_year,
                "alloc": alloc_tag(w_ds, w_gs, w_db),
                "us_stock": round(w_ds, 4),
                "intl_stock": round(w_gs, 4),
                "us_bond": round(w_db, 4),
                "target": target,
                "lower": lower,
                "seed": seed,
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
        if (i + 1) % 20 == 0:
            print(f"  alloc {i+1}/{len(allocs)}  ({time.time()-t0:.0f}s)")
    return rows


def write_summary(df: pd.DataFrame) -> None:
    lines: list[str] = []
    add = lines.append
    add("# CEW-Primary Optimal Allocation — US FIRE_dataset_intl (2026-06-11)")
    add("")
    add(f"Data: {DATA_SOURCE} (US perspective, intl backfilled pre-1970 from "
        f"JST Global_Stock), single-country bootstrap, "
        f"{RETIREMENT_YEARS}y, {NUM_SIMS} sims, seed={SEED} (shared bootstrap "
        f"per start-year)")
    add(f"Guardrail: upper={GR_UPPER}, adj={GR_ADJ}, mode={GR_MODE}, "
        f"mr={GR_MIN_REMAIN}; variants={GR_VARIANTS}")
    add(f"Objective: max median CEW s.t. success_rate >= {SR_FLOOR}, "
        f"P(FR<0.5) <= {SEVERE_FAIL_MAX}; tie-break median consumption Ulcer")
    add("")

    for start_year in START_YEARS:
        add(f"# start_year = {start_year}")
        add("")
        for target, lower in GR_VARIANTS:
            sub = df[
                (df["start_year"] == start_year)
                & (df["target"] == target) & (df["lower"] == lower)
            ].copy()
            feasible = sub[
                (sub["success_rate"] >= SR_FLOOR)
                & (sub["severe_fail_prob"] <= SEVERE_FAIL_MAX)
            ].copy()
            add(f"## target={target} / lower={lower}")
            add("")
            add(f"Feasible allocations: {len(feasible)}/{len(sub)}")
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
            add("| Alloc (US/Intl/Bond) | median_CEW | p10_CEW | Ulcer(med) | "
                "success | severe_fail | init_SWR | eff_FR | P10_min_wd | near_opt |")
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
            add(f"Near-optimal set (within {CEW_NEAR_OPTIMAL:.0%} of best CEW): "
                f"{n_near} allocations")
            add("")

            infeasible = sub[~sub.index.isin(feasible.index)]
            if not infeasible.empty:
                top_excluded = infeasible.sort_values(
                    "median_cew", ascending=False
                ).head(3)
                add("Highest-CEW allocations EXCLUDED by constraints:")
                add("")
                add("| Alloc | median_CEW | success | severe_fail | init_SWR |")
                add("|---|---|---|---|---|")
                for _, r in top_excluded.iterrows():
                    add(f"| {r['alloc']} | ${r['median_cew']:,.0f} | "
                        f"{r['success_rate']:.3f} | {r['severe_fail_prob']:.3f} | "
                        f"{r['init_swr']:.2%} |")
                add("")

    text = "\n".join(lines)
    (OUTPUT_DIR / "cew_us_summary.md").write_text(text)
    print(f"Wrote {OUTPUT_DIR / 'cew_us_summary.md'}")
    print()
    print(text)


def main() -> None:
    returns_df = load_returns_by_source(DATA_SOURCE)
    rows: list[dict] = []
    for start_year in START_YEARS:
        rows.extend(run_grid(returns_df, start_year, SEED))
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "cew_us_results.csv", index=False)
    print(f"Wrote {OUTPUT_DIR / 'cew_us_results.csv'} ({len(df)} rows)")
    write_summary(df)


if __name__ == "__main__":
    main()
