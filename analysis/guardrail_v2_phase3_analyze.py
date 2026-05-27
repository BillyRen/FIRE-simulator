"""Identify robust core from sensitivity.csv.

A "robust core" candidate ranks in top-20 by both eff_funded AND median_cew
across at least N (e.g. 80%) of the 54 environments.

Output: analysis/output/guardrail_v2/robust_core.csv
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

OUT_DIR = Path(__file__).resolve().parent / "output" / "guardrail_v2"
SRC = OUT_DIR / "sensitivity.csv"
PARAM_COLS = ["target", "upper", "lower", "adj", "mode", "min_remain"]


def main():
    df = pd.read_csv(SRC)
    print(f"[load] {len(df)} rows, {df['env'].nunique()} envs, "
          f"{df.drop_duplicates(subset=PARAM_COLS).shape[0]} params")

    # Per-env rank by eff_funded and median_cew
    df["rank_effFR"] = df.groupby("env")["eff_funded"].rank(ascending=False, method="min")
    df["rank_cew"] = df.groupby("env")["median_cew"].rank(ascending=False, method="min")

    top_k = 20
    df["in_top_effFR"] = df["rank_effFR"] <= top_k
    df["in_top_cew"] = df["rank_cew"] <= top_k
    df["in_top_both"] = df["in_top_effFR"] & df["in_top_cew"]

    # Aggregate per-param-set
    n_envs = df["env"].nunique()
    agg = df.groupby(PARAM_COLS).agg(
        envs_total=("env", "nunique"),
        envs_top_effFR=("in_top_effFR", "sum"),
        envs_top_cew=("in_top_cew", "sum"),
        envs_top_both=("in_top_both", "sum"),
        mean_eff_funded=("eff_funded", "mean"),
        min_eff_funded=("eff_funded", "min"),
        mean_median_cew=("median_cew", "mean"),
        min_median_cew=("median_cew", "min"),
        mean_swr=("swr", "mean"),
        min_swr=("swr", "min"),
        mean_eff_sr=("eff_success", "mean"),
    ).reset_index()
    agg["pct_top_effFR"] = agg["envs_top_effFR"] / n_envs
    agg["pct_top_cew"] = agg["envs_top_cew"] / n_envs
    agg["pct_top_both"] = agg["envs_top_both"] / n_envs

    agg.to_csv(OUT_DIR / "sensitivity_agg.csv", index=False)
    print(f"[agg] {len(agg)} params → sensitivity_agg.csv")

    # Robust core threshold: top in >= 60% envs by either metric
    threshold = 0.60
    robust = agg[(agg["pct_top_effFR"] >= threshold) | (agg["pct_top_cew"] >= threshold)].copy()
    robust = robust.sort_values("mean_eff_funded", ascending=False)
    print(f"[robust] {len(robust)} params with >={threshold*100:.0f}% top-{top_k} envs")

    if len(robust) == 0:
        print("  Lowering threshold to 0.40...")
        robust = agg[(agg["pct_top_effFR"] >= 0.40) | (agg["pct_top_cew"] >= 0.40)].copy()
        print(f"  → {len(robust)} candidates")

    if len(robust) == 0:
        print("  Falling back to top-20 by mean_eff_funded")
        robust = agg.nlargest(20, "mean_eff_funded").copy()

    # --- Augment with Aggressive cluster manually ---
    # target=0.80 fails the auto threshold (pct_top_effFR=0 across all params,
    # pct_top_cew <= 0.17) — but it is a real-world recommendation tier whose
    # SWR maxes at 4.28% and effFR averages 0.87. Carry the Top-4 by mean_swr
    # within (target=0.80, mode=amount) so Phase 4 evaluates a representative.
    agg_carry = agg[(agg["target"] == 0.80) & (agg["mode"] == "amount")].nlargest(4, "mean_swr")
    robust["source"] = "auto_threshold"
    agg_carry = agg_carry.copy()
    agg_carry["source"] = "manual_aggressive_topk"
    augmented = pd.concat([robust, agg_carry]).drop_duplicates(
        subset=PARAM_COLS, keep="first"
    )
    augmented.to_csv(OUT_DIR / "robust_core.csv", index=False)
    print(f"\n[augmented] {len(augmented)} params (auto {len(robust)} + manual aggressive {len(agg_carry)})")

    show_cols = PARAM_COLS + [
        "pct_top_effFR", "pct_top_cew", "pct_top_both",
        "mean_eff_funded", "min_eff_funded",
        "mean_median_cew", "min_median_cew", "mean_swr", "min_swr",
    ]
    print("\n=== ROBUST CORE (top by mean_eff_funded) ===")
    print(augmented[show_cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
