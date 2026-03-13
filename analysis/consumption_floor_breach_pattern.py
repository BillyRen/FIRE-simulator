"""消费地板跌破模式深度分析：连续 vs 间歇。

对跌破路径做游程编码(run-length encoding)，统计：
- 跌破段数分布（1次连续跌破 vs 多次间歇跌破）
- 每段连续跌破的长度分布
- 最长连续跌破长度
- 短暂跌破(1-2年)后恢复的比例
- 连续N年跌破的条件概率

用于决定失败判定机制：首次跌破即失败 vs 连续N年跌破才算失败。
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import load_returns_data, filter_by_country, get_country_dfs
from simulator.portfolio import compute_real_portfolio_returns
from simulator.bootstrap import block_bootstrap, block_bootstrap_pooled
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
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

FLOOR_PCT = 0.50


def run_length_encode(arr):
    """对布尔数组做游程编码。返回 [(value, length), ...]"""
    if len(arr) == 0:
        return []
    runs = []
    current = arr[0]
    length = 1
    for i in range(1, len(arr)):
        if arr[i] == current:
            length += 1
        else:
            runs.append((current, length))
            current = arr[i]
            length = 1
    runs.append((current, length))
    return runs


def analyze_breach_patterns(withdrawals, annual_wd, floor_pct):
    """对所有跌破路径做游程编码分析。"""
    floor_val = annual_wd * floor_pct
    n_sims, n_years = withdrawals.shape
    below_floor = withdrawals < floor_val
    ever_below = below_floor.any(axis=1)
    breach_indices = np.where(ever_below)[0]

    if len(breach_indices) == 0:
        return None

    # Per-path stats
    num_breach_runs = []       # 跌破段数
    max_consec_breach = []     # 最长连续跌破
    first_breach_len = []      # 首次跌破段的长度
    all_breach_run_lengths = []  # 所有跌破段的长度（扁平化）
    total_below_years = []
    first_breach_year = []
    path_eventually_recovers = []  # 首次跌破后是否最终恢复（最后一年不在跌破状态）

    for idx in breach_indices:
        path = below_floor[idx]
        runs = run_length_encode(path)

        # Extract breach runs (value=True)
        breach_runs = [length for value, length in runs if value]
        num_breach_runs.append(len(breach_runs))
        max_consec_breach.append(max(breach_runs))
        all_breach_run_lengths.extend(breach_runs)
        total_below_years.append(int(path.sum()))

        # First breach segment
        fb_year = int(np.argmax(path))
        first_breach_year.append(fb_year)
        first_breach_len.append(breach_runs[0])

        # Does path end above floor?
        path_eventually_recovers.append(not path[-1])

    return {
        "num_breach_paths": len(breach_indices),
        "num_breach_runs": np.array(num_breach_runs),
        "max_consec_breach": np.array(max_consec_breach),
        "first_breach_len": np.array(first_breach_len),
        "all_breach_run_lengths": np.array(all_breach_run_lengths),
        "total_below_years": np.array(total_below_years),
        "first_breach_year": np.array(first_breach_year),
        "path_eventually_recovers": np.array(path_eventually_recovers),
        "n_sims": n_sims,
    }


def simulate_tolerance_policy(withdrawals, annual_wd, floor_pct, tolerance_years, trajectories):
    """模拟"连续N年跌破才算失败"的策略，返回有效成功率。

    与当前的 compute_effective_funded_ratio (N=1) 对比。
    """
    floor_val = annual_wd * floor_pct
    n_sims, n_years = withdrawals.shape
    below_floor = withdrawals < floor_val

    # For each path, find first occurrence of `tolerance_years` consecutive breaches
    eff_depletion = np.full(n_sims, float(n_years))

    for i in range(n_sims):
        path = below_floor[i]
        consec = 0
        for y in range(n_years):
            if path[y]:
                consec += 1
                if consec >= tolerance_years:
                    eff_depletion[i] = float(y - tolerance_years + 1)
                    break
            else:
                consec = 0

    # Also factor in asset depletion
    if trajectories is not None:
        depleted = trajectories[:, 1:] <= 0
        any_depleted = depleted.any(axis=1)
        asset_depletion = np.where(
            any_depleted,
            np.argmax(depleted, axis=1).astype(float),
            float(n_years),
        )
        eff_depletion = np.minimum(eff_depletion, asset_depletion)

    retirement_years = n_years
    funded = float(np.mean(np.minimum(eff_depletion / retirement_years, 1.0)))
    success = float(np.mean(eff_depletion >= n_years))
    return success, funded


def main():
    use_pooled = "--pooled" in sys.argv

    data_label = "国际池化 (16国 sqrt-GDP 加权)" if use_pooled else "仅美国 (USA)"
    print("=" * 75)
    print(f"消费地板跌破模式分析 — 数据源: {data_label}")
    print("=" * 75)

    print("\n[1/3] 生成场景 & 运行护栏模拟...")
    df = load_returns_data()

    if use_pooled:
        country_dfs = get_country_dfs(df, DATA_START_YEAR)
        country_weights = get_gdp_weights(list(country_dfs.keys()))
        rng = np.random.default_rng(SEED)
        scenarios = np.zeros((NUM_SIMULATIONS, RETIREMENT_YEARS))
        for i in range(NUM_SIMULATIONS):
            sampled = block_bootstrap_pooled(
                country_dfs, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK,
                rng=rng, country_weights=country_weights,
            )
            scenarios[i] = compute_real_portfolio_returns(sampled, ALLOCATION, EXPENSE_RATIOS)
    else:
        filtered = filter_by_country(df, "USA", DATA_START_YEAR)
        rng = np.random.default_rng(SEED)
        scenarios = np.zeros((NUM_SIMULATIONS, RETIREMENT_YEARS))
        for i in range(NUM_SIMULATIONS):
            sampled = block_bootstrap(filtered, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK, rng=rng)
            scenarios[i] = compute_real_portfolio_returns(sampled, ALLOCATION, EXPENSE_RATIOS)

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
    print(f"  初始提取: ${annual_wd:,.0f} (rate={annual_wd/init_portfolio:.2%})")

    # ── A. 游程编码分析 ──
    print("\n[2/3] 游程编码分析 (50% 地板)...")
    stats = analyze_breach_patterns(withdrawals, annual_wd, FLOOR_PCT)

    if stats is None:
        print("  无跌破路径，分析结束。")
        return

    n_breach = stats["num_breach_paths"]
    print(f"\n  跌破路径: {n_breach}/{stats['n_sims']} ({n_breach/stats['n_sims']:.1%})")

    print("\n" + "=" * 75)
    print("A. 跌破段数分布（每条路径有几段独立的连续跌破？）")
    print("=" * 75)
    runs = stats["num_breach_runs"]
    for n in range(1, min(6, int(runs.max()) + 1)):
        count = np.sum(runs == n)
        print(f"  {n} 段: {count:>4d} 条路径 ({count/n_breach:.1%})")
    if runs.max() >= 6:
        count = np.sum(runs >= 6)
        print(f"  6+段: {count:>4d} 条路径 ({count/n_breach:.1%})")
    print(f"\n  跌破段数 — 均值: {runs.mean():.1f}, 中位数: {np.median(runs):.0f}, "
          f"最大: {runs.max():.0f}")

    print("\n" + "=" * 75)
    print("B. 首次连续跌破段长度分布")
    print("=" * 75)
    fbl = stats["first_breach_len"]
    brackets = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 20), (21, 100)]
    for lo, hi in brackets:
        count = np.sum((fbl >= lo) & (fbl <= hi))
        label = f"{lo}年" if lo == hi else f"{lo}-{hi}年"
        print(f"  {label:>7s}: {count:>4d} ({count/n_breach:.1%})")
    print(f"\n  首次段长度 — 均值: {fbl.mean():.1f}年, 中位数: {np.median(fbl):.0f}年")

    print("\n" + "=" * 75)
    print("C. 最长连续跌破长度分布")
    print("=" * 75)
    mcb = stats["max_consec_breach"]
    for lo, hi in brackets:
        count = np.sum((mcb >= lo) & (mcb <= hi))
        label = f"{lo}年" if lo == hi else f"{lo}-{hi}年"
        print(f"  {label:>7s}: {count:>4d} ({count/n_breach:.1%})")
    print(f"\n  最长连续 — 均值: {mcb.mean():.1f}年, 中位数: {np.median(mcb):.0f}年")

    print("\n" + "=" * 75)
    print("D. 所有跌破段长度分布（扁平化）")
    print("=" * 75)
    arl = stats["all_breach_run_lengths"]
    print(f"  总跌破段数: {len(arl)}")
    for lo, hi in brackets:
        count = np.sum((arl >= lo) & (arl <= hi))
        label = f"{lo}年" if lo == hi else f"{lo}-{hi}年"
        print(f"  {label:>7s}: {count:>4d} ({count/len(arl):.1%})")

    short_breach = np.sum(arl <= 2)
    print(f"\n  短暂跌破(≤2年): {short_breach}/{len(arl)} ({short_breach/len(arl):.1%})")

    print("\n" + "=" * 75)
    print("E. 路径最终状态")
    print("=" * 75)
    recovers = stats["path_eventually_recovers"]
    print(f"  最后一年在地板以上: {recovers.sum():>4d}/{n_breach} ({recovers.mean():.1%})")
    print(f"  最后一年仍低于地板: {(~recovers).sum():>4d}/{n_breach} ({(~recovers).mean():.1%})")

    # ── B. 容忍年数策略对比 ──
    print("\n[3/3] 不同容忍年数下的成功率对比...")
    print("\n" + "=" * 75)
    print("F. 容忍年数策略对比 (连续N年跌破才算失败)")
    print("=" * 75)

    # Current: N=1
    _, current_success = compute_effective_funded_ratio(
        withdrawals, annual_wd, RETIREMENT_YEARS,
        consumption_floor=FLOOR_PCT, trajectories=trajectories,
    )

    tolerance_values = [1, 2, 3, 5, 10]
    print(f"\n  {'容忍年数':>8} | {'成功率':>8} | {'Funded Ratio':>14} | {'vs N=1 差异':>10}")
    print("  " + "-" * 55)

    baseline_success = None
    for n in tolerance_values:
        success, funded = simulate_tolerance_policy(
            withdrawals, annual_wd, FLOOR_PCT, n, trajectories
        )
        if baseline_success is None:
            baseline_success = success
        delta = success - baseline_success
        print(f"  {'N=' + str(n):>8} | {success:>7.1%} | {funded:>13.3f} | {delta:>+9.1%}")

    # ── 结论 ──
    print("\n" + "=" * 75)
    print("结论与建议")
    print("=" * 75)

    # Compute key decision metrics
    single_year_breach_pct = np.sum(stats["first_breach_len"] == 1) / n_breach
    short_breach_pct = np.sum(stats["first_breach_len"] <= 2) / n_breach

    n1_success, _ = simulate_tolerance_policy(withdrawals, annual_wd, FLOOR_PCT, 1, trajectories)
    n3_success, _ = simulate_tolerance_policy(withdrawals, annual_wd, FLOOR_PCT, 3, trajectories)
    marginal_gain = n3_success - n1_success

    print(f"\n  首次跌破仅持续1年的路径: {single_year_breach_pct:.1%}")
    print(f"  首次跌破≤2年的路径:      {short_breach_pct:.1%}")
    print(f"  N=1 vs N=3 成功率差异:   {marginal_gain:+.1%}")

    if single_year_breach_pct > 0.30 and marginal_gain > 0.02:
        print(f"\n  ★ 建议: 考虑采用连续 3 年跌破才判定失败")
        print(f"    理由: {single_year_breach_pct:.0%} 的跌破是短暂的(≤1年), 改用 N=3 可提升成功率 {marginal_gain:.1%}")
    elif single_year_breach_pct > 0.15:
        print(f"\n  ★ 建议: 可考虑连续 2 年跌破判定失败")
        print(f"    理由: 有 {single_year_breach_pct:.0%} 的短暂跌破, 但整体影响有限")
    else:
        print(f"\n  ★ 建议: 维持当前 N=1 (首次跌破即失败) 策略")
        print(f"    理由: 绝大多数跌破是持续性的, 短暂跌破占比仅 {single_year_breach_pct:.0%}")
        print(f"    改用 N=3 仅提升成功率 {marginal_gain:.1%}, 收益极低")

    print("\n" + "=" * 75)
    print("分析完成")
    print("=" * 75)


if __name__ == "__main__":
    main()
