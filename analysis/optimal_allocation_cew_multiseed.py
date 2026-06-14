"""Multi-seed confirmation for top CEW-primary allocation candidates.

Companion to optimal_allocation_cew.py: the success_rate >= 0.90 feasibility
boundary sits within MC noise (stderr ~0.7pp at 2000 sims), so the top
candidates are re-run across 5 seeds to confirm constraint stability and
CEW ranking. Same setup: pooled ALL equal-prob, 1900+, 50y, guardrail
target=0.85 / lower=0.75 / upper=0.99 / adj=0.05 / amount / mr=1.

Output: analysis/output/optimal_allocation/cew_multiseed.csv (+ stdout table)
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
from simulator.statistics import compute_success_rate

from optimal_allocation_cew import (
    INITIAL_PORTFOLIO, NUM_SIMS, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK,
    START_YEAR, EXPENSE, GR_UPPER, GR_ADJ, GR_MODE, GR_MIN_REMAIN,
    compute_cew, per_path_funded_ratio, consumption_ulcer,
)

# NOTE: pregenerate_raw_scenarios derives per-path rng as default_rng(seed + i),
# so adjacent seeds share 1999/2000 path streams and are NOT independent
# replications. Seeds must be spaced by >= num_simulations.
SEEDS = [42, 5042, 10042, 15042, 20042]
TARGET, LOWER = 0.85, 0.75
CANDIDATES = [
    (0.20, 0.80, 0.00),
    (0.10, 0.90, 0.00),
    (0.30, 0.70, 0.00),
    (0.10, 0.80, 0.10),
    (0.20, 0.70, 0.10),
    (0.30, 0.60, 0.10),
]

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"


def main() -> None:
    df_all = load_returns_data()
    country_dfs = get_country_dfs(df_all, START_YEAR)
    returns_df = df_all[df_all["Year"] >= START_YEAR].reset_index(drop=True)

    rows: list[dict] = []
    t0 = time.time()
    for seed in SEEDS:
        print(f"[seed {seed}] bootstrap...  ({time.time()-t0:.0f}s)")
        raw = pregenerate_raw_scenarios(
            expense_ratios=EXPENSE,
            retirement_years=RETIREMENT_YEARS,
            min_block=MIN_BLOCK, max_block=MAX_BLOCK,
            num_simulations=NUM_SIMS,
            returns_df=returns_df,
            seed=seed,
            country_dfs=country_dfs, country_weights=None,
        )
        for w_ds, w_gs, w_db in CANDIDATES:
            real_returns = raw_to_combined(
                raw,
                {"domestic_stock": w_ds, "global_stock": w_gs,
                 "domestic_bond": w_db},
                leverage=1.0,
            )
            rate_grid, table = build_success_rate_table(real_returns)
            _, init_wd, traj, wds, _ = run_guardrail_simulation(
                scenarios=real_returns,
                target_success=TARGET,
                upper_guardrail=GR_UPPER,
                lower_guardrail=LOWER,
                adjustment_pct=GR_ADJ,
                retirement_years=RETIREMENT_YEARS,
                min_remaining_years=GR_MIN_REMAIN,
                table=table, rate_grid=rate_grid,
                adjustment_mode=GR_MODE,
                initial_portfolio=INITIAL_PORTFOLIO,
            )
            cew = compute_cew(wds)
            fr_paths = per_path_funded_ratio(traj, RETIREMENT_YEARS)
            min_wd = np.min(wds, axis=1)
            rows.append({
                "alloc": f"{int(w_ds*100):02d}/{int(w_gs*100):02d}/{int(w_db*100):02d}",
                "seed": seed,
                "success_rate": compute_success_rate(traj, RETIREMENT_YEARS),
                "severe_fail_prob": float(np.mean(fr_paths < 0.5)),
                "median_cew": float(np.median(cew)),
                "p10_cew": float(np.percentile(cew, 10)),
                "median_ulcer": float(np.median(consumption_ulcer(wds))),
                "init_swr": init_wd / INITIAL_PORTFOLIO,
                "p10_min_wd": float(np.percentile(min_wd, 10)),
            })

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "cew_multiseed.csv", index=False)

    agg = df.groupby("alloc").agg(
        sr_mean=("success_rate", "mean"),
        sr_min=("success_rate", "min"),
        sr_max=("success_rate", "max"),
        seeds_above_090=("success_rate", lambda s: int((s >= 0.90).sum())),
        seeds_tail_ok=("severe_fail_prob", lambda s: int((s <= 0.01).sum())),
        severe_min=("severe_fail_prob", "min"),
        severe_max=("severe_fail_prob", "max"),
        cew_mean=("median_cew", "mean"),
        cew_min=("median_cew", "min"),
        p10cew_mean=("p10_cew", "mean"),
        ulcer_mean=("median_ulcer", "mean"),
        severe_mean=("severe_fail_prob", "mean"),
        swr_mean=("init_swr", "mean"),
        p10wd_mean=("p10_min_wd", "mean"),
    ).sort_values("cew_mean", ascending=False)
    print()
    print("Feasibility requires BOTH seeds_above_090 == n_seeds AND "
          "seeds_tail_ok == n_seeds; CEW ranking below is informational "
          "for candidates failing either gate.")
    print(agg.to_string(formatters={
        "cew_mean": "{:,.0f}".format, "cew_min": "{:,.0f}".format,
        "p10cew_mean": "{:,.0f}".format, "p10wd_mean": "{:,.0f}".format,
        "swr_mean": "{:.3%}".format,
    }))
    print(f"\nTotal {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
