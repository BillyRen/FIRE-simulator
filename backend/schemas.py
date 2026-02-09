"""Pydantic 请求/响应模型 — FastAPI 数据验证与序列化。"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 共享子模型
# ---------------------------------------------------------------------------

class AllocationSchema(BaseModel):
    us_stock: float = Field(0.4, ge=0, le=1)
    intl_stock: float = Field(0.4, ge=0, le=1)
    us_bond: float = Field(0.2, ge=0, le=1)


class ExpenseRatioSchema(BaseModel):
    us_stock: float = Field(0.005, ge=0, le=0.1)
    intl_stock: float = Field(0.005, ge=0, le=0.1)
    us_bond: float = Field(0.005, ge=0, le=0.1)


class CashFlowSchema(BaseModel):
    name: str = Field("自定义现金流", max_length=100)
    amount: float = Field(..., description="正=收入, 负=支出 (year-0 美元)")
    start_year: int = Field(1, ge=1, le=100, description="从退休第几年开始 (1-indexed)")
    duration: int = Field(10, ge=1, le=100)
    inflation_adjusted: bool = True


# ---------------------------------------------------------------------------
# 1. 蒙特卡洛模拟
# ---------------------------------------------------------------------------

class SimulationRequest(BaseModel):
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    allocation: AllocationSchema = AllocationSchema()
    expense_ratios: ExpenseRatioSchema = ExpenseRatioSchema()
    retirement_years: int = Field(65, ge=1, le=100)
    min_block: int = Field(5, ge=1, le=30)
    max_block: int = Field(15, ge=1, le=55)
    num_simulations: int = Field(2_000, ge=100, le=50_000)
    data_start_year: int = Field(1926, ge=1871, le=2100)
    withdrawal_strategy: str = Field("fixed", pattern="^(fixed|dynamic)$")
    dynamic_ceiling: float = Field(0.05, ge=0, le=1)
    dynamic_floor: float = Field(0.025, ge=0, le=1)
    leverage: float = Field(1.0, ge=1.0, le=5.0)
    borrowing_spread: float = Field(0.02, ge=0, le=0.2)
    cash_flows: list[CashFlowSchema] = Field(default=[], max_length=20)


class SimulationResponse(BaseModel):
    success_rate: float
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


# ---------------------------------------------------------------------------
# 2. 敏感性分析（扫描）
# ---------------------------------------------------------------------------

class SweepRequest(BaseModel):
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    allocation: AllocationSchema = AllocationSchema()
    expense_ratios: ExpenseRatioSchema = ExpenseRatioSchema()
    retirement_years: int = Field(65, ge=1, le=100)
    min_block: int = Field(5, ge=1, le=30)
    max_block: int = Field(15, ge=1, le=55)
    num_simulations: int = Field(2_000, ge=100, le=50_000)
    data_start_year: int = Field(1926, ge=1871, le=2100)
    withdrawal_strategy: str = Field("fixed", pattern="^(fixed|dynamic)$")
    dynamic_ceiling: float = Field(0.05, ge=0, le=1)
    dynamic_floor: float = Field(0.025, ge=0, le=1)
    rate_max: float = Field(0.12, gt=0, le=0.5)
    rate_step: float = Field(0.001, gt=0, le=0.1)
    leverage: float = Field(1.0, ge=1.0, le=5.0)
    borrowing_spread: float = Field(0.02, ge=0, le=0.2)
    cash_flows: list[CashFlowSchema] = Field(default=[], max_length=20)


class TargetRateResult(BaseModel):
    target_success: str
    rate: str | None
    annual_withdrawal: str | None
    needed_portfolio: str | None


class SweepResponse(BaseModel):
    rates: list[float]
    success_rates: list[float]
    target_results: list[TargetRateResult]


# ---------------------------------------------------------------------------
# 3. Guardrail 策略
# ---------------------------------------------------------------------------

class GuardrailRequest(BaseModel):
    annual_withdrawal: float = Field(40_000, ge=0)
    allocation: AllocationSchema = AllocationSchema()
    expense_ratios: ExpenseRatioSchema = ExpenseRatioSchema()
    retirement_years: int = Field(65, ge=1, le=100)
    min_block: int = Field(5, ge=1, le=30)
    max_block: int = Field(15, ge=1, le=55)
    num_simulations: int = Field(2_000, ge=100, le=50_000)
    data_start_year: int = Field(1926, ge=1871, le=2100)
    target_success: float = Field(0.80, gt=0, lt=1)
    upper_guardrail: float = Field(0.99, gt=0, le=1)
    lower_guardrail: float = Field(0.50, ge=0, lt=1)
    adjustment_pct: float = Field(0.50, gt=0, le=1)
    adjustment_mode: str = Field("amount", pattern="^(amount|success_rate)$")
    min_remaining_years: int = Field(10, ge=1, le=30)
    baseline_rate: float = Field(0.033, gt=0, le=0.5)
    leverage: float = Field(1.0, ge=1.0, le=5.0)
    borrowing_spread: float = Field(0.02, ge=0, le=0.2)
    cash_flows: list[CashFlowSchema] = Field(default=[], max_length=20)


class GuardrailResponse(BaseModel):
    initial_portfolio: float
    initial_rate: float
    # Guardrail MC
    g_success_rate: float
    g_percentile_trajectories: dict[str, list[float]]
    g_withdrawal_percentiles: dict[str, list[float]]
    # Baseline MC
    b_success_rate: float
    b_percentile_trajectories: dict[str, list[float]]
    b_withdrawal_percentiles: dict[str, list[float]]
    baseline_annual_wd: float
    # 关键指标
    metrics: list[dict[str, str]]


# ---------------------------------------------------------------------------
# 4. 历史回测
# ---------------------------------------------------------------------------

class BacktestRequest(BaseModel):
    """复用 GuardrailRequest 的大部分字段，额外加回测起始年。"""
    annual_withdrawal: float = Field(40_000, ge=0)
    allocation: AllocationSchema = AllocationSchema()
    expense_ratios: ExpenseRatioSchema = ExpenseRatioSchema()
    retirement_years: int = Field(65, ge=1, le=100)
    min_block: int = Field(5, ge=1, le=30)
    max_block: int = Field(15, ge=1, le=55)
    num_simulations: int = Field(2_000, ge=100, le=50_000)
    data_start_year: int = Field(1926, ge=1871, le=2100)
    target_success: float = Field(0.80, gt=0, lt=1)
    upper_guardrail: float = Field(0.99, gt=0, le=1)
    lower_guardrail: float = Field(0.50, ge=0, lt=1)
    adjustment_pct: float = Field(0.50, gt=0, le=1)
    adjustment_mode: str = Field("amount", pattern="^(amount|success_rate)$")
    min_remaining_years: int = Field(10, ge=1, le=30)
    baseline_rate: float = Field(0.033, gt=0, le=0.5)
    leverage: float = Field(1.0, ge=1.0, le=5.0)
    borrowing_spread: float = Field(0.02, ge=0, le=0.2)
    initial_portfolio: float = Field(..., gt=0, description="由 guardrail MC 阶段计算得出")
    hist_start_year: int = Field(1990, ge=1871, le=2100)
    cash_flows: list[CashFlowSchema] = Field(default=[], max_length=20)


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


# ---------------------------------------------------------------------------
# 5. 资产配置扫描
# ---------------------------------------------------------------------------

class AllocationSweepRequest(BaseModel):
    initial_portfolio: float = Field(1_000_000, gt=0)
    annual_withdrawal: float = Field(40_000, ge=0)
    expense_ratios: ExpenseRatioSchema = ExpenseRatioSchema()
    retirement_years: int = Field(65, ge=1, le=100)
    min_block: int = Field(5, ge=1, le=30)
    max_block: int = Field(15, ge=1, le=55)
    num_simulations: int = Field(1_000, ge=100, le=50_000)
    data_start_year: int = Field(1926, ge=1871, le=2100)
    withdrawal_strategy: str = Field("fixed", pattern="^(fixed|dynamic)$")
    dynamic_ceiling: float = Field(0.05, ge=0, le=1)
    dynamic_floor: float = Field(0.025, ge=0, le=1)
    leverage: float = Field(1.0, ge=1.0, le=5.0)
    borrowing_spread: float = Field(0.02, ge=0, le=0.2)
    allocation_step: float = Field(0.1, ge=0.05, le=0.2)
    cash_flows: list[CashFlowSchema] = Field(default=[], max_length=20)


class AllocationResult(BaseModel):
    us_stock: float
    intl_stock: float
    us_bond: float
    success_rate: float
    median_final: float
    mean_final: float
    p10_depletion_year: int | None = None


class AllocationSweepResponse(BaseModel):
    results: list[AllocationResult]
    best_by_success: AllocationResult


# ---------------------------------------------------------------------------
# 6. 历史数据
# ---------------------------------------------------------------------------

class ReturnsResponse(BaseModel):
    years: list[int]
    us_stock: list[float]
    intl_stock: list[float]
    us_bond: list[float]
    us_inflation: list[float]
