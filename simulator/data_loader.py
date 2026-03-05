"""数据加载与预处理模块。

支持两种数据源：
  1. JST 多国数据 — CSV 长格式：Year, Country, Domestic_Stock, Global_Stock, Domestic_Bond, Inflation
  2. FIRE Dataset — CSV 宽格式（仅美国）：Year, US Stock, International Stock, US Bond, US Inflation
     加载时自动转换为内部统一格式。
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

HOUSING_COLS = ["Housing_CapGain", "Rent_Growth", "Long_Rate"]


_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_csv_path() -> str:
    return os.path.join(_BASE_DIR, "data", "jst_returns.csv")


def _default_meta_path() -> str:
    return os.path.join(_BASE_DIR, "data", "jst_countries.json")


def _fire_dataset_path() -> str:
    return os.path.join(_BASE_DIR, "data", "FIRE_dataset.csv")


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


# ---------------------------------------------------------------------------
# FIRE Dataset (老数据，仅美国)
# ---------------------------------------------------------------------------

_FIRE_COL_MAP = {
    "US Stock": "Domestic_Stock",
    "International Stock": "Global_Stock",
    "US Bond": "Domestic_Bond",
    "US Inflation": "Inflation",
}


def load_fire_dataset(filepath: str | None = None) -> pd.DataFrame:
    """加载 FIRE_dataset.csv 并转换为内部统一格式。

    列映射: US Stock → Domestic_Stock, International Stock → Global_Stock,
    US Bond → Domestic_Bond, US Inflation → Inflation。
    添加 Country = "USA" 列。
    """
    if filepath is None:
        filepath = _fire_dataset_path()

    try:
        df = pd.read_csv(filepath)
    except FileNotFoundError:
        raise FileNotFoundError(f"数据文件不存在: {filepath}")
    except Exception as e:
        raise ValueError(f"读取 FIRE Dataset 时发生错误: {e}")

    for old_col in _FIRE_COL_MAP:
        if old_col not in df.columns:
            raise ValueError(f"FIRE_dataset.csv 缺少必要列: {old_col}")

    df = df.rename(columns=_FIRE_COL_MAP)
    df["Country"] = "USA"

    # 清洗 NaN / Inf
    has_nan = df[RETURN_COLS].isna().any(axis=1)
    has_inf = np.isinf(df[RETURN_COLS].values).any(axis=1)
    bad_rows = has_nan | has_inf
    if bad_rows.any():
        logger.warning("FIRE Dataset 发现 %d 行 NaN/Inf（已删除）", bad_rows.sum())
        df = df[~bad_rows]

    df = df.sort_values("Year").reset_index(drop=True)
    return df[EXPECTED_COLUMNS]


def load_fire_country_list() -> list[dict[str, Any]]:
    """返回 FIRE Dataset 的国家元数据（仅 USA）。"""
    return [{
        "iso": "USA",
        "name_en": "United States",
        "name_zh": "美国",
        "min_year": 1871,
        "max_year": 2025,
        "n_years": 155,
    }]


# ---------------------------------------------------------------------------
# 统一入口（按 data_source 分发）
# ---------------------------------------------------------------------------

def load_returns_by_source(data_source: str = "jst") -> pd.DataFrame:
    """根据 data_source 加载对应的回报数据。"""
    if data_source == "fire_dataset":
        return load_fire_dataset()
    return load_returns_data()


def load_country_list_by_source(data_source: str = "jst") -> list[dict[str, Any]]:
    """根据 data_source 加载对应的国家列表。"""
    if data_source == "fire_dataset":
        return load_fire_country_list()
    return load_country_list()


def get_housing_available_countries(data_source: str = "jst") -> list[dict[str, Any]]:
    """返回有 housing 数据的国家列表（用于买房 vs 租房功能）。

    仅 JST 数据源含 housing 数据。FIRE Dataset 不含 housing 数据，返回空列表。
    """
    if data_source != "jst":
        return []
    countries = load_country_list()
    return [c for c in countries if c.get("has_housing", False)]


def filter_housing_data(
    df: pd.DataFrame,
    country: str,
    data_start_year: int = 1970,
) -> pd.DataFrame:
    """按国家和起始年过滤，并只保留有 housing 数据的行。

    与 filter_by_country 类似，但额外要求 Housing_CapGain 非 NaN。
    用于买房 vs 租房模拟中需要完整 housing 数据的场景。
    """
    result = filter_by_country(df, country, data_start_year)
    if "Housing_CapGain" in result.columns:
        result = result.dropna(subset=["Housing_CapGain"]).reset_index(drop=True)
    return result


def get_housing_country_dfs(
    df: pd.DataFrame,
    data_start_year: int = 1970,
) -> dict[str, pd.DataFrame]:
    """按国家拆分数据，仅保留有 housing 数据的国家和行。"""
    filtered = df[df["Year"] >= data_start_year]
    result = {}
    for iso, group in filtered.groupby("Country"):
        country_df = group.sort_values("Year").reset_index(drop=True)
        if "Housing_CapGain" in country_df.columns:
            country_df = country_df.dropna(subset=["Housing_CapGain"])
        if len(country_df) >= 2:
            result[str(iso)] = country_df
    return result
