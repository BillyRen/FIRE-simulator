"""Optimal asset allocation analysis v1 (2026-05-27).

Sweeps allocation grid across data sources, countries, start years,
strategies, withdrawal rates, retirement horizons, and leverage to identify
robust configurations and cross-scenario insights.

Plan: docs/optimal-allocation-plan-2026-05-27.md
Output:
  analysis/output/optimal_allocation/results.csv
  analysis/output/optimal_allocation/summary.md
"""
from __future__ import annotations

import sys
import time
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import (
    load_returns_data,
    load_fire_dataset,
    get_country_dfs,
    filter_by_country,
)
from simulator.sweep import pregenerate_raw_scenarios, sweep_allocations
from simulator.config import get_gdp_weights


# ────────────────────────────── parameters ──────────────────────────────────
INITIAL_PORTFOLIO = 1_000_000
NUM_SIMS = 2_000
MIN_BLOCK = 5
MAX_BLOCK = 15
SEED = 42
ALLOCATION_STEP = 0.1
RETIREMENT_AGE = 45
EXPENSE = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}
NEAR_OPTIMAL_THRESHOLD = 0.01  # within 1pp funded_ratio of best

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Scenario:
    data_source: str          # "jst" | "fire_dataset"
    country: str              # ISO or "ALL"
    pooling: str | None       # "gdp_sqrt" if country=="ALL"
    start_year: int
    retirement_years: int

    @property
    def bootstrap_key(self) -> tuple:
        return (self.data_source, self.country, self.pooling,
                self.start_year, self.retirement_years)


def build_raw_scenarios(sc: Scenario) -> dict[str, np.ndarray]:
    if sc.data_source == "jst":
        df_all = load_returns_data()
    elif sc.data_source == "fire_dataset":
        df_all = load_fire_dataset()
        if sc.country != "USA":
            raise ValueError("fire_dataset only supports country=USA")
    else:
        raise ValueError(f"unknown data_source: {sc.data_source}")

    if sc.country == "ALL":
        country_dfs = get_country_dfs(df_all, sc.start_year)
        weights = get_gdp_weights(list(country_dfs.keys()))
        returns_df = df_all[df_all["Year"] >= sc.start_year].reset_index(drop=True)
        return pregenerate_raw_scenarios(
            expense_ratios=EXPENSE,
            retirement_years=sc.retirement_years,
            min_block=MIN_BLOCK,
            max_block=MAX_BLOCK,
            num_simulations=NUM_SIMS,
            returns_df=returns_df,
            seed=SEED,
            country_dfs=country_dfs,
            country_weights=weights,
        )
    else:
        filtered = filter_by_country(df_all, sc.country, sc.start_year)
        return pregenerate_raw_scenarios(
            expense_ratios=EXPENSE,
            retirement_years=sc.retirement_years,
            min_block=MIN_BLOCK,
            max_block=MAX_BLOCK,
            num_simulations=NUM_SIMS,
            returns_df=filtered,
            seed=SEED,
            country_dfs=None,
            country_weights=None,
        )


@dataclass(frozen=True)
class Run:
    scenario: Scenario
    strategy: str             # "fixed" | "declining" | "smile"
    initial_wr: float         # 0.030 .. 0.045
    leverage: float           # 1.0 | 1.2

    @property
    def annual_withdrawal(self) -> float:
        return INITIAL_PORTFOLIO * self.initial_wr


# ────────────────────────────── grid build ──────────────────────────────────

WRS = [0.030, 0.035, 0.040, 0.045]
HORIZONS = [30, 45, 60]
STRATEGIES = ["fixed", "declining", "smile"]


def build_main_runs() -> list[Run]:
    runs: list[Run] = []

    # Main grid: JST × {USA, ALL} × {1900, 1970} × strategies × WRs × horizons
    for country, pooling in [("USA", None), ("ALL", "gdp_sqrt")]:
        for start_year in [1900, 1970]:
            for years in HORIZONS:
                sc = Scenario("jst", country, pooling, start_year, years)
                for strat in STRATEGIES:
                    for wr in WRS:
                        runs.append(Run(sc, strat, wr, 1.0))

    # FIRE_dataset supplement (USA only, fixed strategy, both start years, 45y horizon)
    for start_year in [1900, 1970]:
        sc = Scenario("fire_dataset", "USA", None, start_year, 45)
        for wr in WRS:
            runs.append(Run(sc, "fixed", wr, 1.0))

    # Leverage supplement: 1.2x, fixed, 45y, all WRs, JST USA + ALL
    for country, pooling in [("USA", None), ("ALL", "gdp_sqrt")]:
        sc = Scenario("jst", country, pooling, 1900, 45)
        for wr in WRS:
            runs.append(Run(sc, "fixed", wr, 1.2))

    # Cross-country robustness at baseline (1900, fixed, 4%, 45y)
    for c in ["CHE", "AUS", "JPN", "DEU"]:
        sc = Scenario("jst", c, None, 1900, 45)
        runs.append(Run(sc, "fixed", 0.04, 1.0))

    return runs


# ────────────────────────── allocation pareto helpers ───────────────────────

def annotate_pareto_and_near_optimal(rows: list[dict]) -> None:
    if not rows:
        return
    best_fr = max(r["funded_ratio"] for r in rows)
    for r in rows:
        r["is_near_optimal"] = (best_fr - r["funded_ratio"]) <= NEAR_OPTIMAL_THRESHOLD

    # Break funded_ratio ties by median_final desc so equal-FR rows do not
    # award Pareto to whichever allocation grid order placed first.
    sorted_by_fr = sorted(
        rows, key=lambda x: (-x["funded_ratio"], -x["median_final"]),
    )
    max_median = float("-inf")
    pareto_ids = set()
    for r in sorted_by_fr:
        if r["median_final"] >= max_median:
            pareto_ids.add(id(r))
            max_median = r["median_final"]
    for r in rows:
        r["is_pareto"] = id(r) in pareto_ids


# ────────────────────────────── main pipeline ───────────────────────────────

def run_all(runs: list[Run]) -> pd.DataFrame:
    raw_cache: dict[tuple, dict[str, np.ndarray]] = {}

    by_scenario: dict[tuple, list[Run]] = {}
    for r in runs:
        by_scenario.setdefault(r.scenario.bootstrap_key, []).append(r)

    rows: list[dict] = []
    total = len(runs)
    done = 0
    t0 = time.time()

    for key, group in by_scenario.items():
        sc = group[0].scenario
        print(f"[bootstrap] {key}  ({len(group)} runs)")
        raw = build_raw_scenarios(sc)
        raw_cache[key] = raw

        for r in group:
            res = sweep_allocations(
                raw_scenarios=raw,
                initial_portfolio=INITIAL_PORTFOLIO,
                annual_withdrawal=r.annual_withdrawal,
                allocation_step=ALLOCATION_STEP,
                withdrawal_strategy=r.strategy,
                retirement_age=RETIREMENT_AGE,
                cash_flows=None,
                leverage=r.leverage,
                borrowing_spread=0.02,
            )
            annotate_pareto_and_near_optimal(res)
            for ar in res:
                rows.append({
                    "data_source": sc.data_source,
                    "country": sc.country,
                    "pooling": sc.pooling or "",
                    "start_year": sc.start_year,
                    "retirement_years": sc.retirement_years,
                    "strategy": r.strategy,
                    "initial_wr": r.initial_wr,
                    "leverage": r.leverage,
                    "domestic_stock": ar["domestic_stock"],
                    "global_stock": ar["global_stock"],
                    "domestic_bond": ar["domestic_bond"],
                    "success_rate": ar["success_rate"],
                    "funded_ratio": ar["funded_ratio"],
                    "cvar_10": ar["cvar_10"],
                    "median_final": ar["median_final"],
                    "mean_final": ar["mean_final"],
                    "p90_final": ar["p90_final"],
                    "p10_depletion_year": ar["p10_depletion_year"] or 0,
                    "is_pareto": ar["is_pareto"],
                    "is_near_optimal": ar["is_near_optimal"],
                })
            done += 1
            if done % 20 == 0 or done == total:
                elapsed = time.time() - t0
                print(f"  progress {done}/{total} runs  ({elapsed:.1f}s)")

    return pd.DataFrame(rows)


# ────────────────────────────── analysis ────────────────────────────────────

def alloc_tag(row) -> str:
    a = int(round(row["domestic_stock"] * 100))
    b = int(round(row["global_stock"] * 100))
    c = int(round(row["domestic_bond"] * 100))
    return f"{a:02d}/{b:02d}/{c:02d}"


def cross_scenario_ranking(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["alloc"] = df.apply(alloc_tag, axis=1)
    df["scenario_key"] = (
        df["data_source"] + "|" + df["country"] + "|" +
        df["start_year"].astype(str) + "|" + df["retirement_years"].astype(str) +
        "|" + df["strategy"] + "|" + df["initial_wr"].map("{:.3f}".format) +
        "|" + df["leverage"].map("{:.1f}".format)
    )
    df["rank_fr"] = df.groupby("scenario_key")["funded_ratio"].rank(ascending=False, method="min")
    df["rank_cvar"] = df.groupby("scenario_key")["cvar_10"].rank(ascending=False, method="min")

    agg = df.groupby("alloc").agg(
        mean_rank_fr=("rank_fr", "mean"),
        median_rank_fr=("rank_fr", "median"),
        rank_fr_std=("rank_fr", "std"),
        mean_rank_cvar=("rank_cvar", "mean"),
        rank_cvar_std=("rank_cvar", "std"),
        pareto_count=("is_pareto", "sum"),
        near_optimal_count=("is_near_optimal", "sum"),
        mean_fr=("funded_ratio", "mean"),
        mean_success=("success_rate", "mean"),
        mean_cvar=("cvar_10", "mean"),
        n_scenarios=("scenario_key", "nunique"),
    ).reset_index()
    agg = agg.sort_values("mean_rank_fr").reset_index(drop=True)
    return agg


def best_per_scenario(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["alloc"] = df.apply(alloc_tag, axis=1)
    idx = df.groupby([
        "data_source", "country", "start_year", "retirement_years",
        "strategy", "initial_wr", "leverage",
    ])["funded_ratio"].idxmax()
    best = df.loc[idx].sort_values([
        "data_source", "country", "start_year", "retirement_years",
        "strategy", "initial_wr", "leverage",
    ]).reset_index(drop=True)
    return best[[
        "data_source", "country", "start_year", "retirement_years",
        "strategy", "initial_wr", "leverage", "alloc",
        "funded_ratio", "success_rate", "cvar_10", "median_final", "p90_final",
    ]]


def write_summary(df: pd.DataFrame, ranking: pd.DataFrame, per_scenario_best: pd.DataFrame) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Optimal Allocation Analysis — Summary (2026-05-27)")
    add("")
    add(f"- Total rows: {len(df):,}")
    add(f"- Unique scenarios: {df['data_source'].nunique()} sources × "
        f"{df['country'].nunique()} countries × {df['start_year'].nunique()} start years × "
        f"{df['retirement_years'].nunique()} horizons × {df['strategy'].nunique()} strategies × "
        f"{df['initial_wr'].nunique()} WRs × {df['leverage'].nunique()} leverage")
    add(f"- num_simulations={NUM_SIMS}, allocation_step={ALLOCATION_STEP}, seed={SEED}")
    add("")
    add("## Top 10 robust allocations (sorted by mean rank of funded_ratio across scenarios)")
    add("")
    add("| alloc (Dom/Intl/Bond) | mean_rank_fr | rank_std | pareto_count | near_opt_count | mean_FR | mean_success | mean_CVaR |")
    add("|---|---|---|---|---|---|---|---|")
    for _, r in ranking.head(10).iterrows():
        add(f"| {r['alloc']} | {r['mean_rank_fr']:.2f} | {r['rank_fr_std']:.2f} | "
            f"{int(r['pareto_count'])} | {int(r['near_optimal_count'])} | "
            f"{r['mean_fr']:.3f} | {r['mean_success']:.3f} | ${r['mean_cvar']:,.0f} |")
    add("")
    add("## Bottom 5 (lowest mean rank — sanity check)")
    add("")
    for _, r in ranking.tail(5).iterrows():
        add(f"- {r['alloc']}: mean_rank_fr={r['mean_rank_fr']:.2f}, mean_FR={r['mean_fr']:.3f}")
    add("")

    # Per-strategy best per (country, horizon, wr) — focus on USA/ALL only, default leverage
    add("## Per-scenario best allocation (JST, leverage=1.0, start_year=1900)")
    add("")
    sub = per_scenario_best[
        (per_scenario_best["data_source"] == "jst")
        & (per_scenario_best["leverage"] == 1.0)
        & (per_scenario_best["start_year"] == 1900)
    ]
    add("| country | years | strategy | wr | alloc | FR | success | median_final |")
    add("|---|---|---|---|---|---|---|---|")
    for _, r in sub.iterrows():
        add(f"| {r['country']} | {r['retirement_years']} | {r['strategy']} | "
            f"{r['initial_wr']:.1%} | {r['alloc']} | {r['funded_ratio']:.3f} | "
            f"{r['success_rate']:.3f} | ${r['median_final']:,.0f} |")
    add("")

    # Leverage 1.0 vs 1.2 at baseline — only paired countries
    add("## Leverage 1.0 vs 1.2 (JST, start_year=1900, 45y, fixed, USA/ALL only)")
    add("")
    lv_cmp = per_scenario_best[
        (per_scenario_best["data_source"] == "jst")
        & (per_scenario_best["start_year"] == 1900)
        & (per_scenario_best["retirement_years"] == 45)
        & (per_scenario_best["strategy"] == "fixed")
        & (per_scenario_best["country"].isin(["USA", "ALL"]))
    ]
    add("| country | leverage | wr | alloc | FR | success | CVaR |")
    add("|---|---|---|---|---|---|---|")
    for _, r in lv_cmp.iterrows():
        add(f"| {r['country']} | {r['leverage']:.1f} | {r['initial_wr']:.1%} | "
            f"{r['alloc']} | {r['funded_ratio']:.3f} | {r['success_rate']:.3f} | "
            f"${r['cvar_10']:,.0f} |")
    add("")

    # Data source comparison: FIRE_dataset USA vs JST USA at 45y, fixed
    add("## Data source comparison (USA, fixed, 45y, leverage=1.0)")
    add("")
    ds_cmp = per_scenario_best[
        (per_scenario_best["country"] == "USA")
        & (per_scenario_best["retirement_years"] == 45)
        & (per_scenario_best["strategy"] == "fixed")
        & (per_scenario_best["leverage"] == 1.0)
    ].sort_values(["initial_wr", "start_year", "data_source"])
    add("| data_source | start_year | wr | alloc | FR | success |")
    add("|---|---|---|---|---|---|")
    for _, r in ds_cmp.iterrows():
        add(f"| {r['data_source']} | {r['start_year']} | {r['initial_wr']:.1%} | "
            f"{r['alloc']} | {r['funded_ratio']:.3f} | {r['success_rate']:.3f} |")
    add("")

    # Cross-country robustness
    add("## Cross-country robustness (JST, start_year=1900, fixed, 45y, 4% WR)")
    add("")
    cc = per_scenario_best[
        (per_scenario_best["data_source"] == "jst")
        & (per_scenario_best["start_year"] == 1900)
        & (per_scenario_best["retirement_years"] == 45)
        & (per_scenario_best["strategy"] == "fixed")
        & (per_scenario_best["initial_wr"] == 0.04)
        & (per_scenario_best["leverage"] == 1.0)
    ].sort_values("country")
    add("| country | alloc | FR | success | median_final |")
    add("|---|---|---|---|---|")
    for _, r in cc.iterrows():
        add(f"| {r['country']} | {r['alloc']} | {r['funded_ratio']:.3f} | "
            f"{r['success_rate']:.3f} | ${r['median_final']:,.0f} |")
    add("")

    return "\n".join(lines)


def main():
    runs = build_main_runs()
    print(f"Total runs: {len(runs)}")
    df = run_all(runs)
    df.to_csv(OUTPUT_DIR / "results.csv", index=False)
    print(f"Wrote {OUTPUT_DIR / 'results.csv'}  ({len(df):,} rows)")

    ranking = cross_scenario_ranking(df)
    ranking.to_csv(OUTPUT_DIR / "ranking.csv", index=False)

    per_scenario = best_per_scenario(df)
    per_scenario.to_csv(OUTPUT_DIR / "per_scenario_best.csv", index=False)

    summary = write_summary(df, ranking, per_scenario)
    (OUTPUT_DIR / "summary.md").write_text(summary)
    print(f"Wrote {OUTPUT_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
