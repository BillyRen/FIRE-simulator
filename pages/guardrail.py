"""Risk-based Guardrail 策略页面。"""

import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from simulator.data_loader import load_returns_data
from simulator.sweep import pregenerate_return_scenarios
from simulator.guardrail import (
    build_success_rate_table,
    run_guardrail_simulation,
    run_fixed_baseline,
)

# ---------------------------------------------------------------------------
# 页面配置
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Guardrail 策略 — FIRE 模拟器",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ Risk-based Guardrail 策略")
st.caption(
    "根据当前成功率动态调整提取金额，与固定提取基准对比"
)

# ---------------------------------------------------------------------------
# 加载数据
# ---------------------------------------------------------------------------

@st.cache_data
def get_returns_data():
    return load_returns_data()


returns_df = get_returns_data()

# ---------------------------------------------------------------------------
# 侧边栏 — 参数
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Guardrail 参数")

    st.subheader("💰 提取设置")
    annual_withdrawal = st.number_input(
        "每年提取金额 ($, 实际购买力)",
        min_value=1_000, max_value=10_000_000,
        value=40_000, step=5_000, format="%d",
        key="gr_withdrawal",
    )

    st.subheader("🛡️ 护栏设置")
    target_success_pct = st.number_input(
        "目标成功率 (%)",
        min_value=10.0, max_value=99.0,
        value=80.0, step=5.0, format="%.0f",
        key="gr_target",
        help="初始提取率基于此成功率计算，也是护栏调整的回归目标",
    )
    upper_guardrail_pct = st.number_input(
        "上护栏 (%)",
        min_value=50.0, max_value=100.0,
        value=99.0, step=1.0, format="%.0f",
        key="gr_upper",
        help="成功率高于此值时增加开支",
    )
    lower_guardrail_pct = st.number_input(
        "下护栏 (%)",
        min_value=0.0, max_value=99.0,
        value=50.0, step=5.0, format="%.0f",
        key="gr_lower",
        help="成功率低于此值时缩减开支",
    )
    adjustment_pct = st.number_input(
        "调整百分比 (%)",
        min_value=5.0, max_value=100.0,
        value=50.0, step=5.0, format="%.0f",
        key="gr_adj",
        help="100% = 完全调整到目标成功率对应的提取额，50% = 调整一半",
    )
    min_remaining = st.number_input(
        "剩余年限下限",
        min_value=5, max_value=30,
        value=10, step=1,
        key="gr_min_rem",
        help="计算成功率时的最小剩余年限",
    )

    st.subheader("📏 基准设置")
    baseline_rate_pct = st.number_input(
        "基准固定提取率 (%)",
        min_value=0.5, max_value=15.0,
        value=3.3, step=0.1, format="%.1f",
        key="gr_baseline",
    )

    st.subheader("📊 资产配置 (%)")
    us_stock_pct = st.slider("美股 (US Stock)", 0, 100, 60, 5, key="gr_us")
    intl_stock_pct = st.slider("国际股票 (Intl Stock)", 0, 100, 10, 5, key="gr_intl")
    us_bond_pct = st.slider("美债 (US Bond)", 0, 100, 30, 5, key="gr_bond")

    total_pct = us_stock_pct + intl_stock_pct + us_bond_pct
    if total_pct != 100:
        st.error(f"资产配置总和必须为 100%，当前为 {total_pct}%")

    st.subheader("💸 费用率 (%)")
    us_stock_expense = st.number_input(
        "美股费用率", min_value=0.00, max_value=5.00,
        value=0.03, step=0.01, format="%.2f", key="gr_exp_us",
    )
    intl_stock_expense = st.number_input(
        "国际股票费用率", min_value=0.00, max_value=5.00,
        value=0.10, step=0.01, format="%.2f", key="gr_exp_intl",
    )
    us_bond_expense = st.number_input(
        "美债费用率", min_value=0.00, max_value=5.00,
        value=0.05, step=0.01, format="%.2f", key="gr_exp_bond",
    )

    st.subheader("⏳ 模拟设置")
    retirement_years = st.slider("退休年限", 10, 80, 60, 1, key="gr_years")

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        min_block = st.number_input("最小采样窗口", min_value=1, max_value=30, value=5, key="gr_minb")
    with col_b2:
        max_block = st.number_input("最大采样窗口", min_value=1, max_value=55, value=10, key="gr_maxb")

    if min_block > max_block:
        st.error("最小采样窗口不能大于最大采样窗口")

    num_simulations = st.slider("模拟次数", 1_000, 50_000, 5_000, 1_000, key="gr_nsim")

    run_button = st.button("🚀 运行分析", type="primary", use_container_width=True, key="gr_run")

# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------
valid = (
    total_pct == 100
    and min_block <= max_block
    and lower_guardrail_pct < target_success_pct < upper_guardrail_pct
)

if run_button and not valid:
    if lower_guardrail_pct >= target_success_pct or target_success_pct >= upper_guardrail_pct:
        st.error("需满足：下护栏 < 目标成功率 < 上护栏")

# ---------------------------------------------------------------------------
# 运行模拟
# ---------------------------------------------------------------------------
if run_button and valid:
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

    target_success = target_success_pct / 100.0
    upper_guardrail = upper_guardrail_pct / 100.0
    lower_guardrail = lower_guardrail_pct / 100.0
    adj_pct = adjustment_pct / 100.0
    baseline_rate = baseline_rate_pct / 100.0

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

    with st.spinner("正在构建成功率查找表..."):
        rate_grid, table = build_success_rate_table(
            scenarios, rate_min=0.0, rate_max=0.20, rate_step=0.001,
        )

    with st.spinner("正在运行 Guardrail 模拟..."):
        init_portfolio, traj_g, wd_g = run_guardrail_simulation(
            scenarios=scenarios,
            annual_withdrawal=float(annual_withdrawal),
            target_success=target_success,
            upper_guardrail=upper_guardrail,
            lower_guardrail=lower_guardrail,
            adjustment_pct=adj_pct,
            retirement_years=retirement_years,
            min_remaining_years=min_remaining,
            table=table,
            rate_grid=rate_grid,
        )

    with st.spinner("正在运行基准模拟..."):
        traj_b, wd_b = run_fixed_baseline(
            scenarios, init_portfolio, baseline_rate, retirement_years,
        )

    # ===================================================================
    # 结果计算
    # ===================================================================
    g_success = float(np.mean(traj_g[:, -1] > 0))
    b_success = float(np.mean(traj_b[:, -1] > 0))

    initial_rate = annual_withdrawal / init_portfolio
    baseline_wd = init_portfolio * baseline_rate

    # 总消费额（每条路径的提取金额之和）
    g_total_consumption = np.sum(wd_g, axis=1)
    b_total_consumption = np.sum(wd_b, axis=1)

    # 每条路径的最低年消费
    # 只看非零年份（资产归零后不算）
    def min_nonzero_per_row(arr):
        result = np.full(arr.shape[0], np.nan)
        for i in range(arr.shape[0]):
            nonzero = arr[i, arr[i] > 0]
            if len(nonzero) > 0:
                result[i] = np.min(nonzero)
            else:
                result[i] = 0.0
        return result

    g_min_wd = min_nonzero_per_row(wd_g)
    b_min_wd = min_nonzero_per_row(wd_b)

    # ===================================================================
    # 顶部指标
    # ===================================================================
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("计算初始资产", f"${init_portfolio:,.0f}")
    with c2:
        st.metric("初始提取率", f"{initial_rate * 100:.2f}%")
    with c3:
        st.metric("Guardrail 成功率", f"{g_success:.1%}")
    with c4:
        st.metric("基准成功率", f"{b_success:.1%}",
                   delta=f"{(b_success - g_success):+.1%}" if b_success != g_success else None,
                   delta_color="normal")

    st.divider()

    # ===================================================================
    # 资产轨迹对比扇形图
    # ===================================================================
    st.subheader("资产轨迹对比")

    years = np.arange(retirement_years + 1)
    fig_asset = go.Figure()

    band_pairs = [(10, 90), (25, 75)]
    blue_ops = [0.15, 0.30]
    gray_ops = [0.08, 0.16]

    # Guardrail 区域
    for (p_low, p_high), opacity in zip(band_pairs, blue_ops):
        upper = np.percentile(traj_g, p_high, axis=0)
        lower = np.percentile(traj_g, p_low, axis=0)
        fig_asset.add_trace(go.Scatter(
            x=np.concatenate([years, years[::-1]]),
            y=np.concatenate([upper, lower[::-1]]),
            fill="toself",
            fillcolor=f"rgba(55, 126, 184, {opacity})",
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=True if opacity == blue_ops[0] else False,
            name=f"Guardrail P{p_low}-P{p_high}",
            hoverinfo="skip",
        ))

    # 基准区域
    for (p_low, p_high), opacity in zip(band_pairs, gray_ops):
        upper = np.percentile(traj_b, p_high, axis=0)
        lower = np.percentile(traj_b, p_low, axis=0)
        fig_asset.add_trace(go.Scatter(
            x=np.concatenate([years, years[::-1]]),
            y=np.concatenate([upper, lower[::-1]]),
            fill="toself",
            fillcolor=f"rgba(200, 100, 50, {opacity})",
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=True if opacity == gray_ops[0] else False,
            name=f"基准 P{p_low}-P{p_high}",
            hoverinfo="skip",
        ))

    # 中位数线
    fig_asset.add_trace(go.Scatter(
        x=years, y=np.median(traj_g, axis=0),
        mode="lines", line=dict(color="rgb(55, 126, 184)", width=2.5),
        name="Guardrail P50",
    ))
    fig_asset.add_trace(go.Scatter(
        x=years, y=np.median(traj_b, axis=0),
        mode="lines", line=dict(color="rgb(200, 100, 50)", width=2.5, dash="dash"),
        name="基准 P50",
    ))

    fig_asset.add_hline(y=0, line_dash="dash", line_color="red", opacity=0.4)
    fig_asset.update_layout(
        xaxis_title="退休第 N 年",
        yaxis_title="资产价值 ($, 实际购买力)",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_asset, use_container_width=True)

    # ===================================================================
    # 提取金额轨迹扇形图
    # ===================================================================
    st.subheader("提取金额轨迹对比")

    w_years = np.arange(1, retirement_years + 1)
    fig_wd = go.Figure()

    wd_ops = [0.15, 0.30]
    for (p_low, p_high), opacity in zip(band_pairs, wd_ops):
        upper = np.percentile(wd_g, p_high, axis=0)
        lower = np.percentile(wd_g, p_low, axis=0)
        fig_wd.add_trace(go.Scatter(
            x=np.concatenate([w_years, w_years[::-1]]),
            y=np.concatenate([upper, lower[::-1]]),
            fill="toself",
            fillcolor=f"rgba(55, 126, 184, {opacity})",
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=True if opacity == wd_ops[0] else False,
            name=f"Guardrail P{p_low}-P{p_high}",
            hoverinfo="skip",
        ))

    # Guardrail 中位数线
    fig_wd.add_trace(go.Scatter(
        x=w_years, y=np.median(wd_g, axis=0),
        mode="lines", line=dict(color="rgb(55, 126, 184)", width=2.5),
        name="Guardrail P50",
    ))

    # 基准固定金额参考线
    fig_wd.add_hline(
        y=baseline_wd, line_dash="dot", line_color="rgb(200, 100, 50)", opacity=0.8,
        annotation_text=f"基准固定: ${baseline_wd:,.0f}",
        annotation_position="bottom right",
    )
    # 初始提取金额参考线
    fig_wd.add_hline(
        y=annual_withdrawal, line_dash="dash", line_color="gray", opacity=0.6,
        annotation_text=f"初始提取: ${annual_withdrawal:,.0f}",
        annotation_position="top right",
    )

    fig_wd.update_layout(
        xaxis_title="退休第 N 年",
        yaxis_title="年度提取金额 ($, 实际购买力)",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_wd, use_container_width=True)

    # ===================================================================
    # 关键指标对比表格
    # ===================================================================
    st.subheader("关键指标对比")

    g_p10_min = float(np.percentile(g_min_wd, 10))
    b_p10_min = float(np.percentile(b_min_wd, 10))

    metrics = [
        {
            "指标": "成功率",
            "Guardrail": f"{g_success:.1%}",
            "基准固定": f"{b_success:.1%}",
        },
        {
            "指标": "初始年提取额",
            "Guardrail": f"${annual_withdrawal:,.0f}",
            "基准固定": f"${baseline_wd:,.0f}",
        },
        {
            "指标": "中位数总消费额",
            "Guardrail": f"${np.median(g_total_consumption):,.0f}",
            "基准固定": f"${np.median(b_total_consumption):,.0f}",
        },
        {
            "指标": "中位数最终资产",
            "Guardrail": f"${np.median(traj_g[:, -1]):,.0f}",
            "基准固定": f"${np.median(traj_b[:, -1]):,.0f}",
        },
        {
            "指标": "P10 最低年度消费",
            "Guardrail": f"${g_p10_min:,.0f}",
            "基准固定": f"${b_p10_min:,.0f}",
        },
        {
            "指标": "P10 最低消费 vs 初始提取额",
            "Guardrail": f"{(g_p10_min / annual_withdrawal - 1) * 100:+.1f}%",
            "基准固定": f"{(b_p10_min / baseline_wd - 1) * 100:+.1f}%" if b_p10_min > 0 else "N/A (破产)",
        },
        {
            "指标": "中位数最终年提取额",
            "Guardrail": f"${np.median(wd_g[:, -1]):,.0f}",
            "基准固定": f"${baseline_wd:,.0f}",
        },
    ]

    st.dataframe(pd.DataFrame(metrics), hide_index=True, use_container_width=True)

    # ===================================================================
    # 补充说明
    # ===================================================================
    with st.expander("📖 策略说明"):
        st.markdown(f"""
**Risk-based Guardrail 策略原理**

1. 根据目标成功率 ({target_success_pct:.0f}%) 和退休年限 ({retirement_years} 年)
   计算出初始资产为 **${init_portfolio:,.0f}**，初始提取率为 **{initial_rate*100:.2f}%**
2. 每年检查当前成功率（基于剩余年限，最少 {min_remaining} 年）：
   - 若成功率 **< {lower_guardrail_pct:.0f}%** (下护栏)：缩减开支，调整幅度为目标所需的 {adjustment_pct:.0f}%
   - 若成功率 **> {upper_guardrail_pct:.0f}%** (上护栏)：增加开支，调整幅度为目标所需的 {adjustment_pct:.0f}%
   - 否则：保持当前提取额不变

**基准对比**：固定 {baseline_rate_pct:.1f}% 提取率，相同初始资产 ${init_portfolio:,.0f}，
年提取 ${baseline_wd:,.0f}。
        """)

elif not run_button:
    st.info("👈 请在左侧设置参数，然后点击 **运行分析** 按钮开始。")
