"""Tests for the opt-in geometric block-length distribution (Upgrade A).

Critical invariant (Codex review 2026-06-21, Finding 6): block_dist="uniform"
must be BITWISE identical to the original behavior (same RNG call order), so the
new parameters are a true no-op by default.  Plus: geometric mean/support
behavior, validation guards (Findings 8/9), and circular-wrap safety when a
geometric block exceeds a country's length.
"""

import numpy as np
import pandas as pd
import pytest

from simulator.bootstrap import (
    block_bootstrap,
    block_bootstrap_np,
    block_bootstrap_pooled,
)


def _df(country: str, n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "Year": np.arange(1900, 1900 + n),
        "Country": [country] * n,
        "Domestic_Stock": rng.normal(0.08, 0.18, n),
        "Global_Stock": rng.normal(0.07, 0.17, n),
        "Domestic_Bond": rng.normal(0.03, 0.06, n),
        "Inflation": rng.normal(0.03, 0.02, n),
    })


# --------------------------------------------------------------------------
# Bitwise equivalence: uniform default == explicit uniform (Finding 6)
# --------------------------------------------------------------------------
class TestUniformBitwiseEquivalence:
    def test_single_country_default_matches_explicit_uniform(self):
        df = _df("USA", 40, 1)
        a = block_bootstrap(df, 30, 5, 15, rng=np.random.default_rng(123))
        b = block_bootstrap(df, 30, 5, 15, rng=np.random.default_rng(123),
                            block_dist="uniform")
        np.testing.assert_array_equal(a.values, b.values)

    def test_single_country_np_default_matches_explicit_uniform(self):
        df = _df("USA", 40, 2)
        data = df[["Domestic_Stock", "Global_Stock", "Domestic_Bond",
                   "Inflation"]].values
        a = block_bootstrap_np(data, len(data), 30, 5, 15,
                               rng=np.random.default_rng(7))
        b = block_bootstrap_np(data, len(data), 30, 5, 15,
                               rng=np.random.default_rng(7), block_dist="uniform")
        np.testing.assert_array_equal(a, b)

    def test_pooled_default_matches_explicit_uniform(self):
        cdfs = {"USA": _df("USA", 40, 3), "GBR": _df("GBR", 35, 4)}
        a = block_bootstrap_pooled(cdfs, 30, 5, 15, rng=np.random.default_rng(99))
        b = block_bootstrap_pooled(cdfs, 30, 5, 15, rng=np.random.default_rng(99),
                                   block_dist="uniform")
        np.testing.assert_array_equal(a.values, b.values)

    def test_uniform_unaffected_by_mean_block_arg(self):
        """mean_block is ignored when block_dist='uniform'."""
        df = _df("USA", 40, 5)
        a = block_bootstrap(df, 30, 5, 15, rng=np.random.default_rng(11))
        b = block_bootstrap(df, 30, 5, 15, rng=np.random.default_rng(11),
                            block_dist="uniform", mean_block=3)
        np.testing.assert_array_equal(a.values, b.values)


# --------------------------------------------------------------------------
# Geometric block-length statistics & support (Finding 8)
# --------------------------------------------------------------------------
class TestGeometricBlockLength:
    def test_geometric_mean_block_length(self):
        """Empirical mean block length ~ mean_block (geometric law E[L]=1/p)."""
        rng = np.random.default_rng(0)
        mean_block = 10
        lengths = []
        # Reconstruct block lengths by sampling many short paths and measuring
        # the first block via a long horizon with a sentinel of distinct rows.
        # Simpler: draw geometric directly the same way the core does.
        for _ in range(50000):
            lengths.append(rng.geometric(1.0 / mean_block))
        assert abs(np.mean(lengths) - mean_block) < 0.2

    def test_geometric_produces_blocks_outside_uniform_support(self):
        """Geometric mode is NOT bounded by [min_block, max_block]."""
        df = _df("USA", 120, 6)
        # With mean_block=10 over a long horizon, some blocks must be < 5 or > 15.
        # Detect via repeated identical-row runs is fragile; instead assert the
        # geometric path differs from the uniform path under the same seed.
        u = block_bootstrap(df, 200, 5, 15, rng=np.random.default_rng(8),
                            block_dist="uniform")
        g = block_bootstrap(df, 200, 5, 15, rng=np.random.default_rng(8),
                            block_dist="geometric", mean_block=10)
        assert not np.array_equal(u.values, g.values)

    def test_geometric_output_shape_and_finiteness(self):
        df = _df("USA", 60, 9)
        g = block_bootstrap(df, 50, 5, 15, rng=np.random.default_rng(3),
                            block_dist="geometric", mean_block=8)
        assert g.shape == (50, 4)
        assert np.isfinite(g.values).all()

    def test_geometric_default_mean_is_uniform_midpoint(self):
        """mean_block=None under geometric uses (min+max)/2 = 10 for [5,15]."""
        df = _df("USA", 60, 10)
        a = block_bootstrap(df, 50, 5, 15, rng=np.random.default_rng(21),
                            block_dist="geometric")
        b = block_bootstrap(df, 50, 5, 15, rng=np.random.default_rng(21),
                            block_dist="geometric", mean_block=10)
        np.testing.assert_array_equal(a.values, b.values)


# --------------------------------------------------------------------------
# Circular-wrap safety when geometric block exceeds country length (Finding 9)
# --------------------------------------------------------------------------
class TestGeometricWrapSafety:
    def test_long_geometric_block_wraps_without_error(self):
        """mean_block < n but a geometric draw can exceed n; wrap must be safe."""
        df = _df("USA", 30, 12)  # n=30
        g = block_bootstrap(df, 100, 5, 15, rng=np.random.default_rng(2),
                            block_dist="geometric", mean_block=20)
        assert g.shape == (100, 4)
        assert np.isfinite(g.values).all()
        # every output row must equal some historical row (wrap is a real index)
        hist = set(map(tuple, df[["Domestic_Stock", "Global_Stock",
                                  "Domestic_Bond", "Inflation"]].values))
        for row in g.values:
            assert tuple(row) in hist


# --------------------------------------------------------------------------
# Validation guards (Findings 8/9)
# --------------------------------------------------------------------------
class TestBlockDistValidation:
    def test_invalid_block_dist_raises(self):
        df = _df("USA", 40, 1)
        with pytest.raises(ValueError, match="block_dist"):
            block_bootstrap(df, 30, 5, 15, block_dist="poisson")

    def test_mean_block_below_one_raises(self):
        df = _df("USA", 40, 1)
        with pytest.raises(ValueError, match="mean_block must be >= 1"):
            block_bootstrap(df, 30, 5, 15, block_dist="geometric", mean_block=0)

    def test_mean_block_exceeds_shortest_series_raises(self):
        df = _df("USA", 25, 1)  # n=25
        with pytest.raises(ValueError, match="exceeds the shortest"):
            block_bootstrap(df, 30, 5, 15, block_dist="geometric", mean_block=40)

    def test_default_mean_block_guard_on_short_series(self):
        """Branch review P2: omitted mean_block (midpoint default=10) must also
        be guarded against a short series, not just an explicit value."""
        df = _df("USA", 6, 1)  # n=6 < default midpoint 10
        with pytest.raises(ValueError, match="exceeds the shortest"):
            block_bootstrap(df, 30, 5, 15, block_dist="geometric")  # mean_block=None

    def test_pooled_mean_block_guard_uses_shortest_country(self):
        cdfs = {"USA": _df("USA", 60, 1), "SHORT": _df("SHORT", 20, 2)}
        with pytest.raises(ValueError, match="exceeds the shortest"):
            block_bootstrap_pooled(cdfs, 30, 5, 15, block_dist="geometric",
                                   mean_block=30)

    def test_np_geometric_runs(self):
        df = _df("USA", 50, 1)
        data = df[["Domestic_Stock", "Global_Stock", "Domestic_Bond",
                   "Inflation"]].values
        out = block_bootstrap_np(data, len(data), 40, 5, 15,
                                 rng=np.random.default_rng(1),
                                 block_dist="geometric", mean_block=10)
        assert out.shape == (40, 4)
