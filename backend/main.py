"""FastAPI 后端 — 包装 simulator 计算引擎，提供 REST API。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# 确保 simulator 包可被导入（项目根目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulator.cashflow import CashFlowItem
from simulator.config import (
    GUARDRAIL_RATE_MAX,
    GUARDRAIL_RATE_MIN,
    GUARDRAIL_RATE_STEP,
    TARGET_SUCCESS_RATES,
)
from simulator.data_loader import load_returns_data
from simulator.guardrail import (
    build_success_rate_table,
    run_fixed_baseline,
    run_guardrail_simulation,
    run_historical_backtest,
)
from simulator.monte_carlo import run_simulation
from simulator.portfolio import compute_real_portfolio_returns
from simulator.statistics import PERCENTILES, compute_statistics, final_values_summary_table
from simulator.sweep import (
    interpolate_targets,
    pregenerate_return_scenarios,
    sweep_withdrawal_rates,
)

from schemas import (
    BacktestRequest,
    BacktestResponse,
    GuardrailRequest,
    GuardrailResponse,
    ReturnsResponse,
    SimulationRequest,
    SimulationResponse,
    SweepRequest,
    SweepResponse,
    TargetRateResult,
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="FIRE 退休模拟器 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局缓存
_returns_df = None


def _get_returns_df():
    global _returns_df
    if _returns_df is None:
        _returns_df = load_returns_data()
    return _returns_df


def _filter_df(data_start_year: int):
    df = _get_returns_df()
    return df[df["Year"] >= data_start_year].reset_index(drop=True)


def _to_cash_flows(items) -> list[CashFlowItem] | None:
    if not items:
        return None
    return [
        CashFlowItem(
            name=cf.name,
            amount=cf.amount,
            start_year=cf.start_year,
            duration=cf.duration,
            inflation_adjusted=cf.inflation_adjusted,
        )
        for cf in items
    ]


def _alloc_dict(a) -> dict[str, float]:
    return {"us_stock": a.us_stock, "intl_stock": a.intl_stock, "us_bond": a.us_bond}


def _expense_dict(e) -> dict[str, float]:
    return {"us_stock": e.us_stock, "intl_stock": e.intl_stock, "us_bond": e.us_bond}


# ---------------------------------------------------------------------------
# 1. POST /api/simulate
# ---------------------------------------------------------------------------

@app.post("/api/simulate", response_model=SimulationResponse)
def api_simulate(req: SimulationRequest):
    filtered = _filter_df(req.data_start_year)
    if len(filtered) < 2:
        raise HTTPException(400, "可用数据不足")

    trajectories, withdrawals = run_simulation(
        initial_portfolio=req.initial_portfolio,
        annual_withdrawal=req.annual_withdrawal,
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        retirement_years=req.retirement_years,
        min_block=req.min_block,
        max_block=req.max_block,
        num_simulations=req.num_simulations,
        returns_df=filtered,
        withdrawal_strategy=req.withdrawal_strategy,
        dynamic_ceiling=req.dynamic_ceiling,
        dynamic_floor=req.dynamic_floor,
        cash_flows=_to_cash_flows(req.cash_flows),
    )

    results = compute_statistics(trajectories, req.retirement_years, withdrawals)
    summary_df = final_values_summary_table(results)

    # 序列化
    pct_traj = {str(k): v.tolist() for k, v in results.percentile_trajectories.items()}
    final_pcts = {str(k): v for k, v in results.final_percentiles.items()}

    wd_pct_traj = None
    wd_mean_traj = None
    if results.withdrawal_percentile_trajectories is not None:
        wd_pct_traj = {
            str(k): v.tolist() for k, v in results.withdrawal_percentile_trajectories.items()
        }
    if results.withdrawal_mean_trajectory is not None:
        wd_mean_traj = results.withdrawal_mean_trajectory.tolist()

    return SimulationResponse(
        success_rate=results.success_rate,
        final_median=results.final_median,
        final_mean=results.final_mean,
        final_min=results.final_min,
        final_max=results.final_max,
        final_percentiles=final_pcts,
        percentile_trajectories=pct_traj,
        withdrawal_percentile_trajectories=wd_pct_traj,
        withdrawal_mean_trajectory=wd_mean_traj,
        final_values_summary=summary_df.to_dict("records"),
        initial_withdrawal_rate=(
            req.annual_withdrawal / req.initial_portfolio if req.initial_portfolio > 0 else 0
        ),
    )


# ---------------------------------------------------------------------------
# 2. POST /api/sweep
# ---------------------------------------------------------------------------

@app.post("/api/sweep", response_model=SweepResponse)
def api_sweep(req: SweepRequest):
    filtered = _filter_df(req.data_start_year)
    if len(filtered) < 2:
        raise HTTPException(400, "可用数据不足")

    scenarios, inflation_matrix = pregenerate_return_scenarios(
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        retirement_years=req.retirement_years,
        min_block=req.min_block,
        max_block=req.max_block,
        num_simulations=req.num_simulations,
        returns_df=filtered,
    )

    cash_flows = _to_cash_flows(req.cash_flows)

    rates, success_rates = sweep_withdrawal_rates(
        real_returns_matrix=scenarios,
        initial_portfolio=req.initial_portfolio,
        rate_min=0.0,
        rate_max=req.rate_max,
        rate_step=req.rate_step,
        withdrawal_strategy=req.withdrawal_strategy,
        dynamic_ceiling=req.dynamic_ceiling,
        dynamic_floor=req.dynamic_floor,
        cash_flows=cash_flows,
        inflation_matrix=inflation_matrix,
    )

    target_rates = interpolate_targets(rates, success_rates, TARGET_SUCCESS_RATES)

    target_results = []
    for t, r in zip(TARGET_SUCCESS_RATES, target_rates):
        if r is not None and r > 0:
            target_results.append(TargetRateResult(
                target_success=f"{t:.0%}",
                rate=f"{r * 100:.2f}%",
                annual_withdrawal=f"${req.initial_portfolio * r:,.0f}",
                needed_portfolio=f"${req.annual_withdrawal / r:,.0f}",
            ))
        else:
            target_results.append(TargetRateResult(
                target_success=f"{t:.0%}",
                rate=None,
                annual_withdrawal=None,
                needed_portfolio=None,
            ))

    return SweepResponse(
        rates=rates.tolist(),
        success_rates=success_rates.tolist(),
        target_results=target_results,
    )


# ---------------------------------------------------------------------------
# 3. POST /api/guardrail
# ---------------------------------------------------------------------------

@app.post("/api/guardrail", response_model=GuardrailResponse)
def api_guardrail(req: GuardrailRequest):
    filtered = _filter_df(req.data_start_year)
    if len(filtered) < 2:
        raise HTTPException(400, "可用数据不足")

    scenarios, inflation_matrix = pregenerate_return_scenarios(
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        retirement_years=req.retirement_years,
        min_block=req.min_block,
        max_block=req.max_block,
        num_simulations=req.num_simulations,
        returns_df=filtered,
    )

    rate_grid, table = build_success_rate_table(
        scenarios, GUARDRAIL_RATE_MIN, GUARDRAIL_RATE_MAX, GUARDRAIL_RATE_STEP,
    )

    cash_flows = _to_cash_flows(req.cash_flows)

    init_portfolio, traj_g, wd_g = run_guardrail_simulation(
        scenarios=scenarios,
        annual_withdrawal=req.annual_withdrawal,
        target_success=req.target_success,
        upper_guardrail=req.upper_guardrail,
        lower_guardrail=req.lower_guardrail,
        adjustment_pct=req.adjustment_pct,
        retirement_years=req.retirement_years,
        min_remaining_years=req.min_remaining_years,
        table=table,
        rate_grid=rate_grid,
        adjustment_mode=req.adjustment_mode,
        cash_flows=cash_flows,
        inflation_matrix=inflation_matrix,
    )

    traj_b, wd_b = run_fixed_baseline(
        scenarios, init_portfolio, req.baseline_rate, req.retirement_years,
        cash_flows=cash_flows, inflation_matrix=inflation_matrix,
    )

    g_success = float(np.mean(traj_g[:, -1] > 0))
    b_success = float(np.mean(traj_b[:, -1] > 0))
    initial_rate = req.annual_withdrawal / init_portfolio if init_portfolio > 0 else 0
    baseline_wd = init_portfolio * req.baseline_rate

    # 分位数轨迹
    band_pcts = [10, 25, 50, 75, 90]
    g_pct_traj = {str(p): np.percentile(traj_g, p, axis=0).tolist() for p in band_pcts}
    b_pct_traj = {str(p): np.percentile(traj_b, p, axis=0).tolist() for p in band_pcts}
    g_wd_pcts = {str(p): np.percentile(wd_g, p, axis=0).tolist() for p in band_pcts}

    # 最低消费
    def min_nonzero_per_row(arr):
        mask = arr > 0
        filled = np.where(mask, arr, np.inf)
        return np.where(mask.any(axis=1), np.min(filled, axis=1), 0.0)

    g_min_wd = min_nonzero_per_row(wd_g)
    b_min_wd = min_nonzero_per_row(wd_b)
    g_p10_min = float(np.percentile(g_min_wd, 10))
    b_p10_min = float(np.percentile(b_min_wd, 10))

    g_total = np.sum(wd_g, axis=1)
    b_total = np.sum(wd_b, axis=1)

    metrics = [
        {"指标": "成功率", "Guardrail": f"{g_success:.1%}", "基准固定": f"{b_success:.1%}"},
        {"指标": "初始年提取额", "Guardrail": f"${req.annual_withdrawal:,.0f}", "基准固定": f"${baseline_wd:,.0f}"},
        {"指标": "中位数总消费额", "Guardrail": f"${np.median(g_total):,.0f}", "基准固定": f"${np.median(b_total):,.0f}"},
        {"指标": "中位数最终资产", "Guardrail": f"${np.median(traj_g[:, -1]):,.0f}", "基准固定": f"${np.median(traj_b[:, -1]):,.0f}"},
        {"指标": "P10 最低年度消费", "Guardrail": f"${g_p10_min:,.0f}", "基准固定": f"${b_p10_min:,.0f}"},
        {"指标": "P10 最低消费 vs 初始提取额",
         "Guardrail": f"{(g_p10_min / req.annual_withdrawal - 1) * 100:+.1f}%",
         "基准固定": f"{(b_p10_min / baseline_wd - 1) * 100:+.1f}%" if b_p10_min > 0 else "N/A"},
        {"指标": "中位数最终年提取额",
         "Guardrail": f"${np.median(wd_g[:, -1]):,.0f}",
         "基准固定": f"${baseline_wd:,.0f}"},
    ]

    return GuardrailResponse(
        initial_portfolio=init_portfolio,
        initial_rate=initial_rate,
        g_success_rate=g_success,
        g_percentile_trajectories=g_pct_traj,
        g_withdrawal_percentiles=g_wd_pcts,
        b_success_rate=b_success,
        b_percentile_trajectories=b_pct_traj,
        baseline_annual_wd=baseline_wd,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# 4. POST /api/guardrail/backtest
# ---------------------------------------------------------------------------

@app.post("/api/guardrail/backtest", response_model=BacktestResponse)
def api_backtest(req: BacktestRequest):
    filtered = _filter_df(req.data_start_year)
    if len(filtered) < 2:
        raise HTTPException(400, "可用数据不足")

    # 构建查找表
    scenarios, _ = pregenerate_return_scenarios(
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        retirement_years=req.retirement_years,
        min_block=req.min_block,
        max_block=req.max_block,
        num_simulations=req.num_simulations,
        returns_df=filtered,
    )
    rate_grid, table = build_success_rate_table(
        scenarios, GUARDRAIL_RATE_MIN, GUARDRAIL_RATE_MAX, GUARDRAIL_RATE_STEP,
    )

    # 历史数据
    hist_df = filtered[filtered["Year"] >= req.hist_start_year].reset_index(drop=True)
    if len(hist_df) < 1:
        raise HTTPException(400, f"从 {req.hist_start_year} 年开始无可用数据")

    hist_returns = compute_real_portfolio_returns(
        hist_df, _alloc_dict(req.allocation), _expense_dict(req.expense_ratios),
    )
    hist_inflation = hist_df["US Inflation"].values

    cash_flows = _to_cash_flows(req.cash_flows)

    result = run_historical_backtest(
        real_returns=hist_returns,
        initial_portfolio=req.initial_portfolio,
        annual_withdrawal=req.annual_withdrawal,
        target_success=req.target_success,
        upper_guardrail=req.upper_guardrail,
        lower_guardrail=req.lower_guardrail,
        adjustment_pct=req.adjustment_pct,
        retirement_years=req.retirement_years,
        min_remaining_years=req.min_remaining_years,
        baseline_rate=req.baseline_rate,
        table=table,
        rate_grid=rate_grid,
        adjustment_mode=req.adjustment_mode,
        cash_flows=cash_flows,
        inflation_series=hist_inflation,
    )

    n = result["years_simulated"]
    year_labels = [int(req.hist_start_year + i) for i in range(n + 1)]

    return BacktestResponse(
        years_simulated=n,
        year_labels=year_labels,
        g_portfolio=result["g_portfolio"].tolist(),
        g_withdrawals=result["g_withdrawals"].tolist(),
        g_success_rates=result["g_success_rates"].tolist(),
        b_portfolio=result["b_portfolio"].tolist(),
        b_withdrawals=result["b_withdrawals"].tolist(),
        g_total_consumption=result["g_total_consumption"],
        b_total_consumption=result["b_total_consumption"],
    )


# ---------------------------------------------------------------------------
# 5. GET /api/returns
# ---------------------------------------------------------------------------

@app.get("/api/returns", response_model=ReturnsResponse)
def api_returns(data_start_year: int = 1926):
    filtered = _filter_df(data_start_year)
    return ReturnsResponse(
        years=filtered["Year"].tolist(),
        us_stock=filtered["US Stock"].tolist(),
        intl_stock=filtered["International Stock"].tolist(),
        us_bond=filtered["US Bond"].tolist(),
        us_inflation=filtered["US Inflation"].tolist(),
    )
