"""验证性能优化后的向量化路径与标量路径数值等价。"""

import numpy as np
import pytest

from simulator.sweep import _simulate_success_and_funded
from simulator.monte_carlo import compute_withdrawal
from simulator.guardrail import (
    find_rate_for_target,
    find_rate_for_target_cf_aware,
    build_success_rate_table,
    run_fixed_baseline,
)


@pytest.fixture
def scenarios():
    """可复现的回报矩阵。"""
    rng = np.random.default_rng(42)
    return rng.normal(0.05, 0.15, (200, 30))


@pytest.fixture
def success_table(scenarios):
    """构建成功率查找表。"""
    return build_success_rate_table(scenarios)


# ─────────────────────────────────────────────────────────────────────
# 1. _simulate_success_and_funded: vectorized vs scalar for fixed
# ─────────────────────────────────────────────────────────────────────

def _simulate_scalar(real_returns_matrix, initial_portfolio, annual_withdrawal):
    """纯标量双循环实现（ground truth）。"""
    num_sims, retirement_years = real_returns_matrix.shape
    survived = 0
    depletion_years = np.full(num_sims, float(retirement_years))

    for i in range(num_sims):
        value = initial_portfolio
        failed = False
        for year in range(retirement_years):
            value_after_growth = value * (1.0 + real_returns_matrix[i, year])
            actual_wd = min(annual_withdrawal, max(value_after_growth, 0.0))
            value = value_after_growth - actual_wd
            if value <= 0:
                depletion_years[i] = float(year + 1)
                failed = True
                break
        if not failed:
            survived += 1

    success_rate = survived / num_sims
    funded_ratio = float(np.mean(np.minimum(depletion_years / retirement_years, 1.0)))
    return success_rate, funded_ratio


class TestSimulateSuccessFundedEquivalence:
    """向量化 _simulate_success_and_funded 与标量实现的等价性。"""

    def test_fixed_no_cf_equivalence(self, scenarios):
        """fixed 策略 + 无现金流：向量化路径应与标量路径完全一致。"""
        portfolio = 1_000_000
        withdrawal = 40_000

        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal,
            "fixed", 0.05, 0.025,
        )
        sr_scalar, fr_scalar = _simulate_scalar(scenarios, portfolio, withdrawal)

        assert sr_vec == pytest.approx(sr_scalar, abs=1e-10)
        assert fr_vec == pytest.approx(fr_scalar, abs=1e-10)

    def test_various_withdrawal_rates(self, scenarios):
        """多种提取率下的一致性。"""
        portfolio = 1_000_000
        for rate in [0.02, 0.04, 0.06, 0.08, 0.10]:
            withdrawal = portfolio * rate
            sr_vec, fr_vec = _simulate_success_and_funded(
                scenarios, portfolio, withdrawal,
                "fixed", 0.05, 0.025,
            )
            sr_scalar, fr_scalar = _simulate_scalar(scenarios, portfolio, withdrawal)
            assert sr_vec == pytest.approx(sr_scalar, abs=1e-10), f"rate={rate}"
            assert fr_vec == pytest.approx(fr_scalar, abs=1e-10), f"rate={rate}"

    def test_dynamic_strategy_unchanged(self, scenarios):
        """dynamic 策略仍走标量路径，不应出错。"""
        portfolio = 1_000_000
        withdrawal = 40_000
        sr, fr = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal,
            "dynamic", 0.05, 0.025,
        )
        assert 0.0 <= sr <= 1.0
        assert 0.0 <= fr <= 1.0


# ─────────────────────────────────────────────────────────────────────
# 2. find_rate_for_target: searchsorted vs linear scan
# ─────────────────────────────────────────────────────────────────────

def _find_rate_linear(table, rate_grid, target_success, remaining_years):
    """原始线性扫描实现（ground truth）。"""
    max_years = table.shape[1] - 1
    remaining_years = min(remaining_years, max_years)
    remaining_years = max(remaining_years, 1)
    col = table[:, remaining_years]
    if col[0] < target_success:
        return 0.0
    if col[-1] >= target_success:
        return float(rate_grid[-1])
    for i in range(len(col) - 1):
        if col[i] >= target_success and col[i + 1] < target_success:
            frac = (target_success - col[i + 1]) / (col[i] - col[i + 1])
            return float(rate_grid[i + 1] + frac * (rate_grid[i] - rate_grid[i + 1]))
    return float(rate_grid[0])


class TestFindRateEquivalence:
    """searchsorted 版本与线性扫描版本的等价性。"""

    def test_various_targets(self, success_table):
        rate_grid, table = success_table
        for target in [0.5, 0.7, 0.8, 0.9, 0.95, 0.99]:
            for remaining in [5, 10, 20, 30]:
                result = find_rate_for_target(table, rate_grid, target, remaining)
                expected = _find_rate_linear(table, rate_grid, target, remaining)
                assert result == pytest.approx(expected, abs=1e-10), \
                    f"target={target}, remaining={remaining}"

    def test_edge_cases(self, success_table):
        rate_grid, table = success_table
        # target higher than any success rate
        r1 = find_rate_for_target(table, rate_grid, 1.01, 20)
        e1 = _find_rate_linear(table, rate_grid, 1.01, 20)
        assert r1 == pytest.approx(e1, abs=1e-10)

        # target lower than all
        r2 = find_rate_for_target(table, rate_grid, 0.0, 20)
        e2 = _find_rate_linear(table, rate_grid, 0.0, 20)
        assert r2 == pytest.approx(e2, abs=1e-10)


# ─────────────────────────────────────────────────────────────────────
# 3. run_fixed_baseline: vectorized vs scalar
# ─────────────────────────────────────────────────────────────────────

def _run_fixed_baseline_scalar(scenarios, initial_portfolio, baseline_rate, retirement_years):
    """纯标量实现（ground truth）。"""
    num_sims = scenarios.shape[0]
    annual_wd = initial_portfolio * baseline_rate
    trajectories = np.zeros((num_sims, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.zeros((num_sims, retirement_years))

    for i in range(num_sims):
        value = initial_portfolio
        for year in range(retirement_years):
            withdrawals[i, year] = annual_wd
            value = value * (1.0 + scenarios[i, year]) - annual_wd
            if value <= 0:
                value = 0.0
                trajectories[i, year + 1:] = 0.0
                withdrawals[i, year + 1:] = 0.0
                break
            trajectories[i, year + 1] = value

    return trajectories, withdrawals


class TestFixedBaselineEquivalence:
    """向量化 run_fixed_baseline 与标量实现的等价性。"""

    def test_no_cf_equivalence(self, scenarios):
        portfolio = 1_000_000
        rate = 0.04
        retirement_years = scenarios.shape[1]

        traj_vec, wd_vec = run_fixed_baseline(
            scenarios, portfolio, rate, retirement_years,
        )
        traj_scalar, wd_scalar = _run_fixed_baseline_scalar(
            scenarios, portfolio, rate, retirement_years,
        )

        np.testing.assert_allclose(traj_vec, traj_scalar, rtol=1e-12)
        np.testing.assert_allclose(wd_vec, wd_scalar, rtol=1e-12)

    def test_high_withdrawal_rate(self, scenarios):
        """高提取率导致大量路径破产。"""
        portfolio = 1_000_000
        rate = 0.15
        retirement_years = scenarios.shape[1]

        traj_vec, wd_vec = run_fixed_baseline(
            scenarios, portfolio, rate, retirement_years,
        )
        traj_scalar, wd_scalar = _run_fixed_baseline_scalar(
            scenarios, portfolio, rate, retirement_years,
        )

        np.testing.assert_allclose(traj_vec, traj_scalar, rtol=1e-12)
        np.testing.assert_allclose(wd_vec, wd_scalar, rtol=1e-12)
