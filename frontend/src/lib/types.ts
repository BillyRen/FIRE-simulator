// TypeScript 类型定义 — 与 backend schemas 对应

export interface Allocation {
  domestic_stock: number;
  global_stock: number;
  domestic_bond: number;
}

export interface ExpenseRatios {
  domestic_stock: number;
  global_stock: number;
  domestic_bond: number;
}

export interface CountryInfo {
  iso: string;
  name_en: string;
  name_zh: string;
  min_year: number;
  max_year: number;
  n_years: number;
}

export interface CashFlowItem {
  name: string;
  amount: number; // 正=收入, 负=支出
  start_year: number;
  duration: number;
  inflation_adjusted: boolean;
  enabled?: boolean; // 默认 true
}

// ---------------------------------------------------------------------------
// 1. 蒙特卡洛模拟
// ---------------------------------------------------------------------------

export interface SimulationRequest {
  initial_portfolio: number;
  annual_withdrawal: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  retirement_years: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  withdrawal_strategy: "fixed" | "dynamic";
  dynamic_ceiling: number;
  dynamic_floor: number;
  leverage: number;
  borrowing_spread: number;
  cash_flows: CashFlowItem[];
}

export interface SimulationResponse {
  success_rate: number;
  funded_ratio: number;
  final_median: number;
  final_mean: number;
  final_min: number;
  final_max: number;
  final_percentiles: Record<string, number>;
  percentile_trajectories: Record<string, number[]>;
  withdrawal_percentile_trajectories: Record<string, number[]> | null;
  withdrawal_mean_trajectory: number[] | null;
  final_values_summary: Array<Record<string, string>>;
  initial_withdrawal_rate: number;
  portfolio_metrics: Array<Record<string, string>>;
}

// ---------------------------------------------------------------------------
// 2. 敏感性分析
// ---------------------------------------------------------------------------

export interface SweepRequest {
  initial_portfolio: number;
  annual_withdrawal: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  retirement_years: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  withdrawal_strategy: "fixed" | "dynamic";
  dynamic_ceiling: number;
  dynamic_floor: number;
  rate_max: number;
  rate_step: number;
  leverage: number;
  borrowing_spread: number;
  cash_flows: CashFlowItem[];
}

export interface TargetRateResult {
  target_success: string;
  rate: string | null;
  annual_withdrawal: string | null;
  needed_portfolio: string | null;
}

export interface SweepResponse {
  rates: number[];
  success_rates: number[];
  funded_ratios: number[];
  target_results: TargetRateResult[];
  target_results_funded: TargetRateResult[];
}

// ---------------------------------------------------------------------------
// 3. Guardrail
// ---------------------------------------------------------------------------

export interface GuardrailRequest {
  input_mode: "portfolio" | "withdrawal";
  initial_portfolio: number;
  annual_withdrawal: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  retirement_years: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  target_success: number;
  upper_guardrail: number;
  lower_guardrail: number;
  adjustment_pct: number;
  adjustment_mode: "amount" | "success_rate";
  min_remaining_years: number;
  baseline_rate: number;
  leverage: number;
  borrowing_spread: number;
  cash_flows: CashFlowItem[];
}

export interface GuardrailResponse {
  initial_portfolio: number;
  annual_withdrawal: number;
  initial_rate: number;
  g_success_rate: number;
  g_funded_ratio: number;
  g_percentile_trajectories: Record<string, number[]>;
  g_withdrawal_percentiles: Record<string, number[]>;
  b_success_rate: number;
  b_funded_ratio: number;
  b_percentile_trajectories: Record<string, number[]>;
  b_withdrawal_percentiles: Record<string, number[]>;
  baseline_annual_wd: number;
  upper_trigger_portfolio: number;
  upper_trigger_withdrawal: number;
  lower_trigger_portfolio: number;
  lower_trigger_withdrawal: number;
  metrics: Array<Record<string, string>>;
  portfolio_metrics: Array<Record<string, string>>;
}

// ---------------------------------------------------------------------------
// 4. 历史回测
// ---------------------------------------------------------------------------

export interface BacktestRequest {
  annual_withdrawal: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  retirement_years: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  target_success: number;
  upper_guardrail: number;
  lower_guardrail: number;
  adjustment_pct: number;
  adjustment_mode: "amount" | "success_rate";
  min_remaining_years: number;
  baseline_rate: number;
  leverage: number;
  borrowing_spread: number;
  initial_portfolio: number;
  hist_start_year: number;
  cash_flows: CashFlowItem[];
  backtest_country?: string;
}

export interface AdjustmentEvent {
  year: number;
  old_wd: number;
  new_wd: number;
  success_before: number;
  success_after: number;
}

export interface BacktestResponse {
  years_simulated: number;
  year_labels: number[];
  g_portfolio: number[];
  g_withdrawals: number[];
  g_success_rates: number[];
  b_portfolio: number[];
  b_withdrawals: number[];
  g_total_consumption: number;
  b_total_consumption: number;
  adjustment_events: AdjustmentEvent[];
  path_metrics: Array<Record<string, string>>;
}

// ---------------------------------------------------------------------------
// 4b. 退休模拟历史回测（简单版）
// ---------------------------------------------------------------------------

export interface SimBacktestRequest {
  initial_portfolio: number;
  annual_withdrawal: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  retirement_years: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  withdrawal_strategy: "fixed" | "dynamic";
  dynamic_ceiling: number;
  dynamic_floor: number;
  leverage: number;
  borrowing_spread: number;
  cash_flows: CashFlowItem[];
  hist_start_year: number;
}

export interface SimBacktestResponse {
  years_simulated: number;
  year_labels: number[];
  portfolio: number[];
  withdrawals: number[];
  survived: boolean;
  final_portfolio: number;
  total_consumption: number;
  path_metrics: Array<Record<string, string>>;
}

// ---------------------------------------------------------------------------
// 4c. 批量历史回测（主模拟页）
// ---------------------------------------------------------------------------

export interface SimBatchPathSummary {
  country: string;
  start_year: number;
  years_simulated: number;
  is_complete: boolean;
  survived: boolean;
  final_portfolio: number;
  total_consumption: number;
  year_labels: number[];
  portfolio: number[];
  withdrawals: number[];
  path_metrics: Array<Record<string, string>>;
}

export interface SimBatchBacktestResponse {
  num_paths: number;
  num_complete: number;
  success_rate: number;
  funded_ratio: number;
  percentile_trajectories: Record<string, number[]>;
  withdrawal_percentile_trajectories: Record<string, number[]> | null;
  final_values_summary: Array<Record<string, string>>;
  portfolio_metrics: Array<Record<string, string>>;
  paths: SimBatchPathSummary[];
}

// ---------------------------------------------------------------------------
// 4d. Guardrail 批量历史回测
// ---------------------------------------------------------------------------

export interface GuardrailBatchPathSummary {
  country: string;
  start_year: number;
  years_simulated: number;
  is_complete: boolean;
  g_survived: boolean;
  b_survived: boolean;
  g_final_portfolio: number;
  b_final_portfolio: number;
  g_total_consumption: number;
  b_total_consumption: number;
  num_adjustments: number;
  year_labels: number[];
  g_portfolio: number[];
  g_withdrawals: number[];
  g_success_rates: number[];
  b_portfolio: number[];
  b_withdrawals: number[];
  adjustment_events: AdjustmentEvent[];
  path_metrics: Array<Record<string, string>>;
}

export interface GuardrailBatchBacktestResponse {
  num_paths: number;
  num_complete: number;
  g_success_rate: number;
  g_funded_ratio: number;
  b_success_rate: number;
  b_funded_ratio: number;
  g_percentile_trajectories: Record<string, number[]>;
  b_percentile_trajectories: Record<string, number[]>;
  g_withdrawal_percentiles: Record<string, number[]>;
  b_withdrawal_percentiles: Record<string, number[]>;
  paths: GuardrailBatchPathSummary[];
}

// ---------------------------------------------------------------------------
// 5. 资产配置扫描
// ---------------------------------------------------------------------------

export interface AllocationSweepRequest {
  initial_portfolio: number;
  annual_withdrawal: number;
  expense_ratios: ExpenseRatios;
  retirement_years: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  withdrawal_strategy: "fixed" | "dynamic";
  dynamic_ceiling: number;
  dynamic_floor: number;
  leverage: number;
  borrowing_spread: number;
  allocation_step: number;
  cash_flows: CashFlowItem[];
}

export interface AllocationResult {
  domestic_stock: number;
  global_stock: number;
  domestic_bond: number;
  success_rate: number;
  median_final: number;
  mean_final: number;
  p10_depletion_year: number | null;
  funded_ratio: number;
  cvar_10: number;
  p90_final: number;
}

export interface AllocationSweepResponse {
  results: AllocationResult[];
  best: AllocationResult;
}

// ---------------------------------------------------------------------------
// 共享表单状态
// ---------------------------------------------------------------------------

export interface FormParams {
  initial_portfolio: number;
  annual_withdrawal: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  retirement_years: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  withdrawal_strategy: "fixed" | "dynamic";
  dynamic_ceiling: number;
  dynamic_floor: number;
  leverage: number;
  borrowing_spread: number;
  cash_flows: CashFlowItem[];
}

export const DEFAULT_PARAMS: FormParams = {
  initial_portfolio: 1_000_000,
  annual_withdrawal: 40_000,
  allocation: { domestic_stock: 0.4, global_stock: 0.4, domestic_bond: 0.2 },
  expense_ratios: { domestic_stock: 0.005, global_stock: 0.005, domestic_bond: 0.005 },
  retirement_years: 65,
  min_block: 5,
  max_block: 15,
  num_simulations: 2_000,
  data_start_year: 1900,
  country: "USA",
  pooling_method: "equal",
  data_source: "jst",
  withdrawal_strategy: "fixed",
  dynamic_ceiling: 0.05,
  dynamic_floor: 0.025,
  leverage: 1.0,
  borrowing_spread: 0.02,
  cash_flows: [],
};
