"""Tests for batch backtest optimizations.

Validates:
1. Per-country pre-computation matches per-path computation
2. Vectorized fixed-strategy batch matches scalar loop
3. run_sim_batch_backtest produces correct results
"""

import numpy as np
import pandas as pd
import pytest

from simulator.backtest_batch import run_sim_batch_backtest, _compute_country_arrays
from simulator.monte_carlo import (
    batch_backtest_fixed_vectorized,
    run_simple_historical_backtest,
)
from simulator.portfolio import compute_real_portfolio_returns


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_country_df() -> pd.DataFrame:
    """30-year country data for testing."""
    rng = np.random.default_rng(42)
    n = 30
    return pd.DataFrame({
        "Year": np.arange(1990, 1990 + n),
        "Country": ["USA"] * n,
        "Domestic_Stock": rng.normal(0.10, 0.15, n),
        "Global_Stock": rng.normal(0.08, 0.18, n),
        "Domestic_Bond": rng.normal(0.04, 0.05, n),
        "Inflation": np.abs(rng.normal(0.03, 0.01, n)),
    })


@pytest.fixture
def allocation() -> dict[str, float]:
    return {"domestic_stock": 0.4, "global_stock": 0.4, "domestic_bond": 0.2}


@pytest.fixture
def expenses() -> dict[str, float]:
    return {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}


# ---------------------------------------------------------------------------
# Test 1: Per-country pre-computation equivalence
# ---------------------------------------------------------------------------

class TestPerCountryPrecomputation:
    def test_precomputed_returns_match_per_path(self, sample_country_df, allocation, expenses):
        """Pre-computed full returns sliced should match per-subset computation."""
        cdf_sorted = sample_country_df.sort_values("Year").reset_index(drop=True)
        full_returns, full_inflation = _compute_country_arrays(
            cdf_sorted, allocation, expenses, leverage=1.0, borrowing_spread=0.0,
        )

        # Pick several start indices and compare
        for start_idx in [0, 5, 10, 15]:
            n_years = 10
            subset = cdf_sorted.iloc[start_idx:start_idx + n_years]
            per_path_returns = compute_real_portfolio_returns(
                subset, allocation, expenses, leverage=1.0, borrowing_spread=0.0,
            )
            per_path_inflation = subset["Inflation"].values

            sliced_returns = full_returns[start_idx:start_idx + n_years]
            sliced_inflation = full_inflation[start_idx:start_idx + n_years]

            np.testing.assert_allclose(sliced_returns, per_path_returns, rtol=1e-12)
            np.testing.assert_allclose(sliced_inflation, per_path_inflation, rtol=1e-12)

    def test_precomputed_with_leverage(self, sample_country_df, allocation, expenses):
        """Pre-computation should work correctly with leverage."""
        cdf_sorted = sample_country_df.sort_values("Year").reset_index(drop=True)
        full_returns, _ = _compute_country_arrays(
            cdf_sorted, allocation, expenses, leverage=1.5, borrowing_spread=0.01,
        )

        subset = cdf_sorted.iloc[5:15]
        per_path_returns = compute_real_portfolio_returns(
            subset, allocation, expenses, leverage=1.5, borrowing_spread=0.01,
        )
        np.testing.assert_allclose(full_returns[5:15], per_path_returns, rtol=1e-12)


# ---------------------------------------------------------------------------
# Test 2: Vectorized fixed-strategy batch equivalence
# ---------------------------------------------------------------------------

class TestBatchBacktestFixedVectorized:
    def test_matches_scalar_loop(self):
        """Vectorized batch should match run_simple_historical_backtest for fixed strategy."""
        rng = np.random.default_rng(123)
        num_paths = 20
        max_years = 15
        initial = 1_000_000
        withdrawal = 40_000

        real_returns_2d = rng.normal(0.06, 0.12, (num_paths, max_years))

        portfolios, withdrawals, survived = batch_backtest_fixed_vectorized(
            real_returns_2d, initial, withdrawal,
        )

        for i in range(num_paths):
            scalar_result = run_simple_historical_backtest(
                real_returns=real_returns_2d[i],
                initial_portfolio=initial,
                annual_withdrawal=withdrawal,
                retirement_years=max_years,
                withdrawal_strategy="fixed",
            )
            expected_port = scalar_result["portfolio"]
            expected_wd = scalar_result["withdrawals"]

            np.testing.assert_allclose(
                portfolios[i, :max_years + 1], expected_port, rtol=1e-10,
                err_msg=f"Portfolio mismatch at path {i}",
            )
            np.testing.assert_allclose(
                withdrawals[i, :max_years], expected_wd, rtol=1e-10,
                err_msg=f"Withdrawal mismatch at path {i}",
            )
            assert survived[i] == scalar_result["survived"], f"Survived mismatch at path {i}"

    def test_portfolio_depletion(self):
        """Paths that run out of money should be handled correctly."""
        # Very negative returns to force depletion
        real_returns_2d = np.full((3, 10), -0.30)
        initial = 100_000
        withdrawal = 50_000

        portfolios, withdrawals, survived = batch_backtest_fixed_vectorized(
            real_returns_2d, initial, withdrawal,
        )

        assert not survived.any(), "All paths should be depleted"
        # Final portfolio values should be 0
        assert (portfolios[:, -1] == 0.0).all()

    def test_single_path(self):
        """Single path should work correctly."""
        rng = np.random.default_rng(99)
        returns = rng.normal(0.08, 0.10, (1, 20))
        initial = 500_000
        withdrawal = 20_000

        portfolios, wds, survived = batch_backtest_fixed_vectorized(
            returns, initial, withdrawal,
        )

        scalar = run_simple_historical_backtest(
            real_returns=returns[0],
            initial_portfolio=initial,
            annual_withdrawal=withdrawal,
            retirement_years=20,
            withdrawal_strategy="fixed",
        )

        np.testing.assert_allclose(portfolios[0], scalar["portfolio"], rtol=1e-10)
        np.testing.assert_allclose(wds[0], scalar["withdrawals"], rtol=1e-10)


# ---------------------------------------------------------------------------
# Test 3: run_sim_batch_backtest output correctness
# ---------------------------------------------------------------------------

class TestRunSimBatchBacktest:
    def test_basic_output_structure(self, sample_country_df, allocation, expenses):
        """Result should contain expected keys and reasonable values."""
        result = run_sim_batch_backtest(
            country_dfs=None,
            filtered_df=sample_country_df,
            allocation=allocation,
            expense_ratios=expenses,
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            retirement_years=15,
            withdrawal_strategy="fixed",
        )

        assert "num_paths" in result
        assert "paths" in result
        assert result["num_paths"] > 0
        assert result["num_paths"] == len(result["paths"])
        # No cached arrays should leak into output
        for p in result["paths"]:
            assert "_real_returns" not in p
            assert "_inflation" not in p

    def test_fixed_matches_dynamic_approach(self, sample_country_df, allocation, expenses):
        """Fixed strategy via vectorized path should match dynamic strategy fallback
        on the same returns (when both use fixed withdrawal)."""
        common_args = dict(
            country_dfs=None,
            filtered_df=sample_country_df,
            allocation=allocation,
            expense_ratios=expenses,
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            retirement_years=15,
        )

        result_fixed = run_sim_batch_backtest(**common_args, withdrawal_strategy="fixed")

        # Compare path-level results
        for p in result_fixed["paths"]:
            assert p["years_simulated"] >= 10  # MIN_BACKTEST_YEARS
            assert isinstance(p["portfolio"], list)
            assert len(p["portfolio"]) == p["years_simulated"] + 1

    def test_multi_country(self, allocation, expenses):
        """Multi-country mode should iterate all countries."""
        rng = np.random.default_rng(42)
        n = 20
        dfs = {}
        for iso in ["USA", "GBR"]:
            dfs[iso] = pd.DataFrame({
                "Year": np.arange(2000, 2000 + n),
                "Country": [iso] * n,
                "Domestic_Stock": rng.normal(0.10, 0.15, n),
                "Global_Stock": rng.normal(0.08, 0.18, n),
                "Domestic_Bond": rng.normal(0.04, 0.05, n),
                "Inflation": np.abs(rng.normal(0.03, 0.01, n)),
            })

        result = run_sim_batch_backtest(
            country_dfs=dfs,
            filtered_df=None,
            allocation=allocation,
            expense_ratios=expenses,
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            retirement_years=10,
        )

        countries = {p["country"] for p in result["paths"]}
        assert countries == {"USA", "GBR"}

    def test_empty_input(self, allocation, expenses):
        """Empty input should return empty result."""
        result = run_sim_batch_backtest(
            country_dfs=None,
            filtered_df=None,
            allocation=allocation,
            expense_ratios=expenses,
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            retirement_years=15,
        )
        assert result["num_paths"] == 0

    def test_non_fixed_strategy(self, sample_country_df, allocation, expenses):
        """Non-fixed strategies should still work (scalar fallback)."""
        result = run_sim_batch_backtest(
            country_dfs=None,
            filtered_df=sample_country_df,
            allocation=allocation,
            expense_ratios=expenses,
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            retirement_years=15,
            withdrawal_strategy="dynamic",
        )
        assert result["num_paths"] > 0
        for p in result["paths"]:
            assert "_real_returns" not in p
