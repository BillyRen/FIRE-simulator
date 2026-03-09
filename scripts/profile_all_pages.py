#!/usr/bin/env python
"""全面分析三个慢页面的性能瓶颈。"""

import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.sweep import pregenerate_return_scenarios, pregenerate_raw_scenarios, sweep_allocations
from simulator.data_loader import load_returns_by_source, get_country_dfs


def profile_page(page_name: str, func, params, desc):
    """分析单个页面的性能"""
    print(f"\n{'='*60}")
    print(f"{page_name}")
    print(f"{'='*60}")
    print(f"调用链: {desc}")
    print("-" * 60)

    times = []
    for i in range(3):
        start = time.time()
        result = func(**params)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"运行 {i+1}: {elapsed:.3f}秒")

    avg_time = sum(times) / len(times)
    print(f"平均耗时: {avg_time:.3f}秒")
    return avg_time


def main():
    print("=" * 60)
    print("FIRE模拟器 - 三大慢页面性能分析")
    print("=" * 60)

    df = load_returns_by_source("jst")
    country_dfs = get_country_dfs(df, data_start_year=1900)

    base_params = {
        "retirement_years": 65,
        "min_block": 5,
        "max_block": 15,
        "num_simulations": 2000,
        "returns_df": df.head(1),
        "seed": 42,
        "country_dfs": country_dfs,
        "country_weights": None,
    }

    # ===========================
    # 1. 提取率分析页面
    # ===========================
    sweep_params = {
        **base_params,
        "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
        "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
        "leverage": 1.0,
        "borrowing_spread": 0.0,
    }

    t1 = profile_page(
        "1️⃣  提取率分析页面 (/api/sweep)",
        pregenerate_return_scenarios,
        sweep_params,
        "pregenerate_return_scenarios() [顺序循环2000次] → sweep_withdrawal_rates() [已并行化✓]"
    )

    # ===========================
    # 2. 支出护栏页面
    # ===========================
    guardrail_params = sweep_params.copy()

    t2 = profile_page(
        "2️⃣  支出护栏页面 (/api/guardrail)",
        pregenerate_return_scenarios,
        guardrail_params,
        "pregenerate_return_scenarios() [顺序循环2000次] → build_success_rate_table() → run_guardrail_simulation()"
    )

    # ===========================
    # 3. 资产配置页面
    # ===========================
    allocation_params = {
        "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
        "retirement_years": 65,
        "min_block": 5,
        "max_block": 15,
        "num_simulations": 2000,
        "returns_df": df.head(1),
        "seed": 42,
        "country_dfs": country_dfs,
        "country_weights": None,
    }

    t3 = profile_page(
        "3️⃣  资产配置页面 (/api/allocation-sweep)",
        pregenerate_raw_scenarios,
        allocation_params,
        "pregenerate_raw_scenarios() [顺序循环2000次] → sweep_allocations() [已并行化✓]"
    )

    # ===========================
    # 总结分析
    # ===========================
    print("\n" + "=" * 60)
    print("🔍 瓶颈分析总结")
    print("=" * 60)

    print("\n【共同瓶颈】三个页面都卡在 Bootstrap 采样的顺序循环：")
    print(f"  • 提取率分析页面: {t1:.3f}秒 ← pregenerate_return_scenarios()")
    print(f"  • 支出护栏页面:   {t2:.3f}秒 ← pregenerate_return_scenarios()")
    print(f"  • 资产配置页面:   {t3:.3f}秒 ← pregenerate_raw_scenarios()")

    print("\n【瓶颈代码】simulator/sweep.py")
    print("  Line 74-88:  pregenerate_return_scenarios() - for i in range(2000) ❌")
    print("  Line 497-510: pregenerate_raw_scenarios()    - for i in range(2000) ❌")

    print("\n【已优化部分】✅")
    print("  • sweep_allocations()     - 已并行化（line 441-446）")
    print("  • sweep_withdrawal_rates() - 已并行化（line 306-311）")
    print("  • Monte Carlo核心循环    - 已向量化（fixed策略）")

    print("\n【优化方案】并行化 Bootstrap 采样")
    print("  1️⃣  并行化 pregenerate_return_scenarios()")
    print("     预期加速: 4-8x")
    print(f"     优化后:   {t1/4:.3f}秒 - {t1/8:.3f}秒")
    print(f"     影响页面: 提取率分析 + 支出护栏（两个最常用页面）")

    print("\n  2️⃣  并行化 pregenerate_raw_scenarios()")
    print("     预期加速: 4-8x")
    print(f"     优化后:   {t3/4:.3f}秒 - {t3/8:.3f}秒")
    print(f"     影响页面: 资产配置")

    print("\n【整体影响】")
    total_before = t1 + t2 + t3
    total_after = t1/6 + t2/6 + t3/6  # 保守估计6x加速
    print(f"  • 三个页面总耗时: {total_before:.2f}秒 → {total_after:.2f}秒")
    print(f"  • 节省时间: {total_before - total_after:.2f}秒（{(1-total_after/total_before)*100:.0f}%提升）")
    print(f"  • 用户体验: 从\"有点慢\" → \"瞬间完成\" ⚡️")

    print("\n【实施优先级】")
    print("  🔥 高优先级: pregenerate_return_scenarios()（影响2个最常用页面）")
    print("  🔸 中优先级: pregenerate_raw_scenarios()（影响1个页面）")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
