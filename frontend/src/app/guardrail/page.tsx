"use client";

import { useState, useMemo, useEffect } from "react";
import { usePersistedState } from "@/lib/use-persisted-state";
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
import { ProgressOverlay, PreliminaryBanner, type ProgressInfo } from "@/components/progress-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { CHART_COLORS, MARGINS } from "@/lib/chart-theme";
import { Pin, PinOff } from "lucide-react";
import { runGuardrail, runGuardrailBatchBacktest, runBacktest, fetchCountries, runGuardrailScenarios, runGuardrailSensitivity, fetchHistoricalEvents } from "@/lib/api";
import { filterEvents, eventShapes, eventAnnotations } from "@/lib/historical-events";
import { downloadTrajectories } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { PdfExportButton } from "@/components/pdf-export-button";
import { useSharedParams } from "@/lib/params-context";
import type {
  GuardrailResponse,
  GuardrailBatchBacktestResponse,
  GuardrailBatchPathSummary,
  CountryInfo,
  HistoricalEvent,
  ScenarioAnalysisResponse,
  SensitivityAnalysisResponse,
} from "@/lib/types";
import { fmt, pct, countryFlag, deltaPct } from "@/lib/utils";
import { ErrorBanner } from "@/components/error-banner";

export default function GuardrailPage() {
  const t = useTranslations("guardrail");
  const tc = useTranslations("common");
  const tf = useTranslations("fanChart");
  const locale = useLocale();
  const isMobile = useIsMobile();

  const {
    params, setParams,
    guardrailTargetSuccess: targetSuccess, setGuardrailTargetSuccess: setTargetSuccess,
    guardrailUpperGuardrail: upperGuardrail, setGuardrailUpperGuardrail: setUpperGuardrail,
    guardrailLowerGuardrail: lowerGuardrail, setGuardrailLowerGuardrail: setLowerGuardrail,
    guardrailAdjustmentPct: adjustmentPct, setGuardrailAdjustmentPct: setAdjustmentPct,
    guardrailAdjustmentMode: adjustmentMode, setGuardrailAdjustmentMode: setAdjustmentMode,
    guardrailMinRemainingYears: minRemainingYears, setGuardrailMinRemainingYears: setMinRemainingYears,
    guardrailBaselineRate: baselineRate, setGuardrailBaselineRate: setBaselineRate,
    guardrailConsumptionFloor: consumptionFloor, setGuardrailConsumptionFloor: setConsumptionFloor,
    guardrailConsumptionFloorAmount: consumptionFloorAmount, setGuardrailConsumptionFloorAmount: setConsumptionFloorAmount,
    histStartYear, setHistStartYear,
    singleCountry, setSingleCountry,
  } = useSharedParams();
  const [inputMode, setInputMode] = usePersistedState<"portfolio" | "withdrawal">("fire:guardrail:inputMode", "portfolio");
  const [portfolio, setPortfolio] = usePersistedState("fire:guardrail:portfolio", params.initial_portfolio);
  const [withdrawal, setWithdrawal] = usePersistedState("fire:guardrail:withdrawal", params.annual_withdrawal);

  // Results
  const [mcResult, setMcResult] = useState<GuardrailResponse | null>(null);
  const [pinnedResult, setPinnedResult] = useState<GuardrailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const [preliminary, setPreliminary] = useState(false);
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
  // Path list filters
  const [filterCountries, setFilterCountries] = useState<Set<string>>(new Set());
  const [filterMinStartYear, setFilterMinStartYear] = useState(0);
  const [filterMinYears, setFilterMinYears] = useState(0);

  // Single backtest state
  const [singleBtLoading, setSingleBtLoading] = useState(false);
  const [countries, setCountries] = useState<CountryInfo[]>([]);

  // Historical events
  const [historicalEvents, setHistoricalEvents] = useState<HistoricalEvent[]>([]);

  // Scenario analysis state
  const [scenarioResult, setScenarioResult] = useState<ScenarioAnalysisResponse | null>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [scenarioProgress, setScenarioProgress] = useState<ProgressInfo | null>(null);
  // Sensitivity analysis state
  const [sensitivityResult, setSensitivityResult] = useState<SensitivityAnalysisResponse | null>(null);
  const [sensitivityLoading, setSensitivityLoading] = useState(false);
  const [sensitivityProgress, setSensitivityProgress] = useState<ProgressInfo | null>(null);

  useEffect(() => {
    fetchCountries(params.data_source).then(setCountries).catch(() => { /* non-critical init data */ });
  }, [params.data_source]);

  useEffect(() => {
    fetchHistoricalEvents().then(setHistoricalEvents).catch(() => { /* non-critical init data */ });
  }, []);

  const guardrailReqBase = () => ({
    input_mode: inputMode,
    initial_portfolio: portfolio,
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
    data_source: params.data_source,
    target_success: targetSuccess,
    upper_guardrail: upperGuardrail,
    lower_guardrail: lowerGuardrail,
    adjustment_pct: adjustmentPct,
    adjustment_mode: adjustmentMode,
    min_remaining_years: minRemainingYears,
    baseline_rate: baselineRate,
    consumption_floor: consumptionFloor,
    consumption_floor_amount: consumptionFloorAmount,
    leverage: params.leverage,
    borrowing_spread: params.borrowing_spread,
    cash_flows: params.cash_flows,
  });

  const handleRunMC = async () => {
    setLoading(true);
    setProgress(null);
    setPreliminary(false);
    setError(null);
    try {
      const res = await runGuardrail(guardrailReqBase(), {
        onProgress: setProgress,
        onPreliminaryResult: (data) => {
          setMcResult(data);
          setPreliminary(true);
          setBatchResult(null);
          setSelectedPath(null);
        },
      });
      setMcResult(res);
      setPreliminary(false);
      setBatchResult(null);
      setSelectedPath(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
      setProgress(null);
    }
  };

  const handleRunBatchBacktest = async () => {
    if (!mcResult) return;
    setBatchLoading(true);
    setError(null);
    setSelectedPath(null);
    setBatchSubTab("aggregate");
    setFilterCountries(new Set());
    setFilterMinStartYear(0);
    setFilterMinYears(0);
    try {
      const res = await runGuardrailBatchBacktest({
        ...guardrailReqBase(),
        initial_portfolio: mcResult.initial_portfolio,
        annual_withdrawal: mcResult.annual_withdrawal,
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
        annual_withdrawal: mcResult.annual_withdrawal,
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
        g_survived: n >= params.retirement_years && !res.g_portfolio.slice(1, -1).some((v: number) => v <= 0),
        b_survived: n >= params.retirement_years && !res.b_portfolio.slice(1, -1).some((v: number) => v <= 0),
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

  const handleRunScenarios = async () => {
    if (!mcResult) return;
    setScenarioLoading(true);
    setScenarioProgress(null);
    setError(null);
    try {
      const res = await runGuardrailScenarios({
        ...guardrailReqBase(),
        initial_portfolio: mcResult.initial_portfolio,
        annual_withdrawal: mcResult.annual_withdrawal,
      }, setScenarioProgress);
      setScenarioResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setScenarioLoading(false);
      setScenarioProgress(null);
    }
  };

  const handleRunSensitivity = async () => {
    if (!mcResult) return;
    setSensitivityLoading(true);
    setSensitivityProgress(null);
    setError(null);
    try {
      const res = await runGuardrailSensitivity({
        ...guardrailReqBase(),
        initial_portfolio: mcResult.initial_portfolio,
        annual_withdrawal: mcResult.annual_withdrawal,
      }, setSensitivityProgress);
      setSensitivityResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setSensitivityLoading(false);
      setSensitivityProgress(null);
    }
  };

  const hasProbabilisticCF = useMemo(() => {
    return params.cash_flows.some((cf) => cf.group != null);
  }, [params.cash_flows]);

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

  // Sorted & filtered paths for the table
  const sortedPaths = useMemo(() => {
    if (!batchResult) return [];
    const paths = batchResult.paths.filter((p) => {
      if (filterCountries.size > 0 && !filterCountries.has(p.country)) return false;
      if (filterMinStartYear > 0 && p.start_year < filterMinStartYear) return false;
      if (filterMinYears > 0 && p.years_simulated < filterMinYears) return false;
      return true;
    });
    paths.sort((a, b) => {
      let va: number | string, vb: number | string;
      switch (sortCol) {
        case "country": va = a.country; vb = b.country; break;
        case "start_year": va = a.start_year; vb = b.start_year; break;
        case "years_simulated": va = a.years_simulated; vb = b.years_simulated; break;
        case "g_final_portfolio": va = a.g_final_portfolio; vb = b.g_final_portfolio; break;
        case "min_withdrawal": va = Math.min(...a.g_withdrawals); vb = Math.min(...b.g_withdrawals); break;
        case "g_survived": va = a.g_survived ? 1 : 0; vb = b.g_survived ? 1 : 0; break;
        default: va = a.start_year; vb = b.start_year;
      }
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      if (a.country !== b.country) return a.country < b.country ? -1 : 1;
      return a.start_year - b.start_year;
    });
    return paths;
  }, [batchResult, sortCol, sortDir, filterCountries, filterMinStartYear, filterMinYears]);

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
            <div className="space-y-2">
              <Label className="text-xs">{t("inputMode")}</Label>
              <Select value={inputMode} onValueChange={(v) => setInputMode(v as "portfolio" | "withdrawal")}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="portfolio">{t("inputModePortfolio")}</SelectItem>
                  <SelectItem value="withdrawal">{t("inputModeWithdrawal")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {inputMode === "portfolio" ? (
              <NumberField
                label={t("initialPortfolioInput")}
                value={portfolio}
                onChange={setPortfolio}
                min={0}
              />
            ) : (
              <NumberField
                label={tc("annualWithdrawalAlt")}
                value={withdrawal}
                onChange={setWithdrawal}
                min={0}
              />
            )}

            <SidebarForm
              params={params}
              onChange={setParams}
              showWithdrawalStrategy={false}
              countries={countries}
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
                  <NumberField
                    label={t("consumptionFloor")}
                    value={+(consumptionFloor * 100).toFixed(0)}
                    onChange={(v) => setConsumptionFloor(v / 100)}
                    min={1}
                    max={99}
                    help={t("consumptionFloorHelp")}
                  />
                  <NumberField
                    label={t("consumptionFloorAmount")}
                    value={consumptionFloorAmount}
                    onChange={setConsumptionFloorAmount}
                    min={0}
                    step={1000}
                    help={t("consumptionFloorAmountHelp")}
                  />
                </div>
              </div>
            </SidebarForm>

          </CardContent>
          <div className="sticky bottom-0 bg-card px-6 pt-3 pb-4 border-t space-y-1.5">
            <Button onClick={handleRunMC} className="w-full" disabled={loading}>
              {loading ? tc("running") : t("runSimulation")}
            </Button>
            {mcResult && (
              <div className="flex gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 h-7 text-xs"
                  onClick={() => setPinnedResult(pinnedResult ? null : mcResult)}
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

      {/* ── 右侧结果 ── */}
      <main className="flex-1 space-y-6 min-w-0">
        {error && <ErrorBanner message={error} />}

        {loading && !preliminary && <ProgressOverlay message={t("guardrailLoading")} progress={progress} />}

        {mcResult && (!loading || preliminary) && (
          <Tabs defaultValue="mc">
            <TabsList className="mb-4">
              <TabsTrigger value="mc">{t("mcTab")}</TabsTrigger>
              <TabsTrigger value="backtest">{t("backtestTab")}</TabsTrigger>
              <TabsTrigger value="scenario">{t("scenarioTab")}</TabsTrigger>
            </TabsList>

            {/* ═══ MC Tab ═══ */}
            <TabsContent value="mc" className="space-y-6">
              {preliminary && <PreliminaryBanner />}
              <div id="guardrail-results" className="space-y-6">
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
                <PdfExportButton targetId="guardrail-results" filename="fire-guardrail-report.pdf" />
              </div>

              {/* 指标卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <MetricCard
                  label={inputMode === "portfolio" ? t("annualWithdrawalResult") : t("initialPortfolioResult")}
                  value={inputMode === "portfolio" ? fmt(mcResult.annual_withdrawal) : fmt(mcResult.initial_portfolio)}
                />
                <MetricCard
                  label={t("initialRate")}
                  value={pct(mcResult.initial_rate)}
                />
                <MetricCard
                  label={t("guardrailSuccess")}
                  value={pct(mcResult.g_success_rate)}
                  tooltip={tc("successRateHelp")}
                  delta={pinnedResult ? deltaPct(mcResult.g_success_rate, pinnedResult.g_success_rate) : undefined}
                />
                <MetricCard
                  label={t("guardrailFundedRatio")}
                  value={pct(mcResult.g_funded_ratio)}
                  tooltip={tc("fundedRatioHelp")}
                  delta={pinnedResult ? deltaPct(mcResult.g_funded_ratio, pinnedResult.g_funded_ratio) : undefined}
                />
                <MetricCard
                  label={t("baselineSuccess")}
                  value={pct(mcResult.b_success_rate)}
                  sub={t("baselineRateSub", { rate: (baselineRate * 100).toFixed(1) })}
                  tooltip={tc("successRateHelp")}
                  delta={pinnedResult ? deltaPct(mcResult.b_success_rate, pinnedResult.b_success_rate) : undefined}
                />
                <MetricCard
                  label={t("baselineFundedRatio")}
                  value={pct(mcResult.b_funded_ratio)}
                  tooltip={tc("fundedRatioHelp")}
                  delta={pinnedResult ? deltaPct(mcResult.b_funded_ratio, pinnedResult.b_funded_ratio) : undefined}
                />
              </div>

              {/* 初始护栏触发建议 */}
              {mcResult.upper_trigger_portfolio > 0 && mcResult.lower_trigger_portfolio > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">{t("triggerPanelTitle")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* 上护栏 — 消费提升 */}
                      <div className="rounded-lg border border-green-200 bg-green-50 dark:bg-green-950/30 dark:border-green-800 p-4 space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-lg">📈</span>
                          <span className="font-semibold text-green-700 dark:text-green-400 text-sm">{t("planIncrease")}</span>
                        </div>
                        <div className="text-xs text-muted-foreground">{t("ifBalanceReaches")}</div>
                        <div className="text-xl font-bold text-green-700 dark:text-green-400" title={`$${mcResult.upper_trigger_portfolio.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}>
                          {fmt(mcResult.upper_trigger_portfolio)}
                        </div>
                        <Separator className="bg-green-200 dark:bg-green-800" />
                        <div className="text-xs text-muted-foreground">{t("thenIncreaseTo")}</div>
                        <div className="flex items-baseline gap-2">
                          <span className="text-lg font-bold text-green-700 dark:text-green-400" title={`$${mcResult.upper_trigger_withdrawal.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}>
                            {fmt(mcResult.upper_trigger_withdrawal)}
                          </span>
                          <span className="text-xs font-medium text-green-600 dark:text-green-500">
                            ({((mcResult.upper_trigger_withdrawal / mcResult.annual_withdrawal - 1) * 100).toFixed(1)}%)
                          </span>
                        </div>
                      </div>
                      {/* 下护栏 — 消费削减 */}
                      <div className="rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-800 p-4 space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-lg">📉</span>
                          <span className="font-semibold text-red-700 dark:text-red-400 text-sm">{t("planDecrease")}</span>
                        </div>
                        <div className="text-xs text-muted-foreground">{t("ifBalanceDrops")}</div>
                        <div className="text-xl font-bold text-red-700 dark:text-red-400" title={`$${mcResult.lower_trigger_portfolio.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}>
                          {fmt(mcResult.lower_trigger_portfolio)}
                        </div>
                        <Separator className="bg-red-200 dark:bg-red-800" />
                        <div className="text-xs text-muted-foreground">{t("thenDecreaseTo")}</div>
                        <div className="flex items-baseline gap-2">
                          <span className="text-lg font-bold text-red-700 dark:text-red-400" title={`$${mcResult.lower_trigger_withdrawal.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}>
                            {fmt(mcResult.lower_trigger_withdrawal)}
                          </span>
                          <span className="text-xs font-medium text-red-600 dark:text-red-500">
                            ({((mcResult.lower_trigger_withdrawal / mcResult.annual_withdrawal - 1) * 100).toFixed(1)}%)
                          </span>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* 资产轨迹对比 */}
              <Card>
                <CardContent className="pt-4">
                  <FanChart
                    trajectories={mcResult.g_percentile_trajectories}
                    title={t("portfolioComparison")}
                    xLabels={Array.from({ length: mcResult.g_percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i)}
                    xTitle={tf("ageAxis")}
                    showLogToggle
                    extraTraces={[
                      {
                        x: Array.from({ length: mcResult.b_percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i),
                        y: mcResult.b_percentile_trajectories["50"],
                        mode: "lines",
                        name: tc("baselineP50"),
                        line: { color: CHART_COLORS.orange.hex, width: 2, dash: "dash" },
                        type: "scatter",
                      },
                      ...(pinnedResult ? [{
                        x: Array.from({ length: pinnedResult.g_percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i),
                        y: pinnedResult.g_percentile_trajectories["50"],
                        mode: "lines" as const,
                        name: tc("baselineP50"),
                        line: { color: CHART_COLORS.neutral.hex, width: 2, dash: "dash" as const },
                        type: "scatter" as const,
                        hovertemplate: tc.raw("baselineHover"),
                      }] : []),
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
                    xLabels={Array.from({ length: mcResult.g_withdrawal_percentiles["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i)}
                    xTitle={tf("ageAxis")}
                    color={CHART_COLORS.secondary.rgb}
                    showLogToggle
                    extraTraces={(() => {
                      const wdX = Array.from({ length: mcResult.g_withdrawal_percentiles["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i);
                      return [
                        {
                          x: wdX,
                          y: mcResult.b_withdrawal_percentiles?.["50"] ?? Array(wdX.length).fill(mcResult.baseline_annual_wd),
                          mode: "lines",
                          name: t("baselineP50Withdrawal"),
                          line: { color: CHART_COLORS.orange.hex, width: 2, dash: "dash" },
                          type: "scatter",
                          hovertemplate: tc.raw("baselineHover"),
                        },
                        {
                          x: wdX,
                          y: (() => {
                            const bP50 = mcResult.b_withdrawal_percentiles?.["50"];
                            const baseWd = mcResult.baseline_annual_wd;
                            const initWd = mcResult.annual_withdrawal;
                            if (bP50) return bP50.map((v) => initWd + (v - baseWd));
                            return Array(wdX.length).fill(initWd);
                          })(),
                          mode: "lines",
                          name: tc("initialWithdrawalLine", { amount: fmt(mcResult.annual_withdrawal) }),
                          line: { color: CHART_COLORS.neutral.hex, width: 1, dash: "dot" },
                          type: "scatter",
                          hovertemplate: tc.raw("initialWithdrawalHover"),
                        },
                      ];
                    })()}
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
              </div>
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

              {(batchLoading || singleBtLoading) && <ProgressOverlay message={singleBtLoading ? t("backtesting") : t("batchBacktesting")} />}

              {batchResult && !batchLoading && !selectedPath && (
                <>
                  {/* Summary metrics */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <MetricCard label={t("numPaths")} value={`${batchResult.num_paths}`} />
                    <MetricCard label={t("numComplete")} value={`${batchResult.num_complete}`} />
                    <MetricCard label={t("guardrailSuccess")} value={pct(batchResult.g_success_rate)} tooltip={tc("successRateHelp")} />
                    <MetricCard label={t("guardrailFundedRatio")} value={pct(batchResult.g_funded_ratio)} tooltip={tc("fundedRatioHelp")} />
                    <MetricCard label={t("baselineSuccess")} value={pct(batchResult.b_success_rate)} tooltip={tc("successRateHelp")} />
                    <MetricCard label={t("baselineFundedRatio")} value={pct(batchResult.b_funded_ratio)} tooltip={tc("fundedRatioHelp")} />
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
                              xLabels={Array.from({ length: batchResult.g_percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i)}
                              xTitle={tf("ageAxis")}
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
                              xLabels={Array.from({ length: batchResult.g_withdrawal_percentiles["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i)}
                              xTitle={tf("ageAxis")}
                              color={CHART_COLORS.secondary.rgb}
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
                              xLabels={Array.from({ length: batchResult.b_percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i)}
                              xTitle={tf("ageAxis")}
                              color={CHART_COLORS.orange.rgb}
                              showLogToggle
                            />
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
                              <th className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("min_withdrawal")}>
                                {t("minWithdrawal")}{sortIndicator("min_withdrawal")}
                              </th>
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
                                <td className="px-3 py-1.5">{countryLabel(p.country)}</td>
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
                                <td className="px-3 py-1.5 text-right font-mono">{fmt(Math.min(...p.g_withdrawals))}</td>
                                <td className="px-3 py-1.5 text-right font-mono">{fmt(p.g_final_portfolio)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div className="flex items-center justify-between">
                        <p className="text-xs text-muted-foreground">
                          * = {t("numIncomplete")} | G = Guardrail | B = {tc("baseline")}
                        </p>
                        {batchResult && (
                          <p className="text-xs text-muted-foreground">
                            {t("filteredCount", { count: sortedPaths.length, total: batchResult.paths.length })}
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
                    <MetricCard label={t("backtestCountry")} value={countryLabel(selectedPath.country)} />
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
                      {(() => {
                        const pathCountry = selectedPath.country;
                        const startYear = selectedPath.year_labels[0];
                        const endYear = selectedPath.year_labels[selectedPath.year_labels.length - 1];
                        const filtered = filterEvents(historicalEvents, pathCountry, startYear, endYear);
                        const yMax = Math.max(...selectedPath.g_portfolio, ...selectedPath.b_portfolio);
                        return (
                          <PlotlyChart
                            data={[
                              {
                                x: selectedPath.year_labels,
                                y: selectedPath.g_portfolio,
                                type: "scatter", mode: "lines",
                                name: "Guardrail",
                                line: { color: CHART_COLORS.primary.hex, width: 2 },
                              },
                              {
                                x: selectedPath.year_labels,
                                y: selectedPath.b_portfolio,
                                type: "scatter", mode: "lines",
                                name: tc("baseline"),
                                line: { color: CHART_COLORS.orange.hex, width: 2, dash: "dash" },
                              },
                            ]}
                            layout={{
                              title: isMobile ? undefined : {
                                text: t("historicalPortfolioComparison"), font: { size: 14 },
                                y: 0.98, x: 0.5, xanchor: "center" as const, yanchor: "top" as const,
                              },
                              xaxis: { title: { text: t("yearAxis") }, tickfont: { size: isMobile ? 9 : 12 } },
                              yaxis: {
                                title: isMobile ? undefined : { text: t("assetAxis") },
                                type: btLogScale ? "log" : "linear",
                                tickformat: btLogScale ? "$~s" : (isMobile ? "$~s" : "$,.0f"),
                                tickfont: { size: isMobile ? 9 : 12 },
                              },
                              height: isMobile ? 280 : 400,
                              margin: MARGINS.withTitle(isMobile),
                              legend: isMobile
                                ? { x: 0.5, y: 1.02, xanchor: "center" as const, yanchor: "bottom" as const, orientation: "h" as const, font: { size: 8 } }
                                : { x: 0, y: 1.0, yanchor: "bottom" as const, orientation: "h" as const },
                              shapes: eventShapes(filtered, yMax) as Plotly.Layout["shapes"],
                              annotations: eventAnnotations(filtered, locale, yMax) as Plotly.Layout["annotations"],
                            }}
                            config={{
                              displayModeBar: isMobile ? false : ("hover" as const),
                            }}
                          />
                        );
                      })()}
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
                            line: { color: CHART_COLORS.primary.hex, width: 2 },
                            yaxis: "y",
                          },
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: selectedPath.b_withdrawals,
                            type: "scatter", mode: "lines",
                            name: t("baselineWithdrawal"),
                            line: { color: CHART_COLORS.orange.hex, width: 2, dash: "dash" },
                            yaxis: "y",
                          },
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: selectedPath.g_success_rates.map((s) => s * 100),
                            type: "scatter", mode: "lines",
                            name: t("successRateLine"),
                            line: { color: `rgba(${CHART_COLORS.neutral.rgb},0.5)`, width: 1 },
                            fill: "tozeroy", fillcolor: `rgba(${CHART_COLORS.neutral.rgb},0.08)`,
                            yaxis: "y2",
                          },
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: Array(selectedPath.years_simulated).fill(upperGuardrail * 100),
                            type: "scatter", mode: "lines",
                            name: t("upperGuardrailLine", { pct: (upperGuardrail * 100).toFixed(0) }),
                            line: { color: CHART_COLORS.secondary.hex, width: 1, dash: "dot" },
                            yaxis: "y2",
                          },
                          {
                            x: selectedPath.year_labels.slice(0, selectedPath.years_simulated),
                            y: Array(selectedPath.years_simulated).fill(lowerGuardrail * 100),
                            type: "scatter", mode: "lines",
                            name: t("lowerGuardrailLine", { pct: (lowerGuardrail * 100).toFixed(0) }),
                            line: { color: CHART_COLORS.danger.hex, width: 1, dash: "dot" },
                            yaxis: "y2",
                          },
                        ]}
                        layout={{
                          title: isMobile ? undefined : {
                            text: t("withdrawalAmountAndSuccess"), font: { size: 14 },
                            y: 0.98, x: 0.5, xanchor: "center" as const, yanchor: "top" as const,
                          },
                          xaxis: { title: { text: t("yearAxis") }, tickfont: { size: isMobile ? 9 : 12 } },
                          yaxis: {
                            title: isMobile ? undefined : { text: t("withdrawalAmount") },
                            type: btWdLogScale ? "log" : "linear",
                            tickformat: btWdLogScale ? "$~s" : (isMobile ? "$~s" : "$,.0f"),
                            tickfont: { size: isMobile ? 9 : 12 }, side: "left",
                          },
                          yaxis2: {
                            title: isMobile ? undefined : { text: t("successRateAxis") },
                            type: "linear" as const,
                            overlaying: "y", side: "right", range: [0, 105],
                            tickfont: { size: isMobile ? 9 : 12 },
                          },
                          height: isMobile ? 300 : 450,
                          margin: MARGINS.dualAxisWithTitle(isMobile),
                          legend: isMobile
                            ? { x: 0.5, y: 1.02, xanchor: "center" as const, yanchor: "bottom" as const, orientation: "h" as const, font: { size: 7 }, tracegroupgap: 2 }
                            : { x: 0, y: 1.0, yanchor: "bottom" as const, orientation: "h" as const },
                        }}
                        config={{
                          displayModeBar: isMobile ? false : ("hover" as const),
                        }}
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

            {/* ═══ Scenario Analysis Tab ═══ */}
            <TabsContent value="scenario" className="space-y-6">
              {/* Section 1: Cash Flow Scenario Decomposition */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{t("scenarioTitle")}</CardTitle>
                  <p className="text-xs text-muted-foreground">{t("scenarioDesc")}</p>
                </CardHeader>
                <CardContent className="space-y-4">
                  {hasProbabilisticCF ? (
                    <Button
                      onClick={handleRunScenarios}
                      disabled={scenarioLoading}
                      size="sm"
                    >
                      {scenarioLoading ? t("scenarioRunning") : t("runScenarioAnalysis")}
                    </Button>
                  ) : (
                    <p className="text-sm text-muted-foreground italic">
                      {t("scenarioNoProbCF")}
                    </p>
                  )}
                </CardContent>
              </Card>

              {scenarioLoading && <ProgressOverlay message={t("scenarioLoading")} progress={scenarioProgress} />}

              {scenarioResult && !scenarioLoading && (
                <>
                  {scenarioResult.mode === "per_group" && (
                    <p className="text-xs text-muted-foreground bg-muted/50 rounded-md px-3 py-2">
                      {t("scenarioPerGroupHint")}
                    </p>
                  )}

                  {/* Comparison horizontal bar chart — withdrawal */}
                  <Card>
                    <CardContent className="pt-4">
                      {(() => {
                        const baseWD = scenarioResult.base_case.annual_withdrawal;
                        const fmtDollar = (v: number) =>
                          `$${Math.round(v).toLocaleString("en-US")}`;
                        const sorted = [...scenarioResult.scenarios].sort(
                          (a, b) => a.annual_withdrawal - b.annual_withdrawal
                        );
                        const labels = sorted.map((s) => {
                          const short = s.label.length > 40 ? s.label.slice(0, 37) + "…" : s.label;
                          return `${short} (${(s.probability * 100).toFixed(0)}%)`;
                        });
                        const values = sorted.map((s) => s.annual_withdrawal);
                        const colors = sorted.map((s) =>
                          s.annual_withdrawal >= baseWD
                            ? CHART_COLORS.secondary.hex
                            : CHART_COLORS.danger.hex
                        );

                        const valueAnnotations = sorted.map((s, i) => ({
                          x: s.annual_withdrawal,
                          y: labels[i],
                          text: fmtDollar(s.annual_withdrawal),
                          showarrow: false,
                          xanchor: "left" as const,
                          xshift: 4,
                          font: { size: 10 },
                        }));

                        return (
                          <PlotlyChart
                            data={[
                              {
                                type: "bar" as const,
                                orientation: "h" as const,
                                y: labels,
                                x: values,
                                marker: { color: colors },
                                hovertemplate: sorted.map((s) =>
                                  `%{y}<br>${t("scenarioAnnualWD")}: ${fmtDollar(s.annual_withdrawal)}<extra></extra>`
                                ),
                              },
                            ]}
                            layout={{
                              title: isMobile ? undefined : { text: t("scenarioComparisonTitle"), font: { size: 14 } },
                              xaxis: {
                                title: { text: t("scenarioAnnualWD") },
                                type: "linear" as const,
                                tickprefix: "$",
                                range: (() => {
                                  const all = sorted.map((s) => s.annual_withdrawal);
                                  all.push(baseWD);
                                  const min = Math.min(...all);
                                  const max = Math.max(...all);
                                  const pad = Math.max((max - min) * 0.3, max * 0.02);
                                  return [Math.max(0, min - pad), max + pad];
                                })(),
                              },
                              margin: isMobile
                                ? { l: 160, r: 90, t: 10, b: 40 }
                                : { l: 260, r: 120, t: 40, b: 50 },
                              height: Math.max(isMobile ? 250 : 300, sorted.length * (isMobile ? 26 : 30) + 80),
                              shapes: [
                                {
                                  type: "line",
                                  x0: baseWD,
                                  x1: baseWD,
                                  y0: -0.5,
                                  y1: sorted.length - 0.5,
                                  line: { color: CHART_COLORS.primary.hex, width: 2, dash: "dash" },
                                },
                              ],
                              annotations: [
                                {
                                  x: baseWD,
                                  y: sorted.length - 0.5,
                                  text: `${t("scenarioBaseCase")}: ${fmtDollar(baseWD)}`,
                                  showarrow: false,
                                  yanchor: "bottom" as const,
                                  font: { size: 11, color: CHART_COLORS.primary.hex },
                                },
                                ...valueAnnotations,
                              ],
                            }}
                          />
                        );
                      })()}
                    </CardContent>
                  </Card>

                  {/* Results table */}
                  <Card>
                    <CardContent className="pt-4 overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b">
                            <th className="text-left py-2 px-2 font-medium">{t("scenarioLabel")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("scenarioProbability")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("scenarioSuccessRate")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("scenarioFundedRatio")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("scenarioAnnualWD")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("scenarioMedianFinal")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("scenarioMedianConsumption")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {/* Base case row */}
                          <tr className="border-b bg-muted/50 font-medium">
                            <td className="py-1.5 px-2">{t("scenarioBaseCase")}</td>
                            <td className="text-right py-1.5 px-2">—</td>
                            <td className="text-right py-1.5 px-2">{pct(scenarioResult.base_case.success_rate)}</td>
                            <td className="text-right py-1.5 px-2">{pct(scenarioResult.base_case.funded_ratio)}</td>
                            <td className="text-right py-1.5 px-2">{fmt(scenarioResult.base_case.annual_withdrawal)}</td>
                            <td className="text-right py-1.5 px-2">{fmt(scenarioResult.base_case.median_final_portfolio)}</td>
                            <td className="text-right py-1.5 px-2">{fmt(scenarioResult.base_case.median_total_consumption)}</td>
                          </tr>
                          {scenarioResult.scenarios.map((s, i) => (
                            <tr key={i} className="border-b hover:bg-muted/30">
                              <td className="py-1.5 px-2 max-w-[200px] truncate" title={s.label}>{s.label}</td>
                              <td className="text-right py-1.5 px-2">{(s.probability * 100).toFixed(1)}%</td>
                              <td className="text-right py-1.5 px-2">{pct(s.success_rate)}</td>
                              <td className="text-right py-1.5 px-2">{pct(s.funded_ratio)}</td>
                              <td className="text-right py-1.5 px-2">{fmt(s.annual_withdrawal)}</td>
                              <td className="text-right py-1.5 px-2">{fmt(s.median_final_portfolio)}</td>
                              <td className="text-right py-1.5 px-2">{fmt(s.median_total_consumption)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </CardContent>
                  </Card>
                </>
              )}

              <Separator />

              {/* Section 2: Parameter Sensitivity (Tornado) */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{t("sensitivityTitle")}</CardTitle>
                  <p className="text-xs text-muted-foreground">{t("sensitivityDesc")}</p>
                </CardHeader>
                <CardContent>
                  <Button
                    onClick={handleRunSensitivity}
                    disabled={sensitivityLoading}
                    size="sm"
                  >
                    {sensitivityLoading ? t("sensitivityRunning") : t("runSensitivity")}
                  </Button>
                </CardContent>
              </Card>

              {sensitivityLoading && <ProgressOverlay message={t("sensitivityLoading")} progress={sensitivityProgress} />}

              {sensitivityResult && !sensitivityLoading && (
                <>
                  {/* Tornado chart — withdrawal delta */}
                  <Card>
                    <CardContent className="pt-4">
                      {(() => {
                        const baseWD = sensitivityResult.base_withdrawal ?? 0;
                        const sorted = [...sensitivityResult.deltas].sort(
                          (a, b) =>
                            Math.abs((a.high_withdrawal ?? baseWD) - (a.low_withdrawal ?? baseWD)) -
                            Math.abs((b.high_withdrawal ?? baseWD) - (b.low_withdrawal ?? baseWD))
                        );
                        const labels = sorted.map((d) => d.param_label);
                        const fmtDollar = (v: number) =>
                          `$${Math.round(v).toLocaleString("en-US")}`;

                        const valueAnnotations = sorted.flatMap((d) => {
                          const lowVal = d.low_withdrawal ?? baseWD;
                          const highVal = d.high_withdrawal ?? baseWD;
                          if (baseWD > 0 && Math.abs(highVal - lowVal) / baseWD < 0.03) return [];
                          return [
                            {
                              x: lowVal,
                              y: d.param_label,
                              text: fmtDollar(lowVal),
                              showarrow: false,
                              xanchor: (lowVal <= baseWD ? "right" : "left") as "right" | "left",
                              xshift: lowVal <= baseWD ? -4 : 4,
                              font: { size: 10 },
                            },
                            {
                              x: highVal,
                              y: d.param_label,
                              text: fmtDollar(highVal),
                              showarrow: false,
                              xanchor: (highVal >= baseWD ? "left" : "right") as "left" | "right",
                              xshift: highVal >= baseWD ? 4 : -4,
                              font: { size: 10 },
                            },
                          ];
                        });

                        /* eslint-disable @typescript-eslint/no-explicit-any */
                        const traces: any[] = [
                          {
                            type: "bar",
                            orientation: "h",
                            y: labels,
                            x: sorted.map((d) => (d.low_withdrawal ?? baseWD) - baseWD),
                            base: Array(sorted.length).fill(baseWD),
                            marker: { color: CHART_COLORS.danger.hex },
                            name: t("sensitivityLow"),
                            cliponaxis: false,
                            hovertemplate: sorted.map((d) =>
                              `%{y}<br>${t("sensitivityLow")}: ${fmtDollar(d.low_withdrawal ?? baseWD)}<extra></extra>`
                            ),
                          },
                          {
                            type: "bar",
                            orientation: "h",
                            y: labels,
                            x: sorted.map((d) => (d.high_withdrawal ?? baseWD) - baseWD),
                            base: Array(sorted.length).fill(baseWD),
                            marker: { color: CHART_COLORS.secondary.hex },
                            name: t("sensitivityHigh"),
                            cliponaxis: false,
                            hovertemplate: sorted.map((d) =>
                              `%{y}<br>${t("sensitivityHigh")}: ${fmtDollar(d.high_withdrawal ?? baseWD)}<extra></extra>`
                            ),
                          },
                        ];
                        /* eslint-enable @typescript-eslint/no-explicit-any */

                        return (
                          <PlotlyChart
                            data={traces}
                            layout={{
                              title: { text: t("sensitivityChartTitle"), font: { size: 14 } },
                              xaxis: {
                                title: { text: t("sensitivityImpact") },
                                type: "linear" as const,
                                tickprefix: "$",
                              },
                              barmode: "overlay",
                              margin: isMobile
                                ? { l: 100, r: 90, t: 40, b: 40 }
                                : { l: 140, r: 120, t: 50, b: 50 },
                              height: isMobile ? 320 : 400,
                              shapes: [
                                {
                                  type: "line",
                                  x0: baseWD,
                                  x1: baseWD,
                                  y0: -0.5,
                                  y1: sorted.length - 0.5,
                                  line: { color: CHART_COLORS.neutral.hex, width: 2, dash: "dash" },
                                },
                              ],
                              annotations: [
                                {
                                  x: baseWD,
                                  y: sorted.length - 0.5,
                                  text: `${t("sensitivityBase")}: ${fmtDollar(baseWD)}`,
                                  showarrow: false,
                                  yanchor: "bottom" as const,
                                  font: { size: 11 },
                                },
                                ...valueAnnotations,
                              ],
                            }}
                          />
                        );
                      })()}
                    </CardContent>
                  </Card>

                  {/* Sensitivity detail table — withdrawal delta */}
                  <Card>
                    <CardContent className="pt-4 overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b">
                            <th className="text-left py-2 px-2 font-medium">{t("sensitivityParam")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("sensitivityBaseValue")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("sensitivityRange")}</th>
                            <th className="text-right py-2 px-2 font-medium">{t("sensitivityImpact")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sensitivityResult.deltas.map((d, i) => {
                            const baseWD = sensitivityResult.base_withdrawal ?? 0;
                            const fmtVal = (v: number, key: string) => {
                              if (key === "initial_portfolio" || key === "annual_withdrawal")
                                return `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
                              if (key === "retirement_years") return `${v.toFixed(0)}`;
                              if (key === "stock_allocation" || key === "target_success")
                                return `${(v * 100).toFixed(0)}%`;
                              return v.toFixed(2);
                            };
                            const loD = (d.low_withdrawal ?? baseWD) - baseWD;
                            const hiD = (d.high_withdrawal ?? baseWD) - baseWD;
                            const fmtDelta = (v: number) => {
                              const sign = v >= 0 ? "+" : "";
                              return `${sign}$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
                            };
                            return (
                              <tr key={i} className="border-b hover:bg-muted/30">
                                <td className="py-1.5 px-2">{d.param_label}</td>
                                <td className="text-right py-1.5 px-2">{fmtVal(d.base_value, d.param_key)}</td>
                                <td className="text-right py-1.5 px-2">
                                  {fmtVal(d.low_value, d.param_key)} ~ {fmtVal(d.high_value, d.param_key)}
                                </td>
                                <td className="text-right py-1.5 px-2">
                                  <span className={loD < 0 ? "text-red-600" : "text-green-600"}>
                                    {fmtDelta(loD)}
                                  </span>
                                  {" / "}
                                  <span className={hiD < 0 ? "text-red-600" : "text-green-600"}>
                                    {fmtDelta(hiD)}
                                  </span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </CardContent>
                  </Card>
                </>
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
