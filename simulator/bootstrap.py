"""Block Bootstrap 循环采样模块。"""

import numpy as np
import pandas as pd


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
        历史回报数据，必须包含 US Stock, International Stock, US Bond, US Inflation 列。
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
        列为 US Stock, International Stock, US Bond, US Inflation。
    """
    if rng is None:
        rng = np.random.default_rng()

    return_cols = ["US Stock", "International Stock", "US Bond", "US Inflation"]
    data = returns_df[return_cols].values  # shape: (n, 4)
    n = len(data)

    sampled_rows: list[np.ndarray] = []
    total_sampled = 0

    while total_sampled < retirement_years:
        # 随机选择 block 大小
        block_size = rng.integers(min_block, max_block + 1)  # 包含 max_block
        # 随机选择起始索引
        start = rng.integers(0, n)

        # 环形采样：取 block_size 行数据
        indices = np.arange(start, start + block_size) % n
        block = data[indices]

        sampled_rows.append(block)
        total_sampled += block_size

    # 拼接并截断到 retirement_years
    all_rows = np.concatenate(sampled_rows, axis=0)[:retirement_years]

    return pd.DataFrame(all_rows, columns=return_cols)
