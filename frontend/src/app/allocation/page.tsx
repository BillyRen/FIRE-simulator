"use client";

import { useState } from "react";
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
import { StatsTable } from "@/components/stats-table";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
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

const STEP_OPTIONS = [
  { value: "0.05", label: "5%（约 231 种组合）" },
  { value: "0.1", label: "10%（约 66 种组合）" },
  { value: "0.2", label: "20%（约 21 种组合）" },
];

export default function AllocationPage() {
  const [params, setParams] = useState<FormParams>(DEFAULT_PARAMS);
  const [portfolio, setPortfolio] = useState(DEFAULT_PARAMS.initial_portfolio);
  const [withdrawal, setWithdrawal] = useState(DEFAULT_PARAMS.annual_withdrawal);
  const [allocStep, setAllocStep] = useState(0.1);
  const [result, setResult] = useState<AllocationSweepResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 排序
  const [sortKey, setSortKey] = useState<string>("success_rate");
  const [sortAsc, setSortAsc] = useState(false);

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
      setError(e instanceof Error ? e.message : "未知错误");
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
    <div className="flex flex-col lg:flex-row gap-6 p-6 max-w-[1600px] mx-auto">
      {/* ── 左侧参数面板 ── */}
      <aside className="lg:w-[340px] shrink-0 space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">🎯 资产配置优化</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <NumberField
              label="初始资产 ($)"
              value={portfolio}
              onChange={setPortfolio}
              min={1}
              step={10000}
            />
            <NumberField
              label="年提取金额 ($)"
              value={withdrawal}
              onChange={setWithdrawal}
              min={0}
              step={1000}
            />

            <div>
              <Label className="text-xs">扫描步长</Label>
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
              {loading ? "扫描中..." : "开始扫描"}
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
                label="最优成功率"
                value={pct(result.best_by_success.success_rate)}
              />
              <MetricCard
                label="最优配置"
                value={`${(result.best_by_success.us_stock * 100).toFixed(0)}/${(result.best_by_success.intl_stock * 100).toFixed(0)}/${(result.best_by_success.us_bond * 100).toFixed(0)}`}
                sub="美股/国际股/美债"
              />
              <MetricCard
                label="中位数最终资产"
                value={fmt(result.best_by_success.median_final)}
              />
              <MetricCard
                label="P10 耗尽年"
                value={
                  result.best_by_success.p10_depletion_year
                    ? `第 ${result.best_by_success.p10_depletion_year} 年`
                    : "未耗尽"
                }
              />
            </div>

            {/* 三角热力图 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">资产配置 — 成功率热力图</CardTitle>
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
                          `美股${(r.us_stock * 100).toFixed(0)}% 国际股${(r.intl_stock * 100).toFixed(0)}% 美债${(r.us_bond * 100).toFixed(0)}%<br>成功率: ${(r.success_rate * 100).toFixed(1)}%<br>中位数终值: ${fmt(r.median_final)}`
                      ),
                      hoverinfo: "text",
                      marker: {
                        size: allocStep <= 0.05 ? 8 : allocStep <= 0.1 ? 14 : 20,
                        color: result.results.map((r) => r.success_rate * 100),
                        colorscale: "RdYlGn",
                        cmin: Math.min(...result.results.map((r) => r.success_rate * 100)),
                        cmax: Math.max(...result.results.map((r) => r.success_rate * 100)),
                        colorbar: {
                          title: { text: "成功率 (%)" },
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
                        title: { text: "美股 %" },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.1)",
                      },
                      baxis: {
                        title: { text: "国际股 %" },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.1)",
                      },
                      caxis: {
                        title: { text: "美债 %" },
                        min: 0,
                        linewidth: 1,
                        gridcolor: "rgba(0,0,0,0.1)",
                      },
                    },
                    margin: { t: 40, b: 40, l: 60, r: 60 },
                    showlegend: false,
                    height: 500,
                  }}
                  config={{
                    displayModeBar: "hover" as const,
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
                  style={{ width: "100%", height: "500px" }}
                />
              </CardContent>
            </Card>

            {/* 排序表格 */}
            <Card>
              <CardHeader className="pb-2 flex flex-row items-center justify-between">
                <CardTitle className="text-sm">
                  全部配置结果（{result.results.length} 种）
                </CardTitle>
                <DownloadButton
                  label="下载 CSV"
                  onClick={() => {
                    const headers = [
                      "美股%",
                      "国际股%",
                      "美债%",
                      "成功率",
                      "中位数终值",
                      "均值终值",
                      "P10耗尽年",
                    ];
                    const rows = sortedResults.map((r) => [
                      (r.us_stock * 100).toFixed(0),
                      (r.intl_stock * 100).toFixed(0),
                      (r.us_bond * 100).toFixed(0),
                      (r.success_rate * 100).toFixed(1) + "%",
                      Math.round(r.median_final),
                      Math.round(r.mean_final),
                      r.p10_depletion_year ?? "未耗尽",
                    ]);
                    downloadCSV("allocation_sweep.csv", headers, rows);
                  }}
                />
              </CardHeader>
              <CardContent>
                <div className="max-h-[500px] overflow-auto">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-background border-b">
                      <tr>
                        {[
                          { key: "us_stock", label: "美股 %" },
                          { key: "intl_stock", label: "国际股 %" },
                          { key: "us_bond", label: "美债 %" },
                          { key: "success_rate", label: "成功率" },
                          { key: "median_final", label: "中位数终值" },
                          { key: "mean_final", label: "均值终值" },
                          { key: "p10_depletion_year", label: "P10 耗尽年" },
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
                                ? `第 ${r.p10_depletion_year} 年`
                                : "未耗尽"}
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
