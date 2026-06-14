"""Tests for asymmetric guardrail adjustment (Income-Lab-style 100%-up / X%-down).

The upper guardrail (portfolio doing well, current_success > target) and the
lower guardrail (portfolio struggling, current_success < target) may apply
different fractions of the gap toward target. Backward compatibility: when the
directional fractions are omitted (None), behavior must equal the symmetric
adjustment_pct.
"""

import numpy as np
import pytest

from simulator.guardrail import (
    apply_guardrail_adjustment,
    build_success_rate_table,
    run_guardrail_simulation,
    run_historical_backtest,
)


@pytest.fixture
def simple_table():
    scenarios = np.zeros((400, 10))
    rate_grid, table = build_success_rate_table(scenarios)
    return table, rate_grid


REMAINING = 10
TARGET = 0.85
VALUE = 1000.0


def _target_wd(table, rate_grid):
    """Full-move (100%) target withdrawal from wd=0 in amount mode."""
    return apply_guardrail_adjustment(
        0.0, VALUE, 0.99, TARGET, 1.0, "amount", REMAINING, table, rate_grid,
    )


class TestAsymmetricAdjustment:
    def test_backward_compat_none_equals_symmetric(self, simple_table):
        """Omitting directional fractions == passing the symmetric adjustment_pct."""
        table, rate_grid = simple_table
        base = apply_guardrail_adjustment(
            0.0, VALUE, 0.99, TARGET, 0.5, "amount", REMAINING, table, rate_grid,
        )
        explicit_none = apply_guardrail_adjustment(
            0.0, VALUE, 0.99, TARGET, 0.5, "amount", REMAINING, table, rate_grid,
            upper_adjustment_pct=None, lower_adjustment_pct=None,
        )
        explicit_sym = apply_guardrail_adjustment(
            0.0, VALUE, 0.99, TARGET, 0.5, "amount", REMAINING, table, rate_grid,
            upper_adjustment_pct=0.5, lower_adjustment_pct=0.5,
        )
        assert base == pytest.approx(explicit_none)
        assert base == pytest.approx(explicit_sym)

    def test_upper_breach_uses_upper_fraction(self, simple_table):
        """current_success > target → uses upper fraction, ignoring adjustment_pct."""
        table, rate_grid = simple_table
        twd = _target_wd(table, rate_grid)
        assert twd > 0
        # wd below target; upper=1.0 should move fully to target_wd, ignoring the
        # positional adjustment_pct of 0.10.
        up = apply_guardrail_adjustment(
            0.0, VALUE, 0.99, TARGET, 0.10, "amount", REMAINING, table, rate_grid,
            upper_adjustment_pct=1.0, lower_adjustment_pct=0.10,
        )
        assert up == pytest.approx(twd)

    def test_lower_breach_uses_lower_fraction(self, simple_table):
        """current_success < target → uses lower fraction, ignoring adjustment_pct."""
        table, rate_grid = simple_table
        twd = _target_wd(table, rate_grid)
        wd_high = twd * 3.0
        # current below target; lower=0.10 should move only 10% of the gap down,
        # ignoring the positional adjustment_pct of 1.0.
        lo = apply_guardrail_adjustment(
            wd_high, VALUE, 0.5, TARGET, 1.0, "amount", REMAINING, table, rate_grid,
            upper_adjustment_pct=1.0, lower_adjustment_pct=0.10,
        )
        assert lo == pytest.approx(wd_high + 0.10 * (twd - wd_high))
        assert lo < wd_high  # a cut, but a gentle one

    def test_success_rate_mode_backward_compat(self, simple_table):
        """None directional fractions == symmetric in success_rate mode too."""
        table, rate_grid = simple_table
        base = apply_guardrail_adjustment(
            0.0, VALUE, 0.99, TARGET, 0.5, "success_rate", REMAINING, table, rate_grid,
        )
        none = apply_guardrail_adjustment(
            0.0, VALUE, 0.99, TARGET, 0.5, "success_rate", REMAINING, table, rate_grid,
            upper_adjustment_pct=None, lower_adjustment_pct=None,
        )
        sym = apply_guardrail_adjustment(
            0.0, VALUE, 0.99, TARGET, 0.5, "success_rate", REMAINING, table, rate_grid,
            upper_adjustment_pct=0.5, lower_adjustment_pct=0.5,
        )
        assert base == pytest.approx(none)
        assert base == pytest.approx(sym)

    def test_asymmetry_is_directional(self, simple_table):
        """Same gap magnitude yields a larger up-move than down-move when 1.0/0.1."""
        table, rate_grid = simple_table
        twd = _target_wd(table, rate_grid)
        up = apply_guardrail_adjustment(
            0.0, VALUE, 0.99, TARGET, 0.5, "amount", REMAINING, table, rate_grid,
            upper_adjustment_pct=1.0, lower_adjustment_pct=0.10,
        )
        wd_high = twd * 2.0
        lo = apply_guardrail_adjustment(
            wd_high, VALUE, 0.5, TARGET, 0.5, "amount", REMAINING, table, rate_grid,
            upper_adjustment_pct=1.0, lower_adjustment_pct=0.10,
        )
        assert up == pytest.approx(twd)              # full up-move
        down_gap_closed = (wd_high - lo) / (wd_high - twd)
        assert down_gap_closed == pytest.approx(0.10)  # only 10% down-move


class TestRunGuardrailThreading:
    """Integration: the directional fractions must thread through the run loop."""

    @pytest.fixture
    def scenarios(self):
        rng = np.random.default_rng(7)
        # Varied returns so guardrails actually trigger across paths.
        return rng.normal(0.05, 0.15, (200, 30))

    def _run(self, scenarios, table, rate_grid, **extra):
        return run_guardrail_simulation(
            scenarios=scenarios,
            target_success=0.85,
            upper_guardrail=0.99,
            lower_guardrail=0.60,
            adjustment_pct=0.3,
            retirement_years=30,
            min_remaining_years=5,
            table=table,
            rate_grid=rate_grid,
            adjustment_mode="amount",
            initial_portfolio=1_000_000.0,
            **extra,
        )

    def test_explicit_symmetric_matches_default(self, scenarios):
        rate_grid, table = build_success_rate_table(np.zeros((400, 30)))
        _, _, traj_a, wd_a, _ = self._run(scenarios, table, rate_grid)
        _, _, traj_b, wd_b, _ = self._run(
            scenarios, table, rate_grid,
            upper_adjustment_pct=0.3, lower_adjustment_pct=0.3,
        )
        np.testing.assert_allclose(traj_a, traj_b)
        np.testing.assert_allclose(wd_a, wd_b)

    def test_asymmetric_changes_behavior(self, scenarios):
        rate_grid, table = build_success_rate_table(np.zeros((400, 30)))
        _, _, _, wd_sym, _ = self._run(scenarios, table, rate_grid)
        _, _, _, wd_asym, _ = self._run(
            scenarios, table, rate_grid,
            upper_adjustment_pct=1.0, lower_adjustment_pct=0.05,
        )
        # Asymmetric (full-up / gentle-down) must diverge from symmetric somewhere.
        assert not np.allclose(wd_sym, wd_asym)

    def test_historical_backtest_threading_equivalence(self):
        """run_historical_backtest: explicit symmetric == default (locks 2nd loop)."""
        rate_grid, table = build_success_rate_table(np.zeros((400, 30)))
        rng = np.random.default_rng(11)
        real_returns = rng.normal(0.05, 0.15, 30)
        common = dict(
            real_returns=real_returns, initial_portfolio=1_000_000.0,
            annual_withdrawal=40_000.0, target_success=0.85,
            upper_guardrail=0.99, lower_guardrail=0.60, adjustment_pct=0.3,
            retirement_years=30, min_remaining_years=5, baseline_rate=0.033,
            table=table, rate_grid=rate_grid, adjustment_mode="amount",
        )
        a = run_historical_backtest(**common)
        b = run_historical_backtest(**common, upper_adjustment_pct=0.3, lower_adjustment_pct=0.3)
        np.testing.assert_allclose(a["g_portfolio"], b["g_portfolio"])
        np.testing.assert_allclose(a["g_withdrawals"], b["g_withdrawals"])
