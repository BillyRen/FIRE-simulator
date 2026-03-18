"""蒙特卡洛模拟引擎。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .bootstrap import (
    IDX_DB,
    IDX_DS,
    IDX_GS,
    IDX_INF,
    RETURN_COLS,
    block_bootstrap,
    block_bootstrap_np,
    block_bootstrap_pooled,
    block_bootstrap_pooled_np,
    _prepare_pooled_arrays,
)
from .cashflow import CashFlowItem, build_cf_schedule, build_cf_split_schedules, build_expected_cf_schedule, has_probabilistic_cf, sample_cash_flows
from .portfolio import compute_real_portfolio_returns, compute_real_portfolio_returns_np


def compute_withdrawal(
    strategy: str,
    year: int,
    value: float,
    annual_withdrawal: float,
    prev_withdrawal: float,
    initial_rate: float,
    retirement_age: int = 45,
    dynamic_ceiling: float = 0.05,
    dynamic_floor: float = 0.025,
    declining_rate: float = 0.02,
    declining_start_age: int = 65,
    smile_decline_rate: float = 0.01,
    smile_decline_start_age: int = 65,
    smile_min_age: int = 80,
    smile_increase_rate: float = 0.01,
) -> float:
    """根据策略计算当年提取金额。所有模拟路径共用此逻辑。"""
    if strategy == "dynamic" and year > 0 and value > 0:
        target = value * initial_rate
        upper = prev_withdrawal * (1.0 + dynamic_ceiling)
        lower = prev_withdrawal * (1.0 - dynamic_floor)
        return max(lower, min(target, upper))
    elif strategy == "declining" and year > 0 and value > 0:
        if retirement_age + year >= declining_start_age:
            return prev_withdrawal * (1.0 - declining_rate)
        return annual_withdrawal
    elif strategy == "smile" and value > 0:
        age = retirement_age + year
        if age < smile_decline_start_age:
            return annual_withdrawal
        elif age < smile_min_age:
            return annual_withdrawal * (1.0 - smile_decline_rate) ** (age - smile_decline_start_age)
        else:
            min_spending = annual_withdrawal * (1.0 - smile_decline_rate) ** (smile_min_age - smile_decline_start_age)
            return min_spending * (1.0 + smile_increase_rate) ** (age - smile_min_age)
    return annual_withdrawal


def run_simulation_from_matrix(
    real_returns_matrix: np.ndarray,
    inflation_matrix: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    retirement_years: int,
    withdrawal_strategy: str = "fixed",
    dynamic_ceiling: float = 0.05,
    dynamic_floor: float = 0.025,
    retirement_age: int = 45,
    cash_flows: list[CashFlowItem] | None = None,
    declining_rate: float = 0.02,
    declining_start_age: int = 65,
    smile_decline_rate: float = 0.01,
    smile_decline_start_age: int = 65,
    smile_min_age: int = 80,
    smile_increase_rate: float = 0.01,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Run simulation using pre-generated return/inflation matrices (skip bootstrap).

    This enables sharing a single bootstrap across multiple simulation variants
    (different cash flows, withdrawal amounts, etc.), dramatically reducing compute
    time for scenario analysis and sensitivity endpoints.

    Parameters
    ----------
    real_returns_matrix : np.ndarray
        Shape (num_simulations, retirement_years) real portfolio returns.
    inflation_matrix : np.ndarray
        Shape (num_simulations, retirement_years) inflation rates.
    Other parameters same as run_simulation().

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
        (trajectories, withdrawals, real_returns_matrix, inflation_matrix)
    """
    num_simulations = real_returns_matrix.shape[0]
    can_use_vectorized = (
        withdrawal_strategy == "fixed"
        and (cash_flows is None or len(cash_flows) == 0)
    )

    if can_use_vectorized:
        return _simulate_vectorized_fixed_from_matrix(
            real_returns_matrix, initial_portfolio, annual_withdrawal, retirement_years,
        )

    return _simulate_general_from_matrix(
        real_returns_matrix, inflation_matrix,
        initial_portfolio, annual_withdrawal, retirement_years,
        withdrawal_strategy, dynamic_ceiling, dynamic_floor,
        retirement_age, cash_flows,
        declining_rate, declining_start_age,
        smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
    )


def _simulate_vectorized_fixed_from_matrix(
    real_returns_matrix: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    retirement_years: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized fixed-strategy simulation from pre-generated matrices."""
    num_simulations = real_returns_matrix.shape[0]
    trajectories = np.zeros((num_simulations, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.full((num_simulations, retirement_years), float(annual_withdrawal))
    values = np.full(num_simulations, initial_portfolio, dtype=float)
    alive = np.ones(num_simulations, dtype=bool)

    for year in range(retirement_years):
        grown = values[alive] * (1.0 + real_returns_matrix[alive, year])
        actual_wd = np.minimum(annual_withdrawal, np.maximum(grown, 0.0))
        values[alive] = grown - actual_wd
        withdrawals[alive, year] = actual_wd
        newly_failed = alive & (values <= 0)
        values[newly_failed] = 0.0
        alive[newly_failed] = False
        withdrawals[newly_failed, year + 1:] = 0.0
        trajectories[:, year + 1] = values

    # Return a dummy inflation_matrix of zeros to match signature
    return trajectories, withdrawals, real_returns_matrix, np.zeros_like(real_returns_matrix)


def _simulate_general_from_matrix(
    real_returns_matrix: np.ndarray,
    inflation_matrix: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    retirement_years: int,
    withdrawal_strategy: str,
    dynamic_ceiling: float,
    dynamic_floor: float,
    retirement_age: int,
    cash_flows: list[CashFlowItem] | None,
    declining_rate: float,
    declining_start_age: int,
    smile_decline_rate: float,
    smile_decline_start_age: int,
    smile_min_age: int,
    smile_increase_rate: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """General simulation loop from pre-generated matrices (all strategies + cash flows)."""
    num_simulations = real_returns_matrix.shape[0]
    initial_rate = annual_withdrawal / initial_portfolio if initial_portfolio > 0 else 0.0

    trajectories = np.zeros((num_simulations, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.zeros((num_simulations, retirement_years))

    has_cf = cash_flows is not None and len(cash_flows) > 0
    has_groups = has_cf and has_probabilistic_cf(cash_flows)

    if has_cf and not has_groups:
        adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
        has_nominal = len(nominal_cfs) > 0
        fixed_cf_schedule = build_cf_schedule(adj_cfs, retirement_years)
        # Split schedules for expense/income tracking
        fixed_cf_expense, fixed_cf_income = build_cf_split_schedules(
            [cf for cf in cash_flows if cf.inflation_adjusted], retirement_years
        )
    else:
        fixed_cf_schedule = None
        fixed_cf_expense = None
        fixed_cf_income = None
        nominal_cfs = []
        has_nominal = False

    rng = np.random.default_rng() if has_groups else None

    for i in range(num_simulations):
        real_returns = real_returns_matrix[i]

        # Cash flow schedule for this path
        if has_groups:
            active_cfs = sample_cash_flows(cash_flows, rng)
            if active_cfs:
                _adj = [cf for cf in active_cfs if cf.inflation_adjusted]
                _nom = [cf for cf in active_cfs if not cf.inflation_adjusted]
                _adj_sched = build_cf_schedule(_adj, retirement_years) if _adj else np.zeros(retirement_years)
                _adj_exp, _adj_inc = build_cf_split_schedules(_adj, retirement_years) if _adj else (np.zeros(retirement_years), np.zeros(retirement_years))
                if _nom:
                    _nom_sched = build_cf_schedule(_nom, retirement_years, inflation_matrix[i])
                    cf_schedule = _adj_sched + _nom_sched
                    _nom_exp, _nom_inc = build_cf_split_schedules(_nom, retirement_years, inflation_matrix[i])
                    cf_expense = _adj_exp + _nom_exp
                    cf_income = _adj_inc + _nom_inc
                else:
                    cf_schedule = _adj_sched
                    cf_expense = _adj_exp
                    cf_income = _adj_inc
            else:
                cf_schedule = None
                cf_expense = None
                cf_income = None
        elif has_cf:
            if has_nominal:
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                cf_schedule = fixed_cf_schedule + nominal_schedule
                nom_exp, nom_inc = build_cf_split_schedules(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                cf_expense = fixed_cf_expense + nom_exp
                cf_income = fixed_cf_income + nom_inc
            else:
                cf_schedule = fixed_cf_schedule
                cf_expense = fixed_cf_expense
                cf_income = fixed_cf_income
        else:
            cf_schedule = None
            cf_expense = None
            cf_income = None

        value = initial_portfolio
        prev_withdrawal = annual_withdrawal

        for year in range(retirement_years):
            withdrawal = compute_withdrawal(
                withdrawal_strategy, year, value, annual_withdrawal, prev_withdrawal,
                initial_rate, retirement_age, dynamic_ceiling, dynamic_floor,
                declining_rate, declining_start_age,
                smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
            )
            prev_withdrawal = withdrawal
            value_after_growth = value * (1.0 + real_returns[year])
            actual_wd = min(withdrawal, max(value_after_growth, 0.0))
            value = value_after_growth - actual_wd
            withdrawals[i, year] = actual_wd
            # Apply expenses before depletion check
            if cf_expense is not None and cf_expense[year] > 0:
                value -= cf_expense[year]
                withdrawals[i, year] += cf_expense[year]
            if value <= 0:
                value = 0.0
                trajectories[i, year + 1:] = 0.0
                withdrawals[i, year + 1:] = 0.0
                break
            # Apply income after depletion check
            if cf_income is not None and cf_income[year] > 0:
                value += cf_income[year]
            trajectories[i, year + 1] = value

    return trajectories, withdrawals, real_returns_matrix, inflation_matrix


def run_simulation_vectorized_fixed(
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
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
    country_dfs: dict[str, pd.DataFrame] | None = None,
    country_weights: dict[str, float] | None = None,
    glide_path_end_allocation: dict[str, float] | None = None,
    glide_path_years: int = 20,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """向量化的固定提取策略模拟（优化版本）。

    适用场景：
    - withdrawal_strategy = "fixed"
    - 无现金流 (cash_flows=None)
    - 无复杂动态策略

    通过向量化年度更新，消除内层Python循环，实现5-15x加速。

    Parameters同 run_simulation()，但仅支持 fixed 策略。

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
        (trajectories, withdrawals, real_returns_matrix, inflation_matrix)
    """
    rng = np.random.default_rng(seed)

    # Step 1: 预生成所有bootstrap样本和回报矩阵
    real_returns_matrix = np.zeros((num_simulations, retirement_years))
    inflation_matrix = np.zeros((num_simulations, retirement_years))

    # Pre-extract numpy arrays from DataFrames (avoid per-iteration overhead)
    if country_dfs is not None:
        _, c_arrays, c_lens, c_probs = _prepare_pooled_arrays(
            country_dfs, country_weights, RETURN_COLS,
        )
        src_data, src_n = None, 0
    else:
        src_data = returns_df[RETURN_COLS].values
        src_n = len(src_data)
        c_arrays, c_lens, c_probs = None, None, None

    for i in range(num_simulations):
        if c_arrays is not None:
            sampled_np = block_bootstrap_pooled_np(
                c_arrays, c_lens, c_probs,
                retirement_years, min_block, max_block, rng=rng,
            )
        else:
            sampled_np = block_bootstrap_np(
                src_data, src_n, retirement_years, min_block, max_block, rng=rng,
            )

        if glide_path_end_allocation is not None:
            real_returns = _compute_glide_path_returns_np(
                sampled_np, allocation, glide_path_end_allocation,
                glide_path_years, expense_ratios, leverage, borrowing_spread,
            )
        else:
            real_returns = compute_real_portfolio_returns_np(
                sampled_np, allocation, expense_ratios,
                leverage=leverage, borrowing_spread=borrowing_spread,
            )

        real_returns_matrix[i] = real_returns
        inflation_matrix[i] = sampled_np[:, IDX_INF]

    # Step 2: 向量化模拟所有路径
    # 资产轨迹：(num_simulations, retirement_years + 1)
    trajectories = np.zeros((num_simulations, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio

    # 提取金额：fixed策略，所有年份都是相同的金额
    withdrawals = np.full((num_simulations, retirement_years), float(annual_withdrawal))

    # 当前存活的资产值（向量）
    values = np.full(num_simulations, initial_portfolio, dtype=float)
    alive = np.ones(num_simulations, dtype=bool)  # 存活标记

    # Step 3: 外层循环year，内层向量化所有simulations
    for year in range(retirement_years):
        # 计算增长后的值
        grown = values[alive] * (1.0 + real_returns_matrix[alive, year])
        # Cap withdrawal at available portfolio value
        actual_wd = np.minimum(annual_withdrawal, np.maximum(grown, 0.0))
        values[alive] = grown - actual_wd
        withdrawals[alive, year] = actual_wd

        # 检查破产
        newly_failed = alive & (values <= 0)
        values[newly_failed] = 0.0
        alive[newly_failed] = False

        # 破产的simulation后续提取为0
        withdrawals[newly_failed, year + 1:] = 0.0

        # 记录轨迹
        trajectories[:, year + 1] = values

    return trajectories, withdrawals, real_returns_matrix, inflation_matrix


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
    retirement_age: int = 45,
    cash_flows: list[CashFlowItem] | None = None,
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
    country_dfs: dict[str, pd.DataFrame] | None = None,
    country_weights: dict[str, float] | None = None,
    declining_rate: float = 0.02,
    declining_start_age: int = 65,
    smile_decline_rate: float = 0.01,
    smile_decline_start_age: int = 65,
    smile_min_age: int = 80,
    smile_increase_rate: float = 0.01,
    glide_path_end_allocation: dict[str, float] | None = None,
    glide_path_years: int = 20,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """运行蒙特卡洛退休模拟。

    对每次模拟：
    1. 用 block_bootstrap 生成 retirement_years 年的回报序列
    2. 计算每年的组合实际回报（扣通胀、扣费用）
    3. 逐年模拟提取，根据策略确定提取金额：
       - fixed: 每年固定提取 annual_withdrawal
       - dynamic: Vanguard Dynamic Spending，按初始提取率动态调整，
         受 ceiling/floor 限制
       - declining: EBRI 消费递减，65 岁后每年实际支出下降 2%
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
    # Phase 2.1优化：自动检测并使用向量化版本（适用于fixed策略+无现金流场景）
    can_use_vectorized = (
        withdrawal_strategy == "fixed"
        and (cash_flows is None or len(cash_flows) == 0)
    )

    if can_use_vectorized:
        return run_simulation_vectorized_fixed(
            initial_portfolio=initial_portfolio,
            annual_withdrawal=annual_withdrawal,
            allocation=allocation,
            expense_ratios=expense_ratios,
            retirement_years=retirement_years,
            min_block=min_block,
            max_block=max_block,
            num_simulations=num_simulations,
            returns_df=returns_df,
            seed=seed,
            leverage=leverage,
            borrowing_spread=borrowing_spread,
            country_dfs=country_dfs,
            country_weights=country_weights,
            glide_path_end_allocation=glide_path_end_allocation,
            glide_path_years=glide_path_years,
        )

    # 回退到通用实现（支持所有策略和现金流）
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
    has_groups = has_cf and has_probabilistic_cf(cash_flows)

    # 预计算通胀调整部分的固定 schedule（仅当无概率分组时可复用）
    if has_cf and not has_groups:
        adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
        has_nominal = len(nominal_cfs) > 0
        fixed_cf_schedule = build_cf_schedule(adj_cfs, retirement_years)
        # Split schedules for expense/income tracking
        fixed_cf_expense, fixed_cf_income = build_cf_split_schedules(
            [cf for cf in cash_flows if cf.inflation_adjusted], retirement_years
        )
    else:
        fixed_cf_schedule = None
        fixed_cf_expense = None
        fixed_cf_income = None
        nominal_cfs = []
        has_nominal = False

    # Pre-extract numpy arrays from DataFrames (avoid per-iteration overhead)
    if country_dfs is not None:
        _, c_arrays, c_lens, c_probs = _prepare_pooled_arrays(
            country_dfs, country_weights, RETURN_COLS,
        )
        src_data, src_n = None, 0
    else:
        src_data = returns_df[RETURN_COLS].values
        src_n = len(src_data)
        c_arrays, c_lens, c_probs = None, None, None

    for i in range(num_simulations):
        # 1. 生成 bootstrap 回报序列 (numpy, no DataFrame)
        if c_arrays is not None:
            sampled_np = block_bootstrap_pooled_np(
                c_arrays, c_lens, c_probs,
                retirement_years, min_block, max_block, rng=rng,
            )
        else:
            sampled_np = block_bootstrap_np(
                src_data, src_n, retirement_years, min_block, max_block, rng=rng,
            )

        # 2. 计算组合实际回报
        if glide_path_end_allocation is not None:
            real_returns = _compute_glide_path_returns_np(
                sampled_np, allocation, glide_path_end_allocation,
                glide_path_years, expense_ratios, leverage, borrowing_spread,
            )
        else:
            real_returns = compute_real_portfolio_returns_np(
                sampled_np, allocation, expense_ratios,
                leverage=leverage, borrowing_spread=borrowing_spread,
            )
        real_returns_matrix[i] = real_returns
        inflation_series = sampled_np[:, IDX_INF]
        inflation_matrix[i] = inflation_series

        # 3. 计算该路径的现金流 schedule
        if has_groups:
            active_cfs = sample_cash_flows(cash_flows, rng)
            if active_cfs:
                _adj = [cf for cf in active_cfs if cf.inflation_adjusted]
                _nom = [cf for cf in active_cfs if not cf.inflation_adjusted]
                _adj_sched = build_cf_schedule(_adj, retirement_years) if _adj else np.zeros(retirement_years)
                _adj_exp, _adj_inc = build_cf_split_schedules(_adj, retirement_years) if _adj else (np.zeros(retirement_years), np.zeros(retirement_years))
                if _nom:
                    _nom_sched = build_cf_schedule(_nom, retirement_years, inflation_series)
                    cf_schedule = _adj_sched + _nom_sched
                    _nom_exp, _nom_inc = build_cf_split_schedules(_nom, retirement_years, inflation_series)
                    cf_expense = _adj_exp + _nom_exp
                    cf_income = _adj_inc + _nom_inc
                else:
                    cf_schedule = _adj_sched
                    cf_expense = _adj_exp
                    cf_income = _adj_inc
            else:
                cf_schedule = None
                cf_expense = None
                cf_income = None
        elif has_cf:
            if has_nominal:
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_series
                )
                cf_schedule = fixed_cf_schedule + nominal_schedule
                nom_exp, nom_inc = build_cf_split_schedules(
                    nominal_cfs, retirement_years, inflation_series
                )
                cf_expense = fixed_cf_expense + nom_exp
                cf_income = fixed_cf_income + nom_inc
            else:
                cf_schedule = fixed_cf_schedule
                cf_expense = fixed_cf_expense
                cf_income = fixed_cf_income
        else:
            cf_schedule = None
            cf_expense = None
            cf_income = None

        # 4. 逐年模拟
        value = initial_portfolio
        prev_withdrawal = annual_withdrawal

        for year in range(retirement_years):
            withdrawal = compute_withdrawal(
                withdrawal_strategy, year, value, annual_withdrawal, prev_withdrawal,
                initial_rate, retirement_age, dynamic_ceiling, dynamic_floor,
                declining_rate, declining_start_age,
                smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
            )

            prev_withdrawal = withdrawal

            value_after_growth = value * (1.0 + real_returns[year])
            # Cap withdrawal at available portfolio value
            actual_wd = min(withdrawal, max(value_after_growth, 0.0))
            value = value_after_growth - actual_wd

            withdrawals[i, year] = actual_wd

            # Apply expenses before depletion check
            if cf_expense is not None and cf_expense[year] > 0:
                value -= cf_expense[year]
                withdrawals[i, year] += cf_expense[year]

            if value <= 0:
                value = 0.0
                trajectories[i, year + 1 :] = 0.0
                withdrawals[i, year + 1 :] = 0.0
                break

            # Apply income after depletion check
            if cf_income is not None and cf_income[year] > 0:
                value += cf_income[year]
            trajectories[i, year + 1] = value

    return trajectories, withdrawals, real_returns_matrix, inflation_matrix


def _compute_glide_path_returns_np(
    data: np.ndarray,
    start_alloc: dict[str, float],
    end_alloc: dict[str, float],
    glide_years: int,
    expense_ratios: dict[str, float],
    leverage: float,
    borrowing_spread: float,
) -> np.ndarray:
    """Per-year portfolio returns with linearly interpolated allocation (numpy input).

    Parameters
    ----------
    data : np.ndarray
        shape (n, 4+) with columns in RETURN_COLS order.
    """
    n = len(data)
    asset_keys = ["domestic_stock", "global_stock", "domestic_bond"]
    col_indices = [IDX_DS, IDX_GS, IDX_DB]

    years = np.arange(n)
    t_values = np.minimum(years / max(glide_years, 1), 1.0)

    weights = np.zeros((n, 3))
    for i, key in enumerate(asset_keys):
        w_start = start_alloc.get(key, 0.0)
        w_end = end_alloc.get(key, 0.0)
        weights[:, i] = w_start * (1.0 - t_values) + w_end * t_values

    returns_matrix = data[:, col_indices]
    expense_array = np.array([expense_ratios.get(key, 0.0) for key in asset_keys])

    nominal_returns = np.sum(weights * (returns_matrix - expense_array), axis=1)

    inflation = data[:, IDX_INF]
    if leverage != 1.0:
        nominal_returns = leverage * nominal_returns - (leverage - 1.0) * (inflation + borrowing_spread)

    return (1.0 + nominal_returns) / (1.0 + inflation) - 1.0


def _compute_glide_path_returns(
    sampled: pd.DataFrame,
    start_alloc: dict[str, float],
    end_alloc: dict[str, float],
    glide_years: int,
    expense_ratios: dict[str, float],
    leverage: float,
    borrowing_spread: float,
) -> np.ndarray:
    """Per-year portfolio returns with linearly interpolated allocation (DataFrame input)."""
    from .bootstrap import RETURN_COLS as _RC
    return _compute_glide_path_returns_np(
        sampled[_RC].values, start_alloc, end_alloc,
        glide_years, expense_ratios, leverage, borrowing_spread,
    )


def run_simple_historical_backtest(
    real_returns: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    retirement_years: int,
    withdrawal_strategy: str = "fixed",
    dynamic_ceiling: float = 0.05,
    dynamic_floor: float = 0.025,
    retirement_age: int = 45,
    cash_flows: list[CashFlowItem] | None = None,
    inflation_series: np.ndarray | None = None,
    declining_rate: float = 0.02,
    declining_start_age: int = 65,
    smile_decline_rate: float = 0.01,
    smile_decline_start_age: int = 65,
    smile_min_age: int = 80,
    smile_increase_rate: float = 0.01,
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
        "fixed"、"dynamic" 或 "declining"。
    dynamic_ceiling / dynamic_floor : float
        动态提取的上下限比例。
    retirement_age : int
        退休年龄（declining 策略在 65 岁后每年实际支出下降 2%）。
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
        if has_probabilistic_cf(cash_flows):
            cf_schedule = build_expected_cf_schedule(
                cash_flows, n_years, inflation_series[:n_years] if inflation_series is not None else None
            )
            # For probabilistic CFs, split the expected schedule by sign
            cf_expense = np.maximum(-cf_schedule, 0.0)
            cf_income = np.maximum(cf_schedule, 0.0)
        else:
            adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
            nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
            fixed_cf_schedule = build_cf_schedule(adj_cfs, n_years)
            fixed_exp, fixed_inc = build_cf_split_schedules(
                [cf for cf in cash_flows if cf.inflation_adjusted], n_years
            )
            if nominal_cfs and inflation_series is not None:
                nominal_schedule = build_cf_schedule(nominal_cfs, n_years, inflation_series[:n_years])
                cf_schedule = fixed_cf_schedule + nominal_schedule
                nom_exp, nom_inc = build_cf_split_schedules(
                    nominal_cfs, n_years, inflation_series[:n_years]
                )
                cf_expense = fixed_exp + nom_exp
                cf_income = fixed_inc + nom_inc
            else:
                cf_schedule = fixed_cf_schedule
                cf_expense = fixed_exp
                cf_income = fixed_inc
    else:
        cf_schedule = None
        cf_expense = None
        cf_income = None

    portfolio = [initial_portfolio]
    withdrawals_out: list[float] = []
    value = initial_portfolio
    prev_wd = annual_withdrawal
    survived = True

    for year in range(n_years):
        wd = compute_withdrawal(
            withdrawal_strategy, year, value, annual_withdrawal, prev_wd,
            initial_rate, retirement_age, dynamic_ceiling, dynamic_floor,
            declining_rate, declining_start_age,
            smile_decline_rate, smile_decline_start_age, smile_min_age, smile_increase_rate,
        )

        prev_wd = wd

        value_after_growth = value * (1.0 + real_returns[year])
        actual_wd = min(wd, max(value_after_growth, 0.0))
        value = value_after_growth - actual_wd
        withdrawals_out.append(actual_wd)

        # Apply expenses before depletion check
        if cf_expense is not None and cf_expense[year] > 0:
            value -= cf_expense[year]
            withdrawals_out[-1] += cf_expense[year]

        if value <= 0:
            value = 0.0
            # Last-year depletion = survived (aligned with compute_success_rate)
            survived = (year == n_years - 1)
            portfolio.append(0.0)
            # 后续年份补零
            for _ in range(year + 1, n_years):
                portfolio.append(0.0)
                withdrawals_out.append(0.0)
            break

        # Apply income after depletion check
        if cf_income is not None and cf_income[year] > 0:
            value += cf_income[year]
        portfolio.append(value)

    return {
        "years_simulated": n_years,
        "portfolio": portfolio,
        "withdrawals": withdrawals_out,
        "survived": survived,
    }


def batch_backtest_fixed_vectorized(
    real_returns_2d: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized batch backtest for fixed withdrawal strategy with no cash flows.

    Parameters
    ----------
    real_returns_2d : np.ndarray, shape (num_paths, max_years)
        Real portfolio returns for each path. Paths shorter than max_years
        should be NaN-padded (handled by caller via masking).
    initial_portfolio : float
        Starting portfolio value.
    annual_withdrawal : float
        Fixed annual withdrawal (real dollars).

    Returns
    -------
    portfolios : np.ndarray, shape (num_paths, max_years + 1)
        Portfolio value trajectories (year 0 = initial).
    withdrawals : np.ndarray, shape (num_paths, max_years)
        Actual withdrawal each year.
    survived : np.ndarray, shape (num_paths,)
        True if portfolio > 0 at end.
    """
    num_paths, max_years = real_returns_2d.shape
    portfolios = np.zeros((num_paths, max_years + 1))
    portfolios[:, 0] = initial_portfolio
    wd_out = np.zeros((num_paths, max_years))

    # Track which paths are still alive
    alive = np.ones(num_paths, dtype=bool)

    for yr in range(max_years):
        vals = portfolios[:, yr]
        after_growth = vals * (1.0 + real_returns_2d[:, yr])
        # For alive paths: withdraw min(annual_withdrawal, max(after_growth, 0))
        actual_wd = np.where(
            alive,
            np.minimum(annual_withdrawal, np.maximum(after_growth, 0.0)),
            0.0,
        )
        new_val = np.where(alive, after_growth - actual_wd, 0.0)
        # Mark as dead if value <= 0
        just_died = alive & (new_val <= 0)
        new_val[just_died] = 0.0
        alive[just_died] = False
        portfolios[:, yr + 1] = new_val
        wd_out[:, yr] = actual_wd

    survived = alive
    return portfolios, wd_out, survived
