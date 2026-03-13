"""批量历史回测模块 — 遍历所有有效 (国家, 起始年) 组合。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .cashflow import CashFlowItem
from .guardrail import run_historical_backtest
from .monte_carlo import run_simple_historical_backtest, batch_backtest_fixed_vectorized
from .portfolio import compute_real_portfolio_returns
from .statistics import (
    compute_effective_funded_ratio,
    compute_funded_ratio,
    compute_portfolio_metrics,
    compute_single_path_metrics,
    compute_statistics,
    final_values_summary_table,
    PERCENTILES,
)

MIN_BACKTEST_YEARS = 10


def _compute_country_arrays(cdf_sorted: pd.DataFrame, allocation, expense_ratios,
                            leverage, borrowing_spread):
    """Pre-compute full real returns and inflation arrays for one country."""
    real_returns_full = compute_real_portfolio_returns(
        cdf_sorted, allocation, expense_ratios,
        leverage=leverage, borrowing_spread=borrowing_spread,
    )
    inflation_full = cdf_sorted["Inflation"].values
    return real_returns_full, inflation_full


# ---------------------------------------------------------------------------
# 1. 主模拟页批量回测
# ---------------------------------------------------------------------------

def run_sim_batch_backtest(
    country_dfs: dict[str, pd.DataFrame] | None,
    filtered_df: pd.DataFrame | None,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    initial_portfolio: float,
    annual_withdrawal: float,
    retirement_years: int,
    withdrawal_strategy: str = "fixed",
    dynamic_ceiling: float = 0.05,
    dynamic_floor: float = 0.025,
    retirement_age: int = 45,
    cash_flows: list[CashFlowItem] | None = None,
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
    declining_rate: float = 0.02,
    declining_start_age: int = 65,
    smile_decline_rate: float = 0.01,
    smile_decline_start_age: int = 65,
    smile_min_age: int = 80,
    smile_increase_rate: float = 0.01,
) -> dict:
    """遍历所有有效 (国家, 起始年) 运行历史回测。

    Parameters
    ----------
    country_dfs : dict[str, pd.DataFrame] or None
        {iso: df}，country=ALL 时使用。
    filtered_df : pd.DataFrame or None
        单国模式时使用（已按 country+data_start_year 过滤）。
    其他参数与 run_simple_historical_backtest 相同。

    Returns
    -------
    dict
        包含 "paths" (所有路径列表) 和聚合统计字段。
    """
    # 构建 {iso: df} 迭代列表
    if country_dfs is not None:
        iter_dfs = country_dfs
    elif filtered_df is not None and len(filtered_df) > 0:
        iso = str(filtered_df["Country"].iloc[0])
        iter_dfs = {iso: filtered_df}
    else:
        return _empty_sim_batch_result()

    has_cf = cash_flows is not None and len(cash_flows) > 0
    use_vectorized = withdrawal_strategy == "fixed" and not has_cf

    paths: list[dict] = []

    for iso, cdf in iter_dfs.items():
        cdf_sorted = cdf.sort_values("Year").reset_index(drop=True)
        years = cdf_sorted["Year"].values
        max_year = int(years[-1])

        # Pre-compute full real returns and inflation for this country (once)
        real_returns_full, inflation_full = _compute_country_arrays(
            cdf_sorted, allocation, expense_ratios, leverage, borrowing_spread,
        )

        if use_vectorized:
            # Collect all valid (start_idx, n_years) pairs for batch processing
            batch_entries = []
            for i, sy in enumerate(years):
                sy = int(sy)
                avail = max_year - sy + 1
                if avail < MIN_BACKTEST_YEARS:
                    continue
                n_years = min(retirement_years, avail)
                batch_entries.append((i, n_years, sy))

            if not batch_entries:
                continue

            # Build 2D return matrix for vectorized batch
            max_n = max(e[1] for e in batch_entries)
            ret_2d = np.zeros((len(batch_entries), max_n))
            infl_2d = np.zeros((len(batch_entries), max_n))
            for bi, (start_idx, n_years, _) in enumerate(batch_entries):
                ret_2d[bi, :n_years] = real_returns_full[start_idx:start_idx + n_years]
                infl_2d[bi, :n_years] = inflation_full[start_idx:start_idx + n_years]

            portfolios, withdrawals, survived_arr = batch_backtest_fixed_vectorized(
                ret_2d, initial_portfolio, annual_withdrawal,
            )

            for bi, (start_idx, n_years, start_year) in enumerate(batch_entries):
                is_complete = n_years >= retirement_years
                port_list = portfolios[bi, :n_years + 1].tolist()
                wd_list = withdrawals[bi, :n_years].tolist()
                rr = real_returns_full[start_idx:start_idx + n_years]
                inf = inflation_full[start_idx:start_idx + n_years]
                pm = compute_single_path_metrics(rr, inf)
                year_labels = years[start_idx:start_idx + n_years].tolist()

                paths.append({
                    "country": iso,
                    "start_year": start_year,
                    "years_simulated": n_years,
                    "is_complete": is_complete,
                    "survived": bool(survived_arr[bi]),
                    "final_portfolio": port_list[-1],
                    "total_consumption": sum(wd_list),
                    "year_labels": year_labels,
                    "portfolio": port_list,
                    "withdrawals": wd_list,
                    "path_metrics": pm,
                    # Cached for aggregation phase
                    "_real_returns": rr,
                    "_inflation": inf,
                })
        else:
            # Non-fixed strategies: per-path loop with numpy slicing
            for i, start_year in enumerate(years):
                start_year = int(start_year)
                avail = max_year - start_year + 1
                if avail < MIN_BACKTEST_YEARS:
                    continue

                n_years = min(retirement_years, avail)
                real_returns = real_returns_full[i:i + n_years]
                inflation_series = inflation_full[i:i + n_years]

                result = run_simple_historical_backtest(
                    real_returns=real_returns,
                    initial_portfolio=initial_portfolio,
                    annual_withdrawal=annual_withdrawal,
                    retirement_years=n_years,
                    withdrawal_strategy=withdrawal_strategy,
                    dynamic_ceiling=dynamic_ceiling,
                    dynamic_floor=dynamic_floor,
                    retirement_age=retirement_age,
                    cash_flows=cash_flows,
                    inflation_series=inflation_series,
                    declining_rate=declining_rate,
                    declining_start_age=declining_start_age,
                    smile_decline_rate=smile_decline_rate,
                    smile_decline_start_age=smile_decline_start_age,
                    smile_min_age=smile_min_age,
                    smile_increase_rate=smile_increase_rate,
                )

                pm = compute_single_path_metrics(real_returns, inflation_series)
                year_labels = years[i:i + n_years].tolist()

                paths.append({
                    "country": iso,
                    "start_year": start_year,
                    "years_simulated": n_years,
                    "is_complete": n_years >= retirement_years,
                    "survived": result["survived"],
                    "final_portfolio": result["portfolio"][-1],
                    "total_consumption": sum(result["withdrawals"]),
                    "year_labels": year_labels,
                    "portfolio": result["portfolio"],
                    "withdrawals": result["withdrawals"],
                    "path_metrics": pm,
                    # Cached for aggregation phase
                    "_real_returns": real_returns,
                    "_inflation": inflation_series,
                })

    # --- 聚合统计（仅完整路径） ---
    complete = [p for p in paths if p["is_complete"]]

    if len(complete) == 0:
        # Strip cached arrays before returning
        for p in paths:
            p.pop("_real_returns", None)
            p.pop("_inflation", None)
        return {
            "num_paths": len(paths),
            "num_complete": 0,
            "success_rate": 0.0,
            "funded_ratio": 0.0,
            "percentile_trajectories": {},
            "withdrawal_percentile_trajectories": None,
            "final_values_summary": [],
            "portfolio_metrics": [],
            "paths": paths,
        }

    # 构建轨迹矩阵 (num_complete, retirement_years+1)
    traj = np.array([p["portfolio"] for p in complete])
    wd_mat = np.array([p["withdrawals"] for p in complete])

    stats = compute_statistics(traj, retirement_years, wd_mat)
    summary_df = final_values_summary_table(stats)

    # 构建回报/通胀矩阵 — 直接从缓存读取，无需重新计算
    real_ret_mat = np.array([p["_real_returns"] for p in complete])
    infl_mat = np.array([p["_inflation"] for p in complete])

    port_metrics = compute_portfolio_metrics(real_ret_mat, infl_mat)

    # Strip cached arrays before returning (avoid serialization overhead)
    for p in paths:
        p.pop("_real_returns", None)
        p.pop("_inflation", None)

    # 序列化分位数轨迹
    pct_traj = {str(k): v.tolist() for k, v in stats.percentile_trajectories.items()}
    wd_pct_traj = None
    if stats.withdrawal_percentile_trajectories is not None:
        wd_pct_traj = {
            str(k): v.tolist()
            for k, v in stats.withdrawal_percentile_trajectories.items()
        }

    return {
        "num_paths": len(paths),
        "num_complete": len(complete),
        "success_rate": stats.success_rate,
        "funded_ratio": stats.funded_ratio,
        "percentile_trajectories": pct_traj,
        "withdrawal_percentile_trajectories": wd_pct_traj,
        "final_values_summary": summary_df.to_dict("records"),
        "portfolio_metrics": port_metrics,
        "paths": paths,
    }


def _empty_sim_batch_result() -> dict:
    return {
        "num_paths": 0,
        "num_complete": 0,
        "success_rate": 0.0,
        "funded_ratio": 0.0,
        "percentile_trajectories": {},
        "withdrawal_percentile_trajectories": None,
        "final_values_summary": [],
        "portfolio_metrics": [],
        "paths": [],
    }


# ---------------------------------------------------------------------------
# 2. Guardrail 页批量回测
# ---------------------------------------------------------------------------

def run_guardrail_batch_backtest(
    country_dfs: dict[str, pd.DataFrame] | None,
    filtered_df: pd.DataFrame | None,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    initial_portfolio: float,
    annual_withdrawal: float,
    retirement_years: int,
    target_success: float,
    upper_guardrail: float,
    lower_guardrail: float,
    adjustment_pct: float,
    adjustment_mode: str,
    min_remaining_years: int,
    baseline_rate: float,
    table: np.ndarray,
    rate_grid: np.ndarray,
    cash_flows: list[CashFlowItem] | None = None,
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
    cf_table: np.ndarray | None = None,
    cf_rate_grid: np.ndarray | None = None,
    cf_scale_grid: np.ndarray | None = None,
    cf_ref: float = 0.0,
    last_cf_year: int = -1,
    consumption_floor: float = 0.50,
    consumption_floor_amount: float = 0.0,
) -> dict:
    """遍历所有有效 (国家, 起始年) 运行 guardrail 历史回测。

    Returns
    -------
    dict
        包含 "paths" 和 guardrail/baseline 聚合统计。
    """
    if country_dfs is not None:
        iter_dfs = country_dfs
    elif filtered_df is not None and len(filtered_df) > 0:
        iso = str(filtered_df["Country"].iloc[0])
        iter_dfs = {iso: filtered_df}
    else:
        return _empty_guardrail_batch_result()

    paths: list[dict] = []

    for iso, cdf in iter_dfs.items():
        cdf_sorted = cdf.sort_values("Year").reset_index(drop=True)
        years_arr = cdf_sorted["Year"].values
        max_year = int(years_arr[-1])

        # Pre-compute full real returns and inflation for this country (once)
        real_returns_full, inflation_full = _compute_country_arrays(
            cdf_sorted, allocation, expense_ratios, leverage, borrowing_spread,
        )

        for i, start_year in enumerate(years_arr):
            start_year = int(start_year)
            avail = max_year - start_year + 1
            if avail < MIN_BACKTEST_YEARS:
                continue

            n_years = min(retirement_years, avail)
            real_returns = real_returns_full[i:i + n_years]
            inflation_series = inflation_full[i:i + n_years]

            result = run_historical_backtest(
                real_returns=real_returns,
                initial_portfolio=initial_portfolio,
                annual_withdrawal=annual_withdrawal,
                target_success=target_success,
                upper_guardrail=upper_guardrail,
                lower_guardrail=lower_guardrail,
                adjustment_pct=adjustment_pct,
                retirement_years=retirement_years,
                min_remaining_years=min_remaining_years,
                baseline_rate=baseline_rate,
                table=table,
                rate_grid=rate_grid,
                adjustment_mode=adjustment_mode,
                cash_flows=cash_flows,
                inflation_series=inflation_series,
                cf_table=cf_table,
                cf_rate_grid=cf_rate_grid,
                cf_scale_grid=cf_scale_grid,
                cf_ref=cf_ref,
                last_cf_year=last_cf_year,
            )

            pm = compute_single_path_metrics(real_returns, inflation_series)
            year_labels = years_arr[i:i + n_years].tolist()

            # 逐条路径的消费地板判定
            _path_floor = max(consumption_floor * annual_withdrawal, consumption_floor_amount)
            _path_below_floor = any(w < _path_floor for w in result["g_withdrawals"])
            _g_survived = (
                float(result["g_portfolio"][-1]) > 0
                and not _path_below_floor
            )

            paths.append({
                "country": iso,
                "start_year": start_year,
                "years_simulated": result["years_simulated"],
                "is_complete": n_years >= retirement_years,
                "g_survived": _g_survived,
                "b_survived": float(result["b_portfolio"][-1]) > 0,
                "g_final_portfolio": float(result["g_portfolio"][-1]),
                "b_final_portfolio": float(result["b_portfolio"][-1]),
                "g_total_consumption": result["g_total_consumption"],
                "b_total_consumption": result["b_total_consumption"],
                "num_adjustments": len(result.get("adjustment_events", [])),
                "year_labels": year_labels,
                "g_portfolio": result["g_portfolio"].tolist(),
                "g_withdrawals": result["g_withdrawals"].tolist(),
                "g_success_rates": result["g_success_rates"].tolist(),
                "b_portfolio": result["b_portfolio"].tolist(),
                "b_withdrawals": result["b_withdrawals"].tolist(),
                "adjustment_events": result.get("adjustment_events", []),
                "path_metrics": pm,
            })

    # --- 聚合（仅完整路径） ---
    complete = [p for p in paths if p["is_complete"]]

    if len(complete) == 0:
        return {
            **_empty_guardrail_batch_result(),
            "num_paths": len(paths),
            "paths": paths,
        }

    # Guardrail 轨迹
    g_traj = np.array([p["g_portfolio"] for p in complete])
    g_wd = np.array([p["g_withdrawals"] for p in complete])
    b_traj = np.array([p["b_portfolio"] for p in complete])
    b_wd = np.array([p["b_withdrawals"] for p in complete])

    g_fr, g_success = compute_effective_funded_ratio(
        g_wd, annual_withdrawal, retirement_years,
        consumption_floor=consumption_floor,
        trajectories=g_traj,
        consumption_floor_amount=consumption_floor_amount,
    )
    b_success = float(np.mean(b_traj[:, -1] > 0))
    b_fr = compute_funded_ratio(b_traj, retirement_years)

    band_pcts = [10, 25, 50, 75, 90]
    g_pct_traj = {str(p): np.percentile(g_traj, p, axis=0).tolist() for p in band_pcts}
    b_pct_traj = {str(p): np.percentile(b_traj, p, axis=0).tolist() for p in band_pcts}
    g_wd_pcts = {str(p): np.percentile(g_wd, p, axis=0).tolist() for p in band_pcts}
    b_wd_pcts = {str(p): np.percentile(b_wd, p, axis=0).tolist() for p in band_pcts}

    return {
        "num_paths": len(paths),
        "num_complete": len(complete),
        "g_success_rate": g_success,
        "g_funded_ratio": g_fr,
        "b_success_rate": b_success,
        "b_funded_ratio": b_fr,
        "g_percentile_trajectories": g_pct_traj,
        "b_percentile_trajectories": b_pct_traj,
        "g_withdrawal_percentiles": g_wd_pcts,
        "b_withdrawal_percentiles": b_wd_pcts,
        "paths": paths,
    }


def _empty_guardrail_batch_result() -> dict:
    return {
        "num_paths": 0,
        "num_complete": 0,
        "g_success_rate": 0.0,
        "g_funded_ratio": 0.0,
        "b_success_rate": 0.0,
        "b_funded_ratio": 0.0,
        "g_percentile_trajectories": {},
        "b_percentile_trajectories": {},
        "g_withdrawal_percentiles": {},
        "b_withdrawal_percentiles": {},
        "paths": [],
    }
