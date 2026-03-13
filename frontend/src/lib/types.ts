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
  growth_rate?: number; // 年度复合增长率, 默认 0
  enabled?: boolean; // 默认 true
  probability?: number; // 组内概率权重 (0,1], 默认 1.0
  group?: string | null; // 互斥组名, null=确定事件
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
  withdrawal_strategy: "fixed" | "dynamic" | "declining" | "smile";
  retirement_age: number;
  dynamic_ceiling: number;
  dynamic_floor: number;
  declining_rate: number;
  declining_start_age: number;
  smile_decline_rate: number;
  smile_decline_start_age: number;
  smile_min_age: number;
  smile_increase_rate: number;
  leverage: number;
  borrowing_spread: number;
  cash_flows: CashFlowItem[];
  glide_path_enabled: boolean;
  glide_path_end_allocation: Allocation;
  glide_path_years: number;
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
  withdrawal_strategy: "fixed" | "dynamic" | "declining" | "smile";
  retirement_age: number;
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
  consumption_floor: number;
  consumption_floor_amount: number;
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
  withdrawal_strategy: "fixed" | "dynamic" | "declining" | "smile";
  retirement_age: number;
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
  withdrawal_strategy: "fixed" | "dynamic" | "declining" | "smile";
  retirement_age: number;
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
  is_near_optimal: boolean;
  is_pareto: boolean;
}

export interface AllocationSweepResponse {
  results: AllocationResult[];
  best: AllocationResult;
  near_optimal_count: number;
  near_optimal_threshold: number;
  pareto_frontier: AllocationResult[];
}

// ---------------------------------------------------------------------------
// 6. 买房 vs 租房
// ---------------------------------------------------------------------------

export interface BuyVsRentSimpleRequest {
  home_price: number;
  down_payment_pct: number;
  mortgage_term: number;
  buying_cost_pct: number;
  selling_cost_pct: number;
  property_tax_pct: number;
  maintenance_pct: number;
  insurance_annual: number;
  annual_rent: number;
  analysis_years: number;
  mortgage_rate: number;
  rent_growth_rate: number;
  home_appreciation_rate: number;
  investment_return_rate: number;
  inflation_rate: number;
}

export interface BuyVsRentSimpleResponse {
  analysis_years: number;
  buy_net_worth_real: number[];
  rent_net_worth_real: number[];
  advantage_real: number[];
  breakeven_year: number | null;
  home_value_real: number[];
  mortgage_balance_real: number[];
  buy_cost_total_real: number[];
  rent_cost_real: number[];
  buy_cost_interest_real: number[];
  buy_cost_principal_real: number[];
  buy_cost_tax_real: number[];
  buy_cost_maintenance_real: number[];
  buy_cost_insurance_real: number[];
  summary: Record<string, number | null>;
}

export interface BuyVsRentMCRequest {
  home_price: number;
  down_payment_pct: number;
  mortgage_term: number;
  buying_cost_pct: number;
  selling_cost_pct: number;
  property_tax_pct: number;
  maintenance_pct: number;
  insurance_annual: number;
  annual_rent: number;
  analysis_years: number;
  mortgage_rate_spread: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  leverage: number;
  borrowing_spread: number;
  override_home_appreciation: number | null;
  override_rent_growth: number | null;
  override_mortgage_rate: number | null;
}

export interface BuyVsRentMCResponse {
  num_simulations: number;
  analysis_years: number;
  buy_percentile_trajectories: Record<string, number[]>;
  rent_percentile_trajectories: Record<string, number[]>;
  advantage_percentile_trajectories: Record<string, number[]>;
  buy_wins_probability: number[];
  breakeven_percentiles: Record<string, number>;
  buy_cost_median: number[];
  rent_cost_median: number[];
  sampled_stats: Array<Record<string, string>>;
  summary: Record<string, number | null>;
}

export interface HousingCountryInfo {
  iso: string;
  name_en: string;
  name_zh: string;
  min_year: number;
  max_year: number;
  n_years: number;
  has_housing: boolean;
  housing_years: number;
}

// ---------------------------------------------------------------------------
// 6b. 盈亏平衡房价查找
// ---------------------------------------------------------------------------

export interface BreakevenSimpleRequest {
  down_payment_pct: number;
  mortgage_term: number;
  buying_cost_pct: number;
  selling_cost_pct: number;
  property_tax_pct: number;
  maintenance_pct: number;
  insurance_annual: number;
  annual_rent: number;
  analysis_years: number;
  mortgage_rate: number;
  rent_growth_rate: number;
  home_appreciation_rate: number;
  investment_return_rate: number;
  inflation_rate: number;
  price_low?: number;
  price_high?: number;
  auto_estimate_ha?: boolean;
  fair_pe?: number;
  reversion_years?: number;
}

export interface BreakevenMCRequest {
  down_payment_pct: number;
  mortgage_term: number;
  buying_cost_pct: number;
  selling_cost_pct: number;
  property_tax_pct: number;
  maintenance_pct: number;
  insurance_annual: number;
  annual_rent: number;
  analysis_years: number;
  mortgage_rate_spread: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  leverage: number;
  borrowing_spread: number;
  override_home_appreciation: number | null;
  override_rent_growth: number | null;
  override_mortgage_rate: number | null;
  target_win_pct: number;
  price_low?: number;
  price_high?: number;
}

export interface BreakevenResponse {
  found: boolean;
  breakeven_price: number | null;
  price_to_annual_rent: number | null;
  message?: string;
  summary?: Record<string, number | null>;
  advantage_at_low?: number;
  advantage_at_high?: number;
  target_win_pct?: number;
  actual_win_pct?: number;
  median_advantage?: number;
  median_buy_nw?: number;
  median_rent_nw?: number;
  win_pct_at_low?: number;
  win_pct_at_high?: number;
  ha_at_breakeven?: number;
}

// ---------------------------------------------------------------------------
// FIRE 积累阶段计算器
// ---------------------------------------------------------------------------

export interface AccumulationRequest {
  current_age: number;
  life_expectancy: number;
  current_portfolio: number;
  annual_income: number;
  annual_expenses: number;
  income_growth_rate: number;
  expense_growth_rate: number;
  retirement_spending: number;
  auto_retirement_spending: boolean;
  target_success_rate: number;
  allocation: Allocation;
  expense_ratios: ExpenseRatios;
  withdrawal_strategy: "fixed" | "dynamic" | "declining" | "smile";
  dynamic_ceiling: number;
  dynamic_floor: number;
  retirement_years: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  leverage: number;
  borrowing_spread: number;
  cash_flows: CashFlowItem[];
}

export interface AccumulationResponse {
  fire_age_p25: number | null;
  fire_age_p50: number | null;
  fire_age_p75: number | null;
  fire_probability: number;
  savings_rate: number;
  annual_savings: number;
  swr_at_fire: number;
  required_portfolio_at_fire: number;
  retirement_spending_at_fire: number;
  percentile_trajectories: Record<string, number[]>;
  required_portfolio_curve: number[];
  swr_curve: number[];
  fire_prob_by_year: number[];
  age_labels: number[];
  sensitivity_expenses: number[];
  sensitivity_fire_ages: (number | null)[];
}

// ---------------------------------------------------------------------------
// Historical events
// ---------------------------------------------------------------------------

export interface HistoricalEvent {
  year: number;
  year_end?: number;
  countries: string[];
  label_en: string;
  label_zh: string;
  category: "crisis" | "war" | "bubble" | "policy";
}

// ---------------------------------------------------------------------------
// 现金流情景分析
// ---------------------------------------------------------------------------

export interface ScenarioResult {
  label: string;
  probability: number;
  success_rate: number;
  funded_ratio: number;
  median_final_portfolio: number;
  median_total_consumption: number;
  annual_withdrawal: number;
  initial_portfolio: number;
}

export interface ScenarioAnalysisResponse {
  base_case: ScenarioResult;
  scenarios: ScenarioResult[];
  mode?: "full" | "per_group";
}

// ---------------------------------------------------------------------------
// 参数敏感性分析（龙卷风图）
// ---------------------------------------------------------------------------

export interface SensitivityDelta {
  param_label: string;
  param_key: string;
  low_value: number;
  high_value: number;
  base_value: number;
  low_success_rate: number;
  high_success_rate: number;
  low_funded_ratio: number;
  high_funded_ratio: number;
  low_withdrawal?: number;
  high_withdrawal?: number;
}

export interface SensitivityAnalysisResponse {
  base_success_rate: number;
  base_funded_ratio: number;
  base_withdrawal?: number;
  deltas: SensitivityDelta[];
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
  life_expectancy: number;
  min_block: number;
  max_block: number;
  num_simulations: number;
  data_start_year: number;
  country: string;
  pooling_method: "equal" | "gdp_sqrt";
  data_source: "jst" | "fire_dataset";
  withdrawal_strategy: "fixed" | "dynamic" | "declining" | "smile";
  retirement_age: number;
  dynamic_ceiling: number;
  dynamic_floor: number;
  declining_rate: number;
  declining_start_age: number;
  smile_decline_rate: number;
  smile_decline_start_age: number;
  smile_min_age: number;
  smile_increase_rate: number;
  leverage: number;
  borrowing_spread: number;
  cash_flows: CashFlowItem[];
  glide_path_enabled: boolean;
  glide_path_end_allocation: Allocation;
  glide_path_years: number;
}

export const DEFAULT_PARAMS: FormParams = {
  initial_portfolio: 1_000_000,
  annual_withdrawal: 40_000,
  allocation: { domestic_stock: 0.4, global_stock: 0.4, domestic_bond: 0.2 },
  expense_ratios: { domestic_stock: 0.005, global_stock: 0.005, domestic_bond: 0.005 },
  retirement_years: 55,
  life_expectancy: 100,
  min_block: 5,
  max_block: 15,
  num_simulations: 2_000,
  data_start_year: 1900,
  country: "USA",
  pooling_method: "gdp_sqrt",
  data_source: "jst",
  withdrawal_strategy: "fixed",
  retirement_age: 45,
  dynamic_ceiling: 0.05,
  dynamic_floor: 0.025,
  declining_rate: 0.02,
  declining_start_age: 65,
  smile_decline_rate: 0.01,
  smile_decline_start_age: 65,
  smile_min_age: 80,
  smile_increase_rate: 0.01,
  leverage: 1.0,
  borrowing_spread: 0.02,
  cash_flows: [],
  glide_path_enabled: false,
  glide_path_end_allocation: { domestic_stock: 0.2, global_stock: 0.1, domestic_bond: 0.7 },
  glide_path_years: 20,
};
