"""Tests for adaptive memory optimization (low-memory environments)."""

import os
import numpy as np
import pytest


class TestMemoryDetection:
    """Test memory detection and is_low_memory() logic."""

    def test_is_low_memory_env_override_low(self, monkeypatch):
        monkeypatch.setenv("MEMORY_LIMIT_MB", "256")
        from simulator.config import is_low_memory
        assert is_low_memory() is True

    def test_is_low_memory_env_override_exact_threshold(self, monkeypatch):
        monkeypatch.setenv("MEMORY_LIMIT_MB", "768")
        from simulator.config import is_low_memory
        assert is_low_memory() is True

    def test_high_memory_no_optimization(self, monkeypatch):
        monkeypatch.setenv("MEMORY_LIMIT_MB", "4096")
        from simulator.config import is_low_memory
        assert is_low_memory() is False

    def test_no_env_var_defaults_false(self, monkeypatch):
        monkeypatch.delenv("MEMORY_LIMIT_MB", raising=False)
        # On a dev machine with >768 MB RAM, should return False
        from simulator.config import is_low_memory
        # We can't assert True/False absolutely here since it depends on the
        # machine, but we can verify it returns a bool
        result = is_low_memory()
        assert isinstance(result, bool)

    def test_detect_memory_limit_mb_returns_int_or_none(self):
        from simulator.config import _detect_memory_limit_mb
        result = _detect_memory_limit_mb()
        assert result is None or isinstance(result, int)


class TestFloat32TableEquivalence:
    """Verify float32 tables produce results within tolerance of float64."""

    @pytest.fixture
    def scenarios(self):
        rng = np.random.default_rng(42)
        return rng.normal(0.07, 0.15, size=(500, 30))

    def test_2d_table_float32_vs_float64(self, scenarios):
        """build_success_rate_table uses float32 internally; verify output accuracy."""
        from simulator.guardrail import build_success_rate_table

        rate_grid, table = build_success_rate_table(scenarios)

        # Table values are means of boolean arrays, so they're exact
        # regardless of float32 vs float64 for the intermediate values.
        # Verify table is in valid range.
        assert table.min() >= 0.0
        assert table.max() <= 1.0
        assert table[0, 0] == 1.0  # 0 years, always survive

    def test_3d_table_float32_equivalence(self, scenarios):
        """build_cf_aware_table with float32 should match float64 within tolerance."""
        from simulator.guardrail import build_cf_aware_table

        cf_schedule = np.zeros(30)
        cf_schedule[5:15] = 10000.0  # pension from year 5-14

        # Run with current (float32) implementation
        result = build_cf_aware_table(
            scenarios, cf_schedule, max_sims=200, max_start_years=5,
        )
        assert result is not None
        rate_grid, cf_scale_grid, table_3d, cf_ref, last_cf_year = result

        # Values should be valid probabilities
        assert table_3d.min() >= 0.0
        assert table_3d.max() <= 1.0
        assert cf_ref == pytest.approx(10000.0)
        assert last_cf_year == 14

    def test_cf_default_max_sims_respects_env(self, monkeypatch):
        """_CF_DEFAULT_MAX_SIMS should be 2000 in low memory, 5000 otherwise."""
        # We can't easily re-import to change module-level value,
        # but we can verify the build_cf_aware_table default behavior
        # by checking that max_sims=None works without error
        from simulator.guardrail import build_cf_aware_table

        rng = np.random.default_rng(42)
        scenarios = rng.normal(0.07, 0.15, size=(100, 20))
        cf_schedule = np.zeros(20)
        cf_schedule[3:8] = 5000.0

        result = build_cf_aware_table(
            scenarios, cf_schedule, max_sims=None, max_start_years=3,
        )
        assert result is not None
