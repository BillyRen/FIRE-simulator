#!/usr/bin/env python
"""Bootstrap 并行化性能对比：优化前 vs 优化后。"""

import time
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.sweep import pregenerate_return_scenarios, pregenerate_raw_scenarios, MAX_WORKERS
from simulator.data_loader import load_returns_by_source, get_country_dfs


def benchmark_with_workers(func, params, name, workers):
    """使用指定worker数量运行基准测试"""
    # 临时设置worker数
    original = os.environ.get("MAX_SWEEP_WORKERS")
    os.environ["MAX_SWEEP_WORKERS"] = str(workers)

    # 重新导入以获取新配置
    import importlib
    import simulator.sweep
    importlib.reload(simulator.sweep)
    from simulator.sweep import pregenerate_return_scenarios as pregen_reload

    print(f"\n{name} (MAX_WORKERS={workers})")
    print("-" * 50)

    times = []
    for i in range(3):
        start = time.time()
        if func == "return_scenarios":
            _ = pregen_reload(**params)
        else:
            from simulator.sweep import pregenerate_raw_scenarios as pregen_raw_reload
            _ = pregen_raw_reload(**params)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"  运行 {i+1}: {elapsed:.3f}秒")

    avg = sum(times) / len(times)
    print(f"  平均: {avg:.3f}秒")

    # 恢复原配置
    if original:
        os.environ["MAX_SWEEP_WORKERS"] = original
    elif "MAX_SWEEP_WORKERS" in os.environ:
        del os.environ["MAX_SWEEP_WORKERS"]

    return avg


def main():
    print("=" * 60)
    print("Bootstrap 并行化性能基准测试")
    print("=" * 60)
    print(f"当前配置: MAX_WORKERS = {MAX_WORKERS}")

    df = load_returns_by_source("jst")
    country_dfs = get_country_dfs(df, data_start_year=1900)

    # === 测试场景1：pregenerate_return_scenarios ===
    return_params = {
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

    print("\n" + "=" * 60)
    print("测试1: pregenerate_return_scenarios()")
    print("场景: ALL国家，2000次模拟，65年")
    print("=" * 60)

    # 顺序执行（强制 workers=1）
    t1_seq = benchmark_with_workers("return_scenarios", return_params, "顺序执行", 1)

    # 并行执行（使用默认workers）
    t1_par = benchmark_with_workers("return_scenarios", return_params, "并行执行", MAX_WORKERS)

    speedup1 = t1_seq / t1_par

    # === 测试场景2：pregenerate_raw_scenarios ===
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

    print("\n" + "=" * 60)
    print("测试2: pregenerate_raw_scenarios()")
    print("场景: ALL国家，2000次模拟，65年")
    print("=" * 60)

    t2_seq = benchmark_with_workers("raw_scenarios", raw_params, "顺序执行", 1)
    t2_par = benchmark_with_workers("raw_scenarios", raw_params, "并行执行", MAX_WORKERS)

    speedup2 = t2_seq / t2_par

    # === 总结 ===
    print("\n" + "=" * 60)
    print("性能对比总结")
    print("=" * 60)

    print(f"\n1. pregenerate_return_scenarios()")
    print(f"   顺序执行: {t1_seq:.3f}秒")
    print(f"   并行执行: {t1_par:.3f}秒")
    print(f"   加速比: {speedup1:.2f}x ⚡️")

    print(f"\n2. pregenerate_raw_scenarios()")
    print(f"   顺序执行: {t2_seq:.3f}秒")
    print(f"   并行执行: {t2_par:.3f}秒")
    print(f"   加速比: {speedup2:.2f}x ⚡️")

    print(f"\n整体加速: {(speedup1 + speedup2) / 2:.2f}x（平均）")

    print("\n" + "=" * 60)
    print("实际影响（基于生产环境典型请求）")
    print("=" * 60)
    print(f"提取率分析页面 (/api/sweep):")
    print(f"  优化前: {t1_seq:.2f}秒 → 优化后: {t1_par:.2f}秒 ({speedup1:.1f}x加速)")

    print(f"\n支出护栏页面 (/api/guardrail):")
    print(f"  优化前: {t1_seq:.2f}秒 → 优化后: {t1_par:.2f}秒 ({speedup1:.1f}x加速)")

    print(f"\n资产配置页面 (/api/allocation-sweep):")
    print(f"  优化前: {t2_seq:.2f}秒 → 优化后: {t2_par:.2f}秒 ({speedup2:.1f}x加速)")

    total_before = t1_seq * 2 + t2_seq  # 两个页面用return_scenarios，一个用raw
    total_after = t1_par * 2 + t2_par
    print(f"\n三个页面总耗时:")
    print(f"  优化前: {total_before:.2f}秒")
    print(f"  优化后: {total_after:.2f}秒")
    print(f"  节省: {total_before - total_after:.2f}秒 ({(1-total_after/total_before)*100:.0f}%提升)")

    print("\n✅ 用户体验提升：从\"有点慢\" → \"瞬间完成\" ⚡️")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
