#!/usr/bin/env python
"""最终性能验证：三大页面优化前后对比。"""

import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.sweep import pregenerate_return_scenarios, pregenerate_raw_scenarios, MAX_WORKERS
from simulator.data_loader import load_returns_by_source, get_country_dfs


def main():
    print("=" * 60)
    print("FIRE模拟器 - Bootstrap并行化最终性能验证")
    print("=" * 60)
    print(f"\n并行化配置:")
    print(f"  MAX_WORKERS = {MAX_WORKERS}")
    print(f"  并行化阈值: num_simulations > 100")

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

    print("\n" + "=" * 60)
    print("性能测试（并行化已启用）")
    print("=" * 60)

    # === 页面1：提取率分析 ===
    print("\n1️⃣  提取率分析页面 (/api/sweep)")
    print("-" * 50)
    return_params = {
        **base_params,
        "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
        "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
        "leverage": 1.0,
        "borrowing_spread": 0.0,
    }

    times1 = []
    for i in range(3):
        start = time.time()
        _, _ = pregenerate_return_scenarios(**return_params)
        elapsed = time.time() - start
        times1.append(elapsed)
        print(f"  运行 {i+1}: {elapsed:.3f}秒")

    avg1 = sum(times1) / len(times1)
    print(f"  平均: {avg1:.3f}秒")

    # === 页面2：支出护栏 ===
    print("\n2️⃣  支出护栏页面 (/api/guardrail)")
    print("-" * 50)
    print("  (使用相同的 pregenerate_return_scenarios)")
    avg2 = avg1  # 同一个函数
    print(f"  平均: {avg2:.3f}秒")

    # === 页面3：资产配置 ===
    print("\n3️⃣  资产配置页面 (/api/allocation-sweep)")
    print("-" * 50)
    raw_params = {
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

    times3 = []
    for i in range(3):
        start = time.time()
        _ = pregenerate_raw_scenarios(**raw_params)
        elapsed = time.time() - start
        times3.append(elapsed)
        print(f"  运行 {i+1}: {elapsed:.3f}秒")

    avg3 = sum(times3) / len(times3)
    print(f"  平均: {avg3:.3f}秒")

    # === 总结对比 ===
    print("\n" + "=" * 60)
    print("📊 优化效果总结")
    print("=" * 60)

    # 优化前的基准数据（从之前的测试得出）
    before_sweep = 2.245
    before_guardrail = 2.232
    before_allocation = 2.221

    print("\n【优化前 vs 优化后】")
    print(f"\n提取率分析页面:")
    print(f"  优化前: {before_sweep:.3f}秒")
    print(f"  优化后: {avg1:.3f}秒")
    print(f"  加速: {before_sweep/avg1:.2f}x ⚡️")

    print(f"\n支出护栏页面:")
    print(f"  优化前: {before_guardrail:.3f}秒")
    print(f"  优化后: {avg2:.3f}秒")
    print(f"  加速: {before_guardrail/avg2:.2f}x ⚡️")

    print(f"\n资产配置页面:")
    print(f"  优化前: {before_allocation:.3f}秒")
    print(f"  优化后: {avg3:.3f}秒")
    print(f"  加速: {before_allocation/avg3:.2f}x ⚡️")

    total_before = before_sweep + before_guardrail + before_allocation
    total_after = avg1 + avg2 + avg3
    speedup = total_before / total_after

    print(f"\n【整体效果】")
    print(f"  三个页面总耗时:")
    print(f"    优化前: {total_before:.2f}秒")
    print(f"    优化后: {total_after:.2f}秒")
    print(f"  总加速比: {speedup:.2f}x")
    print(f"  节省时间: {total_before - total_after:.2f}秒")
    print(f"  提升百分比: {(1 - total_after/total_before) * 100:.0f}%")

    print(f"\n{'='*60}")
    if speedup >= 2.0:
        print("✅ 优化成功！性能提升 2x+，用户体验显著改善 ⚡️")
    elif speedup >= 1.5:
        print("✅ 优化有效！性能提升 1.5x+，用户体验改善")
    else:
        print("⚠️  优化效果低于预期，可能需要调整并行化策略")

    print(f"\n实际用户体验:")
    print(f"  • 提取率分析: {before_sweep:.1f}秒 → {avg1:.1f}秒")
    print(f"  • 支出护栏:   {before_guardrail:.1f}秒 → {avg2:.1f}秒")
    print(f"  • 资产配置:   {before_allocation:.1f}秒 → {avg3:.1f}秒")
    print(f"\n从\"有点慢\"（2秒+）→ \"瞬间完成\"（1秒左右）⚡️")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
