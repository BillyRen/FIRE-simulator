"""Tests for statistics module: funded ratio, effective funded ratio, compute_statistics."""

import numpy as np
import pytest

from simulator.statistics import (
    compute_funded_ratio,
    compute_effective_funded_ratio,
    compute_statistics,
    compute_portfolio_metrics,
    compute_single_path_metrics,
)


class TestComputeFundedRatio:
    """Tests for compute_funded_ratio vectorized implementation."""

    def test_all_survive(self):
        """No path depletes -> funded ratio = 1.0."""
        trajectories = np.full((100, 31), 100_000.0)
        assert compute_funded_ratio(trajectories, 30) == 1.0

    def test_all_deplete_year_one(self):
        """All paths deplete at year 1 -> funded ratio = 1/retirement_years."""
        trajectories = np.zeros((50, 21))
        trajectories[:, 0] = 100_000  # initial value
        # years 1..20 are all 0
        result = compute_funded_ratio(trajectories, 20)
        assert result == pytest.approx(1.0 / 20.0)  # argmax=0 +1 → 1/20

    def test_half_deplete_midway(self):
        """Half paths deplete at midpoint, half survive."""
        n_sims, years = 100, 20
        trajectories = np.full((n_sims, years + 1), 50_000.0)
        # First 50 paths deplete at year 10
        for i in range(50):
            trajectories[i, 11:] = 0.0
        result = compute_funded_ratio(trajectories, years)
        # 50 paths: argmax=10 +1 → 11/20=0.55, 50 paths: 20/20=1.0
        expected = (50 * (11 / 20) + 50 * 1.0) / 100
        assert result == pytest.approx(expected, abs=0.01)

    def test_negative_values_count_as_depleted(self):
        """Negative portfolio values should count as depleted."""
        trajectories = np.full((10, 11), 100_000.0)
        trajectories[:, 5:] = -1000.0  # negative from year 5
        result = compute_funded_ratio(trajectories, 10)
        # First depletion at index 4 + 1 = 5 funded years
        expected = 5.0 / 10.0
        assert result == pytest.approx(expected)

    def test_zero_at_boundary(self):
        """Exactly zero at final year only."""
        trajectories = np.full((10, 11), 100_000.0)
        trajectories[:, -1] = 0.0  # zero only at last year
        result = compute_funded_ratio(trajectories, 10)
        # Depleted at exactly final year: index 9 + 1 = 10 → fully funded
        expected = 10.0 / 10.0
        assert result == pytest.approx(expected)

    def test_invalid_retirement_years(self):
        with pytest.raises(ValueError):
            compute_funded_ratio(np.ones((5, 5)), 0)


class TestComputeEffectiveFundedRatio:
    """Tests for vectorized compute_effective_funded_ratio."""

    def test_no_floor_breach(self):
        """When withdrawals never drop below floor, effective = traditional."""
        n_sims, years = 50, 20
        withdrawals = np.full((n_sims, years), 40_000.0)
        initial_wd = 40_000.0
        funded, success = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5
        )
        assert funded == pytest.approx(1.0)
        assert success == pytest.approx(1.0)

    def test_all_breach_floor_immediately(self):
        """All paths have withdrawals below floor from year 0."""
        n_sims, years = 30, 20
        withdrawals = np.full((n_sims, years), 10_000.0)  # below 50% of 40k
        initial_wd = 40_000.0
        funded, success = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5
        )
        assert funded == pytest.approx(1.0 / 20.0)  # argmax=0 +1 → 1/20
        assert success == pytest.approx(0.0)

    def test_breach_midway(self):
        """All paths breach floor at year 10 of 20."""
        n_sims, years = 40, 20
        withdrawals = np.full((n_sims, years), 40_000.0)
        withdrawals[:, 10:] = 15_000.0  # below 50% of 40k = 20k
        initial_wd = 40_000.0
        funded, success = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5
        )
        expected_funded = 11.0 / 20.0  # argmax=10, +1=11
        assert funded == pytest.approx(expected_funded)
        assert success == pytest.approx(0.0)

    def test_with_asset_depletion(self):
        """Asset depletion before consumption floor breach."""
        n_sims, years = 20, 20
        withdrawals = np.full((n_sims, years), 40_000.0)  # never breach floor
        trajectories = np.full((n_sims, years + 1), 100_000.0)
        trajectories[:, 6:] = 0.0  # asset depleted at year 6 (index 5 in depleted array)
        initial_wd = 40_000.0
        funded, success = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5,
            trajectories=trajectories,
        )
        expected_funded = 6.0 / 20.0  # argmax=5, +1=6
        assert funded == pytest.approx(expected_funded)
        assert success == pytest.approx(0.0)

    def test_mixed_paths(self):
        """Some paths breach floor, others don't."""
        n_sims, years = 100, 20
        withdrawals = np.full((n_sims, years), 40_000.0)
        # First 50 paths breach at year 10
        withdrawals[:50, 10:] = 10_000.0
        initial_wd = 40_000.0
        funded, success = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5
        )
        expected_funded = (50 * (11.0 / 20.0) + 50 * 1.0) / 100  # argmax=10, +1=11
        assert funded == pytest.approx(expected_funded)
        assert success == pytest.approx(0.5)

    def test_floor_amount_overrides_percentage(self):
        """Fixed amount > percentage floor -> uses fixed amount."""
        n_sims, years = 50, 20
        withdrawals = np.full((n_sims, years), 25_000.0)
        initial_wd = 40_000.0
        # Percentage floor = 40000 * 0.5 = 20000 -> 25000 > 20000, no breach
        funded_pct, success_pct = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5
        )
        assert success_pct == pytest.approx(1.0)
        # Fixed amount = 30000 > 20000 -> overrides; 25000 < 30000 -> breach
        funded_amt, success_amt = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5,
            consumption_floor_amount=30_000.0,
        )
        assert success_amt == pytest.approx(0.0)

    def test_floor_amount_below_percentage(self):
        """Fixed amount < percentage floor -> percentage still governs."""
        n_sims, years = 50, 20
        withdrawals = np.full((n_sims, years), 15_000.0)  # below 50% of 40k=20k
        initial_wd = 40_000.0
        # Percentage floor = 20000, amount = 10000 -> max(20000,10000) = 20000
        funded, success = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5,
            consumption_floor_amount=10_000.0,
        )
        assert success == pytest.approx(0.0)
        assert funded == pytest.approx(1.0 / 20.0)  # argmax=0, +1=1

    def test_floor_amount_zero_backward_compat(self):
        """consumption_floor_amount=0 behaves identically to old code."""
        n_sims, years = 100, 20
        withdrawals = np.full((n_sims, years), 40_000.0)
        withdrawals[:50, 10:] = 10_000.0
        initial_wd = 40_000.0
        funded_old, success_old = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5,
        )
        funded_new, success_new = compute_effective_funded_ratio(
            withdrawals, initial_wd, years, consumption_floor=0.5,
            consumption_floor_amount=0.0,
        )
        assert funded_new == pytest.approx(funded_old)
        assert success_new == pytest.approx(success_old)


class TestComputeStatistics:
    """Tests for compute_statistics result structure."""

    def test_output_structure(self):
        """Verify all expected fields are populated."""
        n_sims, years = 100, 20
        rng = np.random.default_rng(42)
        trajectories = np.cumsum(rng.normal(5000, 2000, (n_sims, years + 1)), axis=1)
        trajectories[:, 0] = 500_000

        result = compute_statistics(trajectories, years)

        assert result.num_simulations == n_sims
        assert result.retirement_years == years
        assert 0.0 <= result.success_rate <= 1.0
        assert 0.0 <= result.funded_ratio <= 1.0
        assert len(result.final_values) == n_sims
        assert result.final_mean == pytest.approx(float(np.mean(trajectories[:, -1])))
        assert result.final_median == pytest.approx(float(np.median(trajectories[:, -1])))

        # Percentile trajectories should have all expected keys
        for p in [5, 10, 25, 50, 75, 90, 95]:
            assert p in result.percentile_trajectories
            assert len(result.percentile_trajectories[p]) == years + 1
            assert p in result.final_percentiles

    def test_with_withdrawals(self):
        """Withdrawal statistics should be populated when provided."""
        n_sims, years = 50, 10
        trajectories = np.full((n_sims, years + 1), 500_000.0)
        withdrawals = np.full((n_sims, years), 20_000.0)

        result = compute_statistics(trajectories, years, withdrawals=withdrawals)

        assert result.withdrawal_percentile_trajectories is not None
        assert result.withdrawal_mean_trajectory is not None
        assert len(result.withdrawal_mean_trajectory) == years
        assert result.withdrawal_mean_trajectory[0] == pytest.approx(20_000.0)

    def test_without_withdrawals(self):
        """Without withdrawals, withdrawal fields should be None."""
        trajectories = np.full((10, 11), 100_000.0)
        result = compute_statistics(trajectories, 10)
        assert result.withdrawal_percentile_trajectories is None
        assert result.withdrawal_mean_trajectory is None

    def test_all_zero_final(self):
        """All paths end at 0 -> success_rate = 0."""
        trajectories = np.full((20, 11), 100_000.0)
        trajectories[:, -1] = 0.0
        result = compute_statistics(trajectories, 10)
        assert result.success_rate == 0.0


class TestPortfolioMetrics:
    """Tests for compute_portfolio_metrics and compute_single_path_metrics."""

    def test_portfolio_metrics_structure(self):
        rng = np.random.default_rng(42)
        real_returns = rng.normal(0.05, 0.15, (100, 20))
        inflation = rng.normal(0.02, 0.01, (100, 20))
        rows = compute_portfolio_metrics(real_returns, inflation)
        assert len(rows) == 5
        expected_metrics = {
            "ann_nominal_return", "ann_real_return",
            "ann_inflation", "ann_volatility", "max_real_drawdown",
        }
        assert {r["metric"] for r in rows} == expected_metrics
        for row in rows:
            for p in ["P10", "P25", "P50", "P75", "P90"]:
                assert p in row

    def test_single_path_metrics_structure(self):
        rng = np.random.default_rng(42)
        real_returns = rng.normal(0.05, 0.15, 20)
        inflation = rng.normal(0.02, 0.01, 20)
        rows = compute_single_path_metrics(real_returns, inflation)
        assert len(rows) == 5
        for row in rows:
            assert "metric" in row
            assert "value" in row

    def test_single_path_empty(self):
        assert compute_single_path_metrics(np.array([]), np.array([])) == []
