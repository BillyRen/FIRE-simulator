"""Pooling-weight sensitivity (Upgrade C) — research-only.

The product pools developed-market history with EQUAL weight (1/N per country;
see backend/deps.resolve_country_weights and the memory note on the
equal-weight decision). This script checks that the headline FIRE conclusions
(success rate and the safe withdrawal rate) are robust across three plausible
pooling weights:

  1. equal 1/N            (product default)
  2. sqrt(GDP)            (economic-size weighting; config.get_gdp_weights)
  3. observation-weighted (w_i ∝ history length; config.get_observation_weights)
     — mirrors Anarkulova-Cederburg-O'Doherty's implicit country-month weighting.

If the three agree within noise, the robustness claim upgrades from "robust to
1/N vs sqrt-GDP" to "robust across three reasonable weighting schemes".

Run:  python3 analysis/pooling_weight_sensitivity.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.config import get_gdp_weights, get_observation_weights  # noqa: E402
from simulator.data_loader import load_returns_data  # noqa: E402
from simulator.monte_carlo import run_simulation  # noqa: E402
from simulator.statistics import compute_success_rate  # noqa: E402

RETIREMENT_YEARS = 30
NUM_SIM = 20000
INITIAL = 1_000_000.0
ALLOC = {"domestic_stock": 0.30, "global_stock": 0.30, "domestic_bond": 0.40}
EXPENSE = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}
WR_GRID = np.arange(0.030, 0.0601, 0.0025)
SEEDS = [42, 60_042, 120_042]   # spaced > NUM_SIM to avoid seed-overlap pitfall


def run_one(country_dfs, weights, label):
    """Return (success@grid averaged over seeds, swr@90%)."""
    succ = np.zeros(len(WR_GRID))
    for seed in SEEDS:
        for j, wr in enumerate(WR_GRID):
            pv, _, _, _ = run_simulation(
                initial_portfolio=INITIAL, annual_withdrawal=wr * INITIAL,
                allocation=ALLOC, expense_ratios=EXPENSE,
                retirement_years=RETIREMENT_YEARS, min_block=5, max_block=15,
                num_simulations=NUM_SIM, returns_df=None,
                country_dfs=country_dfs, country_weights=weights,
                seed=seed, withdrawal_strategy="fixed",
            )
            succ[j] += compute_success_rate(pv, RETIREMENT_YEARS)
    succ /= len(SEEDS)
    # SWR at 90% success: linear interp on the (decreasing) success curve
    swr = np.nan
    for j in range(len(WR_GRID) - 1):
        if succ[j] >= 0.90 >= succ[j + 1]:
            t = (succ[j] - 0.90) / (succ[j] - succ[j + 1])
            swr = WR_GRID[j] + t * (WR_GRID[j + 1] - WR_GRID[j])
            break
    return succ, swr


def main():
    df = load_returns_data()
    country_dfs = {iso: sub.sort_values("Year").reset_index(drop=True)
                   for iso, sub in df.groupby("Country")}
    isos = list(country_dfs)
    lens = {iso: len(country_dfs[iso]) for iso in isos}

    schemes = {
        "equal_1/N": None,
        "sqrt_GDP": get_gdp_weights(isos),
        "obs_weighted": get_observation_weights(lens),
    }

    print(f"Pooling-weight sensitivity (30y, 30/30/40, {NUM_SIM} sims x "
          f"{len(SEEDS)} seeds)\n")
    print("Country obs-weight vs equal (top movers):")
    ow = schemes["obs_weighted"]
    for iso in sorted(isos, key=lambda x: -ow[x])[:5]:
        print(f"  {iso}: obs={ow[iso]*100:4.1f}%  equal={100/len(isos):4.1f}%  "
              f"(n={lens[iso]})")

    print(f"\n{'WR':>6}" + "".join(f"{s:>14}" for s in schemes))
    results = {s: run_one(country_dfs, w, s) for s, w in schemes.items()}
    for j, wr in enumerate(WR_GRID):
        row = f"{wr*100:>5.2f}%"
        for s in schemes:
            row += f"{results[s][0][j]*100:>13.1f}%"
        print(row)

    print("\nSWR @ 90% success:")
    swrs = {s: results[s][1] for s in schemes}
    for s in schemes:
        print(f"  {s:<14} {swrs[s]*100:.2f}%")
    spread = (max(v for v in swrs.values() if np.isfinite(v))
              - min(v for v in swrs.values() if np.isfinite(v))) * 100
    print(f"\nSWR spread across schemes: {spread:.2f}pp")
    print("Verdict:", "ROBUST (spread < 0.25pp = noise)" if spread < 0.25
          else "schemes differ — investigate")


if __name__ == "__main__":
    main()
