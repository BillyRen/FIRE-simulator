#!/usr/bin/env python
"""性能基准测试脚本：对比优化前后的模拟速度。"""

import time
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulator.monte_carlo import run_simulation
from simulator.data_loader import load_returns_by_source, get_country_dfs


def benchmark_single_country():
    """单国模拟基准测试"""
    print("=" * 60)
    print("基准测试：单国模拟（USA，2000次，30年）")
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
        "num_simulations": 2000,
        "returns_df": usa_df,
        "seed": 42,
        "withdrawal_strategy": "fixed",
    }

    # 预热
    print("\n预热运行...")
    _ = run_simulation(**params)

    # 正式测试（3次取平均）
    times = []
    for i in range(3):
        start = time.time()
        trajectories, withdrawals, real_returns, inflation = run_simulation(**params)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"运行 {i+1}: {elapsed:.2f}秒")

    avg_time = sum(times) / len(times)
    print(f"\n平均时间: {avg_time:.2f}秒")
    print(f"成功率: {(trajectories[:, -1] > 0).sum() / len(trajectories) * 100:.1f}%")

    return avg_time


def benchmark_multi_country():
    """多国池化模拟基准测试"""
    print("\n" + "=" * 60)
    print("基准测试：多国池化模拟（ALL，1000次，30年）")
    print("=" * 60)

    # 加载数据
    df = load_returns_by_source("jst")
    country_dfs = get_country_dfs(df, data_start_year=1900)

    # 测试参数
    params = {
        "initial_portfolio": 1_000_000,
        "annual_withdrawal": 40_000,
        "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
        "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
        "retirement_years": 30,
        "min_block": 5,
        "max_block": 15,
        "num_simulations": 1000,  # 减少到1000以节省时间
        "returns_df": df.head(1),  # placeholder
        "seed": 42,
        "withdrawal_strategy": "fixed",
        "country_dfs": country_dfs,
        "country_weights": None,  # 等概率
    }

    # 预热
    print("\n预热运行...")
    _ = run_simulation(**params)

    # 正式测试（3次取平均）
    times = []
    for i in range(3):
        start = time.time()
        trajectories, withdrawals, real_returns, inflation = run_simulation(**params)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"运行 {i+1}: {elapsed:.2f}秒")

    avg_time = sum(times) / len(times)
    print(f"\n平均时间: {avg_time:.2f}秒")
    print(f"成功率: {(trajectories[:, -1] > 0).sum() / len(trajectories) * 100:.1f}%")

    return avg_time


def benchmark_with_glide_path():
    """带glide path的模拟基准测试"""
    print("\n" + "=" * 60)
    print("基准测试：Glide Path模拟（USA，1000次，30年）")
    print("=" * 60)

    # 加载数据
    df = load_returns_by_source("jst")
    usa_df = df[df["Country"] == "USA"].reset_index(drop=True)

    # 测试参数（包含glide path）
    params = {
        "initial_portfolio": 1_000_000,
        "annual_withdrawal": 40_000,
        "allocation": {"domestic_stock": 0.8, "global_stock": 0.1, "domestic_bond": 0.1},
        "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
        "retirement_years": 30,
        "min_block": 5,
        "max_block": 15,
        "num_simulations": 1000,
        "returns_df": usa_df,
        "seed": 42,
        "withdrawal_strategy": "fixed",
        "glide_path_end_allocation": {"domestic_stock": 0.4, "global_stock": 0.1, "domestic_bond": 0.5},
        "glide_path_years": 20,
    }

    # 预热
    print("\n预热运行...")
    _ = run_simulation(**params)

    # 正式测试（3次取平均）
    times = []
    for i in range(3):
        start = time.time()
        trajectories, withdrawals, real_returns, inflation = run_simulation(**params)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"运行 {i+1}: {elapsed:.2f}秒")

    avg_time = sum(times) / len(times)
    print(f"\n平均时间: {avg_time:.2f}秒")
    print(f"成功率: {(trajectories[:, -1] > 0).sum() / len(trajectories) * 100:.1f}%")

    return avg_time


if __name__ == "__main__":
    print("FIRE Simulator 性能基准测试")
    print("=" * 60)
    print("优化内容：")
    print("  1. Bootstrap数组预分配（消除list.append + concatenate）")
    print("  2. Glide path向量化（预计算权重矩阵）")
    print("=" * 60)

    try:
        t1 = benchmark_single_country()
        t2 = benchmark_multi_country()
        t3 = benchmark_with_glide_path()

        print("\n" + "=" * 60)
        print("总结")
        print("=" * 60)
        print(f"单国模拟（2000次）: {t1:.2f}秒")
        print(f"多国模拟（1000次）: {t2:.2f}秒")
        print(f"Glide Path（1000次）: {t3:.2f}秒")
        print("\n提示：与优化前对比，应看到5-15%的性能提升。")
        print("      完全向量化Monte Carlo循环可获得10-50x加速（Phase 2.1后续工作）。")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
