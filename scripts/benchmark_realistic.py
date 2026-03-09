#!/usr/bin/env python
"""真实场景性能基准测试：模拟实际用户请求。"""

import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.monte_carlo import run_simulation
from simulator.data_loader import load_returns_by_source, get_country_dfs


def benchmark_realistic_scenario():
    """真实用户场景：65年退休期，2000次模拟，ALL国家池化"""
    print("=" * 60)
    print("真实场景基准测试：65年退休期，2000次模拟，ALL国家")
    print("=" * 60)

    # 加载数据
    df = load_returns_by_source("jst")
    country_dfs = get_country_dfs(df, data_start_year=1900)

    # 真实参数
    params = {
        "initial_portfolio": 1_000_000,
        "annual_withdrawal": 40_000,
        "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
        "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
        "retirement_years": 65,  # 真实场景
        "min_block": 5,
        "max_block": 15,
        "num_simulations": 2000,  # 生产环境
        "returns_df": df.head(1),  # placeholder
        "seed": 42,
        "withdrawal_strategy": "fixed",
        "country_dfs": country_dfs,
        "country_weights": None,
    }

    # 预热
    print("\n预热运行...")
    _ = run_simulation(**params)

    # 正式测试
    times = []
    for i in range(3):
        start = time.time()
        trajectories, withdrawals, real_returns, inflation = run_simulation(**params)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"运行 {i+1}: {elapsed:.2f}秒")

    avg_time = sum(times) / len(times)
    success_rate = (trajectories[:, -1] > 0).sum() / len(trajectories) * 100

    print(f"\n平均时间: {avg_time:.2f}秒")
    print(f"成功率: {success_rate:.1f}%")

    if avg_time < 2.0:
        print("✅ 性能优秀！用户体验良好（< 2秒）")
    elif avg_time < 5.0:
        print("✓ 性能良好（2-5秒）")
    else:
        print("⚠️  仍有优化空间（> 5秒）")

    return avg_time


if __name__ == "__main__":
    try:
        benchmark_realistic_scenario()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
