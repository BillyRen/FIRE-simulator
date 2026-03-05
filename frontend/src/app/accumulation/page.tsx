"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SidebarForm, NumberField } from "@/components/sidebar-form";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { useIsMobile } from "@/components/fan-chart";
import { CHART_COLORS, MARGINS } from "@/lib/chart-theme";
import { runAccumulation } from "@/lib/api";
import { useSharedParams } from "@/lib/params-context";
import type { AccumulationResponse } from "@/lib/types";

const RISK_MAP: Record<string, number> = {
  conservative: 0.95,
  moderate: 0.85,
  aggressive: 0.75,
};

export default function AccumulationPage() {
  const t = useTranslations("accumulation");
  const tc = useTranslations("common");
  const isMobile = useIsMobile();

  const { params, setParams } = useSharedParams();

  const [currentAge, setCurrentAge] = useState(30);
  const [lifeExpectancy, setLifeExpectancy] = useState(90);
  const [currentPortfolio, setCurrentPortfolio] = useState(100_000);
  const [annualIncome, setAnnualIncome] = useState(120_000);
  const [annualExpenses, setAnnualExpenses] = useState(60_000);
  const [incomeGrowthRate, setIncomeGrowthRate] = useState(2);
  const [retirementSpending, setRetirementSpending] = useState(60_000);
  const [riskTolerance, setRiskTolerance] = useState("moderate");

  const [result, setResult] = useState<AccumulationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const retYears = Math.max(5, lifeExpectancy - currentAge);
    if (params.retirement_years !== retYears) {
      setParams({ ...params, retirement_years: retYears });
    }
  }, [currentAge, lifeExpectancy]);

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runAccumulation({
        current_age: currentAge,
        life_expectancy: lifeExpectancy,
        current_portfolio: currentPortfolio,
        annual_income: annualIncome,
        annual_expenses: annualExpenses,
        income_growth_rate: incomeGrowthRate / 100,
        retirement_spending: retirementSpending,
        target_success_rate: RISK_MAP[riskTolerance],
        allocation: params.allocation,
        expense_ratios: params.expense_ratios,
        withdrawal_strategy: params.withdrawal_strategy,
        dynamic_ceiling: params.dynamic_ceiling,
        dynamic_floor: params.dynamic_floor,
        retirement_years: Math.max(5, lifeExpectancy - currentAge),
        min_block: params.min_block,
        max_block: params.max_block,
        num_simulations: params.num_simulations,
        data_start_year: params.data_start_year,
        country: params.country,
        pooling_method: params.pooling_method,
        data_source: params.data_source,
        leverage: params.leverage,
        borrowing_spread: params.borrowing_spread,
        cash_flows: params.cash_flows,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
    }
  };

  const fmt = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const pct = (n: number) => `${(n * 100).toFixed(1)}%`;

  return (
    <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 p-3 sm:p-6 max-w-[1600px] mx-auto">
      {/* ── 左侧参数 ── */}
      <aside className="lg:w-[340px] shrink-0 space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t("title")}</CardTitle>
            <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              <NumberField
                label={t("currentAge")}
                value={currentAge}
                onChange={setCurrentAge}
                min={18}
                max={80}
              />
              <NumberField
                label={t("lifeExpectancy")}
                value={lifeExpectancy}
                onChange={setLifeExpectancy}
                min={50}
                max={120}
              />
            </div>

            <NumberField
              label={t("currentPortfolio")}
              value={currentPortfolio}
              onChange={setCurrentPortfolio}
              min={0}
            />

            <div className="grid grid-cols-2 gap-2">
              <NumberField
                label={t("annualIncome")}
                value={annualIncome}
                onChange={setAnnualIncome}
                min={0}
              />
              <NumberField
                label={t("annualExpenses")}
                value={annualExpenses}
                onChange={setAnnualExpenses}
                min={0}
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <NumberField
                label={t("incomeGrowthRate")}
                value={incomeGrowthRate}
                onChange={setIncomeGrowthRate}
                min={-10}
                max={20}
                step={0.5}
                suffix="%"
              />
              <NumberField
                label={t("retirementSpending")}
                value={retirementSpending}
                onChange={setRetirementSpending}
                min={0}
              />
            </div>

            <div>
              <Label className="text-xs">{t("riskTolerance")}</Label>
              <Select value={riskTolerance} onValueChange={setRiskTolerance}>
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="conservative">{t("riskConservative")}</SelectItem>
                  <SelectItem value="moderate">{t("riskModerate")}</SelectItem>
                  <SelectItem value="aggressive">{t("riskAggressive")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <SidebarForm
              params={params}
              onChange={setParams}
              showWithdrawalStrategy={true}
            />

            <Button onClick={handleRun} className="w-full" disabled={loading}>
              {loading ? "..." : t("run")}
            </Button>
          </CardContent>
        </Card>
      </aside>

      {/* ── 右侧结果 ── */}
      <main className="flex-1 space-y-6 min-w-0">
        {error && (
          <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading && <LoadingOverlay message={t("run")} />}

        {result && !loading && (
          <>
            {/* 关键指标卡片 */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <MetricCard
                label={t("fireAgeP50")}
                value={result.fire_age_p50 != null ? `${result.fire_age_p50}` : "N/A"}
                highlight
              />
              <MetricCard
                label={t("fireAgeRange")}
                value={
                  result.fire_age_p25 != null && result.fire_age_p75 != null
                    ? `${result.fire_age_p25} – ${result.fire_age_p75}`
                    : "N/A"
                }
              />
              <MetricCard label={t("fireProbability")} value={pct(result.fire_probability)} />
              <MetricCard label={t("savingsRate")} value={pct(result.savings_rate)} />
              <MetricCard label={t("annualSavings")} value={fmt(result.annual_savings)} />
              <MetricCard label={t("swrAtFire")} value={pct(result.swr_at_fire)} />
              <MetricCard label={t("requiredPortfolio")} value={fmt(result.required_portfolio_at_fire)} />
            </div>

            {result.fire_probability === 0 && (
              <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
                {t("noFireWarning")}
              </div>
            )}

            {/* 图 1: 资产增长轨迹 + FIRE 目标线 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t("chartPortfolio")}</CardTitle>
                <p className="text-xs text-muted-foreground">{t("chartPortfolioDesc")}</p>
              </CardHeader>
              <CardContent>
                <PlotlyChart
                  data={[
                    // P10-P90 扇形
                    {
                      x: result.age_labels,
                      y: result.percentile_trajectories.p90,
                      type: "scatter",
                      mode: "lines",
                      line: { width: 0 },
                      showlegend: false,
                      hoverinfo: "skip",
                    },
                    {
                      x: result.age_labels,
                      y: result.percentile_trajectories.p10,
                      type: "scatter",
                      mode: "lines",
                      line: { width: 0 },
                      fill: "tonexty",
                      fillcolor: `${CHART_COLORS.primary.hex}15`,
                      showlegend: false,
                      hoverinfo: "skip",
                    },
                    // P25-P75 扇形
                    {
                      x: result.age_labels,
                      y: result.percentile_trajectories.p75,
                      type: "scatter",
                      mode: "lines",
                      line: { width: 0 },
                      showlegend: false,
                      hoverinfo: "skip",
                    },
                    {
                      x: result.age_labels,
                      y: result.percentile_trajectories.p25,
                      type: "scatter",
                      mode: "lines",
                      line: { width: 0 },
                      fill: "tonexty",
                      fillcolor: `${CHART_COLORS.primary.hex}30`,
                      showlegend: false,
                      hoverinfo: "skip",
                    },
                    // P50 中位数线
                    {
                      x: result.age_labels,
                      y: result.percentile_trajectories.p50,
                      type: "scatter",
                      mode: "lines",
                      line: { color: CHART_COLORS.primary.hex, width: 2.5 },
                      name: t("accumulatedPortfolio"),
                    },
                    // 所需 FIRE 资产线
                    {
                      x: result.age_labels,
                      y: result.required_portfolio_curve,
                      type: "scatter",
                      mode: "lines",
                      line: { color: CHART_COLORS.danger.hex, width: 2.5, dash: "dash" },
                      name: t("requiredFirePortfolio"),
                    },
                  ]}
                  layout={{
                    xaxis: {
                      title: { text: t("age") },
                      tickfont: { size: isMobile ? 9 : 12 },
                    },
                    yaxis: {
                      title: isMobile ? undefined : { text: "$" },
                      tickformat: "$~s",
                      tickfont: { size: isMobile ? 9 : 12 },
                    },
                    height: isMobile ? 300 : 450,
                    margin: MARGINS.default(isMobile),
                    legend: {
                      orientation: "h" as const,
                      y: -0.15,
                      x: 0.5,
                      xanchor: "center" as const,
                    },
                  }}
                  config={{
                    displayModeBar: isMobile ? false : ("hover" as const),
                  }}
                />
              </CardContent>
            </Card>

            {/* 图 2: FIRE 达成概率 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t("chartFireProb")}</CardTitle>
                <p className="text-xs text-muted-foreground">{t("chartFireProbDesc")}</p>
              </CardHeader>
              <CardContent>
                <PlotlyChart
                  data={[
                    {
                      x: result.age_labels,
                      y: result.fire_prob_by_year.map((p) => p * 100),
                      type: "scatter",
                      mode: "lines",
                      fill: "tozeroy",
                      fillcolor: `${CHART_COLORS.accent.hex}20`,
                      line: { color: CHART_COLORS.accent.hex, width: 2.5 },
                      name: t("fireProbability"),
                    },
                  ]}
                  layout={{
                    xaxis: {
                      title: { text: t("age") },
                      tickfont: { size: isMobile ? 9 : 12 },
                    },
                    yaxis: {
                      title: isMobile ? undefined : { text: t("probability") },
                      range: [0, 105],
                      tickfont: { size: isMobile ? 9 : 12 },
                    },
                    height: isMobile ? 260 : 350,
                    margin: MARGINS.default(isMobile),
                  }}
                  config={{
                    displayModeBar: isMobile ? false : ("hover" as const),
                  }}
                />
              </CardContent>
            </Card>

            {/* 图 3: 敏感性分析 */}
            {result.sensitivity_fire_ages.some((a) => a != null) && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{t("chartSensitivity")}</CardTitle>
                  <p className="text-xs text-muted-foreground">{t("chartSensitivityDesc")}</p>
                </CardHeader>
                <CardContent>
                  <PlotlyChart
                    data={[
                      {
                        x: result.sensitivity_expenses.map((e) => e),
                        y: result.sensitivity_fire_ages,
                        type: "scatter",
                        mode: "lines+markers",
                        marker: { size: 6, color: CHART_COLORS.secondary.hex },
                        line: { color: CHART_COLORS.secondary.hex, width: 2 },
                        name: t("fireAge"),
                      },
                    ]}
                    layout={{
                      xaxis: {
                        title: { text: t("annualExpense") },
                        tickformat: "$~s",
                        tickfont: { size: isMobile ? 9 : 12 },
                      },
                      yaxis: {
                        title: isMobile ? undefined : { text: t("fireAge") },
                        tickfont: { size: isMobile ? 9 : 12 },
                      },
                      height: isMobile ? 260 : 350,
                      margin: MARGINS.default(isMobile),
                    }}
                    config={{
                      displayModeBar: isMobile ? false : ("hover" as const),
                    }}
                  />
                </CardContent>
              </Card>
            )}
          </>
        )}

        {!result && !loading && (
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            {t("placeholder")}
          </div>
        )}
      </main>
    </div>
  );
}

function MetricCard({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        highlight ? "bg-primary/5 border-primary/20" : "bg-card"
      }`}
    >
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className={`text-lg font-semibold ${highlight ? "text-primary" : ""}`}>{value}</p>
    </div>
  );
}
