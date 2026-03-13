"""Accumulation endpoint: /api/accumulation."""

from __future__ import annotations

from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from deps import (
    alloc_dict,
    expense_dict,
    resolve_country_weights,
    resolve_data,
    to_cash_flows,
    validate_data_sufficient,
)
from schemas import AccumulationRequest, AccumulationResponse
from simulator.accumulation import run_accumulation

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/api/accumulation", response_model=AccumulationResponse)
@limiter.limit("5/minute")
def api_accumulation(request: Request, req: AccumulationRequest):
    filtered, country_dfs = resolve_data(req)
    validate_data_sufficient(filtered, country_dfs)

    country_weights = resolve_country_weights(req, country_dfs)
    cf = to_cash_flows(req.cash_flows)

    result = run_accumulation(
        current_age=req.current_age,
        life_expectancy=req.life_expectancy,
        current_portfolio=req.current_portfolio,
        annual_income=req.annual_income,
        annual_expenses=req.annual_expenses,
        income_growth_rate=req.income_growth_rate,
        retirement_spending=req.retirement_spending,
        target_success_rate=req.target_success_rate,
        allocation=alloc_dict(req.allocation),
        expense_ratios=expense_dict(req.expense_ratios),
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
