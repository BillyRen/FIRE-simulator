"""Risk-based Guardrail 策略页面。"""

import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from simulator.data_loader import load_returns_data
from simulator.portfolio import compute_real_portfolio_returns
from simulator.sweep import pregenerate_return_scenarios
from simulator.config import GUARDRAIL_RATE_MIN, GUARDRAIL_RATE_MAX, GUARDRAIL_RATE_STEP
from simulator.ui_common import (
    sidebar_data_range,
    sidebar_allocation,
    sidebar_simulation_settings,
    sidebar_cash_flows,
    filter_returns,
)
from simulator.guardrail import (
    build_success_rate_table,
    run_guardrail_simulation,
    run_fixed_baseline,
    run_historical_backtest,
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

    data_start_year = sidebar_data_range(returns_df, key_prefix="gr_")

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
    adj_mode_label = st.radio(
        "调整模式",
        ["金额调整", "成功率调整"],
        key="gr_adj_mode",
        help=(
            "金额调整：按提取金额差额的百分比调整（如需调整 $100，50% = 调整 $50）。\n\n"
            "成功率调整：按成功率差距的百分比调整（如当前 10%、目标 80%，50% = 调整到 45% 对应的提取额）。"
        ),
    )
    adjustment_mode = "amount" if adj_mode_label == "金额调整" else "success_rate"

    adjustment_pct = st.number_input(
        "调整百分比 (%)",
        min_value=5.0, max_value=100.0,
        value=50.0, step=5.0, format="%.0f",
        key="gr_adj",
        help=(
            "金额调整模式：100% = 完全调整到目标成功率对应的提取额，50% = 调整一半差额。\n\n"
            "成功率调整模式：100% = 完全调整到目标成功率，50% = 调整一半成功率差距。"
        ),
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

    allocation, expense_ratios, total_pct = sidebar_allocation(key_prefix="gr_")

    retirement_years, min_block, max_block, num_simulations = sidebar_simulation_settings(
        key_prefix="gr_", default_nsim=5_000,
    )

    cash_flows = sidebar_cash_flows(key_prefix="gr_")

    st.subheader("📜 历史回测")
    available_hist_years = sorted(
        returns_df[returns_df["Year"] >= data_start_year]["Year"].tolist()
    )
    hist_start_year = st.selectbox(
        "回测起始年",
        options=available_hist_years,
        index=(
            available_hist_years.index(1990)
            if 1990 in available_hist_years
            else len(available_hist_years) // 2
        ),
        key="gr_hist_start",
        help="从该年开始使用真实历史回报进行回测",
    )

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
filtered_df = filter_returns(returns_df, data_start_year, retirement_years)

if run_button and valid:
    target_success = target_success_pct / 100.0
    upper_guardrail = upper_guardrail_pct / 100.0
    lower_guardrail = lower_guardrail_pct / 100.0
    adj_pct = adjustment_pct / 100.0
    baseline_rate = baseline_rate_pct / 100.0

    with st.spinner("正在预生成回报序列..."):
        scenarios, inflation_matrix = pregenerate_return_scenarios(
            allocation=allocation,
            expense_ratios=expense_ratios,
            retirement_years=retirement_years,
            min_block=min_block,
            max_block=max_block,
            num_simulations=num_simulations,
            returns_df=filtered_df,
        )

    with st.spinner("正在构建成功率查找表..."):
        rate_grid, table = build_success_rate_table(
            scenarios,
            rate_min=GUARDRAIL_RATE_MIN,
            rate_max=GUARDRAIL_RATE_MAX,
            rate_step=GUARDRAIL_RATE_STEP,
        )

    cf_arg = cash_flows if cash_flows else None

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
            adjustment_mode=adjustment_mode,
            cash_flows=cf_arg,
            inflation_matrix=inflation_matrix,
        )

    with st.spinner("正在运行基准模拟..."):
        traj_b, wd_b = run_fixed_baseline(
            scenarios, init_portfolio, baseline_rate, retirement_years,
            cash_flows=cf_arg,
            inflation_matrix=inflation_matrix,
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

    # 每条路径的最低年消费（向量化版本）
    def min_nonzero_per_row(arr: np.ndarray) -> np.ndarray:
        mask = arr > 0
        filled = np.where(mask, arr, np.inf)
        return np.where(mask.any(axis=1), np.min(filled, axis=1), 0.0)

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
   - 若成功率 **< {lower_guardrail_pct:.0f}%** (下护栏)：缩减开支
   - 若成功率 **> {upper_guardrail_pct:.0f}%** (上护栏)：增加开支
   - 否则：保持当前提取额不变
   - 调整模式：**{"金额调整" if adjustment_mode == "amount" else "成功率调整"}**，调整比例 {adjustment_pct:.0f}%
     {"（按提取金额差额的百分比调整）" if adjustment_mode == "amount" else "（按成功率差距的百分比调整到中间目标成功率）"}

**基准对比**：固定 {baseline_rate_pct:.1f}% 提取率，相同初始资产 ${init_portfolio:,.0f}，
年提取 ${baseline_wd:,.0f}。
        """)

    # ===================================================================
    # 历史真实回测
    # ===================================================================
    st.divider()
    st.header(f"📜 历史回测：从 {hist_start_year} 年开始")

    # 获取从起始年开始的历史数据
    hist_mask = filtered_df["Year"] >= hist_start_year
    hist_df = filtered_df[hist_mask].reset_index(drop=True)
    hist_real_returns = compute_real_portfolio_returns(hist_df, allocation, expense_ratios)
    hist_inflation_series = hist_df["US Inflation"].values
    hist_years_available = len(hist_real_returns)

    if hist_years_available < retirement_years:
        st.warning(
            f"从 {hist_start_year} 年开始仅有 {hist_years_available} 年数据"
            f"（退休年限设为 {retirement_years} 年），回测将截断至 {hist_years_available} 年。"
        )

    hist = run_historical_backtest(
        real_returns=hist_real_returns,
        initial_portfolio=init_portfolio,
        annual_withdrawal=float(annual_withdrawal),
        target_success=target_success,
        upper_guardrail=upper_guardrail,
        lower_guardrail=lower_guardrail,
        adjustment_pct=adj_pct,
        retirement_years=retirement_years,
        min_remaining_years=min_remaining,
        baseline_rate=baseline_rate,
        table=table,
        rate_grid=rate_grid,
        adjustment_mode=adjustment_mode,
        cash_flows=cf_arg,
        inflation_series=hist_inflation_series,
    )

    n_hist = hist["years_simulated"]
    year_axis = np.array([hist_start_year + i for i in range(n_hist + 1)])
    year_axis_wd = year_axis[:-1]  # 提取金额对应的年份（无初始年）

    # --- 顶部指标 ---
    hc1, hc2, hc3, hc4 = st.columns(4)
    with hc1:
        g_final = hist["g_portfolio"][-1]
        st.metric("Guardrail 最终资产", f"${g_final:,.0f}")
    with hc2:
        b_final = hist["b_portfolio"][-1]
        st.metric("基准最终资产", f"${b_final:,.0f}")
    with hc3:
        st.metric("Guardrail 总消费", f"${hist['g_total_consumption']:,.0f}")
    with hc4:
        st.metric("基准总消费", f"${hist['b_total_consumption']:,.0f}")

    # --- 资产轨迹对比 ---
    st.subheader("历史资产轨迹对比")
    fig_h_asset = go.Figure()

    fig_h_asset.add_trace(go.Scatter(
        x=year_axis, y=hist["g_portfolio"],
        mode="lines+markers", marker=dict(size=4),
        line=dict(color="rgb(55, 126, 184)", width=2.5),
        name="Guardrail",
        hovertemplate="年份: %{x}<br>资产: $%{y:,.0f}<extra></extra>",
    ))
    fig_h_asset.add_trace(go.Scatter(
        x=year_axis, y=hist["b_portfolio"],
        mode="lines+markers", marker=dict(size=4),
        line=dict(color="rgb(200, 100, 50)", width=2.5, dash="dash"),
        name="基准固定",
        hovertemplate="年份: %{x}<br>资产: $%{y:,.0f}<extra></extra>",
    ))

    fig_h_asset.add_hline(y=0, line_dash="dash", line_color="red", opacity=0.4)
    fig_h_asset.update_layout(
        xaxis_title="年份",
        yaxis_title="资产价值 ($, 实际购买力)",
        yaxis_tickformat="$,.0f",
        hovermode="x unified",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_h_asset, use_container_width=True)

    # --- 提取金额 + 成功率对比 ---
    st.subheader("历史提取金额与成功率")

    from plotly.subplots import make_subplots

    fig_h_wd = make_subplots(specs=[[{"secondary_y": True}]])

    # 成功率区域（背景）
    fig_h_wd.add_trace(go.Scatter(
        x=year_axis_wd, y=hist["g_success_rates"] * 100,
        mode="lines",
        line=dict(color="rgba(150, 150, 150, 0.5)", width=1),
        fill="tozeroy",
        fillcolor="rgba(150, 150, 150, 0.1)",
        name="成功率",
        hovertemplate="年份: %{x}<br>成功率: %{y:.1f}%<extra></extra>",
    ), secondary_y=True)

    # 护栏参考线
    fig_h_wd.add_hline(
        y=upper_guardrail * 100, line_dash="dot",
        line_color="rgba(100, 180, 100, 0.5)",
        annotation_text=f"上护栏 {upper_guardrail_pct:.0f}%",
        annotation_position="right",
        secondary_y=True,
    )
    fig_h_wd.add_hline(
        y=lower_guardrail * 100, line_dash="dot",
        line_color="rgba(220, 100, 100, 0.5)",
        annotation_text=f"下护栏 {lower_guardrail_pct:.0f}%",
        annotation_position="right",
        secondary_y=True,
    )

    # Guardrail 提取金额
    fig_h_wd.add_trace(go.Scatter(
        x=year_axis_wd, y=hist["g_withdrawals"],
        mode="lines+markers", marker=dict(size=4),
        line=dict(color="rgb(55, 126, 184)", width=2.5),
        name="Guardrail 提取",
        hovertemplate="年份: %{x}<br>提取: $%{y:,.0f}<extra></extra>",
    ), secondary_y=False)

    # 基准固定提取参考线
    fig_h_wd.add_trace(go.Scatter(
        x=year_axis_wd, y=hist["b_withdrawals"],
        mode="lines",
        line=dict(color="rgb(200, 100, 50)", width=2, dash="dash"),
        name="基准固定提取",
        hovertemplate="年份: %{x}<br>提取: $%{y:,.0f}<extra></extra>",
    ), secondary_y=False)

    fig_h_wd.update_layout(
        xaxis_title="年份",
        hovermode="x unified",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig_h_wd.update_yaxes(
        title_text="年度提取金额 ($, 实际购买力)",
        tickformat="$,.0f",
        secondary_y=False,
    )
    fig_h_wd.update_yaxes(
        title_text="成功率 (%)",
        range=[0, 105],
        secondary_y=True,
    )

    st.plotly_chart(fig_h_wd, use_container_width=True)

    # --- 逐年明细表格 ---
    with st.expander("📋 逐年明细表格"):
        detail_rows = []
        for y in range(n_hist):
            detail_rows.append({
                "年份": int(hist_start_year + y),
                "Guardrail 资产": f"${hist['g_portfolio'][y]:,.0f}",
                "Guardrail 提取": f"${hist['g_withdrawals'][y]:,.0f}",
                "成功率": f"{hist['g_success_rates'][y] * 100:.1f}%",
                "基准资产": f"${hist['b_portfolio'][y]:,.0f}",
                "基准提取": f"${hist['b_withdrawals'][y]:,.0f}",
            })
        # 最终年资产
        detail_rows.append({
            "年份": int(hist_start_year + n_hist),
            "Guardrail 资产": f"${hist['g_portfolio'][-1]:,.0f}",
            "Guardrail 提取": "—",
            "成功率": "—",
            "基准资产": f"${hist['b_portfolio'][-1]:,.0f}",
            "基准提取": "—",
        })
        st.dataframe(pd.DataFrame(detail_rows), hide_index=True, use_container_width=True)

elif not run_button:
    st.info("👈 请在左侧设置参数，然后点击 **运行分析** 按钮开始。")
