"""Tests for Bug 1 (zombie path resurrection), Bug 2 (growth_rate lost in CF split),
and Bug 3 (pension-aware success criteria)."""

import numpy as np
import pytest

from simulator.accumulation import _split_cashflows_at_year
from simulator.cashflow import CashFlowItem, build_cf_schedule
from simulator.config import (
    GUARDRAIL_CF_RATE_SEGMENTS,
    GUARDRAIL_CF_SCALE_SEGMENTS,
    build_nonuniform_grid,
)
from simulator.guardrail import (
    _find_portfolio_for_success,
    _find_withdrawal_for_success,
    build_cf_aware_table,
    build_success_rate_table,
    lookup_cf_aware_success_rate,
    run_historical_backtest,
)
from simulator.statistics import compute_effective_funded_ratio


# ===========================================================================
# Bug 1: Zombie path resurrection in binary search helpers
# ===========================================================================

class TestZombiePathFix:
    """Verify that _find_portfolio_for_success and _find_withdrawal_for_success
    permanently kill paths that hit 0, even when large positive cash flows
    could otherwise resurrect them."""

    def _make_scenarios_all_zero(self, num_sims: int, n_years: int) -> np.ndarray:
        """Zero-return scenarios — portfolio only changes via withdrawal/CF."""
        return np.zeros((num_sims, n_years))

    def test_find_portfolio_no_resurrection(self):
        """With 0 returns, wd=100, and a large CF of +200 starting year 3,
        a portfolio of 200 should fail at year 2 (200 - 100 - 100 = 0)
        and NOT be resurrected by the CF in year 3+."""
        num_sims = 100
        n_years = 5
        scenarios = self._make_scenarios_all_zero(num_sims, n_years)
        annual_withdrawal = 100.0

        # CF: +200 per year, starting year 3 (0-indexed: years 2,3,4)
        # Without fix: portfolio 200 -> year0: 100 -> year1: 0 -> year2: 0-100+200=100 (alive!)
        # With fix: portfolio 200 -> year0: 100 -> year1: 0 -> dead permanently
        cf = np.zeros(n_years)
        cf[2:] = 200.0  # large positive CF from year 3 onward
        cf_matrix = np.broadcast_to(cf, (num_sims, n_years)).copy()

        # With portfolio=200, all paths should fail at year 2
        # Required portfolio for 100% success should be > 500 (100*5)
        result = _find_portfolio_for_success(
            scenarios, annual_withdrawal, target_success=1.0,
            retirement_years=n_years, cf_matrix=cf_matrix,
            initial_guess=500.0, max_iter=30, tol=0.005,
        )
        # Without the CF, need 500 for 5 years of 100/yr withdrawals.
        # With CF starting year 3, need 300 for first 3 years (years 0,1,2),
        # then CF covers wd for years 3,4.
        # But: path must survive continuously. So need >= 300.
        # The key test: result should NOT be ~200 (the zombie-resurrected value)
        assert result >= 295, (
            f"Required portfolio {result:.0f} is too low — zombie resurrection likely"
        )

    def test_find_withdrawal_no_resurrection(self):
        """With 0 returns, portfolio=200, wd=200, CF +300 from year 1 (idx 1),
        zombie resurrection would allow survival at wd=200 despite year-0 failure.
        With fix, wd must be < 200 to survive year 0."""
        num_sims = 100
        n_years = 4
        scenarios = self._make_scenarios_all_zero(num_sims, n_years)
        initial_portfolio = 200.0

        # CF of +300 starting from year index 1 onward
        cf = np.zeros(n_years)
        cf[1:] = 300.0
        cf_matrix = np.broadcast_to(cf, (num_sims, n_years)).copy()

        result = _find_withdrawal_for_success(
            scenarios, initial_portfolio, target_success=1.0,
            retirement_years=n_years, cf_matrix=cf_matrix,
            initial_guess=100.0, max_iter=30, tol=0.005,
        )
        # Year 0: 200 - wd (no CF). Must be > 0 → wd < 200.
        # Year 1+: CF=300 dominates, so year 0 is the binding constraint.
        # Without fix (zombie): wd=200 → year0: 0, year1: 0-200+300=100 (alive!) → would allow wd≈200+
        # With fix: wd must be < 200.
        assert result < 200, (
            f"Safe withdrawal {result:.0f} exceeds pre-CF capacity — zombie fix may not be working"
        )

    def test_zombie_portfolio_rejected(self):
        """A portfolio that only survives via zombie resurrection should NOT
        achieve 100% success rate with the fix.

        Setup: portfolio=100, wd=200, CF=+300 from year 1.
        Without fix: year0: max(100-200,0)=0, year1: max(0-200+300,0)=100 → alive
        With fix: year0: 100-200=-100 → dead permanently → 0% success
        """
        num_sims = 50
        n_years = 3
        scenarios = self._make_scenarios_all_zero(num_sims, n_years)

        cf = np.zeros(n_years)
        cf[1:] = 300.0  # large CF from year 1
        cf_matrix = np.broadcast_to(cf, (num_sims, n_years)).copy()

        # Binary search for 100% success should need portfolio > 200
        # (to survive year 0 without CF)
        result = _find_portfolio_for_success(
            scenarios, annual_withdrawal=200.0, target_success=1.0,
            retirement_years=n_years, cf_matrix=cf_matrix,
            initial_guess=300.0, max_iter=30, tol=0.005,
        )
        # Must need at least 200 to survive year 0 (wd=200, no CF)
        assert result >= 195, (
            f"Required portfolio {result:.0f} < 200 — zombie resurrection likely"
        )


# ===========================================================================
# Bug 2: growth_rate lost during CF split in accumulation
# ===========================================================================

class TestCFSplitGrowthRate:
    """Verify that _split_cashflows_at_year preserves growth_rate."""

    def test_entirely_post_fire_preserves_growth_rate(self):
        """CF entirely after FIRE year should retain growth_rate."""
        cf = CashFlowItem(
            name="pension", amount=20000, start_year=10,
            duration=20, growth_rate=0.03,
        )
        pre, post = _split_cashflows_at_year([cf], fire_year=5)
        assert len(pre) == 0
        assert len(post) == 1
        assert post[0].growth_rate == 0.03
        assert post[0].start_year == 5  # 10 - 5
        assert post[0].duration == 20

    def test_entirely_pre_fire_preserves_growth_rate(self):
        """CF entirely before FIRE year should retain growth_rate."""
        cf = CashFlowItem(
            name="side_income", amount=5000, start_year=1,
            duration=3, growth_rate=0.05,
        )
        pre, post = _split_cashflows_at_year([cf], fire_year=5)
        assert len(pre) == 1
        assert len(post) == 0
        assert pre[0].growth_rate == 0.05

    def test_spanning_cf_preserves_growth_rate(self):
        """CF spanning FIRE boundary should retain growth_rate in both parts."""
        cf = CashFlowItem(
            name="rental", amount=1000, start_year=3,
            duration=8, growth_rate=0.02,
        )
        pre, post = _split_cashflows_at_year([cf], fire_year=5)

        assert len(pre) == 1
        assert len(post) == 1

        # Pre-fire part
        assert pre[0].growth_rate == 0.02
        assert pre[0].start_year == 3
        assert pre[0].duration == 3  # years 3, 4, 5
        assert pre[0].amount == 1000

        # Post-fire part
        assert post[0].growth_rate == 0.02
        assert post[0].start_year == 1
        assert post[0].duration == 5  # years 6-10
        # Amount should be grown: 1000 * 1.02^3 (3 years of pre-fire growth)
        expected_amount = 1000 * (1.02 ** 3)
        assert abs(post[0].amount - expected_amount) < 0.01, (
            f"Post-fire amount {post[0].amount:.2f} != expected {expected_amount:.2f}"
        )

    def test_spanning_cf_schedule_continuity(self):
        """The combined pre+post CF schedule should produce a continuous
        growth series, equivalent to a single unsplit CF."""
        cf = CashFlowItem(
            name="income", amount=1000, start_year=1,
            duration=10, growth_rate=0.05,
        )
        fire_year = 4

        # Unsplit schedule (reference)
        unsplit_schedule = build_cf_schedule([cf], 10)

        # Split and build separate schedules
        pre, post = _split_cashflows_at_year([cf], fire_year=fire_year)

        pre_schedule = build_cf_schedule(pre, fire_year)  # years 1-4
        post_schedule = build_cf_schedule(post, 10 - fire_year)  # years 5-10

        # Combine
        combined = np.concatenate([pre_schedule, post_schedule])

        np.testing.assert_allclose(
            combined, unsplit_schedule,
            rtol=1e-10,
            err_msg="Split CF schedule doesn't match unsplit CF schedule",
        )

    def test_zero_growth_rate_unchanged(self):
        """CF with growth_rate=0 should work identically before and after fix."""
        cf = CashFlowItem(
            name="fixed_pension", amount=2000, start_year=3,
            duration=6, growth_rate=0.0,
        )
        pre, post = _split_cashflows_at_year([cf], fire_year=5)

        assert pre[0].growth_rate == 0.0
        assert post[0].growth_rate == 0.0
        # With 0 growth, amount should be unchanged
        assert post[0].amount == 2000.0

    def test_multiple_cfs_mixed(self):
        """Multiple CFs with different growth rates should all be preserved."""
        cfs = [
            CashFlowItem(name="a", amount=100, start_year=1, duration=3, growth_rate=0.01),
            CashFlowItem(name="b", amount=200, start_year=4, duration=10, growth_rate=0.03),
            CashFlowItem(name="c", amount=-500, start_year=8, duration=5, growth_rate=0.0),
        ]
        pre, post = _split_cashflows_at_year(cfs, fire_year=5)

        # a: entirely pre-fire (years 1-3)
        a_items = [c for c in pre if c.name == "a"]
        assert len(a_items) == 1
        assert a_items[0].growth_rate == 0.01

        # b: spans fire_year (years 4-13), pre: years 4-5, post: years 6-13
        b_pre = [c for c in pre if c.name == "b"]
        b_post = [c for c in post if c.name == "b"]
        assert len(b_pre) == 1
        assert len(b_post) == 1
        assert b_pre[0].growth_rate == 0.03
        assert b_post[0].growth_rate == 0.03
        # Post amount: 200 * 1.03^2 (2 years of pre-fire growth)
        expected = 200 * (1.03 ** 2)
        assert abs(b_post[0].amount - expected) < 0.01

        # c: entirely post-fire (years 8-12)
        c_items = [c for c in post if c.name == "c"]
        assert len(c_items) == 1
        assert c_items[0].growth_rate == 0.0
        assert c_items[0].amount == -500


# ===========================================================================
# Bug 3: Historical backtest zombie resurrection (guardrail path)
# ===========================================================================

class TestHistoricalBacktestZombie:
    """Verify that run_historical_backtest guardrail path doesn't resurrect
    portfolios that have hit 0 via large positive cash flows."""

    @pytest.fixture
    def simple_table(self):
        """Build a simple success rate table from zero-return scenarios."""
        scenarios = np.zeros((100, 10))
        rate_grid, table = build_success_rate_table(scenarios)
        return table, rate_grid

    def test_guardrail_no_zombie_with_pension(self, simple_table):
        """Portfolio hits 0 in year 2, large pension from year 3 should NOT
        resurrect it. Verify g_portfolio stays 0 after depletion."""
        table, rate_grid = simple_table
        n_years = 6
        real_returns = np.zeros(n_years)  # 0% returns
        initial_portfolio = 100.0
        annual_withdrawal = 60.0  # Depletes by year 2: 100-60=40, 40-60<0

        # Pension of 200/year starting year 3 (0-indexed: years 2,3,4,5)
        pension_cf = CashFlowItem(
            name="pension", amount=200, start_year=3,
            duration=4, inflation_adjusted=True,
        )

        result = run_historical_backtest(
            real_returns=real_returns,
            initial_portfolio=initial_portfolio,
            annual_withdrawal=annual_withdrawal,
            target_success=0.9,
            upper_guardrail=0.99,
            lower_guardrail=0.7,
            adjustment_pct=0.1,
            retirement_years=n_years,
            min_remaining_years=2,
            baseline_rate=0.04,
            table=table,
            rate_grid=rate_grid,
            cash_flows=[pension_cf],
        )

        g_port = result["g_portfolio"]
        # Portfolio should hit 0 and STAY at 0
        # Year 0: 100
        # Year 1: 100 - wd (guardrail may adjust, but wd ≈ 60)
        # Year 2: ~40 - wd → 0 or below
        # Years 3-6: should stay at 0 (no zombie resurrection)

        # Find first zero
        first_zero_idx = None
        for i in range(1, len(g_port)):
            if g_port[i] <= 0:
                first_zero_idx = i
                break

        assert first_zero_idx is not None, "Portfolio should have hit 0"

        # All values after first zero must be 0 (no resurrection)
        for i in range(first_zero_idx, len(g_port)):
            assert g_port[i] == 0.0, (
                f"g_portfolio[{i}] = {g_port[i]:.2f} — zombie resurrection detected! "
                f"Portfolio should stay at 0 after depletion at year {first_zero_idx}"
            )

        # Withdrawals after depletion should also be 0
        g_wd = result["g_withdrawals"]
        for i in range(first_zero_idx, len(g_wd)):
            assert g_wd[i] == 0.0, (
                f"g_withdrawals[{i}] = {g_wd[i]:.2f} — should be 0 after depletion"
            )

    def test_baseline_no_zombie_with_pension(self, simple_table):
        """Baseline path should also not resurrect portfolio."""
        table, rate_grid = simple_table
        n_years = 6
        real_returns = np.zeros(n_years)
        initial_portfolio = 100.0
        annual_withdrawal = 60.0

        pension_cf = CashFlowItem(
            name="pension", amount=200, start_year=3,
            duration=4, inflation_adjusted=True,
        )

        result = run_historical_backtest(
            real_returns=real_returns,
            initial_portfolio=initial_portfolio,
            annual_withdrawal=annual_withdrawal,
            target_success=0.9,
            upper_guardrail=0.99,
            lower_guardrail=0.7,
            adjustment_pct=0.1,
            retirement_years=n_years,
            min_remaining_years=2,
            baseline_rate=0.06,  # 6% of 100 = 6/year, depletes fast
            table=table,
            rate_grid=rate_grid,
            cash_flows=[pension_cf],
        )

        b_port = result["b_portfolio"]
        first_zero_idx = None
        for i in range(1, len(b_port)):
            if b_port[i] <= 0:
                first_zero_idx = i
                break

        if first_zero_idx is not None:
            for i in range(first_zero_idx, len(b_port)):
                assert b_port[i] == 0.0, (
                    f"b_portfolio[{i}] = {b_port[i]:.2f} — baseline zombie detected"
                )


# ===========================================================================
# Bug 3b: Pension-aware success criteria
# ===========================================================================

class TestEffectiveFundedRatio:
    """Verify that compute_effective_funded_ratio uses both consumption floor
    and asset depletion checks (no supplemental_income double-counting)."""

    def test_wd_above_floor_portfolio_positive_is_success(self):
        """All withdrawals above floor and portfolio positive → success."""
        n_sims = 10
        n_years = 40
        initial_wd = 40000.0

        withdrawals = np.full((n_sims, n_years), 30000.0)
        trajectories = np.ones((n_sims, n_years + 1)) * 500000.0

        fr, sr = compute_effective_funded_ratio(
            withdrawals, initial_wd, n_years,
            consumption_floor=0.50,
            trajectories=trajectories,
        )

        assert sr == 1.0
        assert fr == 1.0

    def test_wd_below_floor_is_failure(self):
        """Withdrawals drop below consumption floor → failure."""
        n_sims = 10
        n_years = 40
        initial_wd = 40000.0
        # floor = 20k

        withdrawals = np.full((n_sims, n_years), 30000.0)
        withdrawals[:, 20:] = 15000.0  # below 20k floor

        trajectories = np.ones((n_sims, n_years + 1)) * 500000.0

        fr, sr = compute_effective_funded_ratio(
            withdrawals, initial_wd, n_years,
            consumption_floor=0.50,
            trajectories=trajectories,
        )

        assert sr == 0.0
        expected_fr = 21.0 / 40.0  # below floor at year 20 → funded through year 21
        assert abs(fr - expected_fr) < 0.01

    def test_asset_depletion_overrides_good_withdrawals(self):
        """Even if wd > floor, asset depletion still causes failure."""
        n_sims = 10
        n_years = 10
        initial_wd = 100.0

        withdrawals = np.full((n_sims, n_years), 100.0)  # all above floor=50

        trajectories = np.ones((n_sims, n_years + 1)) * 10000.0
        for t in range(5, n_years + 1):
            trajectories[:, t] = 0.0

        fr, sr = compute_effective_funded_ratio(
            withdrawals, initial_wd, n_years,
            consumption_floor=0.50,
            trajectories=trajectories,
        )

        assert sr == 0.0
        # trajectories[:, 5]=0 → depleted index 4 in [:, 1:] + 1 → 5/10=0.5
        assert abs(fr - 0.5) < 0.01

    def test_portfolio_zero_last_year_wd_positive_is_success(self):
        """Portfolio=0 at exactly the last year → fully funded → success."""
        n_sims = 10
        n_years = 40
        initial_wd = 40000.0

        withdrawals = np.full((n_sims, n_years), 20000.0)  # above floor=20k

        trajectories = np.ones((n_sims, n_years + 1)) * 100000.0
        trajectories[:, -1] = 0.0  # portfolio=0 at the end

        fr, sr = compute_effective_funded_ratio(
            withdrawals, initial_wd, n_years,
            consumption_floor=0.50,
            trajectories=trajectories,
        )

        # Asset depleted at exactly the last year → funded for all retirement years
        assert sr == 1.0
        # depletion index 39 in [:, 1:] + 1 → 40/40 = 1.0
        assert abs(fr - 1.0) < 0.01

    def test_portfolio_zero_one_year_early_is_failure(self):
        """Portfolio=0 one year before end, wd=0 → both checks fail."""
        n_sims = 10
        n_years = 40
        initial_wd = 40000.0

        withdrawals = np.full((n_sims, n_years), 30000.0)
        withdrawals[:, 39] = 0.0

        trajectories = np.ones((n_sims, n_years + 1)) * 200000.0
        trajectories[:, 39] = 0.0
        trajectories[:, 40] = 0.0

        fr, sr = compute_effective_funded_ratio(
            withdrawals, initial_wd, n_years,
            consumption_floor=0.50,
            trajectories=trajectories,
        )

        assert sr == 0.0

    def test_no_trajectories_uses_consumption_floor_only(self):
        """When trajectories=None, only consumption floor is checked."""
        n_sims = 5
        n_years = 20
        initial_wd = 40000.0

        withdrawals = np.full((n_sims, n_years), 30000.0)  # above floor=20k

        fr, sr = compute_effective_funded_ratio(
            withdrawals, initial_wd, n_years,
            consumption_floor=0.50,
            trajectories=None,
        )

        assert sr == 1.0
        assert fr == 1.0


# ===========================================================================
# Extended grid coverage tests
# ===========================================================================

class TestExtendedGrid:
    """Verify the non-uniform extended grids cover the required ranges
    and produce accurate 3D table lookups in the extended region."""

    def test_grid_sizes(self):
        """Grid point counts match expected values."""
        rg = build_nonuniform_grid(GUARDRAIL_CF_RATE_SEGMENTS)
        csg = build_nonuniform_grid(GUARDRAIL_CF_SCALE_SEGMENTS)
        assert len(rg) == 170, f"Expected 170 3D rate points, got {len(rg)}"
        assert rg[-1] == 3.0
        assert len(csg) == 15, f"Expected 15 cf_scale points, got {len(csg)}"
        assert csg[-1] == 5.0

    def test_3d_table_high_cf_scale_rescues_high_rate(self):
        """At rate=2.0 with cf_scale=3.0 (pension >> withdrawal),
        success should be high — pension rescues the portfolio."""
        scenarios = np.random.default_rng(42).normal(0.07, 0.15, (2000, 30))
        cf = np.zeros(30)
        cf[:] = 50000.0  # pension every year
        result = build_cf_aware_table(scenarios, cf, max_sims=2000)
        assert result is not None
        rg, csg, tbl, cf_ref, lcy = result

        # rate=2.0, cf_scale=3.0: pension dominates → high success
        s = lookup_cf_aware_success_rate(tbl, rg, csg, 2.0, 3.0, 0)
        assert s > 0.80, f"Expected success > 80% at rate=2.0/cf_scale=3.0, got {s:.1%}"

        # rate=2.0, cf_scale=0: no pension → guaranteed ruin
        s0 = lookup_cf_aware_success_rate(tbl, rg, csg, 2.0, 0.0, 0)
        assert s0 < 0.05, f"Expected success < 5% at rate=2.0/cf_scale=0, got {s0:.1%}"

    def test_3d_table_transition_zone(self):
        """The transition from 0% to 100% success occurs along
        cf_scale ≈ rate - 1.0. Verify both sides of the boundary."""
        scenarios = np.random.default_rng(42).normal(0.07, 0.15, (2000, 30))
        cf = np.zeros(30)
        cf[:] = 50000.0
        result = build_cf_aware_table(scenarios, cf, max_sims=2000)
        rg, csg, tbl, cf_ref, lcy = result

        # Well above boundary: rate=1.5, cf_scale=4.0 → safe
        s_safe = lookup_cf_aware_success_rate(tbl, rg, csg, 1.5, 4.0, 0)
        assert s_safe > 0.95

        # Well below boundary: rate=2.5, cf_scale=0.5 → ruin
        s_ruin = lookup_cf_aware_success_rate(tbl, rg, csg, 2.5, 0.5, 0)
        assert s_ruin < 0.05

    def test_no_fallback_at_rate_1_5(self):
        """rate=1.5 and cf_scale=1.0 previously triggered 2D fallback.
        With extended grid, 3D lookup should work directly."""
        rg = build_nonuniform_grid(GUARDRAIL_CF_RATE_SEGMENTS)
        csg = build_nonuniform_grid(GUARDRAIL_CF_SCALE_SEGMENTS)
        # rate=1.5 is within [0, 3.0], cf_scale=1.0 is within [0, 5.0]
        assert 1.5 <= rg[-1], "rate=1.5 should be within 3D grid"
        assert 1.0 <= csg[-1], "cf_scale=1.0 should be within 3D grid"
