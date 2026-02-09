"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SidebarForm, NumberField } from "@/components/sidebar-form";
import { FanChart, useIsMobile } from "@/components/fan-chart";
import { MetricCard } from "@/components/metric-card";
import { StatsTable } from "@/components/stats-table";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { runGuardrail, runBacktest } from "@/lib/api";
import { downloadCSV, downloadTrajectories } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { DEFAULT_PARAMS } from "@/lib/types";
import type { FormParams, GuardrailResponse, BacktestResponse } from "@/lib/types";

function fmt(n: number): string {
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export default function GuardrailPage() {
  const t = useTranslations("guardrail");
  const tc = useTranslations("common");
  const isMobile = useIsMobile();

  const [params, setParams] = useState<FormParams>(DEFAULT_PARAMS);
  const [withdrawal, setWithdrawal] = useState(40_000);

  // Guardrail-specific params
  const [targetSuccess, setTargetSuccess] = useState(0.8);
  const [upperGuardrail, setUpperGuardrail] = useState(0.99);
  const [lowerGuardrail, setLowerGuardrail] = useState(0.5);
  const [adjustmentPct, setAdjustmentPct] = useState(0.5);
  const [adjustmentMode, setAdjustmentMode] = useState<"amount" | "success_rate">("amount");
  const [minRemainingYears, setMinRemainingYears] = useState(10);
  const [baselineRate, setBaselineRate] = useState(0.033);

  // Backtest
  const [histStartYear, setHistStartYear] = useState(1990);

  // Results
  const [mcResult, setMcResult] = useState<GuardrailResponse | null>(null);
  const [btResult, setBtResult] = useState<BacktestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [btLoading, setBtLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const guardrailReqBase = () => ({
    annual_withdrawal: withdrawal,
    allocation: params.allocation,
    expense_ratios: params.expense_ratios,
    retirement_years: params.retirement_years,
    min_block: params.min_block,
    max_block: params.max_block,
    num_simulations: params.num_simulations,
    data_start_year: params.data_start_year,
    target_success: targetSuccess,
    upper_guardrail: upperGuardrail,
    lower_guardrail: lowerGuardrail,
    adjustment_pct: adjustmentPct,
    adjustment_mode: adjustmentMode,
    min_remaining_years: minRemainingYears,
    baseline_rate: baselineRate,
    leverage: params.leverage,
    borrowing_spread: params.borrowing_spread,
    cash_flows: params.cash_flows,
  });

  const handleRunMC = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runGuardrail(guardrailReqBase());
      setMcResult(res);
      setBtResult(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
    }
  };

  const handleRunBacktest = async () => {
    if (!mcResult) return;
    setBtLoading(true);
    setError(null);
    try {
      const res = await runBacktest({
        ...guardrailReqBase(),
        initial_portfolio: mcResult.initial_portfolio,
        hist_start_year: histStartYear,
      });
      setBtResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setBtLoading(false);
    }
  };

  return (
    <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 p-3 sm:p-6 max-w-[1600px] mx-auto">
      {/* ── 左侧参数面板 ── */}
      <aside className="lg:w-[340px] shrink-0 space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t("title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <NumberField
              label={tc("annualWithdrawalAlt")}
              value={withdrawal}
              onChange={setWithdrawal}
              min={0}
            />

            <SidebarForm
              params={params}
              onChange={setParams}
              showWithdrawalStrategy={false}
            >
              <Separator />
              <div>
                <h3 className="text-sm font-semibold mb-2">{t("guardrailSettings")}</h3>
                <div className="grid grid-cols-2 gap-2">
                  <NumberField
                    label={t("targetSuccess")}
                    value={+(targetSuccess * 100).toFixed(0)}
                    onChange={(v) => setTargetSuccess(v / 100)}
                    min={1}
                    max={99}
                  />
                  <NumberField
                    label={t("baselineRate")}
                    value={+(baselineRate * 100).toFixed(1)}
                    onChange={(v) => setBaselineRate(v / 100)}
                    min={0.1}
                    max={50}
                    step={0.1}
                  />
                  <NumberField
                    label={t("upperGuardrail")}
                    value={+(upperGuardrail * 100).toFixed(0)}
                    onChange={(v) => setUpperGuardrail(v / 100)}
                    min={1}
                    max={100}
                  />
                  <NumberField
                    label={t("lowerGuardrail")}
                    value={+(lowerGuardrail * 100).toFixed(0)}
                    onChange={(v) => setLowerGuardrail(v / 100)}
                    min={0}
                    max={99}
                  />
                </div>

                <div className="mt-2 space-y-2">
                  <div>
                    <Label className="text-xs">{t("adjustmentMode")}</Label>
                    <Select
                      value={adjustmentMode}
                      onValueChange={(v) => setAdjustmentMode(v as "amount" | "success_rate")}
                    >
                      <SelectTrigger className="h-8 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="amount">{t("amountMode")}</SelectItem>
                        <SelectItem value="success_rate">{t("successRateMode")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <NumberField
                    label={t("adjustmentPct")}
                    value={+(adjustmentPct * 100).toFixed(0)}
                    onChange={(v) => setAdjustmentPct(v / 100)}
                    min={1}
                    max={100}
                    help={
                      adjustmentMode === "amount"
                        ? t("amountModeHelp")
                        : t("successRateModeHelp")
                    }
                  />
                  <NumberField
                    label={t("minRemainingYears")}
                    value={minRemainingYears}
                    onChange={(v) => setMinRemainingYears(Math.round(v))}
                    min={1}
                    max={30}
                  />
                </div>
              </div>
            </SidebarForm>

            <Button onClick={handleRunMC} className="w-full" disabled={loading}>
              {loading ? tc("running") : t("runSimulation")}
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

        {loading && <LoadingOverlay message={t("guardrailLoading")} />}

        {mcResult && !loading && (
          <Tabs defaultValue="mc">
            <TabsList className="mb-4">
              <TabsTrigger value="mc">{t("mcTab")}</TabsTrigger>
              <TabsTrigger value="backtest">{t("backtestTab")}</TabsTrigger>
            </TabsList>

            {/* ═══ MC Tab ═══ */}
            <TabsContent value="mc" className="space-y-6">
              {/* 下载按钮组 */}
              <div className="flex flex-wrap gap-2">
                <DownloadButton
                  label={t("downloadPortfolioTrajectory")}
                  onClick={() =>
                    downloadTrajectories("guardrail_portfolio", mcResult.g_percentile_trajectories)
                  }
                />
                <DownloadButton
                  label={t("downloadWithdrawalTrajectory")}
                  onClick={() =>
                    downloadTrajectories("guardrail_withdrawal", mcResult.g_withdrawal_percentiles)
                  }
                />
                <DownloadButton
                  label={t("downloadBaselineTrajectory")}
                  onClick={() =>
                    downloadTrajectories("baseline_portfolio", mcResult.b_percentile_trajectories)
                  }
                />
              </div>

              {/* 指标卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard
                  label={t("initialPortfolio")}
                  value={fmt(mcResult.initial_portfolio)}
                />
                <MetricCard
                  label={t("initialRate")}
                  value={pct(mcResult.initial_rate)}
                />
                <MetricCard
                  label={t("guardrailSuccess")}
                  value={pct(mcResult.g_success_rate)}
                />
                <MetricCard
                  label={t("baselineSuccess")}
                  value={pct(mcResult.b_success_rate)}
                  sub={t("baselineRateSub", { rate: (baselineRate * 100).toFixed(1) })}
                />
              </div>

              {/* 资产轨迹对比 */}
              <Card>
                <CardContent className="pt-4">
                  <FanChart
                    trajectories={mcResult.g_percentile_trajectories}
                    title={t("portfolioComparison")}
                    extraTraces={[
                      {
                        y: mcResult.b_percentile_trajectories["50"],
                        mode: "lines",
                        name: tc("baselineP50"),
                        line: { color: "rgb(234,88,12)", width: 2, dash: "dash" },
                        type: "scatter",
                      },
                    ]}
                  />
                </CardContent>
              </Card>

              {/* 提取金额轨迹 */}
              <Card>
                <CardContent className="pt-4">
                  <FanChart
                    trajectories={mcResult.g_withdrawal_percentiles}
                    title={t("withdrawalTrajectory")}
                    color="16, 185, 129"
                    extraTraces={[
                      {
                        y: mcResult.b_withdrawal_percentiles?.["50"] ?? Array(
                          mcResult.g_withdrawal_percentiles["50"]?.length ?? 0
                        ).fill(mcResult.baseline_annual_wd),
                        mode: "lines",
                        name: t("baselineP50Withdrawal"),
                        line: { color: "rgb(234,88,12)", width: 2, dash: "dash" },
                        type: "scatter",
                        hovertemplate: tc.raw("baselineHover"),
                      },
                      {
                        y: (() => {
                          const bP50 = mcResult.b_withdrawal_percentiles?.["50"];
                          const baseWd = mcResult.baseline_annual_wd;
                          if (bP50) {
                            return bP50.map((v) => withdrawal + (v - baseWd));
                          }
                          const n = mcResult.g_withdrawal_percentiles["50"]?.length ?? 0;
                          return Array(n).fill(withdrawal);
                        })(),
                        mode: "lines",
                        name: tc("initialWithdrawalLine", { amount: fmt(withdrawal) }),
                        line: { color: "gray", width: 1, dash: "dot" },
                        type: "scatter",
                        hovertemplate: tc.raw("initialWithdrawalHover"),
                      },
                    ]}
                  />
                </CardContent>
              </Card>

              {/* 指标对比表 */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{t("metricsTitle")}</CardTitle>
                </CardHeader>
                <CardContent>
                  <StatsTable rows={mcResult.metrics} downloadName="guardrail_metrics" />
                </CardContent>
              </Card>
            </TabsContent>

            {/* ═══ 回测 Tab ═══ */}
            <TabsContent value="backtest" className="space-y-6">
              <Card>
                <CardContent className="pt-4 space-y-3">
                  <div className="flex items-end gap-3">
                    <div className="w-28">
                      <NumberField
                        label={t("backtestStartYear")}
                        value={histStartYear}
                        onChange={(v) => setHistStartYear(Math.round(v))}
                        min={params.data_start_year}
                        max={2024}
                      />
                    </div>
                    <Button
                      onClick={handleRunBacktest}
                      disabled={btLoading}
                      size="sm"
                    >
                      {btLoading ? t("backtesting") : t("runBacktest")}
                    </Button>
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    {t("backtestPortfolioNote", { amount: fmt(mcResult.initial_portfolio) })}
                  </p>
                </CardContent>
              </Card>

              {btLoading && <LoadingOverlay message={t("backtestLoading")} />}

              {btResult && !btLoading && (
                <>
                  {/* 下载按钮 */}
                  <div className="flex flex-wrap gap-2">
                    <DownloadButton
                      label={t("downloadBacktestData")}
                      onClick={() => {
                        const n = btResult.years_simulated;
                        const headers = [
                          t("backtestHeaderYear"),
                          t("backtestHeaderGAsset"),
                          t("backtestHeaderGWithdrawal"),
                          t("backtestHeaderGSuccess"),
                          t("backtestHeaderBAsset"),
                          t("backtestHeaderBWithdrawal"),
                        ];
                        const rows: (string | number)[][] = [];
                        for (let i = 0; i < n; i++) {
                          rows.push([
                            btResult.year_labels[i],
                            Math.round(btResult.g_portfolio[i]),
                            Math.round(btResult.g_withdrawals[i]),
                            `${(btResult.g_success_rates[i] * 100).toFixed(1)}%`,
                            Math.round(btResult.b_portfolio[i]),
                            Math.round(btResult.b_withdrawals[i]),
                          ]);
                        }
                        if (btResult.g_portfolio.length > n) {
                          rows.push([
                            btResult.year_labels[n] ?? btResult.year_labels[n - 1] + 1,
                            Math.round(btResult.g_portfolio[n]),
                            "",
                            "",
                            Math.round(btResult.b_portfolio[n]),
                            "",
                          ]);
                        }
                        downloadCSV("backtest_data", headers, rows);
                      }}
                    />
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <MetricCard
                      label={t("guardrailTotalConsumption")}
                      value={fmt(btResult.g_total_consumption)}
                    />
                    <MetricCard
                      label={t("baselineTotalConsumption")}
                      value={fmt(btResult.b_total_consumption)}
                    />
                    <MetricCard
                      label={t("guardrailFinalPortfolio")}
                      value={fmt(btResult.g_portfolio[btResult.g_portfolio.length - 1])}
                    />
                    <MetricCard
                      label={t("baselineFinalPortfolio")}
                      value={fmt(btResult.b_portfolio[btResult.b_portfolio.length - 1])}
                    />
                  </div>

                  {/* 资产轨迹 */}
                  <Card>
                    <CardContent className="pt-4">
                      <PlotlyChart
                        data={[
                          {
                            x: btResult.year_labels,
                            y: btResult.g_portfolio,
                            type: "scatter",
                            mode: "lines",
                            name: "Guardrail",
                            line: { color: "rgb(59,130,246)", width: 2 },
                          },
                          {
                            x: btResult.year_labels,
                            y: btResult.b_portfolio,
                            type: "scatter",
                            mode: "lines",
                            name: tc("baseline"),
                            line: {
                              color: "rgb(234,88,12)",
                              width: 2,
                              dash: "dash",
                            },
                          },
                        ]}
                        layout={{
                          title: isMobile
                            ? { text: t("historicalPortfolioComparison"), font: { size: 12 }, y: 0.98, yanchor: "top" as const }
                            : { text: t("historicalPortfolioComparison"), font: { size: 14 } },
                          xaxis: { title: { text: t("yearAxis") }, tickfont: { size: isMobile ? 9 : 12 } },
                          yaxis: { title: isMobile ? undefined : { text: t("assetAxis") }, tickformat: isMobile ? "$~s" : "$,.0f", tickfont: { size: isMobile ? 9 : 12 } },
                          height: isMobile ? 300 : 400,
                          margin: isMobile ? { l: 45, r: 10, t: 35, b: 55 } : { l: 80, r: 30, t: 80, b: 50 },
                          legend: isMobile
                            ? { x: 0.5, y: -0.2, xanchor: "center" as const, yanchor: "top" as const, orientation: "h" as const, font: { size: 9 } }
                            : { x: 0, y: 1.0, yanchor: "bottom" as const, orientation: "h" as const },
                          hovermode: "x unified",
                        }}
                        config={{
                          responsive: true,
                          displayModeBar: "hover",
                          modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
                          toImageButtonOptions: { format: "png", height: 800, width: 1200, scale: 2 },
                        }}
                        style={{ width: "100%" }}
                      />
                    </CardContent>
                  </Card>

                  {/* 提取金额 + 成功率 */}
                  <Card>
                    <CardContent className="pt-4">
                      <PlotlyChart
                        data={[
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: btResult.g_withdrawals,
                            type: "scatter",
                            mode: "lines",
                            name: t("guardrailWithdrawal"),
                            line: { color: "rgb(59,130,246)", width: 2 },
                            yaxis: "y",
                          },
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: btResult.b_withdrawals,
                            type: "scatter",
                            mode: "lines",
                            name: t("baselineWithdrawal"),
                            line: {
                              color: "rgb(234,88,12)",
                              width: 2,
                              dash: "dash",
                            },
                            yaxis: "y",
                          },
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: btResult.g_success_rates.map((s) => s * 100),
                            type: "scatter",
                            mode: "lines",
                            name: t("successRateLine"),
                            line: { color: "rgba(100,100,100,0.5)", width: 1 },
                            fill: "tozeroy",
                            fillcolor: "rgba(100,100,100,0.08)",
                            yaxis: "y2",
                          },
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: Array(btResult.years_simulated).fill(
                              upperGuardrail * 100
                            ),
                            type: "scatter",
                            mode: "lines",
                            name: t("upperGuardrailLine", { pct: (upperGuardrail * 100).toFixed(0) }),
                            line: {
                              color: "green",
                              width: 1,
                              dash: "dot",
                            },
                            yaxis: "y2",
                          },
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: Array(btResult.years_simulated).fill(
                              lowerGuardrail * 100
                            ),
                            type: "scatter",
                            mode: "lines",
                            name: t("lowerGuardrailLine", { pct: (lowerGuardrail * 100).toFixed(0) }),
                            line: {
                              color: "red",
                              width: 1,
                              dash: "dot",
                            },
                            yaxis: "y2",
                          },
                        ]}
                        layout={{
                          title: isMobile
                            ? { text: t("withdrawalAmountAndSuccess"), font: { size: 12 }, y: 0.98, yanchor: "top" as const }
                            : { text: t("withdrawalAmountAndSuccess"), font: { size: 14 } },
                          xaxis: { title: { text: t("yearAxis") }, tickfont: { size: isMobile ? 9 : 12 } },
                          yaxis: {
                            title: isMobile ? undefined : { text: t("withdrawalAmount") },
                            tickformat: isMobile ? "$~s" : "$,.0f",
                            tickfont: { size: isMobile ? 9 : 12 },
                            side: "left",
                          },
                          yaxis2: {
                            title: isMobile ? undefined : { text: t("successRateAxis") },
                            overlaying: "y",
                            side: "right",
                            range: [0, 105],
                            tickfont: { size: isMobile ? 9 : 12 },
                          },
                          height: isMobile ? 320 : 450,
                          margin: isMobile ? { l: 45, r: 35, t: 35, b: 75 } : { l: 80, r: 60, t: 100, b: 50 },
                          legend: isMobile
                            ? { x: 0.5, y: -0.3, xanchor: "center" as const, yanchor: "top" as const, orientation: "h" as const, font: { size: 9 } }
                            : { x: 0, y: 1.0, yanchor: "bottom" as const, orientation: "h" as const },
                          hovermode: "x unified",
                        }}
                        config={{
                          responsive: true,
                          displayModeBar: "hover",
                          modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
                          toImageButtonOptions: { format: "png", height: 800, width: 1200, scale: 2 },
                        }}
                        style={{ width: "100%" }}
                      />
                    </CardContent>
                  </Card>

                  {/* 护栏调整明细表 */}
                  {btResult.adjustment_events && btResult.adjustment_events.length > 0 && (
                    <Card>
                      <CardHeader className="pb-2 flex flex-row items-center justify-between">
                        <CardTitle className="text-sm">
                          {t("adjustmentLogTitle", { count: btResult.adjustment_events.length })}
                        </CardTitle>
                        <DownloadButton
                          label={t("downloadAdjustmentLog")}
                          onClick={() => {
                            const headers = [
                              t("adjHeaderYear"),
                              t("adjHeaderOldWithdrawal"),
                              t("adjHeaderNewWithdrawal"),
                              t("adjHeaderChange"),
                              t("adjHeaderOldSuccess"),
                              t("adjHeaderNewSuccess"),
                            ];
                            const rows = btResult.adjustment_events.map((e) => [
                              btResult.year_labels[e.year],
                              `$${Math.round(e.old_wd).toLocaleString()}`,
                              `$${Math.round(e.new_wd).toLocaleString()}`,
                              `${((e.new_wd / e.old_wd - 1) * 100).toFixed(1)}%`,
                              `${(e.success_before * 100).toFixed(1)}%`,
                              `${(e.success_after * 100).toFixed(1)}%`,
                            ]);
                            downloadCSV("guardrail_adjustments", headers, rows);
                          }}
                        />
                      </CardHeader>
                      <CardContent>
                        <div className="max-h-[400px] overflow-auto">
                          <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-background border-b">
                              <tr>
                                <th className="text-left px-2 py-1.5">{t("adjHeaderYear")}</th>
                                <th className="text-right px-2 py-1.5">{t("adjHeaderOldWithdrawal")}</th>
                                <th className="text-right px-2 py-1.5">{t("adjHeaderNewWithdrawal")}</th>
                                <th className="text-right px-2 py-1.5">{t("adjHeaderChange")}</th>
                                <th className="text-right px-2 py-1.5">{t("adjHeaderOldSuccess")}</th>
                                <th className="text-right px-2 py-1.5">{t("adjHeaderNewSuccess")}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {btResult.adjustment_events.map((e, i) => {
                                const change = (e.new_wd / e.old_wd - 1) * 100;
                                const isUp = change > 0;
                                return (
                                  <tr key={i} className="border-b hover:bg-accent/50">
                                    <td className="px-2 py-1">{btResult.year_labels[e.year]}</td>
                                    <td className="text-right px-2 py-1">{fmt(e.old_wd)}</td>
                                    <td className="text-right px-2 py-1">{fmt(e.new_wd)}</td>
                                    <td className={`text-right px-2 py-1 font-medium ${isUp ? "text-green-600" : "text-red-600"}`}>
                                      {isUp ? "+" : ""}{change.toFixed(1)}%
                                    </td>
                                    <td className="text-right px-2 py-1">{pct(e.success_before)}</td>
                                    <td className="text-right px-2 py-1">{pct(e.success_after)}</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </CardContent>
                    </Card>
                  )}
                </>
              )}

              {!btResult && !btLoading && (
                <div className="flex items-center justify-center h-32 text-muted-foreground">
                  {t("backtestPlaceholder")}
                </div>
              )}
            </TabsContent>
          </Tabs>
        )}

        {!mcResult && !loading && (
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            {t("placeholder")}
          </div>
        )}
      </main>
    </div>
  );
}
