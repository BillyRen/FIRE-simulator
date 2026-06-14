"""Phase 4 — Cross-data-source robustness on Phase 3 robust core.

For each "robust core" candidate (identified from sensitivity.csv), evaluate
at the user baseline (15/75/10, 50yr, no CFs, floor=0.50) across:
  - JST USA only (data_start_year=1900)
  - JST DEU only
  - JST JPN only
  - JST Pool (already in Phase 2; rerun here for symmetric comparison)

Records asymmetric cross-rank: USA top in Pool? Pool top in USA?

Output: analysis/output/guardrail_v2/cross_source.csv
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.data_loader import load_returns_data, get_country_dfs
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate
from simulator.sweep import pregenerate_raw_scenarios
from simulator.config import get_gdp_weights

from analysis.guardrail_v2_phase2 import compute_cew


NUM_SIMS = 2000
RETIREMENT_YEARS = 50
MIN_BLOCK = 5
MAX_BLOCK = 15
INITIAL_PORTFOLIO = 1_000_000.0
CONSUMPTION_FLOOR = 0.50
ALLOC = {"domestic_stock": 0.15, "global_stock": 0.75, "domestic_bond": 0.10}
EXPENSE = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}
SEED = 42

SOURCES = ["POOL", "USA", "DEU", "JPN"]


def build_scenarios_for_source(source: str, returns_df, country_dfs, weights) -> np.ndarray:
    if source == "POOL":
        c_dfs, w = country_dfs, weights
    else:
        c_dfs = {source: country_dfs[source]} if source in country_dfs else None
        w = {source: 1.0} if c_dfs else None
    raw = pregenerate_raw_scenarios(
        expense_ratios=EXPENSE,
        retirement_years=RETIREMENT_YEARS,
        min_block=MIN_BLOCK, max_block=MAX_BLOCK,
        num_simulations=NUM_SIMS,
        returns_df=returns_df,
        seed=SEED,
        country_dfs=c_dfs, country_weights=w,
    )
    nominal = (
        ALLOC["domestic_stock"] * raw["domestic_stock"]
        + ALLOC["global_stock"] * raw["global_stock"]
        + ALLOC["domestic_bond"] * raw["domestic_bond"]
    )
    return (1.0 + nominal) / (1.0 + raw["inflation"]) - 1.0


def evaluate(scenarios, table, rate_grid, params) -> dict:
    init_p, ann_wd, traj, wds, _ = run_guardrail_simulation(
        scenarios=scenarios,
        target_success=params["target"],
        upper_guardrail=params["upper"],
        lower_guardrail=params["lower"],
        adjustment_pct=params["adj"],
        retirement_years=RETIREMENT_YEARS,
        min_remaining_years=int(params["min_remain"]),
        table=table, rate_grid=rate_grid,
        adjustment_mode=params["mode"],
        initial_portfolio=INITIAL_PORTFOLIO,
    )
    eff_fr, eff_sr = compute_effective_funded_ratio(
        wds, ann_wd, RETIREMENT_YEARS, consumption_floor=CONSUMPTION_FLOOR, trajectories=traj,
    )
    cew = compute_cew(wds)
    return {
        "swr": ann_wd / init_p,
        "success_rate": compute_success_rate(traj, RETIREMENT_YEARS),
        "eff_success": eff_sr, "eff_funded": eff_fr,
        "median_cew": float(np.median(cew)),
        "p10_avg_wd": float(np.percentile(wds.mean(axis=1), 10)),
        "init_wd": ann_wd,
    }


def main():
    out_dir = Path(__file__).resolve().parent / "output" / "guardrail_v2"
    core_path = out_dir / "robust_core.csv"
    if not core_path.exists():
        print(f"[!] {core_path} not found. Run guardrail_v2_phase3_analyze.py first.")
        sys.exit(1)
    core = pd.read_csv(core_path)
    param_cols = ["target", "upper", "lower", "adj", "mode", "min_remain"]
    core = core.drop_duplicates(subset=param_cols).reset_index(drop=True)
    print(f"[setup] robust_core: {len(core)} param sets")

    returns_df = load_returns_data()
    country_dfs = get_country_dfs(returns_df, data_start_year=1900)
    weights = get_gdp_weights(list(country_dfs.keys()))

    rows = []
    t_start = time.time()
    for src in SOURCES:
        if src != "POOL" and src not in country_dfs:
            print(f"[skip] {src} not in country_dfs")
            continue
        t_src = time.time()
        scenarios = build_scenarios_for_source(src, returns_df, country_dfs, weights)
        rate_grid, table = build_success_rate_table(scenarios)
        print(f"[src {src}] table built in {time.time()-t_src:.1f}s, evaluating {len(core)} configs...")
        for _, p in core.iterrows():
            params = {c: p[c] for c in param_cols}
            m = evaluate(scenarios, table, rate_grid, params)
            rows.append({**params, **m, "source": src})
        pd.DataFrame(rows).to_csv(out_dir / "cross_source.csv", index=False)

    total = time.time() - t_start
    print(f"\n[done] {len(rows)} rows in {total:.0f}s → {out_dir/'cross_source.csv'}")


if __name__ == "__main__":
    main()
