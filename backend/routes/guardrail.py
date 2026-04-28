"""Guardrail endpoints: /api/guardrail, /api/guardrail/scenarios,
/api/guardrail/sensitivity, /api/guardrail/backtest, /api/guardrail/backtest-batch."""

from __future__ import annotations

import gc
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
    unpack_cf_table,
    validate_data_sufficient,
)
from schemas import (
    AdjustmentEvent,
    BacktestRequest,
    BacktestResponse,
    GuardrailBatchBacktestRequest,
    GuardrailBatchBacktestResponse,
    GuardrailBatchPathSummary,
    GuardrailRequest,
    ScenarioResult,
)
from simulator.backtest_batch import run_guardrail_batch_backtest
from simulator.cashflow import (
    CashFlowItem,
    build_representative_cf_schedule,
    enumerate_cf_per_group,
    enumerate_cf_scenarios,
)
from simulator.config import (
    SCENARIO_CF_MAX_SIMS,
    SCENARIO_CF_RATE_SEGMENTS,
    SCENARIO_CF_SCALE_SEGMENTS,
    SCENARIO_MAX_START_YEARS,
    is_low_memory,
)
from simulator.guardrail import (
    apply_guardrail_adjustment,
    build_cf_aware_table,
    build_success_rate_table,
    find_rate_for_target,
    lookup_cf_aware_success_rate,
    run_fixed_baseline,
    run_guardrail_simulation,
    run_historical_backtest,
)
from simulator.portfolio import compute_real_portfolio_returns
from simulator.statistics import (
    compute_effective_funded_ratio,
    compute_funded_ratio,
    compute_portfolio_metrics,
    compute_single_path_metrics,
    compute_success_rate,
)
from simulator.sweep import (
    pregenerate_raw_scenarios,
    pregenerate_return_scenarios,
    raw_to_combined,
)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

_PROGRESSIVE_CPU_THRESHOLD = 4


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _run_guardrail_and_build_result(
    scenarios, inflation_matrix, table, rate_grid,
    cash_flows, cf_table_result, req,
):
    """Run guardrail simulation + baseline comparison + stats, return full result dict."""
    _cf_rg, _cf_sg, _cf_tbl, _cf_ref, _last_cf_y = unpack_cf_table(cf_table_result)

    sim_kwargs = dict(
        scenarios=scenarios,
        target_success=req.target_success,
        upper_guardrail=req.upper_guardrail,
        lower_guardrail=req.lower_guardrail,
        adjustment_pct=req.adjustment_pct,
        retirement_years=req.retirement_years,
        min_remaining_years=req.min_remaining_years,
        table=table, rate_grid=rate_grid,
        adjustment_mode=req.adjustment_mode,
        cash_flows=cash_flows, inflation_matrix=inflation_matrix,
        cf_table=_cf_tbl, cf_rate_grid=_cf_rg,
        cf_scale_grid=_cf_sg, cf_ref=_cf_ref, last_cf_year=_last_cf_y,
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
        consumption_floor=req.consumption_floor, trajectories=traj_g,
        consumption_floor_amount=req.consumption_floor_amount,
    )
    b_success = compute_success_rate(traj_b, req.retirement_years)
    b_fr = compute_funded_ratio(traj_b, req.retirement_years)
    initial_rate = annual_wd / init_portfolio if init_portfolio > 0 else 0
    baseline_wd = init_portfolio * req.baseline_rate

    band_pcts = [10, 25, 50, 75, 90]
    g_pct_traj = {str(p): np.percentile(traj_g, p, axis=0).tolist() for p in band_pcts}
    b_pct_traj = {str(p): np.percentile(traj_b, p, axis=0).tolist() for p in band_pcts}
    g_wd_pcts = {str(p): np.percentile(wd_g, p, axis=0).tolist() for p in band_pcts}
    b_wd_pcts = {str(p): np.percentile(wd_b, p, axis=0).tolist() for p in band_pcts}

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

    port_metrics = compute_portfolio_metrics(scenarios, inflation_matrix)

    remaining_y0 = min(req.retirement_years, table.shape[1] - 1)

    if cf_table_result is not None:
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

    return {
        "initial_portfolio": init_portfolio,
        "annual_withdrawal": annual_wd,
        "initial_rate": initial_rate,
        "g_success_rate": g_success,
        "g_funded_ratio": g_fr,
        "g_percentile_trajectories": g_pct_traj,
        "g_withdrawal_percentiles": g_wd_pcts,
        "b_success_rate": b_success,
        "b_funded_ratio": b_fr,
        "b_percentile_trajectories": b_pct_traj,
        "b_withdrawal_percentiles": b_wd_pcts,
        "baseline_annual_wd": baseline_wd,
        "upper_trigger_portfolio": upper_trigger_port,
        "upper_trigger_withdrawal": upper_trigger_wd,
        "lower_trigger_portfolio": lower_trigger_port,
        "lower_trigger_withdrawal": lower_trigger_wd,
        "metrics": metrics,
        "portfolio_metrics": port_metrics,
    }


# ---------------------------------------------------------------------------
# POST /api/guardrail
# ---------------------------------------------------------------------------

@router.post("/api/guardrail")
@limiter.limit("10/minute")
def api_guardrail(request: Request, req: GuardrailRequest):
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    def _generate():
        yield {"type": "progress", "stage": "bootstrap", "pct": 5}

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

        yield {"type": "progress", "stage": "table_2d", "pct": 20}
        rate_grid, table = build_success_rate_table(scenarios)

        cash_flows = to_cash_flows(req.cash_flows)
        available_cpus = os.cpu_count() or 1
        progressive = cash_flows and (available_cpus < _PROGRESSIVE_CPU_THRESHOLD or is_low_memory())

        if progressive:
            yield {"type": "progress", "stage": "simulation", "pct": 35}
            result_2d = _run_guardrail_and_build_result(
                scenarios, inflation_matrix, table, rate_grid,
                cash_flows, None, req,
            )
            yield {"type": "result", "data": result_2d, "preliminary": True}
            yield {"type": "progress", "stage": "table_3d", "pct": 55}

        cf_table_result = None
        if cash_flows:
            if not progressive:
                yield {"type": "progress", "stage": "table_3d", "pct": 40}
            rep_schedule = build_representative_cf_schedule(
                cash_flows, req.retirement_years, inflation_matrix,
            )
            cf_table_result = build_cf_aware_table(scenarios, rep_schedule)
            gc.collect()

        yield {"type": "progress", "stage": "refining" if progressive else "simulation", "pct": 85}
        result = _run_guardrail_and_build_result(
            scenarios, inflation_matrix, table, rate_grid,
            cash_flows, cf_table_result, req,
        )
        yield {"type": "result", "data": result}

    return streaming(_generate())


# ---------------------------------------------------------------------------
# POST /api/guardrail/scenarios
# ---------------------------------------------------------------------------

@router.post("/api/guardrail/scenarios")
@limiter.limit("5/minute")
def api_guardrail_scenarios(request: Request, req: GuardrailRequest):
    """Enumerate probabilistic cash flow combinations for guardrail strategy."""
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
        yield {"type": "progress", "stage": "bootstrap", "pct": 5}

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

        yield {"type": "progress", "stage": "table_2d", "pct": 20}
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

            _cf_r, _cf_s, _cf_t, _cf_ref, _last_y = unpack_cf_table(cf_table_r)

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
                consumption_floor_amount=req.consumption_floor_amount,
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

        total = 1 + len(cf_scenarios)
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
                pct = 25 + int(70 * completed / total)
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
# POST /api/guardrail/sensitivity
# ---------------------------------------------------------------------------

@router.post("/api/guardrail/sensitivity")
@limiter.limit("5/minute")
def api_guardrail_sensitivity(request: Request, req: GuardrailRequest):
    """Parameter sensitivity analysis for guardrail strategy.

    Uses Common Random Numbers — single bootstrap generates raw matrices,
    all variants share the same random sequences.
    """
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    def _generate():
        yield {"type": "progress", "stage": "bootstrap", "pct": 5}

        country_weights = resolve_country_weights(req, country_dfs)
        cash_flows = to_cash_flows(req.cash_flows)

        base_years = req.retirement_years
        stock_pct = req.allocation.domestic_stock + req.allocation.global_stock
        base_alloc = alloc_dict(req.allocation)
        base_er = expense_dict(req.expense_ratios)

        max_years = base_years + 10
        raw = pregenerate_raw_scenarios(
            expense_ratios=base_er,
            retirement_years=max_years,
            min_block=req.min_block, max_block=req.max_block,
            num_simulations=req.num_simulations, returns_df=filtered,
            seed=req.seed,
            country_dfs=country_dfs, country_weights=country_weights,
        )

        yield {"type": "progress", "stage": "table_2d", "pct": 15}

        def _build_tables(alloc, years):
            scen = raw_to_combined(
                {k: v[:, :years] for k, v in raw.items()},
                alloc, req.leverage, req.borrowing_spread,
            )
            infl = raw["inflation"][:, :years]
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
            return scen, infl, rg, tbl, cf_tbl_r

        base_scen, base_infl, base_rg, base_tbl, base_cf_tbl_r = _build_tables(base_alloc, base_years)
        _base_rg, _base_sg, _base_tbl, _base_ref, _base_ly = unpack_cf_table(base_cf_tbl_r)

        def _run_with_tables(
            scen, infl, rg, tbl, cf_rg, cf_sg, cf_tbl, cf_ref, cf_ly,
            years, ip_override=None, aw_override=None, target_override=None,
        ):
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
                consumption_floor_amount=req.consumption_floor_amount,
            )
            r_fr = compute_funded_ratio(r_traj, years)
            return r_ip, r_aw, r_sr, r_fr

        def _build_and_run(alloc, years):
            scen, infl, rg, tbl, cf_tbl_r = _build_tables(alloc, years)
            _rg, _sg, _tbl, _ref, _ly = unpack_cf_table(cf_tbl_r)
            return _run_with_tables(scen, infl, rg, tbl, _rg, _sg, _tbl, _ref, _ly, years)

        yield {"type": "progress", "stage": "sensitivity_base", "pct": 25}

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

        total_runs = len(param_specs) * 2
        run_idx = 0

        deltas = []
        for key, label, base_val, lo_val, hi_val in param_specs:
            lo_sr = hi_sr = base_sr
            lo_fr = hi_fr = base_fr
            lo_wd = hi_wd = base_aw

            for side, side_val in [("low", lo_val), ("high", hi_val)]:
                run_idx += 1
                pct = 30 + int(65 * run_idx / total_runs)
                yield {"type": "progress", "stage": "sensitivity_param", "pct": pct, "current": run_idx, "total": total_runs}

                r_ip, r_aw, sr, fr = base_ip, base_aw, base_sr, base_fr

                if key in ("initial_portfolio", "annual_withdrawal", "target_success"):
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
                    r_ip, r_aw, sr, fr = _build_and_run(base_alloc, int(side_val))
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
                    r_ip, r_aw, sr, fr = _build_and_run(
                        {"domestic_stock": dom_new, "global_stock": glb_new, "domestic_bond": bond_new},
                        base_years,
                    )

                if side == "low":
                    lo_sr, lo_fr, lo_wd = sr, fr, r_aw
                else:
                    hi_sr, hi_fr, hi_wd = sr, fr, r_aw

            deltas.append({
                "param_label": label,
                "param_key": key,
                "low_value": lo_val,
                "high_value": hi_val,
                "base_value": base_val,
                "low_success_rate": lo_sr,
                "high_success_rate": hi_sr,
                "low_funded_ratio": lo_fr,
                "high_funded_ratio": hi_fr,
                "low_withdrawal": lo_wd,
                "high_withdrawal": hi_wd,
            })

        yield {"type": "result", "data": {
            "base_success_rate": base_sr,
            "base_funded_ratio": base_fr,
            "base_withdrawal": base_aw,
            "deltas": deltas,
        }}

    return streaming(_generate())


# ---------------------------------------------------------------------------
# POST /api/guardrail/backtest
# ---------------------------------------------------------------------------

@router.post("/api/guardrail/backtest", response_model=BacktestResponse)
@limiter.limit("10/minute")
def api_backtest(request: Request, req: BacktestRequest):
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    country_weights = resolve_country_weights(req, country_dfs)

    scenarios, _ = pregenerate_return_scenarios(
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
    rate_grid, table = build_success_rate_table(scenarios)

    bt_country = req.backtest_country or req.country
    if bt_country == "ALL":
        raise HTTPException(400, "历史回测必须指定具体国家")

    if bt_country != req.country or req.country == "ALL":
        hist_filtered = filter_df(bt_country, req.data_start_year, req.data_source)
    else:
        hist_filtered = filtered

    hist_df = hist_filtered[hist_filtered["Year"] >= req.hist_start_year].reset_index(drop=True)
    if len(hist_df) < 1:
        raise HTTPException(400, f"{bt_country} 从 {req.hist_start_year} 年开始无可用数据")

    hist_returns = compute_real_portfolio_returns(
        hist_df, alloc_dict(req.allocation), expense_dict(req.expense_ratios),
        leverage=req.leverage, borrowing_spread=req.borrowing_spread,
    )
    hist_inflation = hist_df["Inflation"].values

    cash_flows = to_cash_flows(req.cash_flows)

    bt_cf_result = None
    if cash_flows:
        rep_schedule = build_representative_cf_schedule(
            cash_flows, req.retirement_years,
        )
        bt_cf_result = build_cf_aware_table(scenarios, rep_schedule)
    _bt_cf_rg, _bt_cf_sg, _bt_cf_tbl, _bt_cf_ref, _bt_last_cf_y = unpack_cf_table(bt_cf_result)

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
    actual_start = int(hist_df["Year"].iloc[0])
    year_labels = [actual_start - 1 + i for i in range(n + 1)]

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
# POST /api/guardrail/backtest-batch
# ---------------------------------------------------------------------------

@router.post("/api/guardrail/backtest-batch", response_model=GuardrailBatchBacktestResponse)
@limiter.limit("5/minute")
def api_guardrail_batch_backtest(request: Request, req: GuardrailBatchBacktestRequest):
    """Batch historical backtest across all valid (country, start_year) combos."""
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    country_weights = resolve_country_weights(req, country_dfs)

    scenarios, _ = pregenerate_return_scenarios(
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
    rate_grid, table = build_success_rate_table(scenarios)

    batch_cash_flows = to_cash_flows(req.cash_flows)

    batch_cf_result = None
    if batch_cash_flows:
        rep_schedule = build_representative_cf_schedule(
            batch_cash_flows, req.retirement_years,
        )
        batch_cf_result = build_cf_aware_table(scenarios, rep_schedule)
    _batch_cf_rg, _batch_cf_sg, _batch_cf_tbl, _batch_cf_ref, _batch_last_cf_y = unpack_cf_table(batch_cf_result)

    if country_dfs is not None:
        bt_country_dfs = country_dfs
        bt_filtered = None
    else:
        bt_country_dfs = None
        bt_filtered = filtered

    result = run_guardrail_batch_backtest(
        country_dfs=bt_country_dfs,
        filtered_df=bt_filtered,
        allocation=alloc_dict(req.allocation),
        expense_ratios=expense_dict(req.expense_ratios),
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
        consumption_floor_amount=req.consumption_floor_amount,
    )

    path_summaries = []
    for p in result["paths"]:
        path_summaries.append(GuardrailBatchPathSummary(
            country=p["country"],
            start_year=p["start_year"],
            years_simulated=p["years_simulated"],
            is_complete=p["is_complete"],
            g_survived=p["g_survived"],
            b_survived=p["b_survived"],
            g_has_failed=p.get("g_has_failed", False),
            b_has_failed=p.get("b_has_failed", False),
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
        num_incomplete_failed_g=result.get("num_incomplete_failed_g", 0),
        num_incomplete_failed_b=result.get("num_incomplete_failed_b", 0),
        num_excluded_g=result.get("num_excluded_g", 0),
        num_excluded_b=result.get("num_excluded_b", 0),
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
