"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
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
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { useIsMobile } from "@/components/fan-chart";
import { runAllocationSweep } from "@/lib/api";
import { downloadCSV } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { DEFAULT_PARAMS } from "@/lib/types";
import type { FormParams, AllocationSweepResponse } from "@/lib/types";

function fmt(n: number): string {
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export default function AllocationPage() {
  const t = useTranslations("allocation");
  const tc = useTranslations("common");
  const isMobile = useIsMobile();

  const [params, setParams] = useState<FormParams>({
    ...DEFAULT_PARAMS,
    num_simulations: 1_000,
  });
  const [portfolio, setPortfolio] = useState(DEFAULT_PARAMS.initial_portfolio);
  const [withdrawal, setWithdrawal] = useState(DEFAULT_PARAMS.annual_withdrawal);
  const [allocStep, setAllocStep] = useState(0.1);
  const [result, setResult] = useState<AllocationSweepResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sortKey, setSortKey] = useState<string>("success_rate");
  const [sortAsc, setSortAsc] = useState(false);

  const STEP_OPTIONS = [
    { value: "0.05", label: t("stepOption5") },
    { value: "0.1", label: t("stepOption10") },
    { value: "0.2", label: t("stepOption20") },
  ];

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runAllocationSweep({
        ...params,
        initial_portfolio: portfolio,
        annual_withdrawal: withdrawal,
        allocation_step: allocStep,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
    }
  };

  const sortedResults = result
    ? [...result.results].sort((a, b) => {
        const va = (a as unknown as Record<string, number | null>)[sortKey];
        const vb = (b as unknown as Record<string, number | null>)[sortKey];
        const na = va ?? Infinity;
        const nb = vb ?? Infinity;
        return sortAsc ? na - nb : nb - na;
      })
    : [];

  const handleSort = (key: string) => {
    if (key === sortKey) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
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

            <Button onClick={handleRun} className="w-full" disabled={loading}>
              {loading ? t("scanning") : t("startScan")}
            </Button>
          </CardContent>
        </Card>
      </aside>

      {/* ── 右侧结果区 ── */}
      <main className="flex-1 space-y-6 relative">
        {loading && <LoadingOverlay />}

        {error && (
          <Card className="border-red-300 bg-red-50">
            <CardContent className="pt-4 text-red-700 text-sm">{error}</CardContent>
          </Card>
        )}

        {result && (
          <>
            {/* 最优配置指标 */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard
                label={t("bestSuccessRate")}
                value={pct(result.best_by_success.success_rate)}
              />
              <MetricCard
                label={t("bestAllocation")}
                value={`${(result.best_by_success.us_stock * 100).toFixed(0)}/${(result.best_by_success.intl_stock * 100).toFixed(0)}/${(result.best_by_success.us_bond * 100).toFixed(0)}`}
                sub={t("allocationSub")}
              />
              <MetricCard
                label={t("medianFinalPortfolio")}
                value={fmt(result.best_by_success.median_final)}
              />
              <MetricCard
                label={t("p10DepletionYear")}
                value={
                  result.best_by_success.p10_depletion_year
                    ? tc("yearN", { n: result.best_by_success.p10_depletion_year })
                    : tc("notDepleted")
                }
              />
            </div>

            {/* 三角热力图 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t("heatmapTitle")}</CardTitle>
              </CardHeader>
              <CardContent>
                <PlotlyChart
                  data={[
                    {
                      type: "scatterternary" as string,
                      mode: "markers",
                      a: result.results.map((r) => r.us_stock * 100),
                      b: result.results.map((r) => r.intl_stock * 100),
                      c: result.results.map((r) => r.us_bond * 100),
                      text: result.results.map(
                        (r) =>
                          `${t("ternaryUSStock").replace(" %", "")}${(r.us_stock * 100).toFixed(0)}% ${t("ternaryIntlStock").replace(" %", "")}${(r.intl_stock * 100).toFixed(0)}% ${t("ternaryUSBond").replace(" %", "")}${(r.us_bond * 100).toFixed(0)}%<br>${tc("successRate")}: ${(r.success_rate * 100).toFixed(1)}%<br>${t("colMedianFinal")}: ${fmt(r.median_final)}`
                      ),
                      hoverinfo: "text",
                      marker: {
                        size: allocStep <= 0.05 ? 8 : allocStep <= 0.1 ? 14 : 20,
                        color: result.results.map((r) => r.success_rate * 100),
                        colorscale: "RdYlGn",
                        cmin: Math.min(...result.results.map((r) => r.success_rate * 100)),
                        cmax: Math.max(...result.results.map((r) => r.success_rate * 100)),
                        colorbar: {
                          title: { text: t("ternaryColorbar") },
                          ticksuffix: "%",
                        },
                        line: { width: 1, color: "rgba(0,0,0,0.2)" },
                      },
                    } as Record<string, unknown>,
                  ]}
                  layout={{
                    ternary: {
                      sum: 100,
                      aaxis: {
                        title: { text: t("ternaryUSStock") },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.1)",
                      },
                      baxis: {
                        title: { text: t("ternaryIntlStock") },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.1)",
                      },
                      caxis: {
                        title: { text: t("ternaryUSBond") },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.1)",
                      },
                    },
                    margin: isMobile ? { t: 20, b: 20, l: 10, r: 10 } : { t: 40, b: 40, l: 60, r: 60 },
                    showlegend: false,
                    height: isMobile ? 350 : 500,
                  }}
                  config={{
                    displayModeBar: isMobile ? false : ("hover" as const),
                    modeBarButtonsToRemove: [
                      "select2d",
                      "lasso2d",
                      "autoScale2d",
                    ],
                    toImageButtonOptions: {
                      format: "png",
                      filename: "allocation_ternary",
                      width: 1200,
                      height: 800,
                    },
                  }}
                  style={{ width: "100%", height: isMobile ? "350px" : "500px" }}
                />
              </CardContent>
            </Card>

            {/* 排序表格 */}
            <Card>
              <CardHeader className="pb-2 flex flex-row items-center justify-between">
                <CardTitle className="text-sm">
                  {t("allResultsTitle", { count: result.results.length })}
                </CardTitle>
                <DownloadButton
                  label={t("downloadCSV")}
                  onClick={() => {
                    const headers = [
                      t("colUSStock"),
                      t("colIntlStock"),
                      t("colUSBond"),
                      t("colSuccessRate"),
                      t("colMedianFinal"),
                      t("colMeanFinal"),
                      t("colP10Depletion"),
                    ];
                    const rows = sortedResults.map((r) => [
                      (r.us_stock * 100).toFixed(0),
                      (r.intl_stock * 100).toFixed(0),
                      (r.us_bond * 100).toFixed(0),
                      (r.success_rate * 100).toFixed(1) + "%",
                      Math.round(r.median_final),
                      Math.round(r.mean_final),
                      r.p10_depletion_year ?? tc("notDepleted"),
                    ]);
                    downloadCSV("allocation_sweep", headers, rows);
                  }}
                />
              </CardHeader>
              <CardContent>
                <div className="max-h-[500px] overflow-auto">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-background border-b">
                      <tr>
                        {[
                          { key: "us_stock", label: t("colUSStock") },
                          { key: "intl_stock", label: t("colIntlStock") },
                          { key: "us_bond", label: t("colUSBond") },
                          { key: "success_rate", label: t("colSuccessRate") },
                          { key: "median_final", label: t("colMedianFinal") },
                          { key: "mean_final", label: t("colMeanFinal") },
                          { key: "p10_depletion_year", label: t("colP10Depletion") },
                        ].map((col) => (
                          <th
                            key={col.key}
                            className="text-left px-2 py-1.5 cursor-pointer hover:bg-accent select-none"
                            onClick={() => handleSort(col.key)}
                          >
                            {col.label}
                            {sortKey === col.key && (
                              <span className="ml-1">{sortAsc ? "↑" : "↓"}</span>
                            )}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sortedResults.map((r, i) => {
                        const isBest =
                          r.us_stock === result.best_by_success.us_stock &&
                          r.intl_stock === result.best_by_success.intl_stock &&
                          r.us_bond === result.best_by_success.us_bond;
                        return (
                          <tr
                            key={i}
                            className={`border-b ${isBest ? "bg-green-50 font-medium" : "hover:bg-accent/50"}`}
                          >
                            <td className="px-2 py-1">
                              {(r.us_stock * 100).toFixed(0)}
                            </td>
                            <td className="px-2 py-1">
                              {(r.intl_stock * 100).toFixed(0)}
                            </td>
                            <td className="px-2 py-1">
                              {(r.us_bond * 100).toFixed(0)}
                            </td>
                            <td className="px-2 py-1">{pct(r.success_rate)}</td>
                            <td className="px-2 py-1">{fmt(r.median_final)}</td>
                            <td className="px-2 py-1">{fmt(r.mean_final)}</td>
                            <td className="px-2 py-1">
                              {r.p10_depletion_year
                                ? tc("yearN", { n: r.p10_depletion_year })
                                : tc("notDepleted")}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
