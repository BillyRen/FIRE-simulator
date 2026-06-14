"""Guardrail Optimal Params v2 — Phase 2: baseline grid sweep.

User profile baseline (locked):
  - JST Pool 1900+ (16 countries sqrt(GDP) weighted)
  - Allocation 15/75/10 (Dom/Global/Bond)
  - Expense ratio 0.5%, leverage 1.0
  - 50-year retirement, $1M initial portfolio
  - Consumption floor 50% (effective failure threshold)
  - No cash flows in Phase 2 (anchor); CFs introduced in Phase 3 sensitivity

Parameter grid (after dropping unsupported `rate` adjustment_mode per Codex review):
  target × upper × lower × adj × mode × min_remain = 5×3×5×5×2×4 = 3000
  Valid (lower < upper): ~2,520

Across 5 seeds for ranking stability check.

Output: analysis/output/guardrail_v2/baseline_grid.csv
"""
import sys
import time
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.data_loader import load_returns_data, get_country_dfs
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import (
    compute_effective_funded_ratio,
    compute_success_rate,
    compute_funded_ratio,
)
from simulator.sweep import pregenerate_raw_scenarios
from simulator.config import get_gdp_weights


# ---- Baseline user profile ----
NUM_SIMS = 2000
RETIREMENT_YEARS = 50
MIN_BLOCK = 5
MAX_BLOCK = 15
INITIAL_PORTFOLIO = 1_000_000.0
CONSUMPTION_FLOOR = 0.50
ALLOC = {"domestic_stock": 0.15, "global_stock": 0.75, "domestic_bond": 0.10}
EXPENSE = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}
SEEDS = [42, 43, 44, 45, 46]


# ---- Parameter grid ----
TARGETS = [0.75, 0.80, 0.85, 0.90, 0.95]
UPPERS = [0.90, 0.95, 0.99]
LOWERS = [0.10, 0.20, 0.50, 0.70, 0.80]
ADJ_PCTS = [0.05, 0.10, 0.15, 0.20, 0.25]
MODES = ["amount", "success_rate"]
MIN_REMAINS = [1, 3, 5, 10]


def compute_cew(wds: np.ndarray, gamma: float = 2.0, delta: float = 0.02) -> np.ndarray:
    """Certainty-equivalent withdrawal per path. Returns shape (n_sims,)."""
    n_years = wds.shape[1]
    safe = np.maximum(wds, 1e-10)
    weights = (1.0 / (1.0 + delta)) ** np.arange(n_years)
    weights = weights / weights.sum()
    if abs(gamma - 1.0) < 1e-9:
        u = np.log(safe)
    else:
        u = safe ** (1.0 - gamma) / (1.0 - gamma)
    mu = (u * weights[np.newaxis, :]).sum(axis=1)
    if abs(gamma - 1.0) < 1e-9:
        cew = np.exp(mu)
    else:
        cew = (mu * (1.0 - gamma)) ** (1.0 / (1.0 - gamma))
    return cew


def build_scenarios(seed: int, returns_df, country_dfs, weights) -> np.ndarray:
    """Generate (NUM_SIMS, RETIREMENT_YEARS) real-portfolio returns for the baseline allocation."""
    raw = pregenerate_raw_scenarios(
        expense_ratios=EXPENSE,
        retirement_years=RETIREMENT_YEARS,
        min_block=MIN_BLOCK, max_block=MAX_BLOCK,
        num_simulations=NUM_SIMS,
        returns_df=returns_df,
        seed=seed,
        country_dfs=country_dfs, country_weights=weights,
    )
    nominal = (
        ALLOC["domestic_stock"] * raw["domestic_stock"]
        + ALLOC["global_stock"] * raw["global_stock"]
        + ALLOC["domestic_bond"] * raw["domestic_bond"]
    )
    inflation = raw["inflation"]
    return (1.0 + nominal) / (1.0 + inflation) - 1.0


def evaluate_one(scenarios, table, rate_grid, params: dict) -> dict:
    """Run one guardrail config and return metrics dict."""
    init_p, ann_wd, traj, wds, _ = run_guardrail_simulation(
        scenarios=scenarios,
        target_success=params["target"],
        upper_guardrail=params["upper"],
        lower_guardrail=params["lower"],
        adjustment_pct=params["adj"],
        retirement_years=RETIREMENT_YEARS,
        min_remaining_years=params["min_remain"],
        table=table, rate_grid=rate_grid,
        adjustment_mode=params["mode"],
        initial_portfolio=INITIAL_PORTFOLIO,
    )
    sr = compute_success_rate(traj, RETIREMENT_YEARS)
    fr = compute_funded_ratio(traj, RETIREMENT_YEARS)
    eff_fr, eff_sr = compute_effective_funded_ratio(
        wds, ann_wd, RETIREMENT_YEARS,
        consumption_floor=CONSUMPTION_FLOOR, trajectories=traj,
    )
    cew = compute_cew(wds)
    floor_val = ann_wd * CONSUMPTION_FLOOR

    p10_wd = float(np.percentile(wds.mean(axis=1), 10))
    p50_wd = float(np.percentile(wds.mean(axis=1), 50))
    p90_wd = float(np.percentile(wds.mean(axis=1), 90))
    # path-level max single-year consumption drop
    yoy = np.diff(wds, axis=1) / np.maximum(wds[:, :-1], 1e-10)
    max_drop_per_path = -np.min(yoy, axis=1)
    p90_max_drop = float(np.percentile(max_drop_per_path, 90))
    # years below floor
    years_below = np.mean((wds < floor_val).sum(axis=1))
    return {
        **params,
        "init_wd": ann_wd,
        "swr": ann_wd / init_p,
        "success_rate": sr,
        "funded_ratio": fr,
        "eff_success": eff_sr,
        "eff_funded": eff_fr,
        "median_cew": float(np.median(cew)),
        "p10_cew": float(np.percentile(cew, 10)),
        "p10_avg_wd": p10_wd,
        "p50_avg_wd": p50_wd,
        "p90_avg_wd": p90_wd,
        "p90_max_drop": p90_max_drop,
        "mean_years_below_floor": float(years_below),
    }


def main() -> None:
    print("[setup] loading JST data + pooling weights")
    returns_df = load_returns_data()
    country_dfs = get_country_dfs(returns_df, data_start_year=1900)
    weights = get_gdp_weights(list(country_dfs.keys()))
    print(f"  {len(country_dfs)} countries")

    # Build full parameter grid, drop lower >= upper
    grid = []
    for tgt, up, lo, adj, mode, mr in itertools.product(
        TARGETS, UPPERS, LOWERS, ADJ_PCTS, MODES, MIN_REMAINS
    ):
        if lo >= up:
            continue
        grid.append({
            "target": tgt, "upper": up, "lower": lo,
            "adj": adj, "mode": mode, "min_remain": mr,
        })
    print(f"[grid] {len(grid)} valid param combos")

    out_path = Path(__file__).resolve().parent / "output" / "guardrail_v2" / "baseline_grid.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows = []
    t_start = time.time()
    for si, seed in enumerate(SEEDS):
        t_seed = time.time()
        scenarios = build_scenarios(seed, returns_df, country_dfs, weights)
        rate_grid, table = build_success_rate_table(scenarios)
        t_setup = time.time() - t_seed
        print(f"[seed {seed}] setup {t_setup:.1f}s; running {len(grid)} configs...")

        for gi, params in enumerate(grid):
            row = evaluate_one(scenarios, table, rate_grid, params)
            row["seed"] = seed
            all_rows.append(row)
            if (gi + 1) % 500 == 0:
                elapsed = time.time() - t_seed
                rate = (gi + 1) / elapsed
                eta = (len(grid) - gi - 1) / rate
                print(f"  [seed {seed}] {gi+1}/{len(grid)} configs ({rate:.1f}/s, eta {eta:.0f}s)")

        seed_dur = time.time() - t_seed
        print(f"[seed {seed}] done in {seed_dur:.1f}s ({len(grid)/seed_dur:.1f} configs/s)")

        # Persist incrementally so we can recover on crash
        pd.DataFrame(all_rows).to_csv(out_path, index=False)

    total_dur = time.time() - t_start
    print(f"\n[done] {len(all_rows)} rows in {total_dur:.0f}s ({total_dur/60:.1f}min)")
    print(f"  → {out_path}")


if __name__ == "__main__":
    main()
