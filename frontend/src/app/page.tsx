"use client";

import { useState, useMemo, useEffect } from "react";
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
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { CHART_COLORS, MARGINS } from "@/lib/chart-theme";
import { runSimulation, runSimBatchBacktest, runSimBacktest, fetchCountries } from "@/lib/api";
import { downloadTrajectories } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { useSharedParams } from "@/lib/params-context";
import type { SimulationResponse, SimBatchBacktestResponse, SimBatchPathSummary, CountryInfo } from "@/lib/types";
import { fmt, pct } from "@/lib/utils";

export default function SimulatorPage() {
  const t = useTranslations("simulator");
  const tc = useTranslations("common");
  const locale = useLocale();

  const isMobile = useIsMobile();

  const { params, setParams, histStartYear, setHistStartYear, singleCountry, setSingleCountry } = useSharedParams();
  const [portfolio, setPortfolio] = useState(params.initial_portfolio);
  const [withdrawal, setWithdrawal] = useState(params.annual_withdrawal);

  // MC state
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [loading, setLoading] = useState(false);
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
  const [sortCol, setSortCol] = useState<string>("start_year");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  // Path list filters
  const [filterCountries, setFilterCountries] = useState<Set<string>>(new Set());
  const [filterMinStartYear, setFilterMinStartYear] = useState(0);
  const [filterMinYears, setFilterMinYears] = useState(0);

  // Single backtest state
  const [singleBtLoading, setSingleBtLoading] = useState(false);
  const [countries, setCountries] = useState<CountryInfo[]>([]);

  useEffect(() => {
    fetchCountries(params.data_source).then(setCountries).catch(() => {});
  }, [params.data_source]);

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runSimulation({
        ...params,
        initial_portfolio: portfolio,
        annual_withdrawal: withdrawal,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
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
        pooling_method: params.pooling_method,
        data_source: params.data_source,
        withdrawal_strategy: params.withdrawal_strategy,
        dynamic_ceiling: params.dynamic_ceiling,
        dynamic_floor: params.dynamic_floor,
        retirement_age: params.retirement_age,
        leverage: params.leverage,
        borrowing_spread: params.borrowing_spread,
        cash_flows: params.cash_flows,
        hist_start_year: histStartYear,
      });
      // Convert SimBacktestResponse -> SimBatchPathSummary for detail view
      setSelectedPath({
        country: btCountry,
        start_year: histStartYear,
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

  // Unique countries from batch result (for filter chips)
  const availableCountries = useMemo(() => {
    if (!batchResult) return [];
    return Array.from(new Set(batchResult.paths.map((p) => p.country))).sort();
  }, [batchResult]);

  // Sorted & filtered paths for the table
  const sortedPaths = useMemo(() => {
    if (!batchResult) return [];
    let paths = batchResult.paths.filter((p) => {
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
        case "final_portfolio": va = a.final_portfolio; vb = b.final_portfolio; break;
        case "min_withdrawal": va = Math.min(...a.withdrawals); vb = Math.min(...b.withdrawals); break;
        case "survived": va = a.survived ? 1 : 0; vb = b.survived ? 1 : 0; break;
        default: va = a.start_year; vb = b.start_year;
      }
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      // secondary sort by country then start_year
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

            <SidebarForm params={params} onChange={setParams} />

            <Button onClick={handleRun} className="w-full" disabled={loading}>
              {loading ? tc("running") : t("runSimulation")}
            </Button>
          </CardContent>
        </Card>
      </aside>

      {/* ── 右侧结果区 ── */}
      <main className="flex-1 space-y-6 min-w-0">
        {error && (
          <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}
        {btError && (
          <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700">
            {btError}
          </div>
        )}

        <Tabs defaultValue="mc">
          <TabsList className="mb-4">
            <TabsTrigger value="mc">{t("tabMonteCarlo")}</TabsTrigger>
            <TabsTrigger value="backtest">{t("tabBacktest")}</TabsTrigger>
          </TabsList>

          {/* ── MC Tab ── */}
          <TabsContent value="mc" className="space-y-6">
            {loading && <LoadingOverlay />}

            {result && !loading && (
              <>
                {/* 下载按钮组 */}
                <div className="flex flex-wrap gap-2">
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
                  <MetricCard label={t("successRate")} value={pct(result.success_rate)} />
                  <MetricCard label={t("fundedRatio")} value={pct(result.funded_ratio)} />
                  <MetricCard label={t("medianFinalPortfolio")} value={fmt(result.final_median)} />
                  <MetricCard label={t("meanFinalPortfolio")} value={fmt(result.final_mean)} />
                  <MetricCard
                    label={t("initialWithdrawalRate")}
                    value={pct(result.initial_withdrawal_rate)}
                  />
                </div>

                {/* 资产轨迹扇形图 */}
                <Card>
                  <CardContent className="pt-4">
                    <FanChart
                      trajectories={result.percentile_trajectories}
                      title={t("portfolioTrajectory")}
                      showLogToggle
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
                        color={CHART_COLORS.orange.rgb}
                        showLogToggle
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
              </>
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

            {(batchLoading || singleBtLoading) && <LoadingOverlay message={singleBtLoading ? t("backtesting") : t("batchBacktesting")} />}

            {batchResult && !batchLoading && !selectedPath && (
              <>
                {/* Summary metrics */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <MetricCard label={t("numPaths")} value={`${batchResult.num_paths}`} />
                  <MetricCard label={t("numComplete")} value={`${batchResult.num_complete}`} />
                  <MetricCard label={t("successRate")} value={pct(batchResult.success_rate)} />
                  <MetricCard label={t("fundedRatio")} value={pct(batchResult.funded_ratio)} />
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
                    {/* Portfolio fan chart */}
                    {Object.keys(batchResult.percentile_trajectories).length > 0 && (
                      <Card>
                        <CardContent className="pt-4">
                          <FanChart
                            trajectories={batchResult.percentile_trajectories}
                            title={t("portfolioTrajectory")}
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
                            color={CHART_COLORS.orange.rgb}
                            showLogToggle
                          />
                        </CardContent>
                      </Card>
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
                              {c}
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
                              {t("country")}{sortIndicator("country")}
                            </th>
                            <th className="px-3 py-2 text-left cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("start_year")}>
                              {t("startYear")}{sortIndicator("start_year")}
                            </th>
                            <th className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("years_simulated")}>
                              {t("yearsSimulatedShort")}{sortIndicator("years_simulated")}
                            </th>
                            <th className="px-3 py-2 text-center whitespace-nowrap">{t("survived")}</th>
                            <th className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("min_withdrawal")}>
                              {t("minWithdrawal")}{sortIndicator("min_withdrawal")}
                            </th>
                            <th className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap" onClick={() => handleSort("final_portfolio")}>
                              {t("finalPortfolio")}{sortIndicator("final_portfolio")}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {sortedPaths.map((p, i) => (
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
                                {p.survived
                                  ? <span className="text-green-600">✓</span>
                                  : <span className="text-red-500">✗</span>
                                }
                              </td>
                              <td className="px-3 py-1.5 text-right font-mono">{fmt(Math.min(...p.withdrawals))}</td>
                              <td className="px-3 py-1.5 text-right font-mono">{fmt(p.final_portfolio)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="flex items-center justify-between">
                      <p className="text-xs text-muted-foreground">
                        * = {t("incomplete")} (&lt; {params.retirement_years} {t("yearsSimulatedShort")})
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
                  <MetricCard label={t("country")} value={selectedPath.country} />
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
                    <PlotlyChart
                      data={[{
                        x: selectedPath.year_labels.concat(
                          selectedPath.portfolio.length > selectedPath.years_simulated
                            ? [selectedPath.year_labels[selectedPath.years_simulated - 1] + 1]
                            : []
                        ),
                        y: selectedPath.portfolio,
                        type: "scatter", mode: "lines",
                        name: t("portfolioHistory"),
                        line: { color: CHART_COLORS.primary.hex, width: 2 },
                        hovertemplate: "%{x}: %{y:$,.0f}<extra></extra>",
                      }]}
                      layout={{
                        title: isMobile ? undefined : { text: t("portfolioHistory"), font: { size: 14 } },
                        xaxis: { title: { text: tc("year") } },
                        yaxis: {
                          title: { text: tc("amount") },
                          type: btLogScale ? "log" : "linear",
                          tickformat: btLogScale ? "$~s" : "$,.0f",
                        },
                        margin: MARGINS.withTitle(isMobile),
                        height: isMobile ? 260 : 380,
                        showlegend: false,
                      }}
                      config={{ displayModeBar: false }}
                    />
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
                        x: selectedPath.year_labels,
                        y: selectedPath.withdrawals,
                        type: "bar",
                        name: t("withdrawalHistory"),
                        marker: { color: CHART_COLORS.orange.hex },
                        hovertemplate: "%{x}: %{y:$,.0f}<extra></extra>",
                      }]}
                      layout={{
                        title: isMobile ? undefined : { text: t("withdrawalHistory"), font: { size: 14 } },
                        xaxis: { title: { text: tc("year") } },
                        yaxis: {
                          title: { text: tc("amount") },
                          type: btWdLogScale ? "log" : "linear",
                          tickformat: btWdLogScale ? "$~s" : "$,.0f",
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
        </Tabs>
      </main>
    </div>
  );
}
