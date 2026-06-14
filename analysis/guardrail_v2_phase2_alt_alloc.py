"""Phase 2 supplementary: sweep baseline grid at alternative allocations.

Use case: user has a non-baseline allocation (e.g. 33/67/0 US-style) and
wants to see whether the 3-tier recommendations shift.

Reuses Phase 2 grid (3,000 configs) at a single seed (42) — multi-seed Jaccard
0.955+ in baseline confirms single seed is enough for ranking.

Run: python analysis/guardrail_v2_phase2_alt_alloc.py --alloc 33/67/0
Output: analysis/output/guardrail_v2/baseline_grid_<alloc-tag>.csv
"""
import argparse
import math
import sys
import time
import itertools
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator.data_loader import load_returns_data, get_country_dfs
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate
from simulator.sweep import pregenerate_raw_scenarios
from simulator.config import get_gdp_weights

from analysis.guardrail_v2_phase2 import (
    NUM_SIMS, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK, INITIAL_PORTFOLIO,
    CONSUMPTION_FLOOR, EXPENSE,
    TARGETS, UPPERS, LOWERS, ADJ_PCTS, MODES, MIN_REMAINS,
    compute_cew,
)


def parse_alloc(s: str) -> tuple[dict, str]:
    """Return (alloc dict, tag string).

    The tag uses the original integer percentages so that fractional rounding
    in float multiplication never bleeds into the filename (e.g. 29/71/0 must
    not become 28_71_0).
    """
    parts_raw = [x.strip() for x in s.split("/")]
    if len(parts_raw) != 3:
        raise ValueError(f"alloc must be 'dom/global/bond', got: {s}")
    parts = [float(x) for x in parts_raw]
    if not all(math.isfinite(p) and p >= 0 for p in parts):
        raise ValueError(f"alloc components must be finite and non-negative, got: {parts}")
    total = sum(parts)
    if abs(total - 100) > 0.1 and abs(total - 1.0) > 0.001:
        raise ValueError(f"alloc must sum to 100 (or 1), got {total}")
    if total > 1.5:
        tag = "_".join(parts_raw)  # keep "33_67_0" / "29_71_0"
        parts = [p / 100.0 for p in parts]
    else:
        # Proportion-style input (0.33/0.67/0). Preserve precision by emitting
        # the original raw components with '.' replaced by 'p' so the filename
        # remains shell-safe and never collides with an integer-percent tag.
        # Example: 0.333/0.667/0 → "0p333_0p667_0", distinct from "33_67_0".
        tag = "_".join(p.replace(".", "p") for p in parts_raw)
    alloc = {"domestic_stock": parts[0], "global_stock": parts[1], "domestic_bond": parts[2]}
    return alloc, tag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alloc", default="33/67/0", help="dom/global/bond (e.g. 33/67/0)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    alloc, tag = parse_alloc(args.alloc)
    print(f"[setup] alloc={alloc} (tag={tag}), seed={args.seed}")

    returns_df = load_returns_data()
    country_dfs = get_country_dfs(returns_df, data_start_year=1900)
    weights = get_gdp_weights(list(country_dfs.keys()))

    raw = pregenerate_raw_scenarios(
        expense_ratios=EXPENSE, retirement_years=RETIREMENT_YEARS,
        min_block=MIN_BLOCK, max_block=MAX_BLOCK,
        num_simulations=NUM_SIMS, returns_df=returns_df,
        seed=args.seed, country_dfs=country_dfs, country_weights=weights,
    )
    nominal = (
        alloc["domestic_stock"] * raw["domestic_stock"]
        + alloc["global_stock"] * raw["global_stock"]
        + alloc["domestic_bond"] * raw["domestic_bond"]
    )
    scenarios = (1.0 + nominal) / (1.0 + raw["inflation"]) - 1.0
    rate_grid, table = build_success_rate_table(scenarios)

    grid = [
        {"target": t, "upper": u, "lower": lo, "adj": a, "mode": m, "min_remain": mr}
        for t, u, lo, a, m, mr in itertools.product(
            TARGETS, UPPERS, LOWERS, ADJ_PCTS, MODES, MIN_REMAINS,
        )
        if lo < u
    ]
    print(f"[grid] {len(grid)} configs")

    rows = []
    t_start = time.time()
    for i, p in enumerate(grid):
        init_p, ann_wd, traj, wds, _ = run_guardrail_simulation(
            scenarios=scenarios,
            target_success=p["target"], upper_guardrail=p["upper"], lower_guardrail=p["lower"],
            adjustment_pct=p["adj"], retirement_years=RETIREMENT_YEARS,
            min_remaining_years=p["min_remain"], table=table, rate_grid=rate_grid,
            adjustment_mode=p["mode"], initial_portfolio=INITIAL_PORTFOLIO,
        )
        eff_fr, eff_sr = compute_effective_funded_ratio(
            wds, ann_wd, RETIREMENT_YEARS, consumption_floor=CONSUMPTION_FLOOR, trajectories=traj,
        )
        cew = compute_cew(wds)
        rows.append({
            **p, "init_wd": ann_wd, "swr": ann_wd / init_p,
            "success_rate": compute_success_rate(traj, RETIREMENT_YEARS),
            "eff_success": eff_sr, "eff_funded": eff_fr,
            "median_cew": float(np.median(cew)),
            "p10_avg_wd": float(np.percentile(wds.mean(axis=1), 10)),
            "mean_years_below_floor": float(np.mean((wds < ann_wd * CONSUMPTION_FLOOR).sum(axis=1))),
        })
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(grid)} done ({time.time()-t_start:.0f}s)")

    df = pd.DataFrame(rows)
    # Gating columns (must match guardrail_v2_analyze.py logic so the CSV is
    # self-contained and §3.5's gating comparison can be reproduced).
    df["passes_eff_sr"] = df["eff_success"] >= 0.85
    df["passes_p10_wd"] = df["p10_avg_wd"] >= df["init_wd"] * 0.60
    df["passes_years_below"] = df["mean_years_below_floor"] <= 5
    df["gating_pass"] = df["passes_eff_sr"] & df["passes_p10_wd"] & df["passes_years_below"]

    out_path = Path(__file__).resolve().parent / "output" / "guardrail_v2" / f"baseline_grid_{tag}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\n[done] {len(df)} configs in {time.time()-t_start:.0f}s → {out_path}")
    print(f"  gating pass: {df['gating_pass'].sum()}/{len(df)}")


if __name__ == "__main__":
    main()
