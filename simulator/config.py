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
# Guardrail 查找表网格
# ---------------------------------------------------------------------------
GUARDRAIL_RATE_MIN = 0.0
GUARDRAIL_RATE_MAX = 0.20
GUARDRAIL_RATE_STEP = 0.001

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
