"""提取率扫描引擎 — 用于敏感性分析。

核心优化：预生成 bootstrap 回报序列后复用于所有扫描点，
避免为每个提取率重复进行昂贵的 bootstrap 采样。

Phase 2.3优化：使用multiprocessing并行化sweep循环，充分利用多核CPU。
"""

from __future__ import annotations

import functools
import os
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count

import numpy as np
import pandas as pd

from .bootstrap import (
    IDX_DS, IDX_GS, IDX_DB, IDX_INF,
    RETURN_COLS,
    block_bootstrap_np,
    block_bootstrap_pooled_np,
    _prepare_pooled_arrays,
)
from .cashflow import CashFlowItem, build_cf_schedule, has_probabilistic_cf, sample_cash_flows
from .config import is_low_memory
from .monte_carlo import compute_withdrawal
from .portfolio import compute_real_portfolio_returns_np

# 并行化配置：使用CPU核心数，但限制最大值避免资源耗尽
# 在低核心环境（如 Render 0.5 CPU）中，进程池 fork 开销反而拖慢性能
# 低内存环境（如 Render Starter 512 MB）中禁用进程池以避免 fork 内存翻倍
_cpu = cpu_count() or 1
if is_low_memory():
    MAX_WORKERS = 1
else:
    MAX_WORKERS = min(_cpu, int(os.getenv("MAX_SWEEP_WORKERS", "8"))) if _cpu > 1 else 1

# ============================================================================
# 进程池 initializer：共享只读大数据，避免每个 task 重复 pickle 序列化
# ============================================================================
_worker_shared: dict = {}


def _init_worker(shared_data: dict):
    """进程池 worker 初始化：存储共享只读数据，避免每个 task 重复 pickle。"""
    _worker_shared.update(shared_data)


# ============================================================================
# Bootstrap 并行化辅助函数（必须在模块级别以支持pickle）
# ============================================================================

def _do_bootstrap_np(retirement_years, min_block, max_block, rng, _shared=None):
    """执行单次 bootstrap 采样（numpy, 从 shared dict 读取缓存数组）。"""
    s = _shared if _shared is not None else _worker_shared
    c_arrays = s.get("c_arrays")
    if c_arrays is not None:
        return block_bootstrap_pooled_np(
            c_arrays, s["c_lens"], s["c_probs"],
            retirement_years, min_block, max_block, rng=rng,
        )
    return block_bootstrap_np(
        s["src_data"], s["src_n"],
        retirement_years, min_block, max_block, rng=rng,
    )


def _bootstrap_single_scenario(args, _shared=None):
    """单个 bootstrap 采样任务（从 shared dict 读取共享数据）。"""
    (sim_index, allocation, expense_ratios, retirement_years,
     min_block, max_block, leverage, borrowing_spread, seed_base) = args

    rng = np.random.default_rng(seed_base + sim_index if seed_base is not None else None)

    data = _do_bootstrap_np(retirement_years, min_block, max_block, rng, _shared=_shared)

    real_returns = compute_real_portfolio_returns_np(
        data, allocation, expense_ratios,
        leverage=leverage, borrowing_spread=borrowing_spread,
    )
    return sim_index, real_returns, data[:, IDX_INF].copy()


def _bootstrap_single_raw(args, _shared=None):
    """单个 bootstrap 采样任务（raw scenarios，从 shared dict 读取共享数据）。"""
    (sim_index, expense_ratios, retirement_years,
     min_block, max_block, seed_base) = args

    rng = np.random.default_rng(seed_base + sim_index if seed_base is not None else None)

    data = _do_bootstrap_np(retirement_years, min_block, max_block, rng, _shared=_shared)

    return sim_index, {
        "domestic_stock": data[:, IDX_DS] - expense_ratios.get("domestic_stock", 0.0),
        "global_stock": data[:, IDX_GS] - expense_ratios.get("global_stock", 0.0),
        "domestic_bond": data[:, IDX_DB] - expense_ratios.get("domestic_bond", 0.0),
        "inflation": data[:, IDX_INF].copy(),
    }


def pregenerate_return_scenarios(
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    retirement_years: int,
    min_block: int,
    max_block: int,
    num_simulations: int,
    returns_df: pd.DataFrame,
    seed: int | None = None,
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
    country_dfs: dict[str, pd.DataFrame] | None = None,
    country_weights: dict[str, float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """预生成实际组合回报矩阵和通胀矩阵。

    Phase 2.4优化：使用ProcessPoolExecutor并行化bootstrap采样（4-8x加速）。

    Parameters
    ----------
    allocation : dict
        资产配置比例。
    expense_ratios : dict
        各资产费用率。
    retirement_years : int
        退休年限。
    min_block, max_block : int
        Block bootstrap 窗口范围。
    num_simulations : int
        模拟次数。
    returns_df : pd.DataFrame
        历史回报数据。
    seed : int or None
        随机种子。
    leverage : float
        杠杆倍数。
    borrowing_spread : float
        借贷利差。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (scenarios, inflation_matrix)
        - scenarios: shape (num_simulations, retirement_years) 的实际组合回报率矩阵。
        - inflation_matrix: shape (num_simulations, retirement_years) 的年度通胀率矩阵。
    """
    scenarios = np.zeros((num_simulations, retirement_years))
    inflation_matrix = np.zeros((num_simulations, retirement_years))

    # Pre-extract numpy arrays from DataFrames
    if country_dfs is not None:
        _, c_arrays, c_lens, c_probs = _prepare_pooled_arrays(
            country_dfs, country_weights, RETURN_COLS,
        )
        shared = {"c_arrays": c_arrays, "c_lens": c_lens, "c_probs": c_probs, "src_data": None, "src_n": 0}
    else:
        src_data = returns_df[RETURN_COLS].values
        shared = {"c_arrays": None, "c_lens": None, "c_probs": None, "src_data": src_data, "src_n": len(src_data)}

    # 统一使用 per-index seed 保证并行/顺序路径结果一致
    tasks = [
        (i, allocation, expense_ratios, retirement_years,
         min_block, max_block, leverage, borrowing_spread, seed)
        for i in range(num_simulations)
    ]

    if num_simulations > 100 and MAX_WORKERS > 1:
        chunksize = max(1, num_simulations // (MAX_WORKERS * 4))
        try:
            with ProcessPoolExecutor(
                max_workers=MAX_WORKERS,
                initializer=_init_worker,
                initargs=(shared,),
            ) as executor:
                results = list(executor.map(_bootstrap_single_scenario, tasks, chunksize=chunksize))
        except (OSError, RuntimeError, PermissionError, NotImplementedError):
            worker = functools.partial(_bootstrap_single_scenario, _shared=shared)
            results = [worker(task) for task in tasks]
    else:
        worker = functools.partial(_bootstrap_single_scenario, _shared=shared)
        results = [worker(task) for task in tasks]

    for sim_index, real_returns, inflation in results:
        scenarios[sim_index] = real_returns
        inflation_matrix[sim_index] = inflation

    return scenarios, inflation_matrix


def _classify_cash_flows(
    cash_flows: list[CashFlowItem] | None,
    retirement_years: int,
) -> tuple[bool, bool, bool, np.ndarray | None, list[CashFlowItem]]:
    """Classify CFs and precompute path-independent schedule.

    Returns (has_cf, has_groups, has_nominal, fixed_schedule, nominal_cfs).
    """
    has_cf = cash_flows is not None and len(cash_flows) > 0
    has_groups = has_cf and has_probabilistic_cf(cash_flows)
    if has_cf and not has_groups:
        has_nominal = any(not cf.inflation_adjusted for cf in cash_flows)
        adj_only = [cf for cf in cash_flows if cf.inflation_adjusted]
        fixed_schedule = build_cf_schedule(adj_only, retirement_years)
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
    else:
        has_nominal = False
        fixed_schedule = None
        nominal_cfs = []
    return has_cf, has_groups, has_nominal, fixed_schedule, nominal_cfs


def _batch_nominal_cf_matrix(
    nominal_cfs: list[CashFlowItem],
    retirement_years: int,
    inflation_matrix: np.ndarray,
) -> np.ndarray:
    """Batch-compute nominal CF schedules for all sims at once.

    Returns (num_sims, retirement_years) matrix of nominal CF contributions
    in real (inflation-adjusted) terms.
    """
    num_sims = inflation_matrix.shape[0]
    cum_infl = np.cumprod(1.0 + inflation_matrix, axis=1)  # (N, Y)
    result = np.zeros((num_sims, retirement_years))
    for cf in nominal_cfs:
        start_idx = cf.start_year - 1
        end_idx = min(start_idx + cf.duration, retirement_years)
        if start_idx < 0 or start_idx >= retirement_years:
            continue
        t_range = np.arange(end_idx - start_idx)
        nominal_vals = cf.amount * (1.0 + cf.growth_rate) ** t_range  # (D,)
        result[:, start_idx:end_idx] += nominal_vals[np.newaxis, :] / cum_infl[:, start_idx:end_idx]
    return result


def _precompute_withdrawal_schedule(
    strategy: str,
    retirement_years: int,
    annual_withdrawal: float,
    retirement_age: int = 45,
    declining_rate: float = 0.02,
    declining_start_age: int = 65,
    smile_decline_rate: float = 0.01,
    smile_decline_start_age: int = 65,
    smile_min_age: int = 80,
    smile_increase_rate: float = 0.01,
) -> np.ndarray:
    """Precompute deterministic withdrawal schedule for fixed/declining/smile.

    These strategies depend only on year number, not portfolio value,
    so the schedule can be precomputed and used in vectorized simulation.
    """
    if strategy == "fixed":
        return np.full(retirement_years, annual_withdrawal)

    schedule = np.empty(retirement_years)
    if strategy == "declining":
        prev = annual_withdrawal
        for year in range(retirement_years):
            age = retirement_age + year
            if year > 0 and age >= declining_start_age:
                prev = prev * (1.0 - declining_rate)
            else:
                prev = annual_withdrawal
            schedule[year] = prev
    elif strategy == "smile":
        for year in range(retirement_years):
            age = retirement_age + year
            if age < smile_decline_start_age:
                schedule[year] = annual_withdrawal
            elif age < smile_min_age:
                schedule[year] = annual_withdrawal * (1.0 - smile_decline_rate) ** (age - smile_decline_start_age)
            else:
                min_spending = annual_withdrawal * (1.0 - smile_decline_rate) ** (smile_min_age - smile_decline_start_age)
                schedule[year] = min_spending * (1.0 + smile_increase_rate) ** (age - smile_min_age)
    else:
        raise ValueError(f"Cannot precompute schedule for strategy: {strategy}")
    return schedule


def _simulate_vectorized(
    real_returns_matrix: np.ndarray,
    initial_portfolio: float,
    wd_schedule: np.ndarray,
    cf_schedule: np.ndarray | None = None,
    cf_matrix: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized simulation loop with optional CF support.

    Parameters
    ----------
    wd_schedule : np.ndarray
        (retirement_years,) withdrawal amount per year.
    cf_schedule : np.ndarray or None
        (retirement_years,) path-independent CF schedule (same for all sims).
    cf_matrix : np.ndarray or None
        (num_sims, retirement_years) per-sim CF schedule (e.g. nominal CFs).
        If provided, takes precedence over cf_schedule.

    Returns
    -------
    (depletion_years, final_values)
    """
    num_sims, retirement_years = real_returns_matrix.shape
    values = np.full(num_sims, initial_portfolio, dtype=np.float64)
    depletion_years = np.full(num_sims, float(retirement_years))
    alive = np.ones(num_sims, dtype=bool)

    has_per_sim_cf = cf_matrix is not None
    has_uniform_cf = cf_schedule is not None and not has_per_sim_cf

    for year in range(retirement_years):
        grown = values[alive] * (1.0 + real_returns_matrix[alive, year])
        actual_wd = np.minimum(wd_schedule[year], np.maximum(grown, 0.0))
        values[alive] = grown - actual_wd

        # Apply CF: expenses before depletion check, income after
        if has_uniform_cf:
            cf_val = cf_schedule[year]
            if cf_val < 0:
                values[alive] += cf_val
        elif has_per_sim_cf:
            alive_idx = np.flatnonzero(alive)
            cf_vals = cf_matrix[alive_idx, year]
            expense_mask = cf_vals < 0
            if np.any(expense_mask):
                idx = alive_idx[expense_mask]
                values[idx] += cf_vals[expense_mask]

        newly_failed = alive & (values <= 0)
        if np.any(newly_failed):
            depletion_years[newly_failed] = float(year + 1)
            values[newly_failed] = 0.0
            alive[newly_failed] = False

        if has_uniform_cf:
            if cf_val > 0:
                values[alive] += cf_val
        elif has_per_sim_cf:
            # Re-check alive status after depletion
            income_mask = cf_vals > 0
            still_alive = alive[alive_idx]
            apply_income = income_mask & still_alive
            if np.any(apply_income):
                idx = alive_idx[apply_income]
                values[idx] += cf_vals[apply_income]

        if not np.any(alive):
            break

    return depletion_years, values


def _simulate_success_and_funded(
    real_returns_matrix: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    withdrawal_strategy: str,
    dynamic_ceiling: float,
    dynamic_floor: float,
    retirement_age: int = 45,
    cash_flows: list[CashFlowItem] | None = None,
    inflation_matrix: np.ndarray | None = None,
    declining_rate: float = 0.02,
    declining_start_age: int = 65,
    smile_decline_rate: float = 0.01,
    smile_decline_start_age: int = 65,
    smile_min_age: int = 80,
    smile_increase_rate: float = 0.01,
) -> tuple[float, float]:
    """给定预生成回报矩阵和参数，快速计算成功率和资金覆盖率。

    Parameters
    ----------
    real_returns_matrix : np.ndarray
        shape (num_simulations, retirement_years) 的回报矩阵。
    initial_portfolio : float
        初始资产。
    annual_withdrawal : float
        年提取金额。
    withdrawal_strategy : str
        "fixed"、"dynamic" 或 "declining"。
    dynamic_ceiling, dynamic_floor : float
        动态策略的上下限。
    retirement_age : int
        退休年龄（declining 策略使用）。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_matrix : np.ndarray or None
        shape (num_simulations, retirement_years) 的通胀率矩阵。
        仅在存在非通胀调整现金流时需要。

    Returns
    -------
    tuple[float, float]
        (success_rate, funded_ratio)，均为 0-1 之间的浮点数。
    """
    num_sims, retirement_years = real_returns_matrix.shape
    initial_rate = annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0.0

    has_cf, has_groups, has_nominal, fixed_schedule, nominal_cfs = _classify_cash_flows(
        cash_flows, retirement_years,
    )

    # Check ALL CFs for nominal items (has_nominal only covers non-grouped CFs)
    if has_cf and inflation_matrix is None and any(
        not cf.inflation_adjusted for cf in cash_flows
    ):
        raise ValueError(
            "inflation_matrix is required when nominal (non-inflation-adjusted) "
            "cash flows are present"
        )

    # Precompute nominal CF matrix if needed (batch across all sims)
    nominal_cf_matrix = None
    if has_nominal and not has_groups:
        nominal_cf_matrix = _batch_nominal_cf_matrix(nominal_cfs, retirement_years, inflation_matrix)

    # ── Vectorized fast path: fixed/declining/smile, no probabilistic groups ──
    can_vectorize = withdrawal_strategy in ("fixed", "declining", "smile") and not has_groups
    if can_vectorize:
        wd_sched = _precompute_withdrawal_schedule(
            withdrawal_strategy, retirement_years, annual_withdrawal,
            retirement_age, declining_rate, declining_start_age,
            smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
        )
        if nominal_cf_matrix is not None:
            cf_mat = fixed_schedule[np.newaxis, :] + nominal_cf_matrix
            depletion_years, _ = _simulate_vectorized(
                real_returns_matrix, initial_portfolio, wd_sched,
                cf_matrix=cf_mat,
            )
        else:
            depletion_years, _ = _simulate_vectorized(
                real_returns_matrix, initial_portfolio, wd_sched,
                cf_schedule=fixed_schedule,  # None when no CF, (Y,) when adj-only CF
            )
        success_rate = float(np.mean(depletion_years >= retirement_years))
        funded_ratio = float(np.mean(np.minimum(depletion_years / retirement_years, 1.0)))
        return success_rate, funded_ratio

    # ── General scalar path: dynamic strategy or probabilistic groups ──
    rng = np.random.default_rng() if has_groups else None

    depletion_years = np.full(num_sims, float(retirement_years))

    for i in range(num_sims):
        value = initial_portfolio
        prev_wd = annual_withdrawal

        # 计算该路径的现金流 schedule
        if has_groups:
            active_cfs = sample_cash_flows(cash_flows, rng)
            if active_cfs:
                _adj = [cf for cf in active_cfs if cf.inflation_adjusted]
                _nom = [cf for cf in active_cfs if not cf.inflation_adjusted]
                _adj_sched = build_cf_schedule(_adj, retirement_years) if _adj else np.zeros(retirement_years)
                if _nom and inflation_matrix is not None:
                    _nom_sched = build_cf_schedule(_nom, retirement_years, inflation_matrix[i])
                    cf_schedule = _adj_sched + _nom_sched
                else:
                    cf_schedule = _adj_sched
            else:
                cf_schedule = None
        elif has_cf:
            if nominal_cf_matrix is not None:
                cf_schedule = fixed_schedule + nominal_cf_matrix[i]
            else:
                cf_schedule = fixed_schedule
        else:
            cf_schedule = None

        for year in range(retirement_years):
            wd = compute_withdrawal(
                withdrawal_strategy, year, value, annual_withdrawal, prev_wd,
                initial_rate, retirement_age, dynamic_ceiling, dynamic_floor,
                declining_rate, declining_start_age,
                smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
            )

            prev_wd = wd
            value_after_growth = value * (1.0 + real_returns_matrix[i, year])
            actual_wd = min(wd, max(value_after_growth, 0.0))
            value = value_after_growth - actual_wd

            # Apply expenses before depletion check (net schedule for portfolio)
            if cf_schedule is not None and cf_schedule[year] < 0:
                value += cf_schedule[year]

            if value <= 0:
                depletion_years[i] = float(year + 1)
                break

            # Apply income after depletion check (net schedule for portfolio)
            if cf_schedule is not None and cf_schedule[year] > 0:
                value += cf_schedule[year]

    success_rate = float(np.mean(depletion_years >= retirement_years))
    funded_ratio = float(np.mean(np.minimum(depletion_years / retirement_years, 1.0)))
    return success_rate, funded_ratio


# ============================================================================
# 并行化辅助函数（必须在模块级别以支持pickle）
# ============================================================================

def _sweep_single_rate(args, _shared=None):
    """单个提取率的模拟任务（从 shared dict 读取共享矩阵数据）。"""
    (rate, initial_portfolio, withdrawal_strategy,
     dynamic_ceiling, dynamic_floor, retirement_age, cash_flows) = args

    s = _shared if _shared is not None else _worker_shared
    annual_wd = initial_portfolio * rate
    sr, fr = _simulate_success_and_funded(
        s["real_returns_matrix"],
        initial_portfolio,
        annual_wd,
        withdrawal_strategy,
        dynamic_ceiling,
        dynamic_floor,
        retirement_age=retirement_age,
        cash_flows=cash_flows,
        inflation_matrix=s.get("inflation_matrix"),
    )
    return sr, fr


def _sweep_single_allocation(args, _shared=None):
    """单个资产配置的模拟任务（从 shared dict 读取共享矩阵数据）。"""
    (w_us, w_intl, w_bond,
     initial_portfolio, annual_withdrawal, leverage, borrowing_spread,
     withdrawal_strategy, dynamic_ceiling, dynamic_floor, retirement_age,
     cash_flows,
     declining_rate, declining_start_age,
     smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
     ) = args

    s = _shared if _shared is not None else _worker_shared
    us_stock = s["us_stock"]
    intl_stock = s["intl_stock"]
    us_bond = s["us_bond"]
    inflation = s["inflation"]

    num_sims, retirement_years = us_stock.shape

    has_cf, has_groups, has_nominal, fixed_schedule, nominal_cfs = _classify_cash_flows(
        cash_flows, retirement_years,
    )

    initial_rate = annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0.0

    # 1. 加权计算名义回报
    nominal = w_us * us_stock + w_intl * intl_stock + w_bond * us_bond

    # 2. 杠杆
    if leverage != 1.0:
        borrowing_cost = inflation + borrowing_spread
        nominal = leverage * nominal - (leverage - 1.0) * borrowing_cost

    # 3. 转换为实际回报
    real_returns = (1.0 + nominal) / (1.0 + inflation) - 1.0

    if has_cf and inflation is None and any(
        not cf.inflation_adjusted for cf in cash_flows
    ):
        raise ValueError(
            "inflation is required when nominal (non-inflation-adjusted) "
            "cash flows are present"
        )

    # Precompute nominal CF matrix if needed
    nominal_cf_matrix = None
    if has_nominal and not has_groups:
        nominal_cf_matrix = _batch_nominal_cf_matrix(nominal_cfs, retirement_years, inflation)

    # 4. 逐年模拟
    # ── Vectorized fast path: fixed/declining/smile, no probabilistic groups ──
    can_vectorize = withdrawal_strategy in ("fixed", "declining", "smile") and not has_groups
    if can_vectorize:
        wd_sched = _precompute_withdrawal_schedule(
            withdrawal_strategy, retirement_years, annual_withdrawal,
            retirement_age, declining_rate, declining_start_age,
            smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
        )
        if nominal_cf_matrix is not None:
            cf_mat = fixed_schedule[np.newaxis, :] + nominal_cf_matrix
            depletion_years, final_values = _simulate_vectorized(
                real_returns, initial_portfolio, wd_sched,
                cf_matrix=cf_mat,
            )
        else:
            depletion_years, final_values = _simulate_vectorized(
                real_returns, initial_portfolio, wd_sched,
                cf_schedule=fixed_schedule,
            )
    else:
        # ── General scalar path ──
        rng = np.random.default_rng() if has_groups else None
        final_values = np.zeros(num_sims)
        depletion_years = np.full(num_sims, retirement_years, dtype=float)

        for i in range(num_sims):
            value = initial_portfolio
            prev_wd = annual_withdrawal
            failed = False

            # 现金流 schedule
            if has_groups:
                active_cfs = sample_cash_flows(cash_flows, rng)
                if active_cfs:
                    _adj = [cf for cf in active_cfs if cf.inflation_adjusted]
                    _nom = [cf for cf in active_cfs if not cf.inflation_adjusted]
                    _adj_sched = build_cf_schedule(_adj, retirement_years) if _adj else np.zeros(retirement_years)
                    if _nom and inflation is not None:
                        _nom_sched = build_cf_schedule(_nom, retirement_years, inflation[i])
                        cf_schedule = _adj_sched + _nom_sched
                    else:
                        cf_schedule = _adj_sched
                else:
                    cf_schedule = None
            elif has_cf:
                if nominal_cf_matrix is not None:
                    cf_schedule = fixed_schedule + nominal_cf_matrix[i]
                else:
                    cf_schedule = fixed_schedule
            else:
                cf_schedule = None

            for year in range(retirement_years):
                wd = compute_withdrawal(
                    withdrawal_strategy, year, value, annual_withdrawal, prev_wd,
                    initial_rate, retirement_age, dynamic_ceiling, dynamic_floor,
                    declining_rate, declining_start_age,
                    smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
                )

                prev_wd = wd
                value_after_growth = value * (1.0 + real_returns[i, year])
                actual_wd = min(wd, max(value_after_growth, 0.0))
                value = value_after_growth - actual_wd

                # Apply expenses before depletion check (net schedule for portfolio)
                if cf_schedule is not None and cf_schedule[year] < 0:
                    value += cf_schedule[year]

                if value <= 0:
                    depletion_years[i] = year + 1
                    value = 0.0
                    failed = True
                    break

                # Apply income after depletion check (net schedule for portfolio)
                if cf_schedule is not None and cf_schedule[year] > 0:
                    value += cf_schedule[year]

            final_values[i] = value

    success_rate = float(np.mean(depletion_years >= retirement_years))
    median_final = float(np.median(final_values))
    mean_final = float(np.mean(final_values))

    # P10 耗尽年：第 10 百分位的耗尽年份
    p10_dep = float(np.percentile(depletion_years, 10))
    p10_depletion_year = int(p10_dep) if p10_dep < retirement_years else None

    # Funded Ratio（资金覆盖率）：平均能覆盖多少退休年限
    funded_ratio = float(np.mean(np.minimum(depletion_years / retirement_years, 1.0)))

    # CVaR₁₀：最差 10% 场景的平均终值
    sorted_finals = np.sort(final_values)
    n10 = max(1, int(0.1 * num_sims))
    cvar_10 = float(np.mean(sorted_finals[:n10]))

    # P90 终值：最好 10% 场景的门槛
    p90_final = float(np.percentile(final_values, 90))

    return {
        "domestic_stock": round(w_us, 4),
        "global_stock": round(w_intl, 4),
        "domestic_bond": round(w_bond, 4),
        "success_rate": success_rate,
        "median_final": median_final,
        "mean_final": mean_final,
        "p10_depletion_year": p10_depletion_year,
        "funded_ratio": funded_ratio,
        "cvar_10": cvar_10,
        "p90_final": p90_final,
    }


def raw_to_combined(
    raw: dict[str, np.ndarray],
    allocation: dict[str, float],
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
) -> np.ndarray:
    """Compute combined real returns from per-asset raw return matrices.

    Parameters
    ----------
    raw : dict
        Output from pregenerate_raw_scenarios() — per-asset return matrices
        (already net of expense ratios) and inflation.
    allocation : dict
        Asset weights, e.g. {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3}.
    leverage : float
        Leverage multiplier.
    borrowing_spread : float
        Borrowing cost spread (above inflation).

    Returns
    -------
    np.ndarray
        Shape (num_simulations, retirement_years) combined real returns.
    """
    w_us = allocation.get("domestic_stock", 0)
    w_intl = allocation.get("global_stock", 0)
    w_bond = allocation.get("domestic_bond", 0)
    inflation = raw["inflation"]

    nominal = w_us * raw["domestic_stock"] + w_intl * raw["global_stock"] + w_bond * raw["domestic_bond"]
    if leverage != 1.0:
        nominal = leverage * nominal - (leverage - 1.0) * (inflation + borrowing_spread)
    real = (1.0 + nominal) / (1.0 + inflation) - 1.0
    return real


def sweep_withdrawal_rates(
    real_returns_matrix: np.ndarray,
    initial_portfolio: float,
    rate_min: float = 0.0,
    rate_max: float = 0.15,
    rate_step: float = 0.001,
    withdrawal_strategy: str = "fixed",
    dynamic_ceiling: float = 0.05,
    dynamic_floor: float = 0.025,
    retirement_age: int = 45,
    cash_flows: list[CashFlowItem] | None = None,
    inflation_matrix: np.ndarray | None = None,
    declining_rate: float = 0.02,
    declining_start_age: int = 65,
    smile_decline_rate: float = 0.01,
    smile_decline_start_age: int = 65,
    smile_min_age: int = 80,
    smile_increase_rate: float = 0.01,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """扫描提取率范围，计算每个提取率对应的成功率和资金覆盖率。

    Parameters
    ----------
    real_returns_matrix : np.ndarray
        预生成的回报矩阵 (num_simulations, retirement_years)。
    initial_portfolio : float
        初始资产金额。
    rate_min, rate_max : float
        扫描的提取率范围。
    rate_step : float
        扫描步长。
    withdrawal_strategy : str
        提取策略。
    dynamic_ceiling, dynamic_floor : float
        动态策略参数。
    retirement_age : int
        退休年龄（declining 策略使用）。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_matrix : np.ndarray or None
        通胀率矩阵。

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray]
        (rates, success_rates, funded_ratios) — 三个等长的一维数组。
    """
    rates = np.arange(rate_min, rate_max + rate_step / 2, rate_step)

    # 每个 rate 的模拟任务太轻量（~12ms），进程池 overhead 反而拖慢
    # 并行化收益在 bootstrap 层（pregenerate_return_scenarios），此处顺序执行更快
    success_list = []
    funded_list = []
    for rate in rates:
        annual_wd = initial_portfolio * rate
        sr, fr = _simulate_success_and_funded(
            real_returns_matrix, initial_portfolio, annual_wd,
            withdrawal_strategy, dynamic_ceiling, dynamic_floor,
            retirement_age=retirement_age,
            cash_flows=cash_flows,
            inflation_matrix=inflation_matrix,
            declining_rate=declining_rate,
            declining_start_age=declining_start_age,
            smile_decline_rate=smile_decline_rate,
            smile_decline_start_age=smile_decline_start_age,
            smile_min_age=smile_min_age,
            smile_increase_rate=smile_increase_rate,
        )
        success_list.append(sr)
        funded_list.append(fr)

    success_rates = np.array(success_list)
    funded_ratios = np.array(funded_list)

    return rates, success_rates, funded_ratios


def pregenerate_raw_scenarios(
    expense_ratios: dict[str, float],
    retirement_years: int,
    min_block: int,
    max_block: int,
    num_simulations: int,
    returns_df: pd.DataFrame,
    seed: int | None = None,
    country_dfs: dict[str, pd.DataFrame] | None = None,
    country_weights: dict[str, float] | None = None,
) -> dict[str, np.ndarray]:
    """预生成各资产类别的原始回报矩阵（已扣费用，未加权合成）。

    Phase 2.4优化：使用ProcessPoolExecutor并行化bootstrap采样（4-8x加速）。

    与 pregenerate_return_scenarios 不同，本函数不绑定特定资产配置，
    返回的原始矩阵可供不同配置复用。

    Returns
    -------
    dict[str, np.ndarray]
        包含以下键，每个值 shape (num_simulations, retirement_years)：
        - "domestic_stock": 本国股票回报（扣费后）
        - "global_stock": 全球股票回报（扣费后）
        - "domestic_bond": 本国债券回报（扣费后）
        - "inflation": 通胀率
    """
    domestic_stock = np.zeros((num_simulations, retirement_years))
    global_stock = np.zeros((num_simulations, retirement_years))
    domestic_bond = np.zeros((num_simulations, retirement_years))
    inflation = np.zeros((num_simulations, retirement_years))

    # Pre-extract numpy arrays from DataFrames
    if country_dfs is not None:
        _, c_arrays, c_lens, c_probs = _prepare_pooled_arrays(
            country_dfs, country_weights, RETURN_COLS,
        )
        shared = {"c_arrays": c_arrays, "c_lens": c_lens, "c_probs": c_probs, "src_data": None, "src_n": 0}
    else:
        src_data = returns_df[RETURN_COLS].values
        shared = {"c_arrays": None, "c_lens": None, "c_probs": None, "src_data": src_data, "src_n": len(src_data)}

    # 统一使用 per-index seed 保证并行/顺序路径结果一致
    tasks = [
        (i, expense_ratios, retirement_years,
         min_block, max_block, seed)
        for i in range(num_simulations)
    ]

    if num_simulations > 100 and MAX_WORKERS > 1:
        chunksize = max(1, num_simulations // (MAX_WORKERS * 4))
        try:
            with ProcessPoolExecutor(
                max_workers=MAX_WORKERS,
                initializer=_init_worker,
                initargs=(shared,),
            ) as executor:
                results = list(executor.map(_bootstrap_single_raw, tasks, chunksize=chunksize))
        except (OSError, RuntimeError, PermissionError, NotImplementedError):
            worker = functools.partial(_bootstrap_single_raw, _shared=shared)
            results = [worker(task) for task in tasks]
    else:
        worker = functools.partial(_bootstrap_single_raw, _shared=shared)
        results = [worker(task) for task in tasks]

    for sim_index, data in results:
        domestic_stock[sim_index] = data["domestic_stock"]
        global_stock[sim_index] = data["global_stock"]
        domestic_bond[sim_index] = data["domestic_bond"]
        inflation[sim_index] = data["inflation"]

    return {
        "domestic_stock": domestic_stock,
        "global_stock": global_stock,
        "domestic_bond": domestic_bond,
        "inflation": inflation,
    }


def sweep_allocations(
    raw_scenarios: dict[str, np.ndarray],
    initial_portfolio: float,
    annual_withdrawal: float,
    allocation_step: float,
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
) -> list[dict]:
    """扫描所有满足 a+b+c=1 的资产配置，计算各项关键指标。

    Parameters
    ----------
    raw_scenarios : dict
        pregenerate_raw_scenarios 返回的原始回报矩阵。
    initial_portfolio : float
        初始资产金额。
    annual_withdrawal : float
        年提取金额。
    allocation_step : float
        配置步长，如 0.1 表示 10%。
    withdrawal_strategy : str
        提取策略。
    dynamic_ceiling, dynamic_floor : float
        动态策略参数。
    cash_flows : list[CashFlowItem] or None
        自定义现金流。
    leverage : float
        杠杆倍数。
    borrowing_spread : float
        借贷利差。

    Returns
    -------
    list[dict]
        每个 dict 包含: us_stock, intl_stock, us_bond,
        success_rate, median_final, mean_final, p10_depletion_year。
    """
    us_stock = raw_scenarios["domestic_stock"]
    intl_stock = raw_scenarios["global_stock"]
    us_bond = raw_scenarios["domestic_bond"]
    inflation = raw_scenarios["inflation"]
    num_sims, retirement_years = us_stock.shape

    # 生成所有 (a, b, c) 组合，满足 a+b+c = 1.0
    steps = int(round(1.0 / allocation_step))
    allocations = []
    for a in range(steps + 1):
        for b in range(steps + 1 - a):
            c = steps - a - b
            allocations.append((a * allocation_step, b * allocation_step, c * allocation_step))

    # 每个配置的模拟任务太轻量（~20ms），进程池 overhead 反而拖慢
    # 并行化收益在 bootstrap 层（pregenerate_raw_scenarios），此处顺序执行更快
    local_shared = {
        "us_stock": us_stock,
        "intl_stock": intl_stock,
        "us_bond": us_bond,
        "inflation": inflation,
    }
    worker = functools.partial(_sweep_single_allocation, _shared=local_shared)

    results = [
        worker((
            w_us, w_intl, w_bond,
            initial_portfolio, annual_withdrawal, leverage, borrowing_spread,
            withdrawal_strategy, dynamic_ceiling, dynamic_floor, retirement_age,
            cash_flows,
            declining_rate, declining_start_age,
            smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
        ))
        for w_us, w_intl, w_bond in allocations
    ]

    return results


def interpolate_targets(
    rates: np.ndarray,
    success_rates: np.ndarray,
    targets: list[float],
) -> list[float | None]:
    """对每个目标成功率，线性插值出对应的提取率。

    成功率通常随提取率增加而单调递减。对于每个 target，找到
    success_rates 从 >= target 变为 < target 的位置并插值。

    Parameters
    ----------
    rates : np.ndarray
        提取率数组（升序）。
    success_rates : np.ndarray
        对应的成功率数组。
    targets : list[float]
        目标成功率列表，如 [1.0, 0.95, 0.90, ...]。

    Returns
    -------
    list[float | None]
        每个目标对应的提取率。无法确定时返回 None。
    """
    results: list[float | None] = []

    # success_rates 是递减序列，翻转后用 searchsorted 做 O(log n) 查找
    sr_rev = success_rates[::-1]
    rates_rev = rates[::-1]

    for t in targets:
        if t > success_rates[0]:
            results.append(None)
            continue
        if t <= success_rates[-1]:
            results.append(float(rates[-1]))
            continue

        # 在翻转后的递增序列中找到插入位置
        idx_rev = np.searchsorted(sr_rev, t)
        if idx_rev <= 0 or idx_rev >= len(sr_rev):
            results.append(None)
            continue

        # 翻转索引对应原始序列中相邻的两个点
        lo, hi = idx_rev - 1, idx_rev
        denom = sr_rev[hi] - sr_rev[lo]
        if abs(denom) < 1e-12:
            results.append(float(rates_rev[lo]))
        else:
            frac = (t - sr_rev[lo]) / denom
            interp_rate = rates_rev[lo] + frac * (rates_rev[hi] - rates_rev[lo])
            results.append(float(interp_rate))

    return results
