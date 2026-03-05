"""三种提取策略综合对比分析。

对比固定提取、Vanguard 动态提取、风险护栏三种策略，
使用同一评分体系（v2 五维评分）和多数据源（FIRE Hist/MC, MC-1970, JST-MC）。
"""

import sys
import time
import itertools
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

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
from simulator.guardrail import build_success_rate_table
from simulator.statistics import CONSUMPTION_FLOOR

from guardrail_optimization import (
    INITIAL_PORTFOLIO,
    RETIREMENT_YEARS,
    ALLOCATION,
    EXPENSE_RATIOS,
    BASELINE_RATE,
    MIN_BLOCK,
    MAX_BLOCK,
    NUM_SIMULATIONS,
    DATA_START_YEAR,
    SEED,
    SAFETY_THRESHOLD,
    OUTPUT_DIR,
    GUARDRAIL_OUTPUT_DIR,
    prepare_scenarios,
    prepare_historical_paths,
    prepare_jst_intl_scenarios,
    _compute_initial_wd,
    evaluate_combo_mc_fast,
    PARAM_GRID,
    generate_valid_combos,
    compute_v3_score,
    compute_cew,
    compute_max_drawdown,
)

SCORE_SCALE = 15.0

STRAT_OUTPUT_DIR = OUTPUT_DIR / "strategy_comparison"
STRAT_OUTPUT_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# 通用指标聚合（从 withdrawal 矩阵计算 v2 评分）
# ═══════════════════════════════════════════════════════════════════════════

def _aggregate_metrics(
    wds_arr: np.ndarray,
    scenarios: np.ndarray,
    initial_wd: float,
    initial_rate: float,
    combo: dict,
) -> dict:
    """从 withdrawal 矩阵 + return 矩阵聚合所有 v2 评分指标。

    Parameters
    ----------
    wds_arr : (n_sims, n_years) 每期提取金额
    scenarios : (n_sims, n_years) 实际回报率
    initial_wd : 初始年提取金额
    initial_rate : 初始提取率
    combo : 参数字典（会被合并到结果中）
    """
    n_sims, n_years = wds_arr.shape

    # 模拟组合价值轨迹
    values = np.full(n_sims, float(INITIAL_PORTFOLIO))
    depletion_year = np.full(n_sims, float(n_years))
    depleted = np.zeros(n_sims, dtype=bool)
    eff_depletion = np.full(n_sims, float(n_years))
    eff_depleted = np.zeros(n_sims, dtype=bool)
    consumption_floor_val = CONSUMPTION_FLOOR * initial_wd

    # 实际提取（耗尽后为 0）
    actual_wds = np.copy(wds_arr)

    for year in range(n_years):
        alive = values > 0
        actual_wds[:, year] = np.where(alive, wds_arr[:, year], 0.0)

        # 消费地板检测
        newly_eff = alive & (~eff_depleted) & (wds_arr[:, year] < consumption_floor_val)
        eff_depletion[newly_eff] = year
        eff_depleted |= newly_eff

        values = values * (1.0 + scenarios[:, year]) - actual_wds[:, year]
        newly_depleted = (~depleted) & (values <= 0)
        depletion_year[newly_depleted] = year + 1
        depleted |= values <= 0
        values = np.maximum(values, 0.0)

    combined_depletion = np.minimum(depletion_year, eff_depletion)
    g_survived = combined_depletion >= n_years
    g_funded = np.minimum(combined_depletion / RETIREMENT_YEARS, 1.0)

    g_min_wd = actual_wds.min(axis=1)
    g_mean_wd = actual_wds.mean(axis=1)
    g_std_wd = actual_wds.std(axis=1)
    g_cv = np.where(g_mean_wd > 0, g_std_wd / g_mean_wd, 999.0)
    g_total = actual_wds.sum(axis=1)

    wd_changes = np.diff(actual_wds, axis=1)
    neg_changes = np.minimum(wd_changes, 0.0)
    downside_sd = np.sqrt(np.mean(neg_changes ** 2, axis=1))
    g_downside_cv = np.where(g_mean_wd > 0, downside_sd / g_mean_wd, 999.0)

    # baseline (固定 BASELINE_RATE 提取)
    b_wd_fixed = float(INITIAL_PORTFOLIO * BASELINE_RATE)
    b_values = np.full(n_sims, float(INITIAL_PORTFOLIO))
    b_total = np.zeros(n_sims)
    for year in range(n_years):
        wd = np.where(b_values > 0, b_wd_fixed, 0.0)
        b_total += wd
        b_values = b_values * (1.0 + scenarios[:, year]) - wd
        b_values = np.maximum(b_values, 0.0)

    cr = np.where(b_total > 0, g_total / b_total, 0.0)
    fr = g_min_wd / initial_wd
    avg_wd_ratio = g_mean_wd / initial_wd

    discount_factors = 1.0 / (1.02 ** np.arange(n_years))
    discount_weights = discount_factors / discount_factors.sum()
    discounted_wd = (actual_wds * discount_weights[np.newaxis, :]).sum(axis=1)

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

    median_util = float(np.median(g_mean_wd)) / INITIAL_PORTFOLIO
    p10_util = float(np.percentile(g_mean_wd, 10)) / INITIAL_PORTFOLIO
    median_discounted = float(np.median(discounted_wd)) / INITIAL_PORTFOLIO

    p10_floor_self = float(np.percentile(g_min_wd / initial_wd, 10))
    p10_floor_self = min(p10_floor_self, 1.0)

    # v3 新指标
    cew_per_path = compute_cew(actual_wds)
    median_cew = float(np.median(cew_per_path)) / INITIAL_PORTFOLIO
    max_dd_per_path = compute_max_drawdown(actual_wds)
    p90_max_drawdown = float(np.percentile(max_dd_per_path, 90))
    below_floor = actual_wds < consumption_floor_val
    years_below = below_floor.sum(axis=1)
    p90_years_below_ratio = float(np.percentile(years_below / n_years, 90))
    p10_floor_abs = min(p10_min_wd / (INITIAL_PORTFOLIO * BASELINE_RATE), 1.0)

    # v2 评分（向后兼容）
    safety = p10_funded ** 2
    smoothness = 1.0 / (1.0 + 20.0 * median_downside_cv)
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
# 固定提取策略
# ═══════════════════════════════════════════════════════════════════════════

FIXED_GRID = {
    "withdrawal_rate": np.round(np.arange(0.020, 0.081, 0.001), 4).tolist(),
}


def evaluate_fixed(rate: float, scenarios: np.ndarray) -> dict:
    """向量化评估固定提取策略。"""
    n_sims, n_years = scenarios.shape
    initial_wd = INITIAL_PORTFOLIO * rate
    wds_arr = np.full((n_sims, n_years), initial_wd)
    combo = {"strategy": "fixed", "withdrawal_rate": rate}
    return _aggregate_metrics(wds_arr, scenarios, initial_wd, rate, combo)


def search_fixed(scenarios: np.ndarray, label: str) -> pd.DataFrame:
    """网格搜索固定提取策略。"""
    rates = FIXED_GRID["withdrawal_rate"]
    print(f"\n  [{label}] 固定策略搜索: {len(rates)} 个提取率...")
    t0 = time.time()
    results = []
    for rate in rates:
        r = evaluate_fixed(rate, scenarios)
        results.append(r)
    df = pd.DataFrame(results).sort_values("score", ascending=False).reset_index(drop=True)
    print(f"    完成 ({time.time()-t0:.1f}s)")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# Vanguard 动态提取策略
# ═══════════════════════════════════════════════════════════════════════════

DYNAMIC_GRID = {
    "withdrawal_rate": np.round(np.arange(0.020, 0.081, 0.005), 4).tolist(),
    "dynamic_ceiling": [0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20],
    "dynamic_floor": [0.01, 0.02, 0.025, 0.03, 0.05, 0.07, 0.10],
}


def evaluate_dynamic(
    rate: float,
    ceiling: float,
    floor: float,
    scenarios: np.ndarray,
) -> dict:
    """向量化评估 Vanguard 动态提取策略。"""
    n_sims, n_years = scenarios.shape
    initial_wd = INITIAL_PORTFOLIO * rate

    wds = np.full(n_sims, initial_wd)
    wds_arr = np.zeros((n_sims, n_years))

    for year in range(n_years):
        wds_arr[:, year] = wds
        # 用下一年初组合价值更新（但这里先记录本年提取）
        # 提取后的组合价值在 _aggregate_metrics 中计算
        # 这里需要跟踪组合价值以计算下一年的目标提取
        if year == 0:
            # 第一年已经设置好了，需要跟踪组合价值
            pass
        # 价值更新放在下面统一处理

    # 需要完整模拟以跟踪动态调整
    values = np.full(n_sims, float(INITIAL_PORTFOLIO))
    wds = np.full(n_sims, initial_wd)
    wds_arr = np.zeros((n_sims, n_years))

    for year in range(n_years):
        if year > 0:
            alive = values > 0
            target = values * rate
            upper = wds * (1.0 + ceiling)
            lower = wds * (1.0 - floor)
            new_wds = np.clip(target, lower, upper)
            wds = np.where(alive, new_wds, wds)

        wds_arr[:, year] = wds
        values = values * (1.0 + scenarios[:, year]) - wds
        values = np.maximum(values, 0.0)

    combo = {
        "strategy": "dynamic",
        "withdrawal_rate": rate,
        "dynamic_ceiling": ceiling,
        "dynamic_floor": floor,
    }
    # 重新计算指标（用 wds_arr 和原始 scenarios）
    return _aggregate_metrics(wds_arr, scenarios, initial_wd, rate, combo)


def search_dynamic(scenarios: np.ndarray, label: str) -> pd.DataFrame:
    """网格搜索 Vanguard 动态提取策略。"""
    rates = DYNAMIC_GRID["withdrawal_rate"]
    ceilings = DYNAMIC_GRID["dynamic_ceiling"]
    floors = DYNAMIC_GRID["dynamic_floor"]
    combos = list(itertools.product(rates, ceilings, floors))
    print(f"\n  [{label}] 动态策略搜索: {len(combos)} 个组合...")
    t0 = time.time()
    results = []
    for i, (rate, ceiling, floor) in enumerate(combos):
        r = evaluate_dynamic(rate, ceiling, floor, scenarios)
        results.append(r)
        if (i + 1) % 200 == 0 or i == len(combos) - 1:
            elapsed = time.time() - t0
            speed = (i + 1) / elapsed
            eta = (len(combos) - i - 1) / speed if speed > 0 else 0
            print(f"    [{i+1}/{len(combos)}]  {speed:.0f} combo/s  ETA: {eta:.0f}s")
    df = pd.DataFrame(results).sort_values("score", ascending=False).reset_index(drop=True)
    print(f"    完成 ({time.time()-t0:.1f}s)")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# 护栏策略（复用现有框架）
# ═══════════════════════════════════════════════════════════════════════════

def search_guardrail(
    scenarios: np.ndarray,
    table: np.ndarray,
    rate_grid: np.ndarray,
    label: str,
    combos: list[dict] | None = None,
) -> pd.DataFrame:
    """网格搜索护栏策略。"""
    if combos is None:
        combos = generate_valid_combos(PARAM_GRID)
    print(f"\n  [{label}] 护栏策略搜索: {len(combos)} 个组合...")
    t0 = time.time()
    results = []
    for i, combo in enumerate(combos):
        r = evaluate_combo_mc_fast(combo, scenarios, table, rate_grid)
        r["strategy"] = "guardrail"
        results.append(r)
        if (i + 1) % 500 == 0 or i == len(combos) - 1:
            elapsed = time.time() - t0
            speed = (i + 1) / elapsed
            eta = (len(combos) - i - 1) / speed if speed > 0 else 0
            print(f"    [{i+1}/{len(combos)}]  {speed:.0f} combo/s  ETA: {eta:.0f}s")
    df = pd.DataFrame(results).sort_values("score", ascending=False).reset_index(drop=True)
    print(f"    完成 ({time.time()-t0:.1f}s)")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# 多数据源综合搜索
# ═══════════════════════════════════════════════════════════════════════════

def run_all_sources():
    """在 4 个数据源上搜索全部三种策略，返回综合排名。"""
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  三种提取策略综合对比分析                                     ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # ── 数据准备 ──
    fire_df_raw = load_fire_dataset()
    fire_filtered = filter_by_country(fire_df_raw, "USA", DATA_START_YEAR)

    print("\n── 数据源 1: FIRE Hist (USA 1926+) ──")
    t0 = time.time()
    hist_paths = prepare_historical_paths(fire_filtered)
    complete_paths = [p for p in hist_paths if p["is_complete"]]
    hist_scenarios = np.array([p["real_returns"] for p in complete_paths])
    print(f"  历史路径: {len(hist_paths)} 条 (完整: {len(complete_paths)}) ({time.time()-t0:.1f}s)")

    print("\n── 数据源 2: FIRE MC (USA 1926+, 2000 paths) ──")
    t0 = time.time()
    mc_scenarios = prepare_scenarios(fire_filtered)
    print(f"  MC scenarios: {mc_scenarios.shape} ({time.time()-t0:.1f}s)")

    print("\n── 数据源 3: MC-1970 (USA 1970+, 国内费率 2.5%) ──")
    mc1970_expense = {"domestic_stock": 0.025, "global_stock": 0.005}
    fire_1970 = filter_by_country(fire_df_raw, "USA", 1970)
    t0 = time.time()
    mc1970_scenarios = prepare_scenarios(fire_1970, expense_ratios=mc1970_expense)
    print(f"  MC-1970 scenarios: {mc1970_scenarios.shape} ({time.time()-t0:.1f}s)")

    print("\n── 数据源 4: JST-MC (多国池化 1926+) ──")
    t0 = time.time()
    jst_scenarios = prepare_jst_intl_scenarios(data_start_year=DATA_START_YEAR)
    print(f"  JST MC scenarios: {jst_scenarios.shape} ({time.time()-t0:.1f}s)")

    # 护栏查找表
    all_scenarios = {
        "hist": hist_scenarios,
        "mc": mc_scenarios,
        "mc1970": mc1970_scenarios,
        "jst": jst_scenarios,
    }

    tables = {}
    for key, sc in all_scenarios.items():
        t0 = time.time()
        rg, tb = build_success_rate_table(sc)
        tables[key] = (rg, tb)
        print(f"  {key} 查找表: {tb.shape} ({time.time()-t0:.1f}s)")

    guardrail_combos = generate_valid_combos(PARAM_GRID)
    print(f"\n  护栏有效组合数: {len(guardrail_combos)}")

    # ── 搜索 ──
    source_labels = ["hist", "mc", "mc1970", "jst"]
    source_names = {
        "hist": "FIRE-Hist",
        "mc": "FIRE-MC",
        "mc1970": "MC-1970",
        "jst": "JST-MC",
    }

    all_fixed = {}
    all_dynamic = {}
    all_guardrail = {}

    for key in source_labels:
        sc = all_scenarios[key]
        lbl = source_names[key]
        all_fixed[key] = search_fixed(sc, lbl)
        all_dynamic[key] = search_dynamic(sc, lbl)
        rg, tb = tables[key]
        all_guardrail[key] = search_guardrail(sc, tb, rg, lbl, combos=guardrail_combos)

    return all_fixed, all_dynamic, all_guardrail, source_labels, source_names


def compute_weighted_geo3(dfs_by_source: dict, source_labels: list, key_cols: list) -> pd.DataFrame:
    """计算加权 Geo3 综合排名。

    权重: US-Std(hist+mc)=1/3, MC1970=1/3, JST-MC=1/3
    US-Std = sqrt(hist * mc)
    """
    score_maps = {}
    for key in source_labels:
        df = dfs_by_source[key]
        smap = {}
        for _, row in df.iterrows():
            k = tuple(row[c] for c in key_cols)
            smap[k] = row["score"]
        score_maps[key] = smap

    all_keys = set(score_maps["hist"].keys())
    for key in source_labels:
        all_keys &= set(score_maps[key].keys())

    results = []
    for k in all_keys:
        scores = {key: score_maps[key][k] for key in source_labels}
        if any(s <= 0 for s in scores.values()):
            continue
        us_std = (scores["hist"] * scores["mc"]) ** 0.5
        wgeo3 = (us_std * scores["mc1970"] * scores["jst"]) ** (1.0 / 3.0)
        results.append({
            **dict(zip(key_cols, k)),
            "hist_score": scores["hist"],
            "mc_score": scores["mc"],
            "us_std_score": us_std,
            "mc1970_score": scores["mc1970"],
            "jst_score": scores["jst"],
            "wgeo3_score": wgeo3,
        })

    df = pd.DataFrame(results).sort_values("wgeo3_score", ascending=False).reset_index(drop=True)
    return df


def build_detail_maps(dfs_by_source: dict, key_cols: list) -> dict:
    """为每个数据源构建 key -> row 映射（用于取最优组合的详细指标）。"""
    detail_maps = {}
    for key, df in dfs_by_source.items():
        dmap = {}
        for _, row in df.iterrows():
            k = tuple(row[c] for c in key_cols)
            dmap[k] = row
        detail_maps[key] = dmap
    return detail_maps


# ═══════════════════════════════════════════════════════════════════════════
# 可视化
# ═══════════════════════════════════════════════════════════════════════════

def plot_radar(strategies: list[dict], filename: str = "strategy_radar.png"):
    """三策略雷达图对比。"""
    dims = ["success_rate", "p10_funded", "median_util", "p10_floor_self", "smoothness", "median_discounted"]
    dim_labels = ["成功率", "P10资金覆盖", "中位消费率", "P10底线保护", "平滑度", "折现消费率"]
    n = len(dims)

    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
    colors = ["#2196F3", "#FF9800", "#4CAF50"]
    strategy_names = [s["label"] for s in strategies]

    for i, s in enumerate(strategies):
        values = [s.get(d, 0) for d in dims]
        values += values[:1]
        ax.plot(angles, values, "o-", linewidth=2, color=colors[i], label=strategy_names[i])
        ax.fill(angles, values, alpha=0.1, color=colors[i])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dim_labels, fontsize=10)
    ax.set_ylim(0, 1.05)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=10)
    ax.set_title("三策略核心指标雷达图", fontsize=14, pad=20)
    fig.tight_layout()
    fig.savefig(STRAT_OUTPUT_DIR / filename, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {STRAT_OUTPUT_DIR}/{filename}")


def plot_pareto_comparison(
    fixed_df: pd.DataFrame,
    dynamic_df: pd.DataFrame,
    guardrail_df: pd.DataFrame,
    filename: str = "strategy_pareto.png",
):
    """三策略 Pareto 前沿图。"""
    fig, axes = plt.subplots(1, 2, figsize=(18, 7))
    datasets = [
        (fixed_df, "固定提取", "#2196F3", "o"),
        (dynamic_df, "Vanguard 动态", "#FF9800", "s"),
        (guardrail_df, "风险护栏", "#4CAF50", "^"),
    ]

    ax = axes[0]
    for df, name, color, marker in datasets:
        safe = df[df["p10_funded"] >= 0.80]
        if len(safe) == 0:
            safe = df.head(30)
        top = safe.nlargest(min(50, len(safe)), "score")
        ax.scatter(
            top["median_util"], top["p10_floor_self"],
            c=color, s=40, alpha=0.6, marker=marker, label=name, edgecolors="none",
        )
        best = top.iloc[0] if len(top) > 0 else None
        if best is not None:
            ax.annotate(
                f"★ {name}",
                (best["median_util"], best["p10_floor_self"]),
                fontsize=8, fontweight="bold", color=color,
                textcoords="offset points", xytext=(8, 8),
            )
    ax.set_xlabel("中位消费率 (Median Util)", fontsize=11)
    ax.set_ylabel("P10 底线保护 (P10 Floor Self)", fontsize=11)
    ax.set_title("消费效率 vs 底线保护", fontsize=12)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    for df, name, color, marker in datasets:
        safe = df[df["p10_funded"] >= 0.80]
        if len(safe) == 0:
            safe = df.head(30)
        top = safe.nlargest(min(50, len(safe)), "score")
        ax.scatter(
            top["median_util"], top["smoothness"],
            c=color, s=40, alpha=0.6, marker=marker, label=name, edgecolors="none",
        )
        best = top.iloc[0] if len(top) > 0 else None
        if best is not None:
            ax.annotate(
                f"★ {name}",
                (best["median_util"], best["smoothness"]),
                fontsize=8, fontweight="bold", color=color,
                textcoords="offset points", xytext=(8, 8),
            )
    ax.set_xlabel("中位消费率 (Median Util)", fontsize=11)
    ax.set_ylabel("平滑度 (Smoothness)", fontsize=11)
    ax.set_title("消费效率 vs 平滑度", fontsize=12)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.suptitle("三策略 Pareto 前沿对比", fontsize=14)
    fig.tight_layout()
    fig.savefig(STRAT_OUTPUT_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"  → {STRAT_OUTPUT_DIR}/{filename}")


def plot_sensitivity(
    fixed_df: pd.DataFrame,
    dynamic_df: pd.DataFrame,
    guardrail_df: pd.DataFrame,
    filename: str = "strategy_sensitivity.png",
):
    """三策略核心参数敏感性图。"""
    fig, axes = plt.subplots(2, 3, figsize=(20, 12))

    # 固定策略: withdrawal_rate vs score
    ax = axes[0, 0]
    ax.plot(fixed_df["withdrawal_rate"] * 100, fixed_df["score"], "b-o", markersize=3)
    best = fixed_df.iloc[0]
    ax.axvline(best["withdrawal_rate"] * 100, color="red", linestyle="--", alpha=0.5)
    ax.set_xlabel("提取率 (%)")
    ax.set_ylabel("Score")
    ax.set_title(f"固定策略: 提取率 vs Score\n最优: {best['withdrawal_rate']:.1%}")
    ax.grid(True, alpha=0.3)

    # 固定策略: withdrawal_rate vs 各指标
    ax = axes[0, 1]
    sorted_f = fixed_df.sort_values("withdrawal_rate")
    ax.plot(sorted_f["withdrawal_rate"] * 100, sorted_f["success_rate"], "g-", label="成功率")
    ax.plot(sorted_f["withdrawal_rate"] * 100, sorted_f["p10_funded"], "r-", label="P10 Funded")
    ax.plot(sorted_f["withdrawal_rate"] * 100, sorted_f["p10_floor_self"], "m-", label="P10 Floor")
    ax.set_xlabel("提取率 (%)")
    ax.set_ylabel("比率")
    ax.set_title("固定策略: 提取率 vs 安全指标")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # 动态策略: withdrawal_rate vs score (按最优 ceiling/floor)
    ax = axes[0, 2]
    dyn_best_by_rate = dynamic_df.loc[
        dynamic_df.groupby("withdrawal_rate")["score"].idxmax()
    ].sort_values("withdrawal_rate")
    ax.plot(dyn_best_by_rate["withdrawal_rate"] * 100, dyn_best_by_rate["score"], "o-",
            color="#FF9800", markersize=4)
    dyn_best = dynamic_df.iloc[0]
    ax.axvline(dyn_best["withdrawal_rate"] * 100, color="red", linestyle="--", alpha=0.5)
    ax.set_xlabel("提取率 (%)")
    ax.set_ylabel("Score")
    ax.set_title(f"动态策略: 提取率 vs 最优Score\n最优: {dyn_best['withdrawal_rate']:.1%}")
    ax.grid(True, alpha=0.3)

    # 动态策略: ceiling vs floor 热力图 (最优 rate)
    ax = axes[1, 0]
    best_rate = dyn_best["withdrawal_rate"]
    sub = dynamic_df[dynamic_df["withdrawal_rate"] == best_rate]
    if len(sub) > 1:
        pivot = sub.pivot_table(values="score", index="dynamic_floor", columns="dynamic_ceiling")
        im = ax.imshow(pivot.values, aspect="auto", cmap="viridis", origin="lower")
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([f"{v:.0%}" for v in pivot.columns], fontsize=8)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([f"{v:.1%}" for v in pivot.index], fontsize=8)
        ax.set_xlabel("Ceiling (上调上限)")
        ax.set_ylabel("Floor (下调上限)")
        ax.set_title(f"动态策略: Ceiling×Floor 热力图\n(rate={best_rate:.1%})")
        plt.colorbar(im, ax=ax, shrink=0.8)

    # 护栏策略: target_success vs score (按最优其他参数)
    ax = axes[1, 1]
    gr_best_by_ts = guardrail_df.loc[
        guardrail_df.groupby("target_success")["score"].idxmax()
    ].sort_values("target_success")
    ax.plot(gr_best_by_ts["target_success"] * 100, gr_best_by_ts["score"], "o-",
            color="#4CAF50", markersize=4)
    gr_best = guardrail_df.iloc[0]
    ax.axvline(gr_best["target_success"] * 100, color="red", linestyle="--", alpha=0.5)
    ax.set_xlabel("目标成功率 (%)")
    ax.set_ylabel("Score")
    ax.set_title(f"护栏策略: 目标成功率 vs 最优Score\n最优: {gr_best['target_success']:.0%}")
    ax.grid(True, alpha=0.3)

    # 三策略 Score 分布箱线图
    ax = axes[1, 2]
    safe_fixed = fixed_df[fixed_df["p10_funded"] >= 0.80]["score"]
    safe_dynamic = dynamic_df[dynamic_df["p10_funded"] >= 0.80]["score"]
    safe_guardrail = guardrail_df[guardrail_df["p10_funded"] >= 0.80]["score"]
    box_data = []
    box_labels = []
    if len(safe_fixed) > 0:
        box_data.append(safe_fixed.values)
        box_labels.append("固定")
    if len(safe_dynamic) > 0:
        box_data.append(safe_dynamic.values)
        box_labels.append("动态")
    if len(safe_guardrail) > 0:
        box_data.append(safe_guardrail.values)
        box_labels.append("护栏")
    if box_data:
        bp = ax.boxplot(box_data, labels=box_labels, patch_artist=True)
        colors = ["#2196F3", "#FF9800", "#4CAF50"]
        for patch, color in zip(bp["boxes"], colors[:len(box_data)]):
            patch.set_facecolor(color)
            patch.set_alpha(0.3)
    ax.set_ylabel("Score")
    ax.set_title("三策略 Score 分布 (p10_funded>=80%)")
    ax.grid(True, alpha=0.3)

    fig.suptitle("三策略参数敏感性分析", fontsize=14)
    fig.tight_layout()
    fig.savefig(STRAT_OUTPUT_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"  → {STRAT_OUTPUT_DIR}/{filename}")


def plot_score_vs_rate(
    fixed_df: pd.DataFrame,
    dynamic_df: pd.DataFrame,
    guardrail_df: pd.DataFrame,
    filename: str = "strategy_score_vs_rate.png",
):
    """三策略 Score vs 初始提取率对比。"""
    fig, ax = plt.subplots(figsize=(12, 7))

    # 固定
    sorted_f = fixed_df.sort_values("initial_rate")
    ax.plot(sorted_f["initial_rate"] * 100, sorted_f["score"],
            "-", color="#2196F3", linewidth=2, label="固定提取", alpha=0.8)

    # 动态: 每个 rate 取最优 ceiling/floor
    dyn_best = dynamic_df.loc[
        dynamic_df.groupby("withdrawal_rate")["score"].idxmax()
    ].sort_values("withdrawal_rate")
    ax.plot(dyn_best["withdrawal_rate"] * 100, dyn_best["score"],
            "s-", color="#FF9800", linewidth=2, markersize=5, label="Vanguard 动态 (最优 C/F)", alpha=0.8)

    # 护栏: 按 initial_rate 分 bin
    gr_sorted = guardrail_df.sort_values("initial_rate")
    gr_sorted["rate_bin"] = (gr_sorted["initial_rate"] * 200).round() / 200
    gr_best = gr_sorted.loc[gr_sorted.groupby("rate_bin")["score"].idxmax()].sort_values("rate_bin")
    ax.plot(gr_best["rate_bin"] * 100, gr_best["score"],
            "^-", color="#4CAF50", linewidth=2, markersize=5, label="风险护栏 (最优参数)", alpha=0.8)

    ax.set_xlabel("初始提取率 (%)", fontsize=12)
    ax.set_ylabel("综合得分 (Score)", fontsize=12)
    ax.set_title("三策略得分 vs 初始提取率", fontsize=14)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(1.5, 8.5)
    fig.tight_layout()
    fig.savefig(STRAT_OUTPUT_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"  → {STRAT_OUTPUT_DIR}/{filename}")


# ═══════════════════════════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════════════════════════

def generate_report(
    fixed_geo3: pd.DataFrame,
    dynamic_geo3: pd.DataFrame,
    guardrail_geo3: pd.DataFrame,
    fixed_detail: dict,
    dynamic_detail: dict,
    guardrail_detail: dict,
    filename: str = "strategy_comparison_report.md",
):
    """生成 Markdown 分析报告。"""
    lines = []
    lines.append("# 三种提取策略综合对比分析报告\n")
    lines.append(f"资产配置: 国内股票 {ALLOCATION.get('domestic_stock',0):.0%} / "
                 f"国际股票 {ALLOCATION.get('global_stock',0):.0%} / "
                 f"债券 {ALLOCATION.get('domestic_bond',0):.0%}")
    lines.append(f"初始资产: ${INITIAL_PORTFOLIO:,} | 退休年限: {RETIREMENT_YEARS} 年 | "
                 f"费率: {list(EXPENSE_RATIOS.values())[0]:.1%}\n")

    lines.append("## 评分体系\n")
    lines.append("v2 五维加权评分: `score = safety * (0.25*util + 0.15*p10_util + 0.20*disc + 0.20*floor + 0.20*smooth) * 15`")
    lines.append("- safety = p10_funded²")
    lines.append("- smoothness = 1/(1+20*median_downside_cv)")
    lines.append("- 四数据源加权 Geo3 = (US-Std × MC1970 × JST-MC)^(1/3)\n")

    # 最优参数对比表
    lines.append("## 最优参数\n")

    strategies = []
    if len(fixed_geo3) > 0:
        fb = fixed_geo3.iloc[0]
        strategies.append(("固定提取", fb, f"提取率 {fb.get('withdrawal_rate', fb.get('initial_rate',0)):.1%}"))
    if len(dynamic_geo3) > 0:
        db = dynamic_geo3.iloc[0]
        strategies.append(("Vanguard 动态", db,
                          f"提取率 {db.get('withdrawal_rate',0):.1%}, "
                          f"上限 {db.get('dynamic_ceiling',0):.0%}, "
                          f"下限 {db.get('dynamic_floor',0):.0%}"))
    if len(guardrail_geo3) > 0:
        gb = guardrail_geo3.iloc[0]
        strategies.append(("风险护栏", gb,
                          f"目标 {gb.get('target_success',0):.0%}, "
                          f"上栏 {gb.get('upper_guardrail',0):.0%}, "
                          f"下栏 {gb.get('lower_guardrail',0):.0%}, "
                          f"调整 {gb.get('adjustment_pct',0):.0%}, "
                          f"模式 {gb.get('adjustment_mode','')}, "
                          f"最少年 {int(gb.get('min_remaining_years',0))}"))

    lines.append("| 策略 | 最优参数 | WGeo3 Score |")
    lines.append("|------|---------|-------------|")
    for name, row, params in strategies:
        lines.append(f"| {name} | {params} | {row['wgeo3_score']:.4f} |")
    lines.append("")

    # 详细指标表
    lines.append("## 关键指标对比 (JST-MC 数据源)\n")
    metric_names = [
        ("success_rate", "成功率"),
        ("p10_funded", "P10 资金覆盖"),
        ("median_util", "中位消费率"),
        ("p10_util", "P10 消费率"),
        ("median_discounted", "折现消费率"),
        ("p10_floor_self", "P10 底线保护"),
        ("smoothness", "平滑度"),
        ("p10_min_wd", "P10 最低年消费"),
        ("median_downside_cv", "中位下行CV"),
        ("score", "综合得分"),
    ]

    header = "| 指标 |"
    sep = "|------|"
    for name, _, _ in strategies:
        header += f" {name} |"
        sep += "-------|"
    lines.append(header)
    lines.append(sep)

    key_cols_map = {
        "固定提取": ["withdrawal_rate"],
        "Vanguard 动态": ["withdrawal_rate", "dynamic_ceiling", "dynamic_floor"],
        "风险护栏": list(PARAM_GRID.keys()),
    }
    detail_map_ref = {
        "固定提取": fixed_detail,
        "Vanguard 动态": dynamic_detail,
        "风险护栏": guardrail_detail,
    }

    for mkey, mlabel in metric_names:
        row_str = f"| {mlabel} |"
        for sname, geo_row, _ in strategies:
            dm = detail_map_ref.get(sname, {}).get("jst")
            val = "N/A"
            if dm is not None:
                kcols = key_cols_map[sname]
                k = tuple(geo_row[c] for c in kcols)
                detail_row = dm.get(k)
                if detail_row is not None:
                    v = detail_row.get(mkey, None)
                    if v is not None:
                        if mkey == "p10_min_wd":
                            val = f"${v:,.0f}"
                        elif mkey in ("median_downside_cv",):
                            val = f"{v:.4f}"
                        else:
                            val = f"{v:.4f}"
            row_str += f" {val} |"
        lines.append(row_str)
    lines.append("")

    # 各策略 Top-5
    for sname, geo3_df, detail in [
        ("固定提取", fixed_geo3, fixed_detail),
        ("Vanguard 动态", dynamic_geo3, dynamic_detail),
        ("风险护栏", guardrail_geo3, guardrail_detail),
    ]:
        lines.append(f"## {sname} Top-5 (WGeo3)\n")
        lines.append("| # | WGeo3 | Hist | MC | MC1970 | JST |")
        lines.append("|---|-------|------|-----|--------|-----|")
        for i, (_, row) in enumerate(geo3_df.head(5).iterrows()):
            lines.append(f"| {i+1} | {row['wgeo3_score']:.4f} | "
                        f"{row['hist_score']:.4f} | {row['mc_score']:.4f} | "
                        f"{row['mc1970_score']:.4f} | {row['jst_score']:.4f} |")
        lines.append("")

    path = STRAT_OUTPUT_DIR / filename
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  → {path}")


# ═══════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════

def main():
    all_fixed, all_dynamic, all_guardrail, source_labels, source_names = run_all_sources()

    # 保存原始结果
    for key in source_labels:
        all_fixed[key].to_csv(STRAT_OUTPUT_DIR / f"fixed_{key}_results.csv", index=False, float_format="%.6f")
        all_dynamic[key].to_csv(STRAT_OUTPUT_DIR / f"dynamic_{key}_results.csv", index=False, float_format="%.6f")

    print(f"\n{'='*80}")
    print(f"  加权 Geo3 综合排名")
    print(f"{'='*80}")

    # 固定策略 Geo3
    fixed_key_cols = ["withdrawal_rate"]
    fixed_geo3 = compute_weighted_geo3(all_fixed, source_labels, fixed_key_cols)
    fixed_geo3.to_csv(STRAT_OUTPUT_DIR / "fixed_geo3.csv", index=False, float_format="%.6f")
    print(f"\n  固定策略 Top-10 (WGeo3):")
    print(f"  {'#':>3}  {'rate':>6}  {'Hist':>8}  {'MC':>8}  {'MC70':>8}  {'JST':>8}  {'WGeo3':>8}")
    print(f"  {'─'*62}")
    for i, (_, row) in enumerate(fixed_geo3.head(10).iterrows()):
        print(f"  {i+1:>3}  {row['withdrawal_rate']:>5.1%}  "
              f"{row['hist_score']:>8.4f}  {row['mc_score']:>8.4f}  "
              f"{row['mc1970_score']:>8.4f}  {row['jst_score']:>8.4f}  {row['wgeo3_score']:>8.4f}")

    # 动态策略 Geo3
    dynamic_key_cols = ["withdrawal_rate", "dynamic_ceiling", "dynamic_floor"]
    dynamic_geo3 = compute_weighted_geo3(all_dynamic, source_labels, dynamic_key_cols)
    dynamic_geo3.to_csv(STRAT_OUTPUT_DIR / "dynamic_geo3.csv", index=False, float_format="%.6f")
    print(f"\n  动态策略 Top-10 (WGeo3):")
    print(f"  {'#':>3}  {'rate':>6}  {'ceil':>5}  {'floor':>6}  {'Hist':>8}  {'MC':>8}  {'MC70':>8}  {'JST':>8}  {'WGeo3':>8}")
    print(f"  {'─'*80}")
    for i, (_, row) in enumerate(dynamic_geo3.head(10).iterrows()):
        print(f"  {i+1:>3}  {row['withdrawal_rate']:>5.1%}  {row['dynamic_ceiling']:>5.0%}  {row['dynamic_floor']:>5.0%}  "
              f"{row['hist_score']:>8.4f}  {row['mc_score']:>8.4f}  "
              f"{row['mc1970_score']:>8.4f}  {row['jst_score']:>8.4f}  {row['wgeo3_score']:>8.4f}")

    # 护栏策略 Geo3
    guardrail_key_cols = list(PARAM_GRID.keys())
    guardrail_geo3 = compute_weighted_geo3(all_guardrail, source_labels, guardrail_key_cols)
    guardrail_geo3.to_csv(STRAT_OUTPUT_DIR / "guardrail_geo3.csv", index=False, float_format="%.6f")
    print(f"\n  护栏策略 Top-10 (WGeo3):")
    print(f"  {'#':>3}  {'target':>7}  {'upper':>6}  {'lower':>6}  {'adj%':>5}  {'mode':>13}  {'mr':>3}  "
          f"{'Hist':>8}  {'MC':>8}  {'MC70':>8}  {'JST':>8}  {'WGeo3':>8}")
    print(f"  {'─'*112}")
    for i, (_, row) in enumerate(guardrail_geo3.head(10).iterrows()):
        print(f"  {i+1:>3}  {row['target_success']:>7.0%}  {row['upper_guardrail']:>6.0%}  {row['lower_guardrail']:>6.0%}"
              f"  {row['adjustment_pct']:>5.0%}  {row['adjustment_mode']:>13}  {int(row['min_remaining_years']):>3}"
              f"  {row['hist_score']:>8.4f}  {row['mc_score']:>8.4f}  "
              f"{row['mc1970_score']:>8.4f}  {row['jst_score']:>8.4f}  {row['wgeo3_score']:>8.4f}")

    # ── 三策略对比 ──
    print(f"\n{'='*80}")
    print(f"  ★ 三策略最优对比")
    print(f"{'='*80}")

    # 取 JST-MC 的详细指标
    fixed_detail = build_detail_maps(all_fixed, fixed_key_cols)
    dynamic_detail = build_detail_maps(all_dynamic, dynamic_key_cols)
    guardrail_detail = build_detail_maps(all_guardrail, guardrail_key_cols)

    comparison_rows = []
    for sname, geo3_df, detail, kcols in [
        ("固定提取", fixed_geo3, fixed_detail, fixed_key_cols),
        ("Vanguard 动态", dynamic_geo3, dynamic_detail, dynamic_key_cols),
        ("风险护栏", guardrail_geo3, guardrail_detail, guardrail_key_cols),
    ]:
        if len(geo3_df) == 0:
            continue
        best = geo3_df.iloc[0]
        k = tuple(best[c] for c in kcols)
        jst_row = detail.get("jst", {}).get(k)
        mc_row = detail.get("mc", {}).get(k)

        ref = jst_row if jst_row is not None else mc_row
        if ref is None:
            continue

        row_data = {
            "strategy": sname,
            "wgeo3_score": best["wgeo3_score"],
        }
        for m in ["success_rate", "p10_funded", "median_util", "p10_util",
                   "median_discounted", "p10_floor_self", "smoothness",
                   "p10_min_wd", "median_downside_cv", "score", "initial_rate"]:
            row_data[m] = ref.get(m, 0)
        comparison_rows.append(row_data)

    comp_df = pd.DataFrame(comparison_rows)
    comp_df.to_csv(STRAT_OUTPUT_DIR / "strategy_comparison.csv", index=False, float_format="%.6f")

    print(f"\n  {'策略':>12}  {'WGeo3':>8}  {'成功率':>6}  {'P10F':>6}  {'util':>6}  {'p10u':>6}  {'disc':>6}  "
          f"{'floor':>6}  {'smooth':>6}  {'P10$':>8}  {'init%':>6}")
    print(f"  {'─'*100}")
    for _, row in comp_df.iterrows():
        print(f"  {row['strategy']:>12}  {row['wgeo3_score']:>8.4f}  {row['success_rate']:>6.1%}  "
              f"{row['p10_funded']:>6.3f}  {row['median_util']:>6.4f}  {row['p10_util']:>6.4f}  "
              f"{row['median_discounted']:>6.4f}  {row['p10_floor_self']:>6.3f}  {row['smoothness']:>6.3f}  "
              f"${row['p10_min_wd']:>7,.0f}  {row['initial_rate']:>5.1%}")

    # ── 可视化 ──
    print(f"\n{'='*80}")
    print(f"  可视化")
    print(f"{'='*80}")

    # 雷达图
    radar_data = []
    for _, row in comp_df.iterrows():
        radar_data.append({
            "label": row["strategy"],
            "success_rate": row["success_rate"],
            "p10_funded": row["p10_funded"],
            "median_util": min(row["median_util"] * SCORE_SCALE, 1.0),
            "p10_floor_self": row["p10_floor_self"],
            "smoothness": row["smoothness"],
            "median_discounted": min(row["median_discounted"] * SCORE_SCALE, 1.0),
        })
    plot_radar(radar_data)

    # Pareto（用 JST-MC 数据）
    plot_pareto_comparison(all_fixed["jst"], all_dynamic["jst"], all_guardrail["jst"])

    # 敏感性（用 JST-MC 数据）
    plot_sensitivity(all_fixed["jst"], all_dynamic["jst"], all_guardrail["jst"])

    # Score vs Rate
    plot_score_vs_rate(all_fixed["jst"], all_dynamic["jst"], all_guardrail["jst"])

    # 报告
    generate_report(
        fixed_geo3, dynamic_geo3, guardrail_geo3,
        fixed_detail, dynamic_detail, guardrail_detail,
    )

    print(f"\n所有输出保存在: {STRAT_OUTPUT_DIR}/")
    print("完成！")


if __name__ == "__main__":
    main()
