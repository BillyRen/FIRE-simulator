"""Core simulation engine tests.

Tests cover: bootstrap (single + pooled), portfolio returns, cash flow schedule,
Monte Carlo simulation, run_simulation_from_matrix, raw_to_combined,
and AllocationSchema validation.
"""

import numpy as np
import pandas as pd
import pytest

from simulator.bootstrap import block_bootstrap, block_bootstrap_pooled
from simulator.cashflow import CashFlowItem, build_cf_schedule
from simulator.monte_carlo import run_simulation, run_simulation_from_matrix
from simulator.portfolio import compute_real_portfolio_returns
from simulator.sweep import raw_to_combined, _simulate_success_and_funded


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
        assert all_vals.intersection(a_vals) and all_vals.intersection(b_vals)


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

    def test_glide_path_fixed(self, sample_returns_df, default_allocation, default_expenses):
        """Glide path with fixed strategy should run without error."""
        end_alloc = {"domestic_stock": 0.2, "global_stock": 0.1, "domestic_bond": 0.7}
        traj, wd, ret_mat, infl_mat = run_simulation(
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
            glide_path_end_allocation=end_alloc,
            glide_path_years=5,
        )
        assert traj.shape == (20, 11)
        assert wd.shape == (20, 10)
        assert np.all(traj[:, 0] == 1_000_000)

    def test_glide_path_dynamic(self, sample_returns_df, default_allocation, default_expenses):
        """Glide path with dynamic strategy should run without error."""
        end_alloc = {"domestic_stock": 0.2, "global_stock": 0.1, "domestic_bond": 0.7}
        traj, wd, ret_mat, infl_mat = run_simulation(
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
            withdrawal_strategy="dynamic",
            glide_path_end_allocation=end_alloc,
            glide_path_years=5,
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


# ---------------------------------------------------------------------------
# run_simulation_from_matrix Tests
# ---------------------------------------------------------------------------

class TestRunSimulationFromMatrix:

    def test_equivalence_fixed_no_cf(self, sample_returns_df, default_allocation, default_expenses):
        """run_simulation_from_matrix matches run_simulation with same random state."""
        # Run full simulation to get the return matrices
        traj1, wd1, ret_mat, infl_mat = run_simulation(
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=3,
            max_block=5,
            num_simulations=50,
            returns_df=sample_returns_df,
            seed=42,
            withdrawal_strategy="fixed",
        )

        # Now run from the same matrices
        traj2, wd2, _, _ = run_simulation_from_matrix(
            real_returns_matrix=ret_mat,
            inflation_matrix=infl_mat,
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            retirement_years=10,
            withdrawal_strategy="fixed",
        )

        np.testing.assert_allclose(traj1, traj2, rtol=1e-10)
        np.testing.assert_allclose(wd1, wd2, rtol=1e-10)

    def test_equivalence_dynamic(self, sample_returns_df, default_allocation, default_expenses):
        """run_simulation_from_matrix matches run_simulation for dynamic strategy."""
        traj1, wd1, ret_mat, infl_mat = run_simulation(
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=3,
            max_block=5,
            num_simulations=30,
            returns_df=sample_returns_df,
            seed=99,
            withdrawal_strategy="dynamic",
            dynamic_ceiling=0.05,
            dynamic_floor=0.025,
        )

        traj2, wd2, _, _ = run_simulation_from_matrix(
            real_returns_matrix=ret_mat,
            inflation_matrix=infl_mat,
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            retirement_years=10,
            withdrawal_strategy="dynamic",
            dynamic_ceiling=0.05,
            dynamic_floor=0.025,
        )

        np.testing.assert_allclose(traj1, traj2, rtol=1e-10)
        np.testing.assert_allclose(wd1, wd2, rtol=1e-10)

    def test_with_cash_flows(self, sample_returns_df, default_allocation, default_expenses):
        """run_simulation_from_matrix handles cash flows correctly."""
        cfs = [
            CashFlowItem(name="pension", amount=10_000, start_year=5, duration=5, inflation_adjusted=True),
        ]
        traj1, wd1, ret_mat, infl_mat = run_simulation(
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=3,
            max_block=5,
            num_simulations=30,
            returns_df=sample_returns_df,
            seed=7,
            withdrawal_strategy="fixed",
            cash_flows=cfs,
        )

        traj2, wd2, _, _ = run_simulation_from_matrix(
            real_returns_matrix=ret_mat,
            inflation_matrix=infl_mat,
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            retirement_years=10,
            withdrawal_strategy="fixed",
            cash_flows=cfs,
        )

        np.testing.assert_allclose(traj1, traj2, rtol=1e-10)
        np.testing.assert_allclose(wd1, wd2, rtol=1e-10)

    def test_different_withdrawal_amounts_same_matrix(self, sample_returns_df, default_allocation, default_expenses):
        """Different withdrawal amounts on same returns should give different results."""
        _, _, ret_mat, infl_mat = run_simulation(
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=10,
            min_block=3, max_block=5,
            num_simulations=50,
            returns_df=sample_returns_df,
            seed=42,
        )

        traj_low, _, _, _ = run_simulation_from_matrix(
            ret_mat, infl_mat, 500_000, 15_000, 10,
        )
        traj_high, _, _, _ = run_simulation_from_matrix(
            ret_mat, infl_mat, 500_000, 40_000, 10,
        )

        # Lower withdrawal => higher final values on average
        assert np.mean(traj_low[:, -1]) > np.mean(traj_high[:, -1])

    def test_output_shapes(self, sample_returns_df, default_allocation, default_expenses):
        """Verify output array shapes."""
        n_sims, n_years = 20, 10
        _, _, ret_mat, infl_mat = run_simulation(
            initial_portfolio=500_000,
            annual_withdrawal=20_000,
            allocation=default_allocation,
            expense_ratios=default_expenses,
            retirement_years=n_years,
            min_block=3, max_block=5,
            num_simulations=n_sims,
            returns_df=sample_returns_df,
            seed=42,
        )

        traj, wd, ret_out, infl_out = run_simulation_from_matrix(
            ret_mat, infl_mat, 500_000, 20_000, n_years,
        )
        assert traj.shape == (n_sims, n_years + 1)
        assert wd.shape == (n_sims, n_years)
        assert ret_out.shape == (n_sims, n_years)


class TestPositiveCFDoesNotMaskDepletion:
    """Verify that positive cash flows (pension/social security) do not prevent
    portfolio depletion detection."""

    def test_positive_cf_does_not_rescue_depleted_portfolio(self):
        """When portfolio depletes due to market losses, positive CF should not
        prevent failure even if CF > withdrawal."""
        n_sims, n_years = 5, 10
        # Extreme negative returns to force depletion
        real_returns = np.full((n_sims, n_years), -0.50)  # -50% per year
        inflation = np.zeros((n_sims, n_years))
        # Large positive CF that would normally rescue
        large_pension = CashFlowItem(
            name="pension", amount=100_000, start_year=0,
            duration=n_years, inflation_adjusted=True,
        )

        traj, wd, _, _ = run_simulation_from_matrix(
            real_returns_matrix=real_returns,
            inflation_matrix=inflation,
            initial_portfolio=200_000,
            annual_withdrawal=50_000,
            retirement_years=n_years,
            withdrawal_strategy="fixed",
            cash_flows=[large_pension],
        )

        # Portfolio should eventually deplete (returns are -50%/year)
        # Before the fix, positive CF would prevent depletion forever
        assert float(np.mean(traj[:, -1] > 0)) < 1.0, (
            "Large positive CF should not make portfolio immortal"
        )

    def test_negative_cf_still_deducts_before_check(self):
        """Negative CFs (extra expenses) should reduce portfolio before depletion check."""
        n_sims, n_years = 5, 10
        real_returns = np.full((n_sims, n_years), -0.10)
        inflation = np.zeros((n_sims, n_years))
        # Extra expense that accelerates depletion
        expense = CashFlowItem(
            name="expense", amount=-50_000, start_year=0,
            duration=n_years, inflation_adjusted=True,
        )

        traj_no_cf, _, _, _ = run_simulation_from_matrix(
            real_returns_matrix=real_returns,
            inflation_matrix=inflation,
            initial_portfolio=200_000,
            annual_withdrawal=20_000,
            retirement_years=n_years,
            withdrawal_strategy="fixed",
        )
        traj_with_cf, _, _, _ = run_simulation_from_matrix(
            real_returns_matrix=real_returns,
            inflation_matrix=inflation,
            initial_portfolio=200_000,
            annual_withdrawal=20_000,
            retirement_years=n_years,
            withdrawal_strategy="fixed",
            cash_flows=[expense],
        )

        # Negative CF should cause earlier depletion
        sr_no_cf = float(np.mean(traj_no_cf[:, -1] > 0))
        sr_with_cf = float(np.mean(traj_with_cf[:, -1] > 0))
        assert sr_with_cf <= sr_no_cf

    def test_backtest_records_actual_withdrawal(self):
        """run_simple_historical_backtest should record actual withdrawal, not intended."""
        from simulator.monte_carlo import run_simple_historical_backtest

        # Returns so bad the portfolio depletes quickly
        real_returns = np.array([-0.8, -0.5, -0.3, 0.05, 0.05])
        result = run_simple_historical_backtest(
            real_returns=real_returns,
            initial_portfolio=100_000,
            annual_withdrawal=50_000,
            retirement_years=5,
        )

        # After -80% return: value = 100k * 0.2 = 20k, withdraw min(50k, 20k) = 20k
        # First withdrawal should be capped at available value, not full 50k
        assert result["withdrawals"][0] < 50_000, (
            "Withdrawal should be capped at portfolio value after growth"
        )


# ---------------------------------------------------------------------------
# raw_to_combined Tests
# ---------------------------------------------------------------------------

class TestRawToCombined:

    def test_basic_combination(self):
        """Verify raw_to_combined produces correct weighted returns."""
        n_sims, n_years = 10, 5
        rng = np.random.default_rng(42)
        raw = {
            "domestic_stock": rng.normal(0.10, 0.15, (n_sims, n_years)),
            "global_stock": rng.normal(0.08, 0.18, (n_sims, n_years)),
            "domestic_bond": rng.normal(0.04, 0.05, (n_sims, n_years)),
            "inflation": rng.normal(0.03, 0.01, (n_sims, n_years)),
        }
        alloc = {"domestic_stock": 0.6, "global_stock": 0.2, "domestic_bond": 0.2}
        result = raw_to_combined(raw, alloc)
        assert result.shape == (n_sims, n_years)

        # Manual check: compute expected nominal and real return
        nominal = (0.6 * raw["domestic_stock"] + 0.2 * raw["global_stock"]
                   + 0.2 * raw["domestic_bond"])
        expected = (1.0 + nominal) / (1.0 + raw["inflation"]) - 1.0
        np.testing.assert_allclose(result, expected, rtol=1e-12)

    def test_leverage(self):
        """Verify leverage math."""
        n_sims, n_years = 5, 3
        raw = {
            "domestic_stock": np.full((n_sims, n_years), 0.10),
            "global_stock": np.full((n_sims, n_years), 0.08),
            "domestic_bond": np.full((n_sims, n_years), 0.04),
            "inflation": np.full((n_sims, n_years), 0.02),
        }
        alloc = {"domestic_stock": 0.5, "global_stock": 0.3, "domestic_bond": 0.2}
        leverage = 1.5
        spread = 0.01

        result = raw_to_combined(raw, alloc, leverage=leverage, borrowing_spread=spread)
        nominal_base = 0.5 * 0.10 + 0.3 * 0.08 + 0.2 * 0.04
        nominal_lev = leverage * nominal_base - (leverage - 1.0) * (0.02 + spread)
        expected = (1.0 + nominal_lev) / (1.0 + 0.02) - 1.0
        np.testing.assert_allclose(result, expected, rtol=1e-12)

    def test_different_allocations_different_results(self):
        """Different allocations on same raw data should give different results."""
        n_sims, n_years = 10, 5
        rng = np.random.default_rng(42)
        raw = {
            "domestic_stock": rng.normal(0.10, 0.15, (n_sims, n_years)),
            "global_stock": rng.normal(0.08, 0.18, (n_sims, n_years)),
            "domestic_bond": rng.normal(0.04, 0.05, (n_sims, n_years)),
            "inflation": rng.normal(0.03, 0.01, (n_sims, n_years)),
        }
        r1 = raw_to_combined(raw, {"domestic_stock": 0.8, "global_stock": 0.1, "domestic_bond": 0.1})
        r2 = raw_to_combined(raw, {"domestic_stock": 0.2, "global_stock": 0.2, "domestic_bond": 0.6})
        assert not np.allclose(r1, r2)


# ---------------------------------------------------------------------------
# _simulate_success_and_funded declining/smile params Tests
# ---------------------------------------------------------------------------

class TestSimulateSuccessFundedStrategies:

    def test_declining_params_affect_result(self):
        """Declining strategy params should change the funded ratio."""
        n_sims, n_years = 100, 30
        rng = np.random.default_rng(42)
        ret_mat = rng.normal(0.05, 0.15, (n_sims, n_years))

        sr1, fr1 = _simulate_success_and_funded(
            ret_mat, 1_000_000, 50_000,
            "declining", 0.05, 0.025,
            retirement_age=45,
            declining_rate=0.0,
            declining_start_age=65,
        )
        sr2, fr2 = _simulate_success_and_funded(
            ret_mat, 1_000_000, 50_000,
            "declining", 0.05, 0.025,
            retirement_age=45,
            declining_rate=0.05,
            declining_start_age=55,
        )
        # Faster decline => higher survival (less total withdrawal)
        assert fr2 >= fr1

    def test_smile_params_affect_result(self):
        """Smile strategy params should change the funded ratio."""
        n_sims, n_years = 100, 40
        rng = np.random.default_rng(42)
        ret_mat = rng.normal(0.04, 0.15, (n_sims, n_years))

        sr1, fr1 = _simulate_success_and_funded(
            ret_mat, 1_000_000, 50_000,
            "smile", 0.05, 0.025,
            retirement_age=45,
            smile_decline_rate=0.0,
            smile_decline_start_age=65,
            smile_min_age=80,
            smile_increase_rate=0.03,
        )
        sr2, fr2 = _simulate_success_and_funded(
            ret_mat, 1_000_000, 50_000,
            "smile", 0.05, 0.025,
            retirement_age=45,
            smile_decline_rate=0.03,
            smile_decline_start_age=55,
            smile_min_age=75,
            smile_increase_rate=0.0,
        )
        # More decline + no late-life increase => better survival
        assert fr2 >= fr1


# ---------------------------------------------------------------------------
# Cross-module CF timing consistency tests
# ---------------------------------------------------------------------------

class TestCFTimingConsistency:
    """Verify that sweep._simulate_success_and_funded and monte_carlo.run_simulation_from_matrix
    produce consistent success rates when using positive cash flows."""

    def test_positive_cf_consistency(self):
        """Same returns + positive CF → sweep and MC should agree on success rate."""
        n_sims, n_years = 200, 20
        rng = np.random.default_rng(42)
        ret_mat = rng.normal(0.02, 0.15, (n_sims, n_years))
        infl_mat = np.zeros((n_sims, n_years))

        pension = CashFlowItem(
            name="pension", amount=20_000, start_year=1,
            duration=n_years, inflation_adjusted=True,
        )

        # MC path
        traj, _, _, _ = run_simulation_from_matrix(
            real_returns_matrix=ret_mat,
            inflation_matrix=infl_mat,
            initial_portfolio=500_000,
            annual_withdrawal=40_000,
            retirement_years=n_years,
            withdrawal_strategy="fixed",
            cash_flows=[pension],
        )
        from simulator.statistics import compute_success_rate as csr
        mc_sr = csr(traj, n_years)

        # Sweep path
        sweep_sr, _ = _simulate_success_and_funded(
            ret_mat, 500_000, 40_000,
            "fixed", 0.05, 0.025,
            cash_flows=[pension],
            inflation_matrix=infl_mat,
        )

        assert abs(mc_sr - sweep_sr) < 0.05, (
            f"MC success_rate={mc_sr:.3f} vs sweep={sweep_sr:.3f} differ too much"
        )

    def test_negative_cf_consistency(self):
        """Same returns + negative CF → sweep and MC should agree."""
        n_sims, n_years = 200, 20
        rng = np.random.default_rng(99)
        ret_mat = rng.normal(0.05, 0.12, (n_sims, n_years))
        infl_mat = np.zeros((n_sims, n_years))

        expense = CashFlowItem(
            name="extra_expense", amount=-15_000, start_year=1,
            duration=n_years, inflation_adjusted=True,
        )

        from simulator.statistics import compute_success_rate as csr

        traj, _, _, _ = run_simulation_from_matrix(
            real_returns_matrix=ret_mat,
            inflation_matrix=infl_mat,
            initial_portfolio=500_000,
            annual_withdrawal=30_000,
            retirement_years=n_years,
            withdrawal_strategy="fixed",
            cash_flows=[expense],
        )
        mc_sr = csr(traj, n_years)

        sweep_sr, _ = _simulate_success_and_funded(
            ret_mat, 500_000, 30_000,
            "fixed", 0.05, 0.025,
            cash_flows=[expense],
            inflation_matrix=infl_mat,
        )

        assert abs(mc_sr - sweep_sr) < 0.05, (
            f"MC success_rate={mc_sr:.3f} vs sweep={sweep_sr:.3f} differ too much"
        )


# ---------------------------------------------------------------------------
# ProcessPoolExecutor fallback test
# ---------------------------------------------------------------------------

class TestProcessPoolFallback:
    """Verify that pregenerate_return_scenarios falls back gracefully."""

    def test_fallback_on_pool_failure(self, sample_returns_df, default_allocation, default_expenses):
        """When ProcessPoolExecutor fails, fallback to sequential execution."""
        from unittest.mock import patch
        from simulator.sweep import pregenerate_return_scenarios

        def raise_permission_error(*args, **kwargs):
            raise PermissionError("pool creation blocked")

        with patch("simulator.sweep.ProcessPoolExecutor", side_effect=raise_permission_error):
            with patch("simulator.sweep.MAX_WORKERS", 4):
                scenarios, inflation = pregenerate_return_scenarios(
                    allocation=default_allocation,
                    expense_ratios=default_expenses,
                    retirement_years=10,
                    min_block=3,
                    max_block=5,
                    num_simulations=200,  # > 100 to trigger pool path
                    returns_df=sample_returns_df,
                    seed=42,
                )

        assert scenarios.shape == (200, 10)
        assert inflation.shape == (200, 10)
        assert not np.all(scenarios == 0)


# ---------------------------------------------------------------------------
# Funded ratio cross-module consistency test
# ---------------------------------------------------------------------------

class TestFundedRatioConsistency:
    """Verify funded_ratio alignment between statistics.py and sweep.py."""

    def test_funded_ratio_year_one_depletion(self):
        """All paths deplete at year 1 → funded_ratio = 1/N, not 0."""
        from simulator.statistics import compute_funded_ratio

        n_sims, n_years = 50, 20
        trajectories = np.zeros((n_sims, n_years + 1))
        trajectories[:, 0] = 100_000
        result = compute_funded_ratio(trajectories, n_years)
        assert result == pytest.approx(1.0 / n_years)

    def test_funded_ratio_last_year_depletion(self):
        """Paths deplete at exactly the final year → fully funded."""
        from simulator.statistics import compute_funded_ratio

        n_sims, n_years = 50, 10
        trajectories = np.full((n_sims, n_years + 1), 50_000.0)
        trajectories[:, -1] = 0.0
        result = compute_funded_ratio(trajectories, n_years)
        assert result == pytest.approx(1.0)

    def test_sweep_and_statistics_agree(self):
        """sweep depletion_years uses year+1, should match statistics funded_ratio."""
        n_sims, n_years = 100, 15
        rng = np.random.default_rng(42)
        ret_mat = rng.normal(0.03, 0.18, (n_sims, n_years))
        infl_mat = np.zeros((n_sims, n_years))

        # Get MC trajectories
        traj, _, _, _ = run_simulation_from_matrix(
            real_returns_matrix=ret_mat,
            inflation_matrix=infl_mat,
            initial_portfolio=500_000,
            annual_withdrawal=50_000,
            retirement_years=n_years,
            withdrawal_strategy="fixed",
        )

        from simulator.statistics import compute_funded_ratio
        stats_fr = compute_funded_ratio(traj, n_years)

        # Sweep path (same returns, no CF, fixed strategy)
        _, sweep_fr = _simulate_success_and_funded(
            ret_mat, 500_000, 50_000,
            "fixed", 0.05, 0.025,
        )

        assert abs(stats_fr - sweep_fr) < 0.05, (
            f"statistics funded_ratio={stats_fr:.3f} vs sweep={sweep_fr:.3f}"
        )

    def test_success_rate_matches_funded_ratio(self):
        """success_rate and funded_ratio should agree on last-year depletion."""
        from simulator.statistics import compute_funded_ratio, compute_success_rate

        n_sims, n_years = 100, 20
        # Half paths survive, half deplete at last year (still success)
        trajectories = np.full((n_sims, n_years + 1), 50_000.0)
        trajectories[50:, -1] = 0.0  # last-year depletion

        sr = compute_success_rate(trajectories, n_years)
        fr = compute_funded_ratio(trajectories, n_years)
        assert sr == 1.0
        assert fr == pytest.approx(1.0)
