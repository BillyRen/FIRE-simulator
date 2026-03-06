"use client";

import { useState } from "react";
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
import { StatsTable } from "@/components/stats-table";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { useIsMobile } from "@/components/fan-chart";
import { CHART_COLORS, MARGINS } from "@/lib/chart-theme";
import { runSweep } from "@/lib/api";
import { downloadCSV } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { useSharedParams } from "@/lib/params-context";
import type { SweepResponse } from "@/lib/types";

export default function SensitivityPage() {
  const t = useTranslations("sensitivity");
  const tc = useTranslations("common");
  const isMobile = useIsMobile();

  const {
    params, setParams,
    sensitivityRateMax: rateMax, setSensitivityRateMax: setRateMax,
    sensitivityRateStep: rateStep, setSensitivityRateStep: setRateStep,
    sensitivityMetric: metric, setSensitivityMetric: setMetric,
  } = useSharedParams();
  const [portfolio, setPortfolio] = useState(params.initial_portfolio);
  const [withdrawal, setWithdrawal] = useState(params.annual_withdrawal);
  const [result, setResult] = useState<SweepResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runSweep({
        ...params,
        initial_portfolio: portfolio,
        annual_withdrawal: withdrawal,
        rate_max: rateMax,
        rate_step: rateStep,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
    }
  };

  // 当前选中的指标数据
  const metricValues = result
    ? metric === "success_rate" ? result.success_rates : result.funded_ratios
    : [];
  const metricLabel = metric === "success_rate" ? t("metricSuccessRate") : t("metricFundedRatio");
  const targetRows = result
    ? metric === "success_rate" ? result.target_results : result.target_results_funded
    : [];

  // 计算分析 2 的数据
  const analysis2Data = result
    ? (() => {
        const portfolioNeeded = result.rates
          .filter((r) => r > 0)
          .map((r) => ({
            portfolio: withdrawal / r,
            metricVal: metricValues[result.rates.indexOf(r)],
          }));
        const highSr = portfolioNeeded.filter((d) => d.metricVal >= 0.995);
        const xMax = highSr.length > 0
          ? Math.min(...highSr.map((d) => d.portfolio)) * 2
          : Math.max(...portfolioNeeded.map((d) => d.portfolio));
        return { portfolioNeeded, xMax };
      })()
    : null;

  return (
    <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 p-3 sm:p-6 max-w-[1600px] mx-auto">
      {/* ── 左侧参数 ── */}
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

            <div className="grid grid-cols-2 gap-2">
              <NumberField
                label={t("maxScanRate")}
                value={+(rateMax * 100).toFixed(1)}
                onChange={(v) => setRateMax(v / 100)}
                min={0.1}
                max={50}
                step={0.5}
              />
              <NumberField
                label={t("scanStep")}
                value={+(rateStep * 100).toFixed(2)}
                onChange={(v) => setRateStep(v / 100)}
                min={0.01}
                max={10}
                step={0.05}
              />
            </div>

            <SidebarForm
              params={params}
              onChange={setParams}
              showWithdrawalStrategy={true}
            />

          </CardContent>
          <div className="sticky bottom-0 bg-card px-6 pt-3 pb-4 border-t">
            <Button onClick={handleRun} className="w-full" disabled={loading}>
              {loading ? t("analyzing") : t("runAnalysis")}
            </Button>
          </div>
        </Card>
      </aside>

      {/* ── 右侧结果 ── */}
      <main className="flex-1 space-y-6 min-w-0">
        {error && (
          <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading && <LoadingOverlay message={t("scanLoading")} />}

        {result && !loading && (
          <>
            {/* 指标选择 + 下载按钮 */}
            <div className="flex flex-wrap items-end gap-4">
              <div className="space-y-1">
                <Label className="text-xs">{t("metricLabel")}</Label>
                <Select
                  value={metric}
                  onValueChange={(v) => setMetric(v as "success_rate" | "funded_ratio")}
                >
                  <SelectTrigger className="h-8 text-sm w-[180px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="success_rate">{t("metricSuccessRate")}</SelectItem>
                    <SelectItem value="funded_ratio">{t("metricFundedRatio")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <DownloadButton
                label={t("downloadScanData")}
                onClick={() =>
                  downloadCSV(
                    "sensitivity_scan",
                    [t("scanHeaderRate"), t("scanHeaderSuccess"), t("scanHeaderFunded")],
                    result.rates.map((r, i) => [
                      `${(r * 100).toFixed(2)}%`,
                      `${(result.success_rates[i] * 100).toFixed(1)}%`,
                      `${(result.funded_ratios[i] * 100).toFixed(1)}%`,
                    ])
                  )
                }
              />
            </div>

            {/* 分析 1: 指标 vs 提取率 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  {t("analysis1Title", { amount: portfolio.toLocaleString(), metric: metricLabel })}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <PlotlyChart
                  data={[
                    {
                      x: result.rates.map((r) => r * 100),
                      y: metricValues.map((s) => s * 100),
                      type: "scatter",
                      mode: "lines+markers",
                      marker: { size: 4 },
                      line: { color: CHART_COLORS.primary.hex, width: 2 },
                      name: metricLabel,
                    },
                  ]}
                  layout={{
                    xaxis: { title: { text: t("analysis1XAxis") }, tickfont: { size: isMobile ? 9 : 12 } },
                    yaxis: { title: isMobile ? undefined : { text: `${metricLabel} (%)` }, range: [0, 105], tickfont: { size: isMobile ? 9 : 12 } },
                    height: isMobile ? 280 : 400,
                    margin: MARGINS.default(isMobile),
                  }}
                  config={{
                    displayModeBar: isMobile ? false : ("hover" as const),
                  }}
                />
              </CardContent>
            </Card>

            {/* 目标阈值表格 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  {t("targetTitle", { metric: metricLabel })}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <StatsTable
                  rows={targetRows.map((r) => ({
                    [t("targetThreshold")]: r.target_success,
                    [t("rate")]: r.rate ?? "N/A",
                    [t("annualWithdrawalAmount")]: r.annual_withdrawal ?? "N/A",
                    [t("neededPortfolio")]: r.needed_portfolio ?? "N/A",
                  }))}
                  downloadName="target_summary"
                />
              </CardContent>
            </Card>

            {/* 分析 2: 指标 vs 所需资产 */}
            {analysis2Data && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">
                    {t("analysis2Title", { amount: withdrawal.toLocaleString(), metric: metricLabel })}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <PlotlyChart
                    data={[
                      {
                        x: analysis2Data.portfolioNeeded.map((d) => d.portfolio),
                        y: analysis2Data.portfolioNeeded.map((d) => d.metricVal * 100),
                        type: "scatter",
                        mode: "lines+markers",
                        marker: { size: 4 },
                        line: { color: CHART_COLORS.secondary.hex, width: 2 },
                        name: metricLabel,
                      },
                    ]}
                    layout={{
                      xaxis: {
                        title: { text: t("analysis2XAxis") },
                        tickformat: isMobile ? "$~s" : "$,.0f",
                        range: [0, analysis2Data.xMax],
                        tickfont: { size: isMobile ? 9 : 12 },
                      },
                      yaxis: { title: isMobile ? undefined : { text: `${metricLabel} (%)` }, range: [0, 105], tickfont: { size: isMobile ? 9 : 12 } },
                      height: isMobile ? 280 : 400,
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
