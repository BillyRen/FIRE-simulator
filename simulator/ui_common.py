"""共享的 Streamlit 侧边栏 UI 组件，消除三个页面间的代码重复。"""

import streamlit as st
import pandas as pd

from simulator.config import (
    INTL_STOCK_DATA_START_YEAR,
    DEFAULT_DATA_START_YEAR,
    DATA_WARNING_MSG,
    DATA_HELP_MSG,
    DEFAULT_ALLOCATION,
    DEFAULT_EXPENSE_RATIOS,
    DEFAULT_MIN_BLOCK,
    DEFAULT_MAX_BLOCK,
    DEFAULT_RETIREMENT_YEARS,
)


def sidebar_data_range(returns_df: pd.DataFrame, key_prefix: str = "") -> int:
    """数据起始年选择器 + 1970 年前警告。

    Returns
    -------
    int
        用户选择的数据起始年。
    """
    st.subheader("📅 数据范围")
    data_start_year = st.number_input(
        "数据起始年",
        min_value=int(returns_df["Year"].min()),
        max_value=int(returns_df["Year"].max()),
        value=DEFAULT_DATA_START_YEAR,
        step=1,
        key=f"{key_prefix}start_year" if key_prefix else None,
        help=DATA_HELP_MSG,
    )
    if data_start_year < INTL_STOCK_DATA_START_YEAR:
        st.warning(DATA_WARNING_MSG)
    return int(data_start_year)


def sidebar_allocation(
    key_prefix: str = "",
) -> tuple[dict[str, float], dict[str, float], int]:
    """资产配置 + 费用率输入。

    Returns
    -------
    tuple[dict, dict, int]
        (allocation, expense_ratios, total_pct)
        - allocation: 资产类别 -> 比例 (0-1)
        - expense_ratios: 资产类别 -> 费用率 (0-1)
        - total_pct: 资产配置总百分比（应为 100）
    """
    st.subheader("📊 资产配置 (%)")
    us_stock_pct = st.slider(
        "美股 (US Stock)", 0, 100, DEFAULT_ALLOCATION["us_stock"], 5,
        key=f"{key_prefix}us" if key_prefix else None,
    )
    intl_stock_pct = st.slider(
        "国际股票 (Intl Stock)", 0, 100, DEFAULT_ALLOCATION["intl_stock"], 5,
        key=f"{key_prefix}intl" if key_prefix else None,
    )
    us_bond_pct = st.slider(
        "美债 (US Bond)", 0, 100, DEFAULT_ALLOCATION["us_bond"], 5,
        key=f"{key_prefix}bond" if key_prefix else None,
    )

    total_pct = us_stock_pct + intl_stock_pct + us_bond_pct
    if total_pct != 100:
        st.error(f"资产配置总和必须为 100%，当前为 {total_pct}%")

    st.subheader("💸 费用率 (%)")
    us_stock_expense = st.number_input(
        "美股费用率", min_value=0.00, max_value=5.00,
        value=DEFAULT_EXPENSE_RATIOS["us_stock"],
        step=0.01, format="%.2f",
        key=f"{key_prefix}exp_us" if key_prefix else None,
    )
    intl_stock_expense = st.number_input(
        "国际股票费用率", min_value=0.00, max_value=5.00,
        value=DEFAULT_EXPENSE_RATIOS["intl_stock"],
        step=0.01, format="%.2f",
        key=f"{key_prefix}exp_intl" if key_prefix else None,
    )
    us_bond_expense = st.number_input(
        "美债费用率", min_value=0.00, max_value=5.00,
        value=DEFAULT_EXPENSE_RATIOS["us_bond"],
        step=0.01, format="%.2f",
        key=f"{key_prefix}exp_bond" if key_prefix else None,
    )

    allocation = {
        "us_stock": us_stock_pct / 100.0,
        "intl_stock": intl_stock_pct / 100.0,
        "us_bond": us_bond_pct / 100.0,
    }
    expense_ratios = {
        "us_stock": us_stock_expense / 100.0,
        "intl_stock": intl_stock_expense / 100.0,
        "us_bond": us_bond_expense / 100.0,
    }

    return allocation, expense_ratios, total_pct


def sidebar_simulation_settings(
    key_prefix: str = "",
    default_years: int = DEFAULT_RETIREMENT_YEARS,
    default_nsim: int = 10_000,
) -> tuple[int, int, int, int]:
    """退休年限 + 采样窗口 + 模拟次数。

    Returns
    -------
    tuple[int, int, int, int]
        (retirement_years, min_block, max_block, num_simulations)
    """
    st.subheader("⏳ 模拟设置")
    retirement_years = st.slider(
        "退休年限", 10, 80, default_years, 1,
        key=f"{key_prefix}years" if key_prefix else None,
    )

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        min_block = st.number_input(
            "最小采样窗口", min_value=1, max_value=30,
            value=DEFAULT_MIN_BLOCK,
            key=f"{key_prefix}minb" if key_prefix else None,
        )
    with col_b2:
        max_block = st.number_input(
            "最大采样窗口", min_value=1, max_value=55,
            value=DEFAULT_MAX_BLOCK,
            key=f"{key_prefix}maxb" if key_prefix else None,
        )

    if min_block > max_block:
        st.error("最小采样窗口不能大于最大采样窗口")

    num_simulations = st.slider(
        "模拟次数", 1_000, 50_000, default_nsim, 1_000,
        key=f"{key_prefix}nsim" if key_prefix else None,
    )

    return int(retirement_years), int(min_block), int(max_block), int(num_simulations)


def filter_returns(
    returns_df: pd.DataFrame,
    data_start_year: int,
    retirement_years: int,
) -> pd.DataFrame:
    """过滤数据并检查数据量是否充足。

    Returns
    -------
    pd.DataFrame
        按起始年过滤后的 DataFrame。
    """
    filtered = returns_df[returns_df["Year"] >= data_start_year].reset_index(drop=True)

    if len(filtered) < retirement_years:
        st.warning(
            f"⚠️ 可用数据仅 {len(filtered)} 年，少于退休年限 {retirement_years} 年，"
            f"Bootstrap 将大量循环采样，可能影响模拟结果的多样性。"
        )

    return filtered
