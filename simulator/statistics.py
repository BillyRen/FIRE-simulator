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

    # Funded Ratio（资金覆盖率）
    funded_ratio: float = 0.0

    # 提取金额统计（动态策略时各模拟路径不同，固定策略时全部相同）
    withdrawal_percentile_trajectories: dict[int, np.ndarray] | None = None
    withdrawal_mean_trajectory: np.ndarray | None = None


def compute_funded_ratio(
    trajectories: np.ndarray,
    retirement_years: int,
) -> float:
    """从轨迹矩阵计算 Funded Ratio（资金覆盖率）。

    对每条模拟路径，找到资产首次 <= 0 的年份（depletion year），
    然后计算 mean(min(depletion_year / retirement_years, 1.0))。

    Parameters
    ----------
    trajectories : np.ndarray
        shape (num_simulations, retirement_years + 1) 的资产轨迹矩阵。
    retirement_years : int
        退休年限。

    Returns
    -------
    float
        Funded Ratio，范围 [0, 1]。
    """
    num_sims = trajectories.shape[0]
    # 跳过第 0 列（初始资产），从第 1 列开始检测
    depleted = trajectories[:, 1:] <= 0  # shape (num_sims, retirement_years)

    depletion_years = np.full(num_sims, float(retirement_years))
    for i in range(num_sims):
        idx = np.where(depleted[i])[0]
        if len(idx) > 0:
            depletion_years[i] = float(idx[0])  # 第几年首次 <= 0

    return float(np.mean(np.minimum(depletion_years / retirement_years, 1.0)))


CONSUMPTION_FLOOR = 0.50


def compute_effective_funded_ratio(
    withdrawals: np.ndarray,
    initial_withdrawal: float,
    retirement_years: int,
    consumption_floor: float = CONSUMPTION_FLOOR,
    trajectories: np.ndarray | None = None,
) -> tuple[float, float]:
    """消费地板调整后的 funded_ratio 和 success_rate。

    护栏策略通过削减消费避免资产归零，导致传统 funded_ratio 虚高。
    本函数将"年消费低于 initial_withdrawal * consumption_floor"视为等效耗尽，
    与传统资产归零耗尽取较早者。

    Returns (effective_funded_ratio, effective_success_rate).
    """
    num_sims = withdrawals.shape[0]
    n_years = withdrawals.shape[1]

    floor_val = initial_withdrawal * consumption_floor
    below_floor = withdrawals < floor_val  # (num_sims, n_years)

    eff_depletion = np.full(num_sims, float(n_years))
    for i in range(num_sims):
        idx = np.where(below_floor[i])[0]
        if len(idx) > 0:
            eff_depletion[i] = float(idx[0])

    if trajectories is not None:
        depleted = trajectories[:, 1:] <= 0
        asset_depletion = np.full(num_sims, float(n_years))
        for i in range(num_sims):
            idx = np.where(depleted[i])[0]
            if len(idx) > 0:
                asset_depletion[i] = float(idx[0])
        eff_depletion = np.minimum(eff_depletion, asset_depletion)

    funded = float(np.mean(np.minimum(eff_depletion / retirement_years, 1.0)))
    success = float(np.mean(eff_depletion >= n_years))
    return funded, success


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

    # Funded Ratio
    funded_ratio = compute_funded_ratio(trajectories, retirement_years)

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
        funded_ratio=funded_ratio,
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


# ---------------------------------------------------------------------------
# 投资组合绩效指标（分位数表格）
# ---------------------------------------------------------------------------

METRIC_PERCENTILES = [10, 25, 50, 75, 90]


def compute_portfolio_metrics(
    real_returns_matrix: np.ndarray,
    inflation_matrix: np.ndarray,
) -> list[dict[str, str]]:
    """根据每条路径的实际回报和通胀，计算投资组合绩效指标的分位数表。

    计算 5 个指标（每条路径一个标量），然后取 P10/P25/P50/P75/P90。

    Parameters
    ----------
    real_returns_matrix : np.ndarray
        shape (num_simulations, retirement_years) 的实际组合回报率矩阵。
    inflation_matrix : np.ndarray
        shape (num_simulations, retirement_years) 的通胀率矩阵。

    Returns
    -------
    list[dict[str, str]]
        每行一个指标，包含 "metric", "P10", "P25", "P50", "P75", "P90" 键。
    """
    num_sims, n_years = real_returns_matrix.shape

    # 名义回报 = (1 + real) * (1 + inflation) - 1
    nominal_returns_matrix = (
        (1.0 + real_returns_matrix) * (1.0 + inflation_matrix) - 1.0
    )

    # --- 每条路径的标量指标 ---

    # 1. 年化名义回报（几何平均）
    ann_nominal = np.prod(1.0 + nominal_returns_matrix, axis=1) ** (1.0 / n_years) - 1.0

    # 2. 年化实际回报（几何平均）
    ann_real = np.prod(1.0 + real_returns_matrix, axis=1) ** (1.0 / n_years) - 1.0

    # 3. 年化通胀（几何平均）
    ann_inflation = np.prod(1.0 + inflation_matrix, axis=1) ** (1.0 / n_years) - 1.0

    # 4. 年化波动率（实际回报的样本标准差）
    ann_volatility = np.std(real_returns_matrix, axis=1, ddof=1)

    # 5. 最大实际回撤（基于累积实际回报指数，纯投资表现）
    cum_real = np.cumprod(1.0 + real_returns_matrix, axis=1)  # (num_sims, n_years)
    running_max = np.maximum.accumulate(cum_real, axis=1)
    drawdowns = (cum_real - running_max) / running_max  # 负值
    max_drawdown = np.min(drawdowns, axis=1)  # 每条路径的最大回撤（负值）

    # --- 汇总为分位数表 ---
    metrics_data = [
        ("ann_nominal_return", ann_nominal),
        ("ann_real_return", ann_real),
        ("ann_inflation", ann_inflation),
        ("ann_volatility", ann_volatility),
        ("max_real_drawdown", max_drawdown),
    ]

    rows: list[dict[str, str]] = []
    for metric_key, values in metrics_data:
        row: dict[str, str] = {"metric": metric_key}
        for p in METRIC_PERCENTILES:
            row[f"P{p}"] = f"{float(np.percentile(values, p)):.2%}"
        rows.append(row)

    return rows


def compute_single_path_metrics(
    real_returns: np.ndarray,
    inflation: np.ndarray,
) -> list[dict[str, str]]:
    """计算单条历史路径的投资组合绩效指标。

    Parameters
    ----------
    real_returns : np.ndarray
        1-D 实际组合回报率序列，长度 n_years。
    inflation : np.ndarray
        1-D 通胀率序列，长度 n_years。

    Returns
    -------
    list[dict[str, str]]
        每行一个指标，包含 "metric" 和 "value" 键。
    """
    n = len(real_returns)
    if n == 0:
        return []

    # 名义回报
    nominal_returns = (1.0 + real_returns) * (1.0 + inflation) - 1.0

    ann_nominal = float(np.prod(1.0 + nominal_returns) ** (1.0 / n) - 1.0)
    ann_real = float(np.prod(1.0 + real_returns) ** (1.0 / n) - 1.0)
    ann_infl = float(np.prod(1.0 + inflation) ** (1.0 / n) - 1.0)
    vol = float(np.std(real_returns, ddof=1)) if n > 1 else 0.0

    # 最大实际回撤
    cum = np.cumprod(1.0 + real_returns)
    running_max = np.maximum.accumulate(cum)
    dd = (cum - running_max) / running_max
    max_dd = float(np.min(dd))

    return [
        {"metric": "ann_nominal_return", "value": f"{ann_nominal:.2%}"},
        {"metric": "ann_real_return", "value": f"{ann_real:.2%}"},
        {"metric": "ann_inflation", "value": f"{ann_infl:.2%}"},
        {"metric": "ann_volatility", "value": f"{vol:.2%}"},
        {"metric": "max_real_drawdown", "value": f"{max_dd:.2%}"},
    ]
