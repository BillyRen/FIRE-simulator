"""Optimal allocation analysis — guardrail strategy (2026-05-27).

Companion to optimal_allocation_v1.py. Replaces fixed/declining/smile with
risk-based guardrail:
  target=0.85, upper=0.99, lower=0.70, adj=0.10, mode=amount, mr=5
Input mode = portfolio: feed 1M, infer init_wd from
find_rate_for_target(target=0.85). This is the same SWR as fixed at that
target; guardrail uplift shows up in eff_FR / p10_min_wd / cvar_10 instead.

Plan: docs/optimal-allocation-guardrail-plan-2026-05-27.md
Output:
  analysis/output/optimal_allocation/guardrail_results.csv
  analysis/output/optimal_allocation/guardrail_summary.md
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

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
from simulator.sweep import pregenerate_raw_scenarios, raw_to_combined
from simulator.guardrail import (
    build_success_rate_table,
    run_guardrail_simulation,
)
from simulator.statistics import (
    compute_effective_funded_ratio,
    compute_success_rate,
)
from simulator.config import get_gdp_weights


# ─────────────── shared params (kept parallel to optimal_allocation_v1) ─────
INITIAL_PORTFOLIO = 1_000_000
NUM_SIMS = 2_000
MIN_BLOCK = 5
MAX_BLOCK = 15
SEED = 42
ALLOCATION_STEP = 0.1
RETIREMENT_AGE = 45
EXPENSE = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}
BORROWING_SPREAD = 0.02
NEAR_OPTIMAL_THRESHOLD = 0.01
CONSUMPTION_FLOOR = 0.50

# Guardrail params (user-specified)
GR_TARGET = 0.85
GR_UPPER = 0.99
GR_LOWER = 0.70
GR_ADJ_PCT = 0.10
GR_MODE = "amount"
GR_MIN_REMAIN = 5

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Scenario:
    data_source: str          # "jst" | "fire_dataset"
    country: str              # ISO or "ALL"
    pooling: str | None
    start_year: int
    retirement_years: int
    leverage: float

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
            min_block=MIN_BLOCK, max_block=MAX_BLOCK,
            num_simulations=NUM_SIMS,
            returns_df=returns_df,
            seed=SEED,
            country_dfs=country_dfs, country_weights=weights,
        )
    filtered = filter_by_country(df_all, sc.country, sc.start_year)
    return pregenerate_raw_scenarios(
        expense_ratios=EXPENSE,
        retirement_years=sc.retirement_years,
        min_block=MIN_BLOCK, max_block=MAX_BLOCK,
        num_simulations=NUM_SIMS,
        returns_df=filtered,
        seed=SEED,
        country_dfs=None, country_weights=None,
    )


def build_scenarios() -> list[Scenario]:
    out: list[Scenario] = []
    # Main: jst × {USA, ALL} × {1900, 1970} × {30, 45, 60}
    for country, pooling in [("USA", None), ("ALL", "gdp_sqrt")]:
        for sy in [1900, 1970]:
            for years in [30, 45, 60]:
                out.append(Scenario("jst", country, pooling, sy, years, 1.0))
    # FIRE_dataset supplement
    for sy in [1900, 1970]:
        out.append(Scenario("fire_dataset", "USA", None, sy, 45, 1.0))
    # Leverage 1.2 supplement
    for country, pooling in [("USA", None), ("ALL", "gdp_sqrt")]:
        out.append(Scenario("jst", country, pooling, 1900, 45, 1.2))
    # Cross-country at baseline
    for c in ["CHE", "AUS", "JPN", "DEU"]:
        out.append(Scenario("jst", c, None, 1900, 45, 1.0))
    return out


def gen_allocations(step: float) -> list[tuple[float, float, float]]:
    out = []
    steps = int(round(1.0 / step))
    for a in range(steps + 1):
        for b in range(steps + 1 - a):
            c = steps - a - b
            out.append((a * step, b * step, c * step))
    return out


# ─────────────── per-allocation guardrail metrics ──────────────────────────

def alloc_metrics(
    raw: dict[str, np.ndarray],
    alloc: tuple[float, float, float],
    leverage: float,
    retirement_years: int,
) -> dict:
    w_us, w_intl, w_bond = alloc
    real_returns = raw_to_combined(
        raw,
        {"domestic_stock": w_us, "global_stock": w_intl, "domestic_bond": w_bond},
        leverage=leverage,
        borrowing_spread=BORROWING_SPREAD,
    )

    # Guardrail success-rate table is per-allocation (depends on real_returns)
    rate_grid, table = build_success_rate_table(real_returns)

    init_p, init_wd, traj, wds = run_guardrail_simulation(
        scenarios=real_returns,
        target_success=GR_TARGET,
        upper_guardrail=GR_UPPER,
        lower_guardrail=GR_LOWER,
        adjustment_pct=GR_ADJ_PCT,
        retirement_years=retirement_years,
        min_remaining_years=GR_MIN_REMAIN,
        table=table, rate_grid=rate_grid,
        adjustment_mode=GR_MODE,
        initial_portfolio=INITIAL_PORTFOLIO,
    )

    success_rate = compute_success_rate(traj, retirement_years)
    eff_fr, eff_sr = compute_effective_funded_ratio(
        wds, init_wd, retirement_years,
        consumption_floor=CONSUMPTION_FLOOR, trajectories=traj,
    )

    final_values = traj[:, -1]
    sorted_finals = np.sort(final_values)
    n10 = max(1, int(0.1 * len(final_values)))
    cvar_10 = float(np.mean(sorted_finals[:n10]))

    # P10 of min-positive withdrawal per simulation
    mask = wds > 0
    filled = np.where(mask, wds, np.inf)
    min_wd_per_sim = np.where(mask.any(axis=1), np.min(filled, axis=1), 0.0)
    p10_min_wd = float(np.percentile(min_wd_per_sim, 10))

    median_total_wd = float(np.median(np.sum(wds, axis=1)))
    median_final = float(np.median(final_values))

    floor_val = init_wd * CONSUMPTION_FLOOR
    mean_years_below_floor = float(np.mean((wds < floor_val).sum(axis=1)))

    return {
        "domestic_stock": round(w_us, 4),
        "global_stock": round(w_intl, 4),
        "domestic_bond": round(w_bond, 4),
        "initial_wd": init_wd,
        "initial_swr": init_wd / INITIAL_PORTFOLIO,
        "success_rate": success_rate,
        "eff_success_rate": eff_sr,
        "eff_funded_ratio": eff_fr,
        "median_final": median_final,
        "cvar_10_final": cvar_10,
        "p10_min_wd": p10_min_wd,
        "median_total_wd": median_total_wd,
        "mean_years_below_floor": mean_years_below_floor,
    }


# ─────────────── pareto / near-optimal ──────────────────────────────────────

def annotate_pareto(rows: list[dict]) -> None:
    if not rows:
        return
    best = max(r["eff_funded_ratio"] for r in rows)
    for r in rows:
        r["is_near_optimal"] = (best - r["eff_funded_ratio"]) <= NEAR_OPTIMAL_THRESHOLD

    sorted_by_fr = sorted(
        rows, key=lambda x: (-x["eff_funded_ratio"], -x["median_final"]),
    )
    max_med = float("-inf")
    pareto_ids = set()
    for r in sorted_by_fr:
        if r["median_final"] >= max_med:
            pareto_ids.add(id(r))
            max_med = r["median_final"]
    for r in rows:
        r["is_pareto"] = id(r) in pareto_ids


# ─────────────── pipeline ──────────────────────────────────────────────────

def run_all() -> pd.DataFrame:
    scenarios = build_scenarios()
    allocs = gen_allocations(ALLOCATION_STEP)
    total = len(scenarios) * len(allocs)
    print(f"Scenarios: {len(scenarios)}, allocs/scenario: {len(allocs)}, total runs: {total}")

    rows: list[dict] = []
    done = 0
    t0 = time.time()
    raw_cache: dict[tuple, dict[str, np.ndarray]] = {}

    for sc in scenarios:
        key = sc.bootstrap_key
        if key not in raw_cache:
            print(f"[bootstrap] {key}")
            raw_cache[key] = build_raw_scenarios(sc)
        raw = raw_cache[key]

        scenario_rows: list[dict] = []
        for alloc in allocs:
            m = alloc_metrics(raw, alloc, sc.leverage, sc.retirement_years)
            base = {
                "data_source": sc.data_source,
                "country": sc.country,
                "pooling": sc.pooling or "",
                "start_year": sc.start_year,
                "retirement_years": sc.retirement_years,
                "leverage": sc.leverage,
                **m,
            }
            scenario_rows.append(base)
            done += 1
            if done % 100 == 0:
                print(f"  progress {done}/{total}  ({time.time()-t0:.0f}s)")

        annotate_pareto(scenario_rows)
        rows.extend(scenario_rows)

    print(f"Total {time.time()-t0:.0f}s")
    return pd.DataFrame(rows)


# ─────────────── analysis ──────────────────────────────────────────────────

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
        "|" + df["leverage"].map("{:.1f}".format)
    )
    df["rank_eff_fr"] = df.groupby("scenario_key")["eff_funded_ratio"].rank(
        ascending=False, method="min",
    )
    df["rank_p10_wd"] = df.groupby("scenario_key")["p10_min_wd"].rank(
        ascending=False, method="min",
    )
    df["rank_swr"] = df.groupby("scenario_key")["initial_swr"].rank(
        ascending=False, method="min",
    )
    # Composite: equal-weight average of the three ranks. Mitigates the
    # bond-heavy bias of pure eff_FR ranking (eff_FR rewards low-volatility
    # paths that mechanically clear the consumption floor at very low SWR).
    df["rank_composite"] = (
        df["rank_eff_fr"] + df["rank_p10_wd"] + df["rank_swr"]
    ) / 3.0

    agg = df.groupby("alloc").agg(
        mean_rank_eff_fr=("rank_eff_fr", "mean"),
        rank_eff_fr_std=("rank_eff_fr", "std"),
        mean_rank_p10_wd=("rank_p10_wd", "mean"),
        mean_rank_swr=("rank_swr", "mean"),
        mean_rank_composite=("rank_composite", "mean"),
        rank_composite_std=("rank_composite", "std"),
        pareto_count=("is_pareto", "sum"),
        near_optimal_count=("is_near_optimal", "sum"),
        mean_eff_fr=("eff_funded_ratio", "mean"),
        mean_eff_sr=("eff_success_rate", "mean"),
        mean_success=("success_rate", "mean"),
        mean_swr=("initial_swr", "mean"),
        mean_p10_wd=("p10_min_wd", "mean"),
        mean_yrs_below_floor=("mean_years_below_floor", "mean"),
        n_scenarios=("scenario_key", "nunique"),
    ).reset_index()
    agg = agg.sort_values("mean_rank_composite").reset_index(drop=True)
    return agg


def best_per_scenario(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["alloc"] = df.apply(alloc_tag, axis=1)
    keys = ["data_source", "country", "start_year",
            "retirement_years", "leverage"]
    idx = df.groupby(keys)["eff_funded_ratio"].idxmax()
    best = df.loc[idx].sort_values(keys).reset_index(drop=True)
    return best[keys + [
        "alloc", "initial_swr", "success_rate", "eff_success_rate",
        "eff_funded_ratio", "median_final", "cvar_10_final",
        "p10_min_wd", "mean_years_below_floor",
    ]]


def write_summary(df: pd.DataFrame, ranking: pd.DataFrame,
                  per_scenario: pd.DataFrame) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Guardrail × Allocation Analysis — Summary (2026-05-27)")
    add("")
    add(f"Guardrail params: target={GR_TARGET} / up={GR_UPPER} / lo={GR_LOWER} "
        f"/ adj={GR_ADJ_PCT} / mode={GR_MODE} / mr={GR_MIN_REMAIN}")
    add(f"num_simulations={NUM_SIMS}, alloc step={ALLOCATION_STEP}, seed={SEED}, "
        f"consumption_floor={CONSUMPTION_FLOOR}")
    add(f"Total rows: {len(df):,}; unique scenarios: {df['data_source'].nunique()} "
        f"sources × {df['country'].nunique()} countries × {df['start_year'].nunique()} "
        f"start years × {df['retirement_years'].nunique()} horizons × "
        f"{df['leverage'].nunique()} leverage")
    add("")

    add("## Top 10 robust allocations (by COMPOSITE rank = avg of eff_FR, P10_min_wd, init_SWR)")
    add("")
    add("> Composite avoids the bond-heavy bias of pure eff_FR. Pure eff_FR "
        "rewards minimal-volatility paths whose low SWR mechanically clears "
        "the 50% consumption floor; composite weighs SWR and worst-decile "
        "consumption equally.")
    add("")
    add("| Alloc | composite | eff_FR_rank | P10_wd_rank | SWR_rank | pareto | "
        "near_opt | mean_eff_FR | mean_SWR | mean_P10_wd | yrs<floor |")
    add("|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in ranking.head(10).iterrows():
        add(f"| {r['alloc']} | {r['mean_rank_composite']:.2f} | "
            f"{r['mean_rank_eff_fr']:.1f} | {r['mean_rank_p10_wd']:.1f} | "
            f"{r['mean_rank_swr']:.1f} | {int(r['pareto_count'])} | "
            f"{int(r['near_optimal_count'])} | {r['mean_eff_fr']:.3f} | "
            f"{r['mean_swr']:.3%} | ${r['mean_p10_wd']:,.0f} | "
            f"{r['mean_yrs_below_floor']:.1f} |")
    add("")
    add("## Top 10 by pure eff_FR rank (for contrast — beware bond-heavy bias)")
    add("")
    by_efr = ranking.sort_values("mean_rank_eff_fr").head(10)
    add("| Alloc | eff_FR_rank | composite | mean_eff_FR | mean_SWR | mean_P10_wd |")
    add("|---|---|---|---|---|---|")
    for _, r in by_efr.iterrows():
        add(f"| {r['alloc']} | {r['mean_rank_eff_fr']:.2f} | "
            f"{r['mean_rank_composite']:.2f} | {r['mean_eff_fr']:.3f} | "
            f"{r['mean_swr']:.3%} | ${r['mean_p10_wd']:,.0f} |")
    add("")
    add("## Bottom 5 (composite)")
    add("")
    for _, r in ranking.tail(5).iterrows():
        add(f"- {r['alloc']}: composite={r['mean_rank_composite']:.2f}, "
            f"mean_eff_FR={r['mean_eff_fr']:.3f}, mean_SWR={r['mean_swr']:.3%}, "
            f"P10_wd=${r['mean_p10_wd']:,.0f}")
    add("")

    add("## Per-scenario best allocation (eff_FR), leverage=1.0, jst")
    add("")
    sub = per_scenario[
        (per_scenario["data_source"] == "jst")
        & (per_scenario["leverage"] == 1.0)
    ]
    add("| country | start | years | alloc | init_SWR | eff_FR | eff_SR | "
        "success | p10_min_wd |")
    add("|---|---|---|---|---|---|---|---|---|")
    for _, r in sub.iterrows():
        add(f"| {r['country']} | {r['start_year']} | {r['retirement_years']} | "
            f"{r['alloc']} | {r['initial_swr']:.3%} | {r['eff_funded_ratio']:.3f} | "
            f"{r['eff_success_rate']:.3f} | {r['success_rate']:.3f} | "
            f"${r['p10_min_wd']:,.0f} |")
    add("")

    add("## Leverage 1.0 vs 1.2 (JST, 1900, 45y, USA/ALL only)")
    add("")
    lv = per_scenario[
        (per_scenario["data_source"] == "jst")
        & (per_scenario["start_year"] == 1900)
        & (per_scenario["retirement_years"] == 45)
        & (per_scenario["country"].isin(["USA", "ALL"]))
    ]
    add("| country | leverage | alloc | init_SWR | eff_FR | p10_min_wd | yrs<floor |")
    add("|---|---|---|---|---|---|---|")
    for _, r in lv.iterrows():
        add(f"| {r['country']} | {r['leverage']:.1f} | {r['alloc']} | "
            f"{r['initial_swr']:.3%} | {r['eff_funded_ratio']:.3f} | "
            f"${r['p10_min_wd']:,.0f} | {r['mean_years_below_floor']:.1f} |")
    add("")

    add("## Data source comparison (USA, 45y, leverage=1.0)")
    add("")
    ds = per_scenario[
        (per_scenario["country"] == "USA")
        & (per_scenario["retirement_years"] == 45)
        & (per_scenario["leverage"] == 1.0)
    ].sort_values(["start_year", "data_source"])
    add("| data_source | start | alloc | init_SWR | eff_FR | p10_min_wd |")
    add("|---|---|---|---|---|---|")
    for _, r in ds.iterrows():
        add(f"| {r['data_source']} | {r['start_year']} | {r['alloc']} | "
            f"{r['initial_swr']:.3%} | {r['eff_funded_ratio']:.3f} | "
            f"${r['p10_min_wd']:,.0f} |")
    add("")

    add("## Cross-country (JST, 1900, 45y, leverage=1.0)")
    add("")
    cc = per_scenario[
        (per_scenario["data_source"] == "jst")
        & (per_scenario["start_year"] == 1900)
        & (per_scenario["retirement_years"] == 45)
        & (per_scenario["leverage"] == 1.0)
    ].sort_values("country")
    add("| country | alloc | init_SWR | eff_FR | success | p10_min_wd | yrs<floor |")
    add("|---|---|---|---|---|---|---|")
    for _, r in cc.iterrows():
        add(f"| {r['country']} | {r['alloc']} | {r['initial_swr']:.3%} | "
            f"{r['eff_funded_ratio']:.3f} | {r['success_rate']:.3f} | "
            f"${r['p10_min_wd']:,.0f} | {r['mean_years_below_floor']:.1f} |")
    add("")

    return "\n".join(lines)


def main():
    df = run_all()
    df.to_csv(OUTPUT_DIR / "guardrail_results.csv", index=False)
    print(f"Wrote {OUTPUT_DIR / 'guardrail_results.csv'} ({len(df):,} rows)")

    ranking = cross_scenario_ranking(df)
    ranking.to_csv(OUTPUT_DIR / "guardrail_ranking.csv", index=False)

    per_scenario = best_per_scenario(df)
    per_scenario.to_csv(OUTPUT_DIR / "guardrail_per_scenario_best.csv", index=False)

    (OUTPUT_DIR / "guardrail_summary.md").write_text(
        write_summary(df, ranking, per_scenario)
    )
    print(f"Wrote {OUTPUT_DIR / 'guardrail_summary.md'}")


if __name__ == "__main__":
    main()
