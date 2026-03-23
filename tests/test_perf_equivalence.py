"""验证性能优化后的向量化路径与标量路径数值等价。"""

import numpy as np
import pytest

from simulator.cashflow import CashFlowItem
from simulator.sweep import _simulate_success_and_funded, _sweep_single_allocation
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

    success_rate = float(np.mean(depletion_years >= retirement_years))
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


# ─────────────────────────────────────────────────────────────────────
# 4. Vectorized CF fast path equivalence
# ─────────────────────────────────────────────────────────────────────

def _simulate_scalar_with_cf(
    real_returns_matrix, initial_portfolio, annual_withdrawal,
    cash_flows, inflation_matrix=None,
    withdrawal_strategy="fixed", retirement_age=45,
    dynamic_ceiling=0.05, dynamic_floor=0.025,
    declining_rate=0.02, declining_start_age=65,
    smile_decline_rate=0.01, smile_decline_start_age=65,
    smile_min_age=80, smile_increase_rate=0.01,
):
    """Pure scalar double-loop reference (ground truth for CF scenarios)."""
    from simulator.cashflow import build_cf_schedule, has_probabilistic_cf

    num_sims, retirement_years = real_returns_matrix.shape
    initial_rate = annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0.0

    has_cf = cash_flows is not None and len(cash_flows) > 0

    if has_cf:
        has_nominal = any(not cf.inflation_adjusted for cf in cash_flows)
        adj_only = [cf for cf in cash_flows if cf.inflation_adjusted]
        fixed_schedule = build_cf_schedule(adj_only, retirement_years)
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
    else:
        fixed_schedule = None
        nominal_cfs = []
        has_nominal = False

    depletion_years = np.full(num_sims, float(retirement_years))
    final_values = np.zeros(num_sims)

    for i in range(num_sims):
        value = initial_portfolio
        prev_wd = annual_withdrawal

        if has_cf:
            if has_nominal and inflation_matrix is not None:
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                cf_schedule = fixed_schedule + nominal_schedule
            else:
                cf_schedule = fixed_schedule
        else:
            cf_schedule = None

        for year in range(retirement_years):
            wd = compute_withdrawal(
                withdrawal_strategy, year, value, annual_withdrawal, prev_wd,
                initial_rate, retirement_age, dynamic_ceiling, dynamic_floor,
                declining_rate, declining_start_age,
                smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
            )
            prev_wd = wd
            value_after_growth = value * (1.0 + real_returns_matrix[i, year])
            actual_wd = min(wd, max(value_after_growth, 0.0))
            value = value_after_growth - actual_wd

            if cf_schedule is not None and cf_schedule[year] < 0:
                value += cf_schedule[year]

            if value <= 0:
                depletion_years[i] = float(year + 1)
                value = 0.0
                break

            if cf_schedule is not None and cf_schedule[year] > 0:
                value += cf_schedule[year]

        final_values[i] = value

    success_rate = float(np.mean(depletion_years >= retirement_years))
    funded_ratio = float(np.mean(np.minimum(depletion_years / retirement_years, 1.0)))
    return success_rate, funded_ratio, depletion_years, final_values


@pytest.fixture
def inflation_scenarios():
    """Reproducible inflation matrix."""
    rng = np.random.default_rng(99)
    return rng.normal(0.03, 0.02, (200, 30))


class TestVectorizedCFEquivalence:
    """Vectorized CF fast path vs scalar reference."""

    def test_fixed_adj_cf_no_growth(self, scenarios):
        """Fixed strategy + inflation-adjusted CFs (no growth)."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [
            CashFlowItem("pension", 20_000, start_year=5, duration=20),
            CashFlowItem("mortgage", -12_000, start_year=1, duration=30),
        ]
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
            cash_flows=cfs,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, cfs,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc

    def test_fixed_adj_cf_with_growth(self, scenarios):
        """Fixed strategy + inflation-adjusted CFs with growth_rate."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [
            CashFlowItem("pension", 15_000, start_year=5, duration=25, growth_rate=0.02),
            CashFlowItem("medical", -5_000, start_year=1, duration=30, growth_rate=0.03),
        ]
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
            cash_flows=cfs,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, cfs,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc

    def test_fixed_nominal_cf(self, scenarios, inflation_scenarios):
        """Fixed strategy + nominal (non-inflation-adjusted) CFs."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [
            CashFlowItem("rent_income", 10_000, start_year=1, duration=20,
                         inflation_adjusted=False, growth_rate=0.03),
        ]
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
            cash_flows=cfs, inflation_matrix=inflation_scenarios,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, cfs,
            inflation_matrix=inflation_scenarios,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc

    def test_fixed_mixed_cf(self, scenarios, inflation_scenarios):
        """Fixed strategy + mixed adj/nominal CFs."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [
            CashFlowItem("pension", 20_000, start_year=5, duration=20),
            CashFlowItem("annuity", 8_000, start_year=1, duration=30,
                         inflation_adjusted=False),
            CashFlowItem("mortgage", -15_000, start_year=1, duration=15),
        ]
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
            cash_flows=cfs, inflation_matrix=inflation_scenarios,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, cfs,
            inflation_matrix=inflation_scenarios,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc

    def test_declining_no_cf(self, scenarios):
        """Declining strategy, no CFs — now vectorized."""
        portfolio = 1_000_000
        withdrawal = 40_000
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal,
            "declining", 0.05, 0.025,
            retirement_age=45, declining_rate=0.02, declining_start_age=65,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, None,
            withdrawal_strategy="declining",
            retirement_age=45, declining_rate=0.02, declining_start_age=65,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc

    def test_declining_with_adj_cf(self, scenarios):
        """Declining strategy + inflation-adjusted CFs."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [CashFlowItem("pension", 15_000, start_year=10, duration=20)]
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal,
            "declining", 0.05, 0.025,
            cash_flows=cfs,
            retirement_age=45, declining_rate=0.02, declining_start_age=65,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, cfs,
            withdrawal_strategy="declining",
            retirement_age=45, declining_rate=0.02, declining_start_age=65,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc

    def test_smile_no_cf(self, scenarios):
        """Smile strategy, no CFs — now vectorized."""
        portfolio = 1_000_000
        withdrawal = 40_000
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal,
            "smile", 0.05, 0.025,
            retirement_age=45,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, None,
            withdrawal_strategy="smile",
            retirement_age=45,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc

    def test_smile_with_adj_cf(self, scenarios):
        """Smile strategy + inflation-adjusted CFs."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [CashFlowItem("pension", 18_000, start_year=8, duration=22)]
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal,
            "smile", 0.05, 0.025,
            cash_flows=cfs,
            retirement_age=45,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, cfs,
            withdrawal_strategy="smile",
            retirement_age=45,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc


class TestAllocationSweepCFEquivalence:
    """_sweep_single_allocation vectorized path vs scalar for CFs."""

    def _run_allocation(self, scenarios, inflation, cfs=None,
                        withdrawal_strategy="fixed", **kwargs):
        """Run allocation sweep with given params."""
        import functools
        shared = {
            "us_stock": scenarios,
            "intl_stock": np.zeros_like(scenarios),
            "us_bond": np.zeros_like(scenarios),
            "inflation": inflation,
        }
        worker = functools.partial(_sweep_single_allocation, _shared=shared)
        return worker((
            1.0, 0.0, 0.0,  # 100% domestic stock
            1_000_000, 40_000, 1.0, 0.0,
            withdrawal_strategy, 0.05, 0.025, 45,
            cfs,
            kwargs.get("declining_rate", 0.02),
            kwargs.get("declining_start_age", 65),
            kwargs.get("smile_decline_rate", 0.01),
            kwargs.get("smile_decline_start_age", 65),
            kwargs.get("smile_min_age", 80),
            kwargs.get("smile_increase_rate", 0.01),
        ))

    def test_adj_cf_final_stats(self, scenarios, inflation_scenarios):
        """Allocation sweep with adj CFs: verify all final value stats."""
        cfs = [
            CashFlowItem("pension", 20_000, start_year=5, duration=20),
            CashFlowItem("mortgage", -12_000, start_year=1, duration=15),
        ]
        result = self._run_allocation(scenarios, inflation_scenarios, cfs=cfs)

        # Compute real returns matching what _sweep_single_allocation does
        # (100% domestic stock, no leverage)
        real_returns = (1.0 + scenarios) / (1.0 + inflation_scenarios) - 1.0

        sr_sc, fr_sc, dep_sc, fv_sc = _simulate_scalar_with_cf(
            real_returns, 1_000_000, 40_000, cfs,
        )
        assert result["success_rate"] == sr_sc
        assert result["funded_ratio"] == fr_sc
        assert result["median_final"] == float(np.median(fv_sc))
        assert result["mean_final"] == float(np.mean(fv_sc))

        sorted_fv = np.sort(fv_sc)
        n10 = max(1, int(0.1 * len(fv_sc)))
        assert result["cvar_10"] == float(np.mean(sorted_fv[:n10]))
        assert result["p90_final"] == float(np.percentile(fv_sc, 90))


class TestNominalCFEdgeCases:
    """Edge case and semantic lock-in tests."""

    def test_nominal_cf_no_inflation_raises(self, scenarios):
        """Nominal CFs with inflation_matrix=None must raise ValueError."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [
            CashFlowItem("annuity", 10_000, start_year=1, duration=20,
                         inflation_adjusted=False),
        ]
        with pytest.raises(ValueError, match="inflation_matrix is required"):
            _simulate_success_and_funded(
                scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
                cash_flows=cfs, inflation_matrix=None,
            )

    def test_grouped_nominal_cf_no_inflation_raises(self, scenarios):
        """Grouped nominal CFs with inflation_matrix=None must also raise."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [
            CashFlowItem("job_a", 15_000, start_year=1, duration=20,
                         inflation_adjusted=False, group="career", probability=0.6),
            CashFlowItem("job_b", 10_000, start_year=1, duration=20,
                         inflation_adjusted=False, group="career", probability=0.4),
        ]
        with pytest.raises(ValueError, match="inflation_matrix is required"):
            _simulate_success_and_funded(
                scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
                cash_flows=cfs, inflation_matrix=None,
            )

    def test_cf_after_retirement_years(self, scenarios):
        """CF starting after retirement_years should be ignored."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [CashFlowItem("late", 50_000, start_year=999, duration=5)]
        sr, fr = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
            cash_flows=cfs,
        )
        sr_no_cf, fr_no_cf = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
        )
        assert sr == sr_no_cf
        assert fr == fr_no_cf

    def test_mixed_expense_income_same_year(self, scenarios):
        """Mixed expense + income CFs in same year."""
        portfolio = 1_000_000
        withdrawal = 40_000
        cfs = [
            CashFlowItem("pension", 30_000, start_year=1, duration=30),
            CashFlowItem("mortgage", -25_000, start_year=1, duration=30),
        ]
        sr_vec, fr_vec = _simulate_success_and_funded(
            scenarios, portfolio, withdrawal, "fixed", 0.05, 0.025,
            cash_flows=cfs,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            scenarios, portfolio, withdrawal, cfs,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc

    def test_single_sim(self):
        """Single simulation path."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.05, 0.15, (1, 30))
        cfs = [CashFlowItem("pension", 10_000, start_year=5, duration=20)]
        sr_vec, fr_vec = _simulate_success_and_funded(
            returns, 500_000, 20_000, "fixed", 0.05, 0.025,
            cash_flows=cfs,
        )
        sr_sc, fr_sc, _, _ = _simulate_scalar_with_cf(
            returns, 500_000, 20_000, cfs,
        )
        assert sr_vec == sr_sc
        assert fr_vec == fr_sc
