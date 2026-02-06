"""数据加载与预处理模块。"""

import os
import pandas as pd


EXPECTED_COLUMNS = [
    "Year",
    "US Stock",
    "International Stock",
    "US Bond",
    "US Inflation",
]


def load_returns_data(filepath: str | None = None) -> pd.DataFrame:
    """加载历史回报数据 CSV 文件。

    Parameters
    ----------
    filepath : str or None
        CSV 文件路径。默认为项目 data/ 目录下的 FIRE_dataset.csv。

    Returns
    -------
    pd.DataFrame
        包含 Year, US Stock, International Stock, US Bond, US Inflation 列的 DataFrame。
    """
    if filepath is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        filepath = os.path.join(base_dir, "data", "FIRE_dataset.csv")

    df = pd.read_csv(filepath)

    # 验证列名
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"CSV 缺少必要列: {col}")

    # 确保数据按年份排序
    df = df.sort_values("Year").reset_index(drop=True)

    return df
