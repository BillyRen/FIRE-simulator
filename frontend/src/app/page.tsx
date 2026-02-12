"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SidebarForm, NumberField } from "@/components/sidebar-form";
import { FanChart, useIsMobile, MobileChartTitle } from "@/components/fan-chart";
import { MetricCard } from "@/components/metric-card";
import { StatsTable } from "@/components/stats-table";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { runSimulation, runSimBacktest } from "@/lib/api";
import { downloadTrajectories, downloadCSV } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { DEFAULT_PARAMS } from "@/lib/types";
import type { FormParams, SimulationResponse, SimBacktestResponse } from "@/lib/types";
import { fmt, pct } from "@/lib/utils";

export default function SimulatorPage() {
  const t = useTranslations("simulator");
  const tc = useTranslations("common");

  const isMobile = useIsMobile();

  const [params, setParams] = useState<FormParams>(DEFAULT_PARAMS);
  const [portfolio, setPortfolio] = useState(DEFAULT_PARAMS.initial_portfolio);
  const [withdrawal, setWithdrawal] = useState(DEFAULT_PARAMS.annual_withdrawal);

  // MC state
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Backtest state
  const [histStartYear, setHistStartYear] = useState(1990);
  const [btResult, setBtResult] = useState<SimBacktestResponse | null>(null);
  const [btLoading, setBtLoading] = useState(false);
  const [btError, setBtError] = useState<string | null>(null);
  const [btLogScale, setBtLogScale] = useState(false);
  const [btWdLogScale, setBtWdLogScale] = useState(false);

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

  const handleRunBacktest = async () => {
    setBtLoading(true);
    setBtError(null);
    try {
      const res = await runSimBacktest({
        initial_portfolio: portfolio,
        annual_withdrawal: withdrawal,
        allocation: params.allocation,
        expense_ratios: params.expense_ratios,
        retirement_years: params.retirement_years,
        data_start_year: params.data_start_year,
        country: params.country,
        withdrawal_strategy: params.withdrawal_strategy,
        dynamic_ceiling: params.dynamic_ceiling,
        dynamic_floor: params.dynamic_floor,
        leverage: params.leverage,
        borrowing_spread: params.borrowing_spread,
        cash_flows: params.cash_flows,
        hist_start_year: histStartYear,
      });
      setBtResult(res);
    } catch (e) {
      setBtError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setBtLoading(false);
    }
  };

  const isPooled = params.country === "ALL";

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
                        color="234, 88, 12" // orange
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
            {isPooled ? (
              <div className="flex items-center justify-center h-64 text-muted-foreground text-center px-4">
                {t("backtestRequiresCountry")}
              </div>
            ) : (
              <>
                {/* 输入区 */}
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
                            t("backtestHeaderPortfolio"),
                            t("backtestHeaderWithdrawal"),
                          ];
                          const rows: (string | number)[][] = [];
                          for (let i = 0; i < n; i++) {
                            rows.push([
                              btResult.year_labels[i],
                              Math.round(btResult.portfolio[i]),
                              Math.round(btResult.withdrawals[i]),
                            ]);
                          }
                          // final year-end portfolio (one extra element)
                          if (btResult.portfolio.length > n) {
                            rows.push([
                              btResult.year_labels[n - 1] + 1,
                              Math.round(btResult.portfolio[n]),
                              "",
                            ]);
                          }
                          downloadCSV("sim_backtest_data", headers, rows);
                        }}
                      />
                    </div>

                    {/* 指标卡片 */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <MetricCard label={t("yearsSimulated")} value={`${btResult.years_simulated}`} />
                      <MetricCard label={t("finalPortfolio")} value={fmt(btResult.final_portfolio)} />
                      <MetricCard label={t("totalConsumption")} value={fmt(btResult.total_consumption)} />
                      <MetricCard
                        label={t("survived")}
                        value={btResult.survived ? t("survived") : t("depleted")}
                      />
                    </div>

                    {/* 资产轨迹 */}
                    <Card>
                      <CardContent className="pt-4">
                        <div className="flex items-center justify-between">
                          <MobileChartTitle title={t("portfolioHistory")} isMobile={isMobile} />
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-6 px-2 text-xs mb-1"
                            onClick={() => setBtLogScale((v) => !v)}
                          >
                            {btLogScale ? tc("linearScale") : tc("logScale")}
                          </Button>
                        </div>
                        <PlotlyChart
                          data={[
                            {
                              x: btResult.year_labels.concat(
                                btResult.portfolio.length > btResult.years_simulated
                                  ? [btResult.year_labels[btResult.years_simulated - 1] + 1]
                                  : []
                              ),
                              y: btResult.portfolio,
                              type: "scatter",
                              mode: "lines",
                              name: t("portfolioHistory"),
                              line: { color: "#2563eb", width: 2 },
                              hovertemplate: "%{x}: %{y:$,.0f}<extra></extra>",
                            },
                          ]}
                          layout={{
                            title: isMobile ? undefined : { text: t("portfolioHistory"), font: { size: 14 } },
                            xaxis: { title: { text: tc("year") } },
                            yaxis: {
                              title: { text: tc("amount") },
                              type: btLogScale ? "log" : "linear",
                              tickformat: btLogScale ? "$~s" : "$,.0f",
                            },
                            margin: { t: isMobile ? 10 : 40, r: 20, b: 40, l: 70 },
                            height: isMobile ? 260 : 380,
                            hovermode: "x unified",
                            showlegend: false,
                          }}
                          config={{ responsive: true, displayModeBar: false }}
                          style={{ width: "100%" }}
                        />
                      </CardContent>
                    </Card>

                    {/* 提取金额轨迹 */}
                    <Card>
                      <CardContent className="pt-4">
                        <div className="flex items-center justify-between">
                          <MobileChartTitle title={t("withdrawalHistory")} isMobile={isMobile} />
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-6 px-2 text-xs mb-1"
                            onClick={() => setBtWdLogScale((v) => !v)}
                          >
                            {btWdLogScale ? tc("linearScale") : tc("logScale")}
                          </Button>
                        </div>
                        <PlotlyChart
                          data={[
                            {
                              x: btResult.year_labels,
                              y: btResult.withdrawals,
                              type: "bar",
                              name: t("withdrawalHistory"),
                              marker: { color: "#ea580c" },
                              hovertemplate: "%{x}: %{y:$,.0f}<extra></extra>",
                            },
                          ]}
                          layout={{
                            title: isMobile ? undefined : { text: t("withdrawalHistory"), font: { size: 14 } },
                            xaxis: { title: { text: tc("year") } },
                            yaxis: {
                              title: { text: tc("amount") },
                              type: btWdLogScale ? "log" : "linear",
                              tickformat: btWdLogScale ? "$~s" : "$,.0f",
                            },
                            margin: { t: isMobile ? 10 : 40, r: 20, b: 40, l: 70 },
                            height: isMobile ? 260 : 380,
                            hovermode: "x unified",
                            showlegend: false,
                          }}
                          config={{ responsive: true, displayModeBar: false }}
                          style={{ width: "100%" }}
                        />
                      </CardContent>
                    </Card>

                    {/* 路径绩效指标 */}
                    {btResult.path_metrics && btResult.path_metrics.length > 0 && (
                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">{t("pathMetrics")}</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <StatsTable rows={btResult.path_metrics} downloadName="backtest_path_metrics" />
                        </CardContent>
                      </Card>
                    )}
                  </>
                )}

                {!btResult && !btLoading && (
                  <div className="flex items-center justify-center h-64 text-muted-foreground">
                    {t("backtestPlaceholder")}
                  </div>
                )}
              </>
            )}
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
