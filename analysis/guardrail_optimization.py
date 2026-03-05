"""风险护栏策略参数优化分析。

通过历史回测网格搜索，寻找最优的护栏策略参数组合。
- 第一阶段：FIRE Dataset (美国 1871-2025) 网格搜索
- 第二阶段：JST 多国数据交叉验证
- 第三阶段：结果可视化与推荐
"""

import sys
import os
import time
import itertools
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

# 使项目根目录可 import
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import (
    load_fire_dataset,
    load_returns_data,
    filter_by_country,
    get_country_dfs,
)
from simulator.portfolio import compute_real_portfolio_returns
from simulator.bootstrap import block_bootstrap
from simulator.guardrail import (
    build_success_rate_table,
    run_historical_backtest,
)
from simulator.statistics import CONSUMPTION_FLOOR

# ═══════════════════════════════════════════════════════════════════════════
# 固定参数
# ═══════════════════════════════════════════════════════════════════════════

INITIAL_PORTFOLIO = 1_000_000
ANNUAL_WITHDRAWAL = 30_000
RETIREMENT_YEARS = 65
ALLOCATION = {"domestic_stock": 0.33, "global_stock": 0.67}
EXPENSE_RATIOS = {"domestic_stock": 0.005, "global_stock": 0.005}
BASELINE_RATE = ANNUAL_WITHDRAWAL / INITIAL_PORTFOLIO  # 0.03
MIN_BLOCK = 5
MAX_BLOCK = 15
NUM_SIMULATIONS = 2000
DATA_START_YEAR = 1926
SEED = 42
MIN_BACKTEST_YEARS = 10

# 评分体系：安全性门槛 —— p10_funded 低于此值的组合被大幅惩罚
SAFETY_THRESHOLD = 0.90

OUTPUT_DIR = ROOT / "analysis" / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
GUARDRAIL_OUTPUT_DIR = OUTPUT_DIR / "guardrail"
GUARDRAIL_OUTPUT_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# 搜索空间
# ═══════════════════════════════════════════════════════════════════════════

PARAM_GRID = {
    "target_success": [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95],
    "upper_guardrail": [0.90, 0.95, 0.99],
    "lower_guardrail": [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70],
    "adjustment_pct": [0.05, 0.10, 0.25, 0.50, 0.75, 1.0],
    "adjustment_mode": ["amount", "success_rate"],
    "min_remaining_years": [1, 5, 10, 15, 20],
}


def generate_valid_combos(grid: dict) -> list[dict]:
    """生成满足约束的参数组合: lower < target < upper。"""
    keys = list(grid.keys())
    combos = []
    for vals in itertools.product(*(grid[k] for k in keys)):
        combo = dict(zip(keys, vals))
        if combo["lower_guardrail"] >= combo["target_success"]:
            continue
        if combo["target_success"] >= combo["upper_guardrail"]:
            continue
        combos.append(combo)
    return combos


# ═══════════════════════════════════════════════════════════════════════════
# 数据准备
# ═══════════════════════════════════════════════════════════════════════════

def prepare_scenarios(returns_df: pd.DataFrame, expense_ratios: dict | None = None) -> np.ndarray:
    """生成 MC scenarios。"""
    er = expense_ratios or EXPENSE_RATIOS
    rng = np.random.default_rng(SEED)
    scenarios = np.zeros((NUM_SIMULATIONS, RETIREMENT_YEARS))
    for i in range(NUM_SIMULATIONS):
        sampled = block_bootstrap(returns_df, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK, rng=rng)
        scenarios[i] = compute_real_portfolio_returns(sampled, ALLOCATION, er)
    return scenarios


def prepare_historical_paths(returns_df: pd.DataFrame, expense_ratios: dict | None = None) -> list[dict]:
    """从历史数据提取所有回测路径。"""
    er = expense_ratios or EXPENSE_RATIOS
    df_sorted = returns_df.sort_values("Year").reset_index(drop=True)
    years_arr = df_sorted["Year"].values
    max_year = int(years_arr[-1])

    paths = []
    for start_year in years_arr:
        start_year = int(start_year)
        avail = max_year - start_year + 1
        if avail < MIN_BACKTEST_YEARS:
            continue
        n_years = min(RETIREMENT_YEARS, avail)
        subset = df_sorted[df_sorted["Year"] >= start_year].iloc[:n_years]
        real_returns = compute_real_portfolio_returns(subset, ALLOCATION, er)
        paths.append({
            "start_year": start_year,
            "n_years": n_years,
            "is_complete": n_years >= RETIREMENT_YEARS,
            "real_returns": real_returns,
        })
    return paths


# ═══════════════════════════════════════════════════════════════════════════
# 评分函数
# ═══════════════════════════════════════════════════════════════════════════

# v3 评分默认参数
V3_DEFAULTS = dict(
    safety_exponent=2.0,
    smoothness_decay=50.0,
    cew_gamma=2.0,
    cew_cap=0.15,
    p10u_cap=0.05,
)


def compute_v3_score(
    median_util: float,
    p10_util: float,
    median_discounted: float,
    p10_funded: float,
    p10_floor_self: float,
    p10_min_wd: float,
    median_downside_cv: float,
    p90_downside_cv: float,
    p90_max_drawdown: float,
    p90_years_below_ratio: float,
    median_cew: float,
    *,
    safety_exponent: float = 2.0,
    smoothness_decay: float = 50.0,
    cew_cap: float = 0.15,
    p10u_cap: float = 0.05,
) -> tuple[float, dict]:
    """计算 v3 评分（5 维精简归一化），返回 (score_v3, 分项明细)。

    核心原则：CEW (CRRA gamma=2) 已隐含惩罚消费波动和下行风险，
    保护维度只保留 CEW 无法捕捉的独立风险（绝对贫困、最大暴跌、持续贫困）。
    去掉与 CEW 冗余的 floor_self、smooth_median、smooth_p90。

    权重: CEW 0.50 + P10消费 0.15 + 底线绝对 0.10 + 无暴跌 0.10 + 无贫困 0.15 = 1.0
    消费:保护 = 0.65:0.35（CEW 本身是风险调整后的，故属于"消费+保护"混合指标）
    """
    baseline_wd = INITIAL_PORTFOLIO * BASELINE_RATE

    safety = p10_funded ** safety_exponent

    norm_cew = min(median_cew / cew_cap, 1.0) if cew_cap > 0 else 0.0
    norm_p10u = min(p10_util / p10u_cap, 1.0) if p10u_cap > 0 else 0.0
    norm_floor_abs = min(p10_min_wd / baseline_wd, 1.0) if baseline_wd > 0 else 0.0
    norm_no_crash = max(1.0 - p90_max_drawdown, 0.0)
    norm_no_poverty = max(1.0 - p90_years_below_ratio, 0.0)

    # 仍然计算冗余维度（用于诊断输出，但不进入主评分）
    norm_floor_self = p10_floor_self
    smooth_median = float(np.exp(-smoothness_decay * median_downside_cv))
    smooth_p90 = float(np.exp(-smoothness_decay * p90_downside_cv))

    score_v3 = safety * (
        0.50 * norm_cew
        + 0.15 * norm_p10u
        + 0.10 * norm_floor_abs
        + 0.10 * norm_no_crash
        + 0.15 * norm_no_poverty
    )

    detail = dict(
        v3_safety=safety,
        v3_norm_cew=norm_cew,
        v3_norm_p10u=norm_p10u,
        v3_norm_floor_self=norm_floor_self,
        v3_norm_floor_abs=norm_floor_abs,
        v3_smooth_median=smooth_median,
        v3_smooth_p90=smooth_p90,
        v3_norm_no_crash=norm_no_crash,
        v3_norm_no_poverty=norm_no_poverty,
    )
    return score_v3, detail


def compute_cew(wds_arr: np.ndarray, gamma: float = 2.0) -> np.ndarray:
    """计算每条路径的确定性等价消费 (Certainty-Equivalent Withdrawal)。

    使用 CRRA (Constant Relative Risk Aversion) 效用函数。
    返回 shape (n_sims,) 的 CEW 数组。
    """
    safe_wds = np.maximum(wds_arr, 1e-10)
    if abs(gamma - 1.0) < 1e-9:
        utility = np.log(safe_wds)
    else:
        utility = safe_wds ** (1.0 - gamma) / (1.0 - gamma)
    mean_utility = utility.mean(axis=1)
    if abs(gamma - 1.0) < 1e-9:
        cew = np.exp(mean_utility)
    else:
        cew = (mean_utility * (1.0 - gamma)) ** (1.0 / (1.0 - gamma))
    return cew


def compute_max_drawdown(wds_arr: np.ndarray) -> np.ndarray:
    """计算每条路径的消费最大回撤 (peak-to-trough)。返回 shape (n_sims,)。"""
    cummax = np.maximum.accumulate(wds_arr, axis=1)
    drawdown = 1.0 - wds_arr / np.maximum(cummax, 1e-10)
    return drawdown.max(axis=1)


def _compute_initial_wd(target_success, table, rate_grid):
    """根据 target_success 从查找表反算初始提取金额。"""
    max_table_years = table.shape[1] - 1
    remaining = min(RETIREMENT_YEARS, max_table_years)
    remaining = max(remaining, 1)
    col = table[:, remaining]
    col_rev = col[::-1]
    rg_rev = rate_grid[::-1]
    initial_rate = float(np.interp(target_success, col_rev, rg_rev))
    initial_wd = INITIAL_PORTFOLIO * initial_rate
    return initial_rate, initial_wd


def evaluate_combo(
    combo: dict,
    paths: list[dict],
    table: np.ndarray,
    rate_grid: np.ndarray,
) -> dict:
    """对一个参数组合，在所有历史路径上评估，返回聚合指标。"""
    initial_rate, initial_wd = _compute_initial_wd(
        combo["target_success"], table, rate_grid
    )
    complete_metrics = []

    for p in paths:
        result = run_historical_backtest(
            real_returns=p["real_returns"],
            initial_portfolio=INITIAL_PORTFOLIO,
            annual_withdrawal=initial_wd,
            target_success=combo["target_success"],
            upper_guardrail=combo["upper_guardrail"],
            lower_guardrail=combo["lower_guardrail"],
            adjustment_pct=combo["adjustment_pct"],
            retirement_years=RETIREMENT_YEARS,
            min_remaining_years=combo["min_remaining_years"],
            baseline_rate=BASELINE_RATE,
            table=table,
            rate_grid=rate_grid,
            adjustment_mode=combo["adjustment_mode"],
        )

        g_wd = result["g_withdrawals"]
        b_total = result["b_total_consumption"]
        g_total = result["g_total_consumption"]
        g_portfolio = result["g_portfolio"]
        n_years = result["years_simulated"]
        n_adj = len(result.get("adjustment_events", []))

        g_min_wd = float(np.min(g_wd)) if len(g_wd) > 0 else 0.0
        g_mean_wd = float(np.mean(g_wd)) if len(g_wd) > 0 else 0.0
        g_std_wd = float(np.std(g_wd)) if len(g_wd) > 0 else 0.0
        g_cv = g_std_wd / g_mean_wd if g_mean_wd > 0 else 999.0

        # 下行半方差：只计算消费下降的波动
        wd_changes = np.diff(g_wd) if len(g_wd) > 1 else np.array([0.0])
        neg_changes = np.minimum(wd_changes, 0.0)
        downside_sd = float(np.sqrt(np.mean(neg_changes ** 2)))
        downside_cv = downside_sd / g_mean_wd if g_mean_wd > 0 else 999.0

        # funded ratio for this path (消费地板 + 资产归零)
        depletion_year = n_years
        for y in range(1, len(g_portfolio)):
            if g_portfolio[y] <= 0:
                depletion_year = y
                break
        consumption_floor_val = CONSUMPTION_FLOOR * initial_wd
        eff_depletion = n_years
        for y in range(len(g_wd)):
            if g_wd[y] < consumption_floor_val:
                eff_depletion = y
                break
        depletion_year = min(depletion_year, eff_depletion)
        funded = min(depletion_year / RETIREMENT_YEARS, 1.0)
        g_survived = depletion_year >= n_years

        consumption_ratio = g_total / b_total if b_total > 0 else 0.0
        floor_ratio = g_min_wd / initial_wd
        avg_wd_ratio = g_mean_wd / initial_wd

        # 时间折现消费
        n_wd = len(g_wd)
        if n_wd > 0:
            disc = 1.0 / (1.02 ** np.arange(n_wd))
            disc_w = disc / disc.sum()
            discounted_wd = float(np.dot(g_wd, disc_w))
        else:
            discounted_wd = 0.0

        # v3 新指标
        g_wd_np = np.asarray(g_wd, dtype=float)
        cew_val = float(compute_cew(g_wd_np.reshape(1, -1))[0]) if len(g_wd) > 0 else 0.0
        md_val = float(compute_max_drawdown(g_wd_np.reshape(1, -1))[0]) if len(g_wd) > 0 else 0.0
        years_below = int(np.sum(g_wd_np < consumption_floor_val)) if len(g_wd) > 0 else 0

        if p["is_complete"]:
            complete_metrics.append({
                "g_survived": g_survived,
                "funded": funded,
                "g_total": g_total,
                "b_total": b_total,
                "consumption_ratio": consumption_ratio,
                "floor_ratio": floor_ratio,
                "avg_wd_ratio": avg_wd_ratio,
                "g_mean_wd": g_mean_wd,
                "g_min_wd": g_min_wd,
                "g_cv": g_cv,
                "downside_cv": downside_cv,
                "discounted_wd": discounted_wd,
                "n_adj": n_adj,
                "cew": cew_val,
                "max_drawdown": md_val,
                "years_below": years_below,
                "n_years": n_years,
            })

    if len(complete_metrics) == 0:
        return {**combo, "n_complete": 0, "score": -999}

    n_complete = len(complete_metrics)
    survived_arr = np.array([m["g_survived"] for m in complete_metrics])
    funded_arr = np.array([m["funded"] for m in complete_metrics])
    cr_arr = np.array([m["consumption_ratio"] for m in complete_metrics])
    fr_arr = np.array([m["floor_ratio"] for m in complete_metrics])
    awr_arr = np.array([m["avg_wd_ratio"] for m in complete_metrics])
    mean_wd_arr = np.array([m["g_mean_wd"] for m in complete_metrics])
    cv_arr = np.array([m["g_cv"] for m in complete_metrics])
    dcv_arr = np.array([m["downside_cv"] for m in complete_metrics])
    min_wd_arr = np.array([m["g_min_wd"] for m in complete_metrics])
    disc_wd_arr = np.array([m["discounted_wd"] for m in complete_metrics])
    adj_arr = np.array([m["n_adj"] for m in complete_metrics])
    cew_arr = np.array([m["cew"] for m in complete_metrics])
    md_arr = np.array([m["max_drawdown"] for m in complete_metrics])
    yb_arr = np.array([m["years_below"] for m in complete_metrics])
    ny_arr = np.array([m["n_years"] for m in complete_metrics])

    # 聚合指标
    success_rate = float(np.mean(survived_arr))
    median_funded = float(np.median(funded_arr))
    p10_funded = float(np.percentile(funded_arr, 10))

    median_cr = float(np.median(cr_arr))
    p10_cr = float(np.percentile(cr_arr, 10))

    median_fr = float(np.median(fr_arr))
    p10_fr = float(np.percentile(fr_arr, 10))

    median_avg_wd_ratio = float(np.median(awr_arr))
    p10_avg_wd_ratio = float(np.percentile(awr_arr, 10))

    median_cv = float(np.median(cv_arr))
    median_downside_cv = float(np.median(dcv_arr))
    p90_downside_cv = float(np.percentile(dcv_arr, 90))

    median_min_wd = float(np.median(min_wd_arr))
    p10_min_wd = float(np.percentile(min_wd_arr, 10))

    median_adj = float(np.median(adj_arr))

    median_util = float(np.median(mean_wd_arr)) / INITIAL_PORTFOLIO
    p10_util = float(np.percentile(mean_wd_arr, 10)) / INITIAL_PORTFOLIO
    median_discounted = float(np.median(disc_wd_arr)) / INITIAL_PORTFOLIO

    p10_floor_self = float(np.percentile(min_wd_arr / initial_wd, 10))
    p10_floor_self = min(p10_floor_self, 1.0)

    # v3 新指标
    median_cew = float(np.median(cew_arr)) / INITIAL_PORTFOLIO
    p90_max_drawdown = float(np.percentile(md_arr, 90))
    yb_ratio = yb_arr / np.maximum(ny_arr, 1).astype(float)
    p90_years_below_ratio = float(np.percentile(yb_ratio, 90))
    p10_floor_abs = min(p10_min_wd / (INITIAL_PORTFOLIO * BASELINE_RATE), 1.0)

    # v2 评分（向后兼容）
    safety = p10_funded ** 2
    smoothness = 1.0 / (1.0 + 20.0 * median_downside_cv)
    SCORE_SCALE = 15.0
    score = safety * (
        0.25 * median_util * SCORE_SCALE
        + 0.15 * p10_util * SCORE_SCALE
        + 0.20 * median_discounted * SCORE_SCALE
        + 0.20 * p10_floor_self
        + 0.20 * smoothness
    )

    # v3 评分
    score_v3, v3_detail = compute_v3_score(
        median_util=median_util,
        p10_util=p10_util,
        median_discounted=median_discounted,
        p10_funded=p10_funded,
        p10_floor_self=p10_floor_self,
        p10_min_wd=p10_min_wd,
        median_downside_cv=median_downside_cv,
        p90_downside_cv=p90_downside_cv,
        p90_max_drawdown=p90_max_drawdown,
        p90_years_below_ratio=p90_years_below_ratio,
        median_cew=median_cew,
    )

    return {
        **combo,
        "initial_rate": initial_rate,
        "initial_wd": initial_wd,
        "n_complete": n_complete,
        "success_rate": success_rate,
        "median_funded": median_funded,
        "p10_funded": p10_funded,
        "median_cr": median_cr,
        "p10_cr": p10_cr,
        "median_fr": median_fr,
        "p10_fr": p10_fr,
        "median_avg_wd_ratio": median_avg_wd_ratio,
        "p10_avg_wd_ratio": p10_avg_wd_ratio,
        "median_cv": median_cv,
        "median_downside_cv": median_downside_cv,
        "p90_downside_cv": p90_downside_cv,
        "median_min_wd": median_min_wd,
        "p10_min_wd": p10_min_wd,
        "median_adj": median_adj,
        "median_util": median_util,
        "p10_util": p10_util,
        "median_discounted": median_discounted,
        "p10_floor_self": p10_floor_self,
        "p10_floor_abs": p10_floor_abs,
        "median_cew": median_cew,
        "p90_max_drawdown": p90_max_drawdown,
        "p90_years_below_ratio": p90_years_below_ratio,
        "smoothness": smoothness,
        "score": score,
        "score_v3": score_v3,
        **v3_detail,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 向量化 MC 评估（numpy 批量处理所有 scenarios，避免逐条 Python 循环）
# ═══════════════════════════════════════════════════════════════════════════

def evaluate_combo_mc_fast(
    combo: dict,
    scenarios: np.ndarray,
    table: np.ndarray,
    rate_grid: np.ndarray,
) -> dict:
    """向量化评估：同时在所有 MC scenarios 上运行护栏策略。

    相比 evaluate_combo 逐条调用 run_historical_backtest，
    此函数用 numpy 一次处理全部 scenarios，速度快 ~100x。
    """
    n_sims = scenarios.shape[0]
    n_years = min(RETIREMENT_YEARS, scenarios.shape[1])
    max_table_years = table.shape[1] - 1

    target_success = combo["target_success"]
    upper = combo["upper_guardrail"]
    lower = combo["lower_guardrail"]
    adj_pct = combo["adjustment_pct"]
    mode = combo["adjustment_mode"]
    min_rem = combo["min_remaining_years"]

    # 根据 target_success 反算初始提取
    initial_rate, initial_wd = _compute_initial_wd(target_success, table, rate_grid)

    # ── Guardrail 策略（向量化） ──
    g_values = np.full(n_sims, float(INITIAL_PORTFOLIO))
    g_wds = np.full(n_sims, initial_wd)
    g_wds_arr = np.zeros((n_sims, n_years))
    g_depleted = np.zeros(n_sims, dtype=bool)
    g_depletion_year = np.full(n_sims, float(n_years))
    consumption_floor_val = CONSUMPTION_FLOOR * initial_wd
    g_eff_depleted = np.zeros(n_sims, dtype=bool)
    g_eff_depletion = np.full(n_sims, float(n_years))
    n_adj = np.zeros(n_sims, dtype=np.int32)

    for year in range(n_years):
        remaining = min(max(min_rem, RETIREMENT_YEARS - year), max_table_years)
        remaining = max(remaining, 1)
        col = table[:, remaining]

        alive = g_values > 0

        # rate → success (forward interpolation)
        rates = np.where(alive, g_wds / np.maximum(g_values, 1e-10), 0.0)
        success = np.interp(rates, rate_grid, col)

        need_adjust = alive & ((success < lower) | (success > upper))

        if np.any(need_adjust):
            n_adj[need_adjust] += 1
            col_rev = col[::-1]
            rg_rev = rate_grid[::-1]

            if mode == "amount":
                target_rate = float(np.interp(target_success, col_rev, rg_rev))
                target_wd = g_values[need_adjust] * target_rate
                g_wds[need_adjust] += adj_pct * (target_wd - g_wds[need_adjust])
            else:
                adj_success = success[need_adjust] + adj_pct * (
                    target_success - success[need_adjust]
                )
                adj_rates = np.interp(adj_success, col_rev, rg_rev)
                g_wds[need_adjust] = g_values[need_adjust] * adj_rates

        g_wds_arr[:, year] = g_wds

        newly_eff = alive & (~g_eff_depleted) & (g_wds < consumption_floor_val)
        g_eff_depletion[newly_eff] = year
        g_eff_depleted |= newly_eff

        g_values = g_values * (1.0 + scenarios[:, year]) - g_wds

        newly_depleted = (~g_depleted) & (g_values <= 0)
        g_depletion_year[newly_depleted] = year + 1
        g_depleted |= g_values <= 0
        g_values = np.maximum(g_values, 0.0)

    # ── Baseline 固定提取策略（向量化） ──
    b_wd_fixed = float(INITIAL_PORTFOLIO * BASELINE_RATE)
    b_values = np.full(n_sims, float(INITIAL_PORTFOLIO))
    b_total = np.zeros(n_sims)

    for year in range(n_years):
        wd = np.where(b_values > 0, b_wd_fixed, 0.0)
        b_total += wd
        b_values = b_values * (1.0 + scenarios[:, year]) - wd
        b_values = np.maximum(b_values, 0.0)

    # ── 聚合指标 ──
    combined_depletion = np.minimum(g_depletion_year, g_eff_depletion)
    g_survived = combined_depletion >= n_years
    g_funded = np.minimum(combined_depletion / RETIREMENT_YEARS, 1.0)
    g_total = g_wds_arr.sum(axis=1)
    g_min_wd = g_wds_arr.min(axis=1)
    g_mean_wd = g_wds_arr.mean(axis=1)
    g_std_wd = g_wds_arr.std(axis=1)
    g_cv = np.where(g_mean_wd > 0, g_std_wd / g_mean_wd, 999.0)

    # 下行半方差（向量化）
    wd_changes = np.diff(g_wds_arr, axis=1)  # (n_sims, n_years-1)
    neg_changes = np.minimum(wd_changes, 0.0)
    downside_sd = np.sqrt(np.mean(neg_changes ** 2, axis=1))
    g_downside_cv = np.where(g_mean_wd > 0, downside_sd / g_mean_wd, 999.0)

    cr = np.where(b_total > 0, g_total / b_total, 0.0)
    fr = g_min_wd / initial_wd
    avg_wd_ratio = g_mean_wd / initial_wd

    # 时间折现消费（2% 年化折现率）
    discount_factors = 1.0 / (1.02 ** np.arange(n_years))
    discount_weights = discount_factors / discount_factors.sum()
    discounted_wd = (g_wds_arr * discount_weights[np.newaxis, :]).sum(axis=1)

    success_rate = float(np.mean(g_survived))
    median_funded = float(np.median(g_funded))
    p10_funded = float(np.percentile(g_funded, 10))
    median_cr = float(np.median(cr))
    p10_cr = float(np.percentile(cr, 10))
    median_fr = float(np.median(fr))
    p10_fr = float(np.percentile(fr, 10))
    median_avg_wd_ratio = float(np.median(avg_wd_ratio))
    p10_avg_wd_ratio = float(np.percentile(avg_wd_ratio, 10))
    median_cv = float(np.median(g_cv))
    median_downside_cv = float(np.median(g_downside_cv))
    p90_downside_cv = float(np.percentile(g_downside_cv, 90))
    median_min_wd = float(np.median(g_min_wd))
    p10_min_wd = float(np.percentile(g_min_wd, 10))
    median_adj = float(np.median(n_adj))

    median_util = float(np.median(g_mean_wd)) / INITIAL_PORTFOLIO
    p10_util = float(np.percentile(g_mean_wd, 10)) / INITIAL_PORTFOLIO
    median_discounted = float(np.median(discounted_wd)) / INITIAL_PORTFOLIO

    p10_floor_self = float(np.percentile(g_min_wd / initial_wd, 10))
    p10_floor_self = min(p10_floor_self, 1.0)

    # v3 新指标
    cew_per_path = compute_cew(g_wds_arr)
    median_cew = float(np.median(cew_per_path)) / INITIAL_PORTFOLIO
    max_dd_per_path = compute_max_drawdown(g_wds_arr)
    p90_max_drawdown = float(np.percentile(max_dd_per_path, 90))
    below_floor = g_wds_arr < consumption_floor_val
    years_below = below_floor.sum(axis=1)
    p90_years_below_ratio = float(np.percentile(years_below / n_years, 90))
    p10_floor_abs = min(p10_min_wd / (INITIAL_PORTFOLIO * BASELINE_RATE), 1.0)

    # v2 评分（向后兼容）
    safety = p10_funded ** 2
    smoothness = 1.0 / (1.0 + 20.0 * median_downside_cv)
    SCORE_SCALE = 15.0
    score = safety * (
        0.25 * median_util * SCORE_SCALE
        + 0.15 * p10_util * SCORE_SCALE
        + 0.20 * median_discounted * SCORE_SCALE
        + 0.20 * p10_floor_self
        + 0.20 * smoothness
    )

    # v3 评分
    score_v3, v3_detail = compute_v3_score(
        median_util=median_util,
        p10_util=p10_util,
        median_discounted=median_discounted,
        p10_funded=p10_funded,
        p10_floor_self=p10_floor_self,
        p10_min_wd=p10_min_wd,
        median_downside_cv=median_downside_cv,
        p90_downside_cv=p90_downside_cv,
        p90_max_drawdown=p90_max_drawdown,
        p90_years_below_ratio=p90_years_below_ratio,
        median_cew=median_cew,
    )

    return {
        **combo,
        "initial_rate": initial_rate,
        "initial_wd": initial_wd,
        "n_complete": n_sims,
        "success_rate": success_rate,
        "median_funded": median_funded,
        "p10_funded": p10_funded,
        "median_cr": median_cr,
        "p10_cr": p10_cr,
        "median_fr": median_fr,
        "p10_fr": p10_fr,
        "median_avg_wd_ratio": median_avg_wd_ratio,
        "p10_avg_wd_ratio": p10_avg_wd_ratio,
        "median_cv": median_cv,
        "median_downside_cv": median_downside_cv,
        "p90_downside_cv": p90_downside_cv,
        "median_min_wd": median_min_wd,
        "p10_min_wd": p10_min_wd,
        "median_adj": median_adj,
        "median_util": median_util,
        "p10_util": p10_util,
        "median_discounted": median_discounted,
        "p10_floor_self": p10_floor_self,
        "p10_floor_abs": p10_floor_abs,
        "median_cew": median_cew,
        "p90_max_drawdown": p90_max_drawdown,
        "p90_years_below_ratio": p90_years_below_ratio,
        "smoothness": smoothness,
        "score": score,
        "score_v3": score_v3,
        **v3_detail,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 网格搜索
# ═══════════════════════════════════════════════════════════════════════════

def _run_search(
    paths: list[dict],
    table: np.ndarray,
    rate_grid: np.ndarray,
    combos: list[dict],
    label: str,
) -> pd.DataFrame:
    """通用网格搜索：在给定的 paths 上评估所有参数组合。"""
    print(f"\n  开始搜索 {len(combos)} 个参数组合...")

    results = []
    t0 = time.time()
    for i, combo in enumerate(combos):
        r = evaluate_combo(combo, paths, table, rate_grid)
        results.append(r)
        if (i + 1) % 200 == 0 or i == len(combos) - 1:
            elapsed = time.time() - t0
            speed = (i + 1) / elapsed
            eta = (len(combos) - i - 1) / speed if speed > 0 else 0
            print(f"    [{i+1}/{len(combos)}]  {speed:.0f} combo/s  ETA: {eta:.0f}s")

    df = pd.DataFrame(results)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    print(f"\n  {label} 搜索完成: {time.time()-t0:.1f}s")
    return df


def _run_mc_search(
    scenarios: np.ndarray,
    table: np.ndarray,
    rate_grid: np.ndarray,
    combos: list[dict],
    label: str,
) -> pd.DataFrame:
    """向量化 MC 网格搜索：用 evaluate_combo_mc_fast 批量处理所有 scenarios。"""
    print(f"\n  开始向量化 MC 搜索 {len(combos)} 个参数组合 ({scenarios.shape[0]} paths)...")

    results = []
    t0 = time.time()
    for i, combo in enumerate(combos):
        r = evaluate_combo_mc_fast(combo, scenarios, table, rate_grid)
        results.append(r)
        if (i + 1) % 200 == 0 or i == len(combos) - 1:
            elapsed = time.time() - t0
            speed = (i + 1) / elapsed
            eta = (len(combos) - i - 1) / speed if speed > 0 else 0
            print(f"    [{i+1}/{len(combos)}]  {speed:.0f} combo/s  ETA: {eta:.0f}s")

    df = pd.DataFrame(results)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    print(f"\n  {label} 搜索完成: {time.time()-t0:.1f}s")
    return df


def run_grid_search(
    returns_df: pd.DataFrame,
    label: str = "FIRE",
    combos: list[dict] | None = None,
    mode: str = "both",
    expense_ratios: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame | None, np.ndarray, np.ndarray]:
    """对给定数据集运行网格搜索。

    mode: "hist" = 仅历史, "mc" = 仅 MC, "both" = 两者都跑
    返回 (hist_df, mc_df, rate_grid, table)
    """
    print(f"\n{'='*60}")
    print(f"  {label}: 准备数据")
    print(f"{'='*60}")

    if combos is None:
        combos = generate_valid_combos(PARAM_GRID)

    # 1. 生成 MC scenarios
    t0 = time.time()
    scenarios = prepare_scenarios(returns_df, expense_ratios=expense_ratios)
    print(f"  MC scenarios: {scenarios.shape} ({time.time()-t0:.1f}s)")

    # 2. 构建查找表
    t0 = time.time()
    rate_grid, table = build_success_rate_table(scenarios)
    print(f"  查找表: {table.shape}, rate_grid: [{rate_grid[0]:.3f}, {rate_grid[-1]:.3f}] ({time.time()-t0:.1f}s)")

    hist_df = None
    mc_df = None

    # 历史回测搜索（向量化：提取完整路径堆叠为矩阵）
    if mode in ("hist", "both"):
        paths = prepare_historical_paths(returns_df, expense_ratios=expense_ratios)
        complete_paths = [p for p in paths if p["is_complete"]]
        print(f"  历史路径: {len(paths)} 条 (完整: {len(complete_paths)}, 向量化评估)")
        if len(complete_paths) > 0:
            hist_scenarios = np.array([p["real_returns"] for p in complete_paths])
            hist_df = _run_mc_search(hist_scenarios, table, rate_grid, combos, f"{label}-Hist")
        else:
            print(f"  警告: 没有完整历史路径")
            hist_df = pd.DataFrame()

    # MC 搜索（向量化，2000 条路径同时处理）
    if mode in ("mc", "both"):
        print(f"  MC 路径: {scenarios.shape[0]} 条 (全部完整)")
        mc_df = _run_mc_search(scenarios, table, rate_grid, combos, f"{label}-MC")

    return hist_df, mc_df, rate_grid, table


# ═══════════════════════════════════════════════════════════════════════════
# JST 交叉验证
# ═══════════════════════════════════════════════════════════════════════════

def run_jst_cross_validation(
    top_combos: list[dict],
    n_top: int = 20,
    rank_col: str = "fire_rank",
) -> pd.DataFrame:
    """使用 JST 多国数据对 top-N 参数组合进行交叉验证（历史回测）。"""
    print(f"\n{'='*60}")
    print(f"  JST 交叉验证 (top-{n_top})")
    print(f"{'='*60}")

    jst_df = load_returns_data()
    country_dfs = get_country_dfs(jst_df, DATA_START_YEAR)
    print(f"  JST 国家: {list(country_dfs.keys())}")

    usa_df = filter_by_country(jst_df, "USA", DATA_START_YEAR)
    print(f"  构建查找表 (JST USA)...")
    t0 = time.time()
    scenarios = prepare_scenarios(usa_df)
    rate_grid, table = build_success_rate_table(scenarios)
    print(f"    完成 ({time.time()-t0:.1f}s)")

    all_paths = []
    for iso, cdf in country_dfs.items():
        cdf_sorted = cdf.sort_values("Year").reset_index(drop=True)
        years_arr = cdf_sorted["Year"].values
        max_year = int(years_arr[-1])

        for start_year in years_arr:
            start_year = int(start_year)
            avail = max_year - start_year + 1
            if avail < MIN_BACKTEST_YEARS:
                continue
            n_years = min(RETIREMENT_YEARS, avail)
            subset = cdf_sorted[cdf_sorted["Year"] >= start_year].iloc[:n_years]
            real_returns = compute_real_portfolio_returns(subset, ALLOCATION, EXPENSE_RATIOS)
            all_paths.append({
                "country": iso,
                "start_year": start_year,
                "n_years": n_years,
                "is_complete": n_years >= RETIREMENT_YEARS,
                "real_returns": real_returns,
            })

    n_complete = sum(1 for p in all_paths if p["is_complete"])
    print(f"  JST 历史路径: {len(all_paths)} 条 (完整: {n_complete})")

    combos_to_test = top_combos[:n_top]
    print(f"  评估 {len(combos_to_test)} 个参数组合...")
    t0 = time.time()
    results = []
    for i, combo in enumerate(combos_to_test):
        r = evaluate_combo(combo, all_paths, table, rate_grid)
        r[rank_col] = i + 1
        results.append(r)

    df = pd.DataFrame(results)
    df["jst_rank"] = df["score"].rank(ascending=False).astype(int)
    df = df.sort_values(rank_col)
    print(f"  完成 ({time.time()-t0:.1f}s)")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════════════

def _spearman_rho(x, y):
    """Spearman rank correlation (无需 scipy)。"""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = len(x)
    if n < 2:
        return 0.0
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    d = rx - ry
    return 1.0 - 6.0 * np.sum(d ** 2) / (n * (n ** 2 - 1))


# ═══════════════════════════════════════════════════════════════════════════
# 可视化
# ═══════════════════════════════════════════════════════════════════════════

def plot_pareto(df: pd.DataFrame, label: str = "FIRE"):
    """Pareto 前沿图: 三维度权衡可视化。"""
    safe = df[df["p10_funded"] >= SAFETY_THRESHOLD].copy()
    if len(safe) == 0:
        print(f"  [Pareto] 没有 p10_funded >= {SAFETY_THRESHOLD} 的组合，放宽到 >= 0.80")
        safe = df[df["p10_funded"] >= 0.80].copy()
    if len(safe) == 0:
        print(f"  [Pareto] 无法绘制 Pareto 图")
        return

    fig, axes = plt.subplots(1, 3, figsize=(22, 7))
    top10 = safe.nlargest(10, "score")

    # 左图: median_avg_wd_ratio vs p10_fr (平均消费水平 vs 尾部保护)
    ax = axes[0]
    sc = ax.scatter(
        safe["median_avg_wd_ratio"], safe["p10_fr"],
        c=safe["score"], cmap="viridis", s=20, alpha=0.6, edgecolors="none",
    )
    plt.colorbar(sc, ax=ax, label="Score")
    for _, row in top10.iterrows():
        ax.annotate(
            f"#{int(row.name)+1}",
            (row["median_avg_wd_ratio"], row["p10_fr"]),
            fontsize=7, fontweight="bold", color="red",
            textcoords="offset points", xytext=(5, 5),
        )
    ax.set_xlabel("Median Avg Withdrawal Ratio (avg spend / initial)", fontsize=10)
    ax.set_ylabel("P10 Floor Ratio (worst-case min wd / initial)", fontsize=10)
    ax.set_title("Avg Consumption vs Tail Protection", fontsize=11)
    ax.grid(True, alpha=0.3)

    # 中图: median_avg_wd_ratio vs median_fr (平均消费水平 vs 典型下限)
    ax = axes[1]
    sc2 = ax.scatter(
        safe["median_avg_wd_ratio"], safe["median_fr"],
        c=safe["score"], cmap="viridis", s=20, alpha=0.6, edgecolors="none",
    )
    plt.colorbar(sc2, ax=ax, label="Score")
    for _, row in top10.iterrows():
        ax.annotate(
            f"#{int(row.name)+1}",
            (row["median_avg_wd_ratio"], row["median_fr"]),
            fontsize=7, fontweight="bold", color="red",
            textcoords="offset points", xytext=(5, 5),
        )
    ax.set_xlabel("Median Avg Withdrawal Ratio", fontsize=10)
    ax.set_ylabel("Median Floor Ratio (typical min wd / initial)", fontsize=10)
    ax.set_title("Avg Consumption vs Typical Floor", fontsize=11)
    ax.grid(True, alpha=0.3)

    # 右图: median_avg_wd_ratio vs median_downside_cv (消费水平 vs 下行稳定性)
    ax = axes[2]
    sc3 = ax.scatter(
        safe["median_avg_wd_ratio"], safe["median_downside_cv"],
        c=safe["score"], cmap="viridis", s=20, alpha=0.6, edgecolors="none",
    )
    plt.colorbar(sc3, ax=ax, label="Score")
    for _, row in top10.iterrows():
        ax.annotate(
            f"#{int(row.name)+1}",
            (row["median_avg_wd_ratio"], row["median_downside_cv"]),
            fontsize=7, fontweight="bold", color="red",
            textcoords="offset points", xytext=(5, 5),
        )
    ax.set_xlabel("Median Avg Withdrawal Ratio", fontsize=10)
    ax.set_ylabel("Median Downside CV (lower = more stable)", fontsize=10)
    ax.set_title("Avg Consumption vs Downside Stability", fontsize=11)
    ax.grid(True, alpha=0.3)

    fig.suptitle(f"Pareto Analysis — {label}  (p10_funded >= {SAFETY_THRESHOLD})", fontsize=13)
    fig.tight_layout()
    fig.savefig(GUARDRAIL_OUTPUT_DIR / f"pareto_{label.lower()}.png", dpi=150)
    plt.close(fig)
    print(f"  → {GUARDRAIL_OUTPUT_DIR}/pareto_{label.lower()}.png")


def plot_heatmaps(df: pd.DataFrame, label: str = "FIRE"):
    """参数敏感性热力图：固定 best 的其他参数，展示两两参数对得分的影响。"""
    if len(df) == 0:
        return
    best = df.iloc[0]

    param_pairs = [
        ("target_success", "lower_guardrail"),
        ("target_success", "adjustment_pct"),
        ("lower_guardrail", "adjustment_pct"),
        ("adjustment_pct", "min_remaining_years"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    axes = axes.flatten()

    for idx, (p1, p2) in enumerate(param_pairs):
        ax = axes[idx]
        other_params = [k for k in PARAM_GRID.keys() if k not in (p1, p2)]
        mask = pd.Series(True, index=df.index)
        for op in other_params:
            mask &= df[op] == best[op]
        sub = df[mask].copy()

        if len(sub) == 0:
            ax.set_title(f"{p1} vs {p2}\n(no data)", fontsize=10)
            continue

        pivot = sub.pivot_table(values="score", index=p2, columns=p1, aggfunc="mean")
        im = ax.imshow(pivot.values, aspect="auto", cmap="viridis", origin="lower")
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([f"{v:.2f}" for v in pivot.columns], fontsize=8)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([f"{v}" for v in pivot.index], fontsize=8)
        ax.set_xlabel(p1, fontsize=9)
        ax.set_ylabel(p2, fontsize=9)
        ax.set_title(f"{p1} vs {p2}", fontsize=10)
        plt.colorbar(im, ax=ax, shrink=0.8)

    fig.suptitle(f"Parameter Sensitivity Heatmaps — {label}\n(other params fixed at best)", fontsize=13)
    fig.tight_layout()
    fig.savefig(GUARDRAIL_OUTPUT_DIR / f"heatmaps_{label.lower()}.png", dpi=150)
    plt.close(fig)
    print(f"  → {GUARDRAIL_OUTPUT_DIR}/heatmaps_{label.lower()}.png")


def plot_cross_validation(fire_df: pd.DataFrame, jst_df: pd.DataFrame):
    """FIRE vs JST 排名一致性图。"""
    merged = fire_df.head(20).copy()
    merged["fire_rank"] = range(1, len(merged) + 1)

    jst_scores = {}
    for _, row in jst_df.iterrows():
        key = (row["target_success"], row["upper_guardrail"], row["lower_guardrail"],
               row["adjustment_pct"], row["adjustment_mode"], row["min_remaining_years"])
        jst_scores[key] = row["score"]

    merged["jst_score"] = merged.apply(
        lambda r: jst_scores.get(
            (r["target_success"], r["upper_guardrail"], r["lower_guardrail"],
             r["adjustment_pct"], r["adjustment_mode"], r["min_remaining_years"]),
            None),
        axis=1,
    )
    merged = merged.dropna(subset=["jst_score"])
    if len(merged) == 0:
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Score comparison
    ax1.scatter(merged["score"], merged["jst_score"], s=50, alpha=0.7)
    for _, row in merged.iterrows():
        ax1.annotate(f"#{int(row['fire_rank'])}", (row["score"], row["jst_score"]),
                     fontsize=7, textcoords="offset points", xytext=(4, 4))
    lims = [
        min(merged["score"].min(), merged["jst_score"].min()) * 0.9,
        max(merged["score"].max(), merged["jst_score"].max()) * 1.1,
    ]
    ax1.plot(lims, lims, "k--", alpha=0.3)
    ax1.set_xlabel("FIRE Score", fontsize=11)
    ax1.set_ylabel("JST Score", fontsize=11)
    ax1.set_title("Score Comparison: FIRE vs JST", fontsize=12)
    ax1.grid(True, alpha=0.3)

    # Rank comparison
    jst_rank = merged["jst_score"].rank(ascending=False).astype(int)
    ax2.scatter(merged["fire_rank"], jst_rank, s=50, alpha=0.7)
    for _, row in merged.iterrows():
        ax2.annotate(f"#{int(row['fire_rank'])}", (row["fire_rank"], jst_rank.loc[row.name]),
                     fontsize=7, textcoords="offset points", xytext=(4, 4))
    ax2.plot([0, 25], [0, 25], "k--", alpha=0.3)
    ax2.set_xlabel("FIRE Rank", fontsize=11)
    ax2.set_ylabel("JST Rank", fontsize=11)
    ax2.set_title("Rank Consistency: FIRE vs JST", fontsize=12)
    ax2.grid(True, alpha=0.3)

    rho = _spearman_rho(merged["fire_rank"].values, jst_rank.values)
    fig.suptitle(f"Cross-Validation — Spearman ρ = {rho:.3f}", fontsize=13)
    fig.tight_layout()
    fig.savefig(GUARDRAIL_OUTPUT_DIR / "cross_validation.png", dpi=150)
    plt.close(fig)
    print(f"  → {GUARDRAIL_OUTPUT_DIR}/cross_validation.png")


# ═══════════════════════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════════════════════

def print_top_results(df: pd.DataFrame, label: str, n: int = 20):
    """打印 Top-N 参数组合。"""
    print(f"\n{'='*100}")
    print(f"  {label}: Top-{n} 参数组合")
    print(f"{'='*100}")

    display_cols = [
        "target_success", "upper_guardrail", "lower_guardrail",
        "adjustment_pct", "adjustment_mode", "min_remaining_years",
        "initial_rate", "initial_wd",
        "score", "success_rate", "median_funded", "p10_funded",
        "median_util", "p10_util", "median_discounted",
        "p10_floor_self", "smoothness",
        "median_avg_wd_ratio", "p10_avg_wd_ratio",
        "median_fr", "p10_fr",
        "median_downside_cv", "median_min_wd", "p10_min_wd", "median_adj",
    ]
    cols = [c for c in display_cols if c in df.columns]
    top = df.head(n)[cols].copy()

    float_cols = [c for c in cols if df[c].dtype in (np.float64, float)]
    for c in float_cols:
        top[c] = top[c].apply(lambda v: f"{v:.4f}")

    print(top.to_string(index=True))
    return top


def save_results_csv(df: pd.DataFrame, filename: str):
    """保存完整结果到 CSV。"""
    path = GUARDRAIL_OUTPUT_DIR / filename
    df.to_csv(path, index=False, float_format="%.6f")
    print(f"  → {path}")


def generate_recommendation(fire_df: pd.DataFrame, jst_df: pd.DataFrame | None = None):
    """生成最终推荐。"""
    print(f"\n{'='*100}")
    print(f"  最终推荐")
    print(f"{'='*100}")

    best = fire_df.iloc[0]
    init_rate = best.get('initial_rate', 0)
    init_wd = best.get('initial_wd', ANNUAL_WITHDRAWAL)
    print(f"\n  FIRE Dataset 最优参数:")
    print(f"    目标成功率 (target_success):     {best['target_success']:.0%}")
    print(f"    上护栏 (upper_guardrail):         {best['upper_guardrail']:.0%}")
    print(f"    下护栏 (lower_guardrail):         {best['lower_guardrail']:.0%}")
    print(f"    调整比例 (adjustment_pct):         {best['adjustment_pct']:.0%}")
    print(f"    调整模式 (adjustment_mode):        {best['adjustment_mode']}")
    print(f"    最少剩余年限 (min_remaining_years): {int(best['min_remaining_years'])}")
    print(f"    初始提取率:           {init_rate:.2%}  (${init_wd:,.0f}/年)")
    print(f"    基准提取率:           {BASELINE_RATE:.2%}  (${ANNUAL_WITHDRAWAL:,.0f}/年)")

    print(f"\n  关键指标:")
    print(f"    成功率:               {best['success_rate']:.1%}")
    print(f"    P10 Funded Ratio:     {best['p10_funded']:.4f}")
    mu = best.get('median_util', 0)
    p10u = best.get('p10_util', 0)
    md = best.get('median_discounted', 0)
    pfs = best.get('p10_floor_self', 0)
    sm = best.get('smoothness', 0)
    print(f"    中位消费率(util):     {mu:.4f}  (median avg_wd / portfolio)")
    print(f"    P10消费率(util):      {p10u:.4f}  (P10 avg_wd / portfolio)")
    print(f"    折现消费率:           {md:.4f}  (2% 年化折现)")
    print(f"    P10底线保护:          {pfs:.4f}  (P10 min_wd / initial_wd)")
    print(f"    平滑度:               {sm:.4f}  (1/(1+20*dcv))")
    print(f"    P10 最低年消费:       ${best['p10_min_wd']:,.0f}")
    print(f"    复合得分:             {best['score']:.6f}")
    print(f"    (v2: safety*[0.25*util + 0.15*p10_util + 0.20*disc + 0.20*floor + 0.20*smooth] *15)")

    if jst_df is not None and len(jst_df) > 0:
        jst_best_row = jst_df[
            (jst_df["target_success"] == best["target_success"]) &
            (jst_df["upper_guardrail"] == best["upper_guardrail"]) &
            (jst_df["lower_guardrail"] == best["lower_guardrail"]) &
            (jst_df["adjustment_pct"] == best["adjustment_pct"]) &
            (jst_df["adjustment_mode"] == best["adjustment_mode"]) &
            (jst_df["min_remaining_years"] == best["min_remaining_years"])
        ]
        if len(jst_best_row) > 0:
            jb = jst_best_row.iloc[0]
            print(f"\n  JST 交叉验证 (同一参数组合):")
            print(f"    JST 排名:             #{int(jb['jst_rank'])}")
            print(f"    JST 成功率:           {jb['success_rate']:.1%}")
            print(f"    JST P10 Funded Ratio: {jb['p10_funded']:.4f}")
            print(f"    JST 中位消费比:       {jb['median_cr']:.4f}")
            print(f"    JST 复合得分:         {jb['score']:.6f}")


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════

def generate_combined_recommendation(
    hist_df: pd.DataFrame,
    mc_df: pd.DataFrame,
    jst_df: pd.DataFrame | None = None,
):
    """综合历史回测 + MC + JST 生成最终推荐。"""
    print(f"\n{'='*100}")
    print(f"  综合推荐 (历史回测 + 蒙特卡洛 + JST 交叉验证)")
    print(f"{'='*100}")

    param_keys = list(PARAM_GRID.keys())

    def combo_key(row):
        return tuple(row[k] for k in param_keys)

    # 预构建 key → (score, rank, initial_rate) 字典，避免 O(n²) 的 apply 查找
    hist_data = {}
    for idx, (_, row) in enumerate(hist_df.iterrows()):
        hist_data[combo_key(row)] = (row["score"], idx + 1, row.get("initial_rate", 0))

    mc_data = {}
    for idx, (_, row) in enumerate(mc_df.iterrows()):
        mc_data[combo_key(row)] = (row["score"], idx + 1, row.get("initial_rate", 0))

    all_keys = set(hist_data.keys()) & set(mc_data.keys())
    combined = []
    for k in all_keys:
        hs, hr, ir = hist_data[k]
        ms, mr, _ = mc_data[k]
        if hs <= 0 or ms <= 0:
            continue
        geo = (hs * ms) ** 0.5
        combined.append({
            **dict(zip(param_keys, k)),
            "initial_rate": ir,
            "hist_score": hs, "hist_rank": hr,
            "mc_score": ms, "mc_rank": mr,
            "combined_score": geo,
        })

    cdf = pd.DataFrame(combined).sort_values("combined_score", ascending=False).reset_index(drop=True)
    cdf["combined_rank"] = range(1, len(cdf) + 1)

    print(f"\n  Top-20 (综合 = √(Hist × MC)):")
    print(f"  {'Rank':>4}  {'target':>7}  {'upper':>6}  {'lower':>6}  {'adj%':>5}  {'mode':>13}  {'min_yr':>6}  {'init%':>6}  {'Hist':>7}  {'H#':>3}  {'MC':>7}  {'M#':>3}  {'Combined':>9}")
    print(f"  {'─'*103}")
    for i, row in cdf.head(20).iterrows():
        print(f"  {row['combined_rank']:>4}  {row['target_success']:>7.0%}  {row['upper_guardrail']:>6.0%}  {row['lower_guardrail']:>6.0%}"
              f"  {row['adjustment_pct']:>5.0%}  {row['adjustment_mode']:>13}  {int(row['min_remaining_years']):>6}"
              f"  {row['initial_rate']:>5.1%}"
              f"  {row['hist_score']:>7.4f}  {int(row['hist_rank']):>3}  {row['mc_score']:>7.4f}  {int(row['mc_rank']):>3}"
              f"  {row['combined_score']:>9.4f}")

    # 如果有 JST 数据，也纳入三路综合
    if jst_df is not None and len(jst_df) > 0:
        jst_scores = {}
        for _, row in jst_df.iterrows():
            k = combo_key(row)
            jst_scores[k] = row["score"]

        print(f"\n  Top-20 加入 JST (综合 = (Hist × MC × JST)^(1/3)):")
        print(f"  {'Rank':>4}  {'target':>7}  {'upper':>6}  {'lower':>6}  {'adj%':>5}  {'mode':>13}  {'min_yr':>6}"
              f"  {'Hist':>7}  {'MC':>7}  {'JST':>7}  {'3-way':>9}")
        print(f"  {'─'*100}")
        three_way = []
        for _, row in cdf.head(20).iterrows():
            k = combo_key(row)
            js = jst_scores.get(k)
            if js is not None and js > 0:
                tw = (row["hist_score"] * row["mc_score"] * js) ** (1.0 / 3.0)
            else:
                tw = None
            three_way.append({**row.to_dict(), "jst_score": js, "three_way": tw})

        tw_df = pd.DataFrame(three_way)
        tw_df = tw_df.dropna(subset=["three_way"]).sort_values("three_way", ascending=False).reset_index(drop=True)
        for i, row in tw_df.iterrows():
            print(f"  {i+1:>4}  {row['target_success']:>7.0%}  {row['upper_guardrail']:>6.0%}  {row['lower_guardrail']:>6.0%}"
                  f"  {row['adjustment_pct']:>5.0%}  {row['adjustment_mode']:>13}  {int(row['min_remaining_years']):>6}"
                  f"  {row['hist_score']:>7.4f}  {row['mc_score']:>7.4f}  {row['jst_score']:>7.4f}  {row['three_way']:>9.4f}")

    # 最终推荐（含关键指标）
    best = cdf.iloc[0]
    best_key = combo_key(best)
    print(f"\n  ★ 综合最优参数 (Hist + MC):")
    print(f"    目标成功率:     {best['target_success']:.0%}")
    print(f"    上护栏:         {best['upper_guardrail']:.0%}")
    print(f"    下护栏:         {best['lower_guardrail']:.0%}")
    print(f"    调整比例:       {best['adjustment_pct']:.0%}")
    print(f"    调整模式:       {best['adjustment_mode']}")
    print(f"    最少剩余年限:   {int(best['min_remaining_years'])}")
    print(f"    Hist 得分/排名: {best['hist_score']:.4f} / #{int(best['hist_rank'])}")
    print(f"    MC 得分/排名:   {best['mc_score']:.4f} / #{int(best['mc_rank'])}")
    print(f"    综合得分:       {best['combined_score']:.4f}")

    # 从预构建的详细指标字典取出最优参数的详情
    hist_details = {combo_key(row): row for _, row in hist_df.iterrows()}
    mc_details = {combo_key(row): row for _, row in mc_df.iterrows()}
    for src_label, details in [("Hist", hist_details), ("MC", mc_details)]:
        m = details.get(best_key)
        if m is not None:
            init_r = m.get("initial_rate", 0)
            init_w = m.get("initial_wd", 0)
            mu = m.get("median_util", 0)
            p10u = m.get("p10_util", 0)
            md = m.get("median_discounted", 0)
            pfs = m.get("p10_floor_self", 0)
            sm = m.get("smoothness", 0)
            print(f"\n    [{src_label}] init_rate={init_r:.2%} (${init_w:,.0f}/yr)  "
                  f"P10_funded={m['p10_funded']:.3f}  "
                  f"util={mu:.4f}  p10_util={p10u:.4f}  disc={md:.4f}  "
                  f"floor_self={pfs:.3f}  smooth={sm:.3f}  "
                  f"p10_min_wd=${m['p10_min_wd']:,.0f}")

    save_results_csv(cdf.head(50), "combined_top50.csv")
    return cdf


def prepare_jst_intl_scenarios(data_start_year: int = 1970) -> np.ndarray:
    """用 JST 多国数据池化生成 MC scenarios（真正的国际化数据）。"""
    jst_df = load_returns_data()
    country_dfs = get_country_dfs(jst_df, data_start_year)
    all_returns = []
    for iso, cdf in country_dfs.items():
        cdf_sorted = cdf.sort_values("Year").reset_index(drop=True)
        real_ret = compute_real_portfolio_returns(cdf_sorted, ALLOCATION, EXPENSE_RATIOS)
        all_returns.extend(real_ret.tolist())

    pooled_df = pd.DataFrame({"Year": range(len(all_returns)), "real_return": all_returns})

    rng = np.random.default_rng(SEED + 1)
    n_pool = len(all_returns)
    scenarios = np.zeros((NUM_SIMULATIONS, RETIREMENT_YEARS))
    for i in range(NUM_SIMULATIONS):
        block_len = rng.integers(MIN_BLOCK, MAX_BLOCK + 1)
        idx = []
        while len(idx) < RETIREMENT_YEARS:
            start = rng.integers(0, max(1, n_pool - block_len))
            idx.extend(range(start, min(start + block_len, n_pool)))
        scenarios[i] = np.array(all_returns)[idx[:RETIREMENT_YEARS]]
    return scenarios


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  风险护栏策略参数优化分析 (加权Geo3: US-Std+MC1970+JST-MC)    ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    combos = generate_valid_combos(PARAM_GRID)
    print(f"\n有效参数组合数: {len(combos)}")

    # ── 第一阶段: FIRE Dataset (美国历史 + 美国MC) ──
    fire_df_raw = load_fire_dataset()
    fire_filtered = filter_by_country(fire_df_raw, "USA", DATA_START_YEAR)
    hist_results, mc_results, rate_grid_fire, table_fire = run_grid_search(
        fire_filtered, label="FIRE", combos=combos, mode="both",
    )

    print_top_results(hist_results, "FIRE-Historical", n=20)
    save_results_csv(hist_results, "fire_hist_results.csv")
    plot_pareto(hist_results, "FIRE-Hist")
    plot_heatmaps(hist_results, "FIRE-Hist")

    print_top_results(mc_results, "FIRE-MonteCarlo", n=20)
    save_results_csv(mc_results, "fire_mc_results.csv")
    plot_pareto(mc_results, "FIRE-MC")
    plot_heatmaps(mc_results, "FIRE-MC")

    # ── 第二阶段: FIRE 1970+ MC (美国数据，起始年1970，国内股票费率2.5%) ──
    mc1970_expense = {"domestic_stock": 0.025, "global_stock": 0.005}
    fire_1970 = filter_by_country(fire_df_raw, "USA", 1970)
    _, mc_1970_results, _, _ = run_grid_search(
        fire_1970, label="FIRE-1970", combos=combos, mode="mc",
        expense_ratios=mc1970_expense,
    )

    print_top_results(mc_1970_results, "FIRE-MC-1970 (美国 1970+, 国内费率2.5%)", n=20)
    save_results_csv(mc_1970_results, "fire_mc_1970_results.csv")
    plot_pareto(mc_1970_results, "FIRE-MC-1970")
    plot_heatmaps(mc_1970_results, "FIRE-MC-1970")

    # ── 第2.5阶段: JST 多国池化 MC 全量搜索 ──
    print(f"\n{'='*60}")
    print(f"  JST-MC: 准备数据 (多国池化 Block Bootstrap)")
    print(f"{'='*60}")
    t0 = time.time()
    jst_mc_scenarios = prepare_jst_intl_scenarios(data_start_year=DATA_START_YEAR)
    print(f"  JST MC scenarios: {jst_mc_scenarios.shape} ({time.time()-t0:.1f}s)")

    t0 = time.time()
    jst_rate_grid, jst_table = build_success_rate_table(jst_mc_scenarios)
    print(f"  JST 查找表: {jst_table.shape}, rate_grid: [{jst_rate_grid[0]:.3f}, {jst_rate_grid[-1]:.3f}] ({time.time()-t0:.1f}s)")

    print(f"  JST MC 路径: {jst_mc_scenarios.shape[0]} 条 (全部完整)")
    jst_mc_results = _run_mc_search(jst_mc_scenarios, jst_table, jst_rate_grid, combos, "JST-MC")

    print_top_results(jst_mc_results, "JST-MC (多国池化)", n=20)
    save_results_csv(jst_mc_results, "jst_mc_results.csv")
    plot_pareto(jst_mc_results, "JST-MC")
    plot_heatmaps(jst_mc_results, "JST-MC")

    # ── 第三阶段: JST 历史回测交叉验证 (用综合 top-20) ──
    param_keys = list(PARAM_GRID.keys())

    def _build_score_map(df):
        return {tuple(row[k] for k in param_keys): row["score"]
                for row in df.to_dict("records")}

    hist_map = _build_score_map(hist_results)
    mc_map = _build_score_map(mc_results)
    pre_combined = []
    for k in set(hist_map.keys()) & set(mc_map.keys()):
        hs, ms = hist_map[k], mc_map[k]
        if hs > 0 and ms > 0:
            pre_combined.append({**dict(zip(param_keys, k)), "geo": (hs * ms) ** 0.5})
    pre_cdf = pd.DataFrame(pre_combined).sort_values("geo", ascending=False)
    top_combos = pre_cdf.head(20)[param_keys].to_dict("records")

    jst_results = run_jst_cross_validation(top_combos, n_top=20, rank_col="combined_rank")

    print_top_results(jst_results, "JST Cross-Validation (Hist)", n=20)
    save_results_csv(jst_results, "jst_cross_validation.csv")

    # ── 第四阶段: 综合推荐 ──
    generate_combined_recommendation(hist_results, mc_results, jst_results)

    # 加权 Geo3 综合分析
    # US-Std = sqrt(Hist × MC) 合并冗余维度，再与 MC1970、JST-MC 等权几何均值
    # 等价权重: Hist^(1/6) × MC^(1/6) × MC1970^(1/3) × JST-MC^(1/3)
    print(f"\n{'='*100}")
    print(f"  加权 Geo3 综合分析: US-Std(Hist+MC) / US-MC-1970 / JST-MC")
    print(f"  权重: US-Std=1/3 (Hist+MC合并), MC1970=1/3, JST-MC=1/3")
    print(f"{'='*100}")

    mc70_map = _build_score_map(mc_1970_results)
    jst_mc_map = _build_score_map(jst_mc_results)
    jst_cv_map = _build_score_map(jst_results)

    combined = []
    all_keys = set(hist_map.keys()) & set(mc_map.keys()) & set(mc70_map.keys()) & set(jst_mc_map.keys())
    for k in all_keys:
        hs, ms, m70, jm = hist_map[k], mc_map[k], mc70_map[k], jst_mc_map[k]
        jcs = jst_cv_map.get(k)
        if hs <= 0 or ms <= 0 or m70 <= 0 or jm <= 0:
            continue
        us_std = (hs * ms) ** 0.5
        wgeo3 = (us_std * m70 * jm) ** (1.0 / 3.0)
        combined.append({
            **dict(zip(param_keys, k)),
            "hist_score": hs,
            "mc_score": ms,
            "us_std_score": us_std,
            "mc_1970_score": m70,
            "jst_mc_score": jm,
            "jst_cv_score": jcs,
            "wgeo3_score": wgeo3,
        })

    fw_df = pd.DataFrame(combined).sort_values("wgeo3_score", ascending=False).reset_index(drop=True)

    print(f"\n  Top-30 (加权 Geo3 = (US-Std × MC1970 × JST-MC) ^ 1/3):")
    print(f"  {'#':>3}  {'target':>7}  {'upper':>6}  {'lower':>6}  {'adj%':>5}  {'mode':>13}  {'mr':>3}"
          f"  {'US-Std':>8}  {'MC70':>8}  {'JST-MC':>8}  {'JST-CV':>8}  {'WGeo3':>8}")
    print(f"  {'─'*112}")
    for i, row in fw_df.head(30).iterrows():
        jcv = f"{row['jst_cv_score']:.4f}" if row['jst_cv_score'] is not None and not pd.isna(row.get('jst_cv_score')) else "   N/A"
        print(f"  {i+1:>3}  {row['target_success']:>7.0%}  {row['upper_guardrail']:>6.0%}  {row['lower_guardrail']:>6.0%}"
              f"  {row['adjustment_pct']:>5.0%}  {row['adjustment_mode']:>13}  {int(row['min_remaining_years']):>3}"
              f"  {row['us_std_score']:>8.4f}  {row['mc_1970_score']:>8.4f}  {row['jst_mc_score']:>8.4f}  {jcv:>8}  {row['wgeo3_score']:>8.4f}")

    save_results_csv(fw_df.head(50), "weighted_geo3_top50.csv")

    # 按 target_success 分组展示最优
    print(f"\n  按 target_success 分组最优:")
    print(f"  {'target':>7}  {'lower':>6}  {'adj%':>5}  {'mode':>13}  {'mr':>3}  {'US-Std':>8}  {'MC70':>8}  {'JST-MC':>8}  {'WGeo3':>8}")
    print(f"  {'─'*90}")
    for ts in sorted(fw_df['target_success'].unique()):
        sub = fw_df[fw_df['target_success'] == ts]
        if len(sub) == 0:
            continue
        best = sub.iloc[0]
        print(f"  {best['target_success']:>7.0%}  {best['lower_guardrail']:>6.0%}  {best['adjustment_pct']:>5.0%}"
              f"  {best['adjustment_mode']:>13}  {int(best['min_remaining_years']):>3}"
              f"  {best['us_std_score']:>8.4f}  {best['mc_1970_score']:>8.4f}  {best['jst_mc_score']:>8.4f}  {best['wgeo3_score']:>8.4f}")

    print(f"\n所有输出保存在: {GUARDRAIL_OUTPUT_DIR}/")
    print("完成！")


if __name__ == "__main__":
    main()
