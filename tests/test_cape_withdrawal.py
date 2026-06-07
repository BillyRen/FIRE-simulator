"""Tests for CAPE-based (valuation-driven) withdrawal strategy.

Withdrawal rate = clamp(intercept + slope/CAPE, floor, ceiling); withdrawal is
that rate times the current portfolio. The CAPE of each historical year travels
with the bootstrapped block, so spending responds to the sampled valuation.
"""

import numpy as np
import pandas as pd
import pytest

from simulator.monte_carlo import compute_withdrawal, run_simulation
from simulator.data_loader import cape_for_years, load_cape_data


class TestComputeWithdrawalCape:
    def test_formula_midrange(self):
        # CAPE=20 -> 1/20=0.05 -> 0.015 + 0.5*0.05 = 0.04 -> 4% of value.
        wd = compute_withdrawal("cape", 0, 1_000_000, 40_000, 40_000, 0.04, cape_value=20.0)
        assert wd == pytest.approx(0.04 * 1_000_000)

    def test_high_cape_lowers_rate(self):
        # Expensive market (CAPE=40): 0.015 + 0.5*0.025 = 0.0275.
        wd = compute_withdrawal("cape", 0, 1_000_000, 40_000, 40_000, 0.04, cape_value=40.0)
        assert wd == pytest.approx(0.0275 * 1_000_000)

    def test_floor_and_ceiling_clamp(self):
        # Very cheap market would exceed ceiling -> clamp to 8%.
        wd_hi = compute_withdrawal("cape", 0, 1_000_000, 40_000, 40_000, 0.04,
                                   cape_value=5.0, cape_ceiling=0.08)
        assert wd_hi == pytest.approx(0.08 * 1_000_000)
        # Very expensive market would fall below floor -> clamp to 2%.
        wd_lo = compute_withdrawal("cape", 0, 1_000_000, 40_000, 40_000, 0.04,
                                   cape_value=200.0, cape_floor=0.02)
        assert wd_lo == pytest.approx(0.02 * 1_000_000)

    def test_missing_cape_falls_back(self):
        # No cape_value -> not the cape branch -> fixed fallback (annual_withdrawal).
        wd = compute_withdrawal("cape", 0, 1_000_000, 40_000, 40_000, 0.04, cape_value=None)
        assert wd == pytest.approx(40_000)


def _flat_returns_df(years, cape):
    """Zero-return US-style returns frame with a constant CAPE per year."""
    n = len(years)
    return pd.DataFrame({
        "Year": years,
        "Domestic_Stock": np.zeros(n),
        "Global_Stock": np.zeros(n),
        "Domestic_Bond": np.zeros(n),
        "Inflation": np.zeros(n),
    }), np.full(n, cape, dtype=float)


class TestRunSimulationCape:
    def test_cape_column_travels_and_drives_withdrawal(self):
        years = np.arange(1950, 2000)
        df, cape = _flat_returns_df(years, cape=20.0)  # constant CAPE -> wr=4%
        alloc = {"domestic_stock": 0.5, "global_stock": 0.0, "domestic_bond": 0.5}
        exp = {"domestic_stock": 0.0, "global_stock": 0.0, "domestic_bond": 0.0}
        traj, wd, _, _ = run_simulation(
            initial_portfolio=1_000_000, annual_withdrawal=40_000,
            allocation=alloc, expense_ratios=exp, retirement_years=10,
            min_block=3, max_block=5, num_simulations=50, returns_df=df,
            seed=1, withdrawal_strategy="cape", cape_by_year=cape,
        )
        # Year 0: 4% of 1,000,000 = 40,000 (zero returns, constant CAPE).
        assert wd[:, 0] == pytest.approx(40_000.0)
        # Withdrawal is a % of a declining portfolio -> strictly decreasing.
        assert np.all(wd[:, 1] < wd[:, 0])

    def test_higher_cape_means_lower_initial_withdrawal(self):
        years = np.arange(1950, 2000)
        alloc = {"domestic_stock": 0.5, "global_stock": 0.0, "domestic_bond": 0.5}
        exp = {"domestic_stock": 0.0, "global_stock": 0.0, "domestic_bond": 0.0}
        df_cheap, cape_cheap = _flat_returns_df(years, cape=10.0)
        df_exp, cape_exp = _flat_returns_df(years, cape=40.0)
        common = dict(initial_portfolio=1_000_000, annual_withdrawal=40_000,
                      allocation=alloc, expense_ratios=exp, retirement_years=10,
                      min_block=3, max_block=5, num_simulations=30, seed=2,
                      withdrawal_strategy="cape")
        _, wd_cheap, _, _ = run_simulation(returns_df=df_cheap, cape_by_year=cape_cheap, **common)
        _, wd_exp, _, _ = run_simulation(returns_df=df_exp, cape_by_year=cape_exp, **common)
        assert wd_cheap[0, 0] > wd_exp[0, 0]


class TestCapeDataLoader:
    def test_load_cape_range(self):
        df = load_cape_data()
        assert {"Year", "CAPE"}.issubset(df.columns)
        assert df["CAPE"].min() > 0
        assert int(df["Year"].min()) <= 1900

    def test_cape_for_years_fills_gaps(self):
        # 1870 (pre-1881) and 2025 (post-coverage) must still get a value.
        out = cape_for_years(np.array([1870, 1990, 2025]))
        assert np.all(np.isfinite(out))
        assert np.all(out > 0)
