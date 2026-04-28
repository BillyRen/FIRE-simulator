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
    compute_success_rate,
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


def _has_failed_depletion(port: np.ndarray, n_years: int, retirement_years: int) -> bool:
    """Path failed = portfolio first hits zero at year < retirement_years.

    Aligned with compute_success_rate: end-of-horizon depletion (fail_year ==
    retirement_years) counts as success (Trinity-style). Incomplete paths use
    fail_year <= n_years <= retirement_years, so any in-window depletion fails.
    """
    if n_years <= 0:
        return False
    actual = port[1:n_years + 1]
    if not np.any(actual <= 0):
        return False
    fail_year = int(np.argmax(actual <= 0)) + 1
    return fail_year < retirement_years


def _has_failed_guardrail(
    g_port: np.ndarray,
    g_wd: np.ndarray,
    n_years: int,
    floor_amount: float,
    retirement_years: int,
) -> bool:
    """Guardrail path failed = depletion OR withdrawal below floor at fail_year < retirement_years."""
    if n_years <= 0:
        return False

    fail_year: int | None = None

    actual_port = g_port[1:n_years + 1]
    if np.any(actual_port <= 0):
        fail_year = int(np.argmax(actual_port <= 0)) + 1

    actual_wd = g_wd[:n_years]
    if np.any(actual_wd < floor_amount):
        floor_fail = int(np.argmax(actual_wd < floor_amount)) + 1
        fail_year = floor_fail if fail_year is None else min(fail_year, floor_fail)

    if fail_year is None:
        return False
    return fail_year < retirement_years


def _pad_portfolio_to(port_list: list[float], target_len: int) -> np.ndarray:
    """Pad portfolio array (length n+1) with zeros to retirement_years+1.

    Failed paths stay zero past their failure point; this matches the
    semantics of compute_success_rate / compute_effective_funded_ratio.
    """
    arr = np.asarray(port_list, dtype=float)
    if arr.size >= target_len:
        return arr[:target_len]
    return np.concatenate([arr, np.zeros(target_len - arr.size)])


def _pad_withdrawals_to(wd_list: list[float], target_len: int) -> np.ndarray:
    """Pad withdrawal array (length n) with zeros to retirement_years."""
    arr = np.asarray(wd_list, dtype=float)
    if arr.size >= target_len:
        return arr[:target_len]
    return np.concatenate([arr, np.zeros(target_len - arr.size)])


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
                year_labels = [int(years[start_idx] - 1)] + years[start_idx:start_idx + n_years].tolist()

                # has_failed: deterministic failure observed within [1, n_years]
                # AND fail_year < retirement_years.  Drives success-rate
                # aggregation; survived (kept for backward compat) reflects
                # the legacy "no early depletion" semantics.
                has_failed = _has_failed_depletion(
                    portfolios[bi, :n_years + 1], n_years, retirement_years,
                )
                actual_port = portfolios[bi, 1:n_years + 1]
                early_depleted = bool(np.any(actual_port[:n_years - 1] <= 0)) if n_years > 1 else False
                path_survived = not early_depleted

                paths.append({
                    "country": iso,
                    "start_year": start_year,
                    "years_simulated": n_years,
                    "is_complete": is_complete,
                    "survived": path_survived,
                    "has_failed": has_failed,
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
                year_labels = [int(start_year - 1)] + years[i:i + n_years].tolist()

                has_failed = _has_failed_depletion(
                    np.asarray(result["portfolio"], dtype=float),
                    n_years, retirement_years,
                )

                paths.append({
                    "country": iso,
                    "start_year": start_year,
                    "years_simulated": n_years,
                    "is_complete": n_years >= retirement_years,
                    "survived": result["survived"],
                    "has_failed": has_failed,
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

    # --- 聚合统计 ---
    # success_rate / funded_ratio 用 (完整 ∪ 已失败不完整),与 compute_success_rate
    # 语义对齐:已观察到的失败一律计入分母,截尾未失败排除(数据不足判定)。
    # 分位数轨迹 / final values / portfolio_metrics 仍仅基于完整路径,避免
    # padded-zero 拉低分位数曲线。
    complete = [p for p in paths if p["is_complete"]]
    incomplete_failed = [p for p in paths if (not p["is_complete"]) and p["has_failed"]]
    stats_eligible = complete + incomplete_failed
    num_excluded = len(paths) - len(stats_eligible)

    if len(stats_eligible) == 0:
        for p in paths:
            p.pop("_real_returns", None)
            p.pop("_inflation", None)
        return {
            "num_paths": len(paths),
            "num_complete": 0,
            "num_incomplete_failed": 0,
            "num_excluded": num_excluded,
            "success_rate": 0.0,
            "funded_ratio": 0.0,
            "percentile_trajectories": {},
            "withdrawal_percentile_trajectories": None,
            "final_values_summary": [],
            "portfolio_metrics": [],
            "paths": paths,
        }

    elig_traj = np.array([
        _pad_portfolio_to(p["portfolio"], retirement_years + 1) for p in stats_eligible
    ])
    elig_wd = np.array([
        _pad_withdrawals_to(p["withdrawals"], retirement_years) for p in stats_eligible
    ])

    success_rate = compute_success_rate(elig_traj, retirement_years)
    funded_ratio = compute_funded_ratio(elig_traj, retirement_years)

    if len(complete) == 0:
        for p in paths:
            p.pop("_real_returns", None)
            p.pop("_inflation", None)
        return {
            "num_paths": len(paths),
            "num_complete": 0,
            "num_incomplete_failed": len(incomplete_failed),
            "num_excluded": num_excluded,
            "success_rate": success_rate,
            "funded_ratio": funded_ratio,
            "percentile_trajectories": {},
            "withdrawal_percentile_trajectories": None,
            "final_values_summary": [],
            "portfolio_metrics": [],
            "paths": paths,
        }

    traj = np.array([p["portfolio"] for p in complete])
    wd_mat = np.array([p["withdrawals"] for p in complete])

    stats = compute_statistics(traj, retirement_years, wd_mat)
    summary_df = final_values_summary_table(stats)

    real_ret_mat = np.array([p["_real_returns"] for p in complete])
    infl_mat = np.array([p["_inflation"] for p in complete])

    port_metrics = compute_portfolio_metrics(real_ret_mat, infl_mat)

    for p in paths:
        p.pop("_real_returns", None)
        p.pop("_inflation", None)

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
        "num_incomplete_failed": len(incomplete_failed),
        "num_excluded": num_excluded,
        "success_rate": success_rate,
        "funded_ratio": funded_ratio,
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
        "num_incomplete_failed": 0,
        "num_excluded": 0,
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
            year_labels = [int(start_year - 1)] + years_arr[i:i + n_years].tolist()

            _path_floor = max(consumption_floor * annual_withdrawal, consumption_floor_amount)
            _path_below_floor = any(w < _path_floor for w in result["g_withdrawals"])

            # Legacy survived: backward-compatible (no early depletion, above floor).
            # has_failed: deterministic failure within observation window AND
            # fail_year < retirement_years. Drives success-rate aggregation.
            g_port = result["g_portfolio"]
            b_port = result["b_portfolio"]
            _g_early_depleted = any(g_port[y] <= 0 for y in range(1, len(g_port) - 1))
            _b_early_depleted = any(b_port[y] <= 0 for y in range(1, len(b_port) - 1))
            _g_survived = (
                n_years >= retirement_years
                and not _g_early_depleted
                and not _path_below_floor
            )

            g_has_failed = _has_failed_guardrail(
                np.asarray(result["g_portfolio"], dtype=float),
                np.asarray(result["g_withdrawals"], dtype=float),
                n_years, _path_floor, retirement_years,
            )
            b_has_failed = _has_failed_depletion(
                np.asarray(result["b_portfolio"], dtype=float),
                n_years, retirement_years,
            )

            paths.append({
                "country": iso,
                "start_year": start_year,
                "years_simulated": result["years_simulated"],
                "is_complete": n_years >= retirement_years,
                "g_survived": _g_survived,
                "b_survived": n_years >= retirement_years and not _b_early_depleted,
                "g_has_failed": g_has_failed,
                "b_has_failed": b_has_failed,
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

    # --- 聚合 ---
    # success_rate / funded_ratio 用 (完整 ∪ 已失败不完整);分位数轨迹仅用完整路径。
    # g 与 b 各自有独立的 has_failed 判定,因此 eligible 集合可能不同。
    complete = [p for p in paths if p["is_complete"]]
    g_incomp_failed = [p for p in paths if (not p["is_complete"]) and p["g_has_failed"]]
    b_incomp_failed = [p for p in paths if (not p["is_complete"]) and p["b_has_failed"]]
    g_eligible = complete + g_incomp_failed
    b_eligible = complete + b_incomp_failed
    # 主展示口径: g 视角的 num_excluded
    num_excluded = len(paths) - len(g_eligible)

    if len(g_eligible) == 0 and len(b_eligible) == 0:
        return {
            **_empty_guardrail_batch_result(),
            "num_paths": len(paths),
            "num_incomplete_failed_g": 0,
            "num_incomplete_failed_b": 0,
            "num_excluded": num_excluded,
            "paths": paths,
        }

    target_len = retirement_years + 1
    band_pcts = [10, 25, 50, 75, 90]

    if g_eligible:
        g_traj_elig = np.array([
            _pad_portfolio_to(p["g_portfolio"], target_len) for p in g_eligible
        ])
        g_wd_elig = np.array([
            _pad_withdrawals_to(p["g_withdrawals"], retirement_years) for p in g_eligible
        ])
        g_fr, g_success = compute_effective_funded_ratio(
            g_wd_elig, annual_withdrawal, retirement_years,
            consumption_floor=consumption_floor,
            trajectories=g_traj_elig,
            consumption_floor_amount=consumption_floor_amount,
        )
    else:
        g_fr, g_success = 0.0, 0.0

    if b_eligible:
        b_traj_elig = np.array([
            _pad_portfolio_to(p["b_portfolio"], target_len) for p in b_eligible
        ])
        b_wd_elig = np.array([
            _pad_withdrawals_to(p["b_withdrawals"], retirement_years) for p in b_eligible
        ])
        b_success = compute_success_rate(b_traj_elig, retirement_years)
        b_fr = compute_funded_ratio(b_traj_elig, retirement_years)
    else:
        b_success, b_fr = 0.0, 0.0

    # 分位数轨迹 — 仅基于完整路径,避免 padded zeros 拉低曲线
    if complete:
        g_traj_c = np.array([p["g_portfolio"] for p in complete])
        g_wd_c = np.array([p["g_withdrawals"] for p in complete])
        b_traj_c = np.array([p["b_portfolio"] for p in complete])
        b_wd_c = np.array([p["b_withdrawals"] for p in complete])
        g_pct_traj = {str(p): np.percentile(g_traj_c, p, axis=0).tolist() for p in band_pcts}
        b_pct_traj = {str(p): np.percentile(b_traj_c, p, axis=0).tolist() for p in band_pcts}
        g_wd_pcts = {str(p): np.percentile(g_wd_c, p, axis=0).tolist() for p in band_pcts}
        b_wd_pcts = {str(p): np.percentile(b_wd_c, p, axis=0).tolist() for p in band_pcts}
    else:
        g_pct_traj = {}
        b_pct_traj = {}
        g_wd_pcts = {}
        b_wd_pcts = {}

    return {
        "num_paths": len(paths),
        "num_complete": len(complete),
        "num_incomplete_failed_g": len(g_incomp_failed),
        "num_incomplete_failed_b": len(b_incomp_failed),
        "num_excluded": num_excluded,
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
        "num_incomplete_failed_g": 0,
        "num_incomplete_failed_b": 0,
        "num_excluded": 0,
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
