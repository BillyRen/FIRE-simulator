"use client";

import { usePersistedState } from "@/lib/use-persisted-state";
import { useTranslations } from "next-intl";
import { useApiCall } from "@/lib/use-api-call";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { SidebarForm, NumberField } from "@/components/sidebar-form";
import { MetricCard } from "@/components/metric-card";
import { ProgressOverlay } from "@/components/progress-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { useIsMobile } from "@/lib/use-is-mobile";
import { runAllocationSweep } from "@/lib/api";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import type { AllocationResult } from "@/lib/types";
import { useSharedParams } from "@/lib/params-context";
import { fmt, pct } from "@/lib/utils";

export default function AllocationPage() {
  const t = useTranslations("allocation");
  const tc = useTranslations("common");
  const isMobile = useIsMobile();

  const {
    params, setParams,
    allocationAllocStep: allocStep, setAllocationAllocStep: setAllocStep,
    getSimCount,
  } = useSharedParams();
  const [portfolio, setPortfolio] = usePersistedState("fire:allocation:portfolio", params.initial_portfolio);
  const [withdrawal, setWithdrawal] = usePersistedState("fire:allocation:withdrawal", params.annual_withdrawal);
  const { data: result, loading, error, progress, run: handleRun } = useApiCall(runAllocationSweep);


  const STEP_OPTIONS = [
    { value: "0.05", label: t("stepOption5") },
    { value: "0.1", label: t("stepOption10") },
    { value: "0.2", label: t("stepOption20") },
  ];

  const allocPct = (v: number) => (v * 100).toFixed(0);
  const allocColumns: DataTableColumn<AllocationResult>[] = [
    { key: "domestic_stock", header: t("colDomStock"), align: "right", sortable: true,
      sortValue: (r) => r.domestic_stock, csvValue: (r) => allocPct(r.domestic_stock), render: (r) => allocPct(r.domestic_stock) },
    { key: "global_stock", header: t("colGlobalStock"), align: "right", sortable: true,
      sortValue: (r) => r.global_stock, csvValue: (r) => allocPct(r.global_stock), render: (r) => allocPct(r.global_stock) },
    { key: "domestic_bond", header: t("colDomBond"), align: "right", sortable: true,
      sortValue: (r) => r.domestic_bond, csvValue: (r) => allocPct(r.domestic_bond), render: (r) => allocPct(r.domestic_bond) },
    { key: "funded_ratio", header: t("colFundedRatio"), align: "right", sortable: true,
      sortValue: (r) => r.funded_ratio, csvValue: (r) => pct(r.funded_ratio),
      render: (r) => <span className="font-medium">{pct(r.funded_ratio)}</span> },
    { key: "success_rate", header: t("colSuccessRate"), align: "right", sortable: true,
      sortValue: (r) => r.success_rate, csvValue: (r) => pct(r.success_rate), render: (r) => pct(r.success_rate) },
    { key: "cvar_10", header: t("colCvar10"), align: "right", sortable: true,
      sortValue: (r) => r.cvar_10, csvValue: (r) => String(Math.round(r.cvar_10)), render: (r) => fmt(r.cvar_10) },
    { key: "median_final", header: t("colMedianFinal"), align: "right", sortable: true,
      sortValue: (r) => r.median_final, csvValue: (r) => String(Math.round(r.median_final)), render: (r) => fmt(r.median_final) },
    { key: "p90_final", header: t("colP90Final"), align: "right", sortable: true,
      sortValue: (r) => r.p90_final, csvValue: (r) => String(Math.round(r.p90_final)), render: (r) => fmt(r.p90_final) },
    { key: "mean_final", header: t("colMeanFinal"), align: "right", sortable: true,
      sortValue: (r) => r.mean_final, csvValue: (r) => String(Math.round(r.mean_final)), render: (r) => fmt(r.mean_final) },
    { key: "p10_depletion_year", header: t("colP10Depletion"), align: "right", sortable: true,
      // null = never depleted = best outcome → sort as +Infinity so it leads on
      // descending (not via DataTable's default null-last, which means "missing").
      sortValue: (r) => r.p10_depletion_year ?? Infinity,
      csvValue: (r) => (r.p10_depletion_year ? String(r.p10_depletion_year) : tc("notDepleted")),
      render: (r) => (r.p10_depletion_year ? tc("yearN", { n: r.p10_depletion_year }) : tc("notDepleted")) },
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
            <NumberField
              label={t("initialPortfolio")}
              value={portfolio}
              onChange={setPortfolio}
              min={1}
              step={10000}
            />
            <NumberField
              label={t("annualWithdrawal")}
              value={withdrawal}
              onChange={setWithdrawal}
              min={0}
              step={1000}
            />

            <div>
              <Label className="text-xs">{t("scanStep")}</Label>
              <Select
                value={String(allocStep)}
                onValueChange={(v) => setAllocStep(parseFloat(v))}
              >
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STEP_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <SidebarForm
              params={params}
              onChange={setParams}
              showAllocation={false}
              showWithdrawalStrategy={true}
            />

          </CardContent>
          <div className="sticky bottom-0 bg-card px-6 pt-3 pb-4 border-t">
            <Button onClick={() => handleRun({
              ...params,
              withdrawal_strategy: params.withdrawal_strategy === "cape" ? "fixed" : params.withdrawal_strategy,
              num_simulations: getSimCount("allocation"),
              initial_portfolio: portfolio,
              annual_withdrawal: withdrawal,
              allocation_step: allocStep,
            })} className="w-full" disabled={loading}>
              {loading ? t("scanning") : t("startScan")}
            </Button>
          </div>
        </Card>
      </aside>

      {/* ── 右侧结果区 ── */}
      <main className="flex-1 space-y-6 relative">
        {loading && <ProgressOverlay progress={progress} />}

        {error && (
          <Card className="border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/30">
            <CardContent className="pt-4 text-red-700 dark:text-red-300 text-sm">{error}</CardContent>
          </Card>
        )}

        {result && (
          <>
            {/* 最优配置指标 */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <MetricCard
                label={t("bestFundedRatio")}
                value={pct(result.best.funded_ratio)}
              />
              <MetricCard
                label={t("bestAllocation")}
                value={`${(result.best.domestic_stock * 100).toFixed(0)}/${(result.best.global_stock * 100).toFixed(0)}/${(result.best.domestic_bond * 100).toFixed(0)}`}
                sub={t("allocationSub")}
              />
              <MetricCard
                label={t("bestSuccessRate")}
                value={pct(result.best.success_rate)}
              />
              <MetricCard
                label={t("medianFinalPortfolio")}
                value={fmt(result.best.median_final)}
              />
              <MetricCard
                label={t("colCvar10")}
                value={fmt(result.best.cvar_10)}
              />
              <MetricCard
                label={t("nearOptimalZone")}
                value={`${result.near_optimal_count} / ${result.results.length}`}
                sub={t("nearOptimalDesc", { pct: `±${(result.near_optimal_threshold * 100).toFixed(0)}%` })}
                tooltip={t("nearOptimalTooltip")}
              />
            </div>

            {/* 三角热力图 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t("heatmapTitle")}</CardTitle>
                <p className="text-xs text-muted-foreground">{t("heatmapHint")}</p>
              </CardHeader>
              <CardContent>
                <PlotlyChart
                  data={[
                    {
                      type: "scatterternary" as string,
                      mode: "markers",
                      name: t("legendRegular"),
                      a: result.results.map((r) => r.domestic_stock * 100),
                      b: result.results.map((r) => r.global_stock * 100),
                      c: result.results.map((r) => r.domestic_bond * 100),
                      text: result.results.map(
                        (r) =>
                          `${t("ternaryDomStock").replace(" %", "")}${(r.domestic_stock * 100).toFixed(0)}% ${t("ternaryGlobalStock").replace(" %", "")}${(r.global_stock * 100).toFixed(0)}% ${t("ternaryDomBond").replace(" %", "")}${(r.domestic_bond * 100).toFixed(0)}%<br>${t("colFundedRatio")}: ${(r.funded_ratio * 100).toFixed(1)}%<br>${tc("successRate")}: ${(r.success_rate * 100).toFixed(1)}%<br>${t("colMedianFinal")}: ${fmt(r.median_final)}`
                      ),
                      hoverinfo: "text",
                      marker: {
                        size: allocStep <= 0.05 ? 8 : allocStep <= 0.1 ? 14 : 20,
                        color: result.results.map((r) => r.funded_ratio * 100),
                        colorscale: "RdYlGn",
                        cmin: Math.min(...result.results.map((r) => r.funded_ratio * 100)),
                        cmax: Math.max(...result.results.map((r) => r.funded_ratio * 100)),
                        colorbar: {
                          title: { text: t("ternaryColorbar") },
                          ticksuffix: "%",
                        },
                        line: {
                          width: result.results.map((r) => r.is_near_optimal ? 3 : 1),
                          color: result.results.map((r) => r.is_near_optimal ? "#F59E0B" : "rgba(0,0,0,0.2)"),
                        },
                      },
                      showlegend: false,
                    } as Record<string, unknown>,
                    {
                      type: "scatterternary" as string,
                      mode: "markers",
                      name: t("legendBest"),
                      a: [result.best.domestic_stock * 100],
                      b: [result.best.global_stock * 100],
                      c: [result.best.domestic_bond * 100],
                      text: [`${t("legendBest")}<br>${t("ternaryDomStock").replace(" %", "")}${(result.best.domestic_stock * 100).toFixed(0)}% ${t("ternaryGlobalStock").replace(" %", "")}${(result.best.global_stock * 100).toFixed(0)}% ${t("ternaryDomBond").replace(" %", "")}${(result.best.domestic_bond * 100).toFixed(0)}%<br>${t("colFundedRatio")}: ${(result.best.funded_ratio * 100).toFixed(1)}%`],
                      hoverinfo: "text",
                      marker: {
                        size: allocStep <= 0.05 ? 14 : allocStep <= 0.1 ? 20 : 26,
                        color: "#EF4444",
                        symbol: "star",
                        line: { width: 2, color: "#991B1B" },
                      },
                      showlegend: true,
                    } as Record<string, unknown>,
                  ]}
                  layout={{
                    ternary: {
                      sum: 100,
                      aaxis: {
                        title: { text: t("ternaryDomStock") },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.08)",
                      },
                      baxis: {
                        title: { text: t("ternaryGlobalStock") },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.08)",
                      },
                      caxis: {
                        title: { text: t("ternaryDomBond") },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.08)",
                      },
                    },
                    margin: isMobile ? { t: 20, b: 20, l: 10, r: 10 } : { t: 40, b: 40, l: 60, r: 60 },
                    showlegend: true,
                    legend: { x: 0.02, y: 0.98, bgcolor: "rgba(255,255,255,0.7)" },
                    height: isMobile ? 350 : 500,
                  }}
                  config={{
                    displayModeBar: isMobile ? false : ("hover" as const),
                    toImageButtonOptions: {
                      format: "png",
                      filename: "allocation_ternary",
                      width: 1200,
                      height: 800,
                    },
                  }}
                  style={{ height: isMobile ? "350px" : "500px" }}
                />
              </CardContent>
            </Card>

            {/* Pareto 散点图 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t("paretoChartTitle")}</CardTitle>
                <p className="text-xs text-muted-foreground">{t("paretoHint")}</p>
              </CardHeader>
              <CardContent>
                {(() => {
                  const regular = result.results.filter((r) => !r.is_near_optimal && !r.is_pareto);
                  const nearOpt = result.results.filter((r) => r.is_near_optimal && !r.is_pareto);
                  const hoverText = (r: typeof result.best) =>
                    `${(r.domestic_stock * 100).toFixed(0)}/${(r.global_stock * 100).toFixed(0)}/${(r.domestic_bond * 100).toFixed(0)}<br>${t("colFundedRatio")}: ${(r.funded_ratio * 100).toFixed(1)}%<br>${t("colMedianFinal")}: ${fmt(r.median_final)}`;
                  return (
                    <PlotlyChart
                      data={[
                        {
                          type: "scatter",
                          mode: "markers",
                          name: t("legendRegular"),
                          x: regular.map((r) => r.funded_ratio * 100),
                          y: regular.map((r) => r.median_final),
                          text: regular.map(hoverText),
                          hoverinfo: "text",
                          marker: { size: 7, color: "#D1D5DB", opacity: 0.6 },
                        },
                        {
                          type: "scatter",
                          mode: "markers",
                          name: t("legendNearOptimal"),
                          x: nearOpt.map((r) => r.funded_ratio * 100),
                          y: nearOpt.map((r) => r.median_final),
                          text: nearOpt.map(hoverText),
                          hoverinfo: "text",
                          marker: { size: 9, color: "#FBBF24", line: { width: 2, color: "#F59E0B" } },
                        },
                        {
                          type: "scatter",
                          mode: "lines+markers",
                          name: t("legendPareto"),
                          x: result.pareto_frontier.map((r) => r.funded_ratio * 100),
                          y: result.pareto_frontier.map((r) => r.median_final),
                          text: result.pareto_frontier.map(hoverText),
                          hoverinfo: "text",
                          marker: { size: 10, color: "#3B82F6", symbol: "diamond" },
                          line: { color: "#3B82F6", width: 2, dash: "dot" },
                        },
                        {
                          type: "scatter",
                          mode: "markers",
                          name: t("legendBest"),
                          x: [result.best.funded_ratio * 100],
                          y: [result.best.median_final],
                          text: [hoverText(result.best)],
                          hoverinfo: "text",
                          marker: { size: 14, color: "#EF4444", symbol: "star", line: { width: 2, color: "#991B1B" } },
                        },
                      ]}
                      layout={{
                        // Pin axis types: both are continuous numeric quantities
                        // (coverage % and median final $). Leaving them to Plotly's
                        // autotype risks degrading into a category axis with unsorted,
                        // full-precision tick labels when the data sample is unusual.
                        xaxis: { type: "linear", title: { text: t("paretoAxisFR") } },
                        yaxis: { type: "linear", title: { text: t("paretoAxisMedian") } },
                        margin: isMobile ? { t: 20, b: 50, l: 60, r: 20 } : { t: 30, b: 50, l: 80, r: 30 },
                        showlegend: true,
                        legend: { x: 0.02, y: 0.98, bgcolor: "rgba(255,255,255,0.7)" },
                        height: isMobile ? 300 : 400,
                      }}
                      config={{
                        displayModeBar: isMobile ? false : ("hover" as const),
                        toImageButtonOptions: {
                          format: "png",
                          filename: "allocation_pareto",
                          width: 1200,
                          height: 800,
                        },
                      }}
                      style={{ height: isMobile ? "300px" : "400px" }}
                    />
                  );
                })()}
              </CardContent>
            </Card>

            {/* 排序表格 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  {t("allResultsTitle", { count: result.results.length })}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <DataTable
                  columns={allocColumns}
                  rows={result.results}
                  getRowKey={(_r, i) => i}
                  defaultSort={{ key: "funded_ratio", dir: -1 }}
                  downloadName="allocation_sweep"
                  maxHeight={500}
                  rowClassName={(r) =>
                    r.domestic_stock === result.best.domestic_stock &&
                    r.global_stock === result.best.global_stock &&
                    r.domestic_bond === result.best.domestic_bond
                      ? "bg-emerald-500/10 font-medium"
                      : r.is_near_optimal
                        ? "bg-amber-500/10"
                        : ""
                  }
                />
              </CardContent>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
