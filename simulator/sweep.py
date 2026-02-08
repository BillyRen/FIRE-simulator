"""提取率扫描引擎 — 用于敏感性分析。

核心优化：预生成 bootstrap 回报序列后复用于所有扫描点，
避免为每个提取率重复进行昂贵的 bootstrap 采样。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .bootstrap import block_bootstrap
from .cashflow import CashFlowItem, build_cf_schedule
from .portfolio import compute_real_portfolio_returns


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
) -> tuple[np.ndarray, np.ndarray]:
    """预生成实际组合回报矩阵和通胀矩阵。

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
    rng = np.random.default_rng(seed)
    scenarios = np.zeros((num_simulations, retirement_years))
    inflation_matrix = np.zeros((num_simulations, retirement_years))

    for i in range(num_simulations):
        sampled = block_bootstrap(
            returns_df, retirement_years, min_block, max_block, rng=rng
        )
        scenarios[i] = compute_real_portfolio_returns(
            sampled, allocation, expense_ratios,
            leverage=leverage, borrowing_spread=borrowing_spread,
        )
        inflation_matrix[i] = sampled["US Inflation"].values

    return scenarios, inflation_matrix


def _simulate_success_rate(
    real_returns_matrix: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    withdrawal_strategy: str,
    dynamic_ceiling: float,
    dynamic_floor: float,
    cash_flows: list[CashFlowItem] | None = None,
    inflation_matrix: np.ndarray | None = None,
) -> float:
    """给定预生成回报矩阵和参数，快速计算成功率。

    Parameters
    ----------
    real_returns_matrix : np.ndarray
        shape (num_simulations, retirement_years) 的回报矩阵。
    initial_portfolio : float
        初始资产。
    annual_withdrawal : float
        年提取金额。
    withdrawal_strategy : str
        "fixed" 或 "dynamic"。
    dynamic_ceiling, dynamic_floor : float
        动态策略的上下限。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_matrix : np.ndarray or None
        shape (num_simulations, retirement_years) 的通胀率矩阵。
        仅在存在非通胀调整现金流时需要。

    Returns
    -------
    float
        成功率 (0-1)。
    """
    num_sims, retirement_years = real_returns_matrix.shape
    initial_rate = annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0.0

    has_cf = cash_flows is not None and len(cash_flows) > 0
    # 预计算通胀调整部分的固定 schedule（所有路径共享）
    if has_cf:
        has_nominal = any(not cf.inflation_adjusted for cf in cash_flows)
        # 通胀调整项的 schedule（路径无关）
        adj_only = [cf for cf in cash_flows if cf.inflation_adjusted]
        fixed_schedule = build_cf_schedule(adj_only, retirement_years)
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
    else:
        fixed_schedule = None

    survived = 0
    for i in range(num_sims):
        value = initial_portfolio
        prev_wd = annual_withdrawal
        failed = False

        # 计算该路径的现金流 schedule
        if has_cf:
            if has_nominal and inflation_matrix is not None:
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                cf_schedule = fixed_schedule + nominal_schedule
            else:
                cf_schedule = fixed_schedule
        else:
            cf_schedule = None

        for year in range(retirement_years):
            # 确定提取金额
            if withdrawal_strategy == "dynamic" and year > 0 and value > 0:
                target = value * initial_rate
                upper = prev_wd * (1.0 + dynamic_ceiling)
                lower = prev_wd * (1.0 - dynamic_floor)
                wd = max(lower, min(target, upper))
            else:
                wd = annual_withdrawal

            prev_wd = wd
            value = value * (1.0 + real_returns_matrix[i, year]) - wd

            # 加入自定义现金流
            if cf_schedule is not None:
                value += cf_schedule[year]

            if value <= 0:
                failed = True
                break

        if not failed:
            survived += 1

    return survived / num_sims


def sweep_withdrawal_rates(
    real_returns_matrix: np.ndarray,
    initial_portfolio: float,
    rate_min: float = 0.0,
    rate_max: float = 0.15,
    rate_step: float = 0.001,
    withdrawal_strategy: str = "fixed",
    dynamic_ceiling: float = 0.05,
    dynamic_floor: float = 0.025,
    cash_flows: list[CashFlowItem] | None = None,
    inflation_matrix: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """扫描提取率范围，计算每个提取率对应的成功率。

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
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_matrix : np.ndarray or None
        通胀率矩阵。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (rates, success_rates) — 两个等长的一维数组。
    """
    rates = np.arange(rate_min, rate_max + rate_step / 2, rate_step)
    success_rates = np.empty(len(rates))

    for idx, rate in enumerate(rates):
        annual_wd = initial_portfolio * rate
        success_rates[idx] = _simulate_success_rate(
            real_returns_matrix,
            initial_portfolio,
            annual_wd,
            withdrawal_strategy,
            dynamic_ceiling,
            dynamic_floor,
            cash_flows=cash_flows,
            inflation_matrix=inflation_matrix,
        )

    return rates, success_rates


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

    for t in targets:
        if t > success_rates[0]:
            results.append(None)
            continue
        if t <= success_rates[-1]:
            results.append(float(rates[-1]))
            continue

        found = False
        for i in range(len(success_rates) - 1):
            if success_rates[i] >= t and success_rates[i + 1] < t:
                frac = (t - success_rates[i + 1]) / (success_rates[i] - success_rates[i + 1])
                interp_rate = rates[i + 1] + frac * (rates[i] - rates[i + 1])
                results.append(float(interp_rate))
                found = True
                break
        if not found:
            results.append(None)

    return results
