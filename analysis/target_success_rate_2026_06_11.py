"""Target success rate study for the user's actual scenario (2026-06-11).

Question 1: fixed real withdrawal — what target success rate should the user
adopt (and what base annual spending does each target imply)?
Question 2: risk-based guardrail — what *realized* (final) success rate is a
sensible target, and which `target_success` parameter achieves it?

Scenario: 24M initial, 33/67/0 allocation, expense 0.005, block 5-15, 65 years
(age 35 -> 100), full probabilistic cash flows from the user's saved scenario
(education / college / social security / housing / one-off incomes).

Data sources:
  POOL    — JST ALL pooled, equal probability, 1900+  (user's default baseline)
  JST_USA — JST USA only, 1900+                       (long-history US contrast)
  FIRE_US — FIRE_dataset USA, 1970+                   (modern US, user reference)

Methodology notes (plan: docs/plan-2026-06-11-target-success-rate.md):
  - Fixed-withdrawal sweep uses a vectorized loop replicating
    run_simulation_from_matrix semantics exactly (negative CF before depletion
    check, positive CF after; depleted paths stay at zero). Equivalence is
    asserted against run_simulation_from_matrix on a deterministic-CF subset.
  - Common random numbers: one bootstrap + one CF branch sampling per seed,
    shared across all withdrawal levels and (for fixed) across sources is NOT
    possible (each source has its own bootstrap), but within a source all
    sweep points share paths and CF branches.
  - Guardrail uses the production path: build_success_rate_table +
    build_cf_aware_table(representative expected CF) + run_guardrail_simulation
    with initial_portfolio=24M (binary-searches the base withdrawal for the
    target). CF branch sampling inside is not seedable; 3-seed drift quantifies
    that noise.
  - Mortality weighting: Gompertz fitted to SSA 2021 (frontend/src/lib/
    mortality.ts): male M=85.0 b=10.4, female M=88.8 b=9.7. Joint = at least
    one of two 35-year-old spouses alive. Secondary metric, not a stopping rule.

Outputs: analysis/output/target_success/*.csv + summary.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.cashflow import (
    CashFlowItem,
    build_cf_schedule,
    build_expected_cf_split_schedules,
    build_representative_cf_schedule,
    sample_cash_flows,
)
from simulator.data_loader import (
    get_country_dfs,
    load_returns_by_source,
    load_returns_data,
)
from simulator.guardrail import (
    build_cf_aware_table,
    build_success_rate_table,
    run_guardrail_simulation,
)
from simulator.monte_carlo import run_simulation_from_matrix
from simulator.statistics import (
    compute_effective_funded_ratio,
    compute_success_rate,
)
from simulator.sweep import pregenerate_raw_scenarios, raw_to_combined

# ─────────────── user scenario (fire-scenario-2026-06-07.json) ─────────────
INITIAL_PORTFOLIO = 24_000_000.0
BASE_WD_CURRENT = 500_000.0
ALLOCATION = {"domestic_stock": 0.33, "global_stock": 0.67, "domestic_bond": 0.0}
EXPENSE = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}
YEARS = 65
RETIREMENT_AGE = 35
MIN_BLOCK, MAX_BLOCK = 5, 15

CASH_FLOWS = [
    # 教育 group: 公办 25% vs 民办 75%, years 3-14
    CashFlowItem("公办", -50_000, 3, 12, True, 0.0, 0.25, "教育"),
    CashFlowItem("民办", -150_000, 3, 12, True, 0.0, 0.75, "教育"),
    # 大学 group: years 15-18, real growth 1%
    CashFlowItem("美国", -700_000, 15, 4, True, 0.01, 0.30, "大学"),
    CashFlowItem("中国", -100_000, 15, 4, True, 0.01, 0.40, "大学"),
    CashFlowItem("其他", -400_000, 15, 4, True, 0.01, 0.30, "大学"),
    # 社保 group: years 25-65
    CashFlowItem("合理社保", 200_000, 25, 41, True, 0.0, 0.50, "社保"),
    CashFlowItem("低社保", 100_000, 25, 41, True, 0.0, 0.50, "社保"),
    # 任成斌收入 (deterministic variant, prob=1)
    CashFlowItem("1年", 2_000_000, 1, 1, True, 0.0, 1.0, "任成斌收入"),
    CashFlowItem("1年", -30_000, 2, 23, True, 0.0, 1.0, "任成斌收入"),
    CashFlowItem("1年", -60_000, 1, 65, True, 0.0, 1.0, "任成斌收入"),
    # 买房租房 group: 租房 90% vs 买房 10%
    CashFlowItem("租房", -250_000, 1, 65, True, 0.0, 0.90, "买房租房"),
    CashFlowItem("买房", -250_000, 1, 5, True, 0.0, 0.10, "买房租房"),
    CashFlowItem("买房", -450_000, 6, 30, True, 0.0, 0.10, "买房租房"),
    # 连欣收入 (deterministic variant, prob=1)
    CashFlowItem("1年", 1_000_000, 1, 1, True, 0.0, 1.0, "连欣收入"),
    CashFlowItem("1年", -30_000, 1, 15, True, 0.0, 1.0, "连欣收入"),
]
assert all(cf.inflation_adjusted for cf in CASH_FLOWS), "all CFs must be real"

# ─────────────── experiment config ──────────────────────────────────────────
N_FIXED = 20_000
N_GUARD = 10_000
SEEDS = [42, 60_042, 120_042]   # spacing > N to avoid path-set overlap

SOURCES = ["POOL", "JST_USA", "FIRE_US"]

# fixed sweep grid: coarse 20-80wan at 2.5wan + fine 1.25wan inside 35-65wan
WD_GRID = sorted(set(
    [200_000 + 25_000 * i for i in range(25)]          # 20wan .. 80wan
    + [350_000 + 12_500 * i for i in range(25)]        # 35wan .. 65wan fine
))
FIXED_TARGETS = [0.75, 0.80, 0.85, 0.90, 0.95, 0.975, 0.99]

# guardrail: tier-F family, lower = target - 0.10 (user gap>=10pp philosophy)
GR_TARGETS = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
GR_UPPER, GR_ADJ, GR_MODE, GR_MR = 0.99, 0.05, "amount", 1
GR_SEEDS_EXTRA_TARGETS = [0.80, 0.85, 0.90]  # multi-seed subset (POOL only)

ESSENTIAL_FLOOR_ABS = 300_000.0   # absolute essential base-consumption floor
FLOOR_ABS_SENS = [250_000.0, 350_000.0]
GAMMA, DELTA = 2.0, 0.02

OUT = ROOT / "analysis" / "output" / "target_success"
OUT.mkdir(parents=True, exist_ok=True)

# ─────────────── mortality (SSA 2021 Gompertz, frontend/src/lib/mortality.ts)
GOMPERTZ = {"male": (85.0, 10.4), "female": (88.8, 9.7)}


def survival_curve(years: int, age0: int = RETIREMENT_AGE) -> dict[str, np.ndarray]:
    """S(t) = P(alive at age0+t | alive at age0), t = 1..years."""
    t = np.arange(1, years + 1)
    out = {}
    for sex, (M, b) in GOMPERTZ.items():
        out[sex] = np.exp(np.exp((age0 - M) / b) * (1.0 - np.exp(t / b)))
    out["joint"] = 1.0 - (1.0 - out["male"]) * (1.0 - out["female"])
    return out


SURV = survival_curve(YEARS)


# ─────────────── helpers ────────────────────────────────────────────────────

def sample_cf_matrix(n: int, rng: np.random.Generator) -> np.ndarray:
    """Per-path probabilistic CF sampling -> (n, YEARS) net real CF matrix."""
    mat = np.zeros((n, YEARS))
    for i in range(n):
        active = sample_cash_flows(CASH_FLOWS, rng)
        if active:
            mat[i] = build_cf_schedule(active, YEARS)
    return mat


def simulate_fixed(R: np.ndarray, cf_mat: np.ndarray, annual_wd: float) -> np.ndarray:
    """Vectorized fixed-withdrawal simulation replicating
    run_simulation_from_matrix semantics (see module docstring)."""
    n, years = R.shape
    traj = np.zeros((n, years + 1))
    traj[:, 0] = INITIAL_PORTFOLIO
    value = np.full(n, INITIAL_PORTFOLIO)
    alive = np.ones(n, dtype=bool)
    neg = np.minimum(cf_mat, 0.0)
    pos = np.maximum(cf_mat, 0.0)
    for y in range(years):
        vg = value * (1.0 + R[:, y])
        wd = np.minimum(annual_wd, np.maximum(vg, 0.0))
        v = vg - wd + neg[:, y]
        depleted_now = v <= 0.0
        v = np.where(depleted_now, 0.0, v + pos[:, y])
        v = np.where(alive, v, 0.0)
        traj[:, y + 1] = v
        alive &= ~depleted_now
        value = v
    return traj


def first_depletion_year(traj: np.ndarray) -> np.ndarray:
    """1-indexed first year-end with value 0; np.inf if never depleted."""
    dep = traj[:, 1:] <= 0
    any_dep = dep.any(axis=1)
    yr = np.argmax(dep, axis=1) + 1.0
    return np.where(any_dep, yr, np.inf)


def ruin_while_alive(dep_year: np.ndarray, who: str) -> float:
    """P(depletion happens while household member(s) still alive)."""
    failed = np.isfinite(dep_year)
    if not failed.any():
        return 0.0
    idx = dep_year[failed].astype(int) - 1
    return float(np.sum(SURV[who][idx]) / len(dep_year))


def wilson_ci(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return center - half, center + half


def per_path_funded_ratio(traj: np.ndarray) -> np.ndarray:
    dep = traj[:, 1:] <= 0
    any_dep = dep.any(axis=1)
    dep_year = np.where(any_dep, np.argmax(dep, axis=1) + 1.0, float(YEARS))
    return np.minimum(dep_year / YEARS, 1.0)


def compute_cew(wds: np.ndarray, gamma: float = GAMMA, delta: float = DELTA) -> np.ndarray:
    n_years = wds.shape[1]
    safe = np.maximum(wds, 1e-10)
    weights = (1.0 / (1.0 + delta)) ** np.arange(n_years)
    weights = weights / weights.sum()
    if abs(gamma - 1.0) < 1e-9:
        return np.exp((np.log(safe) * weights[None, :]).sum(axis=1))
    u = safe ** (1.0 - gamma) / (1.0 - gamma)
    mu = (u * weights[None, :]).sum(axis=1)
    return (mu * (1.0 - gamma)) ** (1.0 / (1.0 - gamma))


def equivalence_check(R: np.ndarray, infl: np.ndarray) -> None:
    """Assert vectorized loop == run_simulation_from_matrix on deterministic CFs."""
    det_cfs = [
        CashFlowItem("exp", -200_000, 1, 40, True),
        CashFlowItem("col", -400_000, 15, 4, True, 0.01),
        CashFlowItem("ss", 150_000, 25, 41, True),
        CashFlowItem("one", 3_000_000, 1, 1, True),
    ]
    sched = build_cf_schedule(det_cfs, YEARS)
    n = 500
    for wd in (400_000.0, 700_000.0):
        ref, _, _, _ = run_simulation_from_matrix(
            R[:n], infl[:n], INITIAL_PORTFOLIO, wd, YEARS, cash_flows=det_cfs,
        )
        mine = simulate_fixed(R[:n], np.tile(sched, (n, 1)), wd)
        assert np.allclose(ref, mine, rtol=1e-9, atol=1e-3), (
            f"vectorized loop diverges from run_simulation_from_matrix at wd={wd}"
        )
    print("  [ok] vectorized fixed loop == run_simulation_from_matrix")


# ─────────────── data ───────────────────────────────────────────────────────

def build_returns(
    source: str, seed: int, n: int,
    min_block: int = MIN_BLOCK, max_block: int = MAX_BLOCK,
) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap -> (real combined returns, inflation), shape (n, YEARS)."""
    if source == "POOL":
        df = load_returns_data()
        country_dfs = get_country_dfs(df, 1900)
        returns_df = df[df["Year"] >= 1900].reset_index(drop=True)
        weights = None  # equal probability
    elif source == "JST_USA":
        df = load_returns_data()
        returns_df = df[(df["Country"] == "USA") & (df["Year"] >= 1900)].reset_index(drop=True)
        country_dfs, weights = None, None
    elif source == "FIRE_US":
        df = load_returns_by_source("fire_dataset")
        returns_df = df[df["Year"] >= 1970].reset_index(drop=True)
        country_dfs, weights = None, None
    else:
        raise ValueError(source)
    raw = pregenerate_raw_scenarios(
        expense_ratios=EXPENSE, retirement_years=YEARS,
        min_block=min_block, max_block=max_block,
        num_simulations=n, returns_df=returns_df, seed=seed,
        country_dfs=country_dfs, country_weights=weights,
    )
    return raw_to_combined(raw, ALLOCATION, leverage=1.0), raw["inflation"]


# ─────────────── experiment A: fixed sweep ──────────────────────────────────

def run_fixed_sweep(
    sources: list[str] = SOURCES, seeds: list[int] = SEEDS,
    blocks: tuple[int, int] = (MIN_BLOCK, MAX_BLOCK),
) -> pd.DataFrame:
    block_tag = f"{blocks[0]}-{blocks[1]}"
    rows = []
    # expected net outflow in the final year, for the fragile-success metric
    exp_expense, exp_income = build_expected_cf_split_schedules(CASH_FLOWS, YEARS)
    net_out_last = max(float(exp_expense[-1] - exp_income[-1]), 0.0)

    for source in sources:
        for seed in seeds:
            t0 = time.time()
            R, infl = build_returns(source, seed, N_FIXED, *blocks)
            if source == "POOL" and seed == seeds[0] and block_tag == "5-15":
                equivalence_check(R, infl)
            cf_mat = sample_cf_matrix(N_FIXED, np.random.default_rng(seed))
            for wd in WD_GRID:
                traj = simulate_fixed(R, cf_mat, float(wd))
                sr = compute_success_rate(traj, YEARS)
                dep_year = first_depletion_year(traj)
                failed = np.isfinite(dep_year)
                finals = traj[:, -1]
                succ = ~failed
                lo, hi = wilson_ci(sr * N_FIXED, N_FIXED)
                fragile_thresh = 3.0 * (wd + net_out_last)
                rows.append({
                    "source": source, "seed": seed, "block": block_tag,
                    "base_wd": wd,
                    "success": sr, "ci_lo": lo, "ci_hi": hi,
                    "p_ruin_alive_male": ruin_while_alive(dep_year, "male"),
                    "p_ruin_alive_joint": ruin_while_alive(dep_year, "joint"),
                    "p_dep_by_25": float(np.mean(dep_year <= 25)),
                    "dep_year_p25": float(np.percentile(dep_year[failed], 25)) if failed.any() else np.nan,
                    "dep_year_p50": float(np.percentile(dep_year[failed], 50)) if failed.any() else np.nan,
                    "median_final": float(np.median(finals)),
                    "p10_final": float(np.percentile(finals, 10)),
                    "fragile_success": float(np.mean(succ & (finals < fragile_thresh))),
                    "median_fr": float(np.median(per_path_funded_ratio(traj))),
                })
            print(f"  [fixed {block_tag}] {source} seed={seed}: "
                  f"{len(WD_GRID)} pts in {time.time()-t0:.0f}s")
    return pd.DataFrame(rows)


def invert_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Interpolate base_wd achieving each target success, per (source, seed)."""
    rows = []
    for (source, seed, block), g in df.groupby(["source", "seed", "block"]):
        g = g.sort_values("base_wd")
        wd = g["base_wd"].to_numpy(float)
        # enforce monotone non-increasing success for clean inversion
        sr = np.minimum.accumulate(g["success"].to_numpy())
        for t in FIXED_TARGETS:
            if sr.max() < t:
                wd_t = np.nan          # unreachable even at min grid wd
            elif sr.min() > t:
                wd_t = np.inf          # above max grid wd
            else:
                # success decreasing in wd: find crossing
                idx = np.where(sr >= t)[0][-1]
                if idx == len(wd) - 1:
                    wd_t = wd[-1]
                else:
                    x0, x1 = sr[idx], sr[idx + 1]
                    w0, w1 = wd[idx], wd[idx + 1]
                    wd_t = w0 + (w1 - w0) * (t - x0) / (x1 - x0) if x1 != x0 else w0
            rows.append({"source": source, "seed": seed, "block": block,
                         "target": t, "base_wd": wd_t})
    return pd.DataFrame(rows)


# ─────────────── experiment C: guardrail target scan ────────────────────────

def run_guardrail_scan() -> pd.DataFrame:
    exp_expense, _ = build_expected_cf_split_schedules(CASH_FLOWS, YEARS)
    rows = []
    for source in SOURCES:
        for seed in SEEDS:
            if seed != SEEDS[0] and source != "POOL":
                continue  # extra seeds: POOL only
            targets = GR_TARGETS if seed == SEEDS[0] else GR_SEEDS_EXTRA_TARGETS
            t0 = time.time()
            R, infl = build_returns(source, seed, N_GUARD)
            rate_grid, table = build_success_rate_table(R)
            rep = build_representative_cf_schedule(CASH_FLOWS, YEARS, infl)
            cf_res = build_cf_aware_table(R, rep)
            if cf_res is not None:
                cf_rg, cf_sg, cf_tbl, cf_ref, last_cf_y = cf_res
            else:
                cf_rg = cf_sg = cf_tbl = None
                cf_ref, last_cf_y = 0.0, -1
            print(f"  [guard] {source} seed={seed}: tables built "
                  f"({time.time()-t0:.0f}s)")
            for tgt in targets:
                t1 = time.time()
                _, wd0, traj, wds = run_guardrail_simulation(
                    scenarios=R, target_success=tgt,
                    upper_guardrail=GR_UPPER, lower_guardrail=round(tgt - 0.10, 2),
                    adjustment_pct=GR_ADJ, retirement_years=YEARS,
                    min_remaining_years=GR_MR, table=table, rate_grid=rate_grid,
                    adjustment_mode=GR_MODE,
                    cash_flows=CASH_FLOWS, inflation_matrix=infl,
                    cf_table=cf_tbl, cf_rate_grid=cf_rg, cf_scale_grid=cf_sg,
                    cf_ref=cf_ref, last_cf_year=last_cf_y,
                    initial_portfolio=INITIAL_PORTFOLIO,
                )
                # base-consumption proxy: strip expense display from wds
                wd_base = np.maximum(wds - exp_expense[None, :], 0.0)
                raw_sr = compute_success_rate(traj, YEARS)
                dep_year = first_depletion_year(traj)
                fr = per_path_funded_ratio(traj)
                cew = compute_cew(wd_base)
                eff_fr_rel, eff_sr_rel = compute_effective_funded_ratio(
                    wd_base, wd0, YEARS, consumption_floor=0.50, trajectories=traj,
                )
                row = {
                    "source": source, "seed": seed, "target": tgt,
                    "lower": round(tgt - 0.10, 2),
                    "init_wd": wd0, "init_swr": wd0 / INITIAL_PORTFOLIO,
                    "raw_success": raw_sr,
                    "eff_success_rel50": eff_sr_rel,
                    "eff_fr_rel50": eff_fr_rel,
                    "p_ruin_alive_joint": ruin_while_alive(dep_year, "joint"),
                    "severe_fail": float(np.mean(fr < 0.5)),
                    "cew_median": float(np.median(cew)),
                    "cew_p10": float(np.percentile(cew, 10)),
                    "p10_min_base_wd": float(np.percentile(wd_base.min(axis=1), 10)),
                    "p10_avg_base_wd": float(np.percentile(wd_base.mean(axis=1), 10)),
                    "median_final": float(np.median(traj[:, -1])),
                    # 0.95 threshold: tolerate proxy noise from per-path vs
                    # expected expense mismatch when detecting real cuts
                    "p_first_cut_by_15": float(
                        np.mean((wd_base < wd0 * 0.95).any(axis=1) &
                                (np.argmax(wd_base < wd0 * 0.95, axis=1) < 15))
                    ),
                }
                for fl in [ESSENTIAL_FLOOR_ABS] + FLOOR_ABS_SENS:
                    _, eff_sr_abs = compute_effective_funded_ratio(
                        wd_base, wd0, YEARS, consumption_floor=1e-6,
                        trajectories=traj, consumption_floor_amount=fl,
                    )
                    row[f"eff_success_abs{int(fl/10000)}w"] = eff_sr_abs
                    row[f"yrs_below_{int(fl/10000)}w_med"] = float(
                        np.median((wd_base < fl).sum(axis=1))
                    )
                rows.append(row)
                print(f"    target={tgt:.2f}: init_wd={wd0:,.0f} "
                      f"raw={raw_sr:.3f} ({time.time()-t1:.0f}s)")
    return pd.DataFrame(rows)


# ─────────────── main ───────────────────────────────────────────────────────

def main() -> None:
    t0 = time.time()
    print(f"[A] fixed sweep: {len(WD_GRID)} pts x {SOURCES} x {SEEDS}, N={N_FIXED}")
    fixed_df = run_fixed_sweep()
    fixed_df.to_csv(OUT / "fixed_sweep.csv", index=False)

    inv = invert_targets(fixed_df)
    inv.to_csv(OUT / "fixed_targets.csv", index=False)

    print("[A2] block-length sensitivity (POOL, 8-20, seed=42)")
    blk_df = run_fixed_sweep(sources=["POOL"], seeds=[42], blocks=(8, 20))
    blk_df.to_csv(OUT / "fixed_sweep_block_8_20.csv", index=False)

    print(f"[C] guardrail scan: targets={GR_TARGETS}, N={N_GUARD}")
    guard_df = run_guardrail_scan()
    guard_df.to_csv(OUT / "guardrail_targets.csv", index=False)

    print(f"\nAll done in {(time.time()-t0)/60:.1f} min. Outputs in {OUT}")


if __name__ == "__main__":
    main()
