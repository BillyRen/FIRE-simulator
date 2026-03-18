"""Risk-based Guardrail 策略引擎。

核心思路：预构建 2D 成功率查找表 success_rate(withdrawal_rate, remaining_years)，
使模拟中每年的成功率查询变为 O(1) 插值操作，避免嵌套模拟。
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from simulator.cashflow import CashFlowItem, build_cf_schedule, build_cf_split_schedules, build_expected_cf_schedule, has_probabilistic_cf, sample_cash_flows
from simulator.config import (
    GUARDRAIL_RATE_MIN,
    GUARDRAIL_RATE_SEGMENTS, GUARDRAIL_CF_RATE_SEGMENTS,
    GUARDRAIL_CF_SCALE_SEGMENTS,
    build_nonuniform_grid,
    is_low_memory,
)


# ---------------------------------------------------------------------------
# 1. 查找表构建（不含现金流 — 查找表基于比例归一化，无法纳入绝对金额）
# ---------------------------------------------------------------------------

def build_success_rate_table(
    scenarios: np.ndarray,
    rate_segments: list[tuple[float, float]] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """构建 2D 成功率查找表。

    对于固定提取策略，成功率只取决于 (提取率, 剩余年限)，与资产绝对值无关。
    将资产归一化为 v=1，每年 v_{t+1} = v_t * (1+r_t) - rate。

    Parameters
    ----------
    scenarios : np.ndarray
        shape (num_sims, max_years) 的实际组合回报率矩阵。
    rate_segments : list of (upper_bound, step) or None
        非均匀网格分段。None 时使用全局默认。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (rate_grid, table)
        - rate_grid: shape (num_rates,) 的提取率数组
        - table: shape (num_rates, max_years + 1) 的成功率表。
          table[i, y] = 以 rate_grid[i] 提取 y 年后仍存活的概率。
          table[:, 0] = 1.0（0 年提取，100% 成功）。
    """
    num_sims, max_years = scenarios.shape
    if rate_segments is None:
        rate_segments = GUARDRAIL_RATE_SEGMENTS
    rate_grid = build_nonuniform_grid(rate_segments, start=GUARDRAIL_RATE_MIN)
    num_rates = len(rate_grid)

    table = np.zeros((num_rates, max_years + 1))
    table[:, 0] = 1.0

    # 2D 广播：同时处理所有 rates, shape (num_rates, num_sims)
    # 使用 float32 节省 50% 内存；最终输出为 boolean mean，精度无损
    values = np.ones((num_rates, num_sims), dtype=np.float32)
    rates_col = rate_grid[:, np.newaxis].astype(np.float32)  # (num_rates, 1)
    for year in range(max_years):
        values = values * (1.0 + scenarios[np.newaxis, :, year]) - rates_col
        alive = values > 0
        values = np.where(alive, values, 0.0)
        table[:, year + 1] = np.mean(alive, axis=1)

    return rate_grid, table


# ---------------------------------------------------------------------------
# 2. 查找表查询（双线性插值）
# ---------------------------------------------------------------------------

def lookup_success_rate(
    table: np.ndarray,
    rate_grid: np.ndarray,
    rate: float,
    remaining_years: int,
) -> float:
    """从查找表中插值查询成功率。

    对 rate 维度做线性插值，remaining_years 取整数索引。
    """
    max_years = table.shape[1] - 1
    remaining_years = min(remaining_years, max_years)
    remaining_years = max(remaining_years, 0)

    if rate <= rate_grid[0]:
        return float(table[0, remaining_years])
    if rate >= rate_grid[-1]:
        return float(table[-1, remaining_years])

    idx = np.searchsorted(rate_grid, rate) - 1
    idx = max(0, min(idx, len(rate_grid) - 2))

    # 防止除零：如果相邻 rate_grid 值相等，直接返回下限值
    denominator = rate_grid[idx + 1] - rate_grid[idx]
    if abs(denominator) < 1e-12:
        return float(table[idx, remaining_years])

    frac = (rate - rate_grid[idx]) / denominator

    val_low = table[idx, remaining_years]
    val_high = table[idx + 1, remaining_years]
    return float(val_low + frac * (val_high - val_low))


# ---------------------------------------------------------------------------
# 3. 反向查找：给定目标成功率和剩余年限，找到对应的提取率
# ---------------------------------------------------------------------------

def find_rate_for_target(
    table: np.ndarray,
    rate_grid: np.ndarray,
    target_success: float,
    remaining_years: int,
) -> float:
    """反向查找：给定目标成功率和剩余年限，找到对应的提取率。"""
    max_years = table.shape[1] - 1
    remaining_years = min(remaining_years, max_years)
    remaining_years = max(remaining_years, 1)

    col = table[:, remaining_years]

    if col[0] < target_success:
        return 0.0
    if col[-1] >= target_success:
        return float(rate_grid[-1])

    # col is monotonically decreasing; flip and use searchsorted for O(log n)
    # col_rev is ascending. searchsorted('left') returns idx where col_rev[idx-1] < target <= col_rev[idx]
    col_rev = col[::-1]
    idx_rev = np.searchsorted(col_rev, target_success)
    if idx_rev <= 0 or idx_rev >= len(col_rev):
        return float(rate_grid[0])

    # Map back to original: col_rev[idx_rev] = col[n-1-idx_rev], col_rev[idx_rev-1] = col[n-idx_rev]
    # Original linear scan finds i where col[i] >= target > col[i+1]
    # col_rev[idx_rev] >= target → original i = n-1-idx_rev
    i = len(col) - 1 - idx_rev
    i = max(0, min(i, len(col) - 2))
    denom = col[i] - col[i + 1]
    if abs(denom) < 1e-12:
        return float(rate_grid[i])
    frac = (target_success - col[i + 1]) / denom
    return float(rate_grid[i + 1] + frac * (rate_grid[i] - rate_grid[i + 1]))


# ---------------------------------------------------------------------------
# 3b. 现金流感知 3D 查找表
# ---------------------------------------------------------------------------
#
# 当存在自定义现金流时，标准 2D 表 (rate, remaining_years) 无法精确建模
# 绝对金额的现金流。3D 表新增两个维度：
#   - cf_scale = C_ref / V（现金流相对于组合的强度）
#   - start_year（不同起始年面对的未来现金流不同）
#
# 归一化公式：v_{t+1} = v_t * (1+r_t) - rate + normalized_cf[t] * cf_scale
# 与用户手动跑 MC 数学上等价。

_CF_TABLE_MAX_START_YEARS = 15
_CF_TABLE_EARLY_TERM_INTERVAL = 10


def _select_cf_start_years(
    normalized_cf: np.ndarray,
    last_cf_year: int,
    max_start_years: int = _CF_TABLE_MAX_START_YEARS,
) -> list[int]:
    """选择代表性的 start_year 子集用于 3D 表构建。

    当总 start_year 数超过阈值时，按 CF 变化幅度排序选择最重要的
    转折点，其余均匀采样填充，始终遵守 max_start_years 上限。
    """
    num_all = last_cf_year + 1
    if num_all <= max_start_years:
        return list(range(num_all))

    # 始终包含首尾
    selected: set[int] = {0, last_cf_year}
    budget = max_start_years - 2

    # 按 CF 变化幅度排序，选择最重要的转折点
    importance = np.zeros(num_all)
    importance[0] = -1.0  # 已选
    importance[last_cf_year] = -1.0  # 已选
    for y in range(1, num_all):
        importance[y] = abs(normalized_cf[y] - normalized_cf[y - 1])

    ranked = np.argsort(importance)[::-1]
    for y in ranked[:budget]:
        if importance[y] <= 1e-12:
            break
        selected.add(int(y))

    # 用均匀采样填充剩余名额
    remaining_budget = max_start_years - len(selected)
    if remaining_budget > 0:
        candidates = [y for y in range(num_all) if y not in selected]
        step = max(1, len(candidates) // (remaining_budget + 1))
        for i in range(0, len(candidates), step):
            if len(selected) >= max_start_years:
                break
            selected.add(candidates[i])

    return sorted(selected)


def _compute_sy_slice(
    sy: int,
    n_years: int,
    returns_1p: np.ndarray,
    normalized_cf: np.ndarray,
    rate_grid: np.ndarray,
    cs_grid: np.ndarray,
) -> tuple[int, np.ndarray]:
    """计算单个 start_year 的 3D 表切片（用于并行）。"""
    num_rates = len(rate_grid)
    num_cs = len(cs_grid)
    num_sims = returns_1p.shape[0]
    remaining = n_years - sy
    if remaining <= 0:
        return sy, np.ones((num_rates, num_cs))

    values = np.ones((num_rates, num_cs, num_sims), dtype=np.float32)
    rates_3d = rate_grid[:, np.newaxis, np.newaxis].astype(np.float32)
    active_r = num_rates

    for t in range(remaining):
        y = sy + t
        adj = (normalized_cf[y] * cs_grid)[np.newaxis, :, np.newaxis] - rates_3d[:active_r]
        np.multiply(values[:active_r], returns_1p[:, y], out=values[:active_r])
        values[:active_r] += adj
        np.maximum(values[:active_r], 0.0, out=values[:active_r])

        # 定期剪枝已全部失败的高提取率，减少后续计算量
        if t % _CF_TABLE_EARLY_TERM_INTERVAL == _CF_TABLE_EARLY_TERM_INTERVAL - 1 and active_r > 10:
            alive_any = np.any(values[:active_r] > 0, axis=(1, 2))
            new_end = 0
            for i in range(active_r - 1, -1, -1):
                if alive_any[i]:
                    new_end = i + 1
                    break
            active_r = max(new_end, 1)

    result = np.zeros((num_rates, num_cs))
    result[:active_r] = np.mean(values[:active_r] > 0, axis=2)
    return sy, result


_CF_DEFAULT_MAX_SIMS = 2000 if is_low_memory() else 5000


def build_cf_aware_table(
    scenarios: np.ndarray,
    cf_schedule: np.ndarray,
    rate_segments: list[tuple[float, float]] | None = None,
    cf_scale_segments: list[tuple[float, float]] | None = None,
    max_sims: int | None = None,
    max_start_years: int = _CF_TABLE_MAX_START_YEARS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, int] | None:
    """构建现金流感知的 3D 成功率查找表。

    对于固定提取策略，3D 表在 2D 表基础上增加 cf_scale 维度和 start_year
    维度，以精确建模绝对金额现金流对成功率的影响。

    各 start_year 之间互相独立，通过线程池并行加速构建。
    """
    if max_sims is None:
        max_sims = _CF_DEFAULT_MAX_SIMS
    num_sims, max_years = scenarios.shape
    if num_sims > max_sims:
        rng = np.random.default_rng(0)
        scenarios = scenarios[rng.choice(num_sims, max_sims, replace=False)]
        num_sims = max_sims
    n_years = min(len(cf_schedule), max_years)

    cf_ref = float(np.max(np.abs(cf_schedule[:n_years])))
    if cf_ref < 1e-10:
        return None

    normalized_cf = np.zeros(n_years)
    normalized_cf[:n_years] = cf_schedule[:n_years] / cf_ref

    last_cf_year = 0
    for y in range(n_years - 1, -1, -1):
        if abs(normalized_cf[y]) > 1e-12:
            last_cf_year = y
            break

    if rate_segments is None:
        rate_segments = GUARDRAIL_CF_RATE_SEGMENTS
    rate_grid = build_nonuniform_grid(rate_segments, start=GUARDRAIL_RATE_MIN)
    if cf_scale_segments is None:
        cf_scale_segments = GUARDRAIL_CF_SCALE_SEGMENTS
    cf_scale_grid = build_nonuniform_grid(cf_scale_segments, start=0.0)
    num_rates = len(rate_grid)
    num_cs = len(cf_scale_grid)
    num_start_years = last_cf_year + 1

    table_3d = np.zeros((num_rates, num_cs, num_start_years))

    selected_years = _select_cf_start_years(normalized_cf, last_cf_year, max_start_years)

    # 预计算 1+returns 避免重复加法；float32 节省内存
    returns_1p = (1.0 + scenarios[:, :n_years]).astype(np.float32)
    cf_scale_grid = cf_scale_grid.astype(np.float32)

    # 各 start_year 互相独立，用线程池并行（numpy 释放 GIL）
    # 低内存时限制为 1 worker，避免并行分配多份 (rates, cs, sims) 数组
    cpu_count = os.cpu_count() or 1
    if is_low_memory():
        max_workers = 1
    else:
        max_workers = max(1, min(cpu_count, 8, len(selected_years)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                _compute_sy_slice, sy, n_years, returns_1p,
                normalized_cf, rate_grid, cf_scale_grid,
            )
            for sy in selected_years
        ]
        for fut in as_completed(futures):
            sy, result = fut.result()
            table_3d[:, :, sy] = result

    # 对未直接计算的 start_year 做线性插值
    if len(selected_years) < num_start_years:
        selected_set = set(selected_years)
        sorted_selected = sorted(selected_years)
        for sy in range(num_start_years):
            if sy in selected_set:
                continue
            idx = np.searchsorted(sorted_selected, sy)
            lo = sorted_selected[max(0, idx - 1)]
            hi = sorted_selected[min(idx, len(sorted_selected) - 1)]
            if lo == hi:
                table_3d[:, :, sy] = table_3d[:, :, lo]
            else:
                frac = (sy - lo) / (hi - lo)
                table_3d[:, :, sy] = (
                    table_3d[:, :, lo] + frac * (table_3d[:, :, hi] - table_3d[:, :, lo])
                )

    return rate_grid, cf_scale_grid, table_3d, cf_ref, last_cf_year


def lookup_cf_aware_success_rate(
    cf_table: np.ndarray,
    rate_grid: np.ndarray,
    cf_scale_grid: np.ndarray,
    rate: float,
    cf_scale: float,
    start_year: int,
) -> float:
    """从 3D 查找表中插值查询成功率。

    对 rate 和 cf_scale 两个维度做线性插值，start_year 取整数索引。
    """
    max_sy = cf_table.shape[2] - 1
    start_year = max(0, min(start_year, max_sy))

    # rate 维度插值
    if rate <= rate_grid[0]:
        r_idx, r_frac = 0, 0.0
    elif rate >= rate_grid[-1]:
        r_idx, r_frac = len(rate_grid) - 2, 1.0
    else:
        r_idx = int(np.searchsorted(rate_grid, rate)) - 1
        r_idx = max(0, min(r_idx, len(rate_grid) - 2))
        r_frac = (rate - rate_grid[r_idx]) / (rate_grid[r_idx + 1] - rate_grid[r_idx])

    # cf_scale 维度插值
    if cf_scale <= cf_scale_grid[0]:
        cs_idx, cs_frac = 0, 0.0
    elif cf_scale >= cf_scale_grid[-1]:
        cs_idx, cs_frac = len(cf_scale_grid) - 2, 1.0
    else:
        cs_idx = int(np.searchsorted(cf_scale_grid, cf_scale)) - 1
        cs_idx = max(0, min(cs_idx, len(cf_scale_grid) - 2))
        cs_frac = (cf_scale - cf_scale_grid[cs_idx]) / (
            cf_scale_grid[cs_idx + 1] - cf_scale_grid[cs_idx]
        )

    # 双线性插值
    v00 = cf_table[r_idx, cs_idx, start_year]
    v10 = cf_table[r_idx + 1, cs_idx, start_year]
    v01 = cf_table[r_idx, cs_idx + 1, start_year]
    v11 = cf_table[r_idx + 1, cs_idx + 1, start_year]

    v0 = v00 + r_frac * (v10 - v00)
    v1 = v01 + r_frac * (v11 - v01)
    return float(v0 + cs_frac * (v1 - v0))


def find_rate_for_target_cf_aware(
    cf_table: np.ndarray,
    rate_grid: np.ndarray,
    cf_scale_grid: np.ndarray,
    target_success: float,
    cf_scale: float,
    start_year: int,
) -> float:
    """3D 表反向查找：给定目标成功率、cf_scale 和 start_year，找到对应提取率。"""
    max_sy = cf_table.shape[2] - 1
    start_year = max(0, min(start_year, max_sy))

    # 先对 cf_scale 插值，得到一条 rate vs success 曲线
    if cf_scale <= cf_scale_grid[0]:
        cs_idx, cs_frac = 0, 0.0
    elif cf_scale >= cf_scale_grid[-1]:
        cs_idx, cs_frac = len(cf_scale_grid) - 2, 1.0
    else:
        cs_idx = int(np.searchsorted(cf_scale_grid, cf_scale)) - 1
        cs_idx = max(0, min(cs_idx, len(cf_scale_grid) - 2))
        cs_frac = (cf_scale - cf_scale_grid[cs_idx]) / (
            cf_scale_grid[cs_idx + 1] - cf_scale_grid[cs_idx]
        )

    col_lo = cf_table[:, cs_idx, start_year]
    col_hi = cf_table[:, cs_idx + 1, start_year]
    col = col_lo + cs_frac * (col_hi - col_lo)

    if col[0] < target_success:
        return 0.0
    if col[-1] >= target_success:
        return float(rate_grid[-1])

    # col is monotonically decreasing; flip and use searchsorted for O(log n)
    col_rev = col[::-1]
    idx_rev = np.searchsorted(col_rev, target_success)
    if idx_rev <= 0 or idx_rev >= len(col_rev):
        return float(rate_grid[0])

    i = len(col) - 1 - idx_rev
    i = max(0, min(i, len(col) - 2))
    denom = col[i] - col[i + 1]
    if abs(denom) < 1e-12:
        return float(rate_grid[i])
    frac = (target_success - col[i + 1]) / denom
    return float(rate_grid[i + 1] + frac * (rate_grid[i] - rate_grid[i + 1]))


# ---------------------------------------------------------------------------
# 4. 护栏调整辅助函数
# ---------------------------------------------------------------------------

def apply_guardrail_adjustment(
    wd: float,
    value: float,
    current_success: float,
    target_success: float,
    adjustment_pct: float,
    adjustment_mode: str,
    remaining: int,
    table: np.ndarray,
    rate_grid: np.ndarray,
    future_cf_avg: float = 0.0,
    cf_table: np.ndarray | None = None,
    cf_scale_grid: np.ndarray | None = None,
    cf_scale: float = 0.0,
    start_year: int = 0,
) -> float:
    """根据调整模式计算护栏触发后的新提取金额。

    当 cf_table 提供时，使用 3D 表做精确查找（rate = wd/value，CFs 已烘焙进表）。
    否则使用 2D 表 + future_cf_avg 近似（向后兼容）。
    """
    if cf_table is not None and cf_scale_grid is not None:
        # 3D 表模式：rate = wd/value，表已包含现金流影响
        if adjustment_mode == "success_rate":
            adjusted_success = current_success + adjustment_pct * (
                target_success - current_success
            )
            adjusted_rate = find_rate_for_target_cf_aware(
                cf_table, rate_grid, cf_scale_grid,
                adjusted_success, cf_scale, start_year,
            )
            new_wd = value * adjusted_rate
        else:
            target_rate = find_rate_for_target_cf_aware(
                cf_table, rate_grid, cf_scale_grid,
                target_success, cf_scale, start_year,
            )
            target_wd = value * target_rate
            new_wd = wd + adjustment_pct * (target_wd - wd)
    else:
        # 2D 表模式（向后兼容）
        if adjustment_mode == "success_rate":
            adjusted_success = current_success + adjustment_pct * (
                target_success - current_success
            )
            adjusted_rate = find_rate_for_target(
                table, rate_grid, adjusted_success, remaining
            )
            new_wd = value * adjusted_rate + future_cf_avg
        else:
            target_rate = find_rate_for_target(
                table, rate_grid, target_success, remaining
            )
            target_wd = value * target_rate + future_cf_avg
            new_wd = wd + adjustment_pct * (target_wd - wd)

    # Boundary safety invariant: success_rate(rate) is monotonically decreasing,
    # so guardrail adjustments always move wd in the correct direction — UNLESS
    # rate/cf_scale is clamped at the grid boundary, breaking monotonicity.
    # This guard is a no-op within grid bounds and only activates at boundaries.
    if current_success > target_success:
        return max(new_wd, wd)
    else:
        return min(new_wd, wd)


# ---------------------------------------------------------------------------
# 5. 向量化二分法：精确查找含现金流的初始资产
# ---------------------------------------------------------------------------

def _find_portfolio_for_success(
    scenarios: np.ndarray,
    annual_withdrawal: float,
    target_success: float,
    retirement_years: int,
    cf_matrix: np.ndarray | None,
    initial_guess: float,
    max_iter: int = 25,
    tol: float = 0.005,
) -> float:
    """用向量化二分法找到使固定提取+现金流达到目标成功率的初始资产。

    Parameters
    ----------
    scenarios : np.ndarray
        shape (num_sims, max_years) 的回报矩阵。
    annual_withdrawal : float
        每年基础提取额。
    target_success : float
        目标成功率 (0-1)。
    retirement_years : int
        退休年限。
    cf_matrix : np.ndarray or None
        shape (num_sims, retirement_years) 或 (retirement_years,) 的现金流矩阵。
        None 表示无现金流。
    initial_guess : float
        初始资产的初始猜测值（用简单平均法得到的估计）。
    max_iter : int
        最大迭代次数。
    tol : float
        成功率容差，|actual - target| < tol 即停止。

    Returns
    -------
    float
        使成功率达到 target_success 的初始资产额。
    """
    num_sims = scenarios.shape[0]
    n_years = min(retirement_years, scenarios.shape[1])

    # 预处理现金流为 2D 方便向量化
    if cf_matrix is not None:
        if cf_matrix.ndim == 1:
            cf_2d = np.broadcast_to(cf_matrix[:n_years], (num_sims, n_years))
        else:
            cf_2d = cf_matrix[:, :n_years]
    else:
        cf_2d = None

    def _success_rate(portfolio: float) -> float:
        values = np.full(num_sims, portfolio, dtype=np.float64)
        alive = np.ones(num_sims, dtype=bool)
        for year in range(n_years):
            values *= (1.0 + scenarios[:, year])
            values -= annual_withdrawal
            # Apply negative CFs (expenses) before depletion check
            if cf_2d is not None:
                cf_year = cf_2d[:, year]
                neg = cf_year < 0
                values[neg] += cf_year[neg]
            values[~alive] = 0.0  # prevent zombie resurrection
            alive &= (values > 0)
            # Apply positive CFs (income) after depletion check
            if cf_2d is not None:
                pos = cf_year > 0
                values[pos & alive] += cf_year[pos & alive]
        return float(np.mean(alive))

    # 设定搜索区间
    lo = initial_guess * 0.3
    hi = initial_guess * 3.0

    # 确保区间有效
    if _success_rate(hi) < target_success:
        hi *= 3.0
    if _success_rate(lo) > target_success:
        lo *= 0.3

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        sr = _success_rate(mid)
        if abs(sr - target_success) < tol:
            return mid
        if sr < target_success:
            lo = mid  # 资产不够，需要更多
        else:
            hi = mid  # 资产过多，可以减少

    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# 5b. 向量化二分法：固定初始资产，查找达到目标成功率的年提取额
# ---------------------------------------------------------------------------

def _find_withdrawal_for_success(
    scenarios: np.ndarray,
    initial_portfolio: float,
    target_success: float,
    retirement_years: int,
    cf_matrix: np.ndarray | None,
    initial_guess: float,
    max_iter: int = 25,
    tol: float = 0.005,
) -> float:
    """用向量化二分法找到使固定提取+现金流达到目标成功率的年提取额。

    Parameters
    ----------
    scenarios : np.ndarray
        shape (num_sims, max_years) 的回报矩阵。
    initial_portfolio : float
        初始资产。
    target_success : float
        目标成功率 (0-1)。
    retirement_years : int
        退休年限。
    cf_matrix : np.ndarray or None
        shape (num_sims, retirement_years) 或 (retirement_years,) 的现金流矩阵。
    initial_guess : float
        年提取额的初始猜测值。
    max_iter : int
        最大迭代次数。
    tol : float
        成功率容差。

    Returns
    -------
    float
        使成功率达到 target_success 的年提取额。
    """
    num_sims = scenarios.shape[0]
    n_years = min(retirement_years, scenarios.shape[1])

    if cf_matrix is not None:
        if cf_matrix.ndim == 1:
            cf_2d = np.broadcast_to(cf_matrix[:n_years], (num_sims, n_years))
        else:
            cf_2d = cf_matrix[:, :n_years]
    else:
        cf_2d = None

    def _success_rate(wd: float) -> float:
        values = np.full(num_sims, initial_portfolio, dtype=np.float64)
        alive = np.ones(num_sims, dtype=bool)
        for year in range(n_years):
            values *= (1.0 + scenarios[:, year])
            values -= wd
            # Apply negative CFs (expenses) before depletion check
            if cf_2d is not None:
                cf_year = cf_2d[:, year]
                neg = cf_year < 0
                values[neg] += cf_year[neg]
            values[~alive] = 0.0  # prevent zombie resurrection
            alive &= (values > 0)
            # Apply positive CFs (income) after depletion check
            if cf_2d is not None:
                pos = cf_year > 0
                values[pos & alive] += cf_year[pos & alive]
        return float(np.mean(alive))

    lo = max(initial_guess * 0.1, 1.0)
    hi = initial_guess * 5.0

    if _success_rate(lo) < target_success:
        lo = 1.0
    if _success_rate(hi) > target_success:
        hi *= 3.0

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        sr = _success_rate(mid)
        if abs(sr - target_success) < tol:
            return mid
        if sr > target_success:
            lo = mid
        else:
            hi = mid

    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# 6. Guardrail 模拟
# ---------------------------------------------------------------------------

def run_guardrail_simulation(
    scenarios: np.ndarray,
    target_success: float,
    upper_guardrail: float,
    lower_guardrail: float,
    adjustment_pct: float,
    retirement_years: int,
    min_remaining_years: int,
    table: np.ndarray,
    rate_grid: np.ndarray,
    adjustment_mode: str = "amount",
    cash_flows: list[CashFlowItem] | None = None,
    inflation_matrix: np.ndarray | None = None,
    initial_portfolio: float | None = None,
    annual_withdrawal: float | None = None,
    cf_table: np.ndarray | None = None,
    cf_rate_grid: np.ndarray | None = None,
    cf_scale_grid: np.ndarray | None = None,
    cf_ref: float = 0.0,
    last_cf_year: int = -1,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    """运行 Risk-based Guardrail 模拟。

    提供 initial_portfolio 或 annual_withdrawal 中的一个，函数根据
    target_success 反算另一个。

    当提供 cf_table 时，对 year <= last_cf_year 使用 3D 表精确查找成功率；
    之后的年份回退到标准 2D 表。

    Returns
    -------
    tuple[float, float, np.ndarray, np.ndarray]
        (initial_portfolio, annual_withdrawal, trajectories, withdrawals)
    """
    if initial_portfolio is None and annual_withdrawal is None:
        raise ValueError("必须提供 initial_portfolio 或 annual_withdrawal 之一")

    num_sims = scenarios.shape[0]

    # 1. 预计算现金流 schedule
    has_cf = cash_flows is not None and len(cash_flows) > 0
    has_groups = has_cf and has_probabilistic_cf(cash_flows)

    rng = np.random.default_rng() if has_groups else None

    if has_groups:
        cf_matrix = np.zeros((num_sims, retirement_years))
        cf_expense_matrix = np.zeros((num_sims, retirement_years))
        cf_income_matrix = np.zeros((num_sims, retirement_years))
        for i in range(num_sims):
            active_cfs = sample_cash_flows(cash_flows, rng)
            if active_cfs:
                _adj = [cf for cf in active_cfs if cf.inflation_adjusted]
                _nom = [cf for cf in active_cfs if not cf.inflation_adjusted]
                _adj_sched = build_cf_schedule(_adj, retirement_years) if _adj else np.zeros(retirement_years)
                _adj_exp, _adj_inc = build_cf_split_schedules(_adj, retirement_years) if _adj else (np.zeros(retirement_years), np.zeros(retirement_years))
                if _nom and inflation_matrix is not None:
                    _nom_sched = build_cf_schedule(_nom, retirement_years, inflation_matrix[i])
                    _nom_exp, _nom_inc = build_cf_split_schedules(_nom, retirement_years, inflation_matrix[i])
                    cf_matrix[i] = _adj_sched + _nom_sched
                    cf_expense_matrix[i] = _adj_exp + _nom_exp
                    cf_income_matrix[i] = _adj_inc + _nom_inc
                else:
                    cf_matrix[i] = _adj_sched
                    cf_expense_matrix[i] = _adj_exp
                    cf_income_matrix[i] = _adj_inc
        fixed_cf_schedule = None
    elif has_cf:
        adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
        has_nominal = len(nominal_cfs) > 0
        fixed_cf_schedule = build_cf_schedule(adj_cfs, retirement_years)
        fixed_cf_expense, fixed_cf_income = build_cf_split_schedules(adj_cfs, retirement_years)

        if has_nominal and inflation_matrix is not None:
            cf_matrix = np.zeros((num_sims, retirement_years))
            cf_expense_matrix = np.zeros((num_sims, retirement_years))
            cf_income_matrix = np.zeros((num_sims, retirement_years))
            for i in range(num_sims):
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                nom_exp, nom_inc = build_cf_split_schedules(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                cf_matrix[i] = fixed_cf_schedule + nominal_schedule
                cf_expense_matrix[i] = fixed_cf_expense + nom_exp
                cf_income_matrix[i] = fixed_cf_income + nom_inc
        else:
            cf_matrix = np.tile(fixed_cf_schedule, (num_sims, 1))
            cf_expense_matrix = np.tile(fixed_cf_expense, (num_sims, 1))
            cf_income_matrix = np.tile(fixed_cf_income, (num_sims, 1))
    else:
        fixed_cf_schedule = None
        cf_matrix = None
        cf_expense_matrix = None
        cf_income_matrix = None

    # 2. 反算缺失的 initial_portfolio 或 annual_withdrawal
    #    如果两者都已提供，跳过反算（用于敏感性分析等固定双参数的场景）
    if initial_portfolio is not None and annual_withdrawal is not None:
        pass
    else:
        initial_rate = find_rate_for_target(table, rate_grid, target_success, retirement_years)
        if initial_rate <= 0:
            initial_rate = rate_grid[1] if len(rate_grid) > 1 else 0.01

        if initial_portfolio is not None:
            if has_cf:
                initial_guess = initial_portfolio * initial_rate
                annual_withdrawal = _find_withdrawal_for_success(
                    scenarios, initial_portfolio, target_success, retirement_years,
                    cf_matrix, initial_guess,
                )
            else:
                annual_withdrawal = initial_portfolio * initial_rate
        else:
            if has_cf:
                median_cf = float(np.median(np.mean(cf_matrix, axis=1)))
                init_cf_avg = median_cf if median_cf != 0 else (
                    float(np.mean(fixed_cf_schedule)) if fixed_cf_schedule is not None and len(fixed_cf_schedule) > 0 else 0.0
                )
                effective_wd = annual_withdrawal - init_cf_avg
                initial_guess = max(effective_wd, annual_withdrawal * 0.1) / initial_rate
                initial_portfolio = _find_portfolio_for_success(
                    scenarios, annual_withdrawal, target_success, retirement_years,
                    cf_matrix, initial_guess,
                )
            else:
                initial_portfolio = annual_withdrawal / initial_rate

    # 3. 逐年模拟
    trajectories = np.zeros((num_sims, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.zeros((num_sims, retirement_years))

    has_3d = cf_table is not None and cf_rate_grid is not None and cf_scale_grid is not None and last_cf_year >= 0

    for i in range(num_sims):
        value = initial_portfolio
        wd = annual_withdrawal

        cf_schedule = cf_matrix[i] if cf_matrix is not None else None
        cf_expense = cf_expense_matrix[i] if cf_expense_matrix is not None else None
        cf_income = cf_income_matrix[i] if cf_income_matrix is not None else None

        for year in range(retirement_years):
            remaining = max(min_remaining_years, retirement_years - year)
            use_3d = (has_3d and year <= last_cf_year
                      and retirement_years - year >= min_remaining_years)

            if value > 0:
                rate = wd / value

                # Fall back to 2D when rate or cf_scale exceeds 3D grid —
                # clamped lookups would overestimate success at high rates
                use_3d_year = use_3d
                if use_3d_year:
                    cf_scale_val = cf_ref / value
                    if rate > cf_rate_grid[-1] or cf_scale_val > cf_scale_grid[-1]:
                        use_3d_year = False

                if use_3d_year:
                    current_success = lookup_cf_aware_success_rate(
                        cf_table, cf_rate_grid, cf_scale_grid,
                        rate, cf_scale_val, year,
                    )
                else:
                    if cf_schedule is not None:
                        actual_remaining = retirement_years - year
                        future_slice = cf_schedule[year:year + actual_remaining]
                        future_cf_avg = float(np.mean(future_slice)) if len(future_slice) > 0 else 0.0
                        effective_rate = max((wd - future_cf_avg) / value, 0.0)
                    else:
                        effective_rate = rate
                        future_cf_avg = 0.0
                    current_success = lookup_success_rate(
                        table, rate_grid, effective_rate, remaining
                    )

                if current_success < lower_guardrail or current_success > upper_guardrail:
                    if use_3d_year:
                        wd = apply_guardrail_adjustment(
                            wd, value, current_success, target_success,
                            adjustment_pct, adjustment_mode, remaining,
                            table, cf_rate_grid,
                            cf_table=cf_table,
                            cf_scale_grid=cf_scale_grid,
                            cf_scale=cf_ref / value,
                            start_year=year,
                        )
                    else:
                        _cf_avg = future_cf_avg if cf_schedule is not None else 0.0
                        wd = apply_guardrail_adjustment(
                            wd, value, current_success, target_success,
                            adjustment_pct, adjustment_mode, remaining,
                            table, rate_grid,
                            future_cf_avg=_cf_avg,
                        )

            withdrawals[i, year] = wd
            value = value * (1.0 + scenarios[i, year]) - wd

            # Apply expenses before depletion check
            if cf_expense is not None and cf_expense[year] > 0:
                value -= cf_expense[year]
                withdrawals[i, year] += cf_expense[year]

            if value <= 0:
                value = 0.0
                trajectories[i, year + 1:] = 0.0
                withdrawals[i, year + 1:] = 0.0
                break

            # Apply income after depletion check
            if cf_income is not None and cf_income[year] > 0:
                value += cf_income[year]
            trajectories[i, year + 1] = value

    return initial_portfolio, annual_withdrawal, trajectories, withdrawals


def run_fixed_baseline(
    scenarios: np.ndarray,
    initial_portfolio: float,
    baseline_rate: float,
    retirement_years: int,
    cash_flows: list[CashFlowItem] | None = None,
    inflation_matrix: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """运行固定提取率基准模拟。

    Parameters
    ----------
    scenarios : np.ndarray
        回报矩阵。
    initial_portfolio : float
        初始资产。
    baseline_rate : float
        固定提取率。
    retirement_years : int
        退休年限。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_matrix : np.ndarray or None
        通胀率矩阵。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (trajectories, withdrawals)
    """
    num_sims = scenarios.shape[0]
    annual_wd = initial_portfolio * baseline_rate

    # 预计算现金流
    has_cf = cash_flows is not None and len(cash_flows) > 0
    has_groups = has_cf and has_probabilistic_cf(cash_flows)

    # ── Fast vectorized path: no cash flows ──
    if not has_cf:
        trajectories = np.zeros((num_sims, retirement_years + 1))
        trajectories[:, 0] = initial_portfolio
        withdrawals = np.full((num_sims, retirement_years), annual_wd)

        values = np.full(num_sims, initial_portfolio, dtype=np.float64)
        alive = np.ones(num_sims, dtype=bool)

        for year in range(retirement_years):
            grown = values[alive] * (1.0 + scenarios[alive, year])
            values[alive] = grown - annual_wd

            newly_failed = alive & (values <= 0)
            if np.any(newly_failed):
                values[newly_failed] = 0.0
                trajectories[newly_failed, year + 1:] = 0.0
                withdrawals[newly_failed, year + 1:] = 0.0
                alive[newly_failed] = False

            trajectories[alive, year + 1] = values[alive]

        return trajectories, withdrawals

    # ── General path with cash flows ──
    if has_cf and not has_groups:
        adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
        nominal_cfs = [cf for cf in cash_flows if not cf.inflation_adjusted]
        has_nominal = len(nominal_cfs) > 0
        fixed_cf_schedule = build_cf_schedule(adj_cfs, retirement_years)
        fixed_cf_expense, fixed_cf_income = build_cf_split_schedules(adj_cfs, retirement_years)
    else:
        fixed_cf_schedule = None
        fixed_cf_expense = None
        fixed_cf_income = None
        nominal_cfs = []
        has_nominal = False

    rng = np.random.default_rng() if has_groups else None

    trajectories = np.zeros((num_sims, retirement_years + 1))
    trajectories[:, 0] = initial_portfolio
    withdrawals = np.zeros((num_sims, retirement_years))

    for i in range(num_sims):
        value = initial_portfolio

        # 计算该路径的现金流
        if has_groups:
            active_cfs = sample_cash_flows(cash_flows, rng)
            if active_cfs:
                _adj = [cf for cf in active_cfs if cf.inflation_adjusted]
                _nom = [cf for cf in active_cfs if not cf.inflation_adjusted]
                _adj_sched = build_cf_schedule(_adj, retirement_years) if _adj else np.zeros(retirement_years)
                _adj_exp, _adj_inc = build_cf_split_schedules(_adj, retirement_years) if _adj else (np.zeros(retirement_years), np.zeros(retirement_years))
                if _nom and inflation_matrix is not None:
                    _nom_sched = build_cf_schedule(_nom, retirement_years, inflation_matrix[i])
                    _nom_exp, _nom_inc = build_cf_split_schedules(_nom, retirement_years, inflation_matrix[i])
                    cf_schedule = _adj_sched + _nom_sched
                    cf_expense = _adj_exp + _nom_exp
                    cf_income = _adj_inc + _nom_inc
                else:
                    cf_schedule = _adj_sched
                    cf_expense = _adj_exp
                    cf_income = _adj_inc
            else:
                cf_schedule = None
                cf_expense = None
                cf_income = None
        elif has_cf:
            if has_nominal and inflation_matrix is not None:
                nominal_schedule = build_cf_schedule(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                nom_exp, nom_inc = build_cf_split_schedules(
                    nominal_cfs, retirement_years, inflation_matrix[i]
                )
                cf_schedule = fixed_cf_schedule + nominal_schedule
                cf_expense = fixed_cf_expense + nom_exp
                cf_income = fixed_cf_income + nom_inc
            else:
                cf_schedule = fixed_cf_schedule
                cf_expense = fixed_cf_expense
                cf_income = fixed_cf_income
        else:
            cf_schedule = None
            cf_expense = None
            cf_income = None

        for year in range(retirement_years):
            withdrawals[i, year] = annual_wd
            value = value * (1.0 + scenarios[i, year]) - annual_wd

            # Apply expenses before depletion check
            if cf_expense is not None and cf_expense[year] > 0:
                value -= cf_expense[year]
                withdrawals[i, year] += cf_expense[year]

            if value <= 0:
                value = 0.0
                trajectories[i, year + 1:] = 0.0
                withdrawals[i, year + 1:] = 0.0
                break

            # Apply income after depletion check
            if cf_income is not None and cf_income[year] > 0:
                value += cf_income[year]
            trajectories[i, year + 1] = value

    return trajectories, withdrawals


# ---------------------------------------------------------------------------
# 6. 历史回测（单条真实路径）
# ---------------------------------------------------------------------------

def run_historical_backtest(
    real_returns: np.ndarray,
    initial_portfolio: float,
    annual_withdrawal: float,
    target_success: float,
    upper_guardrail: float,
    lower_guardrail: float,
    adjustment_pct: float,
    retirement_years: int,
    min_remaining_years: int,
    baseline_rate: float,
    table: np.ndarray,
    rate_grid: np.ndarray,
    adjustment_mode: str = "amount",
    cash_flows: list[CashFlowItem] | None = None,
    inflation_series: np.ndarray | None = None,
    cf_table: np.ndarray | None = None,
    cf_rate_grid: np.ndarray | None = None,
    cf_scale_grid: np.ndarray | None = None,
    cf_ref: float = 0.0,
    last_cf_year: int = -1,
) -> dict:
    """在单条历史回报路径上运行 guardrail 策略和固定基准策略。

    Parameters
    ----------
    real_returns : np.ndarray
        1D 数组，从起始年开始的实际组合回报序列。
    initial_portfolio : float
        初始资产。
    annual_withdrawal : float
        初始年提取金额。
    target_success : float
        目标成功率。
    upper_guardrail, lower_guardrail : float
        上下护栏。
    adjustment_pct : float
        调整百分比。
    retirement_years : int
        退休年限，会被截断到 len(real_returns)。
    min_remaining_years : int
        成功率计算的最小剩余年限。
    baseline_rate : float
        基准固定提取率。
    table, rate_grid : np.ndarray
        成功率查找表及网格。
    adjustment_mode : str
        "amount" or "success_rate"。
    cash_flows : list[CashFlowItem] or None
        自定义现金流列表。
    inflation_series : np.ndarray or None
        1D 真实历史通胀率序列（与 real_returns 等长）。
        仅在存在非通胀调整现金流时需要。

    Returns
    -------
    dict
        包含 g_portfolio, g_withdrawals, g_success_rates, b_portfolio,
        b_withdrawals, g_total_consumption, b_total_consumption 等。
    """
    n_available = len(real_returns)
    n_years = min(retirement_years, n_available)

    # 计算现金流 schedule（历史回测只有一条路径）
    has_cf = cash_flows is not None and len(cash_flows) > 0
    if has_cf:
        infl = inflation_series[:n_years] if inflation_series is not None else None
        if has_probabilistic_cf(cash_flows):
            cf_schedule = build_expected_cf_schedule(cash_flows, n_years, infl)
            # For probabilistic CFs, split the expected schedule by sign
            cf_expense = np.maximum(-cf_schedule, 0.0)
            cf_income = np.maximum(cf_schedule, 0.0)
        else:
            if any(not cf.inflation_adjusted for cf in cash_flows):
                if inflation_series is None:
                    raise ValueError(
                        "历史回测中存在非通胀调整现金流，但未提供 inflation_series"
                    )
                cf_schedule = build_cf_schedule(cash_flows, n_years, infl)
                cf_expense, cf_income = build_cf_split_schedules(cash_flows, n_years, infl)
            else:
                cf_schedule = build_cf_schedule(cash_flows, n_years)
                cf_expense, cf_income = build_cf_split_schedules(cash_flows, n_years)
    else:
        cf_schedule = None
        cf_expense = None
        cf_income = None

    # Guardrail 策略
    has_3d = cf_table is not None and cf_rate_grid is not None and cf_scale_grid is not None and last_cf_year >= 0

    g_portfolio = np.zeros(n_years + 1)
    g_portfolio[0] = initial_portfolio
    g_withdrawals = np.zeros(n_years)
    g_success_rates = np.zeros(n_years)
    adjustment_events: list[dict] = []

    value = initial_portfolio
    wd = annual_withdrawal

    for year in range(n_years):
        remaining = max(min_remaining_years, retirement_years - year)
        use_3d = (has_3d and year <= last_cf_year
                  and retirement_years - year >= min_remaining_years)

        if value > 0:
            rate = wd / value

            # Fall back to 2D when rate or cf_scale exceeds 3D grid
            use_3d_year = use_3d
            if use_3d_year:
                cf_scale_val = cf_ref / value
                if rate > cf_rate_grid[-1] or cf_scale_val > cf_scale_grid[-1]:
                    use_3d_year = False

            if use_3d_year:
                current_success = lookup_cf_aware_success_rate(
                    cf_table, cf_rate_grid, cf_scale_grid,
                    rate, cf_scale_val, year,
                )
            else:
                if cf_schedule is not None:
                    actual_remaining = retirement_years - year
                    future_slice = cf_schedule[year:year + actual_remaining]
                    future_cf_avg = float(np.mean(future_slice)) if len(future_slice) > 0 else 0.0
                    effective_rate = max((wd - future_cf_avg) / value, 0.0)
                else:
                    effective_rate = rate
                    future_cf_avg = 0.0
                current_success = lookup_success_rate(
                    table, rate_grid, effective_rate, remaining
                )
            g_success_rates[year] = current_success

            if current_success < lower_guardrail or current_success > upper_guardrail:
                old_wd = wd
                if use_3d_year:
                    wd = apply_guardrail_adjustment(
                        wd, value, current_success, target_success,
                        adjustment_pct, adjustment_mode, remaining,
                        table, cf_rate_grid,
                        cf_table=cf_table,
                        cf_scale_grid=cf_scale_grid,
                        cf_scale=cf_ref / value,
                        start_year=year,
                    )
                    new_success = lookup_cf_aware_success_rate(
                        cf_table, cf_rate_grid, cf_scale_grid,
                        wd / value, cf_ref / value, year,
                    )
                else:
                    _cf_avg = future_cf_avg if cf_schedule is not None else 0.0
                    wd = apply_guardrail_adjustment(
                        wd, value, current_success, target_success,
                        adjustment_pct, adjustment_mode, remaining,
                        table, rate_grid,
                        future_cf_avg=_cf_avg,
                    )
                    if cf_schedule is not None:
                        new_effective_rate = max((wd - future_cf_avg) / value, 0.0)
                    else:
                        new_effective_rate = wd / value
                    new_success = lookup_success_rate(
                        table, rate_grid, new_effective_rate, remaining
                    )
                adjustment_events.append({
                    "year": year,
                    "old_wd": float(old_wd),
                    "new_wd": float(wd),
                    "success_before": float(current_success),
                    "success_after": float(new_success),
                })
        else:
            g_success_rates[year] = 0.0

        g_withdrawals[year] = wd
        value = value * (1.0 + real_returns[year]) - wd

        # Apply expenses before depletion check
        if cf_expense is not None and cf_expense[year] > 0:
            value -= cf_expense[year]
            g_withdrawals[year] += cf_expense[year]

        if value <= 0:
            value = 0.0
            g_portfolio[year + 1:] = 0.0
            g_withdrawals[year + 1:] = 0.0
            break

        # Apply income after depletion check
        if cf_income is not None and cf_income[year] > 0:
            value += cf_income[year]
        g_portfolio[year + 1] = value

    # 基准固定策略
    baseline_wd = initial_portfolio * baseline_rate
    b_portfolio = np.zeros(n_years + 1)
    b_portfolio[0] = initial_portfolio
    b_withdrawals = np.zeros(n_years)

    value = initial_portfolio
    for year in range(n_years):
        b_withdrawals[year] = baseline_wd if value > 0 else 0.0
        if value > 0:
            value = value * (1.0 + real_returns[year]) - baseline_wd

            # Apply expenses before depletion check
            if cf_expense is not None and cf_expense[year] > 0:
                value -= cf_expense[year]
                b_withdrawals[year] += cf_expense[year]

            if value <= 0:
                value = 0.0

            # Apply income after depletion check
            if cf_income is not None and cf_income[year] > 0:
                value += cf_income[year]
        b_portfolio[year + 1] = value

    return {
        "years_simulated": n_years,
        "g_portfolio": g_portfolio,
        "g_withdrawals": g_withdrawals,
        "g_success_rates": g_success_rates,
        "b_portfolio": b_portfolio,
        "b_withdrawals": b_withdrawals,
        "g_total_consumption": float(np.sum(g_withdrawals)),
        "b_total_consumption": float(np.sum(b_withdrawals)),
        "adjustment_events": adjustment_events,
    }
