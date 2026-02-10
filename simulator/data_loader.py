"""数据加载与预处理模块。

支持 JST 多国数据格式：
  CSV 长格式列：Year, Country, Domestic_Stock, Global_Stock, Domestic_Bond, Inflation
"""

import json
import logging
import os
from typing import Any

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


EXPECTED_COLUMNS = [
    "Year",
    "Country",
    "Domestic_Stock",
    "Global_Stock",
    "Domestic_Bond",
    "Inflation",
]

RETURN_COLS = ["Domestic_Stock", "Global_Stock", "Domestic_Bond", "Inflation"]


def _default_csv_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "data", "jst_returns.csv")


def _default_meta_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "data", "jst_countries.json")


def load_country_list(meta_path: str | None = None) -> list[dict[str, Any]]:
    """加载国家元数据列表。

    Returns
    -------
    list[dict]
        每个 dict 含 iso, name_en, name_zh, min_year, max_year, n_years。
    """
    if meta_path is None:
        meta_path = _default_meta_path()

    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_returns_data(filepath: str | None = None) -> pd.DataFrame:
    """加载全量 JST 回报数据 CSV（长格式，包含所有国家）。

    Returns
    -------
    pd.DataFrame
        包含 Year, Country, Domestic_Stock, Global_Stock, Domestic_Bond, Inflation 列。
    """
    if filepath is None:
        filepath = _default_csv_path()

    try:
        df = pd.read_csv(filepath)
    except FileNotFoundError:
        raise FileNotFoundError(f"数据文件不存在: {filepath}")
    except pd.errors.ParserError as e:
        raise ValueError(f"CSV 解析失败: {e}")
    except Exception as e:
        raise ValueError(f"读取数据文件时发生错误: {e}")

    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"CSV 缺少必要列: {col}")

    if len(df) == 0:
        raise ValueError("CSV 文件为空，没有数据行")

    # 检查数值列的 NaN / Inf
    has_nan = df[RETURN_COLS].isna().any(axis=1)
    has_inf = np.isinf(df[RETURN_COLS].values).any(axis=1)
    bad_rows = has_nan | has_inf

    if bad_rows.any():
        bad_info = df.loc[bad_rows, ["Year", "Country"]].values.tolist()
        logger.warning("发现包含 NaN/Inf 的行（已删除）: %s", bad_info[:10])
        df = df[~bad_rows]

    if len(df) == 0:
        raise ValueError("清洗后没有有效数据行")

    df = df.sort_values(["Country", "Year"]).reset_index(drop=True)
    return df


def filter_by_country(
    df: pd.DataFrame,
    country: str,
    data_start_year: int = 1970,
) -> pd.DataFrame:
    """按国家和起始年份过滤数据。

    Parameters
    ----------
    df : pd.DataFrame
        全量数据。
    country : str
        国家 ISO 码（如 "USA"）或 "ALL" 表示不过滤国家。
    data_start_year : int
        数据起始年份。

    Returns
    -------
    pd.DataFrame
        过滤后的 DataFrame。
    """
    if country != "ALL":
        result = df[df["Country"] == country].copy()
    else:
        result = df.copy()

    result = result[result["Year"] >= data_start_year].reset_index(drop=True)
    return result


def get_country_dfs(
    df: pd.DataFrame,
    data_start_year: int = 1970,
) -> dict[str, pd.DataFrame]:
    """将全量数据按国家拆分为 dict，用于池化 bootstrap。

    Returns
    -------
    dict[str, pd.DataFrame]
        {iso: country_df}，每个 df 已按 Year 排序。
    """
    filtered = df[df["Year"] >= data_start_year]
    result = {}
    for iso, group in filtered.groupby("Country"):
        country_df = group.sort_values("Year").reset_index(drop=True)
        if len(country_df) >= 2:  # 至少需要 2 年数据
            result[str(iso)] = country_df
    return result
