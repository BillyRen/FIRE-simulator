"""Pydantic 请求/响应模型 — FastAPI 数据验证与序列化。"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# 共享子模型
# ---------------------------------------------------------------------------

class AllocationSchema(BaseModel):
    domestic_stock: float = Field(0.4, ge=0, le=1)
    global_stock: float = Field(0.4, ge=0, le=1)
    domestic_bond: float = Field(0.2, ge=0, le=1)

    @model_validator(mode="after")
    def check_sum(self) -> "AllocationSchema":
        total = self.domestic_stock + self.global_stock + self.domestic_bond
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Asset allocation must sum to 100% (got {total * 100:.1f}%)")
        return self


class ExpenseRatioSchema(BaseModel):
    domestic_stock: float = Field(0.005, ge=0, le=0.1)
    global_stock: float = Field(0.005, ge=0, le=0.1)
    domestic_bond: float = Field(0.005, ge=0, le=0.1)


class CashFlowSchema(BaseModel):
    name: str = Field("自定义现金流", max_length=100)
    amount: float = Field(..., description="正=收入, 负=支出 (year-0 美元)")
    start_year: int = Field(1, ge=1, le=100, description="从退休第几年开始 (1-indexed)")
    duration: int = Field(10, ge=1, le=100)
    inflation_adjusted: bool = True
    enabled: bool = True


# ---------------------------------------------------------------------------
# 共享基类
# ---------------------------------------------------------------------------

class BaseSimulationParams(BaseModel):
    """Fields shared by all simulation request schemas."""
    allocation: AllocationSchema = AllocationSchema()
    expense_ratios: ExpenseRatioSchema = ExpenseRatioSchema()
    retirement_years: int = Field(65, ge=1, le=100)
    min_block: int = Field(5, ge=1, le=30)
    max_block: int = Field(15, ge=1, le=55)
    num_simulations: int = Field(2_000, ge=100, le=50_000)
    data_start_year: int = Field(1900, ge=1871, le=2100)
    country: str = Field("USA", description="ISO country code or 'ALL'")
    pooling_method: str = Field(
        "equal",
        pattern="^(equal|gdp_sqrt)$",
        description="池化采样权重方式: 'equal'=等概率 1/N, 'gdp_sqrt'=sqrt(GDP) 加权",
    )
    data_source: str = Field(
        "jst",
        pattern="^(jst|fire_dataset)$",
        description="数据源: 'jst'=JST 多国数据, 'fire_dataset'=FIRE Dataset (仅美国)",
    )
    leverage: float = Field(1.0, ge=1.0, le=5.0)
    borrowing_spread: float = Field(0.02, ge=0, le=0.2)
    cash_flows: list[CashFlowSchema] = Field(default=[], max_length=20)


# ---------------------------------------------------------------------------
# 1. 蒙特卡洛模拟
# ---------------------------------------------------------------------------

class SimulationRequest(BaseSimulationParams):
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    withdrawal_strategy: str = Field("fixed", pattern="^(fixed|dynamic|declining)$")
    retirement_age: int = Field(45, ge=18, le=100)
    dynamic_ceiling: float = Field(0.05, ge=0, le=1)
    dynamic_floor: float = Field(0.025, ge=0, le=1)


class SimulationResponse(BaseModel):
    success_rate: float
    funded_ratio: float
    final_median: float
    final_mean: float
    final_min: float
    final_max: float
    final_percentiles: dict[str, float]
    percentile_trajectories: dict[str, list[float]]
    withdrawal_percentile_trajectories: dict[str, list[float]] | None = None
    withdrawal_mean_trajectory: list[float] | None = None
    final_values_summary: list[dict[str, str]]
    initial_withdrawal_rate: float
    portfolio_metrics: list[dict[str, str]] = []


# ---------------------------------------------------------------------------
# 2. 敏感性分析（扫描）
# ---------------------------------------------------------------------------

class SweepRequest(BaseSimulationParams):
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    withdrawal_strategy: str = Field("fixed", pattern="^(fixed|dynamic|declining)$")
    retirement_age: int = Field(45, ge=18, le=100)
    dynamic_ceiling: float = Field(0.05, ge=0, le=1)
    dynamic_floor: float = Field(0.025, ge=0, le=1)
    rate_max: float = Field(0.12, gt=0, le=0.5)
    rate_step: float = Field(0.001, gt=0, le=0.1)


class TargetRateResult(BaseModel):
    target_success: str
    rate: str | None
    annual_withdrawal: str | None
    needed_portfolio: str | None


class SweepResponse(BaseModel):
    rates: list[float]
    success_rates: list[float]
    funded_ratios: list[float]
    target_results: list[TargetRateResult]
    target_results_funded: list[TargetRateResult]


# ---------------------------------------------------------------------------
# 3. Guardrail 策略
# ---------------------------------------------------------------------------

class GuardrailRequest(BaseSimulationParams):
    input_mode: str = Field("portfolio", pattern="^(portfolio|withdrawal)$")
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    target_success: float = Field(0.85, gt=0, lt=1)
    upper_guardrail: float = Field(0.99, gt=0, le=1)
    lower_guardrail: float = Field(0.60, ge=0, lt=1)
    adjustment_pct: float = Field(0.10, gt=0, le=1)
    adjustment_mode: str = Field("amount", pattern="^(amount|success_rate)$")
    min_remaining_years: int = Field(5, ge=1, le=30)
    baseline_rate: float = Field(0.033, gt=0, le=0.5)


class GuardrailResponse(BaseModel):
    initial_portfolio: float
    annual_withdrawal: float
    initial_rate: float
    # Guardrail MC
    g_success_rate: float
    g_funded_ratio: float
    g_percentile_trajectories: dict[str, list[float]]
    g_withdrawal_percentiles: dict[str, list[float]]
    # Baseline MC
    b_success_rate: float
    b_funded_ratio: float
    b_percentile_trajectories: dict[str, list[float]]
    b_withdrawal_percentiles: dict[str, list[float]]
    baseline_annual_wd: float
    # 初始护栏触发阈值
    upper_trigger_portfolio: float = 0.0
    upper_trigger_withdrawal: float = 0.0
    lower_trigger_portfolio: float = 0.0
    lower_trigger_withdrawal: float = 0.0
    # 关键指标
    metrics: list[dict[str, str]]
    # 投资组合绩效指标（底层回报序列相同，guardrail/baseline 共用）
    portfolio_metrics: list[dict[str, str]] = []


# ---------------------------------------------------------------------------
# 4. 历史回测
# ---------------------------------------------------------------------------

class BacktestRequest(BaseSimulationParams):
    """复用 GuardrailRequest 的大部分字段，额外加回测起始年。"""
    initial_portfolio: float = Field(..., gt=0, description="用户输入的初始资产")
    annual_withdrawal: float = Field(..., ge=0, description="由 guardrail MC 阶段计算得出")
    target_success: float = Field(0.85, gt=0, lt=1)
    upper_guardrail: float = Field(0.99, gt=0, le=1)
    lower_guardrail: float = Field(0.60, ge=0, lt=1)
    adjustment_pct: float = Field(0.10, gt=0, le=1)
    adjustment_mode: str = Field("amount", pattern="^(amount|success_rate)$")
    min_remaining_years: int = Field(5, ge=1, le=30)
    baseline_rate: float = Field(0.033, gt=0, le=0.5)
    hist_start_year: int = Field(1990, ge=1871, le=2100)
    backtest_country: str | None = Field(None, description="回测用的具体国家 ISO（当 country=ALL 时必填）")


class AdjustmentEvent(BaseModel):
    year: int
    old_wd: float
    new_wd: float
    success_before: float
    success_after: float


class BacktestResponse(BaseModel):
    years_simulated: int
    year_labels: list[int]
    g_portfolio: list[float]
    g_withdrawals: list[float]
    g_success_rates: list[float]
    b_portfolio: list[float]
    b_withdrawals: list[float]
    g_total_consumption: float
    b_total_consumption: float
    adjustment_events: list[AdjustmentEvent] = []
    path_metrics: list[dict[str, str]] = []


# ---------------------------------------------------------------------------
# 4b. 退休模拟历史回测（简单版，无 guardrail）
# ---------------------------------------------------------------------------

class SimBacktestRequest(BaseSimulationParams):
    """用户选择国家+起始年，用真实历史回报模拟退休路径。"""
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    withdrawal_strategy: str = Field("fixed", pattern="^(fixed|dynamic|declining)$")
    retirement_age: int = Field(45, ge=18, le=100)
    dynamic_ceiling: float = Field(0.05, ge=0, le=1)
    dynamic_floor: float = Field(0.025, ge=0, le=1)
    hist_start_year: int = Field(1990, ge=1871, le=2100)


class SimBacktestResponse(BaseModel):
    years_simulated: int
    year_labels: list[int]
    portfolio: list[float]
    withdrawals: list[float]
    survived: bool
    final_portfolio: float
    total_consumption: float
    path_metrics: list[dict[str, str]] = []


# ---------------------------------------------------------------------------
# 4c. 批量历史回测（遍历所有国家/起始年）
# ---------------------------------------------------------------------------

class SimBatchBacktestRequest(BaseSimulationParams):
    """批量历史回测 — 自动遍历所有有效 (国家, 起始年) 组合。"""
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    withdrawal_strategy: str = Field("fixed", pattern="^(fixed|dynamic|declining)$")
    retirement_age: int = Field(45, ge=18, le=100)
    dynamic_ceiling: float = Field(0.05, ge=0, le=1)
    dynamic_floor: float = Field(0.025, ge=0, le=1)


class SimBatchPathSummary(BaseModel):
    country: str
    start_year: int
    years_simulated: int
    is_complete: bool
    survived: bool
    final_portfolio: float
    total_consumption: float
    year_labels: list[int]
    portfolio: list[float]
    withdrawals: list[float]
    path_metrics: list[dict[str, str]] = []


class SimBatchBacktestResponse(BaseModel):
    num_paths: int
    num_complete: int
    success_rate: float
    funded_ratio: float
    percentile_trajectories: dict[str, list[float]]
    withdrawal_percentile_trajectories: dict[str, list[float]] | None = None
    final_values_summary: list[dict[str, str]] = []
    portfolio_metrics: list[dict[str, str]] = []
    paths: list[SimBatchPathSummary] = []


# ---------------------------------------------------------------------------
# 4d. Guardrail 批量历史回测
# ---------------------------------------------------------------------------

class GuardrailBatchBacktestRequest(BaseSimulationParams):
    """Guardrail 批量历史回测 — 遍历所有有效 (国家, 起始年)。"""
    initial_portfolio: float = Field(..., gt=0, description="用户输入的初始资产")
    annual_withdrawal: float = Field(..., ge=0, description="由 guardrail MC 阶段计算得出")
    target_success: float = Field(0.85, gt=0, lt=1)
    upper_guardrail: float = Field(0.99, gt=0, le=1)
    lower_guardrail: float = Field(0.60, ge=0, lt=1)
    adjustment_pct: float = Field(0.10, gt=0, le=1)
    adjustment_mode: str = Field("amount", pattern="^(amount|success_rate)$")
    min_remaining_years: int = Field(5, ge=1, le=30)
    baseline_rate: float = Field(0.033, gt=0, le=0.5)


class GuardrailBatchPathSummary(BaseModel):
    country: str
    start_year: int
    years_simulated: int
    is_complete: bool
    g_survived: bool
    b_survived: bool
    g_final_portfolio: float
    b_final_portfolio: float
    g_total_consumption: float
    b_total_consumption: float
    num_adjustments: int
    year_labels: list[int]
    g_portfolio: list[float]
    g_withdrawals: list[float]
    g_success_rates: list[float]
    b_portfolio: list[float]
    b_withdrawals: list[float]
    adjustment_events: list[AdjustmentEvent] = []
    path_metrics: list[dict[str, str]] = []


class GuardrailBatchBacktestResponse(BaseModel):
    num_paths: int
    num_complete: int
    g_success_rate: float
    g_funded_ratio: float
    b_success_rate: float
    b_funded_ratio: float
    g_percentile_trajectories: dict[str, list[float]]
    b_percentile_trajectories: dict[str, list[float]]
    g_withdrawal_percentiles: dict[str, list[float]]
    b_withdrawal_percentiles: dict[str, list[float]]
    paths: list[GuardrailBatchPathSummary] = []


# ---------------------------------------------------------------------------
# 5. 资产配置扫描
# ---------------------------------------------------------------------------

class AllocationSweepRequest(BaseSimulationParams):
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    num_simulations: int = Field(1_000, ge=100, le=50_000)  # override: lower default for sweep
    withdrawal_strategy: str = Field("fixed", pattern="^(fixed|dynamic|declining)$")
    retirement_age: int = Field(45, ge=18, le=100)
    dynamic_ceiling: float = Field(0.05, ge=0, le=1)
    dynamic_floor: float = Field(0.025, ge=0, le=1)
    allocation_step: float = Field(0.1, ge=0.05, le=0.2)


class AllocationResult(BaseModel):
    domestic_stock: float
    global_stock: float
    domestic_bond: float
    success_rate: float
    median_final: float
    mean_final: float
    p10_depletion_year: int | None = None
    funded_ratio: float = 0.0
    cvar_10: float = 0.0
    p90_final: float = 0.0


class AllocationSweepResponse(BaseModel):
    results: list[AllocationResult]
    best: AllocationResult


# ---------------------------------------------------------------------------
# 6. 历史数据
# ---------------------------------------------------------------------------

class CountryInfo(BaseModel):
    iso: str
    name_en: str
    name_zh: str
    min_year: int
    max_year: int
    n_years: int


class CountriesResponse(BaseModel):
    countries: list[CountryInfo]


class ReturnsResponse(BaseModel):
    years: list[int]
    domestic_stock: list[float]
    global_stock: list[float]
    domestic_bond: list[float]
    inflation: list[float]


# ---------------------------------------------------------------------------
# 7. 买房 vs 租房
# ---------------------------------------------------------------------------

class BuyVsRentBaseParams(BaseModel):
    """买房/租房对比的共享参数。"""
    home_price: float = Field(500_000, gt=0, description="房价")
    down_payment_pct: float = Field(0.20, ge=0, le=1, description="首付比例")
    mortgage_term: int = Field(30, ge=1, le=50, description="贷款年限")
    buying_cost_pct: float = Field(0.03, ge=0, le=0.2, description="买房交易费率")
    selling_cost_pct: float = Field(0.06, ge=0, le=0.2, description="卖房交易费率")
    property_tax_pct: float = Field(0.01, ge=0, le=0.1, description="年房产税率")
    maintenance_pct: float = Field(0.01, ge=0, le=0.1, description="年维护费率")
    insurance_annual: float = Field(1200, ge=0, description="年保险费")
    annual_rent: float = Field(20_000, ge=0, description="初始年租金")
    analysis_years: int = Field(30, ge=1, le=60, description="分析年限")


class BuyVsRentSimpleRequest(BuyVsRentBaseParams):
    """简化版：用户手动输入所有利率参数。"""
    mortgage_rate: float = Field(0.065, ge=0, le=0.3, description="固定房贷利率（名义）")
    rent_growth_rate: float = Field(0.03, ge=-0.1, le=0.2, description="年租金增长率（名义）")
    home_appreciation_rate: float = Field(0.035, ge=-0.2, le=0.3, description="年房价增值率（名义）")
    investment_return_rate: float = Field(0.08, ge=-0.1, le=0.3, description="投资回报率（名义）")
    inflation_rate: float = Field(0.025, ge=-0.05, le=0.2, description="通胀率")


class BuyVsRentSimpleResponse(BaseModel):
    analysis_years: int
    buy_net_worth_real: list[float]
    rent_net_worth_real: list[float]
    advantage_real: list[float]
    breakeven_year: int | None
    home_value_real: list[float]
    mortgage_balance_real: list[float]
    buy_cost_total_real: list[float]
    rent_cost_real: list[float]
    buy_cost_interest_real: list[float]
    buy_cost_principal_real: list[float]
    buy_cost_tax_real: list[float]
    buy_cost_maintenance_real: list[float]
    buy_cost_insurance_real: list[float]
    summary: dict


class BuyVsRentMCRequest(BuyVsRentBaseParams):
    """完整版：蒙特卡洛模拟。可选手动覆盖部分参数。"""
    mortgage_rate_spread: float = Field(0.017, ge=0, le=0.1, description="房贷利差（ltrate + spread）")
    allocation: AllocationSchema = AllocationSchema()
    expense_ratios: ExpenseRatioSchema = ExpenseRatioSchema()
    min_block: int = Field(5, ge=1, le=30)
    max_block: int = Field(15, ge=1, le=55)
    num_simulations: int = Field(2_000, ge=100, le=20_000)
    data_start_year: int = Field(1900, ge=1871, le=2100)
    country: str = Field("USA", description="ISO 国家代码或 'ALL'")
    pooling_method: str = Field("equal", pattern="^(equal|gdp_sqrt)$")
    leverage: float = Field(1.0, ge=1.0, le=5.0)
    borrowing_spread: float = Field(0.02, ge=0, le=0.2)
    override_home_appreciation: float | None = Field(None, ge=-0.2, le=0.3, description="手动房价增值率")
    override_rent_growth: float | None = Field(None, ge=-0.1, le=0.2, description="手动租金增长率")
    override_mortgage_rate: float | None = Field(None, ge=0, le=0.3, description="手动房贷利率")


class BuyVsRentMCResponse(BaseModel):
    num_simulations: int
    analysis_years: int
    buy_percentile_trajectories: dict[str, list[float]]
    rent_percentile_trajectories: dict[str, list[float]]
    advantage_percentile_trajectories: dict[str, list[float]]
    buy_wins_probability: list[float]
    breakeven_percentiles: dict
    buy_cost_median: list[float]
    rent_cost_median: list[float]
    sampled_stats: list[dict[str, str]] = []
    summary: dict


class HousingCountryInfo(BaseModel):
    iso: str
    name_en: str
    name_zh: str
    min_year: int
    max_year: int
    n_years: int
    has_housing: bool
    housing_years: int


class HousingCountriesResponse(BaseModel):
    countries: list[HousingCountryInfo]


# ---------------------------------------------------------------------------
# 7b. 盈亏平衡房价查找
# ---------------------------------------------------------------------------

class BreakevenSimpleRequest(BuyVsRentBaseParams):
    """简化版盈亏平衡查找 — 复用 simple 的利率参数。"""
    mortgage_rate: float = Field(0.065, ge=0, le=0.3)
    rent_growth_rate: float = Field(0.03, ge=-0.1, le=0.2)
    home_appreciation_rate: float = Field(0.035, ge=-0.2, le=0.3)
    investment_return_rate: float = Field(0.08, ge=-0.1, le=0.3)
    inflation_rate: float = Field(0.025, ge=-0.05, le=0.2)
    price_low: float | None = Field(None, gt=0, description="搜索下界")
    price_high: float | None = Field(None, gt=0, description="搜索上界")
    auto_estimate_ha: bool = Field(False, description="是否根据房价动态计算增值率")
    fair_pe: float | None = Field(None, ge=5, le=100, description="合理租售比")
    reversion_years: int | None = Field(None, ge=1, le=50, description="回归年限")


class BreakevenMCRequest(BuyVsRentBaseParams):
    """MC 版盈亏平衡查找 — 复用 MC 的采样参数。"""
    mortgage_rate_spread: float = Field(0.017, ge=0, le=0.1)
    allocation: AllocationSchema = AllocationSchema()
    expense_ratios: ExpenseRatioSchema = ExpenseRatioSchema()
    min_block: int = Field(5, ge=1, le=30)
    max_block: int = Field(15, ge=1, le=55)
    num_simulations: int = Field(1_000, ge=100, le=10_000)
    data_start_year: int = Field(1900, ge=1871, le=2100)
    country: str = Field("USA")
    pooling_method: str = Field("equal", pattern="^(equal|gdp_sqrt)$")
    leverage: float = Field(1.0, ge=1.0, le=5.0)
    borrowing_spread: float = Field(0.02, ge=0, le=0.2)
    override_home_appreciation: float | None = Field(None, ge=-0.2, le=0.3)
    override_rent_growth: float | None = Field(None, ge=-0.1, le=0.2)
    override_mortgage_rate: float | None = Field(None, ge=0, le=0.3)
    target_win_pct: float = Field(0.5, ge=0.1, le=0.9, description="目标胜率")
    price_low: float | None = Field(None, gt=0)
    price_high: float | None = Field(None, gt=0)


class BreakevenResponse(BaseModel):
    found: bool
    breakeven_price: float | None = None
    price_to_annual_rent: float | None = None
    message: str | None = None
    ha_at_breakeven: float | None = None
    # simple-specific
    summary: dict | None = None
    advantage_at_low: float | None = None
    advantage_at_high: float | None = None
    # mc-specific
    target_win_pct: float | None = None
    actual_win_pct: float | None = None
    median_advantage: float | None = None
    median_buy_nw: float | None = None
    median_rent_nw: float | None = None
    win_pct_at_low: float | None = None
    win_pct_at_high: float | None = None
