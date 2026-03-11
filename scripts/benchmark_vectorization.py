#!/usr/bin/env python
"""向量化效果专项测试：对比原版vs向量化版本。"""

import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.monte_carlo import run_simulation, run_simulation_vectorized_fixed
from simulator.data_loader import load_returns_by_source


def benchmark_vectorization_speedup():
    """对比向量化前后的性能"""
    print("=" * 60)
    print("向量化效果测试：USA单国，4000次模拟，30年")
    print("=" * 60)

    # 加载数据
    df = load_returns_by_source("jst")
    usa_df = df[df["Country"] == "USA"].reset_index(drop=True)

    # 测试参数
    params = {
        "initial_portfolio": 1_000_000,
        "annual_withdrawal": 40_000,
        "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
        "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
        "retirement_years": 30,
        "min_block": 5,
        "max_block": 15,
        "num_simulations": 4000,
        "returns_df": usa_df,
        "seed": 42,
        "leverage": 1.0,
        "borrowing_spread": 0.0,
    }

    # 测试向量化版本（run_simulation会自动使用）
    print("\n使用向量化版本（自动检测）...")
    times_vectorized = []
    for i in range(3):
        start = time.time()
        traj, wd, ret, inf = run_simulation(**params, withdrawal_strategy="fixed")
        elapsed = time.time() - start
        times_vectorized.append(elapsed)
        print(f"  运行 {i+1}: {elapsed:.3f}秒")

    avg_vectorized = sum(times_vectorized) / len(times_vectorized)

    # 测试原版（强制使用dynamic策略触发通用实现）
    print("\n使用通用版本（dynamic策略，不触发向量化）...")
    times_generic = []
    for i in range(3):
        start = time.time()
        traj, wd, ret, inf = run_simulation(**params, withdrawal_strategy="dynamic")
        elapsed = time.time() - start
        times_generic.append(elapsed)
        print(f"  运行 {i+1}: {elapsed:.3f}秒")

    avg_generic = sum(times_generic) / len(times_generic)

    # 对比
    speedup = avg_generic / avg_vectorized
    print("\n" + "=" * 60)
    print("性能对比")
    print("=" * 60)
    print(f"向量化版本（fixed）: {avg_vectorized:.3f}秒")
    print(f"通用版本（dynamic）: {avg_generic:.3f}秒")
    print(f"加速比: {speedup:.2f}x")

    if speedup > 1.1:
        print(f"✅ 向量化有效提升 {(speedup-1)*100:.1f}%")
    else:
        print("⚠️  加速不明显，可能需要进一步优化")


if __name__ == "__main__":
    try:
        benchmark_vectorization_speedup()
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
