"""消费地板敏感性分析。

对比不同消费地板定义下护栏策略的有效失败率和 funded ratio，
帮助确定合理的"失败"阈值。

支持 --pooled 参数切换为国际池化数据。
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import load_returns_data, filter_by_country, get_country_dfs
from simulator.portfolio import compute_real_portfolio_returns
from simulator.bootstrap import block_bootstrap, block_bootstrap_pooled
from simulator.guardrail import (
    build_success_rate_table,
    run_guardrail_simulation,
)
from simulator.statistics import compute_effective_funded_ratio
from simulator.config import get_gdp_weights

INITIAL_PORTFOLIO = 1_000_000
RETIREMENT_YEARS = 65
ALLOCATION = {"domestic_stock": 0.33, "global_stock": 0.67}
EXPENSE_RATIOS = {"domestic_stock": 0.005, "global_stock": 0.005}
MIN_BLOCK = 5
MAX_BLOCK = 15
NUM_SIMULATIONS = 3000
DATA_START_YEAR = 1900
SEED = 42

TARGET_SUCCESS = 0.85
UPPER_GUARDRAIL = 0.99
LOWER_GUARDRAIL = 0.60
ADJUSTMENT_PCT = 0.10
ADJUSTMENT_MODE = "amount"
MIN_REMAINING_YEARS = 5

FLOOR_VALUES = [0.0, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]


def prepare_scenarios_usa(returns_df):
    rng = np.random.default_rng(SEED)
    scenarios = np.zeros((NUM_SIMULATIONS, RETIREMENT_YEARS))
    for i in range(NUM_SIMULATIONS):
        sampled = block_bootstrap(returns_df, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK, rng=rng)
        scenarios[i] = compute_real_portfolio_returns(sampled, ALLOCATION, EXPENSE_RATIOS)
    return scenarios


def prepare_scenarios_pooled(country_dfs, country_weights):
    rng = np.random.default_rng(SEED)
    scenarios = np.zeros((NUM_SIMULATIONS, RETIREMENT_YEARS))
    for i in range(NUM_SIMULATIONS):
        sampled = block_bootstrap_pooled(
            country_dfs, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK,
            rng=rng, country_weights=country_weights,
        )
        scenarios[i] = compute_real_portfolio_returns(sampled, ALLOCATION, EXPENSE_RATIOS)
    return scenarios


def main():
    use_pooled = "--pooled" in sys.argv

    data_label = "国际池化 (16国 sqrt-GDP 加权)" if use_pooled else "仅美国 (USA)"

    print("=" * 70)
    print(f"消费地板敏感性分析 — 数据源: {data_label}")
    print("=" * 70)
    print(f"\n参数: portfolio=${INITIAL_PORTFOLIO:,.0f}, "
          f"retirement={RETIREMENT_YEARS}yr, target_success={TARGET_SUCCESS:.0%}")
    print(f"护栏: upper={UPPER_GUARDRAIL}, lower={LOWER_GUARDRAIL}, "
          f"adj={ADJUSTMENT_PCT}, mode={ADJUSTMENT_MODE}")

    print("\n[1/3] 加载数据并生成场景...")
    df = load_returns_data()

    if use_pooled:
        country_dfs = get_country_dfs(df, DATA_START_YEAR)
        country_weights = get_gdp_weights(list(country_dfs.keys()))
        print(f"  可用国家: {len(country_dfs)} 个 — {', '.join(sorted(country_dfs.keys()))}")
        scenarios = prepare_scenarios_pooled(country_dfs, country_weights)
    else:
        filtered = filter_by_country(df, "USA", DATA_START_YEAR)
        scenarios = prepare_scenarios_usa(filtered)

    print(f"  生成 {NUM_SIMULATIONS} 条路径, 每条 {RETIREMENT_YEARS} 年")

    print("[2/3] 构建查找表 & 运行护栏模拟...")
    rate_grid, table = build_success_rate_table(scenarios)

    init_portfolio, annual_wd, trajectories, withdrawals = run_guardrail_simulation(
        scenarios=scenarios,
        target_success=TARGET_SUCCESS,
        upper_guardrail=UPPER_GUARDRAIL,
        lower_guardrail=LOWER_GUARDRAIL,
        adjustment_pct=ADJUSTMENT_PCT,
        retirement_years=RETIREMENT_YEARS,
        min_remaining_years=MIN_REMAINING_YEARS,
        table=table,
        rate_grid=rate_grid,
        adjustment_mode=ADJUSTMENT_MODE,
        initial_portfolio=INITIAL_PORTFOLIO,
    )

    print(f"  初始资产: ${init_portfolio:,.0f}")
    print(f"  初始年提取: ${annual_wd:,.0f}")
    print(f"  初始提取率: {annual_wd / init_portfolio:.2%}")

    # ── 传统成功率（仅看资产归零）──
    traditional_success = float(np.mean(trajectories[:, -1] > 0))
    print(f"\n  传统成功率（仅资产归零）: {traditional_success:.1%}")

    # ── 消费分布统计 ──
    print("\n[3/3] 分析消费分布...")

    min_wd_per_path = np.min(withdrawals, axis=1)
    min_wd_ratio = min_wd_per_path / annual_wd

    active_mask = withdrawals > 0
    active_min = np.where(active_mask.any(axis=1),
                          np.where(active_mask, withdrawals, np.inf).min(axis=1),
                          0.0)
    active_min_ratio = active_min / annual_wd

    print("\n" + "=" * 70)
    print("A. 各路径最低年消费 / 初始消费 的分位数分布")
    print("=" * 70)
    print("（排除资产归零后消费=0的路径，仅看存活期间的最低消费）")
    survived = active_min_ratio[active_min_ratio > 0]
    percentiles = [5, 10, 25, 50, 75, 90]
    print(f"\n  存活期间有消费的路径数: {len(survived)}/{NUM_SIMULATIONS}")
    for p in percentiles:
        val = np.percentile(survived, p)
        print(f"  P{p:2d}: {val:.1%}")

    print(f"\n  所有路径最低消费比:")
    for p in percentiles:
        val = np.percentile(min_wd_ratio, p)
        print(f"  P{p:2d}: {val:.1%}")

    # ── 多地板对比 ──
    print("\n" + "=" * 70)
    print("B. 不同消费地板定义下的有效成功率对比")
    print("=" * 70)

    header = f"{'消费地板':>8} | {'有效成功率':>10} | {'Funded Ratio':>14} | {'失败定义'}"
    print(f"\n{header}")
    print("-" * len(header.encode('gbk', errors='replace')))

    results = []
    for floor in FLOOR_VALUES:
        funded, success = compute_effective_funded_ratio(
            withdrawals, annual_wd, RETIREMENT_YEARS,
            consumption_floor=floor,
            trajectories=trajectories,
        )
        if floor == 0:
            label = "仅资产归零"
        else:
            label = f"消费 < 初始的{floor:.0%}"
        results.append((floor, success, funded, label))
        print(f"  {floor:>6.0%}  |   {success:>7.1%}   |    {funded:>8.3f}     | {label}")

    # ── 失败路径分析 ──
    print("\n" + "=" * 70)
    print("C. 失败路径的消费恶化模式分析")
    print("=" * 70)

    floor_70 = 0.70
    floor_val = annual_wd * floor_70
    below_floor = withdrawals < floor_val
    ever_below = below_floor.any(axis=1)
    asset_zero = trajectories[:, -1] <= 0

    only_consumption_fail = ever_below & ~asset_zero
    both_fail = ever_below & asset_zero
    only_asset_fail = ~ever_below & asset_zero
    neither_fail = ~ever_below & ~asset_zero

    n = NUM_SIMULATIONS
    print(f"\n以 70% 消费地板为例:")
    print(f"  两种定义都成功:         {np.sum(neither_fail):>5d} ({np.mean(neither_fail):.1%})")
    print(f"  仅消费低于地板(资产未归零): {np.sum(only_consumption_fail):>5d} ({np.mean(only_consumption_fail):.1%})")
    print(f"  仅资产归零(消费未低于地板): {np.sum(only_asset_fail):>5d} ({np.mean(only_asset_fail):.1%})")
    print(f"  两者都触发:             {np.sum(both_fail):>5d} ({np.mean(both_fail):.1%})")

    if np.sum(only_consumption_fail) > 0:
        fail_paths = withdrawals[only_consumption_fail]
        fail_min = np.min(fail_paths, axis=1) / annual_wd
        print(f"\n  '仅消费降低'路径的最低消费中位数: {np.median(fail_min):.1%}")
        print(f"  这些路径最终资产中位数: ${np.median(trajectories[only_consumption_fail, -1]):,.0f}")

    # ── 不同地板的边际影响 ──
    print("\n" + "=" * 70)
    print("D. 地板从50%提高到70%的边际影响")
    print("=" * 70)

    r50 = [r for r in results if r[0] == 0.50][0]
    r70 = [r for r in results if r[0] == 0.70][0]
    print(f"\n  50% 地板: 成功率 {r50[1]:.1%}, funded ratio {r50[2]:.3f}")
    print(f"  70% 地板: 成功率 {r70[1]:.1%}, funded ratio {r70[2]:.3f}")
    print(f"  差异:     成功率 {r50[1] - r70[1]:+.1%}, funded ratio {r50[2] - r70[2]:+.3f}")
    print(f"\n  解读: 将地板从50%提高到70%，会额外将 {r50[1] - r70[1]:.1%} 的路径")
    print(f"  从\"成功\"重新归类为\"失败\"。这些路径的消费虽未归零，")
    print(f"  但已降至初始水平的50-70%之间，生活质量显著下降。")

    # ── 消费路径分位数 ──
    print("\n" + "=" * 70)
    print("E. 年度消费的百分位走势 (占初始消费比例)")
    print("=" * 70)
    wd_ratio = withdrawals / annual_wd
    years_to_show = [0, 4, 9, 14, 19, 29, 39, 49, 64]
    years_to_show = [y for y in years_to_show if y < RETIREMENT_YEARS]

    print(f"\n{'年份':>4} | {'P5':>6} | {'P10':>6} | {'P25':>6} | {'P50':>6} | {'P75':>6} | {'P90':>6} | {'P95':>6}")
    print("-" * 60)
    for y in years_to_show:
        col = wd_ratio[:, y]
        active = col[col > 0]
        if len(active) == 0:
            continue
        ps = np.percentile(active, [5, 10, 25, 50, 75, 90, 95])
        print(f"  {y+1:>2}  | {ps[0]:>5.0%} | {ps[1]:>5.0%} | {ps[2]:>5.0%} | "
              f"{ps[3]:>5.0%} | {ps[4]:>5.0%} | {ps[5]:>5.0%} | {ps[6]:>5.0%}")

    print("\n" + "=" * 70)
    print("分析完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
