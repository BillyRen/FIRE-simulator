"""统计分析与结果汇总模块。"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


PERCENTILES = [5, 10, 25, 50, 75, 90, 95]


@dataclass
class SimulationResults:
    """模拟结果的汇总数据。"""

    # 基本统计
    success_rate: float  # 成功率 (0-1)
    num_simulations: int
    retirement_years: int

    # 逐年分位数轨迹: shape (len(PERCENTILES), retirement_years+1)
    percentile_trajectories: dict[int, np.ndarray]

    # 最终资产分布统计
    final_values: np.ndarray  # 所有模拟的最终资产值
    final_mean: float
    final_median: float
    final_percentiles: dict[int, float]  # {5: ..., 10: ..., ...}
    final_min: float
    final_max: float

    # 提取金额统计（动态策略时各模拟路径不同，固定策略时全部相同）
    withdrawal_percentile_trajectories: dict[int, np.ndarray] | None = None
    withdrawal_mean_trajectory: np.ndarray | None = None


def compute_statistics(
    trajectories: np.ndarray,
    retirement_years: int,
    withdrawals: np.ndarray | None = None,
) -> SimulationResults:
    """根据资产轨迹矩阵计算统计结果。

    Parameters
    ----------
    trajectories : np.ndarray
        shape (num_simulations, retirement_years + 1) 的资产轨迹矩阵。
    retirement_years : int
        退休年限。
    withdrawals : np.ndarray or None
        shape (num_simulations, retirement_years) 的提取金额矩阵。可选。

    Returns
    -------
    SimulationResults
        汇总统计数据。
    """
    num_simulations = trajectories.shape[0]

    # 最终资产值
    final_values = trajectories[:, -1]

    # 成功率：最终资产 > 0
    success_rate = float(np.mean(final_values > 0))

    # 逐年分位数轨迹
    percentile_trajectories: dict[int, np.ndarray] = {}
    for p in PERCENTILES:
        percentile_trajectories[p] = np.percentile(trajectories, p, axis=0)

    # 最终资产分布统计
    final_percentiles: dict[int, float] = {}
    for p in PERCENTILES:
        final_percentiles[p] = float(np.percentile(final_values, p))

    # 提取金额统计
    withdrawal_pct_traj: dict[int, np.ndarray] | None = None
    withdrawal_mean_traj: np.ndarray | None = None

    if withdrawals is not None:
        withdrawal_pct_traj = {}
        for p in PERCENTILES:
            withdrawal_pct_traj[p] = np.percentile(withdrawals, p, axis=0)
        withdrawal_mean_traj = np.mean(withdrawals, axis=0)

    return SimulationResults(
        success_rate=success_rate,
        num_simulations=num_simulations,
        retirement_years=retirement_years,
        percentile_trajectories=percentile_trajectories,
        final_values=final_values,
        final_mean=float(np.mean(final_values)),
        final_median=float(np.median(final_values)),
        final_percentiles=final_percentiles,
        final_min=float(np.min(final_values)),
        final_max=float(np.max(final_values)),
        withdrawal_percentile_trajectories=withdrawal_pct_traj,
        withdrawal_mean_trajectory=withdrawal_mean_traj,
    )


def final_values_summary_table(results: SimulationResults) -> pd.DataFrame:
    """生成最终资产值的统计摘要表格。

    Returns
    -------
    pd.DataFrame
        包含各分位数、均值等信息的表格。
    """
    rows = []
    rows.append({"指标": "成功率", "值": f"{results.success_rate:.1%}"})
    rows.append({"指标": "模拟次数", "值": f"{results.num_simulations:,}"})
    rows.append({"指标": "平均最终资产", "值": f"${results.final_mean:,.0f}"})
    rows.append({"指标": "最小最终资产", "值": f"${results.final_min:,.0f}"})

    for p in PERCENTILES:
        rows.append({
            "指标": f"第 {p} 百分位",
            "值": f"${results.final_percentiles[p]:,.0f}",
        })

    rows.append({"指标": "最大最终资产", "值": f"${results.final_max:,.0f}"})

    # 动态提取策略时追加提取金额统计
    if results.withdrawal_percentile_trajectories is not None:
        rows.append({"指标": "---", "值": "---"})
        rows.append({"指标": "提取金额统计（最终年）", "值": ""})
        for p in PERCENTILES:
            val = results.withdrawal_percentile_trajectories[p][-1]
            rows.append({
                "指标": f"提取 P{p}",
                "值": f"${val:,.0f}",
            })
        if results.withdrawal_mean_trajectory is not None:
            rows.append({
                "指标": "平均提取金额",
                "值": f"${results.withdrawal_mean_trajectory[-1]:,.0f}",
            })

    return pd.DataFrame(rows)
