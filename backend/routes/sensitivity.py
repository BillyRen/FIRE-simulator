"""Sensitivity endpoints: /api/simulate/sensitivity, /api/allocation-sweep."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from deps import (
    alloc_dict,
    expense_dict,
    resolve_country_weights,
    resolve_data,
    streaming,
    to_cash_flows,
    validate_data_sufficient,
)
from schemas import (
    AllocationResult,
    AllocationSweepRequest,
    AllocationSweepResponse,
    SimulationRequest,
)
from simulator.monte_carlo import run_simulation_from_matrix
from simulator.statistics import (
    compute_funded_ratio,
    compute_success_rate,
)
from simulator.sweep import (
    pregenerate_raw_scenarios,
    raw_to_combined,
    sweep_allocations,
)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# POST /api/simulate/sensitivity
# ---------------------------------------------------------------------------

@router.post("/api/simulate/sensitivity")
@limiter.limit("5/minute")
def api_simulate_sensitivity(request: Request, req: SimulationRequest):
    """Core parameter +/- delta impact on success rate.

    Uses Common Random Numbers — single bootstrap generates raw matrices,
    all variants reuse the same random returns.
    """
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    def _generate():
        yield {"type": "progress", "stage": "sensitivity_base", "pct": 5}

        country_weights = resolve_country_weights(req, country_dfs)
        cash_flows = to_cash_flows(req.cash_flows)

        base_ip = req.initial_portfolio
        base_aw = req.annual_withdrawal
        base_years = req.retirement_years
        stock_pct = req.allocation.domestic_stock + req.allocation.global_stock
        base_alloc = alloc_dict(req.allocation)

        max_years = base_years + 10
        raw = pregenerate_raw_scenarios(
            expense_ratios=expense_dict(req.expense_ratios),
            retirement_years=max_years,
            min_block=req.min_block,
            max_block=req.max_block,
            num_simulations=req.num_simulations,
            returns_df=filtered,
            seed=req.seed,
            country_dfs=country_dfs,
            country_weights=country_weights,
        )

        yield {"type": "progress", "stage": "sensitivity_combine", "pct": 15}

        base_combined_full = raw_to_combined(raw, base_alloc, req.leverage, req.borrowing_spread)
        base_inflation_full = raw["inflation"]

        base_combined = base_combined_full[:, :base_years]
        base_inflation = base_inflation_full[:, :base_years]

        def _run_from_matrix(returns_mat, inflation_mat, ip, aw, yrs, cfs=None):
            traj, wd, _, _ = run_simulation_from_matrix(
                real_returns_matrix=returns_mat[:, :yrs],
                inflation_matrix=inflation_mat[:, :yrs],
                initial_portfolio=ip,
                annual_withdrawal=aw,
                retirement_years=yrs,
                withdrawal_strategy=req.withdrawal_strategy,
                dynamic_ceiling=req.dynamic_ceiling,
                dynamic_floor=req.dynamic_floor,
                retirement_age=req.retirement_age,
                cash_flows=cfs if cfs is not None else cash_flows,
                declining_rate=req.declining_rate,
                declining_start_age=req.declining_start_age,
                smile_decline_rate=req.smile_decline_rate,
                smile_decline_start_age=req.smile_decline_start_age,
                smile_min_age=req.smile_min_age,
                smile_increase_rate=req.smile_increase_rate,
            )
            sr = compute_success_rate(traj, yrs)
            fr = compute_funded_ratio(traj, yrs)
            return sr, fr

        base_sr, base_fr = _run_from_matrix(base_combined, base_inflation, base_ip, base_aw, base_years)

        param_specs = [
            ("initial_portfolio", "初始资产", base_ip, base_ip * 0.8, base_ip * 1.2),
            ("annual_withdrawal", "年提取额", base_aw, base_aw * 0.8, base_aw * 1.2),
            ("retirement_years", "退休年限", float(base_years), float(max(10, base_years - 10)), float(base_years + 10)),
            ("stock_allocation", "股票配置比例", stock_pct, max(0.0, stock_pct - 0.2), min(1.0, stock_pct + 0.2)),
        ]

        total_runs = len(param_specs) * 2
        run_idx = 0

        deltas = []
        for key, label, base_val, lo_val, hi_val in param_specs:
            lo_sr, lo_fr, hi_sr, hi_fr = base_sr, base_fr, base_sr, base_fr

            for side, side_val in [("low", lo_val), ("high", hi_val)]:
                run_idx += 1
                pct = 20 + int(75 * run_idx / total_runs)
                yield {"type": "progress", "stage": "sensitivity_param", "pct": pct, "current": run_idx, "total": total_runs}

                sr, fr = base_sr, base_fr

                if key == "initial_portfolio":
                    sr, fr = _run_from_matrix(base_combined, base_inflation, side_val, base_aw, base_years)
                elif key == "annual_withdrawal":
                    sr, fr = _run_from_matrix(base_combined, base_inflation, base_ip, side_val, base_years)
                elif key == "retirement_years":
                    yrs = int(side_val)
                    sr, fr = _run_from_matrix(base_combined_full, base_inflation_full, base_ip, base_aw, yrs)
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
                    new_alloc = {"domestic_stock": dom_new, "global_stock": glb_new, "domestic_bond": bond_new}
                    new_combined = raw_to_combined(raw, new_alloc, req.leverage, req.borrowing_spread)
                    sr, fr = _run_from_matrix(new_combined, base_inflation_full, base_ip, base_aw, base_years)

                if side == "low":
                    lo_sr, lo_fr = sr, fr
                else:
                    hi_sr, hi_fr = sr, fr

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
            })

        yield {"type": "result", "data": {
            "base_success_rate": base_sr,
            "base_funded_ratio": base_fr,
            "deltas": deltas,
        }}

    return streaming(_generate())


# ---------------------------------------------------------------------------
# POST /api/allocation-sweep
# ---------------------------------------------------------------------------

@router.post("/api/allocation-sweep")
@limiter.limit("10/minute")
def api_allocation_sweep(request: Request, req: AllocationSweepRequest):
    def _generate():
        yield {"type": "progress", "stage": "bootstrap", "pct": 5}
        filtered, country_dfs = resolve_data(req)
        validate_data_sufficient(filtered, country_dfs)
        country_weights = resolve_country_weights(req, country_dfs)

        raw = pregenerate_raw_scenarios(
            expense_ratios=expense_dict(req.expense_ratios),
            retirement_years=req.retirement_years,
            min_block=req.min_block,
            max_block=req.max_block,
            num_simulations=req.num_simulations,
            returns_df=filtered,
            seed=req.seed,
            country_dfs=country_dfs,
            country_weights=country_weights,
        )

        cash_flows = to_cash_flows(req.cash_flows)

        yield {"type": "progress", "stage": "allocation_sweep", "pct": 30}
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
            declining_rate=req.declining_rate,
            declining_start_age=req.declining_start_age,
            smile_decline_rate=req.smile_decline_rate,
            smile_decline_start_age=req.smile_decline_start_age,
            smile_min_age=req.smile_min_age,
            smile_increase_rate=req.smile_increase_rate,
        )

        yield {"type": "progress", "stage": "statistics", "pct": 90}
        alloc_results = [AllocationResult(**r) for r in raw_results]
        best = max(alloc_results, key=lambda x: x.funded_ratio)

        threshold = 0.01
        for r in alloc_results:
            r.is_near_optimal = (best.funded_ratio - r.funded_ratio) <= threshold
        best.is_near_optimal = True
        near_optimal_count = sum(1 for r in alloc_results if r.is_near_optimal)

        sorted_by_fr = sorted(alloc_results, key=lambda x: x.funded_ratio, reverse=True)
        pareto = []
        max_median = float('-inf')
        for r in sorted_by_fr:
            if r.median_final >= max_median:
                r.is_pareto = True
                pareto.append(r)
                max_median = r.median_final
        pareto_frontier = sorted(pareto, key=lambda x: x.funded_ratio)

        yield {"type": "result", "data": AllocationSweepResponse(
            results=alloc_results,
            best=best,
            near_optimal_count=near_optimal_count,
            near_optimal_threshold=threshold,
            pareto_frontier=pareto_frontier,
        ).model_dump()}

    return streaming(_generate())
