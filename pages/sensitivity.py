"""敏感性分析页面 — 不同成功率对应的提取率 / 所需初始资产。"""

import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from simulator.data_loader import load_returns_data
from simulator.sweep import (
    pregenerate_return_scenarios,
    sweep_withdrawal_rates,
    interpolate_targets,
)

# ---------------------------------------------------------------------------
# 页面配置
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="敏感性分析 — FIRE 模拟器",
    page_icon="📊",
    layout="wide",
)

st.title("📊 敏感性分析")
st.caption("探索不同成功率对应的安全提取率与所需初始资产")

# ---------------------------------------------------------------------------
# 加载数据
# ---------------------------------------------------------------------------

@st.cache_data
def get_returns_data():
    return load_returns_data()


returns_df = get_returns_data()

# ---------------------------------------------------------------------------
# 目标成功率列表
# ---------------------------------------------------------------------------
TARGET_SUCCESS_RATES = [1.0, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70,
                        0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.0]

# ---------------------------------------------------------------------------
# 侧边栏 — 参数
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("分析参数")

    st.subheader("💰 基准设置")
    initial_portfolio = st.number_input(
        "初始资产金额 ($)",
        min_value=10_000,
        max_value=100_000_000,
        value=1_000_000,
        step=50_000,
        format="%d",
        key="sens_portfolio",
    )
    annual_withdrawal = st.number_input(
        "每年提取金额 ($, 实际购买力)",
        min_value=1_000,
        max_value=10_000_000,
        value=40_000,
        step=5_000,
        format="%d",
        key="sens_withdrawal",
    )

    st.subheader("📋 提取策略")
    strategy_label = st.radio(
        "选择提取策略",
        ["固定提取", "Vanguard 动态提取"],
        key="sens_strategy",
    )
    withdrawal_strategy = "fixed" if strategy_label == "固定提取" else "dynamic"

    dynamic_ceiling = 0.05
    dynamic_floor = 0.025
    if withdrawal_strategy == "dynamic":
        col_c, col_f = st.columns(2)
        with col_c:
            dynamic_ceiling = st.number_input(
                "最大上调 (%)", min_value=0.0, max_value=50.0,
                value=5.0, step=0.5, format="%.1f", key="sens_ceil",
            ) / 100.0
        with col_f:
            dynamic_floor = st.number_input(
                "最大下调 (%)", min_value=0.0, max_value=50.0,
                value=2.5, step=0.5, format="%.1f", key="sens_floor",
            ) / 100.0

    st.subheader("📊 资产配置 (%)")
    us_stock_pct = st.slider("美股 (US Stock)", 0, 100, 60, 5, key="sens_us")
    intl_stock_pct = st.slider("国际股票 (Intl Stock)", 0, 100, 10, 5, key="sens_intl")
    us_bond_pct = st.slider("美债 (US Bond)", 0, 100, 30, 5, key="sens_bond")

    total_pct = us_stock_pct + intl_stock_pct + us_bond_pct
    if total_pct != 100:
        st.error(f"资产配置总和必须为 100%，当前为 {total_pct}%")

    st.subheader("💸 费用率 (%)")
    us_stock_expense = st.number_input(
        "美股费用率", min_value=0.00, max_value=5.00, value=0.03,
        step=0.01, format="%.2f", key="sens_exp_us",
    )
    intl_stock_expense = st.number_input(
        "国际股票费用率", min_value=0.00, max_value=5.00, value=0.10,
        step=0.01, format="%.2f", key="sens_exp_intl",
    )
    us_bond_expense = st.number_input(
        "美债费用率", min_value=0.00, max_value=5.00, value=0.05,
        step=0.01, format="%.2f", key="sens_exp_bond",
    )

    st.subheader("⏳ 模拟设置")
    retirement_years = st.slider("退休年限", 10, 80, 40, 1, key="sens_years")

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        min_block = st.number_input("最小采样窗口", min_value=1, max_value=30, value=5, key="sens_minb")
    with col_b2:
        max_block = st.number_input("最大采样窗口", min_value=1, max_value=55, value=10, key="sens_maxb")

    if min_block > max_block:
        st.error("最小采样窗口不能大于最大采样窗口")

    num_simulations = st.slider("模拟次数", 1_000, 50_000, 5_000, 1_000, key="sens_nsim")

    st.subheader("🔍 扫描范围")
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        rate_max_pct = st.number_input(
            "最大提取率 (%)", min_value=1.0, max_value=30.0,
            value=12.0, step=1.0, format="%.1f", key="sens_rmax",
        )
    with col_r2:
        rate_step_pct = st.number_input(
            "扫描步长 (%)", min_value=0.05, max_value=2.0,
            value=0.1, step=0.05, format="%.2f", key="sens_rstep",
        )

    run_button = st.button("🚀 运行分析", type="primary", use_container_width=True, key="sens_run")

# ---------------------------------------------------------------------------
# 运行扫描
# ---------------------------------------------------------------------------
if run_button and total_pct == 100 and min_block <= max_block:
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

    with st.spinner("正在预生成回报序列..."):
        scenarios = pregenerate_return_scenarios(
            allocation=allocation,
            expense_ratios=expense_ratios,
            retirement_years=retirement_years,
            min_block=min_block,
            max_block=max_block,
            num_simulations=num_simulations,
            returns_df=returns_df,
        )

    with st.spinner("正在扫描提取率..."):
        rates, success_rates = sweep_withdrawal_rates(
            real_returns_matrix=scenarios,
            initial_portfolio=float(initial_portfolio),
            rate_min=0.0,
            rate_max=rate_max_pct / 100.0,
            rate_step=rate_step_pct / 100.0,
            withdrawal_strategy=withdrawal_strategy,
            dynamic_ceiling=dynamic_ceiling,
            dynamic_floor=dynamic_floor,
        )

    # 插值目标成功率
    target_rates = interpolate_targets(rates, success_rates, TARGET_SUCCESS_RATES)

    # ===================================================================
    # 分析 1：固定资产，不同成功率的提取率
    # ===================================================================
    st.header(f"分析 1：固定资产 ${initial_portfolio:,.0f}，不同成功率的提取率")

    col_chart1, col_table1 = st.columns([3, 2])

    with col_chart1:
        fig1 = go.Figure()

        fig1.add_trace(go.Scatter(
            x=rates * 100,
            y=success_rates * 100,
            mode="lines",
            line=dict(color="rgb(55, 126, 184)", width=2.5),
            name="成功率",
            hovertemplate="提取率: %{x:.2f}%<br>成功率: %{y:.1f}%<extra></extra>",
        ))

        # 标注当前提取率
        current_rate = annual_withdrawal / initial_portfolio * 100
        fig1.add_vline(
            x=current_rate, line_dash="dot", line_color="gray",
            annotation_text=f"当前: {current_rate:.1f}%",
            annotation_position="top",
        )

        # 标注关键成功率水平线
        for sr in [0.95, 0.90, 0.75]:
            fig1.add_hline(
                y=sr * 100, line_dash="dash", line_color="rgba(200,200,200,0.5)",
                annotation_text=f"{sr:.0%}",
                annotation_position="right",
            )

        fig1.update_layout(
            xaxis_title="初始提取率 (%)",
            yaxis_title="成功率 (%)",
            yaxis_range=[-2, 105],
            height=450,
            showlegend=False,
        )

        st.plotly_chart(fig1, use_container_width=True)

    with col_table1:
        rows1 = []
        for t, r in zip(TARGET_SUCCESS_RATES, target_rates):
            if r is not None:
                wd_amount = initial_portfolio * r
                rows1.append({
                    "目标成功率": f"{t:.0%}",
                    "提取率": f"{r * 100:.2f}%",
                    "年提取金额": f"${wd_amount:,.0f}",
                })
            else:
                rows1.append({
                    "目标成功率": f"{t:.0%}",
                    "提取率": "N/A",
                    "年提取金额": "N/A",
                })
        df1 = pd.DataFrame(rows1)
        st.dataframe(df1, hide_index=True, use_container_width=True, height=520)

    st.divider()

    # ===================================================================
    # 分析 2：固定提取金额，不同成功率的所需初始资产
    # ===================================================================
    st.header(f"分析 2：固定提取 ${annual_withdrawal:,.0f}/年，不同成功率的所需初始资产")

    col_chart2, col_table2 = st.columns([3, 2])

    with col_chart2:
        # 将提取率转换为所需资产 = annual_withdrawal / rate
        # 过滤掉 rate == 0 避免除零
        mask = rates > 0
        portfolio_needed = annual_withdrawal / rates[mask]
        sr_for_portfolio = success_rates[mask]

        fig2 = go.Figure()

        fig2.add_trace(go.Scatter(
            x=portfolio_needed,
            y=sr_for_portfolio * 100,
            mode="lines",
            line=dict(color="rgb(77, 175, 74)", width=2.5),
            name="成功率",
            hovertemplate="所需资产: $%{x:,.0f}<br>成功率: %{y:.1f}%<extra></extra>",
        ))

        # 标注当前资产
        fig2.add_vline(
            x=initial_portfolio, line_dash="dot", line_color="gray",
            annotation_text=f"当前: ${initial_portfolio:,.0f}",
            annotation_position="top",
        )

        for sr in [0.95, 0.90, 0.75]:
            fig2.add_hline(
                y=sr * 100, line_dash="dash", line_color="rgba(200,200,200,0.5)",
                annotation_text=f"{sr:.0%}",
                annotation_position="right",
            )

        fig2.update_layout(
            xaxis_title="所需初始资产 ($)",
            xaxis_tickformat="$,.0f",
            yaxis_title="成功率 (%)",
            yaxis_range=[-2, 105],
            height=450,
            showlegend=False,
        )

        st.plotly_chart(fig2, use_container_width=True)

    with col_table2:
        rows2 = []
        for t, r in zip(TARGET_SUCCESS_RATES, target_rates):
            if r is not None and r > 0:
                needed = annual_withdrawal / r
                rows2.append({
                    "目标成功率": f"{t:.0%}",
                    "所需初始资产": f"${needed:,.0f}",
                    "对应提取率": f"{r * 100:.2f}%",
                })
            else:
                rows2.append({
                    "目标成功率": f"{t:.0%}",
                    "所需初始资产": "N/A" if r is None else "无需资产",
                    "对应提取率": "N/A" if r is None else f"{r * 100:.2f}%",
                })
        df2 = pd.DataFrame(rows2)
        st.dataframe(df2, hide_index=True, use_container_width=True, height=520)

elif not run_button:
    st.info("👈 请在左侧设置参数，然后点击 **运行分析** 按钮开始。")
