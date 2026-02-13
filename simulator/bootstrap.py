"""Block Bootstrap 循环采样模块。"""

from __future__ import annotations

import numpy as np
import pandas as pd


RETURN_COLS = ["Domestic_Stock", "Global_Stock", "Domestic_Bond", "Inflation"]


def block_bootstrap(
    returns_df: pd.DataFrame,
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
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
        历史回报数据，必须包含 Domestic_Stock, Global_Stock, Domestic_Bond, Inflation 列。
    retirement_years : int
        退休年限（需要生成的回报序列长度）。
    min_block : int
        最小采样窗口大小。
    max_block : int
        最大采样窗口大小。
    rng : np.random.Generator or None
        随机数生成器，用于可复现性。默认使用全局随机状态。

    Returns
    -------
    pd.DataFrame
        shape 为 (retirement_years, 4) 的 DataFrame，
        列为 Domestic_Stock, Global_Stock, Domestic_Bond, Inflation。
    """
    if rng is None:
        rng = np.random.default_rng()

    data = returns_df[RETURN_COLS].values  # shape: (n, 4)
    n = len(data)

    sampled_rows: list[np.ndarray] = []
    total_sampled = 0

    while total_sampled < retirement_years:
        block_size = rng.integers(min_block, max_block + 1)
        start = rng.integers(0, n)
        indices = np.arange(start, start + block_size) % n
        block = data[indices]
        sampled_rows.append(block)
        total_sampled += block_size

    all_rows = np.concatenate(sampled_rows, axis=0)[:retirement_years]
    return pd.DataFrame(all_rows, columns=RETURN_COLS)


def block_bootstrap_pooled(
    country_dfs: dict[str, pd.DataFrame],
    retirement_years: int,
    min_block: int,
    max_block: int,
    rng: np.random.Generator | None = None,
    country_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """池化多国 block bootstrap。

    每个 block：
    1) 随机选国家（等概率或按 country_weights 加权）
    2) 该国内环形采样

    Parameters
    ----------
    country_dfs : dict[str, pd.DataFrame]
        {iso: country_df}，每个 df 必须包含 RETURN_COLS 列。
    retirement_years : int
        需要生成的总年数。
    min_block, max_block : int
        Block 大小范围。
    rng : np.random.Generator or None
        随机数生成器。
    country_weights : dict[str, float] or None
        {iso: weight} 各国采样权重（需已归一化，和为 1）。
        为 None 时使用等概率 1/N。

    Returns
    -------
    pd.DataFrame
        shape (retirement_years, 4) 的 DataFrame，列为 RETURN_COLS。
    """
    if rng is None:
        rng = np.random.default_rng()

    # 预转换为 numpy 数组
    country_list = list(country_dfs.keys())
    country_arrays = {
        iso: df[RETURN_COLS].values for iso, df in country_dfs.items()
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

    sampled_rows: list[np.ndarray] = []
    total_sampled = 0

    while total_sampled < retirement_years:
        # 1. 随机选国家
        if probs is not None:
            country_idx = rng.choice(n_countries, p=probs)
        else:
            country_idx = rng.integers(0, n_countries)
        iso = country_list[country_idx]
        data = country_arrays[iso]
        n = len(data)

        # 2. 该国内环形采样
        block_size = rng.integers(min_block, max_block + 1)
        start = rng.integers(0, n)
        indices = np.arange(start, start + block_size) % n
        block = data[indices]

        sampled_rows.append(block)
        total_sampled += block_size

    all_rows = np.concatenate(sampled_rows, axis=0)[:retirement_years]
    return pd.DataFrame(all_rows, columns=RETURN_COLS)
