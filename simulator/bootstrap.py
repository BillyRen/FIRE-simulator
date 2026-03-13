"""Block Bootstrap 循环采样模块。

Design note — Circular wrap-around:
When a sampled block extends past the end of the historical dataset, indices
wrap around to the beginning (modular arithmetic).  This is a deliberate design
choice that preserves inter-variable correlations within each block while
maximising the number of distinct starting points.  The alternative — truncating
at the boundary — would bias sampling toward earlier years and waste data near
the end of the series.  The trade-off is that a wrap-around block may contain a
one-period structural break at the seam, but the random block length mitigates
this by spreading seam positions across the dataset.
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
) -> np.ndarray:
    """Core block bootstrap loop operating on numpy arrays."""
    output = np.empty((retirement_years, n_cols), dtype=np.float64)
    pos = 0

    while pos < retirement_years:
        block_size = min(rng.integers(min_block, max_block + 1), retirement_years - pos)
        start = rng.integers(0, n)
        indices = np.arange(start, start + block_size) % n
        output[pos:pos + block_size] = data[indices]
        pos += block_size

    return output


def _validate_bootstrap_args(min_block: int, max_block: int, retirement_years: int):
    if min_block < 1:
        raise ValueError(f"min_block must be >= 1, got {min_block}")
    if min_block > max_block:
        raise ValueError(f"min_block ({min_block}) must be <= max_block ({max_block})")
    if retirement_years <= 0:
        raise ValueError(f"retirement_years must be > 0, got {retirement_years}")


def block_bootstrap_np(
    data: np.ndarray,
    n: int,
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
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

    Returns
    -------
    np.ndarray
        shape (retirement_years, data.shape[1]).
    """
    _validate_bootstrap_args(min_block, max_block, retirement_years)
    if rng is None:
        rng = np.random.default_rng()
    return _block_bootstrap_core(data, n, retirement_years, min_block, max_block, rng, data.shape[1])


def block_bootstrap(
    returns_df: pd.DataFrame,
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
    columns: list[str] | None = None,
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
    _validate_bootstrap_args(min_block, max_block, retirement_years)
    if rng is None:
        rng = np.random.default_rng()

    cols = columns if columns is not None else RETURN_COLS
    data = returns_df[cols].values
    n = len(data)

    output = _block_bootstrap_core(data, n, retirement_years, min_block, max_block, rng, len(cols))
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
) -> np.ndarray:
    """Core pooled block bootstrap loop operating on numpy arrays."""
    output = np.empty((retirement_years, n_cols), dtype=np.float64)
    pos = 0

    while pos < retirement_years:
        if probs is not None:
            country_idx = rng.choice(n_countries, p=probs)
        else:
            country_idx = rng.integers(0, n_countries)
        data = country_arrays[country_idx]
        n = country_lens[country_idx]

        block_size = min(rng.integers(min_block, max_block + 1), retirement_years - pos)
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
    _validate_bootstrap_args(min_block, max_block, retirement_years)
    if rng is None:
        rng = np.random.default_rng()
    n_countries = len(country_arrays)
    n_cols = country_arrays[0].shape[1]
    return _block_bootstrap_pooled_core(
        country_arrays, country_lens, n_countries, probs,
        retirement_years, min_block, max_block, rng, n_cols,
    )


def block_bootstrap_pooled(
    country_dfs: dict[str, pd.DataFrame],
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
    country_weights: dict[str, float] | None = None,
    columns: list[str] | None = None,
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
    _validate_bootstrap_args(min_block, max_block, retirement_years)
    if rng is None:
        rng = np.random.default_rng()

    cols = columns if columns is not None else RETURN_COLS
    _, country_arrays, country_lens, probs = _prepare_pooled_arrays(
        country_dfs, country_weights, cols,
    )

    output = _block_bootstrap_pooled_core(
        country_arrays, country_lens, len(country_arrays), probs,
        retirement_years, min_block, max_block, rng, len(cols),
    )
    return pd.DataFrame(output, columns=cols)
