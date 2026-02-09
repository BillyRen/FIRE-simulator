"""Risk-based Guardrail 策略引擎。

核心思路：预构建 2D 成功率查找表 success_rate(withdrawal_rate, remaining_years)，
使模拟中每年的成功率查询变为 O(1) 插值操作，避免嵌套模拟。
"""

from __future__ import annotations

import numpy as np

from simulator.cashflow import CashFlowItem, build_cf_schedule
from simulator.config import GUARDRAIL_RATE_MIN, GUARDRAIL_RATE_MAX, GUARDRAIL_RATE_STEP


# ---------------------------------------------------------------------------
# 1. 查找表构建（不含现金流 — 查找表基于比例归一化，无法纳入绝对金额）
# ---------------------------------------------------------------------------

def build_success_rate_table(
    scenarios: np.ndarray,
    rate_min: float = GUARDRAIL_RATE_MIN,
    rate_max: float = GUARDRAIL_RATE_MAX,
    rate_step: float = GUARDRAIL_RATE_STEP,
) -> tuple[np.ndarray, np.ndarray]:
    """构建 2D 成功率查找表。

    对于固定提取策略，成功率只取决于 (提取率, 剩余年限)，与资产绝对值无关。
    将资产归一化为 v=1，每年 v_{t+1} = v_t * (1+r_t) - rate。

    Parameters
    ----------
    scenarios : np.ndarray
        shape (num_sims, max_years) 的实际组合回报率矩阵。
    rate_min, rate_max, rate_step : float
        提取率网格范围。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (rate_grid, table)
        - rate_grid: shape (num_rates,) 的提取率数组
        - table: shape (num_rates, max_years + 1) 的成功率表。
          table[i, y] = 以 rate_grid[i] 提取 y 年后仍存活的概率。
          table[:, 0] = 1.0（0 年提取，100% 成功）。
    """
    num_sims, max_years = scenarios.shape
    rate_grid = np.arange(rate_min, rate_max + rate_step / 2, rate_step)
    num_rates = len(rate_grid)

    table = np.zeros((num_rates, max_years + 1))
    table[:, 0] = 1.0

    for rate_idx in range(num_rates):
        rate = rate_grid[rate_idx]
        values = np.ones(num_sims)
        for year in range(max_years):
            values = values * (1.0 + scenarios[:, year]) - rate
            alive = values > 0
            values = np.where(alive, values, 0.0)
            table[rate_idx, year + 1] = np.mean(alive)

    return rate_grid, table


# ---------------------------------------------------------------------------
# 2. 查找表查询（双线性插值）
# ---------------------------------------------------------------------------

def lookup_success_rate(
    table: np.ndarray,
    rate_grid: np.ndarray,
    rate: float,
    remaining_years: int,
) -> float:
    """从查找表中插值查询成功率。

    对 rate 维度做线性插值，remaining_years 取整数索引。
    """
    max_years = table.shape[1] - 1
    remaining_years = min(remaining_years, max_years)
    remaining_years = max(remaining_years, 0)

    if rate <= rate_grid[0]:
        return float(table[0, remaining_years])
    if rate >= rate_grid[-1]:
        return float(table[-1, remaining_years])

    idx = np.searchsorted(rate_grid, rate) - 1
    idx = max(0, min(idx, len(rate_grid) - 2))
    frac = (rate - rate_grid[idx]) / (rate_grid[idx + 1] - rate_grid[idx])

    val_low = table[idx, remaining_years]
    val_high = table[idx + 1, remaining_years]
    return float(val_low + frac * (val_high - val_low))


# ---------------------------------------------------------------------------
# 3. 反向查找：给定目标成功率和剩余年限，找到对应的提取率
# ---------------------------------------------------------------------------

def find_rate_for_target(
    table: np.ndarray,
    rate_grid: np.ndarray,
    target_success: float,
    remaining_years: int,
) -> float:
    """反向查找：给定目标成功率和剩余年限，找到对应的提取率。"""
    max_years = table.shape[1] - 1
    remaining_years = min(remaining_years, max_years)
    remaining_years = max(remaining_years, 1)

    col = table[:, remaining_years]

    if col[0] < target_success:
        return 0.0
    if col[-1] >= target_success:
        return float(rate_grid[-1])

    for i in range(len(col) - 1):
        if col[i] >= target_success and col[i + 1] < target_success:
            frac = (target_success - col[i + 1]) / (col[i] - col[i + 1])
            return float(rate_grid[i + 1] + frac * (rate_grid[i] - rate_grid[i + 1]))

    return float(rate_grid[0])


# ---------------------------------------------------------------------------
# 4. 护栏调整辅助函数
# ---------------------------------------------------------------------------

def _apply_guardrail_adjustment(
    wd: float,
    value: float,
    current_success: float,
    target_success: float,
    adjustment_pct: float,
    adjustment_mode: str,
    remaining: int,
    table: np.ndarray,
    rate_grid: np.ndarray,
    future_cf_avg: float = 0.0,
) -> float:
    """根据调整模式计算护栏触发后的新提取金额。

    Parameters
    ----------
    future_cf_avg : float
        未来现金流年均值（负值=支出，正值=收入）。
        查找表中的 rate 代表"总等效提取率"，包含现金流的影响。
        target_wd 需要减去现金流部分，还原为基础提取额。
    """
    if adjustment_mode == "success_rate":
        adjusted_success = current_success + adjustment_pct * (
            target_success - current_success
        )
        adjusted_rate = find_rate_for_target(
            table, rate_grid, adjusted_success, remaining
        )
        # rate 是总等效提取率，还原为基础提取额：wd = value * rate + cf_avg
        return value * adjusted_rate + future_cf_avg
    else:
        # 默认 "amount" 模式
        target_rate = find_rate_for_target(
            table, rate_grid, target_success, remaining
        )
        # rate 是总等效提取率，还原为基础提取额：target_wd = value * rate + cf_avg
        target_wd = value * target_rate + future_cf_avg
        return wd + adjustment_pct * (target_wd - wd)


# ---------------------------------------------------------------------------
# 5. 向量化二分法：精确查找含现金流的初始资产
# ---------------------------------------------------------------------------

def _find_portfolio_for_success(
    scenarios: np.ndarray,
    annual_withdrawal: float,
    target_success: float,
    retirement_years: int,
    cf_matrix: np.ndarray | None,
    initial_guess: float,
    max_iter: int = 25,
    tol: float = 0.005,
) -> float:
    """用向量化二分法找到使固定提取+现金流达到目标成功率的初始资产。

    Parameters
    ----------
    scenarios : np.ndarray
        shape (num_sims, max_years) 的回报矩阵。
    annual_withdrawal : float
        每年基础提取额。
    target_success : float
        目标成功率 (0-1)。
    retirement_years : int
        退休年限。
    cf_matrix : np.ndarray or None
        shape (num_sims, retirement_years) 或 (retirement_years,) 的现金流矩阵。
        None 表示无现金流。
    initial_guess : float
        初始资产的初始猜测值（用简单平均法得到的估计）。
    max_iter : int
        最大迭代次数。
    tol : float
        成功率容差，|actual - target| < tol 即停止。

    Returns
    -------
    float
        使成功率达到 target_success 的初始资产额。
    """
    num_sims = scenarios.shape[0]
    n_years = min(retirement_years, scenarios.shape[1])

    # 预处理现金流为 2D 方便向量化
    if cf_matrix is not None:
        if cf_matrix.ndim == 1:
            cf_2d = np.broadcast_to(cf_matrix[:n_years], (num_sims, n_years))
        else:
            cf_2d = cf_matrix[:, :n_years]
    else:
        cf_2d = None

    def _success_rate(portfolio: float) -> float:
        values = np.full(num_sims, portfolio)
        for year in range(n_years):
            values = values * (1.0 + scenarios[:, year]) - annual_withdrawal
            if cf_2d is not None:
                values += cf_2d[:, year]
            values = np.maximum(values, 0.0)
        return float(np.mean(values > 0))

    # 设定搜索区间
    lo = initial_guess * 0.3
    hi = initial_guess * 3.0

    # 确保区间有效
    if _success_rate(hi) < target_success:
        hi *= 3.0
    if _success_rate(lo) > target_success:
        lo *= 0.3

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        sr = _success_rate(mid)
        if abs(sr - target_success) < tol:
            return mid
        if sr < target_success:
            lo = mid  # 资产不够，需要更多
        else:
            hi = mid  # 资产过多，可以减少

    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# 6. Guardrail 模拟
# ---------------------------------------------------------------------------

def run_guardrail_simulation(
    scenarios: np.ndarray,
    annual_withdrawal: float,
    target_success: float,
    upper_guardrail: float,
    lower_guardrail: float,
    adjustment_pct: float,
    retirement_years: int,
    min_remaining_years: int,
    table: np.ndarray,
    rate_grid: np.ndarray,
    adjustment_mode: str = "amount",
    cash_flows: list[CashFlowItem] | None = None,
    inflation_matrix: np.ndarray | None = None,
) -> tuple[float, np.ndarray, np.ndarray]:
    """运行 Risk-based Guardrail 模拟。

    Parameters
    ----------
    scenarios : np.ndarray
        shape (num_sims, max_years) 的回报矩阵。
    annual_withdrawal : float
        初始年提取金额（实际购买力）。
    target_success : float
        目标成功率 (0-1)。
    upper_guardrail, lower_guardrail : float
        上下护栏。
    adjustment_pct : float
        调整百分比 (0-1)。
    retirement_years : int
        退休年限。
    min_remaining_years : int
        计算成功率时的最小剩余年限。
    table, rate_grid : np.ndarray
        成功率查找表及网格。
    adjustment_mode : str
        "amount" or "success_rate"。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_matrix : np.ndarray or None
        shape (num_sims, retirement_years) 的通胀率矩阵。

    Returns
    -------
    tuple[float, np.ndarray, np.ndarray]
        (initial_portfolio, trajectories, withdrawals)
    """
    num_sims = scenarios.shape[0]

    # 1. 预计算现金流 schedule
    has_cf = cash_flows is not None and len(cash_flows) > 0

    if has_cf:
        adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
        has_nominal = len(nominal_cfs) > 0
        fixed_cf_schedule = build_cf_schedule(adj_cfs, retirement_years)

        # 预计算完整的 cf_matrix (num_sims, retirement_years) 用于二分法和主循环
        if has_nominal and inflation_matrix is not None:
            cf_matrix = np.zeros((num_sims, retirement_years))
            for i in range(num_sims):
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                cf_matrix[i] = fixed_cf_schedule + nominal_schedule
        else:
            cf_matrix = np.tile(fixed_cf_schedule, (num_sims, 1))
    else:
        fixed_cf_schedule = None
        cf_matrix = None

    # 2. 计算初始资产
    initial_rate = find_rate_for_target(table, rate_grid, target_success, retirement_years)
    if initial_rate <= 0:
        initial_rate = rate_grid[1] if len(rate_grid) > 1 else 0.01

    if has_cf:
        # 用简单平均作为初始猜测，然后用向量化二分法精确求解
        init_cf_avg = float(np.mean(fixed_cf_schedule)) if len(fixed_cf_schedule) > 0 else 0.0
        effective_wd = annual_withdrawal - init_cf_avg
        initial_guess = max(effective_wd, annual_withdrawal * 0.1) / initial_rate

        initial_portfolio = _find_portfolio_for_success(
            scenarios, annual_withdrawal, target_success, retirement_years,
            cf_matrix, initial_guess,
        )
    else:
        initial_portfolio = annual_withdrawal / initial_rate

    # 3. 逐年模拟
    trajectories = np.zeros((num_sims, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.zeros((num_sims, retirement_years))

    for i in range(num_sims):
        value = initial_portfolio
        wd = annual_withdrawal

        # 使用预计算的现金流 schedule
        cf_schedule = cf_matrix[i] if cf_matrix is not None else None

        for year in range(retirement_years):
            remaining = max(min_remaining_years, retirement_years - year)

            if value > 0:
                # 将未来现金流折算为等效提取率
                if cf_schedule is not None:
                    actual_remaining = retirement_years - year
                    future_slice = cf_schedule[year:year + actual_remaining]
                    future_cf_avg = float(np.mean(future_slice)) if len(future_slice) > 0 else 0.0
                    effective_rate = max((wd - future_cf_avg) / value, 0.0)
                else:
                    effective_rate = wd / value

                current_rate = effective_rate
                current_success = lookup_success_rate(
                    table, rate_grid, current_rate, remaining
                )

                if current_success < lower_guardrail or current_success > upper_guardrail:
                    _cf_avg = future_cf_avg if cf_schedule is not None else 0.0
                    wd = _apply_guardrail_adjustment(
                        wd, value, current_success, target_success,
                        adjustment_pct, adjustment_mode, remaining,
                        table, rate_grid,
                        future_cf_avg=_cf_avg,
                    )

            withdrawals[i, year] = wd
            value = value * (1.0 + scenarios[i, year]) - wd

            # 加入自定义现金流
            if cf_schedule is not None:
                value += cf_schedule[year]
                withdrawals[i, year] -= cf_schedule[year]

            if value <= 0:
                value = 0.0
                trajectories[i, year + 1:] = 0.0
                withdrawals[i, year + 1:] = 0.0
                break

            trajectories[i, year + 1] = value

    return initial_portfolio, trajectories, withdrawals


def run_fixed_baseline(
    scenarios: np.ndarray,
    initial_portfolio: float,
    baseline_rate: float,
    retirement_years: int,
    cash_flows: list[CashFlowItem] | None = None,
    inflation_matrix: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """运行固定提取率基准模拟。

    Parameters
    ----------
    scenarios : np.ndarray
        回报矩阵。
    initial_portfolio : float
        初始资产。
    baseline_rate : float
        固定提取率。
    retirement_years : int
        退休年限。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_matrix : np.ndarray or None
        通胀率矩阵。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (trajectories, withdrawals)
    """
    num_sims = scenarios.shape[0]
    annual_wd = initial_portfolio * baseline_rate

    # 预计算现金流
    has_cf = cash_flows is not None and len(cash_flows) > 0
    if has_cf:
        adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
        has_nominal = len(nominal_cfs) > 0
        fixed_cf_schedule = build_cf_schedule(adj_cfs, retirement_years)
    else:
        fixed_cf_schedule = None

    trajectories = np.zeros((num_sims, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.zeros((num_sims, retirement_years))

    for i in range(num_sims):
        value = initial_portfolio

        # 计算该路径的现金流
        if has_cf:
            if has_nominal and inflation_matrix is not None:
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                cf_schedule = fixed_cf_schedule + nominal_schedule
            else:
                cf_schedule = fixed_cf_schedule
        else:
            cf_schedule = None

        for year in range(retirement_years):
            withdrawals[i, year] = annual_wd
            value = value * (1.0 + scenarios[i, year]) - annual_wd

            # 加入自定义现金流
            if cf_schedule is not None:
                value += cf_schedule[year]
                withdrawals[i, year] -= cf_schedule[year]

            if value <= 0:
                value = 0.0
                trajectories[i, year + 1:] = 0.0
                withdrawals[i, year + 1:] = 0.0
                break
            trajectories[i, year + 1] = value

    return trajectories, withdrawals


# ---------------------------------------------------------------------------
# 6. 历史回测（单条真实路径）
# ---------------------------------------------------------------------------

def run_historical_backtest(
    real_returns: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    target_success: float,
    upper_guardrail: float,
    lower_guardrail: float,
    adjustment_pct: float,
    retirement_years: int,
    min_remaining_years: int,
    baseline_rate: float,
    table: np.ndarray,
    rate_grid: np.ndarray,
    adjustment_mode: str = "amount",
    cash_flows: list[CashFlowItem] | None = None,
    inflation_series: np.ndarray | None = None,
) -> dict:
    """在单条历史回报路径上运行 guardrail 策略和固定基准策略。

    Parameters
    ----------
    real_returns : np.ndarray
        1D 数组，从起始年开始的实际组合回报序列。
    initial_portfolio : float
        初始资产。
    annual_withdrawal : float
        初始年提取金额。
    target_success : float
        目标成功率。
    upper_guardrail, lower_guardrail : float
        上下护栏。
    adjustment_pct : float
        调整百分比。
    retirement_years : int
        退休年限，会被截断到 len(real_returns)。
    min_remaining_years : int
        成功率计算的最小剩余年限。
    baseline_rate : float
        基准固定提取率。
    table, rate_grid : np.ndarray
        成功率查找表及网格。
    adjustment_mode : str
        "amount" or "success_rate"。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_series : np.ndarray or None
        1D 真实历史通胀率序列（与 real_returns 等长）。
        仅在存在非通胀调整现金流时需要。

    Returns
    -------
    dict
        包含 g_portfolio, g_withdrawals, g_success_rates, b_portfolio,
        b_withdrawals, g_total_consumption, b_total_consumption 等。
    """
    n_available = len(real_returns)
    n_years = min(retirement_years, n_available)

    # 计算现金流 schedule（历史回测只有一条路径）
    has_cf = cash_flows is not None and len(cash_flows) > 0
    if has_cf:
        if any(not cf.inflation_adjusted for cf in cash_flows):
            if inflation_series is None:
                raise ValueError(
                    "历史回测中存在非通胀调整现金流，但未提供 inflation_series"
                )
            cf_schedule = build_cf_schedule(
                cash_flows, n_years, inflation_series[:n_years]
            )
        else:
            cf_schedule = build_cf_schedule(cash_flows, n_years)
    else:
        cf_schedule = None

    # Guardrail 策略
    g_portfolio = np.zeros(n_years + 1)
    g_portfolio[0] = initial_portfolio
    g_withdrawals = np.zeros(n_years)
    g_success_rates = np.zeros(n_years)
    adjustment_events: list[dict] = []

    value = initial_portfolio
    wd = annual_withdrawal

    for year in range(n_years):
        remaining = max(min_remaining_years, retirement_years - year)

        if value > 0:
            # 将未来现金流折算为等效提取率
            if cf_schedule is not None:
                actual_remaining = retirement_years - year
                future_slice = cf_schedule[year:year + actual_remaining]
                future_cf_avg = float(np.mean(future_slice)) if len(future_slice) > 0 else 0.0
                effective_rate = max((wd - future_cf_avg) / value, 0.0)
            else:
                effective_rate = wd / value

            current_rate = effective_rate
            current_success = lookup_success_rate(
                table, rate_grid, current_rate, remaining
            )
            g_success_rates[year] = current_success

            if current_success < lower_guardrail or current_success > upper_guardrail:
                old_wd = wd
                _cf_avg = future_cf_avg if cf_schedule is not None else 0.0
                wd = _apply_guardrail_adjustment(
                    wd, value, current_success, target_success,
                    adjustment_pct, adjustment_mode, remaining,
                    table, rate_grid,
                    future_cf_avg=_cf_avg,
                )
                # 计算调整后的成功率
                if cf_schedule is not None:
                    new_effective_rate = max((wd - future_cf_avg) / value, 0.0)
                else:
                    new_effective_rate = wd / value
                new_success = lookup_success_rate(
                    table, rate_grid, new_effective_rate, remaining
                )
                adjustment_events.append({
                    "year": year,
                    "old_wd": float(old_wd),
                    "new_wd": float(wd),
                    "success_before": float(current_success),
                    "success_after": float(new_success),
                })
        else:
            g_success_rates[year] = 0.0

        g_withdrawals[year] = wd
        value = value * (1.0 + real_returns[year]) - wd

        # 加入自定义现金流
        if cf_schedule is not None:
            value += cf_schedule[year]
            g_withdrawals[year] -= cf_schedule[year]

        if value <= 0:
            value = 0.0
        g_portfolio[year + 1] = value

    # 基准固定策略
    baseline_wd = initial_portfolio * baseline_rate
    b_portfolio = np.zeros(n_years + 1)
    b_portfolio[0] = initial_portfolio
    b_withdrawals = np.zeros(n_years)

    value = initial_portfolio
    for year in range(n_years):
        b_withdrawals[year] = baseline_wd if value > 0 else 0.0
        if value > 0:
            value = value * (1.0 + real_returns[year]) - baseline_wd

            # 基准策略也加入自定义现金流
            if cf_schedule is not None:
                value += cf_schedule[year]
                b_withdrawals[year] -= cf_schedule[year]

            if value <= 0:
                value = 0.0
        b_portfolio[year + 1] = value

    return {
        "years_simulated": n_years,
        "g_portfolio": g_portfolio,
        "g_withdrawals": g_withdrawals,
        "g_success_rates": g_success_rates,
        "b_portfolio": b_portfolio,
        "b_withdrawals": b_withdrawals,
        "g_total_consumption": float(np.sum(g_withdrawals)),
        "b_total_consumption": float(np.sum(b_withdrawals)),
        "adjustment_events": adjustment_events,
    }
