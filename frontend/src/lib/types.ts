// TypeScript 类型定义 — 与 backend schemas 对应

export interface Allocation {
  us_stock: number;
  intl_stock: number;
  us_bond: number;
}

export interface ExpenseRatios {
  us_stock: number;
  intl_stock: number;
  us_bond: number;
}

export interface CashFlowItem {
  name: string;
  amount: number; // 正=收入, 负=支出
  start_year: number;
  duration: number;
  inflation_adjusted: boolean;
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
  withdrawal_strategy: "fixed" | "dynamic";
  dynamic_ceiling: number;
  dynamic_floor: number;
  cash_flows: CashFlowItem[];
}

export interface SimulationResponse {
  success_rate: number;
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
  withdrawal_strategy: "fixed" | "dynamic";
  dynamic_ceiling: number;
  dynamic_floor: number;
  rate_max: number;
  rate_step: number;
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
  target_results: TargetRateResult[];
}

// ---------------------------------------------------------------------------
// 3. Guardrail
// ---------------------------------------------------------------------------

export interface GuardrailRequest {
  annual_withdrawal: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  retirement_years: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  target_success: number;
  upper_guardrail: number;
  lower_guardrail: number;
  adjustment_pct: number;
  adjustment_mode: "amount" | "success_rate";
  min_remaining_years: number;
  baseline_rate: number;
  cash_flows: CashFlowItem[];
}

export interface GuardrailResponse {
  initial_portfolio: number;
  initial_rate: number;
  g_success_rate: number;
  g_percentile_trajectories: Record<string, number[]>;
  g_withdrawal_percentiles: Record<string, number[]>;
  b_success_rate: number;
  b_percentile_trajectories: Record<string, number[]>;
  baseline_annual_wd: number;
  metrics: Array<Record<string, string>>;
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
  target_success: number;
  upper_guardrail: number;
  lower_guardrail: number;
  adjustment_pct: number;
  adjustment_mode: "amount" | "success_rate";
  min_remaining_years: number;
  baseline_rate: number;
  initial_portfolio: number;
  hist_start_year: number;
  cash_flows: CashFlowItem[];
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
  withdrawal_strategy: "fixed" | "dynamic";
  dynamic_ceiling: number;
  dynamic_floor: number;
  cash_flows: CashFlowItem[];
}

export const DEFAULT_PARAMS: FormParams = {
  initial_portfolio: 1_000_000,
  annual_withdrawal: 40_000,
  allocation: { us_stock: 0.4, intl_stock: 0.4, us_bond: 0.2 },
  expense_ratios: { us_stock: 0.005, intl_stock: 0.005, us_bond: 0.005 },
  retirement_years: 65,
  min_block: 5,
  max_block: 15,
  num_simulations: 10_000,
  data_start_year: 1926,
  withdrawal_strategy: "fixed",
  dynamic_ceiling: 0.05,
  dynamic_floor: 0.025,
  cash_flows: [],
};
