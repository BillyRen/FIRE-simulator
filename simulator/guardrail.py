"""Risk-based Guardrail 策略引擎。

核心思路：预构建 2D 成功率查找表 success_rate(withdrawal_rate, remaining_years)，
使模拟中每年的成功率查询变为 O(1) 插值操作，避免嵌套模拟。
"""

import numpy as np

from simulator.config import GUARDRAIL_RATE_MIN, GUARDRAIL_RATE_MAX, GUARDRAIL_RATE_STEP


# ---------------------------------------------------------------------------
# 1. 查找表构建
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

    # table[rate_idx, year] = 提取 year 年后的成功率
    table = np.zeros((num_rates, max_years + 1))
    table[:, 0] = 1.0  # 0 年提取，全部存活

    for rate_idx in range(num_rates):
        rate = rate_grid[rate_idx]
        # 归一化：初始值 = 1.0
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

    Parameters
    ----------
    table : np.ndarray
        shape (num_rates, max_years + 1) 的成功率表。
    rate_grid : np.ndarray
        提取率网格。
    rate : float
        当前提取率。
    remaining_years : int
        剩余年限。

    Returns
    -------
    float
        插值后的成功率。
    """
    max_years = table.shape[1] - 1
    remaining_years = min(remaining_years, max_years)
    remaining_years = max(remaining_years, 0)

    # 将 rate 限制在网格范围内
    if rate <= rate_grid[0]:
        return float(table[0, remaining_years])
    if rate >= rate_grid[-1]:
        return float(table[-1, remaining_years])

    # 线性插值 rate 维度
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
    """反向查找：给定目标成功率和剩余年限，找到对应的提取率。

    成功率随提取率增大而单调递减。

    Parameters
    ----------
    table : np.ndarray
        成功率查找表。
    rate_grid : np.ndarray
        提取率网格。
    target_success : float
        目标成功率 (0-1)。
    remaining_years : int
        剩余年限。

    Returns
    -------
    float
        对应的提取率。如果无法达到目标成功率返回 0.0 或 rate_grid[-1]。
    """
    max_years = table.shape[1] - 1
    remaining_years = min(remaining_years, max_years)
    remaining_years = max(remaining_years, 1)

    # 获取该剩余年限下的成功率列（随 rate 递减）
    col = table[:, remaining_years]

    # 如果最低 rate 的成功率都低于目标，返回 0
    if col[0] < target_success:
        return 0.0

    # 如果最高 rate 的成功率都高于目标，返回最高 rate
    if col[-1] >= target_success:
        return float(rate_grid[-1])

    # 找到成功率从 >= target 跌到 < target 的位置
    for i in range(len(col) - 1):
        if col[i] >= target_success and col[i + 1] < target_success:
            # 线性插值
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
) -> float:
    """根据调整模式计算护栏触发后的新提取金额。

    Parameters
    ----------
    wd : float
        当前提取金额。
    value : float
        当前资产价值。
    current_success : float
        当前成功率。
    target_success : float
        目标成功率。
    adjustment_pct : float
        调整百分比 (0-1)。
    adjustment_mode : str
        "amount" = 按金额比例调整, "success_rate" = 按成功率比例调整。
    remaining : int
        剩余年限。
    table, rate_grid : np.ndarray
        成功率查找表及网格。

    Returns
    -------
    float
        调整后的提取金额。
    """
    if adjustment_mode == "success_rate":
        # 计算中间目标成功率，然后找对应的提取率
        adjusted_success = current_success + adjustment_pct * (
            target_success - current_success
        )
        adjusted_rate = find_rate_for_target(
            table, rate_grid, adjusted_success, remaining
        )
        return value * adjusted_rate
    else:
        # 默认 "amount" 模式：按金额比例调整
        target_rate = find_rate_for_target(
            table, rate_grid, target_success, remaining
        )
        target_wd = value * target_rate
        return wd + adjustment_pct * (target_wd - wd)


# ---------------------------------------------------------------------------
# 5. Guardrail 模拟
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
) -> tuple[float, np.ndarray, np.ndarray]:
    """运行 Risk-based Guardrail 模拟。

    步骤：
    1. 根据 target_success 和 retirement_years 从查找表反解出初始提取率，
       计算初始资产 = annual_withdrawal / initial_rate
    2. 逐年模拟：查表获取当前成功率，触发护栏时调整提取金额

    Parameters
    ----------
    scenarios : np.ndarray
        shape (num_sims, max_years) 的回报矩阵。max_years >= retirement_years。
    annual_withdrawal : float
        初始年提取金额（实际购买力）。
    target_success : float
        目标成功率 (0-1)。
    upper_guardrail : float
        上护栏成功率。
    lower_guardrail : float
        下护栏成功率。
    adjustment_pct : float
        调整百分比 (0-1)，1.0 = 100% 调整到目标。
    retirement_years : int
        退休年限。
    min_remaining_years : int
        计算成功率时的最小剩余年限。
    table : np.ndarray
        成功率查找表。
    rate_grid : np.ndarray
        提取率网格。
    adjustment_mode : str
        "amount" = 按金额比例调整, "success_rate" = 按成功率比例调整。

    Returns
    -------
    tuple[float, np.ndarray, np.ndarray]
        (initial_portfolio, trajectories, withdrawals)
        - initial_portfolio: 计算出的初始资产
        - trajectories: shape (num_sims, retirement_years + 1)
        - withdrawals: shape (num_sims, retirement_years)
    """
    num_sims = scenarios.shape[0]

    # 1. 计算初始资产
    initial_rate = find_rate_for_target(table, rate_grid, target_success, retirement_years)
    if initial_rate <= 0:
        # 无法达到目标成功率，使用一个保守的极小值
        initial_rate = rate_grid[1] if len(rate_grid) > 1 else 0.01
    initial_portfolio = annual_withdrawal / initial_rate

    # 2. 逐年模拟
    trajectories = np.zeros((num_sims, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.zeros((num_sims, retirement_years))

    for i in range(num_sims):
        value = initial_portfolio
        wd = annual_withdrawal

        for year in range(retirement_years):
            remaining = max(min_remaining_years, retirement_years - year)

            # 查询当前成功率
            if value > 0:
                current_rate = wd / value
                current_success = lookup_success_rate(
                    table, rate_grid, current_rate, remaining
                )

                # 检查护栏
                if current_success < lower_guardrail or current_success > upper_guardrail:
                    wd = _apply_guardrail_adjustment(
                        wd, value, current_success, target_success,
                        adjustment_pct, adjustment_mode, remaining,
                        table, rate_grid,
                    )

            withdrawals[i, year] = wd
            value = value * (1.0 + scenarios[i, year]) - wd

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
) -> tuple[np.ndarray, np.ndarray]:
    """运行固定提取率基准模拟。

    Parameters
    ----------
    scenarios : np.ndarray
        回报矩阵。
    initial_portfolio : float
        初始资产（与 guardrail 相同）。
    baseline_rate : float
        固定提取率。
    retirement_years : int
        退休年限。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (trajectories, withdrawals)
    """
    num_sims = scenarios.shape[0]
    annual_wd = initial_portfolio * baseline_rate

    trajectories = np.zeros((num_sims, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.zeros((num_sims, retirement_years))

    for i in range(num_sims):
        value = initial_portfolio
        for year in range(retirement_years):
            withdrawals[i, year] = annual_wd
            value = value * (1.0 + scenarios[i, year]) - annual_wd
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
) -> dict:
    """在单条历史回报路径上运行 guardrail 策略和固定基准策略。

    使用蒙特卡洛查找表来评估每年的成功率（模拟真实决策过程：
    退休者基于蒙特卡洛概率估计来判断是否触发护栏调整）。

    Parameters
    ----------
    real_returns : np.ndarray
        1D 数组，从起始年开始的实际组合回报序列。
    initial_portfolio : float
        初始资产（由蒙特卡洛阶段的 guardrail 模拟计算得出）。
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
    table : np.ndarray
        成功率查找表。
    rate_grid : np.ndarray
        提取率网格。
    adjustment_mode : str
        "amount" = 按金额比例调整, "success_rate" = 按成功率比例调整。

    Returns
    -------
    dict
        包含以下键：
        - years_simulated: 实际模拟年数
        - g_portfolio: guardrail 逐年资产值 (years_simulated + 1,)
        - g_withdrawals: guardrail 逐年提取金额 (years_simulated,)
        - g_success_rates: 每年的成功率 (years_simulated,)
        - b_portfolio: 基准逐年资产值 (years_simulated + 1,)
        - b_withdrawals: 基准逐年提取金额 (years_simulated,)
        - g_total_consumption: guardrail 总消费额
        - b_total_consumption: 基准总消费额
    """
    n_available = len(real_returns)
    n_years = min(retirement_years, n_available)

    # Guardrail 策略
    g_portfolio = np.zeros(n_years + 1)
    g_portfolio[0] = initial_portfolio
    g_withdrawals = np.zeros(n_years)
    g_success_rates = np.zeros(n_years)

    value = initial_portfolio
    wd = annual_withdrawal

    for year in range(n_years):
        remaining = max(min_remaining_years, retirement_years - year)

        if value > 0:
            current_rate = wd / value
            current_success = lookup_success_rate(
                table, rate_grid, current_rate, remaining
            )
            g_success_rates[year] = current_success

            if current_success < lower_guardrail or current_success > upper_guardrail:
                wd = _apply_guardrail_adjustment(
                    wd, value, current_success, target_success,
                    adjustment_pct, adjustment_mode, remaining,
                    table, rate_grid,
                )
        else:
            g_success_rates[year] = 0.0

        g_withdrawals[year] = wd
        value = value * (1.0 + real_returns[year]) - wd
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
    }
