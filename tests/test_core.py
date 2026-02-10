"""Core simulation engine tests.

Tests cover: bootstrap, portfolio returns, cash flow schedule,
Monte Carlo simulation, and AllocationSchema validation.
"""

import numpy as np
import pandas as pd
import pytest

from simulator.bootstrap import block_bootstrap
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
        "US Stock": rng.normal(0.10, 0.15, n),
        "International Stock": rng.normal(0.08, 0.18, n),
        "US Bond": rng.normal(0.04, 0.05, n),
        "US Inflation": rng.normal(0.03, 0.01, n),
    })


@pytest.fixture
def default_allocation() -> dict[str, float]:
    return {"us_stock": 0.4, "intl_stock": 0.4, "us_bond": 0.2}


@pytest.fixture
def default_expenses() -> dict[str, float]:
    return {"us_stock": 0.005, "intl_stock": 0.005, "us_bond": 0.005}


# ---------------------------------------------------------------------------
# Block Bootstrap Tests
# ---------------------------------------------------------------------------

class TestBlockBootstrap:

    def test_output_shape(self, sample_returns_df: pd.DataFrame):
        result = block_bootstrap(sample_returns_df, retirement_years=30, min_block=3, max_block=5)
        assert result.shape == (30, 4)

    def test_output_columns(self, sample_returns_df: pd.DataFrame):
        result = block_bootstrap(sample_returns_df, retirement_years=10, min_block=2, max_block=4)
        expected = ["US Stock", "International Stock", "US Bond", "US Inflation"]
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
            "US Stock": [0.10, 0.05],
            "International Stock": [0.08, 0.03],
            "US Bond": [0.04, 0.02],
            "US Inflation": [0.0, 0.0],
        })
        alloc = {"us_stock": 0.5, "intl_stock": 0.3, "us_bond": 0.2}
        expenses = {"us_stock": 0.0, "intl_stock": 0.0, "us_bond": 0.0}
        result = compute_real_portfolio_returns(df, alloc, expenses)
        # Expected: 0.5*0.10 + 0.3*0.08 + 0.2*0.04 = 0.082
        np.testing.assert_almost_equal(result[0], 0.082, decimal=6)

    def test_with_leverage(self):
        """Leverage should amplify returns."""
        df = pd.DataFrame({
            "US Stock": [0.10],
            "International Stock": [0.08],
            "US Bond": [0.04],
            "US Inflation": [0.03],
        })
        alloc = {"us_stock": 0.6, "intl_stock": 0.2, "us_bond": 0.2}
        expenses = {"us_stock": 0.0, "intl_stock": 0.0, "us_bond": 0.0}

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
        traj, wd = run_simulation(
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

    def test_initial_portfolio_preserved(self, sample_returns_df, default_allocation, default_expenses):
        traj, _ = run_simulation(
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
        _, wd = run_simulation(
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
        t1, w1 = run_simulation(**kwargs, seed=99)
        t2, w2 = run_simulation(**kwargs, seed=99)
        np.testing.assert_array_equal(t1, t2)
        np.testing.assert_array_equal(w1, w2)

    def test_zero_withdrawal_never_depletes(self, sample_returns_df, default_allocation, default_expenses):
        traj, _ = run_simulation(
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
        _, wd = run_simulation(
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
        # Check at least one simulation has non-constant withdrawals
        has_variation = False
        for i in range(50):
            active = wd[i, wd[i] > 0]
            if len(active) > 1 and not np.allclose(active, active[0]):
                has_variation = True
                break
        assert has_variation, "Dynamic strategy should produce varying withdrawals"

    def test_with_cash_flows(self, sample_returns_df, default_allocation, default_expenses):
        cfs = [CashFlowItem("income", 10_000, start_year=1, duration=5, inflation_adjusted=True)]
        traj_with, _ = run_simulation(
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
        traj_without, _ = run_simulation(
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


# ---------------------------------------------------------------------------
# Pydantic Validation Tests
# ---------------------------------------------------------------------------

class TestAllocationValidation:

    def test_valid_allocation(self):
        from backend.schemas import AllocationSchema
        a = AllocationSchema(us_stock=0.5, intl_stock=0.3, us_bond=0.2)
        assert a.us_stock == 0.5

    def test_invalid_allocation_sum(self):
        from backend.schemas import AllocationSchema
        with pytest.raises(Exception, match="sum to 100%"):
            AllocationSchema(us_stock=0.5, intl_stock=0.5, us_bond=0.5)

    def test_allocation_small_rounding(self):
        """Small floating-point deviations (< 1%) should be accepted."""
        from backend.schemas import AllocationSchema
        a = AllocationSchema(us_stock=0.333, intl_stock=0.334, us_bond=0.333)
        assert abs(a.us_stock + a.intl_stock + a.us_bond - 1.0) < 0.01
