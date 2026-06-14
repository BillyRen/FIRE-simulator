"""Hard consumption floor (enforce) vs post-hoc classifier — headline success delta.

Quantifies how much the guardrail headline success rate moves when switching from
the existing post-hoc consumption-floor classifier (free cut + "any year < floor =
fail") to the opt-in behavioral hard floor (clamp wd >= floor + pure-depletion
success). Runs both Monte Carlo and the historical batch backtest, for the pooled
(ALL, equal-weight) and USA perspectives, across horizons.

Per config it decomposes the MC delta into:
  metric-only Δ  = free_cut_pure_depletion - old_headline   (relaxing the <floor=fail rule)
  behavior  Δ    = new_headline - free_cut_pure_depletion   (clamp causing earlier depletion)

Usage:
  python analysis/hard_floor_vs_classifier.py [--floor 0.50] [--nsim 5000]

Design spec: docs/superpowers/specs/2026-06-14-guardrail-hard-floor-design.md
Results doc: docs/hard-floor-vs-classifier-2026-06-14.md
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import load_returns_data, filter_by_country, get_country_dfs
from simulator.portfolio import compute_real_portfolio_returns
from simulator.bootstrap import block_bootstrap, block_bootstrap_pooled
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import (
    compute_effective_funded_ratio, compute_success_rate, compute_floor_exposure,
)
from simulator.backtest_batch import run_guardrail_batch_backtest

INITIAL = 1_000_000
ALLOC = {"domestic_stock": 0.30, "global_stock": 0.70}  # user baseline 30/70/00
EXP = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}
MINB, MAXB = 5, 15
DSTART = 1900
SEED = 42
TARGET, UP, LO, ADJ, MODE, MINREM, BASELINE = 0.85, 0.99, 0.60, 0.10, "amount", 5, 0.033
HORIZONS = (30, 50)


def gen_scen(sampler, years, nsim):
    rng = np.random.default_rng(SEED)
    s = np.zeros((nsim, years))
    for i in range(nsim):
        s[i] = compute_real_portfolio_returns(sampler(years, rng), ALLOC, EXP)
    return s


def run_config(label, scen, years, country_dfs, filtered, floor, nsim):
    rate_grid, table = build_success_rate_table(scen)
    common = dict(
        scenarios=scen, target_success=TARGET, upper_guardrail=UP,
        lower_guardrail=LO, adjustment_pct=ADJ, retirement_years=years,
        min_remaining_years=MINREM, table=table, rate_grid=rate_grid,
        adjustment_mode=MODE, initial_portfolio=INITIAL,
    )
    ip, aw, traj_off, wd_off, _ = run_guardrail_simulation(**common)
    _, old_head = compute_effective_funded_ratio(
        wd_off, aw, years, consumption_floor=floor, trajectories=traj_off)
    free_dep = compute_success_rate(traj_off, years)
    _, _, traj_on, _, floored = run_guardrail_simulation(
        **common, enforce_consumption_floor=True, consumption_floor=floor)
    new_head = compute_success_rate(traj_on, years)
    pctf, medf = compute_floor_exposure(floored)

    bt_common = dict(
        country_dfs=country_dfs, filtered_df=filtered, allocation=ALLOC,
        expense_ratios=EXP, initial_portfolio=INITIAL, annual_withdrawal=aw,
        retirement_years=years, target_success=TARGET, upper_guardrail=UP,
        lower_guardrail=LO, adjustment_pct=ADJ, adjustment_mode=MODE,
        min_remaining_years=MINREM, baseline_rate=BASELINE,
        table=table, rate_grid=rate_grid, consumption_floor=floor,
    )
    bt_off = run_guardrail_batch_backtest(**bt_common, enforce_consumption_floor=False)
    bt_on = run_guardrail_batch_backtest(**bt_common, enforce_consumption_floor=True)
    bt_pf = bt_on.get("g_pct_paths_floored")

    print(f"\n{'='*78}\n{label} | {years}y | annual_wd=${aw:,.0f} ({aw/ip:.2%}) | "
          f"floor={floor:.0%} (${floor*aw:,.0f})\n{'='*78}")
    print(f"  MC ({nsim} paths):")
    print(f"    OLD headline (free cut, effective)   : {old_head:6.1%}")
    print(f"    NEW headline (hard floor, depletion) : {new_head:6.1%}")
    print(f"    Δ (NEW - OLD)                        : {(new_head-old_head)*100:+5.1f} pp")
    print(f"    [decomp] metric-only Δ               : {(free_dep-old_head)*100:+5.1f} pp")
    print(f"             behavior Δ                  : {(new_head-free_dep)*100:+5.1f} pp")
    print(f"    pct pinned at floor                  : {pctf:6.1%}  (median {medf:.0f} yrs)")
    print(f"  Historical backtest:")
    print(f"    OLD headline (effective)             : {bt_off['g_success_rate']:6.1%}")
    print(f"    NEW headline (pure depletion)        : {bt_on['g_success_rate']:6.1%}")
    print(f"    Δ (NEW - OLD)                        : "
          f"{(bt_on['g_success_rate']-bt_off['g_success_rate'])*100:+5.1f} pp")
    print(f"    pct pinned at floor                  : "
          + (f"{bt_pf:6.1%}" if bt_pf is not None else "   n/a"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor", type=float, default=0.50)
    ap.add_argument("--nsim", type=int, default=5000)
    args = ap.parse_args()

    df = load_returns_data()
    cdfs = get_country_dfs(df, DSTART)
    usa = filter_by_country(df, "USA", DSTART)
    print(f"pooled countries: {len(cdfs)} | seed={SEED} nsim={args.nsim} floor={args.floor:.0%}\n"
          f"params: target=85% up=99 lo=60 adj=0.10 amount, baseline=3.3%, alloc=30/70/00")

    for years in HORIZONS:
        scen_p = gen_scen(lambda y, rng: block_bootstrap_pooled(cdfs, y, MINB, MAXB, rng=rng), years, args.nsim)
        run_config("POOLED (ALL, equal-weight)", scen_p, years, cdfs, None, args.floor, args.nsim)
        scen_u = gen_scen(lambda y, rng: block_bootstrap(usa, y, MINB, MAXB, rng=rng), years, args.nsim)
        run_config("USA", scen_u, years, None, usa, args.floor, args.nsim)


if __name__ == "__main__":
    main()
