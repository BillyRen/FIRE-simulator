"""买房 vs 租房 对比模拟模块。

全程使用名义值计算（房贷、房价、租金天然都是名义值），
最终输出时用累积通胀折算为第 0 年实际购买力。

核心模型：
  买房净资产 = 房产当前价值 * (1 - 卖房费率) - 剩余贷款
  租房净资产 = 投资组合价值

  租房者的投资组合追踪两方案之间的累计现金流差异：
    第 0 年：初始资金 = 首付 + 买房交易费用
    第 t 年：portfolio = portfolio * (1 + 名义投资回报) + (买房年支出 - 租金)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from simulator.bootstrap import (
    HOUSING_COLS,
    RETURN_COLS,
    block_bootstrap,
    block_bootstrap_pooled,
)
from simulator.portfolio import compute_real_portfolio_returns


def _mortgage_annual_payment(balance: float, annual_rate: float, remaining_years: int) -> float:
    """等额本息年还款额（名义值）。balance 为 0 或 remaining_years 为 0 时返回 0。"""
    if balance <= 0 or remaining_years <= 0:
        return 0.0
    if annual_rate <= 0:
        return balance / remaining_years
    r = annual_rate
    n = remaining_years
    return balance * r * (1 + r) ** n / ((1 + r) ** n - 1)


def _simulate_path(
    *,
    home_price: float,
    down_payment_pct: float,
    mortgage_term: int,
    buying_cost_pct: float,
    selling_cost_pct: float,
    property_tax_pct: float,
    maintenance_pct: float,
    insurance_annual: float,
    annual_rent: float,
    analysis_years: int,
    # Per-year arrays (length = analysis_years), all nominal
    home_appreciation: np.ndarray,
    rent_growth: np.ndarray,
    mortgage_rates: np.ndarray,
    investment_returns_nominal: np.ndarray,
    inflation: np.ndarray,
) -> dict:
    """模拟一条买房 vs 租房路径（名义值），然后转换为实际值。"""

    down_payment = home_price * down_payment_pct
    buying_costs = home_price * buying_cost_pct
    initial_capital = down_payment + buying_costs
    mortgage_principal = home_price - down_payment

    # 累积通胀因子（用于名义→实际转换）
    cum_inflation = np.ones(analysis_years + 1)
    for t in range(analysis_years):
        cum_inflation[t + 1] = cum_inflation[t] * (1 + inflation[t])

    # --- 买房路径（名义值） ---
    home_value = np.zeros(analysis_years + 1)
    home_value[0] = home_price
    mortgage_balance = np.zeros(analysis_years + 1)
    mortgage_balance[0] = mortgage_principal

    buy_cost_interest = np.zeros(analysis_years)
    buy_cost_principal = np.zeros(analysis_years)
    buy_cost_tax = np.zeros(analysis_years)
    buy_cost_maintenance = np.zeros(analysis_years)
    buy_cost_insurance = np.zeros(analysis_years)
    buy_cost_total = np.zeros(analysis_years)

    for t in range(analysis_years):
        # 房价增值
        home_value[t + 1] = home_value[t] * (1 + home_appreciation[t])

        # 房贷还款
        remaining_term = mortgage_term - t
        if remaining_term > 0 and mortgage_balance[t] > 0:
            payment = _mortgage_annual_payment(
                mortgage_balance[t], mortgage_rates[t], remaining_term
            )
            interest = mortgage_balance[t] * mortgage_rates[t]
            principal_paid = payment - interest
            principal_paid = min(principal_paid, mortgage_balance[t])
            mortgage_balance[t + 1] = mortgage_balance[t] - principal_paid
        else:
            payment = 0.0
            interest = 0.0
            principal_paid = 0.0
            mortgage_balance[t + 1] = 0.0

        buy_cost_interest[t] = interest
        buy_cost_principal[t] = principal_paid

        # 持有成本（基于当前房价）
        buy_cost_tax[t] = home_value[t] * property_tax_pct
        buy_cost_maintenance[t] = home_value[t] * maintenance_pct
        # 保险按通胀调整
        buy_cost_insurance[t] = insurance_annual * cum_inflation[t]

        buy_cost_total[t] = (payment + buy_cost_tax[t]
                             + buy_cost_maintenance[t] + buy_cost_insurance[t])

    # 买房净资产（卖房后）
    buy_net_worth_nominal = np.zeros(analysis_years + 1)
    buy_net_worth_nominal[0] = -buying_costs  # 沉没成本
    for t in range(1, analysis_years + 1):
        buy_net_worth_nominal[t] = (
            home_value[t] * (1 - selling_cost_pct) - mortgage_balance[t]
        )

    # --- 租房路径（名义值） ---
    rent_annual = np.zeros(analysis_years)
    rent_annual[0] = annual_rent
    for t in range(1, analysis_years):
        rent_annual[t] = rent_annual[t - 1] * (1 + rent_growth[t])

    # 租房者投资组合
    portfolio = np.zeros(analysis_years + 1)
    portfolio[0] = initial_capital
    for t in range(analysis_years):
        cash_flow_diff = buy_cost_total[t] - rent_annual[t]
        portfolio[t + 1] = portfolio[t] * (1 + investment_returns_nominal[t]) + cash_flow_diff
        portfolio[t + 1] = max(portfolio[t + 1], 0.0)

    rent_net_worth_nominal = portfolio.copy()

    # --- 转换为实际值（第 0 年购买力） ---
    buy_net_worth_real = buy_net_worth_nominal / cum_inflation
    rent_net_worth_real = rent_net_worth_nominal / cum_inflation
    advantage_real = buy_net_worth_real - rent_net_worth_real

    # 成本明细转换为实际值
    buy_cost_total_real = buy_cost_total / cum_inflation[:analysis_years]
    rent_cost_real = rent_annual / cum_inflation[:analysis_years]

    # Breakeven: 第一个 advantage_real > 0 的年份（从第 1 年开始）
    breakeven_year = None
    for t in range(1, analysis_years + 1):
        if advantage_real[t] > 0:
            breakeven_year = t
            break

    return {
        "buy_net_worth_real": buy_net_worth_real.tolist(),
        "rent_net_worth_real": rent_net_worth_real.tolist(),
        "advantage_real": advantage_real.tolist(),
        "breakeven_year": breakeven_year,
        "home_value_real": (home_value / cum_inflation).tolist(),
        "mortgage_balance_real": (mortgage_balance / cum_inflation).tolist(),
        "buy_cost_total_real": buy_cost_total_real.tolist(),
        "rent_cost_real": rent_cost_real.tolist(),
        "buy_cost_interest_real": (buy_cost_interest / cum_inflation[:analysis_years]).tolist(),
        "buy_cost_principal_real": (buy_cost_principal / cum_inflation[:analysis_years]).tolist(),
        "buy_cost_tax_real": (buy_cost_tax / cum_inflation[:analysis_years]).tolist(),
        "buy_cost_maintenance_real": (buy_cost_maintenance / cum_inflation[:analysis_years]).tolist(),
        "buy_cost_insurance_real": (buy_cost_insurance / cum_inflation[:analysis_years]).tolist(),
    }


def run_simple_buy_vs_rent(
    home_price: float,
    down_payment_pct: float,
    mortgage_term: int,
    mortgage_rate: float,
    buying_cost_pct: float,
    selling_cost_pct: float,
    property_tax_pct: float,
    maintenance_pct: float,
    insurance_annual: float,
    annual_rent: float,
    rent_growth_rate: float,
    home_appreciation_rate: float,
    investment_return_rate: float,
    inflation_rate: float,
    analysis_years: int,
) -> dict:
    """简化版：用固定利率/增长率进行确定性计算。

    所有 rate 参数均为名义年化利率（小数形式，如 0.05 = 5%）。

    Returns
    -------
    dict
        包含逐年净资产、成本明细、breakeven 年份等。
    """
    home_appr = np.full(analysis_years, home_appreciation_rate)
    rent_gr = np.full(analysis_years, rent_growth_rate)
    mort_rates = np.full(analysis_years, mortgage_rate)
    inv_ret = np.full(analysis_years, investment_return_rate)
    infl = np.full(analysis_years, inflation_rate)

    result = _simulate_path(
        home_price=home_price,
        down_payment_pct=down_payment_pct,
        mortgage_term=mortgage_term,
        buying_cost_pct=buying_cost_pct,
        selling_cost_pct=selling_cost_pct,
        property_tax_pct=property_tax_pct,
        maintenance_pct=maintenance_pct,
        insurance_annual=insurance_annual,
        annual_rent=annual_rent,
        analysis_years=analysis_years,
        home_appreciation=home_appr,
        rent_growth=rent_gr,
        mortgage_rates=mort_rates,
        investment_returns_nominal=inv_ret,
        inflation=infl,
    )

    result["analysis_years"] = analysis_years
    result["summary"] = {
        "final_buy_net_worth": result["buy_net_worth_real"][-1],
        "final_rent_net_worth": result["rent_net_worth_real"][-1],
        "final_advantage": result["advantage_real"][-1],
        "breakeven_year": result["breakeven_year"],
        "total_buy_cost_real": sum(result["buy_cost_total_real"]),
        "total_rent_cost_real": sum(result["rent_cost_real"]),
    }
    return result


def run_buy_vs_rent_mc(
    home_price: float,
    down_payment_pct: float,
    mortgage_term: int,
    mortgage_rate_spread: float,
    buying_cost_pct: float,
    selling_cost_pct: float,
    property_tax_pct: float,
    maintenance_pct: float,
    insurance_annual: float,
    annual_rent: float,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    analysis_years: int,
    num_simulations: int,
    min_block: int,
    max_block: int,
    returns_df: pd.DataFrame,
    seed: int | None = None,
    country_dfs: dict[str, pd.DataFrame] | None = None,
    country_weights: dict[str, float] | None = None,
    override_home_appreciation: float | None = None,
    override_rent_growth: float | None = None,
    override_mortgage_rate: float | None = None,
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
) -> dict:
    """蒙特卡洛版：用 block bootstrap 联合采样金融和房产数据。

    对于每个可覆盖的参数（home_appreciation, rent_growth, mortgage_rate），
    None 表示从 JST 数据采样，非 None 表示使用固定值。

    Returns
    -------
    dict
        包含百分位轨迹、P(买>租)、breakeven 分布、成本明细等。
    """
    rng = np.random.default_rng(seed)
    all_cols = RETURN_COLS + HOUSING_COLS

    # 收集每次模拟的结果
    buy_nw = np.zeros((num_simulations, analysis_years + 1))
    rent_nw = np.zeros((num_simulations, analysis_years + 1))
    advantage = np.zeros((num_simulations, analysis_years + 1))
    breakeven_years = np.full(num_simulations, np.nan)
    buy_costs_total = np.zeros((num_simulations, analysis_years))
    rent_costs_total = np.zeros((num_simulations, analysis_years))

    for sim in range(num_simulations):
        # Block bootstrap: 联合采样所有列
        if country_dfs is not None:
            sampled = block_bootstrap_pooled(
                country_dfs, analysis_years, min_block, max_block,
                rng=rng, country_weights=country_weights, columns=all_cols,
            )
        else:
            sampled = block_bootstrap(
                returns_df, analysis_years, min_block, max_block,
                rng=rng, columns=all_cols,
            )

        inflation = sampled["Inflation"].values

        # --- 投资组合名义回报 ---
        nominal_return = np.zeros(analysis_years)
        asset_map = {
            "domestic_stock": "Domestic_Stock",
            "global_stock": "Global_Stock",
            "domestic_bond": "Domestic_Bond",
        }
        for asset_key, col_name in asset_map.items():
            weight = allocation.get(asset_key, 0.0)
            expense = expense_ratios.get(asset_key, 0.0)
            nominal_return += weight * (sampled[col_name].values - expense)

        if leverage != 1.0:
            borrowing_cost = inflation + borrowing_spread
            nominal_return = leverage * nominal_return - (leverage - 1.0) * borrowing_cost

        # --- 房产数据 ---
        if override_home_appreciation is not None:
            home_appr = np.full(analysis_years, override_home_appreciation)
        else:
            home_appr = sampled["Housing_CapGain"].values

        if override_rent_growth is not None:
            rent_gr = np.full(analysis_years, override_rent_growth)
        else:
            rent_gr = sampled["Rent_Growth"].values

        if override_mortgage_rate is not None:
            mort_rates = np.full(analysis_years, override_mortgage_rate)
        else:
            mort_rates = sampled["Long_Rate"].values + mortgage_rate_spread
            mort_rates = np.maximum(mort_rates, 0.001)

        # 处理采样数据中可能的 NaN（个别年份缺失时用中位数填充）
        if np.any(np.isnan(home_appr)):
            home_appr = np.nan_to_num(home_appr, nan=np.nanmedian(home_appr))
        if np.any(np.isnan(rent_gr)):
            rent_gr = np.nan_to_num(rent_gr, nan=np.nanmedian(rent_gr))
        if np.any(np.isnan(mort_rates)):
            mort_rates = np.nan_to_num(mort_rates, nan=np.nanmedian(mort_rates))

        result = _simulate_path(
            home_price=home_price,
            down_payment_pct=down_payment_pct,
            mortgage_term=mortgage_term,
            buying_cost_pct=buying_cost_pct,
            selling_cost_pct=selling_cost_pct,
            property_tax_pct=property_tax_pct,
            maintenance_pct=maintenance_pct,
            insurance_annual=insurance_annual,
            annual_rent=annual_rent,
            analysis_years=analysis_years,
            home_appreciation=home_appr,
            rent_growth=rent_gr,
            mortgage_rates=mort_rates,
            investment_returns_nominal=nominal_return,
            inflation=inflation,
        )

        buy_nw[sim] = result["buy_net_worth_real"]
        rent_nw[sim] = result["rent_net_worth_real"]
        advantage[sim] = result["advantage_real"]
        breakeven_years[sim] = result["breakeven_year"] if result["breakeven_year"] is not None else np.nan
        buy_costs_total[sim] = result["buy_cost_total_real"]
        rent_costs_total[sim] = result["rent_cost_real"]

    # --- 统计汇总 ---
    percentiles = [10, 25, 50, 75, 90]

    def _pct_trajectories(data: np.ndarray) -> dict[str, list[float]]:
        return {
            f"P{p}": np.percentile(data, p, axis=0).tolist()
            for p in percentiles
        }

    buy_wins_prob = (advantage > 0).mean(axis=0).tolist()

    # Breakeven 分布
    valid_be = breakeven_years[~np.isnan(breakeven_years)]
    breakeven_stats: dict = {}
    if len(valid_be) > 0:
        breakeven_stats = {
            f"P{p}": float(np.percentile(valid_be, p))
            for p in percentiles
        }
        breakeven_stats["mean"] = float(valid_be.mean())
        breakeven_stats["pct_reached"] = float(len(valid_be) / num_simulations)
    else:
        breakeven_stats["pct_reached"] = 0.0

    return {
        "num_simulations": num_simulations,
        "analysis_years": analysis_years,
        "buy_percentile_trajectories": _pct_trajectories(buy_nw),
        "rent_percentile_trajectories": _pct_trajectories(rent_nw),
        "advantage_percentile_trajectories": _pct_trajectories(advantage),
        "buy_wins_probability": buy_wins_prob,
        "breakeven_percentiles": breakeven_stats,
        "buy_cost_median": np.median(buy_costs_total, axis=0).tolist(),
        "rent_cost_median": np.median(rent_costs_total, axis=0).tolist(),
        "summary": {
            "final_buy_median": float(np.median(buy_nw[:, -1])),
            "final_rent_median": float(np.median(rent_nw[:, -1])),
            "final_advantage_median": float(np.median(advantage[:, -1])),
            "final_buy_wins_pct": float((advantage[:, -1] > 0).mean()),
            "breakeven_median": breakeven_stats.get("P50"),
        },
    }
