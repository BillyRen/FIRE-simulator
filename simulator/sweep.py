"""提取率扫描引擎 — 用于敏感性分析。

核心优化：预生成 bootstrap 回报序列后复用于所有扫描点，
避免为每个提取率重复进行昂贵的 bootstrap 采样。
"""

import numpy as np
import pandas as pd

from .bootstrap import block_bootstrap
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
) -> np.ndarray:
    """预生成实际组合回报矩阵。

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

    Returns
    -------
    np.ndarray
        shape (num_simulations, retirement_years) 的实际组合回报率矩阵。
    """
    rng = np.random.default_rng(seed)
    scenarios = np.zeros((num_simulations, retirement_years))

    for i in range(num_simulations):
        sampled = block_bootstrap(
            returns_df, retirement_years, min_block, max_block, rng=rng
        )
        scenarios[i] = compute_real_portfolio_returns(
            sampled, allocation, expense_ratios
        )

    return scenarios


def _simulate_success_rate(
    real_returns_matrix: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    withdrawal_strategy: str,
    dynamic_ceiling: float,
    dynamic_floor: float,
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

    Returns
    -------
    float
        成功率 (0-1)。
    """
    num_sims, retirement_years = real_returns_matrix.shape
    initial_rate = annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0.0

    survived = 0
    for i in range(num_sims):
        value = initial_portfolio
        prev_wd = annual_withdrawal
        failed = False

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
            # 即使 0% 提取率都达不到此成功率
            results.append(None)
            continue
        if t <= success_rates[-1]:
            # 最高提取率仍能达到此成功率
            results.append(float(rates[-1]))
            continue

        # 找到成功率从 >= t 跌到 < t 的过渡点
        found = False
        for i in range(len(success_rates) - 1):
            if success_rates[i] >= t and success_rates[i + 1] < t:
                # 线性插值
                frac = (t - success_rates[i + 1]) / (success_rates[i] - success_rates[i + 1])
                interp_rate = rates[i + 1] + frac * (rates[i] - rates[i + 1])
                results.append(float(interp_rate))
                found = True
                break
        if not found:
            results.append(None)

    return results
