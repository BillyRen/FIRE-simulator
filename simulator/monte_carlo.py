"""蒙特卡洛模拟引擎。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .bootstrap import block_bootstrap, block_bootstrap_pooled
from .cashflow import CashFlowItem, build_cf_schedule
from .portfolio import compute_real_portfolio_returns


def run_simulation(
    initial_portfolio: float,
    annual_withdrawal: float,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    retirement_years: int,
    min_block: int,
    max_block: int,
    num_simulations: int,
    returns_df: pd.DataFrame,
    seed: int | None = None,
    withdrawal_strategy: str = "fixed",
    dynamic_ceiling: float = 0.05,
    dynamic_floor: float = 0.025,
    cash_flows: list[CashFlowItem] | None = None,
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
    country_dfs: dict[str, pd.DataFrame] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """运行蒙特卡洛退休模拟。

    对每次模拟：
    1. 用 block_bootstrap 生成 retirement_years 年的回报序列
    2. 计算每年的组合实际回报（扣通胀、扣费用）
    3. 逐年模拟提取，根据策略确定提取金额：
       - fixed: 每年固定提取 annual_withdrawal
       - dynamic: Vanguard Dynamic Spending，按初始提取率动态调整，
         受 ceiling/floor 限制
       year_end = year_start * (1 + real_return) - withdrawal + net_cf
       若 value <= 0 则标记失败，后续年份资产为 0

    Parameters
    ----------
    initial_portfolio : float
        初始资产组合金额。
    annual_withdrawal : float
        每年提取的实际金额（今日购买力）。
    allocation : dict
        资产配置比例，如 {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3}。
    expense_ratios : dict
        各资产的费用率，键同 allocation。
    retirement_years : int
        退休年限。
    min_block : int
        Block bootstrap 最小窗口。
    max_block : int
        Block bootstrap 最大窗口。
    num_simulations : int
        模拟次数。
    returns_df : pd.DataFrame
        历史回报数据。
    seed : int or None
        随机种子，用于可复现性。
    withdrawal_strategy : str
        提取策略："fixed"（固定提取）或 "dynamic"（Vanguard 动态提取）。
    dynamic_ceiling : float
        动态提取时每年最大上调比例（如 0.05 表示 5%）。
    dynamic_floor : float
        动态提取时每年最大下调比例（如 0.025 表示 2.5%）。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。每条现金流有起始年、持续年数、金额和是否通胀调整。

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
        (trajectories, withdrawals, real_returns_matrix, inflation_matrix)
        - trajectories: shape (num_simulations, retirement_years + 1) 的资产轨迹矩阵。
          第 0 列为初始值，第 k 列为第 k 年末的资产值。
        - withdrawals: shape (num_simulations, retirement_years) 的提取金额矩阵。
          第 k 列为第 k+1 年的实际提取金额。
        - real_returns_matrix: shape (num_simulations, retirement_years) 的实际组合回报矩阵。
        - inflation_matrix: shape (num_simulations, retirement_years) 的通胀率矩阵。
    """
    rng = np.random.default_rng(seed)

    # 初始提取率（动态策略用）
    initial_rate = annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0.0

    # 资产轨迹矩阵：(num_simulations, retirement_years + 1)
    trajectories = np.zeros((num_simulations, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio

    # 提取金额矩阵：(num_simulations, retirement_years)
    withdrawals = np.zeros((num_simulations, retirement_years))

    # 回报与通胀矩阵（用于绩效指标计算）
    real_returns_matrix = np.zeros((num_simulations, retirement_years))
    inflation_matrix = np.zeros((num_simulations, retirement_years))

    has_cf = cash_flows is not None and len(cash_flows) > 0
    # 预计算通胀调整部分的固定 schedule（仅当有现金流时）
    if has_cf:
        adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
        has_nominal = len(nominal_cfs) > 0
        fixed_cf_schedule = build_cf_schedule(adj_cfs, retirement_years)
    else:
        fixed_cf_schedule = None

    for i in range(num_simulations):
        # 1. 生成 bootstrap 回报序列
        if country_dfs is not None:
            sampled = block_bootstrap_pooled(
                country_dfs, retirement_years, min_block, max_block, rng=rng
            )
        else:
            sampled = block_bootstrap(
                returns_df, retirement_years, min_block, max_block, rng=rng
            )

        # 2. 计算组合实际回报
        real_returns = compute_real_portfolio_returns(
            sampled, allocation, expense_ratios,
            leverage=leverage, borrowing_spread=borrowing_spread,
        )
        real_returns_matrix[i] = real_returns
        inflation_matrix[i] = sampled["Inflation"].values

        # 3. 计算该路径的现金流 schedule
        if has_cf:
            if has_nominal:
                inflation_series = sampled["Inflation"].values
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_series
                )
                cf_schedule = fixed_cf_schedule + nominal_schedule
            else:
                cf_schedule = fixed_cf_schedule
        else:
            cf_schedule = None

        # 4. 逐年模拟
        value = initial_portfolio
        prev_withdrawal = annual_withdrawal

        for year in range(retirement_years):
            # 确定本年提取金额
            if withdrawal_strategy == "dynamic" and year > 0 and value > 0:
                target = value * initial_rate
                upper = prev_withdrawal * (1.0 + dynamic_ceiling)
                lower = prev_withdrawal * (1.0 - dynamic_floor)
                withdrawal = max(lower, min(target, upper))
            else:
                withdrawal = annual_withdrawal

            withdrawals[i, year] = withdrawal
            prev_withdrawal = withdrawal

            value = value * (1.0 + real_returns[year]) - withdrawal

            # 加入自定义现金流
            if cf_schedule is not None:
                value += cf_schedule[year]
                withdrawals[i, year] -= cf_schedule[year]

            if value <= 0:
                value = 0.0
                trajectories[i, year + 1 :] = 0.0
                withdrawals[i, year + 1 :] = 0.0
                break
            trajectories[i, year + 1] = value

    return trajectories, withdrawals, real_returns_matrix, inflation_matrix


def run_simple_historical_backtest(
    real_returns: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    retirement_years: int,
    withdrawal_strategy: str = "fixed",
    dynamic_ceiling: float = 0.05,
    dynamic_floor: float = 0.025,
    cash_flows: list[CashFlowItem] | None = None,
    inflation_series: np.ndarray | None = None,
) -> dict:
    """在单条历史回报路径上运行退休模拟（无 bootstrap）。

    Parameters
    ----------
    real_returns : np.ndarray
        实际（扣通胀）组合回报率序列，长度 >= retirement_years。
    initial_portfolio : float
        初始资产。
    annual_withdrawal : float
        每年提取金额（实际购买力）。
    retirement_years : int
        模拟年数。
    withdrawal_strategy : str
        "fixed" 或 "dynamic"。
    dynamic_ceiling / dynamic_floor : float
        动态提取的上下限比例。
    cash_flows : list[CashFlowItem] or None
        自定义现金流。
    inflation_series : np.ndarray or None
        通胀序列（用于非通胀调整的现金流换算），长度 >= retirement_years。

    Returns
    -------
    dict
        years_simulated, portfolio (list), withdrawals (list), survived (bool).
    """
    n_years = min(retirement_years, len(real_returns))

    initial_rate = annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0.0

    # 现金流 schedule
    has_cf = cash_flows is not None and len(cash_flows) > 0
    if has_cf:
        adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
        fixed_cf_schedule = build_cf_schedule(adj_cfs, n_years)
        if nominal_cfs and inflation_series is not None:
            nominal_schedule = build_cf_schedule(nominal_cfs, n_years, inflation_series[:n_years])
            cf_schedule = fixed_cf_schedule + nominal_schedule
        else:
            cf_schedule = fixed_cf_schedule
    else:
        cf_schedule = None

    portfolio = [initial_portfolio]
    withdrawals_out: list[float] = []
    value = initial_portfolio
    prev_wd = annual_withdrawal
    survived = True

    for year in range(n_years):
        # 确定提取金额
        if withdrawal_strategy == "dynamic" and year > 0 and value > 0:
            target = value * initial_rate
            upper = prev_wd * (1.0 + dynamic_ceiling)
            lower = prev_wd * (1.0 - dynamic_floor)
            wd = max(lower, min(target, upper))
        else:
            wd = annual_withdrawal

        withdrawals_out.append(wd)
        prev_wd = wd

        value = value * (1.0 + real_returns[year]) - wd

        if cf_schedule is not None:
            value += cf_schedule[year]

        if value <= 0:
            value = 0.0
            survived = False
            portfolio.append(0.0)
            # 后续年份补零
            for _ in range(year + 1, n_years):
                portfolio.append(0.0)
                withdrawals_out.append(0.0)
            break
        portfolio.append(value)

    return {
        "years_simulated": n_years,
        "portfolio": portfolio,
        "withdrawals": withdrawals_out,
        "survived": survived,
    }
