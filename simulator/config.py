"""全局常量与默认配置。"""

# ---------------------------------------------------------------------------
# 数据相关（JST 多国数据）
# ---------------------------------------------------------------------------
DEFAULT_DATA_START_YEAR = 1900
DEFAULT_COUNTRY = "USA"

# ---------------------------------------------------------------------------
# 图表常量
# ---------------------------------------------------------------------------
PERCENTILE_BANDS = [(5, 95), (10, 90), (25, 75)]
BAND_OPACITIES = [0.15, 0.25, 0.35]

# ---------------------------------------------------------------------------
# Guardrail 查找表网格（非均匀：低 rate 密集、高 rate 稀疏）
# ---------------------------------------------------------------------------
GUARDRAIL_RATE_MIN = 0.0

# 2D 表网格分段: [(上限, 步长), ...]
# [0, 0.20] step 0.001 (201 pt) + (0.20, 0.50] step 0.005 (60 pt) + (0.50, 1.0] step 0.01 (50 pt) = 311 pt
GUARDRAIL_RATE_SEGMENTS = [(0.20, 0.001), (0.50, 0.005), (1.00, 0.01)]

# 3D 表网格分段（比 2D 粗一倍以控制构建时间，扩展到 3.0 覆盖极端提取率）
# [0, 0.20] step 0.002 (101 pt) + (0.20, 0.50] step 0.01 (30 pt) + (0.50, 1.0] step 0.02 (25 pt)
# + (1.0, 2.0] step 0.10 (10 pt) + (2.0, 3.0] step 0.25 (4 pt) = 170 pt
GUARDRAIL_CF_RATE_SEGMENTS = [(0.20, 0.002), (0.50, 0.01), (1.00, 0.02), (2.00, 0.10), (3.00, 0.25)]

# 3D 现金流感知查找表 — cf_scale = C_ref / portfolio
# 非均匀: [0, 0.50] step 0.10 (6 pt) + (0.50, 2.0] step 0.25 (6 pt) + (2.0, 5.0] step 1.0 (3 pt) = 15 pt
GUARDRAIL_CF_SCALE_SEGMENTS = [(0.50, 0.10), (2.00, 0.25), (5.00, 1.00)]

# 场景分析专用：更粗的网格以加速多场景对比
SCENARIO_CF_RATE_SEGMENTS = [(0.20, 0.004), (0.50, 0.02), (1.00, 0.04), (2.00, 0.20), (3.00, 0.50)]
SCENARIO_CF_MAX_SIMS = 2000
SCENARIO_CF_SCALE_SEGMENTS = [(0.50, 0.10), (2.00, 0.50), (5.00, 1.00)]
SCENARIO_MAX_START_YEARS = 10


def build_nonuniform_grid(segments: list[tuple[float, float]], start: float = 0.0) -> "np.ndarray":
    """根据分段定义构建非均匀网格。

    Parameters
    ----------
    segments : list of (upper_bound, step)
        每段的上限和步长。段按顺序拼接，前一段的上限是后一段的起点。
    start : float
        网格起始值。

    Returns
    -------
    np.ndarray
        非均匀网格数组（已去重、排序）。
    """
    import numpy as np
    points = [start]
    cursor = start
    for upper, step in segments:
        seg = np.arange(cursor + step, upper + step / 2, step)
        points.extend(seg.tolist())
        points.append(upper)  # ensure segment endpoint is included
        cursor = upper
    # deduplicate & sort; round to avoid floating-point near-duplicates
    rounded = sorted(set(round(p, 10) for p in points))
    return np.array(rounded)

# ---------------------------------------------------------------------------
# 敏感性分析
# ---------------------------------------------------------------------------
TARGET_SUCCESS_RATES = [
    1.0, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70,
    0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.0,
]

# ---------------------------------------------------------------------------
# 池化采样权重（基于 2015-2020 年平均 GDP 的平方根，归一化）
# weight_i = sqrt(GDP_i) / sum(sqrt(GDP_j))
# GDP 数据来源：World Bank, 单位万亿美元
# ---------------------------------------------------------------------------
_GDP_TRILLION: dict[str, float] = {
    "USA": 20.9, "JPN": 5.1, "DEU": 3.8, "GBR": 2.8, "FRA": 2.7,
    "ITA": 2.0, "AUS": 1.4, "ESP": 1.3, "NLD": 0.9, "CHE": 0.7,
    "SWE": 0.54, "BEL": 0.52, "NOR": 0.40, "DNK": 0.36, "FIN": 0.27, "PRT": 0.23,
}

# 预计算全量 sqrt(GDP) 权重（16 国全部可用时的值）
_sqrt_vals = {iso: gdp ** 0.5 for iso, gdp in _GDP_TRILLION.items()}
_sqrt_total = sum(_sqrt_vals.values())
GDP_SQRT_WEIGHTS: dict[str, float] = {
    iso: sv / _sqrt_total for iso, sv in _sqrt_vals.items()
}


def get_gdp_weights(available_countries: list[str]) -> dict[str, float]:
    """根据实际可用国家子集，返回归一化的 sqrt(GDP) 权重。

    当某些国家因 data_start_year 被过滤掉时，
    从剩余国家中重新归一化权重。

    Parameters
    ----------
    available_countries : list[str]
        可用国家的 ISO 代码列表。

    Returns
    -------
    dict[str, float]
        {iso: weight}，所有权重之和为 1.0。
    """
    raw = {iso: _sqrt_vals.get(iso, 1.0) for iso in available_countries}
    total = sum(raw.values())
    if total == 0:
        # fallback: 等权
        n = len(available_countries)
        return {iso: 1.0 / n for iso in available_countries}
    return {iso: v / total for iso, v in raw.items()}


# ---------------------------------------------------------------------------
# 默认 UI 参数
# ---------------------------------------------------------------------------
DEFAULT_ALLOCATION = {"domestic_stock": 40, "global_stock": 40, "domestic_bond": 20}
DEFAULT_EXPENSE_RATIOS = {"domestic_stock": 0.50, "global_stock": 0.50, "domestic_bond": 0.50}
DEFAULT_MIN_BLOCK = 5
DEFAULT_MAX_BLOCK = 15
DEFAULT_RETIREMENT_YEARS = 65


# ---------------------------------------------------------------------------
# 内存限制检测（用于 Render Starter 等低内存环境自适应优化）
# ---------------------------------------------------------------------------
_LOW_MEMORY_THRESHOLD_MB = 768


def _detect_memory_limit_mb() -> int | None:
    """检测当前环境的内存限制（MB）。

    依次尝试：cgroup v2 → cgroup v1 → /proc/meminfo → os.sysconf → 环境变量。
    """
    import os as _os

    # cgroup v2
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            val = f.read().strip()
            if val != "max":
                return int(val) // (1024 * 1024)
    except (FileNotFoundError, OSError, ValueError):
        pass

    # cgroup v1
    try:
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
            val = int(f.read().strip())
            # 极大值意味着无限制
            if val < 2**62:
                return val // (1024 * 1024)
    except (FileNotFoundError, OSError, ValueError):
        pass

    # /proc/meminfo (物理内存)
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except (FileNotFoundError, OSError, ValueError):
        pass

    # os.sysconf (macOS / BSD)
    try:
        pages = _os.sysconf("SC_PHYS_PAGES")
        page_size = _os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return (pages * page_size) // (1024 * 1024)
    except (AttributeError, ValueError, OSError):
        pass

    # 环境变量 fallback
    env_val = _os.environ.get("MEMORY_LIMIT_MB")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass

    return None


_SENTINEL = object()
_cached_memory_limit: int | None | object = _SENTINEL


def get_memory_limit_mb() -> int | None:
    """获取内存限制（MB），结果缓存。"""
    global _cached_memory_limit
    if _cached_memory_limit is _SENTINEL:
        _cached_memory_limit = _detect_memory_limit_mb()
    return _cached_memory_limit


def is_low_memory() -> bool:
    """当前环境是否为低内存（≤768 MB）。未知时返回 False。"""
    import os as _os
    # 环境变量优先（允许运行时覆盖，方便测试）
    env_val = _os.environ.get("MEMORY_LIMIT_MB")
    if env_val:
        try:
            return int(env_val) <= _LOW_MEMORY_THRESHOLD_MB
        except ValueError:
            pass
    limit = get_memory_limit_mb()
    if limit is None:
        return False
    return limit <= _LOW_MEMORY_THRESHOLD_MB
