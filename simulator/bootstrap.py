"""Block Bootstrap 循环采样模块。"""

from __future__ import annotations

import numpy as np
import pandas as pd


RETURN_COLS = ["Domestic_Stock", "Global_Stock", "Domestic_Bond", "Inflation"]
HOUSING_COLS = ["Housing_CapGain", "Rent_Growth", "Long_Rate"]


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
    if min_block < 1:
        raise ValueError(f"min_block must be >= 1, got {min_block}")
    if min_block > max_block:
        raise ValueError(f"min_block ({min_block}) must be <= max_block ({max_block})")
    if retirement_years <= 0:
        raise ValueError(f"retirement_years must be > 0, got {retirement_years}")

    if rng is None:
        rng = np.random.default_rng()

    cols = columns if columns is not None else RETURN_COLS
    data = returns_df[cols].values
    n = len(data)

    output = np.empty((retirement_years, len(cols)), dtype=np.float64)
    pos = 0

    while pos < retirement_years:
        # 计算本次block大小，确保不超出剩余空间
        block_size = min(rng.integers(min_block, max_block + 1), retirement_years - pos)
        start = rng.integers(0, n)
        indices = np.arange(start, start + block_size) % n
        # 直接写入预分配数组
        output[pos:pos + block_size] = data[indices]
        pos += block_size

    return pd.DataFrame(output, columns=cols)


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
    if min_block < 1:
        raise ValueError(f"min_block must be >= 1, got {min_block}")
    if min_block > max_block:
        raise ValueError(f"min_block ({min_block}) must be <= max_block ({max_block})")
    if retirement_years <= 0:
        raise ValueError(f"retirement_years must be > 0, got {retirement_years}")

    if rng is None:
        rng = np.random.default_rng()

    cols = columns if columns is not None else RETURN_COLS

    # 预转换为 numpy 数组
    # NOTE: 这个转换可以在调用端缓存以进一步提升性能
    country_list = list(country_dfs.keys())
    country_arrays = {
        iso: df[cols].values for iso, df in country_dfs.items()
    }
    n_countries = len(country_list)

    # 构建采样概率数组
    if country_weights is not None:
        probs = np.array([country_weights.get(iso, 0.0) for iso in country_list])
        prob_sum = probs.sum()
        if prob_sum > 0:
            probs = probs / prob_sum  # 安全归一化
        else:
            probs = np.ones(n_countries) / n_countries
    else:
        probs = None  # 等概率

    # 预分配输出数组，避免动态list增长和concatenate
    output = np.empty((retirement_years, len(cols)), dtype=np.float64)
    pos = 0

    while pos < retirement_years:
        # 1. 随机选国家
        if probs is not None:
            country_idx = rng.choice(n_countries, p=probs)
        else:
            country_idx = rng.integers(0, n_countries)
        iso = country_list[country_idx]
        data = country_arrays[iso]
        n = len(data)

        # 2. 该国内环形采样
        # 计算本次block大小，确保不超出剩余空间
        block_size = min(rng.integers(min_block, max_block + 1), retirement_years - pos)
        start = rng.integers(0, n)
        indices = np.arange(start, start + block_size) % n

        # 直接写入预分配数组
        output[pos:pos + block_size] = data[indices]
        pos += block_size

    return pd.DataFrame(output, columns=cols)
