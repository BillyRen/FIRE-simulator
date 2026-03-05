"""FIRE 积累阶段计算器 — 动态交叉法 + 蒙特卡洛模拟。

同时计算两条线并找交叉点：
  1. 累计资产线（MC 扇形，上升）: 储蓄 + 投资回报
  2. 所需 FIRE 资产线（下降）: 随退休年数缩短，SWR 升高，所需资产降低

支持统一现金流时间线：用户用绝对年份添加现金流，系统自动
按 FIRE 年分割为积累阶段和退休阶段。
"""

from __future__ import annotations

import numpy as np
from scipy import interpolate

from .cashflow import CashFlowItem, build_cf_schedule
from .sweep import pregenerate_return_scenarios, _simulate_success_and_funded


# ---------------------------------------------------------------------------
# 现金流分割
# ---------------------------------------------------------------------------

def _split_cashflows_at_year(
    cash_flows: list[CashFlowItem],
    fire_year: int,
) -> tuple[list[CashFlowItem], list[CashFlowItem]]:
    """将统一时间线的现金流按 FIRE 年分割为积累和退休两部分。

    Parameters
    ----------
    cash_flows : list[CashFlowItem]
        绝对年份的现金流（year 1 = 从现在起第 1 年）。
    fire_year : int
        FIRE 年份（从现在起第几年退休）。0 表示立刻退休。

    Returns
    -------
    tuple[list[CashFlowItem], list[CashFlowItem]]
        (pre_fire_cfs, post_fire_cfs)
        post_fire_cfs 已重新索引为退休第 1 年起。
    """
    pre_fire: list[CashFlowItem] = []
    post_fire: list[CashFlowItem] = []

    for cf in cash_flows:
        cf_end = cf.start_year + cf.duration - 1

        if cf_end <= fire_year:
            pre_fire.append(cf)
        elif cf.start_year > fire_year:
            post_fire.append(CashFlowItem(
                name=cf.name,
                amount=cf.amount,
                start_year=cf.start_year - fire_year,
                duration=cf.duration,
                inflation_adjusted=cf.inflation_adjusted,
            ))
        else:
            pre_duration = fire_year - cf.start_year + 1
            post_duration = cf.duration - pre_duration
            pre_fire.append(CashFlowItem(
                name=cf.name,
                amount=cf.amount,
                start_year=cf.start_year,
                duration=pre_duration,
                inflation_adjusted=cf.inflation_adjusted,
            ))
            if post_duration > 0:
                post_fire.append(CashFlowItem(
                    name=cf.name,
                    amount=cf.amount,
                    start_year=1,
                    duration=post_duration,
                    inflation_adjusted=cf.inflation_adjusted,
                ))

    return pre_fire, post_fire


# ---------------------------------------------------------------------------
# 所需 FIRE 资产二分查找
# ---------------------------------------------------------------------------

def _binary_search_required_portfolio(
    return_scenarios: np.ndarray,
    inflation_matrix: np.ndarray,
    annual_withdrawal: float,
    target_success: float,
    withdrawal_strategy: str,
    retirement_age: int,
    dynamic_ceiling: float,
    dynamic_floor: float,
    cash_flows: list[CashFlowItem] | None = None,
    max_iterations: int = 20,
    tolerance: float = 0.005,
) -> float:
    """二分搜索满足目标成功率的最小初始资产。

    Parameters
    ----------
    return_scenarios : ndarray, shape (num_sims, retirement_years)
    inflation_matrix : ndarray, shape (num_sims, retirement_years)
    annual_withdrawal : float
        退休后年支出。
    target_success : float
        目标成功率 (0-1)。
    withdrawal_strategy, retirement_age, dynamic_ceiling, dynamic_floor
        提取策略参数。
    cash_flows : list[CashFlowItem] or None
        退休阶段现金流（已重新索引为退休第 1 年起）。
    max_iterations : int
        二分搜索最大迭代次数。
    tolerance : float
        成功率误差容忍度。

    Returns
    -------
    float
        满足目标成功率的最小初始资产（保守取上界）。
    """
    lo = annual_withdrawal * 2
    hi = annual_withdrawal * 120

    sr_lo, _ = _simulate_success_and_funded(
        return_scenarios, lo, annual_withdrawal,
        withdrawal_strategy, dynamic_ceiling, dynamic_floor,
        retirement_age, cash_flows, inflation_matrix,
    )
    sr_hi, _ = _simulate_success_and_funded(
        return_scenarios, hi, annual_withdrawal,
        withdrawal_strategy, dynamic_ceiling, dynamic_floor,
        retirement_age, cash_flows, inflation_matrix,
    )

    if sr_lo >= target_success:
        return lo
    if sr_hi < target_success:
        return hi * 2

    for _ in range(max_iterations):
        mid = (lo + hi) / 2
        sr, _ = _simulate_success_and_funded(
            return_scenarios, mid, annual_withdrawal,
            withdrawal_strategy, dynamic_ceiling, dynamic_floor,
            retirement_age, cash_flows, inflation_matrix,
        )
        if abs(sr - target_success) < tolerance:
            return mid
        if sr >= target_success:
            hi = mid
        else:
            lo = mid

    return hi


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_accumulation(
    current_age: int,
    life_expectancy: int,
    current_portfolio: float,
    annual_income: float,
    annual_expenses: float,
    income_growth_rate: float,
    retirement_spending: float,
    target_success_rate: float,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    withdrawal_strategy: str,
    dynamic_ceiling: float,
    dynamic_floor: float,
    num_simulations: int,
    min_block: int,
    max_block: int,
    returns_df,
    cash_flows: list[CashFlowItem] | None = None,
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
    country_dfs: dict | None = None,
    country_weights: dict[str, float] | None = None,
    num_sims_swr: int = 500,
    swr_sample_interval: int = 5,
    expense_growth_rate: float = 0.0,
    auto_retirement_spending: bool = False,
) -> dict:
    """运行 FIRE 积累阶段蒙特卡洛模拟。

    Parameters
    ----------
    current_age : int
        当前年龄。
    life_expectancy : int
        预期寿命。
    current_portfolio : float
        当前投资组合价值。
    annual_income : float
        年税后收入（实际购买力）。
    annual_expenses : float
        年支出（实际购买力）。
    income_growth_rate : float
        年收入实际增长率（如 0.02 = 2%）。
    retirement_spending : float
        退休后年支出（实际购买力）。
    target_success_rate : float
        目标成功率（如 0.85）。
    allocation, expense_ratios : dict
        资产配置和费用率。
    withdrawal_strategy : str
        退休阶段提取策略。
    dynamic_ceiling, dynamic_floor : float
        动态提取上下限。
    num_simulations : int
        积累阶段 MC 模拟次数。
    min_block, max_block : int
        Block bootstrap 窗口。
    returns_df : pd.DataFrame
        历史回报数据。
    cash_flows : list[CashFlowItem] or None
        统一时间线现金流（年份从现在起）。
    leverage, borrowing_spread : float
        杠杆参数。
    country_dfs, country_weights : dict or None
        池化 bootstrap 参数。
    num_sims_swr : int
        SWR 二分查找使用的模拟次数（默认 500）。
    swr_sample_interval : int
        SWR 采样间隔年数（默认 5）。

    Returns
    -------
    dict
        包含 FIRE 年龄分位数、概率曲线、资产轨迹、SWR 曲线、敏感性数据等。
    """
    min_retirement_years = 5
    max_working_years = max(1, life_expectancy - current_age - min_retirement_years)
    max_retirement_years = life_expectancy - current_age

    rng = np.random.default_rng(42)
    cfs = cash_flows or []

    # ── 1. 预生成积累阶段 MC 回报场景 ──
    accum_scenarios, accum_inflation = pregenerate_return_scenarios(
        allocation, expense_ratios, max_working_years,
        min_block, max_block, num_simulations,
        returns_df, seed=int(rng.integers(0, 2**31)),
        leverage=leverage, borrowing_spread=borrowing_spread,
        country_dfs=country_dfs, country_weights=country_weights,
    )

    # ── 2. 预生成退休阶段 MC 回报场景（用于 SWR 计算）──
    retire_scenarios, retire_inflation = pregenerate_return_scenarios(
        allocation, expense_ratios, max_retirement_years,
        min_block, max_block, num_sims_swr,
        returns_df, seed=int(rng.integers(0, 2**31)),
        leverage=leverage, borrowing_spread=borrowing_spread,
        country_dfs=country_dfs, country_weights=country_weights,
    )

    # ── 3. 计算所需 FIRE 资产曲线 ──
    sample_years = list(range(0, max_working_years + 1, swr_sample_interval))
    if sample_years[-1] != max_working_years:
        sample_years.append(max_working_years)

    req_portfolio_samples = []
    swr_samples = []
    spending_at_year = []

    for t in sample_years:
        remaining = life_expectancy - (current_age + t)
        if remaining < min_retirement_years:
            req_portfolio_samples.append(0.0)
            swr_samples.append(1.0)
            spending_at_year.append(0.0)
            continue

        if auto_retirement_spending:
            spend_t = annual_expenses * (1.0 + expense_growth_rate) ** t
        else:
            spend_t = retirement_spending

        _, post_fire_cfs = _split_cashflows_at_year(cfs, t)
        cf_arg = post_fire_cfs if post_fire_cfs else None
        retirement_age_at_fire = current_age + t

        req_p = _binary_search_required_portfolio(
            retire_scenarios[:, :remaining],
            retire_inflation[:, :remaining],
            spend_t,
            target_success_rate,
            withdrawal_strategy,
            retirement_age_at_fire,
            dynamic_ceiling, dynamic_floor,
            cash_flows=cf_arg,
        )
        req_portfolio_samples.append(req_p)
        swr = spend_t / req_p if req_p > 0 else 0.0
        swr_samples.append(swr)
        spending_at_year.append(spend_t)

    # 线性插值到每年
    interp_portfolio = interpolate.interp1d(
        sample_years, req_portfolio_samples,
        kind="linear", fill_value="extrapolate",
    )
    interp_swr = interpolate.interp1d(
        sample_years, swr_samples,
        kind="linear", fill_value="extrapolate",
    )
    all_years = np.arange(max_working_years + 1)
    required_portfolio_curve = np.maximum(interp_portfolio(all_years), 0.0)
    swr_curve = np.clip(interp_swr(all_years), 0.0, 1.0)

    # ── 4. 构建积累阶段现金流 schedule ──
    if cfs:
        pre_fire_cfs_max, _ = _split_cashflows_at_year(cfs, max_working_years)
        adj_cfs = [cf for cf in pre_fire_cfs_max if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in pre_fire_cfs_max if not cf.inflation_adjusted]
        fixed_cf_schedule = build_cf_schedule(adj_cfs, max_working_years)
        has_nominal = len(nominal_cfs) > 0
    else:
        fixed_cf_schedule = np.zeros(max_working_years)
        nominal_cfs = []
        has_nominal = False

    # ── 5. 模拟积累路径 ──
    portfolio_paths = np.zeros((num_simulations, max_working_years + 1))
    portfolio_paths[:, 0] = current_portfolio

    for i in range(num_simulations):
        if has_nominal:
            nom_schedule = build_cf_schedule(
                nominal_cfs, max_working_years, accum_inflation[i],
            )
            cf_schedule = fixed_cf_schedule + nom_schedule
        else:
            cf_schedule = fixed_cf_schedule

        income = annual_income
        expenses = annual_expenses
        for t in range(max_working_years):
            savings = income - expenses + cf_schedule[t]
            new_val = portfolio_paths[i, t] * (1.0 + accum_scenarios[i, t]) + savings
            portfolio_paths[i, t + 1] = max(new_val, 0.0)
            income *= (1.0 + income_growth_rate)
            expenses *= (1.0 + expense_growth_rate)

    # ── 6. 检测 FIRE 交叉点 ──
    fire_years = np.full(num_simulations, -1, dtype=int)
    for t in range(max_working_years + 1):
        reached = (portfolio_paths[:, t] >= required_portfolio_curve[t]) & (fire_years < 0)
        fire_years[reached] = t

    # ── 7. 计算 FIRE 概率曲线 ──
    fire_prob_by_year = np.zeros(max_working_years + 1)
    for t in range(max_working_years + 1):
        fire_prob_by_year[t] = np.mean((fire_years >= 0) & (fire_years <= t))

    # ── 8. 百分位轨迹 ──
    pct_keys = ["p10", "p25", "p50", "p75", "p90"]
    pct_vals = [10, 25, 50, 75, 90]
    percentile_trajectories = {
        k: np.percentile(portfolio_paths, v, axis=0).tolist()
        for k, v in zip(pct_keys, pct_vals)
    }

    # ── 9. FIRE 年龄统计 ──
    valid_fire_years = fire_years[fire_years >= 0]
    fire_probability = float(len(valid_fire_years) / num_simulations)

    if len(valid_fire_years) > 0:
        fire_age_p25 = int(current_age + np.percentile(valid_fire_years, 25))
        fire_age_p50 = int(current_age + np.percentile(valid_fire_years, 50))
        fire_age_p75 = int(current_age + np.percentile(valid_fire_years, 75))
    else:
        fire_age_p25 = fire_age_p50 = fire_age_p75 = None

    # SWR 和所需资产在中位 FIRE 年
    if fire_age_p50 is not None:
        fire_idx = min(fire_age_p50 - current_age, max_working_years)
        swr_at_fire = float(swr_curve[fire_idx])
        req_portfolio_at_fire = float(required_portfolio_curve[fire_idx])
        if auto_retirement_spending:
            ret_spending_at_fire = float(annual_expenses * (1.0 + expense_growth_rate) ** fire_idx)
        else:
            ret_spending_at_fire = float(retirement_spending)
    else:
        swr_at_fire = float(swr_curve[0])
        req_portfolio_at_fire = float(required_portfolio_curve[0])
        ret_spending_at_fire = float(retirement_spending)

    # ── 10. 敏感性分析：FIRE 年龄 vs 年支出 ──
    median_return = float(np.median(accum_scenarios))
    n_expense_levels = 7
    expense_levels = np.linspace(
        max(annual_expenses * 0.5, 1.0),
        min(annual_expenses * 1.5, annual_income * 0.95),
        n_expense_levels,
    )
    sensitivity_fire_ages: list[int | None] = []

    for exp_level in expense_levels:
        p = current_portfolio
        inc = annual_income
        exp = exp_level
        fire_year_est = None
        for t in range(max_working_years):
            sav = inc - exp
            p = p * (1.0 + median_return) + sav
            if t + 1 < len(required_portfolio_curve) and p >= required_portfolio_curve[t + 1]:
                fire_year_est = t + 1
                break
            inc *= (1.0 + income_growth_rate)
            exp *= (1.0 + expense_growth_rate)
        if fire_year_est is not None:
            sensitivity_fire_ages.append(current_age + fire_year_est)
        else:
            sensitivity_fire_ages.append(None)

    savings_rate = float((annual_income - annual_expenses) / annual_income) if annual_income > 0 else 0.0

    return {
        "fire_age_p25": fire_age_p25,
        "fire_age_p50": fire_age_p50,
        "fire_age_p75": fire_age_p75,
        "fire_probability": fire_probability,
        "savings_rate": savings_rate,
        "annual_savings": annual_income - annual_expenses,
        "swr_at_fire": swr_at_fire,
        "required_portfolio_at_fire": req_portfolio_at_fire,
        "retirement_spending_at_fire": ret_spending_at_fire,
        "percentile_trajectories": percentile_trajectories,
        "required_portfolio_curve": required_portfolio_curve.tolist(),
        "swr_curve": swr_curve.tolist(),
        "fire_prob_by_year": fire_prob_by_year.tolist(),
        "age_labels": list(range(current_age, current_age + max_working_years + 1)),
        "sensitivity_expenses": expense_levels.tolist(),
        "sensitivity_fire_ages": sensitivity_fire_ages,
    }
