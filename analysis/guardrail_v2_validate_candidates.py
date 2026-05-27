"""Validate a set of final candidate guardrail parameters across 4 sources +
54 environments, so they can be compared apples-to-apples with the existing
robust_core results.

Adds rows to cross_source.csv and sensitivity.csv for any candidate not
already evaluated. Idempotent: re-runs only fill missing rows.

Run: python analysis/guardrail_v2_validate_candidates.py
"""
import sys
from pathlib import Path
import itertools
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.cashflow import CashFlowItem
from simulator.data_loader import load_returns_data, get_country_dfs
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate
from simulator.sweep import pregenerate_raw_scenarios
from simulator.config import get_gdp_weights

from analysis.guardrail_v2_phase2 import (
    NUM_SIMS, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK, INITIAL_PORTFOLIO,
    CONSUMPTION_FLOOR, ALLOC, EXPENSE, compute_cew,
)
from analysis.guardrail_v2_phase3 import (
    ALLOCATIONS, RETIREMENT_YEARS_LIST, FLOORS,
    build_baseline_cfs, build_scenarios as build_env_scenarios,
)
from analysis.guardrail_v2_phase4 import (
    SOURCES, build_scenarios_for_source,
)


# Add the two missing candidates to the existing 29-row robust_core
ADDITIONAL_CANDIDATES = [
    {"name": "Composite-winner", "target": 0.85, "upper": 0.90, "lower": 0.50,
     "adj": 0.15, "mode": "amount", "min_remain": 10},
    {"name": "Legacy-v1",        "target": 0.85, "upper": 0.99, "lower": 0.70,
     "adj": 0.10, "mode": "amount", "min_remain": 5},
]
PARAM_COLS = ["target", "upper", "lower", "adj", "mode", "min_remain"]
OUT_DIR = Path(__file__).resolve().parent / "output" / "guardrail_v2"


def run_one(scenarios, table, rate_grid, params, retirement_years, floor, cfs, inflation_matrix):
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


def augment_cross_source():
    """Add candidates × 4 sources to cross_source.csv."""
    cs_path = OUT_DIR / "cross_source.csv"
    cs = pd.read_csv(cs_path)
    print(f"[cross_source] existing rows: {len(cs)}")

    returns_df = load_returns_data()
    country_dfs = get_country_dfs(returns_df, data_start_year=1900)
    weights = get_gdp_weights(list(country_dfs.keys()))

    new_rows = []
    for src in SOURCES:
        if src != "POOL" and src not in country_dfs:
            continue
        scenarios = build_scenarios_for_source(src, returns_df, country_dfs, weights)
        rate_grid, table = build_success_rate_table(scenarios)
        for cand in ADDITIONAL_CANDIDATES:
            params = {k: cand[k] for k in PARAM_COLS}
            row = run_one(scenarios, table, rate_grid, params, RETIREMENT_YEARS, CONSUMPTION_FLOOR, None, None)
            new_rows.append({**params, **row, "source": src})

    new_df = pd.DataFrame(new_rows)
    combined = pd.concat([cs, new_df]).drop_duplicates(
        subset=PARAM_COLS + ["source"], keep="last"
    )
    combined.to_csv(cs_path, index=False)
    print(f"[cross_source] added {len(new_df)} rows → {len(combined)} total")


def augment_sensitivity():
    """Add candidates × 54 envs to sensitivity.csv."""
    sens_path = OUT_DIR / "sensitivity.csv"
    sens = pd.read_csv(sens_path)
    print(f"\n[sensitivity] existing rows: {len(sens)}")

    returns_df = load_returns_data()
    country_dfs = get_country_dfs(returns_df, data_start_year=1900)
    weights = get_gdp_weights(list(country_dfs.keys()))

    new_rows = []
    SEED = 42
    env_combos = list(itertools.product(ALLOCATIONS.items(), RETIREMENT_YEARS_LIST, [False, True]))
    for ei, ((alloc_name, alloc), years, use_cfs) in enumerate(env_combos):
        scenarios, inflation = build_env_scenarios(SEED, returns_df, country_dfs, weights, alloc, years)
        rate_grid, table = build_success_rate_table(scenarios)
        cfs = build_baseline_cfs(years) if use_cfs else None
        for floor in FLOORS:
            env_label = f"{alloc_name}|y{years}|cf{'1' if use_cfs else '0'}|fl{floor:.2f}"
            for cand in ADDITIONAL_CANDIDATES:
                params = {k: cand[k] for k in PARAM_COLS}
                try:
                    row = run_one(scenarios, table, rate_grid, params, years, floor, cfs, inflation)
                except Exception as e:
                    print(f"  [err] {params} in {env_label}: {e}")
                    continue
                new_rows.append({
                    **params, **row,
                    "alloc": alloc_name, "years": years,
                    "with_cfs": use_cfs, "floor": floor, "env": env_label,
                })
        print(f"  [env {ei+1}/{len(env_combos)}] {env_label} done")

    new_df = pd.DataFrame(new_rows)
    combined = pd.concat([sens, new_df]).drop_duplicates(
        subset=PARAM_COLS + ["env"], keep="last"
    )
    combined.to_csv(sens_path, index=False)
    print(f"\n[sensitivity] added {len(new_df)} rows → {len(combined)} total")


def main():
    print(f"Adding {len(ADDITIONAL_CANDIDATES)} candidates to robustness data:")
    for c in ADDITIONAL_CANDIDATES:
        print(f"  {c['name']:18s}: {c}")
    t0 = time.time()
    augment_cross_source()
    augment_sensitivity()
    print(f"\n[done] in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
