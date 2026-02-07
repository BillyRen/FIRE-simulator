"""数据加载与预处理模块。"""

import logging
import os

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


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

    Raises
    ------
    FileNotFoundError
        文件不存在时抛出。
    ValueError
        数据格式有问题时抛出。
    """
    if filepath is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        filepath = os.path.join(base_dir, "data", "FIRE_dataset.csv")

    # 读取 CSV
    try:
        df = pd.read_csv(filepath)
    except FileNotFoundError:
        raise FileNotFoundError(f"数据文件不存在: {filepath}")
    except pd.errors.ParserError as e:
        raise ValueError(f"CSV 解析失败: {e}")
    except Exception as e:
        raise ValueError(f"读取数据文件时发生错误: {e}")

    # 验证列名
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"CSV 缺少必要列: {col}")

    # 检查空数据
    if len(df) == 0:
        raise ValueError("CSV 文件为空，没有数据行")

    # 检查重复年份
    duplicates = df["Year"].duplicated()
    if duplicates.any():
        dup_years = df.loc[duplicates, "Year"].tolist()
        logger.warning("发现重复年份，已保留首次出现的记录: %s", dup_years)
        df = df.drop_duplicates(subset=["Year"], keep="first")

    # 检查数值列的 NaN / Inf
    numeric_cols = ["US Stock", "International Stock", "US Bond", "US Inflation"]
    has_nan = df[numeric_cols].isna().any(axis=1)
    has_inf = np.isinf(df[numeric_cols].values).any(axis=1)
    bad_rows = has_nan | has_inf

    if bad_rows.any():
        bad_years = df.loc[bad_rows, "Year"].tolist()
        logger.warning("发现包含 NaN/Inf 的行（已删除），涉及年份: %s", bad_years)
        df = df[~bad_rows]

    if len(df) == 0:
        raise ValueError("清洗后没有有效数据行")

    # 确保数据按年份排序
    df = df.sort_values("Year").reset_index(drop=True)

    return df
