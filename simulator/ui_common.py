"""共享的 Streamlit 侧边栏 UI 组件，消除三个页面间的代码重复。"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from simulator.cashflow import CashFlowItem
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


def sidebar_cash_flows(key_prefix: str = "") -> list[CashFlowItem]:
    """自定义现金流编辑器（基于独立表单控件）。

    每条现金流用 expander + 独立 widget 展示，通过唯一 ID 管理状态，
    避免 st.data_editor 的状态丢失问题。

    Parameters
    ----------
    key_prefix : str
        Streamlit widget key 前缀（多页面防冲突）。

    Returns
    -------
    list[CashFlowItem]
        用户定义的现金流列表。
    """
    st.subheader("💰 自定义现金流")

    # ------ 唯一 ID 列表管理 ------
    ids_key = f"{key_prefix}cf_ids"
    next_id_key = f"{key_prefix}cf_next_id"
    if ids_key not in st.session_state:
        st.session_state[ids_key] = []
    if next_id_key not in st.session_state:
        st.session_state[next_id_key] = 1

    # 添加按钮
    if st.button("➕ 添加现金流", key=f"{key_prefix}cf_add"):
        new_id = st.session_state[next_id_key]
        st.session_state[ids_key].append(new_id)
        st.session_state[next_id_key] = new_id + 1
        st.rerun()

    # ------ 渲染每条现金流 ------
    cash_flow_items: list[CashFlowItem] = []
    delete_id: int | None = None

    for uid in st.session_state[ids_key]:
        # 读取名称用于 expander 标题（从 session_state 取已有值）
        name_key = f"{key_prefix}cf_{uid}_name"
        current_name = st.session_state.get(name_key, "新现金流")
        display_name = current_name if current_name else "新现金流"

        with st.expander(f"{display_name}", expanded=True):
            # 第一行：名称 + 类型
            c1, c2 = st.columns([3, 2])
            with c1:
                name = st.text_input(
                    "名称", value="新现金流",
                    key=name_key,
                    label_visibility="collapsed",
                    placeholder="名称",
                )
            with c2:
                cf_type = st.selectbox(
                    "类型", ["支出", "收入"],
                    key=f"{key_prefix}cf_{uid}_type",
                    label_visibility="collapsed",
                )

            # 第二行：金额 + 起始年
            c3, c4 = st.columns(2)
            with c3:
                raw_amount = st.number_input(
                    "金额 ($)", min_value=0, max_value=100_000_000,
                    value=10_000, step=1_000, format="%d",
                    key=f"{key_prefix}cf_{uid}_amt",
                )
            with c4:
                start_year = st.number_input(
                    "起始年", min_value=1, max_value=200,
                    value=1, step=1,
                    key=f"{key_prefix}cf_{uid}_start",
                    help="退休第几年开始（1=第一年）",
                )

            # 第三行：持续年数 + 通胀调整
            c5, c6 = st.columns(2)
            with c5:
                duration = st.number_input(
                    "持续年数", min_value=1, max_value=200,
                    value=10, step=1,
                    key=f"{key_prefix}cf_{uid}_dur",
                )
            with c6:
                inflation_adj = st.checkbox(
                    "通胀调整",
                    value=True,
                    key=f"{key_prefix}cf_{uid}_infl",
                    help="勾选 = 金额为 year-0 实际购买力",
                )

            # 删除按钮
            if st.button(
                "🗑 删除", key=f"{key_prefix}cf_{uid}_del",
                use_container_width=True,
            ):
                delete_id = uid

            # 收集有效数据
            amount = float(raw_amount) if cf_type == "收入" else -float(raw_amount)
            if raw_amount > 0:
                cash_flow_items.append(
                    CashFlowItem(
                        name=name or "未命名",
                        amount=amount,
                        start_year=int(start_year),
                        duration=int(duration),
                        inflation_adjusted=inflation_adj,
                    )
                )

    # ------ 处理删除 ------
    if delete_id is not None:
        st.session_state[ids_key].remove(delete_id)
        # 清理该 ID 相关的 session_state keys
        for suffix in ("name", "type", "amt", "start", "dur", "infl", "del"):
            k = f"{key_prefix}cf_{delete_id}_{suffix}"
            st.session_state.pop(k, None)
        st.rerun()

    return cash_flow_items
