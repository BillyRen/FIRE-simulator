"""CEW-primary allocation optimization with housing + gold (2026-06-10).

Extends optimal_allocation_cew.py from 3 financial assets to 5:
  domestic_stock / global_stock / domestic_bond / housing / gold

Same objective framework:
  max median CEW (gamma=2, delta=0.02)
  s.t. success_rate >= 0.90 (tail severe_fail reported)
  tie-break consumption-path Ulcer

Housing is modeled as an INDIVIDUAL property per user spec (2026-06-10):
  - volatility 1.5x the housing index: idiosyncratic real-space noise with
    sigma = sqrt(1.5^2 - 1) * sigma_index (same method as
    multi_asset_allocation.py v3; implies corr ~2/3 with the index),
    individual real return floored at -100%
  - 2.0%/yr maintenance cost (expense ratio on housing)
Gold: jst_gold.csv local-currency nominal returns, 0.5%/yr holding cost.
Financial assets keep 0.5%/yr expense.

Data universe: countries with complete 6-column data (housing+gold) from 1900;
slightly narrower than jst_returns alone, so the 3-asset corner of this grid
is the apples-to-apples baseline, not the previous run's numbers.

Phases:
  1. Full 5-asset simplex grid (10pp, 1001 combos), seed 42, shared bootstrap
  2. Multi-seed confirmation (independent spaced seeds) for top candidates
  3. High-N (10000) confirmation for the finalists

Output: analysis/output/optimal_allocation/cew_multi_{results,multiseed}.csv
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

from simulator.bootstrap import block_bootstrap_pooled_np
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate

from multi_asset_allocation import (
    load_nominal_arrays, ASSETS, NOMINAL_COLS, IDX_INFL, HOUSING_IDX,
    N_ASSETS, REAL_CLIP, compositions,
)
from optimal_allocation_cew import (
    compute_cew, per_path_funded_ratio, consumption_ulcer,
)

# ─────────────── parameters ────────────────────────────────────────────────
INITIAL_PORTFOLIO = 1_000_000.0
NUM_SIMS = 2_000
HORIZON = 50
MIN_BLOCK, MAX_BLOCK = 5, 15
START_YEAR = 1900
STEP = 0.10
SEED = 42
CONFIRM_SEEDS = [5042, 10042, 15042, 20042]  # bootstrap_tensor uses one rng
HIGHN_SIMS = 10_000
HIGHN_SEED = 777_000

FIN_EXPENSE = 0.005
HOUSING_EXPENSE = 0.020          # user spec: 2%/yr maintenance
GOLD_EXPENSE = 0.005
VOL_MULT = 1.5                   # user spec: individual property vol 1.5x index
CONSUMPTION_FLOOR = 0.50

GR_TARGET, GR_LOWER = 0.85, 0.75
GR_UPPER, GR_ADJ, GR_MODE, GR_MIN_REMAIN = 0.99, 0.05, "amount", 1
SR_FLOOR = 0.90
TOP_K_CONFIRM = 8
TOP_TAIL_CONFIRM = 3  # best p10_cew among feasible, added to phase-2 set

GOLD_IDX = ASSETS.index("gold")
EXPENSE_VEC = np.full(N_ASSETS, FIN_EXPENSE)
EXPENSE_VEC[HOUSING_IDX] = HOUSING_EXPENSE
EXPENSE_VEC[GOLD_IDX] = GOLD_EXPENSE

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────── data / bootstrap ───────────────────────────────────────────

def pooled_housing_real_vol(arrays: dict[str, np.ndarray]) -> float:
    """Equal-weight-per-country pooled real housing index volatility."""
    vals, w = [], []
    for c, a in arrays.items():
        r = (1.0 + a[:, HOUSING_IDX]) / (1.0 + a[:, IDX_INFL]) - 1.0
        r = np.clip(r, *REAL_CLIP)
        vals.append(r)
        w.append(np.full(len(r), 1.0 / len(r)))
    vals = np.concatenate(vals)
    w = np.concatenate(w)
    w = w / w.sum()
    mean = w @ vals
    return float(np.sqrt(w @ (vals - mean) ** 2))


def bootstrap_tensor_equal(arrays, num_sims, horizon, seed) -> np.ndarray:
    """Pooled equal-probability bootstrap of the 6-column nominal tensor."""
    rng = np.random.default_rng(seed)
    clist = list(arrays.keys())
    carr = [arrays[c] for c in clist]
    clens = [len(a) for a in carr]
    probs = np.full(len(clist), 1.0 / len(clist))
    out = np.empty((num_sims, horizon, len(NOMINAL_COLS)))
    for s in range(num_sims):
        out[s] = block_bootstrap_pooled_np(
            carr, clens, probs, horizon, MIN_BLOCK, MAX_BLOCK, rng)
    return out


def make_scenario_builder(tensor: np.ndarray, sigma_real: float, noise_seed: int):
    """Precompute shared pieces; return f(weights) -> real returns (S,H)."""
    nominal_assets = tensor[:, :, :N_ASSETS]
    one_plus_infl = 1.0 + tensor[:, :, IDX_INFL]
    rng = np.random.default_rng(noise_seed)
    noise_unit = rng.standard_normal(tensor.shape[:2])
    e_h = EXPENSE_VEC[HOUSING_IDX]
    hr_index = (1.0 + nominal_assets[:, :, HOUSING_IDX] - e_h) / one_plus_infl - 1.0
    hr_indiv = np.maximum(hr_index + sigma_real * noise_unit, -1.0)
    delta_h = hr_indiv - hr_index

    def build(w: np.ndarray) -> np.ndarray:
        nom_port = nominal_assets @ w - float(w @ EXPENSE_VEC)
        real = (1.0 + nom_port) / one_plus_infl - 1.0
        return real + w[HOUSING_IDX] * delta_h

    return build


# ─────────────── per-allocation guardrail metrics ───────────────────────────

def alloc_metrics(real_returns: np.ndarray, horizon: int) -> dict:
    rate_grid, table = build_success_rate_table(real_returns)
    _, init_wd, traj, wds, _ = run_guardrail_simulation(
        scenarios=real_returns,
        target_success=GR_TARGET,
        upper_guardrail=GR_UPPER,
        lower_guardrail=GR_LOWER,
        adjustment_pct=GR_ADJ,
        retirement_years=horizon,
        min_remaining_years=GR_MIN_REMAIN,
        table=table, rate_grid=rate_grid,
        adjustment_mode=GR_MODE,
        initial_portfolio=INITIAL_PORTFOLIO,
    )
    cew = compute_cew(wds)
    fr_paths = per_path_funded_ratio(traj, horizon)
    min_wd = np.min(wds, axis=1)
    eff_fr, eff_sr = compute_effective_funded_ratio(
        wds, init_wd, horizon,
        consumption_floor=CONSUMPTION_FLOOR, trajectories=traj,
    )
    return {
        "init_swr": init_wd / INITIAL_PORTFOLIO,
        "success_rate": compute_success_rate(traj, horizon),
        "severe_fail_prob": float(np.mean(fr_paths < 0.5)),
        "median_cew": float(np.median(cew)),
        "p10_cew": float(np.percentile(cew, 10)),
        "median_ulcer": float(np.median(consumption_ulcer(wds))),
        "eff_funded_ratio": eff_fr,
        "p10_min_wd": float(np.percentile(min_wd, 10)),
        "median_final": float(np.median(traj[:, -1])),
    }


def gen_allocations() -> np.ndarray:
    n = int(round(1.0 / STEP))
    return np.array(compositions(N_ASSETS, n), dtype=float) * STEP


def tag(w: np.ndarray) -> str:
    return "/".join(f"{int(round(x*100)):02d}" for x in w)


# ─────────────── phases ─────────────────────────────────────────────────────

def run_phase1(arrays, sigma_real) -> pd.DataFrame:
    allocs = gen_allocations()
    print(f"[phase1] grid {len(allocs)} combos, {NUM_SIMS} sims, seed={SEED}")
    tensor = bootstrap_tensor_equal(arrays, NUM_SIMS, HORIZON, SEED)
    build = make_scenario_builder(tensor, sigma_real, noise_seed=SEED * 7 + 1234)
    rows = []
    t0 = time.time()
    for i, w in enumerate(allocs):
        m = alloc_metrics(build(w), HORIZON)
        rows.append({"alloc": tag(w),
                     **{a: round(w[j], 4) for j, a in enumerate(ASSETS)},
                     **m})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(allocs)}  ({time.time()-t0:.0f}s)")
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "cew_multi_results.csv", index=False)
    print(f"[phase1] done {time.time()-t0:.0f}s -> cew_multi_results.csv")
    return df


def run_phase2(arrays, sigma_real, df: pd.DataFrame) -> pd.DataFrame:
    feas = df[df.success_rate >= SR_FLOOR].sort_values(
        "median_cew", ascending=False)
    # Top-K by CEW plus the best tail candidates (p10_cew) so that
    # tail-robust alternatives (e.g. gold sleeves) are also seed-confirmed.
    cand = pd.concat([
        feas.head(TOP_K_CONFIRM),
        feas.sort_values("p10_cew", ascending=False).head(TOP_TAIL_CONFIRM),
    ]).drop_duplicates(subset="alloc")
    if cand.empty:
        print("[phase2] no feasible candidates; confirming top-3 by success")
        cand = df.sort_values("success_rate", ascending=False).head(3)
    weights = cand[ASSETS].to_numpy()
    tags = cand["alloc"].tolist()
    print(f"[phase2] confirming {tags} across seeds {CONFIRM_SEEDS}")
    rows = [dict(r, seed=SEED) for r in
            df[df.alloc.isin(tags)].to_dict("records")]
    for seed in CONFIRM_SEEDS:
        tensor = bootstrap_tensor_equal(arrays, NUM_SIMS, HORIZON, seed)
        build = make_scenario_builder(tensor, sigma_real, noise_seed=seed * 7 + 1234)
        for w, t in zip(weights, tags):
            m = alloc_metrics(build(w), HORIZON)
            rows.append({"alloc": t, "seed": seed, **m})
    ms = pd.DataFrame(rows)
    ms.to_csv(OUTPUT_DIR / "cew_multi_multiseed.csv", index=False)
    agg = ms.groupby("alloc").agg(
        sr_mean=("success_rate", "mean"),
        sr_min=("success_rate", "min"),
        seeds_ok=("success_rate", lambda s: int((s >= SR_FLOOR).sum())),
        cew_mean=("median_cew", "mean"),
        cew_min=("median_cew", "min"),
        p10cew_mean=("p10_cew", "mean"),
        ulcer_mean=("median_ulcer", "mean"),
        severe_mean=("severe_fail_prob", "mean"),
        swr_mean=("init_swr", "mean"),
        p10wd_mean=("p10_min_wd", "mean"),
    ).sort_values("cew_mean", ascending=False)
    print("\n[phase2] cross-seed aggregation "
          f"(n_seeds={1+len(CONFIRM_SEEDS)}; feasible needs seeds_ok==all):")
    print(agg.to_string(formatters={
        "cew_mean": "{:,.0f}".format, "cew_min": "{:,.0f}".format,
        "p10cew_mean": "{:,.0f}".format, "p10wd_mean": "{:,.0f}".format,
        "swr_mean": "{:.3%}".format}))
    return agg


def run_phase3(arrays, sigma_real, agg: pd.DataFrame, df: pd.DataFrame) -> None:
    n_seeds = 1 + len(CONFIRM_SEEDS)
    robust = agg[agg.seeds_ok == n_seeds]
    finalists = robust.head(3).index.tolist()
    if not finalists:
        print("[phase3] no robust finalists; skipping high-N")
        return
    print(f"\n[phase3] high-N ({HIGHN_SIMS}) confirmation: {finalists}")
    tensor = bootstrap_tensor_equal(arrays, HIGHN_SIMS, HORIZON, HIGHN_SEED)
    build = make_scenario_builder(tensor, sigma_real,
                                  noise_seed=HIGHN_SEED * 7 + 1234)
    lookup = df.set_index("alloc")
    print(f"{'alloc':>15} {'success':>8} {'severe':>7} {'med_CEW':>9} "
          f"{'p10_CEW':>9} {'ulcer':>7} {'init_SWR':>8} {'p10_min_wd':>10}")
    for t in finalists:
        w = lookup.loc[t, ASSETS].to_numpy(dtype=float)
        m = alloc_metrics(build(w), HORIZON)
        print(f"{t:>15} {m['success_rate']:8.4f} {m['severe_fail_prob']:7.4f} "
              f"{m['median_cew']:9,.0f} {m['p10_cew']:9,.0f} "
              f"{m['median_ulcer']:7.4f} {m['init_swr']:8.3%} "
              f"{m['p10_min_wd']:10,.0f}")


def main() -> None:
    arrays = load_nominal_arrays(year_min=START_YEAR)
    spans = {c: (len(a)) for c, a in arrays.items()}
    print(f"Countries ({len(arrays)}): "
          f"{', '.join(f'{c}({n})' for c, n in sorted(spans.items()))}")
    v_idx = pooled_housing_real_vol(arrays)
    sigma_real = float(np.sqrt(VOL_MULT**2 - 1.0) * v_idx)
    print(f"Housing index real vol (pooled, equal-wt): {v_idx:.4f}; "
          f"idiosyncratic sigma for {VOL_MULT}x: {sigma_real:.4f}")

    df = run_phase1(arrays, sigma_real)
    n_feas = int((df.success_rate >= SR_FLOOR).sum())
    print(f"\nFeasible (success >= {SR_FLOOR}): {n_feas}/{len(df)}")
    print("\nTop 15 by median CEW among feasible:")
    cols = ["alloc", "median_cew", "p10_cew", "median_ulcer", "success_rate",
            "severe_fail_prob", "init_swr", "p10_min_wd"]
    feas = df[df.success_rate >= SR_FLOOR].sort_values(
        "median_cew", ascending=False)
    print(feas[cols].head(15).to_string(index=False))

    agg = run_phase2(arrays, sigma_real, df)
    run_phase3(arrays, sigma_real, agg, df)


if __name__ == "__main__":
    main()
