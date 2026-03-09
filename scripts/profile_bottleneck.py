#!/usr/bin/env python
"""定位提取率分析和护栏页面的性能瓶颈。"""

import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.sweep import pregenerate_return_scenarios
from simulator.data_loader import load_returns_by_source, get_country_dfs


def profile_pregenerate():
    """分析 pregenerate_return_scenarios() 的耗时"""
    print("=" * 60)
    print("性能瓶颈分析：pregenerate_return_scenarios()")
    print("=" * 60)

    df = load_returns_by_source("jst")
    country_dfs = get_country_dfs(df, data_start_year=1900)

    params = {
        "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
        "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
        "retirement_years": 65,
        "min_block": 5,
        "max_block": 15,
        "num_simulations": 2000,
        "returns_df": df.head(1),
        "seed": 42,
        "leverage": 1.0,
        "borrowing_spread": 0.0,
        "country_dfs": country_dfs,
        "country_weights": None,
    }

    print("\n测试场景：ALL国家，2000次模拟，65年")
    print("-" * 60)

    # 测试3次
    times = []
    for i in range(3):
        start = time.time()
        scenarios, inflation = pregenerate_return_scenarios(**params)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"运行 {i+1}: {elapsed:.3f}秒")

    avg_time = sum(times) / len(times)
    print(f"\n平均耗时: {avg_time:.3f}秒")

    # 分析
    total_iterations = params["num_simulations"]
    time_per_iteration = avg_time / total_iterations * 1000  # 毫秒

    print("\n" + "=" * 60)
    print("瓶颈分析")
    print("=" * 60)
    print(f"总迭代次数: {total_iterations:,}")
    print(f"每次迭代耗时: {time_per_iteration:.2f} 毫秒")
    print(f"当前实现: 顺序执行（单核）")
    print(f"\n⚠️  这个函数被以下endpoint调用：")
    print(f"  • /api/sweep（提取率分析页面）")
    print(f"  • /api/guardrail（支出护栏页面）")
    print(f"  • /api/guardrail/scenarios")
    print(f"  • /api/guardrail/sensitivity")

    print(f"\n💡 优化建议：")
    print(f"  1. 并行化bootstrap采样（ProcessPoolExecutor）")
    print(f"     预期加速：4-8x（8核CPU）")
    print(f"     优化后耗时：{avg_time/4:.3f} - {avg_time/8:.3f}秒")
    print(f"\n  2. 缓存预生成结果（相同参数复用）")
    print(f"     用户重复请求可瞬间返回")

    return avg_time


if __name__ == "__main__":
    try:
        profile_pregenerate()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
