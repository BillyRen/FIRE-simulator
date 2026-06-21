"""Block Bootstrap 循环采样模块。

Design note — Circular wrap-around (Politis-Romano 1992 Circular Block Bootstrap):
When a sampled block extends past the end of a country's historical series,
indices wrap around to the beginning (modular arithmetic).  This is the standard
Circular Block Bootstrap: treating the series as circular removes the
block-boundary EDGE BIAS that plain truncation introduces (truncation
under-samples the first/last observations).  The cost is one artificial seam per
wrap (e.g. 2025 -> 1872 within the same country).

Scope of the "benign seam" claim (Codex review 2026-06-21, Finding 2):
The seam is benign for *return-like* columns (Domestic_Stock, Global_Stock,
Domestic_Bond, Inflation rate), which are approximately stationary, so the wrap
seam is no worse than any other block boundary.  It is LESS clean for *level*
columns — Long_Rate (a yield level) and the housing level series — which are
persistent/non-stationary; a wrap there joins two distant rate regimes.  The
default sampling uses only return-like columns, so this is not a product issue,
but callers sampling HOUSING_COLS / Long_Rate should be aware.

We deliberately do NOT switch to truncation (reintroduces edge bias) or to
ACO-style cross-country continuation (double seam + bias toward a new country's
earliest rows); see the plan doc §3.D for the adjudication.

Block-length distribution (Upgrade A, opt-in, default unchanged):
``block_dist="uniform"`` (default) draws block length ~ U[min_block, max_block]
exactly as before.  ``block_dist="geometric"`` draws length ~ Geometric(p) with
mean ``mean_block`` (the stationary bootstrap of Politis-Romano 1994); the
geometric law gives the resampled series a *stationary Markov renewal* structure
(a property of the bootstrap process, not a claim about the data).  Geometric
mode preserves only the MEAN block length, not the [min_block, max_block]
support — many blocks fall outside that range by design.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


RETURN_COLS = ["Domestic_Stock", "Global_Stock", "Domestic_Bond", "Inflation"]
HOUSING_COLS = ["Housing_CapGain", "Rent_Growth", "Long_Rate"]

# Column indices for RETURN_COLS (used by numpy-returning variants)
IDX_DS = 0   # Domestic_Stock
IDX_GS = 1   # Global_Stock
IDX_DB = 2   # Domestic_Bond
IDX_INF = 3  # Inflation


def _block_bootstrap_core(
    data: np.ndarray,
    n: int,
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator,
    n_cols: int,
    block_dist: str = "uniform",
    geom_p: float | None = None,
) -> np.ndarray:
    """Core block bootstrap loop operating on numpy arrays.

    block_dist="uniform" preserves the exact RNG call order of the original
    implementation (draw length, then start) so seeded output is bitwise
    identical.  "geometric" swaps only the length draw for rng.geometric(geom_p).
    """
    output = np.empty((retirement_years, n_cols), dtype=np.float64)
    pos = 0

    while pos < retirement_years:
        if block_dist == "geometric":
            block_len = rng.geometric(geom_p)
        else:
            block_len = rng.integers(min_block, max_block + 1)
        block_size = min(block_len, retirement_years - pos)
        start = rng.integers(0, n)
        indices = np.arange(start, start + block_size) % n
        output[pos:pos + block_size] = data[indices]
        pos += block_size

    return output


def _resolve_geom_p(
    block_dist: str, min_block: int, max_block: int, mean_block: int | None,
) -> float | None:
    """Compute the geometric success prob p = 1/mean_block (None for uniform).

    mean_block defaults to the uniform midpoint (min+max)/2 — a *compatibility
    initial value* that matches the uniform mean, not a statistically optimal
    choice (see analysis/block_length_vr_calibration.py and plan §3.A Finding 10).
    """
    if block_dist != "geometric":
        return None
    if mean_block is None:
        mean_block = (min_block + max_block) / 2.0
    return 1.0 / mean_block


def _validate_bootstrap_args(
    min_block: int,
    max_block: int,
    retirement_years: int,
    block_dist: str = "uniform",
    mean_block: int | None = None,
    min_country_len: int | None = None,
):
    if min_block < 1:
        raise ValueError(f"min_block must be >= 1, got {min_block}")
    if min_block > max_block:
        raise ValueError(f"min_block ({min_block}) must be <= max_block ({max_block})")
    if retirement_years <= 0:
        raise ValueError(f"retirement_years must be > 0, got {retirement_years}")
    if block_dist not in ("uniform", "geometric"):
        raise ValueError(f"block_dist must be 'uniform' or 'geometric', got {block_dist!r}")
    if block_dist == "geometric":
        # Resolve the implicit default the SAME way _resolve_geom_p does, so the
        # omitted-mean_block case is validated identically to an explicit value
        # (branch review P2): otherwise the midpoint default could exceed a short
        # series and bypass the lap-prevention guard below.
        eff_mean = (mean_block if mean_block is not None
                    else (min_block + max_block) / 2.0)
        if eff_mean < 1:
            raise ValueError(f"mean_block must be >= 1, got {eff_mean}")
        # Finding 9: mean_block exceeding the shortest series means a single
        # geometric block can lap an entire country's data within one path.
        if min_country_len is not None and eff_mean > min_country_len:
            raise ValueError(
                f"mean_block ({eff_mean}) exceeds the shortest available series "
                f"length ({min_country_len}); pick a smaller mean_block."
            )


def block_bootstrap_np(
    data: np.ndarray,
    n: int,
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
    block_dist: str = "uniform",
    mean_block: int | None = None,
) -> np.ndarray:
    """Block bootstrap returning a numpy array (no DataFrame overhead).

    Parameters
    ----------
    data : np.ndarray
        Pre-extracted numpy array from returns_df[cols].values.
        Caller should cache this to avoid repeated DataFrame column access.
    n : int
        Number of rows in data (len(data)).
    retirement_years, min_block, max_block : int
        Same as block_bootstrap().
    rng : np.random.Generator or None
        Random number generator.
    block_dist : {"uniform", "geometric"}
        Block-length law. "uniform" (default) is unchanged behavior.
    mean_block : int or None
        Mean block length for geometric mode (default = uniform midpoint).

    Returns
    -------
    np.ndarray
        shape (retirement_years, data.shape[1]).
    """
    _validate_bootstrap_args(min_block, max_block, retirement_years,
                             block_dist, mean_block, min_country_len=n)
    if rng is None:
        rng = np.random.default_rng()
    geom_p = _resolve_geom_p(block_dist, min_block, max_block, mean_block)
    return _block_bootstrap_core(data, n, retirement_years, min_block, max_block,
                                 rng, data.shape[1], block_dist, geom_p)


def block_bootstrap(
    returns_df: pd.DataFrame,
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
    columns: list[str] | None = None,
    block_dist: str = "uniform",
    mean_block: int | None = None,
) -> pd.DataFrame:
    """使用 block bootstrap 方法生成一条退休期间的回报序列。

    算法：
    1. 随机选择 block_size ∈ [min_block, max_block]
    2. 随机选择起始行索引 start ∈ [0, n-1]
    3. 从 start 开始取 block_size 行，超出数据末尾时循环到开头（环形采样）
    4. 重复 1-3 直到累积长度 >= retirement_years
    5. 截断到 retirement_years 行

    Parameters
    ----------
    returns_df : pd.DataFrame
        历史回报数据，必须包含 columns 中指定的列。
    retirement_years : int
        需要生成的回报序列长度。
    min_block : int
        最小采样窗口大小。
    max_block : int
        最大采样窗口大小。
    rng : np.random.Generator or None
        随机数生成器，用于可复现性。默认使用全局随机状态。
    columns : list[str] or None
        要采样的列名。默认 None 时使用 RETURN_COLS。
        传入 RETURN_COLS + HOUSING_COLS 可联合采样金融和房产数据。

    Returns
    -------
    pd.DataFrame
        shape 为 (retirement_years, len(columns)) 的 DataFrame。
    """
    cols = columns if columns is not None else RETURN_COLS
    data = returns_df[cols].values
    n = len(data)
    _validate_bootstrap_args(min_block, max_block, retirement_years,
                             block_dist, mean_block, min_country_len=n)
    if rng is None:
        rng = np.random.default_rng()

    geom_p = _resolve_geom_p(block_dist, min_block, max_block, mean_block)
    output = _block_bootstrap_core(data, n, retirement_years, min_block, max_block,
                                   rng, len(cols), block_dist, geom_p)
    return pd.DataFrame(output, columns=cols)


def _prepare_pooled_arrays(
    country_dfs: dict[str, pd.DataFrame],
    country_weights: dict[str, float] | None,
    cols: list[str],
) -> tuple[list[str], list[np.ndarray], list[int], np.ndarray | None]:
    """Pre-convert country DataFrames to numpy arrays and build probability array.

    Returns (country_list, country_arrays, country_lens, probs).
    """
    country_list = list(country_dfs.keys())
    country_arrays = [country_dfs[iso][cols].values for iso in country_list]
    country_lens = [len(a) for a in country_arrays]
    n_countries = len(country_list)

    if country_weights is not None:
        probs = np.array([country_weights.get(iso, 0.0) for iso in country_list])
        prob_sum = probs.sum()
        if prob_sum > 0:
            probs = probs / prob_sum
        else:
            probs = np.ones(n_countries) / n_countries
    else:
        probs = None

    return country_list, country_arrays, country_lens, probs


def _block_bootstrap_pooled_core(
    country_arrays: list[np.ndarray],
    country_lens: list[int],
    n_countries: int,
    probs: np.ndarray | None,
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator,
    n_cols: int,
    block_dist: str = "uniform",
    geom_p: float | None = None,
) -> np.ndarray:
    """Core pooled block bootstrap loop operating on numpy arrays.

    RNG call order (country, then length, then start) is preserved exactly for
    block_dist="uniform"; geometric only swaps the length draw.
    """
    output = np.empty((retirement_years, n_cols), dtype=np.float64)
    pos = 0

    while pos < retirement_years:
        if probs is not None:
            country_idx = rng.choice(n_countries, p=probs)
        else:
            country_idx = rng.integers(0, n_countries)
        data = country_arrays[country_idx]
        n = country_lens[country_idx]

        if block_dist == "geometric":
            block_len = rng.geometric(geom_p)
        else:
            block_len = rng.integers(min_block, max_block + 1)
        block_size = min(block_len, retirement_years - pos)
        start = rng.integers(0, n)
        indices = np.arange(start, start + block_size) % n
        output[pos:pos + block_size] = data[indices]
        pos += block_size

    return output


def block_bootstrap_pooled_np(
    country_arrays: list[np.ndarray],
    country_lens: list[int],
    probs: np.ndarray | None,
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
    block_dist: str = "uniform",
    mean_block: int | None = None,
) -> np.ndarray:
    """Pooled multi-country block bootstrap returning numpy array.

    Parameters
    ----------
    country_arrays : list[np.ndarray]
        Pre-extracted numpy arrays, one per country.
    country_lens : list[int]
        Number of rows in each country array.
    probs : np.ndarray or None
        Sampling probabilities per country.
    retirement_years, min_block, max_block : int
        Same as block_bootstrap_pooled().
    rng : np.random.Generator or None
        Random number generator.

    Returns
    -------
    np.ndarray
        shape (retirement_years, n_cols).
    """
    _validate_bootstrap_args(
        min_block, max_block, retirement_years, block_dist, mean_block,
        min_country_len=min(country_lens) if country_lens else None,
    )
    if rng is None:
        rng = np.random.default_rng()
    n_countries = len(country_arrays)
    n_cols = country_arrays[0].shape[1]
    geom_p = _resolve_geom_p(block_dist, min_block, max_block, mean_block)
    return _block_bootstrap_pooled_core(
        country_arrays, country_lens, n_countries, probs,
        retirement_years, min_block, max_block, rng, n_cols, block_dist, geom_p,
    )


def block_bootstrap_pooled(
    country_dfs: dict[str, pd.DataFrame],
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
    country_weights: dict[str, float] | None = None,
    columns: list[str] | None = None,
    block_dist: str = "uniform",
    mean_block: int | None = None,
) -> pd.DataFrame:
    """池化多国 block bootstrap。

    每个 block：
    1) 随机选国家（等概率或按 country_weights 加权）
    2) 该国内环形采样

    Parameters
    ----------
    country_dfs : dict[str, pd.DataFrame]
        {iso: country_df}，每个 df 必须包含 columns 中指定的列。
    retirement_years : int
        需要生成的总年数。
    min_block, max_block : int
        Block 大小范围。
    rng : np.random.Generator or None
        随机数生成器。
    country_weights : dict[str, float] or None
        {iso: weight} 各国采样权重（需已归一化，和为 1）。
        为 None 时使用等概率 1/N。
    columns : list[str] or None
        要采样的列名。默认 None 时使用 RETURN_COLS。

    Returns
    -------
    pd.DataFrame
        shape (retirement_years, len(columns)) 的 DataFrame。
    """
    cols = columns if columns is not None else RETURN_COLS
    _, country_arrays, country_lens, probs = _prepare_pooled_arrays(
        country_dfs, country_weights, cols,
    )
    _validate_bootstrap_args(
        min_block, max_block, retirement_years, block_dist, mean_block,
        min_country_len=min(country_lens) if country_lens else None,
    )
    if rng is None:
        rng = np.random.default_rng()

    geom_p = _resolve_geom_p(block_dist, min_block, max_block, mean_block)
    output = _block_bootstrap_pooled_core(
        country_arrays, country_lens, len(country_arrays), probs,
        retirement_years, min_block, max_block, rng, len(cols), block_dist, geom_p,
    )
    return pd.DataFrame(output, columns=cols)
