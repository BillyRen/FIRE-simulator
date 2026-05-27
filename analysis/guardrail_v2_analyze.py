"""Aggregate baseline_grid.csv across seeds and produce gating + Top-K rankings.

Phase 2 output → Phase 2.5 analysis (3-tier recommendations) → feeds Phase 3.

Gating layer (hard constraints):
  - effective_success_rate ≥ 0.85
  - p10_avg_wd ≥ 0.60 × init_wd  (P10 path's avg consumption is ≥ 60% initial)
  - mean_years_below_floor ≤ 5

Ranking layer (3 tiers within gating):
  - conservative: max eff_funded
  - balanced:     max median_cew
  - aggressive:   max init_wd / portfolio (= swr)

Stability check:
  - aggregate across seeds (mean ± std)
  - rank-stability via Jaccard of Top-50 across seeds
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent / "output" / "guardrail_v2"
SRC = OUT_DIR / "baseline_grid.csv"


def aggregate_across_seeds(df: pd.DataFrame) -> pd.DataFrame:
    """Group by param key, aggregate metric mean/std across seeds."""
    key = ["target", "upper", "lower", "adj", "mode", "min_remain"]
    metrics = [
        "swr", "success_rate", "funded_ratio", "eff_success", "eff_funded",
        "median_cew", "p10_cew", "p10_avg_wd", "p50_avg_wd", "p90_avg_wd",
        "p90_max_drop", "mean_years_below_floor", "init_wd",
    ]
    grouped = df.groupby(key)[metrics].agg(["mean", "std"]).reset_index()
    # flatten MultiIndex columns
    grouped.columns = [
        c[0] if c[1] == "" else f"{c[0]}_{c[1]}"
        for c in grouped.columns.to_flat_index()
    ]
    grouped["n_seeds"] = df.groupby(key).size().values
    return grouped


def apply_gating(agg: pd.DataFrame) -> pd.DataFrame:
    g = agg.copy()
    g["init_wd_floor60"] = g["init_wd_mean"] * 0.60
    g["passes_eff_sr"] = g["eff_success_mean"] >= 0.85
    g["passes_p10_wd"] = g["p10_avg_wd_mean"] >= g["init_wd_floor60"]
    g["passes_years_below"] = g["mean_years_below_floor_mean"] <= 5
    g["gating_pass"] = g["passes_eff_sr"] & g["passes_p10_wd"] & g["passes_years_below"]
    return g


def jaccard_top_k(df: pd.DataFrame, k: int = 50, metric: str = "eff_funded") -> dict:
    """Per-seed Top-K Jaccard similarity matrix for stability check."""
    seeds = sorted(df["seed"].unique())
    top_sets = {}
    key_cols = ["target", "upper", "lower", "adj", "mode", "min_remain"]
    for s in seeds:
        sub = df[df["seed"] == s].nlargest(k, metric)
        top_sets[s] = set(map(tuple, sub[key_cols].values.tolist()))
    mat = {}
    for i, s1 in enumerate(seeds):
        for s2 in seeds[i+1:]:
            j = len(top_sets[s1] & top_sets[s2]) / len(top_sets[s1] | top_sets[s2])
            mat[(s1, s2)] = j
    return {"top_sets": top_sets, "jaccard": mat,
            "mean_jaccard": float(np.mean(list(mat.values()))) if mat else float("nan")}


def main():
    raw = pd.read_csv(SRC)
    print(f"[load] {SRC}: {len(raw)} rows, {raw['seed'].nunique()} seeds")

    # Per-seed stability for top-50 by eff_funded
    stab = jaccard_top_k(raw, k=50, metric="eff_funded")
    print(f"[stability] Top-50 by eff_funded mean Jaccard = {stab['mean_jaccard']:.3f}")
    stab_cew = jaccard_top_k(raw, k=50, metric="median_cew")
    print(f"[stability] Top-50 by median_cew mean Jaccard = {stab_cew['mean_jaccard']:.3f}")

    agg = aggregate_across_seeds(raw)
    gated = apply_gating(agg)
    print(f"\n[gating] {gated['gating_pass'].sum()}/{len(gated)} params pass gating")
    print(f"  passes_eff_sr:        {gated['passes_eff_sr'].sum()}")
    print(f"  passes_p10_wd:        {gated['passes_p10_wd'].sum()}")
    print(f"  passes_years_below:   {gated['passes_years_below'].sum()}")

    agg.to_csv(OUT_DIR / "baseline_agg.csv", index=False)
    gated.to_csv(OUT_DIR / "baseline_gated.csv", index=False)

    pool = gated[gated["gating_pass"]].copy()
    if len(pool) == 0:
        print("\n[!] NO PARAMS PASS GATING — falling back to top by eff_success_mean")
        pool = gated.nlargest(50, "eff_success_mean").copy()

    cols_show = [
        "target", "upper", "lower", "adj", "mode", "min_remain",
        "swr_mean", "eff_funded_mean", "eff_success_mean", "median_cew_mean",
        "p10_avg_wd_mean", "p90_max_drop_mean", "mean_years_below_floor_mean",
    ]
    cons_top = pool.nlargest(10, "eff_funded_mean")
    bal_top = pool.nlargest(10, "median_cew_mean")
    agg_top = pool.nlargest(10, "swr_mean")

    print("\n=== TIER 1: CONSERVATIVE (max eff_funded) ===")
    print(cons_top[cols_show].to_string(index=False))
    print("\n=== TIER 2: BALANCED (max median_cew) ===")
    print(bal_top[cols_show].to_string(index=False))
    print("\n=== TIER 3: AGGRESSIVE (max SWR) ===")
    print(agg_top[cols_show].to_string(index=False))

    # Union of Top-50 across three tiers (for Phase 3 sensitivity)
    cons_top50 = pool.nlargest(50, "eff_funded_mean")
    bal_top50 = pool.nlargest(50, "median_cew_mean")
    agg_top50 = pool.nlargest(50, "swr_mean")
    union = pd.concat([cons_top50, bal_top50, agg_top50]).drop_duplicates(
        subset=["target", "upper", "lower", "adj", "mode", "min_remain"]
    )
    union.to_csv(OUT_DIR / "phase3_candidates.csv", index=False)
    print(f"\n[phase3] {len(union)} unique candidates (union of 3-tier Top-50) → phase3_candidates.csv")


if __name__ == "__main__":
    main()
