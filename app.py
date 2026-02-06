"""FIRE 蒙特卡洛退休模拟器 — Streamlit 应用。"""

import streamlit as st
import numpy as np
import plotly.graph_objects as go

from simulator.data_loader import load_returns_data
from simulator.monte_carlo import run_simulation
from simulator.statistics import (
    PERCENTILES,
    compute_statistics,
    final_values_summary_table,
)

# ---------------------------------------------------------------------------
# 页面配置
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="FIRE 退休模拟器",
    page_icon="🔥",
    layout="wide",
)

st.title("🔥 FIRE 蒙特卡洛退休模拟器")
st.caption("基于历史回报数据的 Block Bootstrap 蒙特卡洛模拟")

# ---------------------------------------------------------------------------
# 加载数据
# ---------------------------------------------------------------------------

@st.cache_data
def get_returns_data():
    return load_returns_data()


returns_df = get_returns_data()

# ---------------------------------------------------------------------------
# 侧边栏 — 用户参数
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("模拟参数")

    st.subheader("💰 资产与提取")
    initial_portfolio = st.number_input(
        "初始资产金额 ($)",
        min_value=10_000,
        max_value=100_000_000,
        value=1_000_000,
        step=50_000,
        format="%d",
    )
    annual_withdrawal = st.number_input(
        "每年提取金额 ($, 实际购买力)",
        min_value=0,
        max_value=10_000_000,
        value=40_000,
        step=5_000,
        format="%d",
    )

    st.subheader("📋 提取策略")
    strategy_label = st.radio(
        "选择提取策略",
        ["固定提取", "Vanguard 动态提取"],
        help=(
            "固定提取：每年提取固定的实际金额。\n\n"
            "Vanguard 动态提取：按初始提取率动态调整提取金额，"
            "但每年调整幅度受上下限约束。"
        ),
    )
    withdrawal_strategy = "fixed" if strategy_label == "固定提取" else "dynamic"

    # 动态提取参数
    dynamic_ceiling = 0.05
    dynamic_floor = 0.025
    if withdrawal_strategy == "dynamic":
        col_ceil, col_floor = st.columns(2)
        with col_ceil:
            dynamic_ceiling = st.number_input(
                "最大上调 (%)",
                min_value=0.0,
                max_value=50.0,
                value=5.0,
                step=0.5,
                format="%.1f",
                help="每年提取金额相对上一年最多上调的百分比",
            ) / 100.0
        with col_floor:
            dynamic_floor = st.number_input(
                "最大下调 (%)",
                min_value=0.0,
                max_value=50.0,
                value=2.5,
                step=0.5,
                format="%.1f",
                help="每年提取金额相对上一年最多下调的百分比",
            ) / 100.0

    st.subheader("📊 资产配置 (%)")
    us_stock_pct = st.slider("美股 (US Stock)", 0, 100, 60, 5)
    intl_stock_pct = st.slider("国际股票 (Intl Stock)", 0, 100, 10, 5)
    us_bond_pct = st.slider("美债 (US Bond)", 0, 100, 30, 5)

    total_pct = us_stock_pct + intl_stock_pct + us_bond_pct
    if total_pct != 100:
        st.error(f"资产配置总和必须为 100%，当前为 {total_pct}%")

    st.subheader("💸 费用率 (%)")
    us_stock_expense = st.number_input(
        "美股费用率", min_value=0.00, max_value=5.00, value=0.03, step=0.01, format="%.2f"
    )
    intl_stock_expense = st.number_input(
        "国际股票费用率", min_value=0.00, max_value=5.00, value=0.10, step=0.01, format="%.2f"
    )
    us_bond_expense = st.number_input(
        "美债费用率", min_value=0.00, max_value=5.00, value=0.05, step=0.01, format="%.2f"
    )

    st.subheader("⏳ 模拟设置")
    retirement_years = st.slider("退休年限", 10, 80, 40, 1)

    col_block1, col_block2 = st.columns(2)
    with col_block1:
        min_block = st.number_input("最小采样窗口", min_value=1, max_value=30, value=5)
    with col_block2:
        max_block = st.number_input("最大采样窗口", min_value=1, max_value=55, value=10)

    if min_block > max_block:
        st.error("最小采样窗口不能大于最大采样窗口")

    num_simulations = st.slider("模拟次数", 1_000, 50_000, 10_000, 1_000)

    run_button = st.button("🚀 运行模拟", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# 运行模拟
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

    with st.spinner("正在运行蒙特卡洛模拟..."):
        trajectories, withdrawals = run_simulation(
            initial_portfolio=float(initial_portfolio),
            annual_withdrawal=float(annual_withdrawal),
            allocation=allocation,
            expense_ratios=expense_ratios,
            retirement_years=retirement_years,
            min_block=min_block,
            max_block=max_block,
            num_simulations=num_simulations,
            returns_df=returns_df,
            withdrawal_strategy=withdrawal_strategy,
            dynamic_ceiling=dynamic_ceiling,
            dynamic_floor=dynamic_floor,
        )

        results = compute_statistics(trajectories, retirement_years, withdrawals)

    # -------------------------------------------------------------------
    # 结果展示
    # -------------------------------------------------------------------

    # 顶部指标卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("成功率", f"{results.success_rate:.1%}")
    with col2:
        st.metric("中位数最终资产", f"${results.final_median:,.0f}")
    with col3:
        st.metric("平均最终资产", f"${results.final_mean:,.0f}")
    with col4:
        withdrawal_rate = annual_withdrawal / initial_portfolio * 100
        st.metric("初始提取率", f"{withdrawal_rate:.1f}%")

    st.divider()

    # -------------------------------------------------------------------
    # 资产轨迹扇形图 (Fan Chart)
    # -------------------------------------------------------------------
    st.subheader("资产轨迹扇形图")

    years = np.arange(retirement_years + 1)
    fig_fan = go.Figure()

    # 渐变填充：从外层到内层
    band_pairs = [(5, 95), (10, 90), (25, 75)]
    opacities = [0.15, 0.25, 0.35]

    for (p_low, p_high), opacity in zip(band_pairs, opacities):
        upper = results.percentile_trajectories[p_high]
        lower = results.percentile_trajectories[p_low]
        color = f"rgba(55, 126, 184, {opacity})"

        fig_fan.add_trace(go.Scatter(
            x=np.concatenate([years, years[::-1]]),
            y=np.concatenate([upper, lower[::-1]]),
            fill="toself",
            fillcolor=color,
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=True,
            name=f"P{p_low}-P{p_high}",
            hoverinfo="skip",
        ))

    # 中位数线
    fig_fan.add_trace(go.Scatter(
        x=years,
        y=results.percentile_trajectories[50],
        mode="lines",
        line=dict(color="rgb(55, 126, 184)", width=2.5),
        name="中位数 (P50)",
    ))

    # 零线
    fig_fan.add_hline(y=0, line_dash="dash", line_color="red", opacity=0.5)

    fig_fan.update_layout(
        xaxis_title="退休第 N 年",
        yaxis_title="资产价值 ($, 实际购买力)",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    st.plotly_chart(fig_fan, use_container_width=True)

    # -------------------------------------------------------------------
    # 提取金额轨迹扇形图（动态策略时显示）
    # -------------------------------------------------------------------
    if withdrawal_strategy == "dynamic" and results.withdrawal_percentile_trajectories is not None:
        st.subheader("提取金额轨迹扇形图")

        w_years = np.arange(1, retirement_years + 1)
        fig_w = go.Figure()

        for (p_low, p_high), opacity in zip(band_pairs, opacities):
            upper = results.withdrawal_percentile_trajectories[p_high]
            lower = results.withdrawal_percentile_trajectories[p_low]
            color = f"rgba(228, 120, 51, {opacity})"

            fig_w.add_trace(go.Scatter(
                x=np.concatenate([w_years, w_years[::-1]]),
                y=np.concatenate([upper, lower[::-1]]),
                fill="toself",
                fillcolor=color,
                line=dict(color="rgba(255,255,255,0)"),
                showlegend=True,
                name=f"P{p_low}-P{p_high}",
                hoverinfo="skip",
            ))

        # 中位数线
        fig_w.add_trace(go.Scatter(
            x=w_years,
            y=results.withdrawal_percentile_trajectories[50],
            mode="lines",
            line=dict(color="rgb(228, 120, 51)", width=2.5),
            name="中位数 (P50)",
        ))

        # 初始提取金额参考线
        fig_w.add_hline(
            y=annual_withdrawal, line_dash="dot", line_color="gray", opacity=0.6,
            annotation_text=f"初始提取: ${annual_withdrawal:,.0f}",
            annotation_position="bottom right",
        )

        fig_w.update_layout(
            xaxis_title="退休第 N 年",
            yaxis_title="年度提取金额 ($, 实际购买力)",
            yaxis_tickformat="$,.0f",
            hovermode="x unified",
            height=400,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        st.plotly_chart(fig_w, use_container_width=True)

    # -------------------------------------------------------------------
    # 最终资产分布直方图 + 统计摘要表格
    # -------------------------------------------------------------------
    col_hist, col_table = st.columns([3, 2])

    with col_hist:
        st.subheader("最终资产分布")

        fig_hist = go.Figure()
        fig_hist.add_trace(go.Histogram(
            x=results.final_values,
            nbinsx=80,
            marker_color="rgba(55, 126, 184, 0.7)",
            marker_line=dict(color="rgba(55, 126, 184, 1)", width=0.5),
            name="最终资产",
        ))

        # 标注关键分位数
        for p in [10, 50, 90]:
            val = results.final_percentiles[p]
            fig_hist.add_vline(
                x=val,
                line_dash="dash",
                line_color="red" if p == 10 else ("green" if p == 50 else "orange"),
                annotation_text=f"P{p}: ${val:,.0f}",
                annotation_position="top",
            )

        fig_hist.update_layout(
            xaxis_title="最终资产价值 ($, 实际购买力)",
            xaxis_tickformat="$,.0f",
            yaxis_title="模拟次数",
            height=400,
            showlegend=False,
        )

        st.plotly_chart(fig_hist, use_container_width=True)

    # -------------------------------------------------------------------
    # 统计摘要表格
    # -------------------------------------------------------------------
    with col_table:
        st.subheader("统计摘要")
        summary_df = final_values_summary_table(results)
        st.dataframe(summary_df, hide_index=True, use_container_width=True)

    # -------------------------------------------------------------------
    # 原始数据概览
    # -------------------------------------------------------------------
    with st.expander("📄 历史回报数据预览"):
        st.dataframe(returns_df, use_container_width=True)

elif not run_button:
    st.info("👈 请在左侧设置参数，然后点击 **运行模拟** 按钮开始。")
