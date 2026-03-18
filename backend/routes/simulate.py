"""Simulation endpoints: /api/simulate, /api/simulate/backtest, /api/simulate/backtest-batch,
/api/simulate/scenarios, /api/simulate/sensitivity, /api/sweep."""

from __future__ import annotations

import os

import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from deps import (
    alloc_dict,
    expense_dict,
    filter_df,
    resolve_country_weights,
    resolve_data,
    streaming,
    to_cash_flows,
    validate_data_sufficient,
)
from schemas import (
    ScenarioResult,
    SimBacktestRequest,
    SimBacktestResponse,
    SimBatchBacktestRequest,
    SimBatchBacktestResponse,
    SimBatchPathSummary,
    SimulationRequest,
    SweepRequest,
    SweepResponse,
    TargetRateResult,
)
from simulator.backtest_batch import run_sim_batch_backtest
from simulator.cashflow import CashFlowItem, enumerate_cf_per_group, enumerate_cf_scenarios
from simulator.config import TARGET_SUCCESS_RATES, is_low_memory
from simulator.monte_carlo import run_simulation, run_simulation_from_matrix, run_simple_historical_backtest
from simulator.portfolio import compute_real_portfolio_returns
from simulator.statistics import (
    compute_funded_ratio,
    compute_portfolio_metrics,
    compute_single_path_metrics,
    compute_statistics,
    compute_success_rate,
    final_values_summary_table,
)
from simulator.sweep import (
    interpolate_targets,
    pregenerate_raw_scenarios,
    pregenerate_return_scenarios,
    raw_to_combined,
    sweep_withdrawal_rates,
)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# POST /api/simulate
# ---------------------------------------------------------------------------

@router.post("/api/simulate")
@limiter.limit("10/minute")
def api_simulate(request: Request, req: SimulationRequest):
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    def _generate():
        yield {"type": "progress", "stage": "bootstrap", "pct": 10}

        country_weights = resolve_country_weights(req, country_dfs)

        trajectories, withdrawals, real_ret_mat, infl_mat = run_simulation(
            initial_portfolio=req.initial_portfolio,
            annual_withdrawal=req.annual_withdrawal,
            allocation=alloc_dict(req.allocation),
            expense_ratios=expense_dict(req.expense_ratios),
            retirement_years=req.retirement_years,
            min_block=req.min_block,
            max_block=req.max_block,
            num_simulations=req.num_simulations,
            returns_df=filtered,
            seed=req.seed,
            withdrawal_strategy=req.withdrawal_strategy,
            dynamic_ceiling=req.dynamic_ceiling,
            dynamic_floor=req.dynamic_floor,
            retirement_age=req.retirement_age,
            cash_flows=to_cash_flows(req.cash_flows),
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
            glide_path_end_allocation=alloc_dict(req.glide_path_end_allocation) if req.glide_path_enabled else None,
            glide_path_years=req.glide_path_years,
        )

        yield {"type": "progress", "stage": "statistics", "pct": 80}

        results = compute_statistics(trajectories, req.retirement_years, withdrawals)
        summary_df = final_values_summary_table(results)
        port_metrics = compute_portfolio_metrics(real_ret_mat, infl_mat)

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

        yield {"type": "result", "data": {
            "success_rate": results.success_rate,
            "funded_ratio": results.funded_ratio,
            "final_median": results.final_median,
            "final_mean": results.final_mean,
            "final_min": results.final_min,
            "final_max": results.final_max,
            "final_percentiles": final_pcts,
            "percentile_trajectories": pct_traj,
            "withdrawal_percentile_trajectories": wd_pct_traj,
            "withdrawal_mean_trajectory": wd_mean_traj,
            "final_values_summary": summary_df.to_dict("records"),
            "initial_withdrawal_rate": (
                req.annual_withdrawal / req.initial_portfolio if req.initial_portfolio > 0 else 0
            ),
            "portfolio_metrics": port_metrics,
        }}

    return streaming(_generate())


# ---------------------------------------------------------------------------
# POST /api/simulate/backtest
# ---------------------------------------------------------------------------

@router.post("/api/simulate/backtest", response_model=SimBacktestResponse)
@limiter.limit("10/minute")
def api_sim_backtest(request: Request, req: SimBacktestRequest):
    """Single historical path backtest (no bootstrap)."""
    country = req.country
    if req.data_source == "fire_dataset" and country == "ALL":
        country = "USA"
    if country == "ALL":
        raise HTTPException(400, "历史回测必须选择具体国家，不能使用 ALL 池化模式")

    filtered = filter_df(country, req.data_start_year, req.data_source)
    if len(filtered) < 2:
        raise HTTPException(400, "可用数据不足")

    filtered = filtered[filtered["Year"] >= req.hist_start_year].sort_values("Year").reset_index(drop=True)
    n_avail = len(filtered)
    if n_avail == 0:
        raise HTTPException(400, f"所选国家在 {req.hist_start_year} 年之后没有可用数据")

    n_years = min(req.retirement_years, n_avail)
    sampled = filtered.iloc[:n_years]
    year_labels = [int(sampled["Year"].iloc[0] - 1)] + sampled["Year"].tolist()

    real_returns = compute_real_portfolio_returns(
        sampled, alloc_dict(req.allocation), expense_dict(req.expense_ratios),
        leverage=req.leverage, borrowing_spread=req.borrowing_spread,
    )

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
        cash_flows=to_cash_flows(req.cash_flows),
        inflation_series=inflation_series,
        declining_rate=req.declining_rate,
        declining_start_age=req.declining_start_age,
        smile_decline_rate=req.smile_decline_rate,
        smile_decline_start_age=req.smile_decline_start_age,
        smile_min_age=req.smile_min_age,
        smile_increase_rate=req.smile_increase_rate,
    )

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
# POST /api/simulate/backtest-batch
# ---------------------------------------------------------------------------

@router.post("/api/simulate/backtest-batch", response_model=SimBatchBacktestResponse)
@limiter.limit("5/minute")
def api_sim_batch_backtest(request: Request, req: SimBatchBacktestRequest):
    """Batch historical backtest across all valid (country, start_year) combos."""
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    result = run_sim_batch_backtest(
        country_dfs=country_dfs,
        filtered_df=filtered if country_dfs is None else None,
        allocation=alloc_dict(req.allocation),
        expense_ratios=expense_dict(req.expense_ratios),
        initial_portfolio=req.initial_portfolio,
        annual_withdrawal=req.annual_withdrawal,
        retirement_years=req.retirement_years,
        withdrawal_strategy=req.withdrawal_strategy,
        dynamic_ceiling=req.dynamic_ceiling,
        dynamic_floor=req.dynamic_floor,
        retirement_age=req.retirement_age,
        cash_flows=to_cash_flows(req.cash_flows),
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
# POST /api/simulate/scenarios
# ---------------------------------------------------------------------------

@router.post("/api/simulate/scenarios")
@limiter.limit("5/minute")
def api_simulate_scenarios(request: Request, req: SimulationRequest):
    """Enumerate probabilistic cash flow combinations, simulate with chosen strategy.

    All scenarios share a single bootstrap return matrix (Common Random Numbers).
    """
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    cash_flows = to_cash_flows(req.cash_flows)
    if not cash_flows:
        raise HTTPException(400, "需要至少一个自定义现金流")

    mode = "full"
    cf_scenarios = enumerate_cf_scenarios(cash_flows, max_combinations=32)
    if not cf_scenarios:
        cf_scenarios = enumerate_cf_per_group(cash_flows)
        mode = "per_group"
        if not cf_scenarios:
            raise HTTPException(400, "没有概率分组现金流。请检查现金流设置。")

    def _generate():
        yield {"type": "progress", "stage": "bootstrap", "pct": 10}

        country_weights = resolve_country_weights(req, country_dfs)

        scenarios, inflation_matrix = pregenerate_return_scenarios(
            allocation=alloc_dict(req.allocation),
            expense_ratios=expense_dict(req.expense_ratios),
            retirement_years=req.retirement_years,
            min_block=req.min_block,
            max_block=req.max_block,
            num_simulations=req.num_simulations,
            returns_df=filtered,
            seed=req.seed,
            leverage=req.leverage,
            borrowing_spread=req.borrowing_spread,
            country_dfs=country_dfs,
            country_weights=country_weights,
        )

        total = 1 + len(cf_scenarios)
        yield {"type": "progress", "stage": "scenario_run", "pct": 20, "current": 0, "total": total}

        def _run_scenario(
            scenario_cfs: list[CashFlowItem] | None,
            label: str,
        ) -> ScenarioResult:
            traj, wd, _, _ = run_simulation_from_matrix(
                real_returns_matrix=scenarios,
                inflation_matrix=inflation_matrix,
                initial_portfolio=req.initial_portfolio,
                annual_withdrawal=req.annual_withdrawal,
                retirement_years=req.retirement_years,
                withdrawal_strategy=req.withdrawal_strategy,
                dynamic_ceiling=req.dynamic_ceiling,
                dynamic_floor=req.dynamic_floor,
                retirement_age=req.retirement_age,
                cash_flows=scenario_cfs,
                declining_rate=req.declining_rate,
                declining_start_age=req.declining_start_age,
                smile_decline_rate=req.smile_decline_rate,
                smile_decline_start_age=req.smile_decline_start_age,
                smile_min_age=req.smile_min_age,
                smile_increase_rate=req.smile_increase_rate,
            )
            sr = compute_success_rate(traj, req.retirement_years)
            fr = compute_funded_ratio(traj, req.retirement_years)
            total_wd = np.sum(wd, axis=1)
            return ScenarioResult(
                label=label,
                probability=0.0,
                success_rate=sr,
                funded_ratio=fr,
                median_final_portfolio=float(np.median(traj[:, -1])),
                median_total_consumption=float(np.median(total_wd)),
                annual_withdrawal=req.annual_withdrawal,
                initial_portfolio=req.initial_portfolio,
            )

        completed = 0
        max_workers = 1 if is_low_memory() else max(1, os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_base = pool.submit(_run_scenario, cash_flows, "base_case")
            futures = {
                pool.submit(_run_scenario, cfs, label): (label, prob)
                for label, cfs, prob in cf_scenarios
            }
            all_futures = {future_base: None, **futures}

            base = None
            results = []
            for fut in as_completed(all_futures):
                completed += 1
                pct = 20 + int(75 * completed / total)
                yield {"type": "progress", "stage": "scenario_run", "pct": pct, "current": completed, "total": total}
                if fut is future_base:
                    base = fut.result()
                else:
                    label, prob = futures[fut]
                    r = fut.result()
                    r.probability = prob
                    results.append(r)

        yield {"type": "result", "data": {
            "base_case": base.model_dump() if hasattr(base, "model_dump") else base.__dict__,
            "scenarios": [s.model_dump() if hasattr(s, "model_dump") else s.__dict__ for s in results],
            "mode": mode,
        }}

    return streaming(_generate())


# ---------------------------------------------------------------------------
# POST /api/sweep
# ---------------------------------------------------------------------------

@router.post("/api/sweep")
@limiter.limit("10/minute")
def api_sweep(request: Request, req: SweepRequest):
    def _generate():
        yield {"type": "progress", "stage": "bootstrap", "pct": 5}
        filtered, country_dfs = resolve_data(req)
        validate_data_sufficient(filtered, country_dfs)
        country_weights = resolve_country_weights(req, country_dfs)

        scenarios, inflation_matrix = pregenerate_return_scenarios(
            allocation=alloc_dict(req.allocation),
            expense_ratios=expense_dict(req.expense_ratios),
            retirement_years=req.retirement_years,
            min_block=req.min_block,
            max_block=req.max_block,
            num_simulations=req.num_simulations,
            returns_df=filtered,
            seed=req.seed,
            leverage=req.leverage,
            borrowing_spread=req.borrowing_spread,
            country_dfs=country_dfs,
            country_weights=country_weights,
        )

        cash_flows = to_cash_flows(req.cash_flows)

        yield {"type": "progress", "stage": "sweep", "pct": 30}
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
            declining_rate=req.declining_rate,
            declining_start_age=req.declining_start_age,
            smile_decline_rate=req.smile_decline_rate,
            smile_decline_start_age=req.smile_decline_start_age,
            smile_min_age=req.smile_min_age,
            smile_increase_rate=req.smile_increase_rate,
        )

        yield {"type": "progress", "stage": "statistics", "pct": 85}

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
                    target_success=f"{t:.0%}", rate=None, annual_withdrawal=None, needed_portfolio=None,
                ))

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
                    target_success=f"{t:.0%}", rate=None, annual_withdrawal=None, needed_portfolio=None,
                ))

        yield {"type": "result", "data": SweepResponse(
            rates=rates.tolist(),
            success_rates=success_rates.tolist(),
            funded_ratios=funded_ratios.tolist(),
            target_results=target_results,
            target_results_funded=target_results_funded,
        ).model_dump()}

    return streaming(_generate())
