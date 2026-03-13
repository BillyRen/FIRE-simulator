"""Buy vs Rent endpoints: /api/buy-vs-rent/simple, /api/buy-vs-rent/simulate,
/api/buy-vs-rent/breakeven/simple, /api/buy-vs-rent/breakeven/mc."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from deps import (
    get_returns_df,
    prepare_housing_data,
    resolve_country_weights_for_housing,
)
from schemas import (
    BreakevenMCRequest,
    BreakevenResponse,
    BreakevenSimpleRequest,
    BuyVsRentMCRequest,
    BuyVsRentMCResponse,
    BuyVsRentSimpleRequest,
    BuyVsRentSimpleResponse,
)
from simulator.buy_vs_rent import (
    find_breakeven_price_mc,
    find_breakeven_price_simple,
    run_buy_vs_rent_mc,
    run_simple_buy_vs_rent,
)
from simulator.data_loader import (
    filter_housing_data,
    get_housing_country_dfs,
)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# POST /api/buy-vs-rent/simple
# ---------------------------------------------------------------------------

@router.post("/api/buy-vs-rent/simple", response_model=BuyVsRentSimpleResponse)
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


# ---------------------------------------------------------------------------
# POST /api/buy-vs-rent/simulate
# ---------------------------------------------------------------------------

@router.post("/api/buy-vs-rent/simulate", response_model=BuyVsRentMCResponse)
@limiter.limit("10/minute")
def api_buy_vs_rent_mc(request: Request, req: BuyVsRentMCRequest):
    df = get_returns_df("jst")

    alloc_dict = req.allocation.model_dump()
    expense_dict = req.expense_ratios.model_dump()

    if req.country == "ALL":
        country_dfs = get_housing_country_dfs(df, req.data_start_year)
        if not country_dfs:
            raise HTTPException(400, "No countries with housing data available")
        country_weights = resolve_country_weights_for_housing(req, country_dfs)
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


# ---------------------------------------------------------------------------
# POST /api/buy-vs-rent/breakeven/simple
# ---------------------------------------------------------------------------

@router.post("/api/buy-vs-rent/breakeven/simple", response_model=BreakevenResponse)
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


# ---------------------------------------------------------------------------
# POST /api/buy-vs-rent/breakeven/mc
# ---------------------------------------------------------------------------

@router.post("/api/buy-vs-rent/breakeven/mc", response_model=BreakevenResponse)
@limiter.limit("5/minute")
def api_breakeven_mc(request: Request, req: BreakevenMCRequest):
    df = get_returns_df("jst")
    filtered_df, country_dfs, country_weights = prepare_housing_data(req, df)

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
