"""FastAPI 后端 — 包装 simulator 计算引擎，提供 REST API。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# 确保 simulator 包可被导入（项目根目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulator.cashflow import CashFlowItem, build_cf_schedule, build_representative_cf_schedule, enumerate_cf_scenarios, enumerate_cf_per_group, has_probabilistic_cf
from concurrent.futures import ThreadPoolExecutor

from simulator.config import (
    SCENARIO_CF_MAX_SIMS,
    SCENARIO_CF_RATE_SEGMENTS,
    SCENARIO_CF_SCALE_SEGMENTS,
    SCENARIO_MAX_START_YEARS,
    TARGET_SUCCESS_RATES,
    get_gdp_weights,
)
from simulator.buy_vs_rent import (
    find_breakeven_price_mc,
    find_breakeven_price_simple,
    run_buy_vs_rent_mc,
    run_simple_buy_vs_rent,
)
from simulator.data_loader import (
    filter_by_country,
    filter_housing_data,
    get_country_dfs,
    get_housing_available_countries,
    get_housing_country_dfs,
    load_country_list_by_source,
    load_returns_by_source,
)
from simulator.guardrail import (
    apply_guardrail_adjustment,
    build_cf_aware_table,
    build_success_rate_table,
    find_rate_for_target,
    find_rate_for_target_cf_aware,
    lookup_cf_aware_success_rate,
    run_fixed_baseline,
    run_guardrail_simulation,
    run_historical_backtest,
)
from simulator.monte_carlo import run_simulation, run_simple_historical_backtest
from simulator.portfolio import compute_real_portfolio_returns
from simulator.statistics import (
    PERCENTILES,
    compute_effective_funded_ratio,
    compute_funded_ratio,
    compute_portfolio_metrics,
    compute_single_path_metrics,
    compute_statistics,
    final_values_summary_table,
)
from simulator.backtest_batch import (
    run_guardrail_batch_backtest,
    run_sim_batch_backtest,
)
from simulator.sweep import (
    interpolate_targets,
    pregenerate_raw_scenarios,
    pregenerate_return_scenarios,
    sweep_allocations,
    sweep_withdrawal_rates,
)
from simulator.accumulation import run_accumulation

from schemas import (
    AdjustmentEvent,
    AllocationResult,
    AllocationSweepRequest,
    AllocationSweepResponse,
    BacktestRequest,
    BacktestResponse,
    BreakevenMCRequest,
    BreakevenResponse,
    BreakevenSimpleRequest,
    BuyVsRentMCRequest,
    BuyVsRentMCResponse,
    BuyVsRentSimpleRequest,
    BuyVsRentSimpleResponse,
    CountriesResponse,
    CountryInfo,
    GuardrailBatchBacktestRequest,
    GuardrailBatchBacktestResponse,
    GuardrailBatchPathSummary,
    GuardrailRequest,
    GuardrailResponse,
    HousingCountriesResponse,
    ScenarioAnalysisResponse,
    ScenarioResult,
    SensitivityAnalysisResponse,
    SensitivityDelta,
    HousingCountryInfo,
    ReturnsResponse,
    SimBatchBacktestRequest,
    SimBatchBacktestResponse,
    SimBatchPathSummary,
    SimBacktestRequest,
    SimBacktestResponse,
    SimulationRequest,
    SimulationResponse,
    SweepRequest,
    SweepResponse,
    TargetRateResult,
    AccumulationRequest,
    AccumulationResponse,
)

# ---------------------------------------------------------------------------
# 自定义异常类：提供结构化错误响应
# ---------------------------------------------------------------------------

class DataNotFoundError(HTTPException):
    """数据未找到异常（404）"""
    def __init__(self, message: str):
        super().__init__(
            status_code=404,
            detail={"error": "DATA_NOT_FOUND", "message": message}
        )


class ValidationError(HTTPException):
    """参数验证失败异常（400）"""
    def __init__(self, message: str):
        super().__init__(
            status_code=400,
            detail={"error": "VALIDATION_ERROR", "message": message}
        )


class ComputationError(HTTPException):
    """计算过程错误异常（500）"""
    def __init__(self, message: str):
        super().__init__(
            status_code=500,
            detail={"error": "COMPUTATION_ERROR", "message": message}
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

# GZIP 响应压缩：减少大型 JSON 响应的网络传输量（60-80% 压缩率）
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 全局缓存（按 data_source 键分别缓存）
_returns_cache: dict[str, object] = {}
_country_list_cache: dict[str, list] = {}
# 新增：按 (data_start_year, data_source) 缓存 country_dfs 和 combined DataFrame
_country_dfs_cache: dict[tuple[int, str], dict] = {}
_combined_df_cache: dict[tuple[int, str], object] = {}


def _get_returns_df(data_source: str = "jst"):
    if data_source not in _returns_cache:
        _returns_cache[data_source] = load_returns_by_source(data_source)
    return _returns_cache[data_source]


def _get_country_list(data_source: str = "jst"):
    if data_source not in _country_list_cache:
        _country_list_cache[data_source] = load_country_list_by_source(data_source)
    return _country_list_cache[data_source]


def _filter_df(country: str, data_start_year: int, data_source: str = "jst"):
    """按国家和起始年份过滤数据（单国模式）。"""
    df = _get_returns_df(data_source)
    return filter_by_country(df, country, data_start_year)


def _get_country_dfs_cached(data_start_year: int, data_source: str = "jst") -> dict[str, "pd.DataFrame"]:
    """获取按国家拆分的 DataFrames（池化 bootstrap 用）。

    使用 (data_start_year, data_source) 作为缓存键，避免重复过滤。
    """
    cache_key = (data_start_year, data_source)
    if cache_key not in _country_dfs_cache:
        df = _get_returns_df(data_source)
        _country_dfs_cache[cache_key] = get_country_dfs(df, data_start_year)
    return _country_dfs_cache[cache_key]


def _get_combined_df(data_start_year: int, data_source: str = "jst"):
    """获取合并后的多国 DataFrame（ALL模式），带缓存。"""
    cache_key = (data_start_year, data_source)
    if cache_key not in _combined_df_cache:
        country_dfs = _get_country_dfs_cached(data_start_year, data_source)
        if not country_dfs:
            _combined_df_cache[cache_key] = pd.DataFrame()
        else:
            _combined_df_cache[cache_key] = pd.concat(country_dfs.values(), ignore_index=True)
    return _combined_df_cache[cache_key]


def _to_cash_flows(items) -> list[CashFlowItem] | None:
    if not items:
        return None
    enabled = [cf for cf in items if getattr(cf, "enabled", True)]
    if not enabled:
        return None
    return [
        CashFlowItem(
            name=cf.name,
            amount=cf.amount,
            start_year=cf.start_year,
            duration=cf.duration,
            inflation_adjusted=cf.inflation_adjusted,
            growth_rate=getattr(cf, "growth_rate", 0.0),
            probability=getattr(cf, "probability", 1.0),
            group=getattr(cf, "group", None),
        )
        for cf in enabled
    ]


def _alloc_dict(a) -> dict[str, float]:
    return {"domestic_stock": a.domestic_stock, "global_stock": a.global_stock, "domestic_bond": a.domestic_bond}


def _expense_dict(e) -> dict[str, float]:
    return {"domestic_stock": e.domestic_stock, "global_stock": e.global_stock, "domestic_bond": e.domestic_bond}


def _validate_data_sufficient(filtered, country_dfs) -> None:
    """校验数据是否充足，不足则抛出 400。"""
    if len(filtered) < 2 and country_dfs is None:
        raise HTTPException(400, "可用数据不足")


def _unpack_cf_table(cf_table_result) -> tuple:
    """解包 build_cf_aware_table 返回的五元组，None 安全。"""
    if cf_table_result is None:
        return None, None, None, 0.0, -1
    return (
        cf_table_result[0],  # cf_rate_grid
        cf_table_result[1],  # cf_scale_grid
        cf_table_result[2],  # cf_table
        cf_table_result[3],  # cf_ref
        cf_table_result[4],  # last_cf_year
    )


def _resolve_data(req):
    """根据 country 字段解析 filtered_df 和 country_dfs。

    Returns
    -------
    tuple[pd.DataFrame, dict | None]
        (filtered_df, country_dfs)
        - 单国模式: filtered_df 非空, country_dfs = None
        - ALL 模式: filtered_df 为空 placeholder, country_dfs 非空
    """
    ds = getattr(req, "data_source", "jst")
    country = req.country
    # FIRE Dataset 只有 USA，自动降级
    if ds == "fire_dataset" and country == "ALL":
        country = "USA"

    if country == "ALL":
        country_dfs = _get_country_dfs_cached(req.data_start_year, ds)
        if not country_dfs:
            return pd.DataFrame(), None
        # 使用缓存的 combined DataFrame，避免每次请求都 concat
        combined = _get_combined_df(req.data_start_year, ds)
        return combined, country_dfs
    else:
        filtered = _filter_df(country, req.data_start_year, ds)
        return filtered, None


def _resolve_country_weights(
    req, country_dfs: dict | None,
) -> dict[str, float] | None:
    """根据 pooling_method 和可用国家计算采样权重。

    仅在 country=ALL 且 country_dfs 非空时有效；
    单国模式下返回 None（不使用池化）。
    """
    if country_dfs is None:
        return None
    if req.pooling_method == "gdp_sqrt":
        return get_gdp_weights(list(country_dfs.keys()))
    # "equal" — 返回 None 让 bootstrap 使用默认等概率
    return None


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
def api_countries(data_source: str = "jst"):
    """返回可用国家列表及其元数据。"""
    raw = _get_country_list(data_source)
    items = [CountryInfo(**c) for c in raw]
    return CountriesResponse(countries=items)


# ---------------------------------------------------------------------------
# Historical events
# ---------------------------------------------------------------------------

_historical_events: list[dict] | None = None

def _load_historical_events() -> list[dict]:
    global _historical_events
    if _historical_events is None:
        import json
        events_path = PROJECT_ROOT / "data" / "historical_events.json"
        with open(events_path, encoding="utf-8") as f:
            _historical_events = json.load(f)
    return _historical_events


@app.get("/api/historical-events")
def api_historical_events(country: str | None = None):
    events = _load_historical_events()
    if country:
        events = [
            e for e in events
            if "ALL" in e["countries"] or country in e["countries"]
        ]
    return events


# ---------------------------------------------------------------------------
# 1. POST /api/simulate
# ---------------------------------------------------------------------------

@app.post("/api/simulate", response_model=SimulationResponse)
@limiter.limit("10/minute")
def api_simulate(request: Request, req: SimulationRequest):
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)

    trajectories, withdrawals, real_ret_mat, infl_mat = run_simulation(
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
        retirement_age=req.retirement_age,
        cash_flows=_to_cash_flows(req.cash_flows),
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        country_dfs=country_dfs,
        country_weights=country_weights,
        declining_rate=req.declining_rate,
        declining_start_age=req.declining_start_age,
        smile_decline_rate=req.smile_decline_rate,
        smile_decline_start_age=req.smile_decline_start_age,
        smile_min_age=req.smile_min_age,
        smile_increase_rate=req.smile_increase_rate,
        glide_path_end_allocation=_alloc_dict(req.glide_path_end_allocation) if req.glide_path_enabled else None,
        glide_path_years=req.glide_path_years,
    )

    results = compute_statistics(trajectories, req.retirement_years, withdrawals)
    summary_df = final_values_summary_table(results)
    port_metrics = compute_portfolio_metrics(real_ret_mat, infl_mat)

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
        funded_ratio=results.funded_ratio,
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
        portfolio_metrics=port_metrics,
    )


# ---------------------------------------------------------------------------
# 1b. POST /api/simulate/backtest  — 单条历史路径回测
# ---------------------------------------------------------------------------

@app.post("/api/simulate/backtest", response_model=SimBacktestResponse)
@limiter.limit("10/minute")
def api_sim_backtest(request: Request, req: SimBacktestRequest):
    """用真实历史回报模拟退休路径（无 bootstrap）。"""
    country = req.country
    if req.data_source == "fire_dataset" and country == "ALL":
        country = "USA"
    if country == "ALL":
        raise HTTPException(400, "历史回测必须选择具体国家，不能使用 ALL 池化模式")

    filtered = _filter_df(country, req.data_start_year, req.data_source)
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
        retirement_age=req.retirement_age,
        cash_flows=_to_cash_flows(req.cash_flows),
        inflation_series=inflation_series,
        declining_rate=req.declining_rate,
        declining_start_age=req.declining_start_age,
        smile_decline_rate=req.smile_decline_rate,
        smile_decline_start_age=req.smile_decline_start_age,
        smile_min_age=req.smile_min_age,
        smile_increase_rate=req.smile_increase_rate,
    )

    # 单路径绩效指标
    path_metrics = compute_single_path_metrics(
        real_returns[:n_years],
        inflation_series[:n_years] if inflation_series is not None else np.zeros(n_years),
    )

    return SimBacktestResponse(
        years_simulated=result["years_simulated"],
        year_labels=year_labels,
        portfolio=result["portfolio"],
        withdrawals=result["withdrawals"],
        survived=result["survived"],
        final_portfolio=result["portfolio"][-1],
        total_consumption=sum(result["withdrawals"]),
        path_metrics=path_metrics,
    )


# ---------------------------------------------------------------------------
# 1c. POST /api/simulate/backtest-batch  — 批量历史回测
# ---------------------------------------------------------------------------

@app.post("/api/simulate/backtest-batch", response_model=SimBatchBacktestResponse)
@limiter.limit("5/minute")
def api_sim_batch_backtest(request: Request, req: SimBatchBacktestRequest):
    """遍历所有有效 (国家, 起始年) 组合进行历史回测。"""
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    result = run_sim_batch_backtest(
        country_dfs=country_dfs,
        filtered_df=filtered if country_dfs is None else None,
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        initial_portfolio=req.initial_portfolio,
        annual_withdrawal=req.annual_withdrawal,
        retirement_years=req.retirement_years,
        withdrawal_strategy=req.withdrawal_strategy,
        dynamic_ceiling=req.dynamic_ceiling,
        dynamic_floor=req.dynamic_floor,
        retirement_age=req.retirement_age,
        cash_flows=_to_cash_flows(req.cash_flows),
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        declining_rate=req.declining_rate,
        declining_start_age=req.declining_start_age,
        smile_decline_rate=req.smile_decline_rate,
        smile_decline_start_age=req.smile_decline_start_age,
        smile_min_age=req.smile_min_age,
        smile_increase_rate=req.smile_increase_rate,
    )

    return SimBatchBacktestResponse(
        num_paths=result["num_paths"],
        num_complete=result["num_complete"],
        success_rate=result["success_rate"],
        funded_ratio=result["funded_ratio"],
        percentile_trajectories=result["percentile_trajectories"],
        withdrawal_percentile_trajectories=result["withdrawal_percentile_trajectories"],
        final_values_summary=result["final_values_summary"],
        portfolio_metrics=result["portfolio_metrics"],
        paths=[SimBatchPathSummary(**p) for p in result["paths"]],
    )


# ---------------------------------------------------------------------------
# 1d. POST /api/simulate/scenarios — 现金流情景分解（通用策略）
# ---------------------------------------------------------------------------

@app.post("/api/simulate/scenarios", response_model=ScenarioAnalysisResponse)
@limiter.limit("5/minute")
def api_simulate_scenarios(request: Request, req: SimulationRequest):
    """枚举概率现金流的所有确定性组合，用用户选择的提取策略模拟。"""
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    cash_flows = _to_cash_flows(req.cash_flows)
    if not cash_flows:
        raise HTTPException(400, "需要至少一个自定义现金流")

    mode = "full"
    cf_scenarios = enumerate_cf_scenarios(cash_flows, max_combinations=32)
    if not cf_scenarios:
        cf_scenarios = enumerate_cf_per_group(cash_flows)
        mode = "per_group"
        if not cf_scenarios:
            raise HTTPException(400, "没有概率分组现金流。请检查现金流设置。")

    country_weights = _resolve_country_weights(req, country_dfs)

    def _sim_kwargs_base():
        return dict(
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
            retirement_age=req.retirement_age,
            leverage=req.leverage,
            borrowing_spread=req.borrowing_spread,
            country_dfs=country_dfs,
            country_weights=country_weights,
            declining_rate=req.declining_rate,
            declining_start_age=req.declining_start_age,
            smile_decline_rate=req.smile_decline_rate,
            smile_decline_start_age=req.smile_decline_start_age,
            smile_min_age=req.smile_min_age,
            smile_increase_rate=req.smile_increase_rate,
            glide_path_end_allocation=_alloc_dict(req.glide_path_end_allocation) if req.glide_path_enabled else None,
            glide_path_years=req.glide_path_years,
        )

    def _run_scenario(
        scenario_cfs: list[CashFlowItem] | None,
        label: str,
    ) -> ScenarioResult:
        kw = _sim_kwargs_base()
        kw["cash_flows"] = scenario_cfs
        traj, wd, _, _ = run_simulation(**kw)
        sr = float(np.mean(traj[:, -1] > 0))
        fr = compute_funded_ratio(traj, req.retirement_years)
        total = np.sum(wd, axis=1)
        return ScenarioResult(
            label=label,
            probability=0.0,
            success_rate=sr,
            funded_ratio=fr,
            median_final_portfolio=float(np.median(traj[:, -1])),
            median_total_consumption=float(np.median(total)),
            annual_withdrawal=req.annual_withdrawal,
            initial_portfolio=req.initial_portfolio,
        )

    max_workers = max(1, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_base = pool.submit(_run_scenario, cash_flows, "base_case")
        futures = {
            pool.submit(_run_scenario, cfs, label): (label, prob)
            for label, cfs, prob in cf_scenarios
        }
        base = future_base.result()
        results = []
        for fut, (label, prob) in futures.items():
            r = fut.result()
            r.probability = prob
            results.append(r)

    return ScenarioAnalysisResponse(base_case=base, scenarios=results, mode=mode)


# ---------------------------------------------------------------------------
# 1e. POST /api/simulate/sensitivity — 参数敏感性分析（通用策略）
# ---------------------------------------------------------------------------

@app.post("/api/simulate/sensitivity", response_model=SensitivityAnalysisResponse)
@limiter.limit("5/minute")
def api_simulate_sensitivity(request: Request, req: SimulationRequest):
    """核心参数 ±delta 对成功率的影响（使用用户选择的提取策略）。"""
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)
    cash_flows = _to_cash_flows(req.cash_flows)

    def _run_sim(ip, aw, yrs, alloc=None, er=None, cfs=None):
        kw = dict(
            initial_portfolio=ip,
            annual_withdrawal=aw,
            allocation=alloc or _alloc_dict(req.allocation),
            expense_ratios=er or _expense_dict(req.expense_ratios),
            retirement_years=yrs,
            min_block=req.min_block,
            max_block=req.max_block,
            num_simulations=req.num_simulations,
            returns_df=filtered,
            withdrawal_strategy=req.withdrawal_strategy,
            dynamic_ceiling=req.dynamic_ceiling,
            dynamic_floor=req.dynamic_floor,
            retirement_age=req.retirement_age,
            cash_flows=cfs if cfs is not None else cash_flows,
            leverage=req.leverage,
            borrowing_spread=req.borrowing_spread,
            country_dfs=country_dfs,
            country_weights=country_weights,
            declining_rate=req.declining_rate,
            declining_start_age=req.declining_start_age,
            smile_decline_rate=req.smile_decline_rate,
            smile_decline_start_age=req.smile_decline_start_age,
            smile_min_age=req.smile_min_age,
            smile_increase_rate=req.smile_increase_rate,
            glide_path_end_allocation=_alloc_dict(req.glide_path_end_allocation) if req.glide_path_enabled else None,
            glide_path_years=req.glide_path_years,
        )
        traj, _, _, _ = run_simulation(**kw)
        sr = float(np.mean(traj[:, -1] > 0))
        fr = compute_funded_ratio(traj, yrs)
        return sr, fr

    base_ip = req.initial_portfolio
    base_aw = req.annual_withdrawal
    base_years = req.retirement_years
    stock_pct = req.allocation.domestic_stock + req.allocation.global_stock

    base_sr, base_fr = _run_sim(base_ip, base_aw, base_years)

    param_specs = [
        ("initial_portfolio", "初始资产", base_ip, base_ip * 0.8, base_ip * 1.2),
        ("annual_withdrawal", "年提取额", base_aw, base_aw * 0.8, base_aw * 1.2),
        ("retirement_years", "退休年限", float(base_years), float(max(10, base_years - 10)), float(base_years + 10)),
        ("stock_allocation", "股票配置比例", stock_pct, max(0.0, stock_pct - 0.2), min(1.0, stock_pct + 0.2)),
    ]

    deltas = []
    for key, label, base_val, lo_val, hi_val in param_specs:
        lo_sr, lo_fr, hi_sr, hi_fr = base_sr, base_fr, base_sr, base_fr

        for side, side_val in [("low", lo_val), ("high", hi_val)]:
            sr, fr = base_sr, base_fr

            if key == "initial_portfolio":
                sr, fr = _run_sim(side_val, base_aw, base_years)
            elif key == "annual_withdrawal":
                sr, fr = _run_sim(base_ip, side_val, base_years)
            elif key == "retirement_years":
                sr, fr = _run_sim(base_ip, base_aw, int(side_val))
            elif key == "stock_allocation":
                new_stock = side_val
                old_stock = stock_pct
                if old_stock > 0:
                    ratio = new_stock / old_stock
                    dom_new = req.allocation.domestic_stock * ratio
                    glb_new = req.allocation.global_stock * ratio
                else:
                    dom_new = new_stock / 2.0
                    glb_new = new_stock / 2.0
                bond_new = max(0.0, 1.0 - dom_new - glb_new)
                new_alloc = {"domestic_stock": dom_new, "global_stock": glb_new, "domestic_bond": bond_new}
                sr, fr = _run_sim(base_ip, base_aw, base_years, alloc=new_alloc)

            if side == "low":
                lo_sr, lo_fr = sr, fr
            else:
                hi_sr, hi_fr = sr, fr

        deltas.append(SensitivityDelta(
            param_label=label,
            param_key=key,
            low_value=lo_val,
            high_value=hi_val,
            base_value=base_val,
            low_success_rate=lo_sr,
            high_success_rate=hi_sr,
            low_funded_ratio=lo_fr,
            high_funded_ratio=hi_fr,
        ))

    return SensitivityAnalysisResponse(
        base_success_rate=base_sr,
        base_funded_ratio=base_fr,
        deltas=deltas,
    )


# ---------------------------------------------------------------------------
# 2. POST /api/sweep
# ---------------------------------------------------------------------------

@app.post("/api/sweep", response_model=SweepResponse)
@limiter.limit("10/minute")
def api_sweep(request: Request, req: SweepRequest):
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)

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
        country_weights=country_weights,
    )

    cash_flows = _to_cash_flows(req.cash_flows)

    rates, success_rates, funded_ratios = sweep_withdrawal_rates(
        real_returns_matrix=scenarios,
        initial_portfolio=req.initial_portfolio,
        rate_min=0.0,
        rate_max=req.rate_max,
        rate_step=req.rate_step,
        withdrawal_strategy=req.withdrawal_strategy,
        dynamic_ceiling=req.dynamic_ceiling,
        dynamic_floor=req.dynamic_floor,
        retirement_age=req.retirement_age,
        cash_flows=cash_flows,
        inflation_matrix=inflation_matrix,
    )

    # 成功率目标插值
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

    # 覆盖率目标插值（复用同一目标阈值）
    target_rates_funded = interpolate_targets(rates, funded_ratios, TARGET_SUCCESS_RATES)

    target_results_funded = []
    for t, r in zip(TARGET_SUCCESS_RATES, target_rates_funded):
        if r is not None and r > 0:
            target_results_funded.append(TargetRateResult(
                target_success=f"{t:.0%}",
                rate=f"{r * 100:.2f}%",
                annual_withdrawal=f"${req.initial_portfolio * r:,.0f}",
                needed_portfolio=f"${req.annual_withdrawal / r:,.0f}",
            ))
        else:
            target_results_funded.append(TargetRateResult(
                target_success=f"{t:.0%}",
                rate=None,
                annual_withdrawal=None,
                needed_portfolio=None,
            ))

    return SweepResponse(
        rates=rates.tolist(),
        success_rates=success_rates.tolist(),
        funded_ratios=funded_ratios.tolist(),
        target_results=target_results,
        target_results_funded=target_results_funded,
    )


# ---------------------------------------------------------------------------
# 3. POST /api/guardrail
# ---------------------------------------------------------------------------

@app.post("/api/guardrail", response_model=GuardrailResponse)
@limiter.limit("10/minute")
def api_guardrail(request: Request, req: GuardrailRequest):
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)

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
        country_weights=country_weights,
    )

    rate_grid, table = build_success_rate_table(scenarios)

    cash_flows = _to_cash_flows(req.cash_flows)

    # 3D 现金流感知查找表
    cf_table_result = None
    if cash_flows:
        rep_schedule = build_representative_cf_schedule(
            cash_flows, req.retirement_years, inflation_matrix,
        )
        cf_table_result = build_cf_aware_table(scenarios, rep_schedule)

    _cf_rg, _cf_sg, _cf_tbl, _cf_ref, _last_cf_y = _unpack_cf_table(cf_table_result)

    sim_kwargs = dict(
        scenarios=scenarios,
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
        cf_table=_cf_tbl,
        cf_rate_grid=_cf_rg,
        cf_scale_grid=_cf_sg,
        cf_ref=_cf_ref,
        last_cf_year=_last_cf_y,
    )
    if req.input_mode == "withdrawal":
        sim_kwargs["annual_withdrawal"] = req.annual_withdrawal
    else:
        sim_kwargs["initial_portfolio"] = req.initial_portfolio

    init_portfolio, annual_wd, traj_g, wd_g = run_guardrail_simulation(**sim_kwargs)

    traj_b, wd_b = run_fixed_baseline(
        scenarios, init_portfolio, req.baseline_rate, req.retirement_years,
        cash_flows=cash_flows, inflation_matrix=inflation_matrix,
    )

    g_fr, g_success = compute_effective_funded_ratio(
        wd_g, annual_wd, req.retirement_years,
        consumption_floor=req.consumption_floor,
        trajectories=traj_g,
    )
    b_success = float(np.mean(traj_b[:, -1] > 0))
    b_fr = compute_funded_ratio(traj_b, req.retirement_years)
    initial_rate = annual_wd / init_portfolio if init_portfolio > 0 else 0
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
        {"指标": "初始年提取额", "Guardrail": f"${annual_wd:,.0f}", "基准固定": f"${baseline_wd:,.0f}"},
        {"指标": "中位数总消费额", "Guardrail": f"${np.median(g_total):,.0f}", "基准固定": f"${np.median(b_total):,.0f}"},
        {"指标": "中位数最终资产", "Guardrail": f"${np.median(traj_g[:, -1]):,.0f}", "基准固定": f"${np.median(traj_b[:, -1]):,.0f}"},
        {"指标": "P10 最低年度消费", "Guardrail": f"${g_p10_min:,.0f}", "基准固定": f"${b_p10_min:,.0f}"},
        {"指标": "P10 最低消费 vs 初始提取额",
         "Guardrail": f"{(g_p10_min / annual_wd - 1) * 100:+.1f}%" if annual_wd > 0 else "N/A",
         "基准固定": f"{(b_p10_min / baseline_wd - 1) * 100:+.1f}%" if baseline_wd > 0 else "N/A"},
        {"指标": "中位数最终年提取额",
         "Guardrail": f"${np.median(wd_g[:, -1]):,.0f}",
         "基准固定": f"${baseline_wd:,.0f}"},
    ]

    # 投资组合绩效指标（底层回报序列相同，guardrail/baseline 共用）
    port_metrics = compute_portfolio_metrics(scenarios, inflation_matrix)

    # 初始护栏触发阈值：反算触发上/下护栏时的资产值和调整后提取额
    remaining_y0 = min(req.retirement_years, table.shape[1] - 1)

    if cf_table_result is not None:
        # 3D 表模式：用二分法找到 V 使 success_rate(wd/V, cf_ref/V, 0) = target
        def _find_trigger_port_3d(target_sr: float) -> float:
            r0 = find_rate_for_target(table, rate_grid, target_sr, remaining_y0)
            v_guess = annual_wd / r0 if r0 > 0 else init_portfolio * 5
            lo, hi = v_guess * 0.1, v_guess * 10
            for _ in range(40):
                v_mid = (lo + hi) / 2
                sr = lookup_cf_aware_success_rate(
                    _cf_tbl, _cf_rg, _cf_sg,
                    annual_wd / v_mid, _cf_ref / v_mid, 0,
                )
                if sr < target_sr:
                    lo = v_mid
                else:
                    hi = v_mid
            return (lo + hi) / 2

        upper_trigger_port = _find_trigger_port_3d(req.upper_guardrail)
        lower_trigger_port = _find_trigger_port_3d(req.lower_guardrail)

        _cs_upper = _cf_ref / upper_trigger_port if upper_trigger_port > 0 else 0.0
        upper_trigger_wd = apply_guardrail_adjustment(
            wd=annual_wd, value=upper_trigger_port,
            current_success=req.upper_guardrail, target_success=req.target_success,
            adjustment_pct=req.adjustment_pct, adjustment_mode=req.adjustment_mode,
            remaining=remaining_y0, table=table, rate_grid=_cf_rg,
            cf_table=_cf_tbl, cf_scale_grid=_cf_sg,
            cf_scale=_cs_upper, start_year=0,
        ) if upper_trigger_port > 0 else 0.0

        _cs_lower = _cf_ref / lower_trigger_port if lower_trigger_port > 0 else 0.0
        lower_trigger_wd = apply_guardrail_adjustment(
            wd=annual_wd, value=lower_trigger_port,
            current_success=req.lower_guardrail, target_success=req.target_success,
            adjustment_pct=req.adjustment_pct, adjustment_mode=req.adjustment_mode,
            remaining=remaining_y0, table=table, rate_grid=_cf_rg,
            cf_table=_cf_tbl, cf_scale_grid=_cf_sg,
            cf_scale=_cs_lower, start_year=0,
        ) if lower_trigger_port > 0 else 0.0
    else:
        upper_rate = find_rate_for_target(table, rate_grid, req.upper_guardrail, remaining_y0)
        lower_rate = find_rate_for_target(table, rate_grid, req.lower_guardrail, remaining_y0)
        upper_trigger_port = annual_wd / upper_rate if upper_rate > 0 else 0.0
        lower_trigger_port = annual_wd / lower_rate if lower_rate > 0 else 0.0

        upper_trigger_wd = apply_guardrail_adjustment(
            wd=annual_wd, value=upper_trigger_port,
            current_success=req.upper_guardrail, target_success=req.target_success,
            adjustment_pct=req.adjustment_pct, adjustment_mode=req.adjustment_mode,
            remaining=remaining_y0, table=table, rate_grid=rate_grid,
        ) if upper_trigger_port > 0 else 0.0
        lower_trigger_wd = apply_guardrail_adjustment(
            wd=annual_wd, value=lower_trigger_port,
            current_success=req.lower_guardrail, target_success=req.target_success,
            adjustment_pct=req.adjustment_pct, adjustment_mode=req.adjustment_mode,
            remaining=remaining_y0, table=table, rate_grid=rate_grid,
        ) if lower_trigger_port > 0 else 0.0

    return GuardrailResponse(
        initial_portfolio=init_portfolio,
        annual_withdrawal=annual_wd,
        initial_rate=initial_rate,
        g_success_rate=g_success,
        g_funded_ratio=g_fr,
        g_percentile_trajectories=g_pct_traj,
        g_withdrawal_percentiles=g_wd_pcts,
        b_success_rate=b_success,
        b_funded_ratio=b_fr,
        b_percentile_trajectories=b_pct_traj,
        b_withdrawal_percentiles=b_wd_pcts,
        baseline_annual_wd=baseline_wd,
        upper_trigger_portfolio=upper_trigger_port,
        upper_trigger_withdrawal=upper_trigger_wd,
        lower_trigger_portfolio=lower_trigger_port,
        lower_trigger_withdrawal=lower_trigger_wd,
        metrics=metrics,
        portfolio_metrics=port_metrics,
    )


# ---------------------------------------------------------------------------
# 3b. POST /api/guardrail/scenarios — 现金流情景分解
# ---------------------------------------------------------------------------

@app.post("/api/guardrail/scenarios", response_model=ScenarioAnalysisResponse)
@limiter.limit("5/minute")
def api_guardrail_scenarios(request: Request, req: GuardrailRequest):
    """枚举概率现金流的所有确定性组合，对比各场景对退休结果的影响。"""
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    cash_flows = _to_cash_flows(req.cash_flows)
    if not cash_flows:
        raise HTTPException(400, "需要至少一个自定义现金流")

    mode = "full"
    cf_scenarios = enumerate_cf_scenarios(cash_flows, max_combinations=32)
    if not cf_scenarios:
        cf_scenarios = enumerate_cf_per_group(cash_flows)
        mode = "per_group"
        if not cf_scenarios:
            raise HTTPException(400, "没有概率分组现金流。请检查现金流设置。")

    country_weights = _resolve_country_weights(req, country_dfs)

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
        country_weights=country_weights,
    )

    rate_grid, table = build_success_rate_table(scenarios)

    def _run_scenario(
        scenario_cfs: list[CashFlowItem] | None,
        label: str,
    ) -> ScenarioResult:
        cf_table_r = None
        if scenario_cfs:
            rep_schedule = build_representative_cf_schedule(
                scenario_cfs, req.retirement_years, inflation_matrix,
            )
            cf_table_r = build_cf_aware_table(
                scenarios, rep_schedule,
                rate_segments=SCENARIO_CF_RATE_SEGMENTS,
                cf_scale_segments=SCENARIO_CF_SCALE_SEGMENTS,
                max_sims=SCENARIO_CF_MAX_SIMS,
                max_start_years=SCENARIO_MAX_START_YEARS,
            )

        _cf_r, _cf_s, _cf_t, _cf_ref, _last_y = _unpack_cf_table(cf_table_r)

        sim_kwargs = dict(
            scenarios=scenarios,
            target_success=req.target_success,
            upper_guardrail=req.upper_guardrail,
            lower_guardrail=req.lower_guardrail,
            adjustment_pct=req.adjustment_pct,
            retirement_years=req.retirement_years,
            min_remaining_years=req.min_remaining_years,
            table=table,
            rate_grid=rate_grid,
            adjustment_mode=req.adjustment_mode,
            cash_flows=scenario_cfs,
            inflation_matrix=inflation_matrix,
            cf_table=_cf_t,
            cf_rate_grid=_cf_r,
            cf_scale_grid=_cf_s,
            cf_ref=_cf_ref,
            last_cf_year=_last_y,
        )
        if req.input_mode == "withdrawal":
            sim_kwargs["annual_withdrawal"] = req.annual_withdrawal
        else:
            sim_kwargs["initial_portfolio"] = req.initial_portfolio

        ip, aw, traj, wd = run_guardrail_simulation(**sim_kwargs)

        g_fr, g_sr = compute_effective_funded_ratio(
            wd, aw, req.retirement_years,
            consumption_floor=req.consumption_floor,
            trajectories=traj,
        )
        g_total = np.sum(wd, axis=1)
        return ScenarioResult(
            label=label,
            probability=0.0,
            success_rate=g_sr,
            funded_ratio=g_fr,
            median_final_portfolio=float(np.median(traj[:, -1])),
            median_total_consumption=float(np.median(g_total)),
            annual_withdrawal=aw,
            initial_portfolio=ip,
        )

    max_workers = max(1, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_base = pool.submit(_run_scenario, cash_flows, "base_case")
        futures = {
            pool.submit(_run_scenario, cfs, label): (label, prob)
            for label, cfs, prob in cf_scenarios
        }
        base = future_base.result()
        results = []
        for fut, (label, prob) in futures.items():
            r = fut.result()
            r.probability = prob
            results.append(r)

    return ScenarioAnalysisResponse(base_case=base, scenarios=results, mode=mode)


# ---------------------------------------------------------------------------
# 3c. POST /api/guardrail/sensitivity — 参数敏感性分析（龙卷风图）
# ---------------------------------------------------------------------------

@app.post("/api/guardrail/sensitivity", response_model=SensitivityAnalysisResponse)
@limiter.limit("5/minute")
def api_guardrail_sensitivity(request: Request, req: GuardrailRequest):
    """固定目标成功率，变动参数后用护栏策略计算最优提取额/初始资产。"""
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)
    cash_flows = _to_cash_flows(req.cash_flows)

    base_years = req.retirement_years
    stock_pct = req.allocation.domestic_stock + req.allocation.global_stock

    # Pre-generate base scenarios and tables once — reused for ip/aw/target variations
    base_alloc = _alloc_dict(req.allocation)
    base_er = _expense_dict(req.expense_ratios)
    base_scen, base_infl = pregenerate_return_scenarios(
        allocation=base_alloc, expense_ratios=base_er,
        retirement_years=base_years,
        min_block=req.min_block, max_block=req.max_block,
        num_simulations=req.num_simulations, returns_df=filtered,
        leverage=req.leverage, borrowing_spread=req.borrowing_spread,
        country_dfs=country_dfs, country_weights=country_weights,
    )
    base_rg, base_tbl = build_success_rate_table(base_scen)
    base_cf_tbl_r = None
    if cash_flows:
        base_rep = build_representative_cf_schedule(cash_flows, base_years, base_infl)
        base_cf_tbl_r = build_cf_aware_table(
            base_scen, base_rep,
            rate_segments=SCENARIO_CF_RATE_SEGMENTS,
            cf_scale_segments=SCENARIO_CF_SCALE_SEGMENTS,
            max_sims=SCENARIO_CF_MAX_SIMS,
            max_start_years=SCENARIO_MAX_START_YEARS,
        )
    _base_rg, _base_sg, _base_tbl, _base_ref, _base_ly = _unpack_cf_table(base_cf_tbl_r)

    def _run_with_tables(
        scen, infl, rg, tbl, cf_rg, cf_sg, cf_tbl, cf_ref, cf_ly,
        years, ip_override=None, aw_override=None, target_override=None,
    ):
        """Run guardrail simulation with pre-built scenarios and tables."""
        sim_kw = dict(
            scenarios=scen,
            target_success=target_override or req.target_success,
            upper_guardrail=req.upper_guardrail,
            lower_guardrail=req.lower_guardrail,
            adjustment_pct=req.adjustment_pct,
            retirement_years=years,
            min_remaining_years=req.min_remaining_years,
            table=tbl, rate_grid=rg,
            adjustment_mode=req.adjustment_mode,
            cash_flows=cash_flows, inflation_matrix=infl,
            cf_table=cf_tbl,
            cf_rate_grid=cf_rg,
            cf_scale_grid=cf_sg,
            cf_ref=cf_ref,
            last_cf_year=cf_ly,
        )
        if ip_override is not None:
            sim_kw["initial_portfolio"] = ip_override
        elif aw_override is not None:
            sim_kw["annual_withdrawal"] = aw_override
        elif req.input_mode == "withdrawal":
            sim_kw["annual_withdrawal"] = req.annual_withdrawal
        else:
            sim_kw["initial_portfolio"] = req.initial_portfolio

        r_ip, r_aw, r_traj, r_wd = run_guardrail_simulation(**sim_kw)

        _, r_sr = compute_effective_funded_ratio(
            r_wd, r_aw, years,
            consumption_floor=req.consumption_floor,
            trajectories=r_traj,
        )
        r_fr = compute_funded_ratio(r_traj, years)
        return r_ip, r_aw, r_sr, r_fr

    def _build_fresh_and_run(scen_alloc=None, scen_er=None, yrs=None):
        """Rebuild scenarios/tables from scratch (for allocation/years changes)."""
        alloc = scen_alloc or base_alloc
        er = scen_er or base_er
        years = yrs or base_years
        scen, infl = pregenerate_return_scenarios(
            allocation=alloc, expense_ratios=er,
            retirement_years=years,
            min_block=req.min_block, max_block=req.max_block,
            num_simulations=req.num_simulations, returns_df=filtered,
            leverage=req.leverage, borrowing_spread=req.borrowing_spread,
            country_dfs=country_dfs, country_weights=country_weights,
        )
        rg, tbl = build_success_rate_table(scen)
        cf_tbl_r = None
        if cash_flows:
            rep = build_representative_cf_schedule(cash_flows, years, infl)
            cf_tbl_r = build_cf_aware_table(
                scen, rep,
                rate_segments=SCENARIO_CF_RATE_SEGMENTS,
                cf_scale_segments=SCENARIO_CF_SCALE_SEGMENTS,
                max_sims=SCENARIO_CF_MAX_SIMS,
                max_start_years=SCENARIO_MAX_START_YEARS,
            )
        _rg, _sg, _tbl, _ref, _ly = _unpack_cf_table(cf_tbl_r)
        return _run_with_tables(scen, infl, rg, tbl, _rg, _sg, _tbl, _ref, _ly, years)

    base_ip, base_aw, base_sr, base_fr = _run_with_tables(
        base_scen, base_infl, base_rg, base_tbl,
        _base_rg, _base_sg, _base_tbl, _base_ref, _base_ly, base_years,
    )

    is_portfolio_mode = req.input_mode != "withdrawal"
    if is_portfolio_mode:
        param_specs = [
            ("initial_portfolio", "初始资产", base_ip, base_ip * 0.8, base_ip * 1.2),
            ("retirement_years", "退休年限", float(base_years), float(max(10, base_years - 10)), float(base_years + 10)),
            ("stock_allocation", "股票配置比例", stock_pct, max(0.0, stock_pct - 0.2), min(1.0, stock_pct + 0.2)),
            ("target_success", "目标成功率", req.target_success, max(0.5, req.target_success - 0.05), min(0.99, req.target_success + 0.05)),
        ]
    else:
        param_specs = [
            ("annual_withdrawal", "年提取额", base_aw, base_aw * 0.8, base_aw * 1.2),
            ("retirement_years", "退休年限", float(base_years), float(max(10, base_years - 10)), float(base_years + 10)),
            ("stock_allocation", "股票配置比例", stock_pct, max(0.0, stock_pct - 0.2), min(1.0, stock_pct + 0.2)),
            ("target_success", "目标成功率", req.target_success, max(0.5, req.target_success - 0.05), min(0.99, req.target_success + 0.05)),
        ]

    deltas = []
    for key, label, base_val, lo_val, hi_val in param_specs:
        lo_sr = hi_sr = base_sr
        lo_fr = hi_fr = base_fr
        lo_wd = hi_wd = base_aw

        for side, side_val in [("low", lo_val), ("high", hi_val)]:
            r_ip, r_aw, sr, fr = base_ip, base_aw, base_sr, base_fr

            if key in ("initial_portfolio", "annual_withdrawal", "target_success"):
                # Reuse base scenarios and tables — only the sim parameter changes
                kw = {}
                if key == "initial_portfolio":
                    kw["ip_override"] = side_val
                elif key == "annual_withdrawal":
                    kw["aw_override"] = side_val
                else:
                    kw["target_override"] = side_val
                r_ip, r_aw, sr, fr = _run_with_tables(
                    base_scen, base_infl, base_rg, base_tbl,
                    _base_rg, _base_sg, _base_tbl, _base_ref, _base_ly,
                    base_years, **kw,
                )
            elif key == "retirement_years":
                r_ip, r_aw, sr, fr = _build_fresh_and_run(yrs=int(side_val))
            elif key == "stock_allocation":
                new_stock = side_val
                if stock_pct > 0:
                    ratio = new_stock / stock_pct
                    dom_new = req.allocation.domestic_stock * ratio
                    glb_new = req.allocation.global_stock * ratio
                else:
                    dom_new = new_stock / 2.0
                    glb_new = new_stock / 2.0
                bond_new = max(0.0, 1.0 - dom_new - glb_new)
                if bond_new < 0:
                    total_s = dom_new + glb_new
                    dom_new /= total_s
                    glb_new /= total_s
                    bond_new = 0.0
                r_ip, r_aw, sr, fr = _build_fresh_and_run(
                    scen_alloc={"domestic_stock": dom_new, "global_stock": glb_new, "domestic_bond": bond_new},
                )

            if side == "low":
                lo_sr, lo_fr, lo_wd = sr, fr, r_aw
            else:
                hi_sr, hi_fr, hi_wd = sr, fr, r_aw

        deltas.append(SensitivityDelta(
            param_label=label,
            param_key=key,
            low_value=lo_val,
            high_value=hi_val,
            base_value=base_val,
            low_success_rate=lo_sr,
            high_success_rate=hi_sr,
            low_funded_ratio=lo_fr,
            high_funded_ratio=hi_fr,
            low_withdrawal=lo_wd,
            high_withdrawal=hi_wd,
        ))

    return SensitivityAnalysisResponse(
        base_success_rate=base_sr,
        base_funded_ratio=base_fr,
        base_withdrawal=base_aw,
        deltas=deltas,
    )


# ---------------------------------------------------------------------------
# 4. POST /api/guardrail/backtest
# ---------------------------------------------------------------------------

@app.post("/api/guardrail/backtest", response_model=BacktestResponse)
@limiter.limit("10/minute")
def api_backtest(request: Request, req: BacktestRequest):
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)

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
        country_weights=country_weights,
    )
    rate_grid, table = build_success_rate_table(scenarios)

    # 历史数据 — 回测需要具体国家的真实历史路径
    bt_country = req.backtest_country or req.country
    if bt_country == "ALL":
        raise HTTPException(400, "历史回测必须指定具体国家")

    # 如果回测国家与 MC 国家不同（如 MC 用 ALL，回测用 USA），单独获取该国数据
    if bt_country != req.country or req.country == "ALL":
        hist_filtered = _filter_df(bt_country, req.data_start_year, req.data_source)
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

    # 3D 现金流感知查找表
    bt_cf_result = None
    if cash_flows:
        rep_schedule = build_representative_cf_schedule(
            cash_flows, req.retirement_years,
        )
        bt_cf_result = build_cf_aware_table(scenarios, rep_schedule)
    _bt_cf_rg, _bt_cf_sg, _bt_cf_tbl, _bt_cf_ref, _bt_last_cf_y = _unpack_cf_table(bt_cf_result)

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
        cf_table=_bt_cf_tbl,
        cf_rate_grid=_bt_cf_rg,
        cf_scale_grid=_bt_cf_sg,
        cf_ref=_bt_cf_ref,
        last_cf_year=_bt_last_cf_y,
    )

    n = result["years_simulated"]
    year_labels = [int(req.hist_start_year + i) for i in range(n + 1)]

    # 单路径绩效指标
    path_metrics = compute_single_path_metrics(
        hist_returns[:n], hist_inflation[:n],
    )

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
        path_metrics=path_metrics,
    )


# ---------------------------------------------------------------------------
# 4b. POST /api/guardrail/backtest-batch  — 批量历史回测
# ---------------------------------------------------------------------------

@app.post("/api/guardrail/backtest-batch", response_model=GuardrailBatchBacktestResponse)
@limiter.limit("5/minute")
def api_guardrail_batch_backtest(request: Request, req: GuardrailBatchBacktestRequest):
    """遍历所有有效 (国家, 起始年) 进行 guardrail 历史回测。"""
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)

    # 构建成功率查找表（需要 MC 场景）
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
        country_weights=country_weights,
    )
    rate_grid, table = build_success_rate_table(scenarios)

    batch_cash_flows = _to_cash_flows(req.cash_flows)

    # 3D 现金流感知查找表
    batch_cf_result = None
    if batch_cash_flows:
        rep_schedule = build_representative_cf_schedule(
            batch_cash_flows, req.retirement_years,
        )
        batch_cf_result = build_cf_aware_table(scenarios, rep_schedule)
    _batch_cf_rg, _batch_cf_sg, _batch_cf_tbl, _batch_cf_ref, _batch_last_cf_y = _unpack_cf_table(batch_cf_result)

    # 确定回测用的国家数据
    if country_dfs is not None:
        bt_country_dfs = country_dfs
        bt_filtered = None
    else:
        bt_country_dfs = None
        bt_filtered = filtered

    result = run_guardrail_batch_backtest(
        country_dfs=bt_country_dfs,
        filtered_df=bt_filtered,
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        initial_portfolio=req.initial_portfolio,
        annual_withdrawal=req.annual_withdrawal,
        retirement_years=req.retirement_years,
        target_success=req.target_success,
        upper_guardrail=req.upper_guardrail,
        lower_guardrail=req.lower_guardrail,
        adjustment_pct=req.adjustment_pct,
        adjustment_mode=req.adjustment_mode,
        min_remaining_years=req.min_remaining_years,
        baseline_rate=req.baseline_rate,
        table=table,
        rate_grid=rate_grid,
        cash_flows=batch_cash_flows,
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        cf_table=_batch_cf_tbl,
        cf_rate_grid=_batch_cf_rg,
        cf_scale_grid=_batch_cf_sg,
        cf_ref=_batch_cf_ref,
        last_cf_year=_batch_last_cf_y,
        consumption_floor=req.consumption_floor,
    )

    # 构建路径摘要
    path_summaries = []
    for p in result["paths"]:
        path_summaries.append(GuardrailBatchPathSummary(
            country=p["country"],
            start_year=p["start_year"],
            years_simulated=p["years_simulated"],
            is_complete=p["is_complete"],
            g_survived=p["g_survived"],
            b_survived=p["b_survived"],
            g_final_portfolio=p["g_final_portfolio"],
            b_final_portfolio=p["b_final_portfolio"],
            g_total_consumption=p["g_total_consumption"],
            b_total_consumption=p["b_total_consumption"],
            num_adjustments=p["num_adjustments"],
            year_labels=p["year_labels"],
            g_portfolio=p["g_portfolio"],
            g_withdrawals=p["g_withdrawals"],
            g_success_rates=p["g_success_rates"],
            b_portfolio=p["b_portfolio"],
            b_withdrawals=p["b_withdrawals"],
            adjustment_events=[AdjustmentEvent(**e) for e in p["adjustment_events"]],
            path_metrics=p["path_metrics"],
        ))

    return GuardrailBatchBacktestResponse(
        num_paths=result["num_paths"],
        num_complete=result["num_complete"],
        g_success_rate=result["g_success_rate"],
        g_funded_ratio=result["g_funded_ratio"],
        b_success_rate=result["b_success_rate"],
        b_funded_ratio=result["b_funded_ratio"],
        g_percentile_trajectories=result["g_percentile_trajectories"],
        b_percentile_trajectories=result["b_percentile_trajectories"],
        g_withdrawal_percentiles=result["g_withdrawal_percentiles"],
        b_withdrawal_percentiles=result["b_withdrawal_percentiles"],
        paths=path_summaries,
    )


# ---------------------------------------------------------------------------
# 5. POST /api/allocation-sweep
# ---------------------------------------------------------------------------

@app.post("/api/allocation-sweep", response_model=AllocationSweepResponse)
@limiter.limit("10/minute")
def api_allocation_sweep(request: Request, req: AllocationSweepRequest):
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)

    raw = pregenerate_raw_scenarios(
        expense_ratios=_expense_dict(req.expense_ratios),
        retirement_years=req.retirement_years,
        min_block=req.min_block,
        max_block=req.max_block,
        num_simulations=req.num_simulations,
        returns_df=filtered,
        country_dfs=country_dfs,
        country_weights=country_weights,
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
        retirement_age=req.retirement_age,
        cash_flows=cash_flows,
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
    )

    alloc_results = [AllocationResult(**r) for r in raw_results]
    best = max(alloc_results, key=lambda x: x.funded_ratio)

    return AllocationSweepResponse(
        results=alloc_results,
        best=best,
    )


# ---------------------------------------------------------------------------
# 6. GET /api/returns
# ---------------------------------------------------------------------------

@app.get("/api/returns", response_model=ReturnsResponse)
def api_returns(country: str = "USA", data_start_year: int = 1900, data_source: str = "jst"):
    df = _get_returns_df(data_source)
    filtered = filter_by_country(df, country, data_start_year)
    return ReturnsResponse(
        years=filtered["Year"].tolist(),
        domestic_stock=filtered["Domestic_Stock"].tolist(),
        global_stock=filtered["Global_Stock"].tolist(),
        domestic_bond=filtered["Domestic_Bond"].tolist(),
        inflation=filtered["Inflation"].tolist(),
    )


# ---------------------------------------------------------------------------
# 7. 买房 vs 租房
# ---------------------------------------------------------------------------

@app.get("/api/buy-vs-rent/countries", response_model=HousingCountriesResponse)
def api_housing_countries():
    countries = get_housing_available_countries("jst")
    return HousingCountriesResponse(
        countries=[HousingCountryInfo(**c) for c in countries]
    )


@app.post("/api/buy-vs-rent/simple", response_model=BuyVsRentSimpleResponse)
@limiter.limit("20/minute")
def api_buy_vs_rent_simple(request: Request, req: BuyVsRentSimpleRequest):
    result = run_simple_buy_vs_rent(
        home_price=req.home_price,
        down_payment_pct=req.down_payment_pct,
        mortgage_term=req.mortgage_term,
        mortgage_rate=req.mortgage_rate,
        buying_cost_pct=req.buying_cost_pct,
        selling_cost_pct=req.selling_cost_pct,
        property_tax_pct=req.property_tax_pct,
        maintenance_pct=req.maintenance_pct,
        insurance_annual=req.insurance_annual,
        annual_rent=req.annual_rent,
        rent_growth_rate=req.rent_growth_rate,
        home_appreciation_rate=req.home_appreciation_rate,
        investment_return_rate=req.investment_return_rate,
        inflation_rate=req.inflation_rate,
        analysis_years=req.analysis_years,
    )
    return BuyVsRentSimpleResponse(**result)


@app.post("/api/buy-vs-rent/simulate", response_model=BuyVsRentMCResponse)
@limiter.limit("10/minute")
def api_buy_vs_rent_mc(request: Request, req: BuyVsRentMCRequest):
    df = _get_returns_df("jst")

    alloc_dict = req.allocation.model_dump()
    expense_dict = req.expense_ratios.model_dump()

    if req.country == "ALL":
        country_dfs = get_housing_country_dfs(df, req.data_start_year)
        if not country_dfs:
            raise HTTPException(400, "No countries with housing data available")
        country_weights = _resolve_country_weights_for_housing(req, country_dfs)
        filtered_df = None
    else:
        filtered_df = filter_housing_data(df, req.country, req.data_start_year)
        if len(filtered_df) < 10:
            raise HTTPException(
                400,
                f"Insufficient housing data for country {req.country} "
                f"(need 10+ years, got {len(filtered_df)})"
            )
        country_dfs = None
        country_weights = None

    result = run_buy_vs_rent_mc(
        home_price=req.home_price,
        down_payment_pct=req.down_payment_pct,
        mortgage_term=req.mortgage_term,
        mortgage_rate_spread=req.mortgage_rate_spread,
        buying_cost_pct=req.buying_cost_pct,
        selling_cost_pct=req.selling_cost_pct,
        property_tax_pct=req.property_tax_pct,
        maintenance_pct=req.maintenance_pct,
        insurance_annual=req.insurance_annual,
        annual_rent=req.annual_rent,
        allocation=alloc_dict,
        expense_ratios=expense_dict,
        analysis_years=req.analysis_years,
        num_simulations=req.num_simulations,
        min_block=req.min_block,
        max_block=req.max_block,
        returns_df=filtered_df,
        country_dfs=country_dfs,
        country_weights=country_weights,
        override_home_appreciation=req.override_home_appreciation,
        override_rent_growth=req.override_rent_growth,
        override_mortgage_rate=req.override_mortgage_rate,
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
    )
    return BuyVsRentMCResponse(**result)


def _resolve_country_weights_for_housing(
    req,
    country_dfs: dict,
) -> dict[str, float] | None:
    """为有 housing 数据的国家计算池化权重。"""
    if req.pooling_method == "gdp_sqrt":
        all_weights = get_gdp_weights(list(country_dfs.keys()))
        weights = {iso: all_weights.get(iso, 1.0) for iso in country_dfs}
        total = sum(weights.values())
        if total > 0:
            return {iso: w / total for iso, w in weights.items()}
    return None


def _prepare_housing_data(req, df):
    """Shared helper: resolve country_dfs / filtered_df for housing endpoints."""
    if req.country == "ALL":
        country_dfs = get_housing_country_dfs(df, req.data_start_year)
        if not country_dfs:
            raise HTTPException(400, "No countries with housing data available")
        country_weights = _resolve_country_weights_for_housing(req, country_dfs)
        return None, country_dfs, country_weights
    else:
        filtered_df = filter_housing_data(df, req.country, req.data_start_year)
        if len(filtered_df) < 10:
            raise HTTPException(
                400,
                f"Insufficient housing data for country {req.country} "
                f"(need 10+ years, got {len(filtered_df)})"
            )
        return filtered_df, None, None


# ---------------------------------------------------------------------------
# 8. 盈亏平衡房价查找
# ---------------------------------------------------------------------------

@app.post("/api/buy-vs-rent/breakeven/simple", response_model=BreakevenResponse)
@limiter.limit("20/minute")
def api_breakeven_simple(request: Request, req: BreakevenSimpleRequest):
    result = find_breakeven_price_simple(
        down_payment_pct=req.down_payment_pct,
        mortgage_term=req.mortgage_term,
        mortgage_rate=req.mortgage_rate,
        buying_cost_pct=req.buying_cost_pct,
        selling_cost_pct=req.selling_cost_pct,
        property_tax_pct=req.property_tax_pct,
        maintenance_pct=req.maintenance_pct,
        insurance_annual=req.insurance_annual,
        annual_rent=req.annual_rent,
        rent_growth_rate=req.rent_growth_rate,
        home_appreciation_rate=req.home_appreciation_rate,
        investment_return_rate=req.investment_return_rate,
        inflation_rate=req.inflation_rate,
        analysis_years=req.analysis_years,
        price_low=req.price_low,
        price_high=req.price_high,
        auto_estimate_ha=req.auto_estimate_ha,
        fair_pe=req.fair_pe,
        reversion_years=req.reversion_years,
    )
    return BreakevenResponse(**result)


@app.post("/api/buy-vs-rent/breakeven/mc", response_model=BreakevenResponse)
@limiter.limit("5/minute")
def api_breakeven_mc(request: Request, req: BreakevenMCRequest):
    df = _get_returns_df("jst")
    filtered_df, country_dfs, country_weights = _prepare_housing_data(req, df)

    result = find_breakeven_price_mc(
        down_payment_pct=req.down_payment_pct,
        mortgage_term=req.mortgage_term,
        mortgage_rate_spread=req.mortgage_rate_spread,
        buying_cost_pct=req.buying_cost_pct,
        selling_cost_pct=req.selling_cost_pct,
        property_tax_pct=req.property_tax_pct,
        maintenance_pct=req.maintenance_pct,
        insurance_annual=req.insurance_annual,
        annual_rent=req.annual_rent,
        allocation=req.allocation.model_dump(),
        expense_ratios=req.expense_ratios.model_dump(),
        analysis_years=req.analysis_years,
        num_simulations=req.num_simulations,
        min_block=req.min_block,
        max_block=req.max_block,
        returns_df=filtered_df,
        country_dfs=country_dfs,
        country_weights=country_weights,
        override_home_appreciation=req.override_home_appreciation,
        override_rent_growth=req.override_rent_growth,
        override_mortgage_rate=req.override_mortgage_rate,
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        target_win_pct=req.target_win_pct,
        price_low=req.price_low,
        price_high=req.price_high,
    )
    return BreakevenResponse(**result)


# ---------------------------------------------------------------------------
# 9. FIRE 积累阶段计算器
# ---------------------------------------------------------------------------

@app.post("/api/accumulation", response_model=AccumulationResponse)
@limiter.limit("5/minute")
def api_accumulation(request: Request, req: AccumulationRequest):
    filtered, country_dfs = _resolve_data(req)
    _validate_data_sufficient(filtered, country_dfs)

    country_weights = _resolve_country_weights(req, country_dfs)
    cf = _to_cash_flows(req.cash_flows)

    result = run_accumulation(
        current_age=req.current_age,
        life_expectancy=req.life_expectancy,
        current_portfolio=req.current_portfolio,
        annual_income=req.annual_income,
        annual_expenses=req.annual_expenses,
        income_growth_rate=req.income_growth_rate,
        retirement_spending=req.retirement_spending,
        target_success_rate=req.target_success_rate,
        allocation=_alloc_dict(req.allocation),
        expense_ratios=_expense_dict(req.expense_ratios),
        withdrawal_strategy=req.withdrawal_strategy,
        dynamic_ceiling=req.dynamic_ceiling,
        dynamic_floor=req.dynamic_floor,
        num_simulations=req.num_simulations,
        min_block=req.min_block,
        max_block=req.max_block,
        returns_df=filtered,
        cash_flows=cf,
        leverage=req.leverage,
        borrowing_spread=req.borrowing_spread,
        country_dfs=country_dfs,
        country_weights=country_weights,
        expense_growth_rate=req.expense_growth_rate,
        auto_retirement_spending=req.auto_retirement_spending,
    )

    return AccumulationResponse(**result)
