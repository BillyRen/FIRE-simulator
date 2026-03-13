"""消费地板跌破后的恢复概率分析。

分析护栏策略模拟中，年消费跌破地板后能否恢复到地板以上，
以及恢复耗时分布。结论用于决定是否需要引入"容忍年数"机制。

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

FLOOR_LEVELS = [0.40, 0.50, 0.60, 0.70]


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


def analyze_recovery(withdrawals, annual_wd, floor_pct):
    """分析跌破地板后的恢复模式。

    Returns dict with:
      - num_breach_paths: 曾跌破地板的路径数
      - recovery_rate: 跌破后恢复到地板以上的概率
      - recovery_time_median/mean: 恢复耗时（年）
      - duration_below_median/mean: 跌破持续年数
      - permanent_below_rate: 一旦跌破就再也不恢复的比例
    """
    floor_val = annual_wd * floor_pct
    n_sims, n_years = withdrawals.shape

    below_floor = withdrawals < floor_val

    # Find paths that ever go below floor
    ever_below = below_floor.any(axis=1)
    num_breach = int(ever_below.sum())

    if num_breach == 0:
        return {
            "floor_pct": floor_pct,
            "num_breach_paths": 0,
            "breach_rate": 0.0,
            "recovery_rate": float("nan"),
            "recovery_time_median": float("nan"),
            "recovery_time_mean": float("nan"),
            "duration_below_median": float("nan"),
            "duration_below_mean": float("nan"),
            "permanent_below_rate": float("nan"),
        }

    # For each breaching path, analyze recovery
    recovery_times = []
    durations_below = []
    recovered_count = 0

    for sim_idx in np.where(ever_below)[0]:
        path = below_floor[sim_idx]  # boolean array length n_years
        first_breach = int(np.argmax(path))  # first year below floor

        # Check if it ever recovers after first breach
        remaining = path[first_breach:]
        above_after = ~remaining  # years above floor after breach

        if above_after.any():
            # Find first recovery (first True in above_after, skipping the breach year)
            recovery_idx = int(np.argmax(above_after))
            if recovery_idx > 0:  # actually recovered (not just the breach year itself being above)
                recovered_count += 1
                recovery_times.append(recovery_idx)

        # Total years spent below floor
        total_below = int(path.sum())
        durations_below.append(total_below)

    recovery_rate = recovered_count / num_breach
    permanent_below_rate = 1.0 - recovery_rate

    return {
        "floor_pct": floor_pct,
        "num_breach_paths": num_breach,
        "breach_rate": num_breach / n_sims,
        "recovery_rate": recovery_rate,
        "recovery_time_median": float(np.median(recovery_times)) if recovery_times else float("nan"),
        "recovery_time_mean": float(np.mean(recovery_times)) if recovery_times else float("nan"),
        "duration_below_median": float(np.median(durations_below)),
        "duration_below_mean": float(np.mean(durations_below)),
        "permanent_below_rate": permanent_below_rate,
    }


def main():
    use_pooled = "--pooled" in sys.argv
    data_label = "国际池化 (16国 sqrt-GDP 加权)" if use_pooled else "仅美国 (USA)"

    print("=" * 70)
    print(f"消费地板跌破恢复分析 — 数据源: {data_label}")
    print("=" * 70)
    print(f"\n参数: portfolio=${INITIAL_PORTFOLIO:,.0f}, "
          f"retirement={RETIREMENT_YEARS}yr, sims={NUM_SIMULATIONS}")

    print("\n[1/3] 生成场景...")
    df = load_returns_data()

    if use_pooled:
        country_dfs = get_country_dfs(df, DATA_START_YEAR)
        country_weights = get_gdp_weights(list(country_dfs.keys()))
        scenarios = prepare_scenarios_pooled(country_dfs, country_weights)
    else:
        filtered = filter_by_country(df, "USA", DATA_START_YEAR)
        scenarios = prepare_scenarios_usa(filtered)

    print("[2/3] 运行护栏模拟...")
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

    print("\n[3/3] 分析恢复模式...")
    print("\n" + "=" * 70)
    print("各地板水平的跌破恢复统计")
    print("=" * 70)

    header = (f"{'地板':>6} | {'跌破路径':>8} | {'跌破率':>7} | {'恢复率':>7} | "
              f"{'恢复耗时':>8} | {'持续年数':>8} | {'永久跌破':>8}")
    print(f"\n{header}")
    print("-" * 80)

    results = []
    for floor_pct in FLOOR_LEVELS:
        r = analyze_recovery(withdrawals, annual_wd, floor_pct)
        results.append(r)

        recovery_str = f"{r['recovery_rate']:.1%}" if not np.isnan(r['recovery_rate']) else "N/A"
        time_str = f"{r['recovery_time_median']:.1f}yr" if not np.isnan(r['recovery_time_median']) else "N/A"
        dur_str = f"{r['duration_below_median']:.1f}yr" if not np.isnan(r['duration_below_median']) else "N/A"
        perm_str = f"{r['permanent_below_rate']:.1%}" if not np.isnan(r['permanent_below_rate']) else "N/A"

        print(f"  {floor_pct:>4.0%}  | {r['num_breach_paths']:>7d}  | {r['breach_rate']:>6.1%} | "
              f"{recovery_str:>7s} | {time_str:>8s} | {dur_str:>8s} | {perm_str:>8s}")

    # Detailed analysis for 50% floor
    print("\n" + "=" * 70)
    print("详细分析: 50% 消费地板")
    print("=" * 70)

    r50 = [r for r in results if r["floor_pct"] == 0.50][0]
    if r50["num_breach_paths"] > 0:
        floor_val = annual_wd * 0.50
        below = withdrawals < floor_val
        ever_below = below.any(axis=1)

        # Distribution of first breach year
        first_breach_years = []
        for idx in np.where(ever_below)[0]:
            first_breach_years.append(int(np.argmax(below[idx])) + 1)

        if first_breach_years:
            print(f"\n  首次跌破发生年份分布:")
            for p in [10, 25, 50, 75, 90]:
                print(f"    P{p}: 第 {int(np.percentile(first_breach_years, p))} 年")

        # Min withdrawal ratio for breach paths
        breach_wd = withdrawals[ever_below]
        min_ratios = np.min(breach_wd, axis=1) / annual_wd
        print(f"\n  跌破路径的最低消费比 (vs 初始):")
        for p in [10, 25, 50, 75, 90]:
            print(f"    P{p}: {np.percentile(min_ratios, p):.1%}")

    # Conclusion
    print("\n" + "=" * 70)
    print("结论")
    print("=" * 70)

    r50 = [r for r in results if r["floor_pct"] == 0.50][0]
    if r50["num_breach_paths"] == 0:
        print("\n  50% 地板无跌破路径，无需容忍年数机制。")
    elif r50["recovery_rate"] < 0.10:
        print(f"\n  50% 地板恢复率极低 ({r50['recovery_rate']:.1%})。")
        print("  一旦跌破地板基本不可逆，无需容忍年数机制。")
        print("  直接将首次跌破视为失败即可。")
    elif r50["recovery_rate"] > 0.50:
        print(f"\n  50% 地板恢复率较高 ({r50['recovery_rate']:.1%})。")
        print("  建议引入容忍年数机制，避免将暂时性消费下降误判为失败。")
    else:
        print(f"\n  50% 地板恢复率中等 ({r50['recovery_rate']:.1%})。")
        print("  当前直接判定方式基本合理，暂无需容忍年数机制。")

    print("\n" + "=" * 70)
    print("分析完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
