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

    # 买房净资产（假设当年卖房后能拿到的净额）
    buy_net_worth_nominal = np.zeros(analysis_years + 1)
    for t in range(analysis_years + 1):
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

    # Breakeven: 买房最终获胜时，最后一次从落后翻转为领先的年份
    breakeven_year = None
    if advantage_real[-1] > 0:
        for t in range(analysis_years, 0, -1):
            if advantage_real[t - 1] <= 0:
                breakeven_year = t
                break
        if breakeven_year is None:
            breakeven_year = 0

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


def _simulate_paths_batch(
    num_sims: int,
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
    home_appreciation: np.ndarray,       # (N, T)
    rent_growth: np.ndarray,             # (N, T)
    mortgage_rates: np.ndarray,          # (N, T)
    investment_returns_nominal: np.ndarray,  # (N, T)
    inflation: np.ndarray,               # (N, T)
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised batch simulation of N buy-vs-rent paths.

    Returns (buy_nw_real, rent_nw_real, advantage_real, breakeven_years,
             buy_cost_real, rent_cost_real).
    All output arrays have shape (N, T+1) except buy_cost_real / rent_cost_real
    which are (N, T), and breakeven_years which is (N,).
    """
    N, T = num_sims, analysis_years
    dp = home_price * down_payment_pct
    bc = home_price * buying_cost_pct
    initial_capital = dp + bc
    mortgage_principal = home_price - dp

    # Cumulative inflation (N, T+1)
    cum_infl = np.ones((N, T + 1))
    cum_infl[:, 1:] = np.cumprod(1 + inflation, axis=1)

    # Home value via cumulative product (N, T+1)
    home_val = np.empty((N, T + 1))
    home_val[:, 0] = home_price
    home_val[:, 1:] = home_price * np.cumprod(1 + home_appreciation, axis=1)

    # Mortgage balance & buy costs — sequential over T, vectorised over N
    mort_bal = np.zeros((N, T + 1))
    mort_bal[:, 0] = mortgage_principal
    buy_cost_total = np.zeros((N, T))

    for t in range(T):
        remaining = mortgage_term - t
        bal = mort_bal[:, t]

        if remaining > 0:
            rate = mortgage_rates[:, t]
            active = bal > 0

            payment = np.zeros(N)
            pos_rate = active & (rate > 0)
            if pos_rate.any():
                r = rate[pos_rate]
                b = bal[pos_rate]
                payment[pos_rate] = b * r * (1 + r) ** remaining / ((1 + r) ** remaining - 1)
            zero_rate = active & (rate <= 0)
            if zero_rate.any():
                payment[zero_rate] = bal[zero_rate] / remaining

            interest = bal * rate
            principal = np.clip(payment - interest, 0, bal)
            mort_bal[:, t + 1] = bal - principal
        else:
            payment = np.zeros(N)
            mort_bal[:, t + 1] = 0.0

        tax = home_val[:, t] * property_tax_pct
        maint = home_val[:, t] * maintenance_pct
        insur = insurance_annual * cum_infl[:, t]
        buy_cost_total[:, t] = payment + tax + maint + insur

    buy_nw_nom = home_val * (1 - selling_cost_pct) - mort_bal

    # Rent via cumulative product (N, T)
    rg = (1 + rent_growth).copy()
    rg[:, 0] = 1.0
    rent_ann = annual_rent * np.cumprod(rg, axis=1)

    # Renter portfolio — sequential over T, vectorised over N
    portfolio = np.zeros((N, T + 1))
    portfolio[:, 0] = initial_capital
    for t in range(T):
        cf = buy_cost_total[:, t] - rent_ann[:, t]
        portfolio[:, t + 1] = np.maximum(
            portfolio[:, t] * (1 + investment_returns_nominal[:, t]) + cf, 0.0,
        )

    rent_nw_nom = portfolio

    # Convert to real values
    buy_nw_real = buy_nw_nom / cum_infl
    rent_nw_real = rent_nw_nom / cum_infl
    advantage_real = buy_nw_real - rent_nw_real
    buy_cost_real = buy_cost_total / cum_infl[:, :T]
    rent_cost_real = rent_ann / cum_infl[:, :T]

    # Breakeven — fully vectorised
    final_pos = advantage_real[:, -1] > 0
    adv_pos = advantage_real > 0                      # (N, T+1)
    transitions = adv_pos[:, 1:] & ~adv_pos[:, :-1]   # (N, T) — ≤0 → >0
    rev_trans = transitions[:, ::-1]
    has_trans = rev_trans.any(axis=1)
    last_idx_rev = rev_trans.argmax(axis=1)
    last_year = T - last_idx_rev                       # breakeven year

    breakeven_years = np.full(N, np.nan)
    mask = final_pos & has_trans
    breakeven_years[mask] = last_year[mask]
    breakeven_years[final_pos & ~has_trans] = 0        # always positive

    return buy_nw_real, rent_nw_real, advantage_real, breakeven_years, buy_cost_real, rent_cost_real


def _sample_mc_paths(
    num_simulations: int,
    analysis_years: int,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    mortgage_rate_spread: float,
    min_block: int,
    max_block: int,
    returns_df: pd.DataFrame,
    rng: np.random.Generator,
    country_dfs: dict[str, pd.DataFrame] | None = None,
    country_weights: dict[str, float] | None = None,
    override_home_appreciation: float | None = None,
    override_rent_growth: float | None = None,
    override_mortgage_rate: float | None = None,
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sample N sets of per-year return arrays via block bootstrap.

    Returns five (N, T) arrays:
        (home_appr, rent_gr, mort_rates, inv_returns_nominal, inflation)
    """
    N, T = num_simulations, analysis_years
    all_cols = RETURN_COLS + HOUSING_COLS

    all_home = np.zeros((N, T))
    all_rent = np.zeros((N, T))
    all_mort = np.zeros((N, T))
    all_inv = np.zeros((N, T))
    all_infl = np.zeros((N, T))

    for sim in range(N):
        if country_dfs is not None:
            sampled = block_bootstrap_pooled(
                country_dfs, T, min_block, max_block,
                rng=rng, country_weights=country_weights, columns=all_cols,
            )
        else:
            sampled = block_bootstrap(
                returns_df, T, min_block, max_block,
                rng=rng, columns=all_cols,
            )

        infl = sampled["Inflation"].values

        # Investment return
        nom_ret = np.zeros(T)
        asset_map = {"domestic_stock": "Domestic_Stock",
                     "global_stock": "Global_Stock",
                     "domestic_bond": "Domestic_Bond"}
        for ak, col in asset_map.items():
            w = allocation.get(ak, 0.0)
            e = expense_ratios.get(ak, 0.0)
            nom_ret += w * (sampled[col].values - e)
        if leverage != 1.0:
            nom_ret = leverage * nom_ret - (leverage - 1.0) * (infl + borrowing_spread)

        # Housing
        ha = np.full(T, override_home_appreciation) if override_home_appreciation is not None else sampled["Housing_CapGain"].values
        rg = np.full(T, override_rent_growth) if override_rent_growth is not None else sampled["Rent_Growth"].values
        mr = np.full(T, override_mortgage_rate) if override_mortgage_rate is not None else np.maximum(sampled["Long_Rate"].values + mortgage_rate_spread, 0.001)

        # NaN safety
        ha = np.nan_to_num(ha, nan=float(np.nanmedian(ha)) if not np.all(np.isnan(ha)) else 0.0)
        rg = np.nan_to_num(rg, nan=float(np.nanmedian(rg)) if not np.all(np.isnan(rg)) else 0.0)
        mr = np.nan_to_num(mr, nan=float(np.nanmedian(mr)) if not np.all(np.isnan(mr)) else 0.05)

        all_home[sim] = ha
        all_rent[sim] = rg
        all_mort[sim] = mr
        all_inv[sim] = nom_ret
        all_infl[sim] = infl

    return all_home, all_rent, all_mort, all_inv, all_infl


def _compute_sampled_stats(
    home_appr: np.ndarray,    # (N, T)
    rent_gr: np.ndarray,
    mort_rates: np.ndarray,
    inv_ret: np.ndarray,
    inflation: np.ndarray,
    percentiles: list[int],
) -> list[dict[str, str]]:
    """Compute per-path summary statistics and format as percentile table."""
    N, T = home_appr.shape
    inv_t = 1.0 / T

    s_home_nom = np.prod(1 + home_appr, axis=1) ** inv_t - 1
    s_rent_nom = np.prod(1 + rent_gr, axis=1) ** inv_t - 1
    s_infl = np.prod(1 + inflation, axis=1) ** inv_t - 1
    s_inv_nom = np.prod(1 + inv_ret, axis=1) ** inv_t - 1

    home_real = (1 + home_appr) / (1 + inflation) - 1
    rent_real = (1 + rent_gr) / (1 + inflation) - 1
    inv_real = (1 + inv_ret) / (1 + inflation) - 1

    s_home_real = np.prod(1 + home_real, axis=1) ** inv_t - 1
    s_rent_real = np.prod(1 + rent_real, axis=1) ** inv_t - 1
    s_inv_real = np.prod(1 + inv_real, axis=1) ** inv_t - 1

    s_mort = mort_rates.mean(axis=1)
    s_vol = home_appr.std(axis=1, ddof=1) if T > 1 else np.zeros(N)

    cum_nom = np.cumprod(1 + home_appr, axis=1)
    peak_nom = np.maximum.accumulate(cum_nom, axis=1)
    s_dd_nom = np.min(cum_nom / peak_nom - 1, axis=1)

    cum_real = np.cumprod(1 + home_real, axis=1)
    peak_real = np.maximum.accumulate(cum_real, axis=1)
    s_dd_real = np.min(cum_real / peak_real - 1, axis=1)

    metrics = [
        ("ann_home_appreciation_nominal", s_home_nom),
        ("ann_home_appreciation_real", s_home_real),
        ("ann_rent_growth_nominal", s_rent_nom),
        ("ann_rent_growth_real", s_rent_real),
        ("avg_mortgage_rate", s_mort),
        ("ann_inflation", s_infl),
        ("ann_investment_nominal", s_inv_nom),
        ("ann_investment_real", s_inv_real),
        ("max_home_drawdown_nominal", s_dd_nom),
        ("max_home_drawdown_real", s_dd_real),
        ("home_price_volatility", s_vol),
    ]
    rows: list[dict[str, str]] = []
    for key, vals in metrics:
        row: dict[str, str] = {"metric": key}
        for p in percentiles:
            row[f"P{p}"] = f"{float(np.percentile(vals, p)):.2%}"
        rows.append(row)
    return rows


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
    """蒙特卡洛版：block bootstrap 采样 + 向量化批量模拟。"""
    rng = np.random.default_rng(seed)

    # Phase 1 — sample N sets of return arrays
    all_home, all_rent, all_mort, all_inv, all_infl = _sample_mc_paths(
        num_simulations, analysis_years, allocation, expense_ratios,
        mortgage_rate_spread, min_block, max_block, returns_df, rng,
        country_dfs=country_dfs, country_weights=country_weights,
        override_home_appreciation=override_home_appreciation,
        override_rent_growth=override_rent_growth,
        override_mortgage_rate=override_mortgage_rate,
        leverage=leverage, borrowing_spread=borrowing_spread,
    )

    # Phase 2 — vectorised batch simulation
    buy_nw, rent_nw, advantage, breakeven_years, buy_cost_real, rent_cost_real = (
        _simulate_paths_batch(
            num_simulations, home_price, down_payment_pct, mortgage_term,
            buying_cost_pct, selling_cost_pct, property_tax_pct,
            maintenance_pct, insurance_annual, annual_rent, analysis_years,
            all_home, all_rent, all_mort, all_inv, all_infl,
        )
    )

    # Phase 3 — statistics
    percentiles = [10, 25, 50, 75, 90]

    def _pct(data: np.ndarray) -> dict[str, list[float]]:
        return {f"P{p}": np.percentile(data, p, axis=0).tolist() for p in percentiles}

    buy_wins_prob = (advantage > 0).mean(axis=0).tolist()

    valid_be = breakeven_years[~np.isnan(breakeven_years)]
    be_stats: dict = {}
    if len(valid_be) > 0:
        be_stats = {f"P{p}": float(np.percentile(valid_be, p)) for p in percentiles}
        be_stats["mean"] = float(valid_be.mean())
        be_stats["pct_reached"] = float(len(valid_be) / num_simulations)
    else:
        be_stats["pct_reached"] = 0.0

    sampled_stats = _compute_sampled_stats(all_home, all_rent, all_mort, all_inv, all_infl, percentiles)

    return {
        "num_simulations": num_simulations,
        "analysis_years": analysis_years,
        "buy_percentile_trajectories": _pct(buy_nw),
        "rent_percentile_trajectories": _pct(rent_nw),
        "advantage_percentile_trajectories": _pct(advantage),
        "buy_wins_probability": buy_wins_prob,
        "breakeven_percentiles": be_stats,
        "buy_cost_median": np.median(buy_cost_real, axis=0).tolist(),
        "rent_cost_median": np.median(rent_cost_real, axis=0).tolist(),
        "sampled_stats": sampled_stats,
        "summary": {
            "final_buy_median": float(np.median(buy_nw[:, -1])),
            "final_rent_median": float(np.median(rent_nw[:, -1])),
            "final_advantage_median": float(np.median(advantage[:, -1])),
            "final_buy_wins_pct": float((advantage[:, -1] > 0).mean()),
            "breakeven_median": be_stats.get("P50"),
        },
    }


def _auto_ha(price: float, annual_rent: float, rent_growth_rate: float,
             fair_pe: float, reversion_years: int) -> float:
    """Compute auto-estimated home appreciation rate for a given price.

    Mean-reversion model: price converges to fair_pe * future_rent over
    reversion_years.
    """
    if annual_rent <= 0 or price <= 0 or reversion_years <= 0:
        return 0.0
    future_rent = annual_rent * (1 + rent_growth_rate) ** reversion_years
    fair_value = future_rent * fair_pe
    return (fair_value / price) ** (1.0 / reversion_years) - 1.0


def find_breakeven_price_simple(
    *,
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
    price_low: float | None = None,
    price_high: float | None = None,
    auto_estimate_ha: bool = False,
    fair_pe: float | None = None,
    reversion_years: int | None = None,
) -> dict:
    """Binary search for the home price where buying breaks even with renting.

    When auto_estimate_ha is True, the home appreciation rate is dynamically
    recomputed for each candidate price using the mean-reversion model.
    """
    from scipy.optimize import brentq

    if price_low is None:
        price_low = annual_rent * 1
    if price_high is None:
        price_high = annual_rent * 200

    def _get_ha(price: float) -> float:
        if auto_estimate_ha and fair_pe is not None and reversion_years is not None:
            return _auto_ha(price, annual_rent, rent_growth_rate, fair_pe, reversion_years)
        return home_appreciation_rate

    def objective(price: float) -> float:
        r = run_simple_buy_vs_rent(
            home_price=price,
            down_payment_pct=down_payment_pct,
            mortgage_term=mortgage_term,
            mortgage_rate=mortgage_rate,
            buying_cost_pct=buying_cost_pct,
            selling_cost_pct=selling_cost_pct,
            property_tax_pct=property_tax_pct,
            maintenance_pct=maintenance_pct,
            insurance_annual=insurance_annual,
            annual_rent=annual_rent,
            rent_growth_rate=rent_growth_rate,
            home_appreciation_rate=_get_ha(price),
            investment_return_rate=investment_return_rate,
            inflation_rate=inflation_rate,
            analysis_years=analysis_years,
        )
        return r["summary"]["final_advantage"]

    fa_low = objective(price_low)
    fa_high = objective(price_high)

    if fa_low * fa_high > 0:
        return {
            "found": False,
            "breakeven_price": None,
            "message": "no_sign_change",
            "advantage_at_low": fa_low,
            "advantage_at_high": fa_high,
        }

    bp = brentq(objective, price_low, price_high, xtol=100)
    ha_at_bp = _get_ha(bp)
    full = run_simple_buy_vs_rent(
        home_price=bp,
        down_payment_pct=down_payment_pct,
        mortgage_term=mortgage_term,
        mortgage_rate=mortgage_rate,
        buying_cost_pct=buying_cost_pct,
        selling_cost_pct=selling_cost_pct,
        property_tax_pct=property_tax_pct,
        maintenance_pct=maintenance_pct,
        insurance_annual=insurance_annual,
        annual_rent=annual_rent,
        rent_growth_rate=rent_growth_rate,
        home_appreciation_rate=ha_at_bp,
        investment_return_rate=investment_return_rate,
        inflation_rate=inflation_rate,
        analysis_years=analysis_years,
    )
    result = {
        "found": True,
        "breakeven_price": round(bp, -2),
        "price_to_annual_rent": round(bp / annual_rent, 1),
        "summary": full["summary"],
    }
    if auto_estimate_ha:
        result["ha_at_breakeven"] = round(ha_at_bp * 100, 2)
    return result


def find_breakeven_price_mc(
    *,
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
    target_win_pct: float = 0.5,
    price_low: float | None = None,
    price_high: float | None = None,
) -> dict:
    """Binary search for breakeven home price using MC simulation.

    Samples paths ONCE and reuses them across all binary search iterations.
    The objective is to find the price where P(buy wins) = target_win_pct.
    """
    from scipy.optimize import brentq

    rng = np.random.default_rng(seed)

    if price_low is None:
        price_low = annual_rent * 1
    if price_high is None:
        price_high = annual_rent * 200

    all_home, all_rent, all_mort, all_inv, all_infl = _sample_mc_paths(
        num_simulations, analysis_years, allocation, expense_ratios,
        mortgage_rate_spread, min_block, max_block, returns_df, rng,
        country_dfs=country_dfs, country_weights=country_weights,
        override_home_appreciation=override_home_appreciation,
        override_rent_growth=override_rent_growth,
        override_mortgage_rate=override_mortgage_rate,
        leverage=leverage, borrowing_spread=borrowing_spread,
    )

    def objective(price: float) -> float:
        _, _, adv, _, _, _ = _simulate_paths_batch(
            num_simulations, price, down_payment_pct, mortgage_term,
            buying_cost_pct, selling_cost_pct, property_tax_pct,
            maintenance_pct, insurance_annual, annual_rent, analysis_years,
            all_home, all_rent, all_mort, all_inv, all_infl,
        )
        win_pct = float((adv[:, -1] > 0).mean())
        return win_pct - target_win_pct

    v_low = objective(price_low)
    v_high = objective(price_high)

    if v_low * v_high > 0:
        return {
            "found": False,
            "breakeven_price": None,
            "message": "no_sign_change",
            "win_pct_at_low": v_low + target_win_pct,
            "win_pct_at_high": v_high + target_win_pct,
        }

    bp = brentq(objective, price_low, price_high, xtol=100)

    # Final evaluation at breakeven price
    buy_nw, rent_nw, adv, be_years, _, _ = _simulate_paths_batch(
        num_simulations, bp, down_payment_pct, mortgage_term,
        buying_cost_pct, selling_cost_pct, property_tax_pct,
        maintenance_pct, insurance_annual, annual_rent, analysis_years,
        all_home, all_rent, all_mort, all_inv, all_infl,
    )

    return {
        "found": True,
        "breakeven_price": round(bp, -2),
        "price_to_annual_rent": round(bp / annual_rent, 1),
        "target_win_pct": target_win_pct,
        "actual_win_pct": float((adv[:, -1] > 0).mean()),
        "median_advantage": float(np.median(adv[:, -1])),
        "median_buy_nw": float(np.median(buy_nw[:, -1])),
        "median_rent_nw": float(np.median(rent_nw[:, -1])),
    }
