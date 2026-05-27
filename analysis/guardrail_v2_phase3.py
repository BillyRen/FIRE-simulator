"""Phase 3 — Environment sensitivity sweep on Phase 2 candidates.

For each candidate in phase3_candidates.csv, evaluate across 3×3×2×3 = 54 environments:
  - retirement_years ∈ {30, 45, 60}
  - allocation ∈ {10/80/10, 25/65/10, 60/30/10}   (Pool / user / US-style)
  - cash_flows ∈ {none, baseline_cfs}
  - consumption_floor ∈ {0.40, 0.50, 0.60}

Output: analysis/output/guardrail_v2/sensitivity.csv

Robust core = candidates ranking in top-20 by eff_funded AND median_cew across ALL 54 envs.
"""
import sys
import time
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.cashflow import CashFlowItem
from simulator.data_loader import load_returns_data, get_country_dfs
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate
from simulator.sweep import pregenerate_raw_scenarios
from simulator.config import get_gdp_weights

from analysis.guardrail_v2_phase2 import compute_cew


NUM_SIMS = 2000
MIN_BLOCK = 5
MAX_BLOCK = 15
INITIAL_PORTFOLIO = 1_000_000.0
SEED = 42  # single seed for sensitivity (stability already verified in Phase 2)
EXPENSE = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}

ALLOCATIONS = {
    "pool_optimal_10_80_10": {"domestic_stock": 0.10, "global_stock": 0.80, "domestic_bond": 0.10},
    "user_baseline_15_75_10": {"domestic_stock": 0.15, "global_stock": 0.75, "domestic_bond": 0.10},
    "balanced_25_65_10": {"domestic_stock": 0.25, "global_stock": 0.65, "domestic_bond": 0.10},
}
RETIREMENT_YEARS_LIST = [30, 45, 60]
FLOORS = [0.40, 0.50, 0.60]


def build_baseline_cfs(retirement_years: int) -> list[CashFlowItem]:
    """User profile cash flows: maintenance expense always, social security from year 30 (for 60yr horizon)."""
    cfs = [
        CashFlowItem(
            amount=-30_000.0, start_year=0, duration=retirement_years,
            inflation_adjusted=True, name="property_maintenance",
        ),
    ]
    if retirement_years >= 30:
        cfs.append(CashFlowItem(
            amount=120_000.0,
            start_year=min(30, retirement_years - 1),
            duration=min(20, max(1, retirement_years - 30)),
            inflation_adjusted=True, name="social_security",
        ))
    elif retirement_years >= 20:
        # earlier scenario: scale start_year
        cfs.append(CashFlowItem(
            amount=120_000.0,
            start_year=min(15, retirement_years - 1),
            duration=min(15, retirement_years - 15),
            inflation_adjusted=True, name="social_security",
        ))
    return cfs


def build_scenarios(
    seed: int, returns_df, country_dfs, weights,
    alloc: dict, retirement_years: int,
) -> np.ndarray:
    raw = pregenerate_raw_scenarios(
        expense_ratios=EXPENSE,
        retirement_years=retirement_years,
        min_block=MIN_BLOCK, max_block=MAX_BLOCK,
        num_simulations=NUM_SIMS,
        returns_df=returns_df,
        seed=seed,
        country_dfs=country_dfs, country_weights=weights,
    )
    nominal = (
        alloc["domestic_stock"] * raw["domestic_stock"]
        + alloc["global_stock"] * raw["global_stock"]
        + alloc["domestic_bond"] * raw["domestic_bond"]
    )
    return (1.0 + nominal) / (1.0 + raw["inflation"]) - 1.0, raw["inflation"]


def evaluate(
    scenarios, table, rate_grid, params, retirement_years, floor, cfs, inflation_matrix,
) -> dict:
    init_p, ann_wd, traj, wds = run_guardrail_simulation(
        scenarios=scenarios,
        target_success=params["target"],
        upper_guardrail=params["upper"],
        lower_guardrail=params["lower"],
        adjustment_pct=params["adj"],
        retirement_years=retirement_years,
        min_remaining_years=int(params["min_remain"]),
        table=table, rate_grid=rate_grid,
        adjustment_mode=params["mode"],
        initial_portfolio=INITIAL_PORTFOLIO,
        cash_flows=cfs if cfs else None,
        inflation_matrix=inflation_matrix if cfs else None,
    )
    sr = compute_success_rate(traj, retirement_years)
    eff_fr, eff_sr = compute_effective_funded_ratio(
        wds, ann_wd, retirement_years, consumption_floor=floor, trajectories=traj,
    )
    cew = compute_cew(wds)
    return {
        "swr": ann_wd / init_p,
        "success_rate": sr,
        "eff_success": eff_sr,
        "eff_funded": eff_fr,
        "median_cew": float(np.median(cew)),
        "p10_avg_wd": float(np.percentile(wds.mean(axis=1), 10)),
        "init_wd": ann_wd,
    }


def main():
    print("[setup] loading data + Phase 3 candidates")
    cand_path = Path(__file__).resolve().parent / "output" / "guardrail_v2" / "phase3_candidates.csv"
    cands = pd.read_csv(cand_path)
    param_cols = ["target", "upper", "lower", "adj", "mode", "min_remain"]
    cands = cands.drop_duplicates(subset=param_cols).reset_index(drop=True)
    print(f"  {len(cands)} candidate parameter sets")

    returns_df = load_returns_data()
    country_dfs = get_country_dfs(returns_df, data_start_year=1900)
    weights = get_gdp_weights(list(country_dfs.keys()))

    out_path = cand_path.parent / "sensitivity.csv"

    # Per-environment scenario+table caching
    rows = []
    t_start = time.time()
    env_combos = list(itertools.product(
        ALLOCATIONS.items(), RETIREMENT_YEARS_LIST, [False, True],
    ))
    print(f"[envs] {len(env_combos) * len(FLOORS)} envs total (alloc×years×CFs×floor)")

    for ei, ((alloc_name, alloc), years, use_cfs) in enumerate(env_combos):
        t_env = time.time()
        scenarios, inflation = build_scenarios(SEED, returns_df, country_dfs, weights, alloc, years)
        rate_grid, table = build_success_rate_table(scenarios)
        cfs = build_baseline_cfs(years) if use_cfs else None
        for floor in FLOORS:
            env_label = f"{alloc_name}|y{years}|cf{'1' if use_cfs else '0'}|fl{floor:.2f}"
            for _, p in cands.iterrows():
                params = {c: p[c] for c in param_cols}
                try:
                    m = evaluate(scenarios, table, rate_grid, params, years, floor, cfs, inflation)
                except Exception as e:
                    print(f"  [err] {params} in {env_label}: {e}")
                    continue
                row = {**params, **m, "alloc": alloc_name, "years": years,
                       "with_cfs": use_cfs, "floor": floor, "env": env_label}
                rows.append(row)
        env_dur = time.time() - t_env
        elapsed = time.time() - t_start
        envs_done = ei + 1
        envs_total = len(env_combos)
        eta = elapsed / envs_done * (envs_total - envs_done)
        print(f"[env {ei+1}/{envs_total}] {alloc_name} y={years} cf={use_cfs} done in {env_dur:.1f}s "
              f"(elapsed {elapsed:.0f}s, eta {eta:.0f}s)")
        pd.DataFrame(rows).to_csv(out_path, index=False)

    total_dur = time.time() - t_start
    print(f"\n[done] {len(rows)} rows in {total_dur:.0f}s ({total_dur/60:.1f}min) → {out_path}")


if __name__ == "__main__":
    main()
