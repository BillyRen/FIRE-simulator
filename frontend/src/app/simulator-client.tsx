"use client";

import { useState, useMemo, useEffect, memo } from "react";
import { usePersistedState } from "@/lib/use-persisted-state";
import { useTranslations, useLocale } from "next-intl";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { SidebarForm, NumberField } from "@/components/sidebar-form";
import { FanChart, useIsMobile, MobileChartTitle } from "@/components/fan-chart";
import { MetricCard } from "@/components/metric-card";
import { StatsTable } from "@/components/stats-table";
import { ProgressOverlay, type ProgressInfo } from "@/components/progress-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { CHART_COLORS, MARGINS } from "@/lib/chart-theme";
import { Pin, PinOff } from "lucide-react";
import { runSimulation, runSimBatchBacktest, runSimBacktest, runSimScenarios, runSimSensitivity, fetchCountries, fetchHistoricalEvents } from "@/lib/api";
import { filterEvents, buildEventOverlay, EVENT_MARKER_AXIS } from "@/lib/historical-events";
import { EventLegend } from "@/components/event-legend";
import type { HistoricalEvent } from "@/lib/types";
import { downloadTrajectories } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { PdfExportButton } from "@/components/pdf-export-button";
import { RichBrokeDeadChart } from "@/components/rich-broke-dead-chart";
import { CountrySuccessTable } from "@/components/country-success-table";
import { computeCountrySuccessStats } from "@/lib/country-success";
import { useSharedParams } from "@/lib/params-context";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { StatusBadge } from "@/components/ui/status-badge";
import type { SimulationResponse, SimBatchBacktestResponse, SimBatchPathSummary, CountryInfo, ScenarioAnalysisResponse, SensitivityAnalysisResponse } from "@/lib/types";
import { fmt, pct, countryFlag, deltaPct, deltaFmt, formatParamValue } from "@/lib/utils";
import { ErrorBanner } from "@/components/error-banner";

/**
 * Plain-language verdict banner keyed off the Monte Carlo success rate
 * (probability the portfolio is not depleted before the horizon ends).
 * Replaces the old dashboard's composite "readiness score", which summed
 * incommensurable quantities (probability + funded ratio + a 4%-threshold
 * penalty) with hand-picked weights and is not financially defensible.
 */
const PlanVerdict = memo(function PlanVerdict({ successRate }: { successRate: number }) {
  const t = useTranslations("simulator");
  const tier =
    successRate >= 0.9 ? "Great"
    : successRate >= 0.8 ? "Good"
    : successRate >= 0.65 ? "Caution"
    : "Danger";
  const cls =
    tier === "Great" || tier === "Good"
      ? "border-green-200 bg-green-50/60 text-green-900 dark:border-green-900/60 dark:bg-green-950/30 dark:text-green-200"
      : tier === "Caution"
        ? "border-amber-200 bg-amber-50/60 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
        : "border-red-200 bg-red-50/60 text-red-900 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200";
  return (
    <div className={`rounded-lg border px-4 py-3 ${cls}`}>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold tabular-nums">{pct(successRate)}</span>
        <span className="text-sm font-medium opacity-80">{t("successRate")}</span>
      </div>
      <p className="text-sm mt-1 leading-snug">{t(`verdict${tier}`)}</p>
    </div>
  );
});

export function SimulatorClient() {
  const t = useTranslations("simulator");
  const tc = useTranslations("common");
  const tf = useTranslations("fanChart");
  const locale = useLocale();

  const isMobile = useIsMobile();

  const { params, setParams, getSimCount, histStartYear, setHistStartYear, singleCountry, setSingleCountry } = useSharedParams();
  const [portfolio, setPortfolio] = usePersistedState("fire:main:portfolio", params.initial_portfolio);
  const [withdrawal, setWithdrawal] = usePersistedState("fire:main:withdrawal", params.annual_withdrawal);

  useEffect(() => {
    setParams(p => ({ ...p, initial_portfolio: portfolio, annual_withdrawal: withdrawal }));
  }, [portfolio, withdrawal, setParams]);


  // MC state
  const [result, setResult] = useState<SimulationResponse | null>(null);
  // Retirement age that produced `result`, snapshotted at run time so the
  // result charts (fan charts + mortality overlay) stay consistent with the
  // displayed data even if the form's retirement age is edited afterwards.
  const [resultAge, setResultAge] = useState<number>(params.retirement_age);
  const [pinnedResult, setPinnedResult] = useState<SimulationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Batch backtest state
  const [batchResult, setBatchResult] = useState<SimBatchBacktestResponse | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [btError, setBtError] = useState<string | null>(null);
  const [batchSubTab, setBatchSubTab] = useState<"aggregate" | "paths">("aggregate");
  const [selectedPath, setSelectedPath] = useState<SimBatchPathSummary | null>(null);
  const [btLogScale, setBtLogScale] = useState(false);
  const [btWdLogScale, setBtWdLogScale] = useState(false);
  // Path list sorting
  // Path list filters
  const [filterCountries, setFilterCountries] = useState<Set<string>>(new Set());
  const [filterMinStartYear, setFilterMinStartYear] = useState(0);
  const [filterMinYears, setFilterMinYears] = useState(0);

  // Single backtest state
  const [singleBtLoading, setSingleBtLoading] = useState(false);
  const [countries, setCountries] = useState<CountryInfo[]>([]);

  // Analysis state
  const [scenarioResult, setScenarioResult] = useState<ScenarioAnalysisResponse | null>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [scenarioProgress, setScenarioProgress] = useState<ProgressInfo | null>(null);
  const [scenarioMode, setScenarioMode] = usePersistedState<"auto" | "full" | "per_group">("fire:main:scenarioMode", "auto");
  const [sensitivityResult, setSensitivityResult] = useState<SensitivityAnalysisResponse | null>(null);
  const [sensitivityLoading, setSensitivityLoading] = useState(false);
  const [sensitivityProgress, setSensitivityProgress] = useState<ProgressInfo | null>(null);

  // Historical events
  const [historicalEvents, setHistoricalEvents] = useState<HistoricalEvent[]>([]);

  const hasProbabilisticCF = useMemo(() => {
    return params.cash_flows.some((cf: { group?: string | null }) => cf.group != null);
  }, [params.cash_flows]);

  useEffect(() => {
    fetchCountries(params.data_source).then(setCountries).catch(() => { /* non-critical init data */ });
  }, [params.data_source]);

  useEffect(() => {
    fetchHistoricalEvents().then(setHistoricalEvents).catch(() => { /* non-critical init data */ });
  }, []);

  const handleRun = async () => {
    setLoading(true);
    setProgress(null);
    setError(null);
    try {
      const res = await runSimulation({
        ...params,
        initial_portfolio: portfolio,
        annual_withdrawal: withdrawal,
        num_simulations: getSimCount("default"),
      }, setProgress);
      setResult(res);
      setResultAge(params.retirement_age);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
      setProgress(null);
    }
  };

  const handleRunBatchBacktest = async () => {
    setBatchLoading(true);
    setBtError(null);
    setSelectedPath(null);
    setBatchSubTab("aggregate");
    setFilterCountries(new Set());
    setFilterMinStartYear(0);
    setFilterMinYears(0);
    try {
      const res = await runSimBatchBacktest({
        ...params,
        // CAPE is a /simulate-MC-only strategy; the batch backtest doesn't
        // accept it, so fall back to fixed there.
        withdrawal_strategy: params.withdrawal_strategy === "cape" ? "fixed" : params.withdrawal_strategy,
        initial_portfolio: portfolio,
        annual_withdrawal: withdrawal,
      });
      setBatchResult(res);
    } catch (e) {
      setBtError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setBatchLoading(false);
    }
  };

  const handleRunSingleBacktest = async () => {
    setSingleBtLoading(true);
    setBtError(null);
    try {
      const btCountry = params.country === "ALL" ? singleCountry : params.country;
      const res = await runSimBacktest({
        initial_portfolio: portfolio,
        annual_withdrawal: withdrawal,
        allocation: params.allocation,
        expense_ratios: params.expense_ratios,
        retirement_years: params.retirement_years,
        data_start_year: params.data_start_year,
        country: btCountry,
        data_source: params.data_source,
        // CAPE is a Monte-Carlo-only strategy; the single-path backtest doesn't
        // support it, so fall back to fixed there.
        withdrawal_strategy: params.withdrawal_strategy === "cape" ? "fixed" : params.withdrawal_strategy,
        dynamic_ceiling: params.dynamic_ceiling,
        dynamic_floor: params.dynamic_floor,
        retirement_age: params.retirement_age,
        declining_rate: params.declining_rate,
        declining_start_age: params.declining_start_age,
        smile_decline_rate: params.smile_decline_rate,
        smile_decline_start_age: params.smile_decline_start_age,
        smile_min_age: params.smile_min_age,
        smile_increase_rate: params.smile_increase_rate,
        leverage: params.leverage,
        borrowing_spread: params.borrowing_spread,
        cash_flows: params.cash_flows,
        hist_start_year: histStartYear,
      });
      // Convert SimBacktestResponse -> SimBatchPathSummary for detail view
      setSelectedPath({
        country: btCountry,
        start_year: res.year_labels.length > 1 ? res.year_labels[1] : histStartYear,
        years_simulated: res.years_simulated,
        is_complete: res.years_simulated >= params.retirement_years,
        survived: res.survived,
        final_portfolio: res.final_portfolio,
        total_consumption: res.total_consumption,
        year_labels: res.year_labels,
        portfolio: res.portfolio,
        withdrawals: res.withdrawals,
        path_metrics: res.path_metrics,
      });
    } catch (e) {
      setBtError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setSingleBtLoading(false);
    }
  };

  const simReqBase = () => ({
    ...params,
    // CAPE is supported only on the main MC run; scenario/sensitivity endpoints
    // don't accept it, so coerce to fixed for those shared requests.
    withdrawal_strategy: params.withdrawal_strategy === "cape" ? "fixed" : params.withdrawal_strategy,
    initial_portfolio: portfolio,
    annual_withdrawal: withdrawal,
    num_simulations: getSimCount("default"),
  });

  const handleRunScenarios = async () => {
    setScenarioLoading(true);
    setScenarioProgress(null);
    setError(null);
    try {
      const res = await runSimScenarios({ ...simReqBase(), scenario_mode: scenarioMode }, setScenarioProgress);
      setScenarioResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setScenarioLoading(false);
      setScenarioProgress(null);
    }
  };

  const handleRunSensitivity = async () => {
    setSensitivityLoading(true);
    setSensitivityProgress(null);
    setError(null);
    try {
      const res = await runSimSensitivity(simReqBase(), setSensitivityProgress);
      setSensitivityResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setSensitivityLoading(false);
      setSensitivityProgress(null);
    }
  };

  // Unique countries from batch result (for filter chips)
  const availableCountries = useMemo(() => {
    if (!batchResult) return [];
    return Array.from(new Set(batchResult.paths.map((p) => p.country))).sort();
  }, [batchResult]);

  const countryLabel = useMemo(() => {
    const map: Record<string, string> = {};
    for (const c of countries) {
      const name = locale === "zh" ? c.name_zh : c.name_en;
      map[c.iso] = `${countryFlag(c.iso)} ${name}`;
    }
    return (iso: string) => map[iso] ?? iso;
  }, [countries, locale]);

  // Per-country censored-aware success stats (only meaningful for the pooled run)
  const countrySuccessRows = useMemo(() => {
    if (!batchResult || availableCountries.length <= 1) return [];
    return computeCountrySuccessStats(
      batchResult.paths.map((p) => ({
        country: p.country,
        is_complete: p.is_complete,
        has_failed: p.has_failed,
        minWithdrawal: p.withdrawals.length > 0 ? Math.min(...p.withdrawals) : 0,
      })),
    );
  }, [batchResult, availableCountries]);

  // Filtered paths for the table (DataTable owns sorting)
  const filteredPaths = useMemo(() => {
    if (!batchResult) return [];
    return batchResult.paths.filter((p) => {
      if (filterCountries.size > 0 && !filterCountries.has(p.country)) return false;
      if (filterMinStartYear > 0 && p.start_year < filterMinStartYear) return false;
      if (filterMinYears > 0 && p.years_simulated < filterMinYears) return false;
      return true;
    });
  }, [batchResult, filterCountries, filterMinStartYear, filterMinYears]);

  const minWithdrawal = (w: number[]): number => {
    if (w.length === 0) return 0;
    let m = w[0];
    for (let i = 1; i < w.length; i++) if (w[i] < m) m = w[i];
    return m;
  };

  const pathColumns: DataTableColumn<SimBatchPathSummary>[] = [
    { key: "country", header: t("country"), sortable: true, sortValue: (p) => p.country,
      csvValue: (p) => countryLabel(p.country), render: (p) => countryLabel(p.country) },
    { key: "start_year", header: t("startYear"), sortable: true, sortValue: (p) => p.start_year,
      csvValue: (p) => String(p.start_year) },
    { key: "years_simulated", header: t("yearsSimulatedShort"), align: "right", sortable: true,
      sortValue: (p) => p.years_simulated, csvValue: (p) => String(p.years_simulated),
      render: (p) => (
        <>
          {p.years_simulated}
          {!p.is_complete && <span className="ml-1 text-xs text-amber-600 dark:text-amber-500">*</span>}
        </>
      ) },
    { key: "status", header: t("survived"),
      csvValue: (p) => (p.has_failed ? tc("statusFailed") : p.is_complete ? tc("statusSuccess") : tc("statusCensored")),
      render: (p) =>
        p.has_failed ? (
          <StatusBadge variant="bad" label={tc("statusFailed")} />
        ) : p.is_complete ? (
          <StatusBadge variant="ok" label={tc("statusSuccess")} />
        ) : (
          <StatusBadge variant="censored" label={tc("statusCensored")} />
        ) },
    { key: "min_withdrawal", header: t("minWithdrawal"), align: "right", sortable: true,
      sortValue: (p) => minWithdrawal(p.withdrawals), csvValue: (p) => String(Math.round(minWithdrawal(p.withdrawals))),
      render: (p) => fmt(minWithdrawal(p.withdrawals)) },
    { key: "final_portfolio", header: t("finalPortfolio"), align: "right", sortable: true,
      sortValue: (p) => p.final_portfolio, csvValue: (p) => String(Math.round(p.final_portfolio)),
      render: (p) => fmt(p.final_portfolio) },
  ];

  return (
    <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 p-3 sm:p-6 max-w-[1600px] mx-auto">
      {/* ── 左侧参数面板 ── */}
      <aside className="lg:w-[340px] shrink-0 space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t("title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              <NumberField
                label={tc("initialPortfolio")}
                value={portfolio}
                onChange={setPortfolio}
                min={0}
              />
              <NumberField
                label={tc("annualWithdrawal")}
                value={withdrawal}
                onChange={setWithdrawal}
                min={0}
              />
            </div>
            <p className="text-xs text-muted-foreground leading-snug">{tc("currencyNote")}</p>

            <SidebarForm params={params} onChange={setParams} countries={countries} />

          </CardContent>
          <div className="sticky bottom-0 bg-card px-6 pt-3 pb-4 border-t space-y-1.5">
            <Button onClick={handleRun} className="w-full" disabled={loading}>
              {loading ? tc("running") : t("runSimulation")}
            </Button>
            {result && (
              <div className="flex gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 h-7 text-xs"
                  onClick={() => setPinnedResult(pinnedResult ? null : result)}
                >
                  {pinnedResult ? (
                    <><PinOff className="h-3 w-3 mr-1" />{tc("unpinBaseline")}</>
                  ) : (
                    <><Pin className="h-3 w-3 mr-1" />{tc("pinBaseline")}</>
                  )}
                </Button>
              </div>
            )}
          </div>
        </Card>
      </aside>

      {/* ── 右侧结果区 ── */}
      <main className="flex-1 space-y-6 min-w-0">
        {error && <ErrorBanner message={error} />}
        {btError && <ErrorBanner message={btError} />}

        <Tabs defaultValue="mc">
          <TabsList className="mb-4">
            <TabsTrigger value="mc">{t("tabMonteCarlo")}</TabsTrigger>
            <TabsTrigger value="backtest">{t("tabBacktest")}</TabsTrigger>
            <TabsTrigger value="analysis">{t("tabAnalysis")}</TabsTrigger>
          </TabsList>

          {/* ── MC Tab ── */}
          <TabsContent value="mc" className="space-y-6">
            {loading && <ProgressOverlay progress={progress} />}

            {result && !loading && (
              <div id="sim-results" className="space-y-4">
                {/* 计划结论横幅(基于成功率) */}
                <PlanVerdict successRate={result.success_rate} />

                {/* 下载按钮组 */}
                <div className="flex flex-wrap gap-2">
                  <PdfExportButton targetId="sim-results" filename="fire-simulation-report.pdf" />
                  <DownloadButton
                    label={t("downloadPortfolioTrajectory")}
                    onClick={() =>
                      downloadTrajectories("portfolio_trajectory", result.percentile_trajectories)
                    }
                  />
                  {result.withdrawal_percentile_trajectories && (
                    <DownloadButton
                      label={t("downloadWithdrawalTrajectory")}
                      onClick={() =>
                        downloadTrajectories(
                          "withdrawal_trajectory",
                          result.withdrawal_percentile_trajectories!
                        )
                      }
                    />
                  )}
                </div>

                {/* 指标卡片 */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                  <MetricCard label={t("successRate")} value={pct(result.success_rate)}
                    tooltip={t("successRateHelp")}
                    delta={pinnedResult ? deltaPct(result.success_rate, pinnedResult.success_rate) : undefined} />
                  <MetricCard label={t("fundedRatio")} value={pct(result.funded_ratio)}
                    tooltip={t("fundedRatioHelp")}
                    delta={pinnedResult ? deltaPct(result.funded_ratio, pinnedResult.funded_ratio) : undefined} />
                  <MetricCard label={t("medianFinalPortfolio")} value={fmt(result.final_median)}
                    delta={pinnedResult ? deltaFmt(result.final_median, pinnedResult.final_median) : undefined} />
                  <MetricCard label={t("meanFinalPortfolio")} value={fmt(result.final_mean)}
                    delta={pinnedResult ? deltaFmt(result.final_mean, pinnedResult.final_mean) : undefined} />
                  <MetricCard label={t("initialWithdrawalRate")} value={pct(result.initial_withdrawal_rate)}
                    delta={pinnedResult ? deltaPct(result.initial_withdrawal_rate, pinnedResult.initial_withdrawal_rate) : undefined} />
                </div>

                {/* 资产轨迹扇形图 */}
                <Card>
                  <CardContent className="pt-4">
                    <FanChart
                      trajectories={result.percentile_trajectories}
                      title={t("portfolioTrajectory")}
                      xLabels={Array.from({ length: result.percentile_trajectories["50"]?.length ?? 0 }, (_, i) => resultAge + i)}
                      xTitle={tf("ageAxis")}
                      showLogToggle
                      extraTraces={pinnedResult ? [{
                        x: Array.from({ length: pinnedResult.percentile_trajectories["50"]?.length ?? 0 }, (_, i) => resultAge + i),
                        y: pinnedResult.percentile_trajectories["50"],
                        mode: "lines" as const,
                        name: tc("baselineP50"),
                        line: { color: CHART_COLORS.neutral.hex, width: 2, dash: "dash" as const },
                        type: "scatter" as const,
                        hovertemplate: tc.raw("baselineHover"),
                      }] : []}
                    />
                  </CardContent>
                </Card>

                {/* 提取金额扇形图 */}
                {result.withdrawal_percentile_trajectories && (
                  <Card>
                    <CardContent className="pt-4">
                      <FanChart
                        trajectories={result.withdrawal_percentile_trajectories}
                        title={t("withdrawalTrajectory")}
                        xLabels={Array.from({ length: result.withdrawal_percentile_trajectories["50"]?.length ?? 0 }, (_, i) => resultAge + 1 + i)}
                        xTitle={tf("ageAxis")}
                        color={CHART_COLORS.orange.rgb}
                        showLogToggle
                      />
                    </CardContent>
                  </Card>
                )}

                {/* Rich / Broke / Dead 死亡率叠加图 */}
                {result.solvency_by_year && (
                  <Card>
                    <CardContent className="pt-4">
                      <RichBrokeDeadChart
                        solvencyByYear={result.solvency_by_year}
                        retirementAge={resultAge}
                      />
                    </CardContent>
                  </Card>
                )}

                {/* 统计表 */}
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{t("statsSummary")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <StatsTable rows={result.final_values_summary} downloadName="stats_summary" />
                  </CardContent>
                </Card>

                {/* 投资组合绩效指标 */}
                {result.portfolio_metrics && result.portfolio_metrics.length > 0 && (
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm">{t("portfolioMetrics")}</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <StatsTable rows={result.portfolio_metrics} downloadName="portfolio_metrics" />
                    </CardContent>
                  </Card>
                )}
              </div>
            )}

            {!result && !loading && (
              <div className="flex items-center justify-center h-64 text-muted-foreground">
                {t("placeholder")}
              </div>
            )}
          </TabsContent>

          {/* ── Backtest Tab ── */}
          <TabsContent value="backtest" className="space-y-6">
            {/* Single backtest input */}
            <Card>
              <CardContent className="pt-4 space-y-3">
                <div className="flex items-end gap-3 flex-wrap">
                  {params.country === "ALL" && (
                    <div className="w-40">
                      <Label className="text-xs">{t("country")}</Label>
                      <Select value={singleCountry} onValueChange={setSingleCountry}>
                        <SelectTrigger className="h-8 text-sm">
                          <SelectValue placeholder={t("country")} />
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
              </CardContent>
            </Card>

            {/* Batch backtest */}
            <Card>
              <CardContent className="pt-4 space-y-2">
                <p className="text-sm text-muted-foreground">{t("batchBacktestDesc")}</p>
                <Button
                  onClick={handleRunBatchBacktest}
                  disabled={batchLoading}
                  size="sm"
                >
                  {batchLoading ? t("batchBacktesting") : t("runBatchBacktest")}
                </Button>
              </CardContent>
            </Card>

            {(batchLoading || singleBtLoading) && <ProgressOverlay message={singleBtLoading ? t("backtesting") : t("batchBacktesting")} />}

            {batchResult && !batchLoading && !selectedPath && (
              <>
                {/* Summary metrics */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <MetricCard label={t("numPaths")} value={`${batchResult.num_paths}`} />
                  <MetricCard label={t("numComplete")} value={`${batchResult.num_complete}`} />
                  <MetricCard label={t("successRate")} value={pct(batchResult.success_rate)} tooltip={t("successRateHelp")} />
                  <MetricCard label={t("fundedRatio")} value={pct(batchResult.funded_ratio)} tooltip={t("fundedRatioHelp")} />
                </div>
                {(batchResult.num_incomplete_failed ?? 0) > 0 || (batchResult.num_excluded ?? 0) > 0 ? (
                  <p className="text-xs text-muted-foreground">
                    {tc("successRateDenominator", {
                      complete: batchResult.num_complete,
                      failed: batchResult.num_incomplete_failed ?? 0,
                      excluded: batchResult.num_excluded ?? 0,
                    })}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">{t("aggregateOnlyComplete")}</p>
                )}

                {/* Sub-tabs */}
                <Tabs value={batchSubTab} onValueChange={(v) => setBatchSubTab(v as "aggregate" | "paths")}>
                  <TabsList className="mb-4">
                    <TabsTrigger value="aggregate">{t("batchAggregateView")}</TabsTrigger>
                    <TabsTrigger value="paths">{t("batchPathsTable")}</TabsTrigger>
                  </TabsList>

                  {/* ── Aggregate view ── */}
                  <TabsContent value="aggregate" className="space-y-6">
                    {/* Portfolio fan chart */}
                    {Object.keys(batchResult.percentile_trajectories).length > 0 && (
                      <Card>
                        <CardContent className="pt-4">
                          <FanChart
                            trajectories={batchResult.percentile_trajectories}
                            title={t("portfolioTrajectory")}
                            xLabels={Array.from({ length: batchResult.percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i)}
                            xTitle={tf("ageAxis")}
                            showLogToggle
                          />
                        </CardContent>
                      </Card>
                    )}

                    {/* Withdrawal fan chart */}
                    {batchResult.withdrawal_percentile_trajectories &&
                      Object.keys(batchResult.withdrawal_percentile_trajectories).length > 0 && (
                      <Card>
                        <CardContent className="pt-4">
                          <FanChart
                            trajectories={batchResult.withdrawal_percentile_trajectories}
                            title={t("withdrawalTrajectory")}
                            xLabels={Array.from({ length: batchResult.withdrawal_percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + 1 + i)}
                            xTitle={tf("ageAxis")}
                            color={CHART_COLORS.orange.rgb}
                            showLogToggle
                          />
                        </CardContent>
                      </Card>
                    )}

                    {/* Per-country success rate */}
                    {countrySuccessRows.length > 1 && (
                      <CountrySuccessTable rows={countrySuccessRows} countryLabel={countryLabel} />
                    )}

                    {/* Stats summary */}
                    {batchResult.final_values_summary.length > 0 && (
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">{t("statsSummary")}</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <StatsTable rows={batchResult.final_values_summary} downloadName="batch_stats_summary" />
                        </CardContent>
                      </Card>
                    )}

                    {/* Portfolio metrics */}
                    {batchResult.portfolio_metrics && batchResult.portfolio_metrics.length > 0 && (
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">{t("portfolioMetrics")}</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <StatsTable rows={batchResult.portfolio_metrics} downloadName="batch_portfolio_metrics" />
                        </CardContent>
                      </Card>
                    )}
                  </TabsContent>

                  {/* ── Individual paths table ── */}
                  <TabsContent value="paths" className="space-y-4">
                    {/* Filters */}
                    <div className="flex flex-wrap items-end gap-3 text-sm">
                      {/* Country chips */}
                      <div className="space-y-1">
                        <Label className="text-xs">{t("filterCountry")}</Label>
                        <div className="flex flex-wrap gap-1">
                          <button
                            className={`px-2 py-0.5 text-xs rounded border transition-colors ${filterCountries.size === 0 ? "bg-primary text-primary-foreground border-primary" : "bg-background border-border hover:bg-muted"}`}
                            onClick={() => setFilterCountries(new Set())}
                          >
                            {t("allCountries")}
                          </button>
                          {availableCountries.map((c) => (
                            <button
                              key={c}
                              className={`px-2 py-0.5 text-xs rounded border transition-colors ${filterCountries.has(c) ? "bg-primary text-primary-foreground border-primary" : "bg-background border-border hover:bg-muted"}`}
                              onClick={() => {
                                setFilterCountries((prev) => {
                                  const next = new Set(prev);
                                  if (next.has(c)) next.delete(c);
                                  else next.add(c);
                                  return next;
                                });
                              }}
                            >
                              {countryLabel(c)}
                            </button>
                          ))}
                        </div>
                      </div>
                      {/* Start year min */}
                      <div className="w-28">
                        <NumberField
                          label={t("filterMinStartYear")}
                          value={filterMinStartYear}
                          onChange={(v) => setFilterMinStartYear(Math.round(v))}
                          min={0}
                        />
                      </div>
                      {/* Years simulated min */}
                      <div className="w-28">
                        <NumberField
                          label={t("filterMinYears")}
                          value={filterMinYears}
                          onChange={(v) => setFilterMinYears(Math.round(v))}
                          min={0}
                        />
                      </div>
                      {/* Clear */}
                      {(filterCountries.size > 0 || filterMinStartYear > 0 || filterMinYears > 0) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => {
                            setFilterCountries(new Set());
                            setFilterMinStartYear(0);
                            setFilterMinYears(0);
                          }}
                        >
                          {t("clearFilters")}
                        </Button>
                      )}
                    </div>

                    <DataTable
                      columns={pathColumns}
                      rows={filteredPaths}
                      getRowKey={(p) => `${p.country}-${p.start_year}`}
                      onRowClick={(p) => setSelectedPath(p)}
                      rowClassName={(p) => (!p.is_complete ? "opacity-60" : "")}
                      defaultSort={{ key: "start_year", dir: 1 }}
                      downloadName="backtest_paths"
                      maxHeight={600}
                    />
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-muted-foreground">
                        * = {t("incomplete")} (&lt; {params.retirement_years} {t("yearsSimulatedShort")})
                      </p>
                      {batchResult && (
                        <p className="text-xs text-muted-foreground">
                          {t("filteredCount", { count: filteredPaths.length, total: batchResult.paths.length })}
                        </p>
                      )}
                    </div>
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
                  <MetricCard label={t("country")} value={countryLabel(selectedPath.country)} />
                  <MetricCard label={t("startYear")} value={`${selectedPath.start_year}`} />
                  <MetricCard label={t("yearsSimulated")} value={`${selectedPath.years_simulated}`} />
                  <MetricCard
                    label={t("survived")}
                    value={selectedPath.survived ? t("survived") : t("depleted")}
                  />
                  <MetricCard label={t("finalPortfolio")} value={fmt(selectedPath.final_portfolio)} />
                  <MetricCard label={t("totalConsumption")} value={fmt(selectedPath.total_consumption)} />
                </div>

                {/* Portfolio trajectory */}
                <Card>
                  <CardContent className="pt-4">
                    <div className="flex items-center justify-between">
                      <MobileChartTitle title={t("portfolioHistory")} isMobile={isMobile} />
                      <Button
                        variant="outline" size="sm"
                        className="h-6 px-2 text-xs mb-1"
                        onClick={() => setBtLogScale(v => !v)}
                      >
                        {btLogScale ? tc("linearScale") : tc("logScale")}
                      </Button>
                    </div>
                    {(() => {
                      const pathCountry = selectedPath.country;
                      const startY = selectedPath.year_labels[0];
                      const endY = selectedPath.year_labels[selectedPath.year_labels.length - 1];
                      const filtered = filterEvents(historicalEvents, pathCountry, startY, endY);
                      const overlay = buildEventOverlay(filtered, locale, startY, endY);
                      return (
                        <>
                          <PlotlyChart
                            data={[{
                              x: selectedPath.year_labels,
                              y: selectedPath.portfolio,
                              type: "scatter", mode: "lines",
                              name: t("portfolioHistory"),
                              line: { color: CHART_COLORS.primary.hex, width: 2 },
                              hovertemplate: "%{x}: %{y:,.0f}<extra></extra>",
                            }, ...overlay.traces]}
                            layout={{
                              title: isMobile ? undefined : { text: t("portfolioHistory"), font: { size: 14 } },
                              xaxis: { title: { text: tc("year") } },
                              yaxis: {
                                title: { text: tc("amount") },
                                type: btLogScale ? "log" : "linear",
                                tickformat: btLogScale ? "~s" : ",.0f",
                              },
                              yaxis2: EVENT_MARKER_AXIS,
                              margin: MARGINS.withTitle(isMobile),
                              height: isMobile ? 260 : 380,
                              showlegend: false,
                              shapes: overlay.shapes as Plotly.Layout["shapes"],
                            }}
                            config={{ displayModeBar: false }}
                          />
                          <EventLegend items={overlay.legendItems} />
                        </>
                      );
                    })()}
                  </CardContent>
                </Card>

                {/* Withdrawal trajectory */}
                <Card>
                  <CardContent className="pt-4">
                    <div className="flex items-center justify-between">
                      <MobileChartTitle title={t("withdrawalHistory")} isMobile={isMobile} />
                      <Button
                        variant="outline" size="sm"
                        className="h-6 px-2 text-xs mb-1"
                        onClick={() => setBtWdLogScale(v => !v)}
                      >
                        {btWdLogScale ? tc("linearScale") : tc("logScale")}
                      </Button>
                    </div>
                    <PlotlyChart
                      data={[{
                        x: selectedPath.year_labels.slice(1),
                        y: selectedPath.withdrawals,
                        type: "bar",
                        name: t("withdrawalHistory"),
                        marker: { color: CHART_COLORS.orange.hex },
                        hovertemplate: "%{x}: %{y:,.0f}<extra></extra>",
                      }]}
                      layout={{
                        title: isMobile ? undefined : { text: t("withdrawalHistory"), font: { size: 14 } },
                        xaxis: { title: { text: tc("year") } },
                        yaxis: {
                          title: { text: tc("amount") },
                          type: btWdLogScale ? "log" : "linear",
                          tickformat: btWdLogScale ? "~s" : ",.0f",
                        },
                        margin: MARGINS.withTitle(isMobile),
                        height: isMobile ? 260 : 380,
                        showlegend: false,
                      }}
                      config={{ displayModeBar: false }}
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
              </>
            )}

            {!batchResult && !batchLoading && !selectedPath && (
              <div className="flex items-center justify-center h-64 text-muted-foreground">
                {t("backtestPlaceholder")}
              </div>
            )}
          </TabsContent>

          {/* ── Analysis Tab ── */}
          <TabsContent value="analysis" className="space-y-6">
            {!result ? (
              <div className="flex items-center justify-center h-64 text-muted-foreground">
                {t("analysisRequiresSim")}
              </div>
            ) : (
              <>
                {/* Scenario Analysis */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">{t("scenarioTitle")}</CardTitle>
                    <p className="text-sm text-muted-foreground">{t("scenarioDesc")}</p>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {hasProbabilisticCF ? (
                      <div className="flex flex-wrap items-end gap-3">
                        <div className="space-y-1">
                          <Label className="text-xs text-muted-foreground">{t("scenarioModeLabel")}</Label>
                          <Select
                            value={scenarioMode}
                            onValueChange={(v) => setScenarioMode(v as "auto" | "full" | "per_group")}
                          >
                            <SelectTrigger className="h-8 w-44 text-sm">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="auto">{t("scenarioModeAuto")}</SelectItem>
                              <SelectItem value="full">{t("scenarioModeFull")}</SelectItem>
                              <SelectItem value="per_group">{t("scenarioModePerGroup")}</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <Button
                          onClick={handleRunScenarios}
                          disabled={scenarioLoading}
                          size="sm"
                        >
                          {scenarioLoading ? t("scenarioRunning") : t("runScenarioAnalysis")}
                        </Button>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">{t("scenarioNoProbCF")}</p>
                    )}

                    {hasProbabilisticCF && (
                      <p className="text-xs text-muted-foreground">{t(`scenarioModeHint_${scenarioMode}`)}</p>
                    )}

                    {scenarioLoading && <ProgressOverlay message={t("scenarioLoading")} progress={scenarioProgress} />}

                    {scenarioResult && (
                      <>
                        {scenarioResult.mode === "per_group" && (
                          <p className="text-xs text-muted-foreground bg-muted/50 rounded-md px-3 py-2">
                            {scenarioMode === "per_group" ? t("scenarioPerGroupManual") : t("scenarioPerGroupHint")}
                          </p>
                        )}

                        {/* Scenario bar chart */}
                        <PlotlyChart
                          data={(() => {
                            const sorted = [...scenarioResult.scenarios].sort(
                              (a, b) => a.success_rate - b.success_rate
                            );
                            const labels = sorted.map((s) => s.label);
                            const values = sorted.map((s) => s.success_rate * 100);
                            const colors = sorted.map((s) =>
                              s.success_rate >= scenarioResult.base_case.success_rate
                                ? CHART_COLORS.secondary.hex
                                : CHART_COLORS.danger.hex
                            );
                            return [
                              {
                                type: "bar" as const,
                                orientation: "h" as const,
                                y: labels,
                                x: values,
                                marker: { color: colors },
                                text: values.map((v) => `${v.toFixed(1)}%`),
                                textposition: "outside" as const,
                                hovertemplate: "%{y}<br>" + t("scenarioSuccessRate") + ": %{x:.1f}%<extra></extra>",
                              },
                            ];
                          })()}
                          layout={{
                            title: isMobile ? undefined : { text: t("scenarioComparisonTitle"), font: { size: 14 } },
                            xaxis: {
                              title: { text: t("scenarioSuccessRate") },
                              type: "linear" as const,
                              ticksuffix: "%",
                              range: (() => {
                                const all = scenarioResult.scenarios.map((s) => s.success_rate * 100);
                                all.push(scenarioResult.base_case.success_rate * 100);
                                const min = Math.min(...all);
                                const max = Math.max(...all);
                                const pad = Math.max((max - min) * 0.3, 2);
                                return [Math.max(0, min - pad), Math.min(100, max + pad + 2)];
                              })(),
                            },
                            margin: isMobile
                              ? { l: 160, r: 50, t: 10, b: 40 }
                              : { l: 260, r: 60, t: 40, b: 50 },
                            height: Math.max(isMobile ? 250 : 300, scenarioResult.scenarios.length * (isMobile ? 26 : 30) + 80),
                            shapes: [
                              {
                                type: "line",
                                x0: scenarioResult.base_case.success_rate * 100,
                                x1: scenarioResult.base_case.success_rate * 100,
                                y0: -0.5,
                                y1: scenarioResult.scenarios.length - 0.5,
                                line: { color: CHART_COLORS.primary.hex, width: 2, dash: "dash" },
                              },
                            ],
                            annotations: [
                              {
                                x: scenarioResult.base_case.success_rate * 100,
                                y: scenarioResult.scenarios.length - 0.5,
                                text: `${t("scenarioBaseCase")}: ${(scenarioResult.base_case.success_rate * 100).toFixed(1)}%`,
                                showarrow: false,
                                yanchor: "bottom" as const,
                                font: { size: 11, color: CHART_COLORS.primary.hex },
                              },
                            ],
                          }}
                        />

                        {/* Scenario table */}
                        <Card>
                          <CardContent className="pt-4">
                            {(() => {
                              type ScenRow = { isBase: boolean; label: string; probability: number | null; success_rate: number; funded_ratio: number; median_final: number; median_consumption: number };
                              const bc = scenarioResult.base_case;
                              const scenRows: ScenRow[] = [
                                { isBase: true, label: t("scenarioBaseCase"), probability: null, success_rate: bc.success_rate, funded_ratio: bc.funded_ratio, median_final: bc.median_final_portfolio, median_consumption: bc.median_total_consumption },
                                ...scenarioResult.scenarios.map((s) => ({ isBase: false, label: s.label, probability: s.probability, success_rate: s.success_rate, funded_ratio: s.funded_ratio, median_final: s.median_final_portfolio, median_consumption: s.median_total_consumption })),
                              ];
                              const scenCols: DataTableColumn<ScenRow>[] = [
                                { key: "label", header: t("scenarioLabel"), csvValue: (r) => r.label,
                                  render: (r) => <span className="block max-w-[220px] truncate" title={r.label}>{r.label}</span> },
                                { key: "probability", header: t("scenarioProbability"), align: "right",
                                  csvValue: (r) => (r.probability === null ? "—" : pct(r.probability)),
                                  render: (r) => (r.probability === null ? "—" : pct(r.probability)) },
                                { key: "success_rate", header: t("scenarioSuccessRate"), align: "right", csvValue: (r) => pct(r.success_rate), render: (r) => pct(r.success_rate) },
                                { key: "funded_ratio", header: t("scenarioFundedRatio"), align: "right", csvValue: (r) => pct(r.funded_ratio), render: (r) => pct(r.funded_ratio) },
                                { key: "median_final", header: t("scenarioMedianFinal"), align: "right", csvValue: (r) => String(Math.round(r.median_final)), render: (r) => fmt(r.median_final) },
                                { key: "median_consumption", header: t("scenarioMedianConsumption"), align: "right", csvValue: (r) => String(Math.round(r.median_consumption)), render: (r) => fmt(r.median_consumption) },
                              ];
                              return (
                                <DataTable
                                  columns={scenCols}
                                  rows={scenRows}
                                  getRowKey={(_r, i) => i}
                                  rowClassName={(r) => (r.isBase ? "bg-muted/50 font-medium" : "")}
                                  downloadName="scenarios"
                                />
                              );
                            })()}
                          </CardContent>
                        </Card>
                      </>
                    )}
                  </CardContent>
                </Card>

                {/* Parameter Sensitivity */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">{t("sensitivityTitle")}</CardTitle>
                    <p className="text-sm text-muted-foreground">{t("sensitivityDesc")}</p>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <Button
                      onClick={handleRunSensitivity}
                      disabled={sensitivityLoading}
                      size="sm"
                    >
                      {sensitivityLoading ? t("sensitivityRunning") : t("runSensitivity")}
                    </Button>

                    {sensitivityLoading && <ProgressOverlay progress={sensitivityProgress} />}

                    {sensitivityResult && (
                      <>
                        {/* Tornado chart */}
                        <PlotlyChart
                          data={(() => {
                            const baseSR = sensitivityResult.base_success_rate * 100;
                            const sorted = [...sensitivityResult.deltas].sort(
                              (a, b) =>
                                Math.abs(a.high_success_rate - a.low_success_rate) -
                                Math.abs(b.high_success_rate - b.low_success_rate)
                            );
                            return [
                              {
                                type: "bar" as const,
                                orientation: "h" as const,
                                y: sorted.map((d) => d.param_label),
                                x: sorted.map((d) => (d.low_success_rate - sensitivityResult.base_success_rate) * 100),
                                base: Array(sorted.length).fill(baseSR),
                                marker: { color: CHART_COLORS.danger.hex },
                                name: t("sensitivityLow"),
                                hovertemplate: "%{y}: %{x:+.1f}pp<extra></extra>",
                              },
                              {
                                type: "bar" as const,
                                orientation: "h" as const,
                                y: sorted.map((d) => d.param_label),
                                x: sorted.map((d) => (d.high_success_rate - sensitivityResult.base_success_rate) * 100),
                                base: Array(sorted.length).fill(baseSR),
                                marker: { color: CHART_COLORS.secondary.hex },
                                name: t("sensitivityHigh"),
                                hovertemplate: "%{y}: %{x:+.1f}pp<extra></extra>",
                              },
                            ];
                          })()}
                          layout={{
                            title: isMobile ? undefined : { text: t("sensitivityChartTitle"), font: { size: 14 } },
                            barmode: "overlay",
                            xaxis: { title: { text: t("sensitivityImpact") }, type: "linear" as const, ticksuffix: "%" },
                            margin: isMobile ? { l: 100, r: 30, t: 10, b: 40 } : { l: 140, r: 40, t: 40, b: 50 },
                            height: isMobile ? 250 : 300,
                            shapes: [
                              {
                                type: "line",
                                x0: sensitivityResult.base_success_rate * 100,
                                x1: sensitivityResult.base_success_rate * 100,
                                y0: -0.5,
                                y1: sensitivityResult.deltas.length - 0.5,
                                line: { color: CHART_COLORS.neutral.hex, width: 1, dash: "dash" },
                              },
                            ],
                          }}
                        />

                        {/* Parameter table */}
                        <Card>
                          <CardContent className="pt-4">
                            {(() => {
                              type SensRow = (typeof sensitivityResult.deltas)[number];
                              const base = sensitivityResult.base_success_rate;
                              const ppClass = (v: number) =>
                                v < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400";
                              const loPp = (d: SensRow) => (d.low_success_rate - base) * 100;
                              const hiPp = (d: SensRow) => (d.high_success_rate - base) * 100;
                              const sensCols: DataTableColumn<SensRow>[] = [
                                { key: "param_label", header: t("sensitivityParam"), csvValue: (d) => d.param_label, render: (d) => d.param_label },
                                { key: "base_value", header: t("sensitivityBaseValue"), align: "right",
                                  csvValue: (d) => formatParamValue(d.base_value, d.param_key),
                                  render: (d) => formatParamValue(d.base_value, d.param_key) },
                                { key: "range", header: t("sensitivityRange"), align: "right",
                                  csvValue: (d) => `${formatParamValue(d.low_value, d.param_key)} ~ ${formatParamValue(d.high_value, d.param_key)}`,
                                  render: (d) => `${formatParamValue(d.low_value, d.param_key)} ~ ${formatParamValue(d.high_value, d.param_key)}` },
                                { key: "impact", header: t("sensitivityImpact"), align: "right",
                                  csvValue: (d) => `${loPp(d).toFixed(1)}pp / ${hiPp(d).toFixed(1)}pp`,
                                  render: (d) => (
                                    <>
                                      <span className={ppClass(loPp(d))}>{loPp(d).toFixed(1)}pp</span>
                                      {" / "}
                                      <span className={ppClass(hiPp(d))}>{hiPp(d).toFixed(1)}pp</span>
                                    </>
                                  ) },
                              ];
                              return (
                                <DataTable
                                  columns={sensCols}
                                  rows={sensitivityResult.deltas}
                                  getRowKey={(_d, i) => i}
                                  downloadName="sensitivity"
                                />
                              );
                            })()}
                          </CardContent>
                        </Card>
                      </>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
