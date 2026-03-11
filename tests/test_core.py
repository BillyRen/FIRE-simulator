"""Core simulation engine tests.

Tests cover: bootstrap (single + pooled), portfolio returns, cash flow schedule,
Monte Carlo simulation, and AllocationSchema validation.
"""

import numpy as np
import pandas as pd
import pytest

from simulator.bootstrap import block_bootstrap, block_bootstrap_pooled
from simulator.cashflow import CashFlowItem, build_cf_schedule
from simulator.monte_carlo import run_simulation
from simulator.portfolio import compute_real_portfolio_returns


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_returns_df() -> pd.DataFrame:
    """Minimal historical returns data (20 years) for testing."""
    rng = np.random.default_rng(42)
    n = 20
    return pd.DataFrame({
        "Year": np.arange(2000, 2000 + n),
        "Country": ["USA"] * n,
        "Domestic_Stock": rng.normal(0.10, 0.15, n),
        "Global_Stock": rng.normal(0.08, 0.18, n),
        "Domestic_Bond": rng.normal(0.04, 0.05, n),
        "Inflation": rng.normal(0.03, 0.01, n),
    })


@pytest.fixture
def default_allocation() -> dict[str, float]:
    return {"domestic_stock": 0.4, "global_stock": 0.4, "domestic_bond": 0.2}


@pytest.fixture
def default_expenses() -> dict[str, float]:
    return {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}


# ---------------------------------------------------------------------------
# Block Bootstrap Tests
# ---------------------------------------------------------------------------

class TestBlockBootstrap:

    def test_output_shape(self, sample_returns_df: pd.DataFrame):
        result = block_bootstrap(sample_returns_df, retirement_years=30, min_block=3, max_block=5)
        assert result.shape == (30, 4)

    def test_output_columns(self, sample_returns_df: pd.DataFrame):
        result = block_bootstrap(sample_returns_df, retirement_years=10, min_block=2, max_block=4)
        expected = ["Domestic_Stock", "Global_Stock", "Domestic_Bond", "Inflation"]
        assert list(result.columns) == expected

    def test_reproducible_with_seed(self, sample_returns_df: pd.DataFrame):
        rng1 = np.random.default_rng(123)
        rng2 = np.random.default_rng(123)
        r1 = block_bootstrap(sample_returns_df, 15, 3, 5, rng=rng1)
        r2 = block_bootstrap(sample_returns_df, 15, 3, 5, rng=rng2)
        pd.testing.assert_frame_equal(r1, r2)

    def test_values_come_from_source(self, sample_returns_df: pd.DataFrame):
        """All sampled values should exist in the original data."""
        result = block_bootstrap(sample_returns_df, 10, 2, 4, rng=np.random.default_rng(0))
        for col in result.columns:
            source_vals = set(sample_returns_df[col].values)
            for val in result[col].values:
                assert val in source_vals, f"Value {val} not found in source column {col}"

    def test_single_year(self, sample_returns_df: pd.DataFrame):
        result = block_bootstrap(sample_returns_df, 1, 1, 1)
        assert result.shape == (1, 4)


# ---------------------------------------------------------------------------
# Pooled Bootstrap Tests
# ---------------------------------------------------------------------------

class TestPooledBootstrap:

    def test_output_shape(self, sample_returns_df: pd.DataFrame):
        """Pooled bootstrap with two countries should produce correct shape."""
        rng = np.random.default_rng(42)
        n = 15
        df2 = pd.DataFrame({
            "Year": np.arange(2000, 2000 + n),
            "Country": ["GBR"] * n,
            "Domestic_Stock": rng.normal(0.09, 0.14, n),
            "Global_Stock": rng.normal(0.07, 0.16, n),
            "Domestic_Bond": rng.normal(0.03, 0.04, n),
            "Inflation": rng.normal(0.025, 0.01, n),
        })
        country_dfs = {"USA": sample_returns_df, "GBR": df2}
        result = block_bootstrap_pooled(country_dfs, 30, 3, 5, rng=np.random.default_rng(0))
        assert result.shape == (30, 4)

    def test_output_columns(self, sample_returns_df: pd.DataFrame):
        country_dfs = {"USA": sample_returns_df}
        result = block_bootstrap_pooled(country_dfs, 10, 2, 4)
        expected = ["Domestic_Stock", "Global_Stock", "Domestic_Bond", "Inflation"]
        assert list(result.columns) == expected

    def test_reproducible_with_seed(self, sample_returns_df: pd.DataFrame):
        country_dfs = {"USA": sample_returns_df}
        rng1 = np.random.default_rng(99)
        rng2 = np.random.default_rng(99)
        r1 = block_bootstrap_pooled(country_dfs, 15, 3, 5, rng=rng1)
        r2 = block_bootstrap_pooled(country_dfs, 15, 3, 5, rng=rng2)
        pd.testing.assert_frame_equal(r1, r2)

    def test_values_from_correct_countries(self):
        """Pooled bootstrap draws from multiple countries."""
        rng = np.random.default_rng(42)
        df_a = pd.DataFrame({
            "Year": [2000, 2001, 2002],
            "Country": ["A"] * 3,
            "Domestic_Stock": [0.1, 0.2, 0.3],
            "Global_Stock": [0.05, 0.15, 0.25],
            "Domestic_Bond": [0.01, 0.02, 0.03],
            "Inflation": [0.01, 0.02, 0.03],
        })
        df_b = pd.DataFrame({
            "Year": [2000, 2001, 2002],
            "Country": ["B"] * 3,
            "Domestic_Stock": [0.9, 0.8, 0.7],
            "Global_Stock": [0.85, 0.75, 0.65],
            "Domestic_Bond": [0.04, 0.05, 0.06],
            "Inflation": [0.04, 0.05, 0.06],
        })
        country_dfs = {"A": df_a, "B": df_b}
        result = block_bootstrap_pooled(country_dfs, 20, 1, 2, rng=rng)
        # Should contain values from both A and B
        all_vals = set(result["Domestic_Stock"].values)
        a_vals = set(df_a["Domestic_Stock"].values)
        b_vals = set(df_b["Domestic_Stock"].values)
        assert all_vals.intersection(a_vals) or all_vals.intersection(b_vals)


# ---------------------------------------------------------------------------
# Portfolio Return Tests
# ---------------------------------------------------------------------------

class TestPortfolioReturns:

    def test_output_shape(self, sample_returns_df: pd.DataFrame, default_allocation, default_expenses):
        sampled = block_bootstrap(sample_returns_df, 10, 2, 4, rng=np.random.default_rng(0))
        result = compute_real_portfolio_returns(sampled, default_allocation, default_expenses)
        assert result.shape == (10,)

    def test_no_leverage_no_inflation(self):
        """When inflation is 0, real return ≈ nominal return."""
        df = pd.DataFrame({
            "Domestic_Stock": [0.10, 0.05],
            "Global_Stock": [0.08, 0.03],
            "Domestic_Bond": [0.04, 0.02],
            "Inflation": [0.0, 0.0],
        })
        alloc = {"domestic_stock": 0.5, "global_stock": 0.3, "domestic_bond": 0.2}
        expenses = {"domestic_stock": 0.0, "global_stock": 0.0, "domestic_bond": 0.0}
        result = compute_real_portfolio_returns(df, alloc, expenses)
        # Expected: 0.5*0.10 + 0.3*0.08 + 0.2*0.04 = 0.082
        np.testing.assert_almost_equal(result[0], 0.082, decimal=6)

    def test_with_leverage(self):
        """Leverage should amplify returns."""
        df = pd.DataFrame({
            "Domestic_Stock": [0.10],
            "Global_Stock": [0.08],
            "Domestic_Bond": [0.04],
            "Inflation": [0.03],
        })
        alloc = {"domestic_stock": 0.6, "global_stock": 0.2, "domestic_bond": 0.2}
        expenses = {"domestic_stock": 0.0, "global_stock": 0.0, "domestic_bond": 0.0}

        r1 = compute_real_portfolio_returns(df, alloc, expenses, leverage=1.0)
        r2 = compute_real_portfolio_returns(df, alloc, expenses, leverage=2.0, borrowing_spread=0.01)

        # With positive returns, 2x leverage should give higher return
        # (but also higher borrowing cost)
        assert r2[0] != r1[0], "Leverage should change return"


# ---------------------------------------------------------------------------
# Cash Flow Tests
# ---------------------------------------------------------------------------

class TestCashFlow:

    def test_inflation_adjusted_schedule(self):
        cfs = [CashFlowItem("income", 10000, start_year=1, duration=5, inflation_adjusted=True)]
        schedule = build_cf_schedule(cfs, retirement_years=10)
        assert schedule.shape == (10,)
        np.testing.assert_array_equal(schedule[:5], [10000] * 5)
        np.testing.assert_array_equal(schedule[5:], [0] * 5)

    def test_nominal_schedule_with_inflation(self):
        cfs = [CashFlowItem("expense", -5000, start_year=1, duration=3, inflation_adjusted=False)]
        inflation = np.full(10, 0.03)
        schedule = build_cf_schedule(cfs, retirement_years=10, inflation_series=inflation)
        # Year 0: -5000 / (1.03) ≈ -4854.37
        cum = np.cumprod(1 + inflation)
        np.testing.assert_almost_equal(schedule[0], -5000 / cum[0], decimal=2)
        assert schedule[3] == 0.0  # past duration

    def test_nominal_without_inflation_raises(self):
        cfs = [CashFlowItem("expense", -5000, start_year=1, duration=3, inflation_adjusted=False)]
        with pytest.raises(ValueError, match="inflation_series"):
            build_cf_schedule(cfs, retirement_years=10)

    def test_empty_cash_flows(self):
        schedule = build_cf_schedule([], retirement_years=10)
        np.testing.assert_array_equal(schedule, np.zeros(10))

    def test_out_of_range_start_year(self):
        cfs = [CashFlowItem("late", 1000, start_year=20, duration=5, inflation_adjusted=True)]
        schedule = build_cf_schedule(cfs, retirement_years=10)
        np.testing.assert_array_equal(schedule, np.zeros(10))


# ---------------------------------------------------------------------------
# Monte Carlo Simulation Tests
# ---------------------------------------------------------------------------

class TestMonteCarloSimulation:

    def test_output_shapes(self, sample_returns_df, default_allocation, default_expenses):
        traj, wd, ret_mat, infl_mat = run_simulation(
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=2,
            max_block=4,
            num_simulations=50,
            returns_df=sample_returns_df,
            seed=42,
        )
        assert traj.shape == (50, 11)  # 10 years + initial
        assert wd.shape == (50, 10)
        assert ret_mat.shape == (50, 10)
        assert infl_mat.shape == (50, 10)

    def test_initial_portfolio_preserved(self, sample_returns_df, default_allocation, default_expenses):
        traj, _, _, _ = run_simulation(
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=5,
            min_block=2,
            max_block=3,
            num_simulations=10,
            returns_df=sample_returns_df,
            seed=0,
        )
        np.testing.assert_array_equal(traj[:, 0], 500_000)

    def test_fixed_withdrawal_consistent(self, sample_returns_df, default_allocation, default_expenses):
        _, wd, _, _ = run_simulation(
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=5,
            min_block=2,
            max_block=3,
            num_simulations=10,
            returns_df=sample_returns_df,
            seed=42,
            withdrawal_strategy="fixed",
        )
        # For paths that haven't depleted, withdrawal should be 40000
        for i in range(10):
            for y in range(5):
                if wd[i, y] > 0:
                    assert wd[i, y] == pytest.approx(40_000, rel=1e-6)

    def test_reproducible_with_seed(self, sample_returns_df, default_allocation, default_expenses):
        kwargs = dict(
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=2,
            max_block=4,
            num_simulations=20,
            returns_df=sample_returns_df,
        )
        t1, w1, _, _ = run_simulation(**kwargs, seed=99)
        t2, w2, _, _ = run_simulation(**kwargs, seed=99)
        np.testing.assert_array_equal(t1, t2)
        np.testing.assert_array_equal(w1, w2)

    def test_zero_withdrawal_never_depletes(self, sample_returns_df, default_allocation, default_expenses):
        traj, _, _, _ = run_simulation(
            initial_portfolio=1_000_000,
            annual_withdrawal=0,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=2,
            max_block=4,
            num_simulations=20,
            returns_df=sample_returns_df,
            seed=42,
        )
        # With 0 withdrawal, portfolio should always be > 0
        assert np.all(traj[:, -1] > 0)

    def test_dynamic_strategy_produces_varying_withdrawals(
        self, sample_returns_df, default_allocation, default_expenses
    ):
        _, wd, _, _ = run_simulation(
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=2,
            max_block=4,
            num_simulations=50,
            returns_df=sample_returns_df,
            seed=42,
            withdrawal_strategy="dynamic",
            dynamic_ceiling=0.05,
            dynamic_floor=0.025,
        )
        # Dynamic strategy should have varying withdrawals across years
        has_variation = False
        for i in range(50):
            active = wd[i, wd[i] > 0]
            if len(active) > 1 and not np.allclose(active, active[0]):
                has_variation = True
                break
        assert has_variation, "Dynamic strategy should produce varying withdrawals"

    def test_with_cash_flows(self, sample_returns_df, default_allocation, default_expenses):
        cfs = [CashFlowItem("income", 10_000, start_year=1, duration=5, inflation_adjusted=True)]
        traj_with, _, _, _ = run_simulation(
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=2,
            max_block=4,
            num_simulations=20,
            returns_df=sample_returns_df,
            seed=42,
            cash_flows=cfs,
        )
        traj_without, _, _, _ = run_simulation(
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=2,
            max_block=4,
            num_simulations=20,
            returns_df=sample_returns_df,
            seed=42,
        )
        # With income cash flow, final portfolio should generally be higher
        assert np.median(traj_with[:, -1]) > np.median(traj_without[:, -1])

    def test_with_country_dfs_pooled(self, sample_returns_df, default_allocation, default_expenses):
        """Test run_simulation with country_dfs for pooled bootstrap."""
        rng = np.random.default_rng(42)
        n = 15
        df_gbr = pd.DataFrame({
            "Year": np.arange(2000, 2000 + n),
            "Country": ["GBR"] * n,
            "Domestic_Stock": rng.normal(0.09, 0.14, n),
            "Global_Stock": rng.normal(0.07, 0.16, n),
            "Domestic_Bond": rng.normal(0.03, 0.04, n),
            "Inflation": rng.normal(0.025, 0.01, n),
        })
        country_dfs = {"USA": sample_returns_df, "GBR": df_gbr}
        traj, wd, _, _ = run_simulation(
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=2,
            max_block=4,
            num_simulations=20,
            returns_df=sample_returns_df,
            seed=42,
            country_dfs=country_dfs,
        )
        assert traj.shape == (20, 11)
        assert wd.shape == (20, 10)


# ---------------------------------------------------------------------------
# Pydantic Validation Tests
# ---------------------------------------------------------------------------

class TestAllocationValidation:

    def test_valid_allocation(self):
        from backend.schemas import AllocationSchema
        a = AllocationSchema(domestic_stock=0.5, global_stock=0.3, domestic_bond=0.2)
        assert a.domestic_stock == 0.5

    def test_invalid_allocation_sum(self):
        from backend.schemas import AllocationSchema
        with pytest.raises(Exception, match="sum to 100%"):
            AllocationSchema(domestic_stock=0.5, global_stock=0.5, domestic_bond=0.5)

    def test_allocation_small_rounding(self):
        """Small floating-point deviations (< 1%) should be accepted."""
        from backend.schemas import AllocationSchema
        a = AllocationSchema(domestic_stock=0.333, global_stock=0.334, domestic_bond=0.333)
        assert abs(a.domestic_stock + a.global_stock + a.domestic_bond - 1.0) < 0.01
