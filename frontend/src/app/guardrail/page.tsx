"use client";

import { useState, useMemo, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
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
import { FanChart, useIsMobile, MobileChartTitle } from "@/components/fan-chart";
import { MetricCard } from "@/components/metric-card";
import { StatsTable } from "@/components/stats-table";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { runGuardrail, runGuardrailBatchBacktest, runBacktest, fetchCountries } from "@/lib/api";
import { downloadTrajectories } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { DEFAULT_PARAMS } from "@/lib/types";
import type {
  FormParams,
  GuardrailResponse,
  GuardrailBatchBacktestResponse,
  GuardrailBatchPathSummary,
  CountryInfo,
} from "@/lib/types";
import { fmt, pct } from "@/lib/utils";

export default function GuardrailPage() {
  const t = useTranslations("guardrail");
  const tc = useTranslations("common");
  const locale = useLocale();
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

  // Results
  const [mcResult, setMcResult] = useState<GuardrailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Batch backtest state
  const [batchResult, setBatchResult] = useState<GuardrailBatchBacktestResponse | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchSubTab, setBatchSubTab] = useState<"aggregate" | "paths">("aggregate");
  const [selectedPath, setSelectedPath] = useState<GuardrailBatchPathSummary | null>(null);
  const [btLogScale, setBtLogScale] = useState(false);
  const [btWdLogScale, setBtWdLogScale] = useState(false);
  const [sortCol, setSortCol] = useState<string>("start_year");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // Single backtest state
  const [histStartYear, setHistStartYear] = useState(1990);
  const [singleCountry, setSingleCountry] = useState("USA");
  const [singleBtLoading, setSingleBtLoading] = useState(false);
  const [countries, setCountries] = useState<CountryInfo[]>([]);

  useEffect(() => {
    fetchCountries().then(setCountries).catch(() => {});
  }, []);

  const guardrailReqBase = () => ({
    annual_withdrawal: withdrawal,
    allocation: params.allocation,
    expense_ratios: params.expense_ratios,
    retirement_years: params.retirement_years,
    min_block: params.min_block,
    max_block: params.max_block,
    num_simulations: params.num_simulations,
    data_start_year: params.data_start_year,
    country: params.country,
    pooling_method: params.pooling_method,
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
      setBatchResult(null);
      setSelectedPath(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
    }
  };

  const handleRunBatchBacktest = async () => {
    if (!mcResult) return;
    setBatchLoading(true);
    setError(null);
    setSelectedPath(null);
    setBatchSubTab("aggregate");
    try {
      const res = await runGuardrailBatchBacktest({
        ...guardrailReqBase(),
        initial_portfolio: mcResult.initial_portfolio,
      });
      setBatchResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setBatchLoading(false);
    }
  };

  const handleRunSingleBacktest = async () => {
    if (!mcResult) return;
    setSingleBtLoading(true);
    setError(null);
    try {
      const btCountry = params.country === "ALL" ? singleCountry : params.country;
      const res = await runBacktest({
        ...guardrailReqBase(),
        initial_portfolio: mcResult.initial_portfolio,
        hist_start_year: histStartYear,
        backtest_country: params.country === "ALL" ? btCountry : undefined,
      });
      // Convert BacktestResponse -> GuardrailBatchPathSummary for detail view
      const n = res.years_simulated;
      setSelectedPath({
        country: btCountry,
        start_year: histStartYear,
        years_simulated: n,
        is_complete: n >= params.retirement_years,
        g_survived: res.g_portfolio[res.g_portfolio.length - 1] > 0,
        b_survived: res.b_portfolio[res.b_portfolio.length - 1] > 0,
        g_final_portfolio: res.g_portfolio[res.g_portfolio.length - 1],
        b_final_portfolio: res.b_portfolio[res.b_portfolio.length - 1],
        g_total_consumption: res.g_total_consumption,
        b_total_consumption: res.b_total_consumption,
        num_adjustments: res.adjustment_events?.length ?? 0,
        year_labels: res.year_labels,
        g_portfolio: res.g_portfolio,
        g_withdrawals: res.g_withdrawals,
        g_success_rates: res.g_success_rates,
        b_portfolio: res.b_portfolio,
        b_withdrawals: res.b_withdrawals,
        adjustment_events: res.adjustment_events ?? [],
        path_metrics: res.path_metrics ?? [],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setSingleBtLoading(false);
    }
  };

  // Sorted paths for the table
  const sortedPaths = useMemo(() => {
    if (!batchResult) return [];
    const paths = [...batchResult.paths];
    paths.sort((a, b) => {
      let va: number | string, vb: number | string;
      switch (sortCol) {
        case "country": va = a.country; vb = b.country; break;
        case "start_year": va = a.start_year; vb = b.start_year; break;
        case "years_simulated": va = a.years_simulated; vb = b.years_simulated; break;
        case "g_final_portfolio": va = a.g_final_portfolio; vb = b.g_final_portfolio; break;
        case "g_survived": va = a.g_survived ? 1 : 0; vb = b.g_survived ? 1 : 0; break;
        default: va = a.start_year; vb = b.start_year;
      }
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      if (a.country !== b.country) return a.country < b.country ? -1 : 1;
      return a.start_year - b.start_year;
    });
    return paths;
  }, [batchResult, sortCol, sortDir]);

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  };

  const sortIndicator = (col: string) =>
    sortCol === col ? (sortDir === "asc" ? " ↑" : " ↓") : "";

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
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
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
                  label={t("guardrailFundedRatio")}
                  value={pct(mcResult.g_funded_ratio)}
                />
                <MetricCard
                  label={t("baselineSuccess")}
                  value={pct(mcResult.b_success_rate)}
                  sub={t("baselineRateSub", { rate: (baselineRate * 100).toFixed(1) })}
                />
                <MetricCard
                  label={t("baselineFundedRatio")}
                  value={pct(mcResult.b_funded_ratio)}
                />
              </div>

              {/* 资产轨迹对比 */}
              <Card>
                <CardContent className="pt-4">
                  <FanChart
                    trajectories={mcResult.g_percentile_trajectories}
                    title={t("portfolioComparison")}
                    showLogToggle
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
                    showLogToggle
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

              {/* 投资组合绩效指标 */}
              {mcResult.portfolio_metrics && mcResult.portfolio_metrics.length > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{t("portfolioMetrics")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <StatsTable rows={mcResult.portfolio_metrics} downloadName="portfolio_metrics" />
                  </CardContent>
                </Card>
              )}
            </TabsContent>

            {/* ═══ Backtest Tab ═══ */}
            <TabsContent value="backtest" className="space-y-6">
              {/* Single backtest input */}
              <Card>
                <CardContent className="pt-4 space-y-3">
                  <p className="text-[10px] text-muted-foreground">
                    {t("backtestPortfolioNote", { amount: fmt(mcResult.initial_portfolio) })}
                  </p>
                  <div className="flex items-end gap-3 flex-wrap">
                    {params.country === "ALL" && (
                      <div className="w-40">
                        <Label className="text-xs">{t("backtestCountry")}</Label>
                        <Select value={singleCountry} onValueChange={setSingleCountry}>
                          <SelectTrigger className="h-8 text-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {countries
                              .filter((c) => c.iso !== "ALL")
                              .map((c) => (
                                <SelectItem key={c.iso} value={c.iso}>
                                  {locale === "zh" ? c.name_zh : c.name_en}
                                </SelectItem>
                              ))}
                          </SelectContent>
                        </Select>
                      </div>
                    )}
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
                      onClick={handleRunSingleBacktest}
                      disabled={singleBtLoading}
                      size="sm"
                    >
                      {singleBtLoading ? t("backtesting") : t("runBacktest")}
                    </Button>
                  </div>
                  {params.country === "ALL" && (
                    <p className="text-[10px] text-muted-foreground italic">
                      {t("backtestCountryHint")}
                    </p>
                  )}
                </CardContent>
              </Card>

              {/* Batch backtest */}
              <Card>
                <CardContent className="pt-4 space-y-2">
                  <Button
                    onClick={handleRunBatchBacktest}
                    disabled={batchLoading}
                    size="sm"
                  >
                    {batchLoading ? t("batchBacktesting") : t("runBatchBacktest")}
                  </Button>
                </CardContent>
              </Card>

              {(batchLoading || singleBtLoading) && <LoadingOverlay message={singleBtLoading ? t("backtesting") : t("batchBacktesting")} />}

              {batchResult && !batchLoading && !selectedPath && (
                <>
                  {/* Summary metrics */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <MetricCard label={t("numPaths")} value={`${batchResult.num_paths}`} />
                    <MetricCard label={t("numComplete")} value={`${batchResult.num_complete}`} />
                    <MetricCard label={t("guardrailSuccess")} value={pct(batchResult.g_success_rate)} />
                    <MetricCard label={t("guardrailFundedRatio")} value={pct(batchResult.g_funded_ratio)} />
                    <MetricCard label={t("baselineSuccess")} value={pct(batchResult.b_success_rate)} />
                    <MetricCard label={t("baselineFundedRatio")} value={pct(batchResult.b_funded_ratio)} />
                  </div>
                  <p className="text-xs text-muted-foreground">{t("aggregateOnlyComplete")}</p>

                  {/* Sub-tabs */}
                  <Tabs value={batchSubTab} onValueChange={(v) => setBatchSubTab(v as "aggregate" | "paths")}>
                    <TabsList className="mb-4">
                      <TabsTrigger value="aggregate">{t("batchAggregateView")}</TabsTrigger>
                      <TabsTrigger value="paths">{t("batchPathsTable")}</TabsTrigger>
                    </TabsList>

                    {/* ── Aggregate view ── */}
                    <TabsContent value="aggregate" className="space-y-6">
                      {/* Guardrail portfolio fan chart */}
                      {Object.keys(batchResult.g_percentile_trajectories).length > 0 && (
                        <Card>
                          <CardContent className="pt-4">
                            <FanChart
                              trajectories={batchResult.g_percentile_trajectories}
                              title={t("portfolioComparison")}
                              showLogToggle
                            />
                          </CardContent>
                        </Card>
                      )}

                      {/* Guardrail withdrawal fan chart */}
                      {Object.keys(batchResult.g_withdrawal_percentiles).length > 0 && (
                        <Card>
                          <CardContent className="pt-4">
                            <FanChart
                              trajectories={batchResult.g_withdrawal_percentiles}
                              title={t("withdrawalTrajectory")}
                              color="16, 185, 129"
                              showLogToggle
                            />
                          </CardContent>
                        </Card>
                      )}

                      {/* Baseline portfolio fan chart */}
                      {Object.keys(batchResult.b_percentile_trajectories).length > 0 && (
                        <Card>
                          <CardContent className="pt-4">
                            <FanChart
                              trajectories={batchResult.b_percentile_trajectories}
                              title={`${tc("baseline")} - ${t("portfolioComparison")}`}
                              color="234, 88, 12"
                              showLogToggle
                            />
                          </CardContent>
                        </Card>
                      )}
                    </TabsContent>

                    {/* ── Individual paths table ── */}
                    <TabsContent value="paths" className="space-y-4">
                      <div className="rounded-md border overflow-auto max-h-[600px]">
                        <table className="w-full text-sm">
                          <thead className="bg-muted/50 sticky top-0">
                            <tr>
                              <th className="px-3 py-2 text-left cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("country")}>
                                {t("backtestCountry")}{sortIndicator("country")}
                              </th>
                              <th className="px-3 py-2 text-left cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("start_year")}>
                                {t("backtestStartYear")}{sortIndicator("start_year")}
                              </th>
                              <th className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("years_simulated")}>
                                {t("yearsSimulated")}{sortIndicator("years_simulated")}
                              </th>
                              <th className="px-3 py-2 text-center whitespace-nowrap">G</th>
                              <th className="px-3 py-2 text-center whitespace-nowrap">B</th>
                              <th className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("g_final_portfolio")}>
                                {t("guardrailFinalPortfolio")}{sortIndicator("g_final_portfolio")}
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {sortedPaths.map((p) => (
                              <tr
                                key={`${p.country}-${p.start_year}`}
                                className={`border-t cursor-pointer hover:bg-muted/30 transition-colors ${!p.is_complete ? "opacity-60" : ""}`}
                                onClick={() => setSelectedPath(p)}
                              >
                                <td className="px-3 py-1.5">{p.country}</td>
                                <td className="px-3 py-1.5">{p.start_year}</td>
                                <td className="px-3 py-1.5 text-right">
                                  {p.years_simulated}
                                  {!p.is_complete && <span className="ml-1 text-xs text-amber-600">*</span>}
                                </td>
                                <td className="px-3 py-1.5 text-center">
                                  {p.g_survived ? <span className="text-green-600">✓</span> : <span className="text-red-500">✗</span>}
                                </td>
                                <td className="px-3 py-1.5 text-center">
                                  {p.b_survived ? <span className="text-green-600">✓</span> : <span className="text-red-500">✗</span>}
                                </td>
                                <td className="px-3 py-1.5 text-right font-mono">{fmt(p.g_final_portfolio)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        * = {t("numIncomplete")} | G = Guardrail | B = {tc("baseline")}
                      </p>
                    </TabsContent>
                  </Tabs>
                </>
              )}

              {/* ── Path detail view ── */}
              {selectedPath && !batchLoading && !singleBtLoading && (
                <>
                  <Button variant="ghost" size="sm" onClick={() => setSelectedPath(null)}>
                    {t("backToList")}
                  </Button>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <MetricCard label={t("backtestCountry")} value={selectedPath.country} />
                    <MetricCard label={t("backtestStartYear")} value={`${selectedPath.start_year}`} />
                    <MetricCard label={t("yearsSimulated")} value={`${selectedPath.years_simulated}`} />
                    <MetricCard label={t("adjustmentCount")} value={`${selectedPath.num_adjustments}`} />
                    <MetricCard label={t("guardrailTotalConsumption")} value={fmt(selectedPath.g_total_consumption)} />
                    <MetricCard label={t("baselineTotalConsumption")} value={fmt(selectedPath.b_total_consumption)} />
                    <MetricCard label={t("guardrailFinalPortfolio")} value={fmt(selectedPath.g_final_portfolio)} />
                    <MetricCard label={t("baselineFinalPortfolio")} value={fmt(selectedPath.b_final_portfolio)} />
                  </div>

                  {/* Portfolio trajectory */}
                  <Card>
                    <CardContent className="pt-4">
                      <div className="flex items-center justify-between">
                        <MobileChartTitle title={t("historicalPortfolioComparison")} isMobile={isMobile} />
                        <Button variant="outline" size="sm" className="h-6 px-2 text-xs mb-1"
                          onClick={() => setBtLogScale(v => !v)}>
                          {btLogScale ? tc("linearScale") : tc("logScale")}
                        </Button>
                      </div>
                      <PlotlyChart
                        data={[
                          {
                            x: selectedPath.year_labels,
                            y: selectedPath.g_portfolio,
                            type: "scatter", mode: "lines",
                            name: "Guardrail",
                            line: { color: "rgb(59,130,246)", width: 2 },
                          },
                          {
                            x: selectedPath.year_labels,
                            y: selectedPath.b_portfolio,
                            type: "scatter", mode: "lines",
                            name: tc("baseline"),
                            line: { color: "rgb(234,88,12)", width: 2, dash: "dash" },
                          },
                        ]}
                        layout={{
                          title: isMobile ? undefined : { text: t("historicalPortfolioComparison"), font: { size: 14 } },
                          xaxis: { title: { text: t("yearAxis") }, tickfont: { size: isMobile ? 9 : 12 } },
                          yaxis: {
                            title: isMobile ? undefined : { text: t("assetAxis") },
                            type: btLogScale ? "log" : "linear",
                            tickformat: btLogScale ? "$~s" : (isMobile ? "$~s" : "$,.0f"),
                            tickfont: { size: isMobile ? 9 : 12 },
                          },
                          height: isMobile ? 280 : 400,
                          margin: isMobile ? { l: 45, r: 10, t: 10, b: 30 } : { l: 80, r: 30, t: 80, b: 50 },
                          legend: isMobile
                            ? { x: 0.5, y: 1.02, xanchor: "center" as const, yanchor: "bottom" as const, orientation: "h" as const, font: { size: 8 } }
                            : { x: 0, y: 1.0, yanchor: "bottom" as const, orientation: "h" as const },
                          hovermode: "x unified",
                        }}
                        config={{ responsive: true, displayModeBar: isMobile ? false : "hover",
                          modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
                          toImageButtonOptions: { format: "png", height: 800, width: 1200, scale: 2 },
                        }}
                        style={{ width: "100%" }}
                      />
                    </CardContent>
                  </Card>

                  {/* Withdrawal + success rate */}
                  <Card>
                    <CardContent className="pt-4">
                      <div className="flex items-center justify-between">
                        <MobileChartTitle title={t("withdrawalAmountAndSuccess")} isMobile={isMobile} />
                        <Button variant="outline" size="sm" className="h-6 px-2 text-xs mb-1"
                          onClick={() => setBtWdLogScale(v => !v)}>
                          {btWdLogScale ? tc("linearScale") : tc("logScale")}
                        </Button>
                      </div>
                      <PlotlyChart
                        data={[
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: selectedPath.g_withdrawals,
                            type: "scatter", mode: "lines",
                            name: t("guardrailWithdrawal"),
                            line: { color: "rgb(59,130,246)", width: 2 },
                            yaxis: "y",
                          },
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: selectedPath.b_withdrawals,
                            type: "scatter", mode: "lines",
                            name: t("baselineWithdrawal"),
                            line: { color: "rgb(234,88,12)", width: 2, dash: "dash" },
                            yaxis: "y",
                          },
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: selectedPath.g_success_rates.map((s) => s * 100),
                            type: "scatter", mode: "lines",
                            name: t("successRateLine"),
                            line: { color: "rgba(100,100,100,0.5)", width: 1 },
                            fill: "tozeroy", fillcolor: "rgba(100,100,100,0.08)",
                            yaxis: "y2",
                          },
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: Array(selectedPath.years_simulated).fill(upperGuardrail * 100),
                            type: "scatter", mode: "lines",
                            name: t("upperGuardrailLine", { pct: (upperGuardrail * 100).toFixed(0) }),
                            line: { color: "green", width: 1, dash: "dot" },
                            yaxis: "y2",
                          },
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: Array(selectedPath.years_simulated).fill(lowerGuardrail * 100),
                            type: "scatter", mode: "lines",
                            name: t("lowerGuardrailLine", { pct: (lowerGuardrail * 100).toFixed(0) }),
                            line: { color: "red", width: 1, dash: "dot" },
                            yaxis: "y2",
                          },
                        ]}
                        layout={{
                          title: isMobile ? undefined : { text: t("withdrawalAmountAndSuccess"), font: { size: 14 } },
                          xaxis: { title: { text: t("yearAxis") }, tickfont: { size: isMobile ? 9 : 12 } },
                          yaxis: {
                            title: isMobile ? undefined : { text: t("withdrawalAmount") },
                            type: btWdLogScale ? "log" : "linear",
                            tickformat: btWdLogScale ? "$~s" : (isMobile ? "$~s" : "$,.0f"),
                            tickfont: { size: isMobile ? 9 : 12 }, side: "left",
                          },
                          yaxis2: {
                            title: isMobile ? undefined : { text: t("successRateAxis") },
                            overlaying: "y", side: "right", range: [0, 105],
                            tickfont: { size: isMobile ? 9 : 12 },
                          },
                          height: isMobile ? 300 : 450,
                          margin: isMobile ? { l: 45, r: 35, t: 10, b: 30 } : { l: 80, r: 60, t: 100, b: 50 },
                          legend: isMobile
                            ? { x: 0.5, y: 1.02, xanchor: "center" as const, yanchor: "bottom" as const, orientation: "h" as const, font: { size: 7 }, tracegroupgap: 2 }
                            : { x: 0, y: 1.0, yanchor: "bottom" as const, orientation: "h" as const },
                          hovermode: "x unified",
                        }}
                        config={{ responsive: true, displayModeBar: isMobile ? false : "hover",
                          modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
                          toImageButtonOptions: { format: "png", height: 800, width: 1200, scale: 2 },
                        }}
                        style={{ width: "100%" }}
                      />
                    </CardContent>
                  </Card>

                  {/* Path metrics */}
                  {selectedPath.path_metrics && selectedPath.path_metrics.length > 0 && (
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">{t("pathMetrics")}</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <StatsTable rows={selectedPath.path_metrics} downloadName="backtest_path_metrics" />
                      </CardContent>
                    </Card>
                  )}

                  {/* Adjustment events */}
                  {selectedPath.adjustment_events && selectedPath.adjustment_events.length > 0 && (
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">
                          {t("adjustmentLogTitle", { count: selectedPath.adjustment_events.length })}
                        </CardTitle>
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
                              {selectedPath.adjustment_events.map((e, i) => {
                                const change = (e.new_wd / e.old_wd - 1) * 100;
                                const isUp = change > 0;
                                return (
                                  <tr key={i} className="border-b hover:bg-accent/50">
                                    <td className="px-2 py-1">{selectedPath.year_labels[e.year]}</td>
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

              {!batchResult && !batchLoading && !selectedPath && (
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
