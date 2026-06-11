"""Multi-seed confirmation for US FIRE_dataset_intl CEW candidates.

Companion to optimal_allocation_cew_us.py. Re-runs the start_year=1900
grid leaders across 5 independent seeds (spaced >= num_simulations to
avoid the default_rng(seed+i) path-stream overlap), then confirms the
winners at N=10,000.

Output: analysis/output/optimal_allocation/cew_us_multiseed.csv (+ stdout)
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
from simulator.statistics import compute_success_rate

from optimal_allocation_cew import (
    INITIAL_PORTFOLIO, NUM_SIMS, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK,
    EXPENSE, GR_UPPER, GR_ADJ, GR_MODE, GR_MIN_REMAIN,
    compute_cew, per_path_funded_ratio, consumption_ulcer,
)

DATA_SOURCE = "fire_dataset_intl"
START_YEAR = 1900
SEEDS = [42, 5042, 10042, 15042, 20042]
CONFIRM_SIMS = 10_000
CONFIRM_SEED = 777_000
TARGET, LOWER = 0.85, 0.75

# start=1900 grid leaders (by median CEW) + tail-robust 10%-bond variants
CANDIDATES = [
    (1.00, 0.00, 0.00),
    (0.90, 0.10, 0.00),
    (0.80, 0.20, 0.00),
    (0.70, 0.30, 0.00),
    (0.60, 0.40, 0.00),
    (0.50, 0.50, 0.00),
    (0.80, 0.10, 0.10),
    (0.70, 0.20, 0.10),
    (0.60, 0.30, 0.10),
]

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"


def eval_alloc(raw: dict, w_ds: float, w_gs: float, w_db: float,
               seed_label: int | str) -> dict:
    real_returns = raw_to_combined(
        raw,
        {"domestic_stock": w_ds, "global_stock": w_gs, "domestic_bond": w_db},
        leverage=1.0,
    )
    rate_grid, table = build_success_rate_table(real_returns)
    _, init_wd, traj, wds = run_guardrail_simulation(
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
    return {
        "alloc": f"{int(w_ds*100):02d}/{int(w_gs*100):02d}/{int(w_db*100):02d}",
        "seed": seed_label,
        "success_rate": compute_success_rate(traj, RETIREMENT_YEARS),
        "severe_fail_prob": float(np.mean(fr_paths < 0.5)),
        "median_cew": float(np.median(cew)),
        "p10_cew": float(np.percentile(cew, 10)),
        "median_ulcer": float(np.median(consumption_ulcer(wds))),
        "init_swr": init_wd / INITIAL_PORTFOLIO,
        "p10_min_wd": float(np.percentile(min_wd, 10)),
    }


def main() -> None:
    df_all = load_returns_by_source(DATA_SOURCE)
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
            country_dfs=None, country_weights=None,
        )
        for w_ds, w_gs, w_db in CANDIDATES:
            rows.append(eval_alloc(raw, w_ds, w_gs, w_db, seed))

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "cew_us_multiseed.csv", index=False)

    agg = df.groupby("alloc").agg(
        sr_mean=("success_rate", "mean"),
        sr_min=("success_rate", "min"),
        seeds_above_090=("success_rate", lambda s: int((s >= 0.90).sum())),
        seeds_tail_ok=("severe_fail_prob", lambda s: int((s <= 0.01).sum())),
        severe_max=("severe_fail_prob", "max"),
        cew_mean=("median_cew", "mean"),
        cew_min=("median_cew", "min"),
        p10cew_mean=("p10_cew", "mean"),
        ulcer_mean=("median_ulcer", "mean"),
        swr_mean=("init_swr", "mean"),
        p10wd_mean=("p10_min_wd", "mean"),
    ).sort_values("cew_mean", ascending=False)
    print()
    print(f"5-seed aggregation (start={START_YEAR}, target={TARGET}, N={NUM_SIMS}):")
    print("Feasibility requires seeds_above_090 == 5 AND seeds_tail_ok == 5.")
    print(agg.to_string(formatters={
        "cew_mean": "{:,.0f}".format, "cew_min": "{:,.0f}".format,
        "p10cew_mean": "{:,.0f}".format, "p10wd_mean": "{:,.0f}".format,
        "swr_mean": "{:.3%}".format,
    }))

    # N=10,000 confirmation for robust finalists (all seeds pass both gates)
    robust = agg[(agg["seeds_above_090"] == len(SEEDS))
                 & (agg["seeds_tail_ok"] == len(SEEDS))]
    finalists = list(robust.head(4).index)
    if not finalists:
        print("\nNo candidate passed all seed gates; skipping confirmation run.")
        return
    print(f"\n[confirm] N={CONFIRM_SIMS}, seed={CONFIRM_SEED}: {finalists} "
          f"({time.time()-t0:.0f}s)")
    raw = pregenerate_raw_scenarios(
        expense_ratios=EXPENSE,
        retirement_years=RETIREMENT_YEARS,
        min_block=MIN_BLOCK, max_block=MAX_BLOCK,
        num_simulations=CONFIRM_SIMS,
        returns_df=returns_df,
        seed=CONFIRM_SEED,
        country_dfs=None, country_weights=None,
    )
    confirm_rows = []
    for tag in finalists:
        w_ds, w_gs, w_db = (int(p) / 100 for p in tag.split("/"))
        confirm_rows.append(eval_alloc(raw, w_ds, w_gs, w_db, "confirm10k"))
    cdf = pd.DataFrame(confirm_rows).sort_values("median_cew", ascending=False)
    cdf.to_csv(OUTPUT_DIR / "cew_us_confirm10k.csv", index=False)
    print(cdf.to_string(index=False, formatters={
        "median_cew": "{:,.0f}".format, "p10_cew": "{:,.0f}".format,
        "p10_min_wd": "{:,.0f}".format, "init_swr": "{:.3%}".format,
        "success_rate": "{:.4f}".format, "severe_fail_prob": "{:.4f}".format,
    }))
    print(f"\nTotal {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
