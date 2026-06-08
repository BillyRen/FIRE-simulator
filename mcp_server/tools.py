"""FIRE Simulator MCP tool implementations.

5 tools, all with sensible defaults so Claude can call them with minimal args:
- fire_simulate: single Monte Carlo run -> success rate, percentiles
- fire_sweep_withdrawal: scan withdrawal rates 0..rate_max
- fire_swr_for_target: one-shot SWR for a target success rate
- fire_guardrail: Guyton-Klinger guardrail vs fixed baseline
- fire_list_countries: list valid ISO codes
"""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np

from deps import get_country_list
from simulator.monte_carlo import run_simulation
from simulator.sweep import (
    pregenerate_return_scenarios,
    sweep_withdrawal_rates,
    interpolate_targets,
)
from simulator.guardrail import (
    build_success_rate_table,
    run_guardrail_simulation,
    run_fixed_baseline,
    find_rate_for_target,
    apply_guardrail_adjustment,
)
from simulator.statistics import (
    compute_statistics,
    compute_portfolio_metrics,
    compute_funded_ratio,
    compute_success_rate,
    compute_effective_funded_ratio,
)

from mcp_server.helpers import (
    safe_call,
    _resolve_allocation,
    _resolve_data,
    _build_notes,
)


_MAX_SIMS = 20_000
_MAX_SIMS_GUARDRAIL = 5_000


# ---------------------------------------------------------------------------
# Defaults — keep aligned with backend/schemas.py BaseSimulationParams
# ---------------------------------------------------------------------------

_DEFAULT_EXPENSE = {
    "domestic_stock": 0.005,
    "global_stock": 0.005,
    "domestic_bond": 0.005,
}
_TARGETS = [1.0, 0.95, 0.90, 0.85, 0.80, 0.75]  # for sweep interpolation


def _portfolio_metrics_summary(scen: np.ndarray, infl: np.ndarray | None) -> str:
    """Flatten the P50 column of compute_portfolio_metrics into one line."""
    if infl is None:
        return ""
    rows = compute_portfolio_metrics(scen, infl)
    if not rows:
        return ""
    parts = []
    for r in rows:
        key = r.get("metric", "")
        p50 = r.get("P50", "")
        if key and p50:
            parts.append(f"{key}(P50)={p50}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Tool 1: fire_simulate
# ---------------------------------------------------------------------------

@safe_call
def fire_simulate(
    initial_portfolio: float = 1_000_000,
    annual_withdrawal: float = 40_000,
    country: str = "USA",
    retirement_years: int = 65,
    stock_pct: float = 0.8,
    allocation: Optional[dict] = None,
    num_simulations: int = 2_000,
    withdrawal_strategy: Literal["fixed", "dynamic", "declining", "smile"] = "fixed",
    retirement_age: int = 45,
    leverage: float = 1.0,
    seed: Optional[int] = None,
    data_source: Literal["jst", "fire_dataset"] = "jst",
    data_start_year: int = 1900,
) -> dict:
    """Run a single Monte Carlo FIRE simulation.

    Returns success_rate, funded_ratio, and compact P10/P50/P90 trajectories
    (not full percentile bands — too much data for chat). Uses Block Bootstrap
    sampling from historical JST data (1871-2025) by default.

    Common usage:
      - Default args = 1M portfolio, 40K/yr (4% rule), USA, 65 years
      - country='ALL' enables equal-probability pooled bootstrap across
        16 JST countries (preferred for globally diversified investors)
      - stock_pct=0.8 auto-splits to ds=40% / gs=40% / db=20%. For full
        control, pass allocation={'domestic_stock':..., 'global_stock':..., 'domestic_bond':...}

    Gotchas:
      - country codes are 3-letter ISO ('CHN' not 'CN', 'GBR' not 'UK').
        Use fire_list_countries to discover valid codes.
      - data_source='fire_dataset' + country='ALL' silently coerces to 'USA'.
      - leverage>1.0 applies borrowing at 2% real spread above bond yield.
    """
    alloc = _resolve_allocation(allocation, stock_pct)
    if num_simulations > _MAX_SIMS:
        raise ValueError(f"num_simulations capped at {_MAX_SIMS:_} for MCP")

    filtered, country_dfs, weights = _resolve_data(country, data_source, data_start_year)

    traj, wd, real_ret, infl = run_simulation(
        initial_portfolio=initial_portfolio,
        annual_withdrawal=annual_withdrawal,
        allocation=alloc,
        expense_ratios=_DEFAULT_EXPENSE,
        retirement_years=retirement_years,
        min_block=5, max_block=15,
        num_simulations=num_simulations,
        returns_df=filtered, seed=seed,
        withdrawal_strategy=withdrawal_strategy,
        dynamic_ceiling=0.05, dynamic_floor=0.025,
        retirement_age=retirement_age,
        cash_flows=None,
        leverage=leverage, borrowing_spread=0.02,
        country_dfs=country_dfs, country_weights=weights,
    )
    res = compute_statistics(traj, retirement_years, wd)

    p10 = np.percentile(traj, 10, axis=0)
    p50 = np.percentile(traj, 50, axis=0)
    p90 = np.percentile(traj, 90, axis=0)

    return {
        "success_rate": res.success_rate,
        "funded_ratio": res.funded_ratio,
        "initial_withdrawal_rate": annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0,
        "final_portfolio": {
            "p10": res.final_percentiles[10],
            "p50": res.final_median,
            "p90": res.final_percentiles[90],
            "mean": res.final_mean,
        },
        "trajectory_p10_p50_p90": {
            "years": list(range(retirement_years + 1)),
            "p10": [float(x) for x in p10],
            "p50": [float(x) for x in p50],
            "p90": [float(x) for x in p90],
        },
        "portfolio_metrics_summary": _portfolio_metrics_summary(real_ret, infl),
        "notes": _build_notes(
            country, data_source,
            strategy=withdrawal_strategy, sims=num_simulations,
            alloc=f"{alloc['domestic_stock']:.2f}/{alloc['global_stock']:.2f}/{alloc['domestic_bond']:.2f}",
            years=retirement_years,
        ),
    }


# ---------------------------------------------------------------------------
# Tool 2: fire_sweep_withdrawal
# ---------------------------------------------------------------------------

@safe_call
def fire_sweep_withdrawal(
    initial_portfolio: float = 1_000_000,
    country: str = "USA",
    retirement_years: int = 65,
    stock_pct: float = 0.8,
    allocation: Optional[dict] = None,
    rate_min: float = 0.0,
    rate_max: float = 0.12,
    rate_step: float = 0.002,
    num_simulations: int = 2_000,
    withdrawal_strategy: Literal["fixed", "declining", "smile"] = "fixed",
    retirement_age: int = 45,
    leverage: float = 1.0,
    seed: Optional[int] = None,
    data_source: Literal["jst", "fire_dataset"] = "jst",
    data_start_year: int = 1900,
) -> dict:
    """Sweep withdrawal rates 0..rate_max and find SWR at standard targets.

    Returns:
      - swr_at_targets: SWR (as decimal, e.g. 0.0354 = 3.54%) for each of
        100/95/90/85/80/75% success targets
      - funded_at_targets: same but for funded_ratio targets
      - curve: full {rates[], success[], funded[]} arrays for inspection

    Tip: For a one-shot "what's the SWR at 85% success?" answer, use
    fire_swr_for_target instead — it returns just the number you want.
    """
    alloc = _resolve_allocation(allocation, stock_pct)
    if num_simulations > _MAX_SIMS:
        raise ValueError(f"num_simulations capped at {_MAX_SIMS:_} for MCP")

    filtered, country_dfs, weights = _resolve_data(country, data_source, data_start_year)

    scenarios, infl = pregenerate_return_scenarios(
        allocation=alloc, expense_ratios=_DEFAULT_EXPENSE,
        retirement_years=retirement_years,
        min_block=5, max_block=15,
        num_simulations=num_simulations,
        returns_df=filtered, seed=seed,
        leverage=leverage, borrowing_spread=0.02,
        country_dfs=country_dfs, country_weights=weights,
    )

    rates, success_rates, funded_ratios = sweep_withdrawal_rates(
        real_returns_matrix=scenarios,
        initial_portfolio=initial_portfolio,
        rate_min=rate_min, rate_max=rate_max, rate_step=rate_step,
        withdrawal_strategy=withdrawal_strategy,
        retirement_age=retirement_age,
        cash_flows=None, inflation_matrix=infl,
    )

    swr_at = interpolate_targets(rates, success_rates, _TARGETS)
    fwr_at = interpolate_targets(rates, funded_ratios, _TARGETS)

    return {
        "swr_at_targets": {
            f"{int(t*100)}%": (float(v) if v is not None else None)
            for t, v in zip(_TARGETS, swr_at)
        },
        "funded_at_targets": {
            f"{int(t*100)}%": (float(v) if v is not None else None)
            for t, v in zip(_TARGETS, fwr_at)
        },
        "curve": {
            "rates": [float(x) for x in rates],
            "success": [float(x) for x in success_rates],
            "funded": [float(x) for x in funded_ratios],
        },
        "notes": _build_notes(
            country, data_source,
            strategy=withdrawal_strategy, sims=num_simulations,
            alloc=f"{alloc['domestic_stock']:.2f}/{alloc['global_stock']:.2f}/{alloc['domestic_bond']:.2f}",
            years=retirement_years,
        ),
    }


# ---------------------------------------------------------------------------
# Tool 3: fire_swr_for_target
# ---------------------------------------------------------------------------

@safe_call
def fire_swr_for_target(
    target_success: float = 0.85,
    initial_portfolio: float = 1_000_000,
    country: str = "USA",
    retirement_years: int = 65,
    stock_pct: float = 0.8,
    allocation: Optional[dict] = None,
    num_simulations: int = 2_000,
    withdrawal_strategy: Literal["fixed", "declining", "smile"] = "fixed",
    retirement_age: int = 45,
    leverage: float = 1.0,
    seed: Optional[int] = None,
    data_source: Literal["jst", "fire_dataset"] = "jst",
    data_start_year: int = 1900,
) -> dict:
    """One-shot: what's the safe withdrawal rate (SWR) at a target success rate?

    Returns the SWR as a decimal (e.g. 0.0354 = 3.54%) and the implied
    annual_withdrawal / needed_portfolio. Internally runs a sweep and
    interpolates.

    Example: "What SWR gives 90% success on $1.5M, ALL countries pool, 50 years?"
    -> fire_swr_for_target(target_success=0.90, initial_portfolio=1_500_000,
                          country='ALL', retirement_years=50)
    """
    if not 0.0 < target_success < 1.0:
        raise ValueError(f"target_success must be in (0,1), got {target_success}")
    if num_simulations > _MAX_SIMS:
        raise ValueError(f"num_simulations capped at {_MAX_SIMS:_} for MCP")

    alloc = _resolve_allocation(allocation, stock_pct)
    filtered, country_dfs, weights = _resolve_data(country, data_source, data_start_year)

    scenarios, infl = pregenerate_return_scenarios(
        allocation=alloc, expense_ratios=_DEFAULT_EXPENSE,
        retirement_years=retirement_years,
        min_block=5, max_block=15,
        num_simulations=num_simulations,
        returns_df=filtered, seed=seed,
        leverage=leverage, borrowing_spread=0.02,
        country_dfs=country_dfs, country_weights=weights,
    )

    rates, success_rates, funded_ratios = sweep_withdrawal_rates(
        real_returns_matrix=scenarios,
        initial_portfolio=initial_portfolio,
        rate_min=0.0, rate_max=0.12, rate_step=0.001,
        withdrawal_strategy=withdrawal_strategy,
        retirement_age=retirement_age,
        cash_flows=None, inflation_matrix=infl,
    )

    swr = interpolate_targets(rates, success_rates, [target_success])[0]
    if swr is None:
        return {
            "swr": None,
            "annual_withdrawal": None,
            "needed_portfolio": None,
            "notes": f"No rate achieves {target_success:.0%} success "
                     f"(max success in sweep = {float(success_rates[0]):.1%}). "
                     f"Try lowering target or extending retirement_years.",
        }

    return {
        "swr": float(swr),
        "annual_withdrawal": float(swr * initial_portfolio),
        "needed_portfolio_per_40k": float(40_000 / swr) if swr > 0 else None,
        "context": _build_notes(
            country, data_source,
            target=f"{target_success:.0%}",
            strategy=withdrawal_strategy, sims=num_simulations,
            alloc=f"{alloc['domestic_stock']:.2f}/{alloc['global_stock']:.2f}/{alloc['domestic_bond']:.2f}",
            years=retirement_years,
        ),
    }


# ---------------------------------------------------------------------------
# Tool 4: fire_guardrail
# ---------------------------------------------------------------------------

@safe_call
def fire_guardrail(
    initial_portfolio: float = 1_000_000,
    target_success: float = 0.85,
    upper_guardrail: float = 0.99,
    lower_guardrail: float = 0.60,
    adjustment_pct: float = 0.10,
    baseline_rate: float = 0.033,
    consumption_floor: float = 0.50,
    consumption_floor_amount: float = 0.0,
    country: str = "USA",
    retirement_years: int = 65,
    stock_pct: float = 0.8,
    allocation: Optional[dict] = None,
    num_simulations: int = 2_000,
    min_remaining_years: int = 5,
    adjustment_mode: Literal["amount", "success_rate"] = "amount",
    annual_withdrawal: Optional[float] = None,
    leverage: float = 1.0,
    seed: Optional[int] = None,
    data_source: Literal["jst", "fire_dataset"] = "jst",
    data_start_year: int = 1900,
) -> dict:
    """Evaluate risk-based guardrail strategy vs fixed-rate baseline.

    Compares Guyton-Klinger style guardrail (raise withdrawal when success
    rate > upper_guardrail, cut when < lower_guardrail) against a fixed
    baseline_rate. Returns effective funded_ratio (consumption-floor-adjusted),
    P10 worst-year consumption, trigger thresholds, and a Chinese comparison
    table.

    Two input modes:
      - Default: provide initial_portfolio -> back out initial annual_withdrawal
        from target_success at year 0
      - Alternative: also pass annual_withdrawal -> use both directly (skip back-out)

    Defaults match the FIRE_simulator web UI guardrail page. target_success=0.85
    is the user's preferred baseline. Set num_simulations >= 2000 for stable
    effFR (capped at 5000 to bound memory).
    """
    if num_simulations > _MAX_SIMS_GUARDRAIL:
        raise ValueError(
            f"fire_guardrail num_simulations capped at {_MAX_SIMS_GUARDRAIL:_} (memory)"
        )
    if lower_guardrail >= upper_guardrail:
        raise ValueError(f"lower_guardrail ({lower_guardrail}) must be < upper_guardrail ({upper_guardrail})")

    alloc = _resolve_allocation(allocation, stock_pct)
    filtered, country_dfs, weights = _resolve_data(country, data_source, data_start_year)

    scenarios, infl = pregenerate_return_scenarios(
        allocation=alloc, expense_ratios=_DEFAULT_EXPENSE,
        retirement_years=retirement_years,
        min_block=5, max_block=15,
        num_simulations=num_simulations,
        returns_df=filtered, seed=seed,
        leverage=leverage, borrowing_spread=0.02,
        country_dfs=country_dfs, country_weights=weights,
    )

    rate_grid, table = build_success_rate_table(scenarios)

    sim_kwargs = dict(
        scenarios=scenarios,
        target_success=target_success,
        upper_guardrail=upper_guardrail,
        lower_guardrail=lower_guardrail,
        adjustment_pct=adjustment_pct,
        retirement_years=retirement_years,
        min_remaining_years=min_remaining_years,
        table=table, rate_grid=rate_grid,
        adjustment_mode=adjustment_mode,
        cash_flows=None, inflation_matrix=infl,
        initial_portfolio=initial_portfolio,
    )
    if annual_withdrawal is not None:
        sim_kwargs["annual_withdrawal"] = annual_withdrawal

    init_p, ann_wd, traj_g, wd_g = run_guardrail_simulation(**sim_kwargs)

    traj_b, wd_b = run_fixed_baseline(
        scenarios, init_p, baseline_rate, retirement_years,
        cash_flows=None, inflation_matrix=infl,
    )

    g_fr, g_sr = compute_effective_funded_ratio(
        wd_g, ann_wd, retirement_years,
        consumption_floor=consumption_floor, trajectories=traj_g,
        consumption_floor_amount=consumption_floor_amount,
    )
    b_sr = compute_success_rate(traj_b, retirement_years)
    b_fr = compute_funded_ratio(traj_b, retirement_years)
    baseline_wd = init_p * baseline_rate

    def min_nonzero_per_row(arr: np.ndarray) -> np.ndarray:
        mask = arr > 0
        filled = np.where(mask, arr, np.inf)
        return np.where(mask.any(axis=1), np.min(filled, axis=1), 0.0)

    g_p10_min = float(np.percentile(min_nonzero_per_row(wd_g), 10))
    b_p10_min = float(np.percentile(min_nonzero_per_row(wd_b), 10))
    g_total = np.sum(wd_g, axis=1)
    b_total = np.sum(wd_b, axis=1)

    metrics = [
        {"指标": "成功率", "Guardrail": f"{g_sr:.1%}", "基准固定": f"{b_sr:.1%}"},
        {"指标": "初始年提取额", "Guardrail": f"${ann_wd:,.0f}", "基准固定": f"${baseline_wd:,.0f}"},
        {"指标": "中位数总消费额",
         "Guardrail": f"${np.median(g_total):,.0f}",
         "基准固定": f"${np.median(b_total):,.0f}"},
        {"指标": "中位数最终资产",
         "Guardrail": f"${np.median(traj_g[:, -1]):,.0f}",
         "基准固定": f"${np.median(traj_b[:, -1]):,.0f}"},
        {"指标": "P10 最低年度消费",
         "Guardrail": f"${g_p10_min:,.0f}",
         "基准固定": f"${b_p10_min:,.0f}"},
        {"指标": "Effective Funded Ratio",
         "Guardrail": f"{g_fr:.3f}",
         "基准固定": f"{b_fr:.3f}"},
    ]

    # Compute trigger thresholds at year 0
    remaining_y0 = min(retirement_years, table.shape[1] - 1)
    upper_rate = find_rate_for_target(table, rate_grid, upper_guardrail, remaining_y0)
    lower_rate = find_rate_for_target(table, rate_grid, lower_guardrail, remaining_y0)
    upper_trigger_port = ann_wd / upper_rate if upper_rate > 0 else 0.0
    lower_trigger_port = ann_wd / lower_rate if lower_rate > 0 else 0.0

    return {
        "guardrail": {
            "success_rate": g_sr,
            "funded_ratio_effective": g_fr,
            "initial_portfolio": float(init_p),
            "initial_annual_withdrawal": float(ann_wd),
            "initial_rate": float(ann_wd / init_p) if init_p > 0 else 0,
            "p10_min_annual_consumption": g_p10_min,
            "median_total_consumption": float(np.median(g_total)),
            "median_final_portfolio": float(np.median(traj_g[:, -1])),
            "upper_trigger_portfolio": float(upper_trigger_port),
            "lower_trigger_portfolio": float(lower_trigger_port),
        },
        "baseline_fixed": {
            "success_rate": b_sr,
            "funded_ratio": b_fr,
            "annual_withdrawal": float(baseline_wd),
            "rate": baseline_rate,
            "p10_min_annual_consumption": b_p10_min,
            "median_total_consumption": float(np.median(b_total)),
            "median_final_portfolio": float(np.median(traj_b[:, -1])),
        },
        "metrics_table": metrics,
        "notes": _build_notes(
            country, data_source,
            target=f"{target_success:.0%}",
            upper=f"{upper_guardrail:.0%}", lower=f"{lower_guardrail:.0%}",
            adj=f"{adjustment_pct:.0%}",
            sims=num_simulations,
            alloc=f"{alloc['domestic_stock']:.2f}/{alloc['global_stock']:.2f}/{alloc['domestic_bond']:.2f}",
            years=retirement_years,
        ),
    }


# ---------------------------------------------------------------------------
# Tool 5: fire_list_countries
# ---------------------------------------------------------------------------

@safe_call
def fire_list_countries(
    data_source: Literal["jst", "fire_dataset"] = "jst",
) -> dict:
    """List valid country ISO codes with their data year ranges.

    Use this to discover correct 3-letter ISO codes — JST uses 'CHN' not 'CN',
    'GBR' not 'UK', 'JPN' not 'JP', etc. The special code 'ALL' means
    equal-probability pooled bootstrap across all available countries
    (recommended for globally diversified investors).

    data_source='jst' has 16 countries from 1871-2025 (Jorda-Schularick-Taylor
    Macrohistory + 2021-2025 IMF/OECD extension). data_source='fire_dataset'
    is USA-only from 1871-2024 (FIRECalc-style).
    """
    countries = get_country_list(data_source)
    items = [
        {
            "iso": c["iso"],
            "name_en": c["name_en"],
            "name_zh": c["name_zh"],
            "min_year": c["min_year"],
            "max_year": c["max_year"],
            "n_years": c["n_years"],
        }
        for c in countries
    ]
    items.append({
        "iso": "ALL",
        "name_en": "Pooled (equal probability)",
        "name_zh": "全球池化（等概率）",
        "min_year": min(c["min_year"] for c in countries) if countries else 0,
        "max_year": max(c["max_year"] for c in countries) if countries else 0,
        "n_years": sum(c["n_years"] for c in countries),
    })
    return {"data_source": data_source, "countries": items}
