"""FastAPI 后端 — 包装 simulator 计算引擎，提供 REST API。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

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
from simulator.data_loader import (
    filter_by_country,
    get_country_dfs,
    load_country_list,
    load_returns_data,
)
from simulator.guardrail import (
    build_success_rate_table,
    run_fixed_baseline,
    run_guardrail_simulation,
    run_historical_backtest,
)
from simulator.monte_carlo import run_simulation, run_simple_historical_backtest
from simulator.portfolio import compute_real_portfolio_returns
from simulator.statistics import PERCENTILES, compute_statistics, final_values_summary_table
from simulator.sweep import (
    interpolate_targets,
    pregenerate_raw_scenarios,
    pregenerate_return_scenarios,
    sweep_allocations,
    sweep_withdrawal_rates,
)

from schemas import (
    AllocationResult,
    AllocationSweepRequest,
    AllocationSweepResponse,
    BacktestRequest,
    BacktestResponse,
    CountriesResponse,
    CountryInfo,
    GuardrailRequest,
    GuardrailResponse,
    ReturnsResponse,
    SimBacktestRequest,
    SimBacktestResponse,
    SimulationRequest,
    SimulationResponse,
    SweepRequest,
    SweepResponse,
    TargetRateResult,
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="FIRE 退休模拟器 API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: 生产环境通过 ALLOWED_ORIGINS 环境变量限制，多域名用逗号分隔
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# 全局缓存
_returns_df = None
_country_list = None


def _get_returns_df():
    global _returns_df
    if _returns_df is None:
        _returns_df = load_returns_data()
    return _returns_df


def _get_country_list():
    global _country_list
    if _country_list is None:
        _country_list = load_country_list()
    return _country_list


def _filter_df(country: str, data_start_year: int):
    """按国家和起始年份过滤数据（单国模式）。"""
    df = _get_returns_df()
    return filter_by_country(df, country, data_start_year)


def _get_country_dfs_cached(data_start_year: int) -> dict[str, "pd.DataFrame"]:
    """获取按国家拆分的 DataFrames（池化 bootstrap 用）。"""
    df = _get_returns_df()
    return get_country_dfs(df, data_start_year)


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
    return {"domestic_stock": a.domestic_stock, "global_stock": a.global_stock, "domestic_bond": a.domestic_bond}


def _expense_dict(e) -> dict[str, float]:
    return {"domestic_stock": e.domestic_stock, "global_stock": e.global_stock, "domestic_bond": e.domestic_bond}


def _resolve_data(req):
    """根据 country 字段解析 filtered_df 和 country_dfs。

    Returns
    -------
    tuple[pd.DataFrame, dict | None]
        (filtered_df, country_dfs)
        - 单国模式: filtered_df 非空, country_dfs = None
        - ALL 模式: filtered_df 为空 placeholder, country_dfs 非空
    """
    import pandas as pd

    if req.country == "ALL":
        country_dfs = _get_country_dfs_cached(req.data_start_year)
        if not country_dfs:
            return pd.DataFrame(), None
        # 合并所有国家数据作为 filtered_df（用于非 bootstrap 场景）
        combined = pd.concat(country_dfs.values(), ignore_index=True)
        return combined, country_dfs
    else:
        filtered = _filter_df(req.country, req.data_start_year)
        return filtered, None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "ok"}



# ---------------------------------------------------------------------------
# GET /api/countries
# ---------------------------------------------------------------------------

@app.get("/api/countries", response_model=CountriesResponse)
def api_countries():
    """返回可用国家列表及其元数据。"""
    raw = _get_country_list()
    items = [CountryInfo(**c) for c in raw]
    return CountriesResponse(countries=items)


# ---------------------------------------------------------------------------
# 1. POST /api/simulate
# ---------------------------------------------------------------------------

@app.post("/api/simulate", response_model=SimulationResponse)
@limiter.limit("10/minute")
def api_simulate(request: Request, req: SimulationRequest):
    filtered, country_dfs = _resolve_data(req)
    if len(filtered) < 2 and country_dfs is None:
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
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        country_dfs=country_dfs,
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
# 1b. POST /api/simulate/backtest  — 单条历史路径回测
# ---------------------------------------------------------------------------

@app.post("/api/simulate/backtest", response_model=SimBacktestResponse)
@limiter.limit("10/minute")
def api_sim_backtest(request: Request, req: SimBacktestRequest):
    """用真实历史回报模拟退休路径（无 bootstrap）。"""
    if req.country == "ALL":
        raise HTTPException(400, "历史回测必须选择具体国家，不能使用 ALL 池化模式")

    filtered = _filter_df(req.country, req.data_start_year)
    if len(filtered) < 2:
        raise HTTPException(400, "可用数据不足")

    # 从 hist_start_year 开始截取
    filtered = filtered[filtered["Year"] >= req.hist_start_year].sort_values("Year").reset_index(drop=True)
    n_avail = len(filtered)
    if n_avail == 0:
        raise HTTPException(400, f"所选国家在 {req.hist_start_year} 年之后没有可用数据")

    n_years = min(req.retirement_years, n_avail)
    sampled = filtered.iloc[:n_years]
    year_labels = sampled["Year"].tolist()

    # 计算实际组合回报
    real_returns = compute_real_portfolio_returns(
        sampled, _alloc_dict(req.allocation), _expense_dict(req.expense_ratios),
        leverage=req.leverage, borrowing_spread=req.borrowing_spread,
    )

    # 通胀序列（用于名义现金流）
    inflation_series = sampled["Inflation"].values if "Inflation" in sampled.columns else None

    result = run_simple_historical_backtest(
        real_returns=real_returns,
        initial_portfolio=req.initial_portfolio,
        annual_withdrawal=req.annual_withdrawal,
        retirement_years=n_years,
        withdrawal_strategy=req.withdrawal_strategy,
        dynamic_ceiling=req.dynamic_ceiling,
        dynamic_floor=req.dynamic_floor,
        cash_flows=_to_cash_flows(req.cash_flows),
        inflation_series=inflation_series,
    )

    return SimBacktestResponse(
        years_simulated=result["years_simulated"],
        year_labels=year_labels,
        portfolio=result["portfolio"],
        withdrawals=result["withdrawals"],
        survived=result["survived"],
        final_portfolio=result["portfolio"][-1],
        total_consumption=sum(result["withdrawals"]),
    )


# ---------------------------------------------------------------------------
# 2. POST /api/sweep
# ---------------------------------------------------------------------------

@app.post("/api/sweep", response_model=SweepResponse)
@limiter.limit("10/minute")
def api_sweep(request: Request, req: SweepRequest):
    filtered, country_dfs = _resolve_data(req)
    if len(filtered) < 2 and country_dfs is None:
        raise HTTPException(400, "可用数据不足")

    scenarios, inflation_matrix = pregenerate_return_scenarios(
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        retirement_years=req.retirement_years,
        min_block=req.min_block,
        max_block=req.max_block,
        num_simulations=req.num_simulations,
        returns_df=filtered,
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        country_dfs=country_dfs,
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
@limiter.limit("10/minute")
def api_guardrail(request: Request, req: GuardrailRequest):
    filtered, country_dfs = _resolve_data(req)
    if len(filtered) < 2 and country_dfs is None:
        raise HTTPException(400, "可用数据不足")

    scenarios, inflation_matrix = pregenerate_return_scenarios(
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        retirement_years=req.retirement_years,
        min_block=req.min_block,
        max_block=req.max_block,
        num_simulations=req.num_simulations,
        returns_df=filtered,
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        country_dfs=country_dfs,
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
    b_wd_pcts = {str(p): np.percentile(wd_b, p, axis=0).tolist() for p in band_pcts}

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
         "Guardrail": f"{(g_p10_min / req.annual_withdrawal - 1) * 100:+.1f}%" if req.annual_withdrawal > 0 else "N/A",
         "基准固定": f"{(b_p10_min / baseline_wd - 1) * 100:+.1f}%" if baseline_wd > 0 else "N/A"},
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
        b_withdrawal_percentiles=b_wd_pcts,
        baseline_annual_wd=baseline_wd,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# 4. POST /api/guardrail/backtest
# ---------------------------------------------------------------------------

@app.post("/api/guardrail/backtest", response_model=BacktestResponse)
@limiter.limit("10/minute")
def api_backtest(request: Request, req: BacktestRequest):
    filtered, country_dfs = _resolve_data(req)
    if len(filtered) < 2 and country_dfs is None:
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
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        country_dfs=country_dfs,
    )
    rate_grid, table = build_success_rate_table(
        scenarios, GUARDRAIL_RATE_MIN, GUARDRAIL_RATE_MAX, GUARDRAIL_RATE_STEP,
    )

    # 历史数据 — 回测需要具体国家的真实历史路径
    bt_country = req.backtest_country or req.country
    if bt_country == "ALL":
        raise HTTPException(400, "历史回测必须指定具体国家")

    # 如果回测国家与 MC 国家不同（如 MC 用 ALL，回测用 USA），单独获取该国数据
    if bt_country != req.country or req.country == "ALL":
        hist_filtered = _filter_df(bt_country, req.data_start_year)
    else:
        hist_filtered = filtered

    hist_df = hist_filtered[hist_filtered["Year"] >= req.hist_start_year].reset_index(drop=True)
    if len(hist_df) < 1:
        raise HTTPException(400, f"{bt_country} 从 {req.hist_start_year} 年开始无可用数据")

    hist_returns = compute_real_portfolio_returns(
        hist_df, _alloc_dict(req.allocation), _expense_dict(req.expense_ratios),
        leverage=req.leverage, borrowing_spread=req.borrowing_spread,
    )
    hist_inflation = hist_df["Inflation"].values

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
        adjustment_events=result.get("adjustment_events", []),
    )


# ---------------------------------------------------------------------------
# 5. POST /api/allocation-sweep
# ---------------------------------------------------------------------------

@app.post("/api/allocation-sweep", response_model=AllocationSweepResponse)
@limiter.limit("10/minute")
def api_allocation_sweep(request: Request, req: AllocationSweepRequest):
    filtered, country_dfs = _resolve_data(req)
    if len(filtered) < 2 and country_dfs is None:
        raise HTTPException(400, "可用数据不足")

    raw = pregenerate_raw_scenarios(
        expense_ratios=_expense_dict(req.expense_ratios),
        retirement_years=req.retirement_years,
        min_block=req.min_block,
        max_block=req.max_block,
        num_simulations=req.num_simulations,
        returns_df=filtered,
        country_dfs=country_dfs,
    )

    cash_flows = _to_cash_flows(req.cash_flows)

    raw_results = sweep_allocations(
        raw_scenarios=raw,
        initial_portfolio=req.initial_portfolio,
        annual_withdrawal=req.annual_withdrawal,
        allocation_step=req.allocation_step,
        withdrawal_strategy=req.withdrawal_strategy,
        dynamic_ceiling=req.dynamic_ceiling,
        dynamic_floor=req.dynamic_floor,
        cash_flows=cash_flows,
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
    )

    alloc_results = [AllocationResult(**r) for r in raw_results]
    best = max(alloc_results, key=lambda x: x.success_rate)

    return AllocationSweepResponse(
        results=alloc_results,
        best_by_success=best,
    )


# ---------------------------------------------------------------------------
# 6. GET /api/returns
# ---------------------------------------------------------------------------

@app.get("/api/returns", response_model=ReturnsResponse)
def api_returns(country: str = "USA", data_start_year: int = 1970):
    df = _get_returns_df()
    filtered = filter_by_country(df, country, data_start_year)
    return ReturnsResponse(
        years=filtered["Year"].tolist(),
        domestic_stock=filtered["Domestic_Stock"].tolist(),
        global_stock=filtered["Global_Stock"].tolist(),
        domestic_bond=filtered["Domestic_Bond"].tolist(),
        inflation=filtered["Inflation"].tolist(),
    )
