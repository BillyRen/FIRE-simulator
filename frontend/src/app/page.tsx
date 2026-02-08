"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SidebarForm, NumberField } from "@/components/sidebar-form";
import { FanChart } from "@/components/fan-chart";
import { MetricCard } from "@/components/metric-card";
import { StatsTable } from "@/components/stats-table";
import { LoadingOverlay } from "@/components/loading-overlay";
import { runSimulation } from "@/lib/api";
import { downloadTrajectories } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { DEFAULT_PARAMS } from "@/lib/types";
import type { FormParams, SimulationResponse } from "@/lib/types";

function fmt(n: number): string {
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export default function SimulatorPage() {
  const [params, setParams] = useState<FormParams>(DEFAULT_PARAMS);
  const [portfolio, setPortfolio] = useState(DEFAULT_PARAMS.initial_portfolio);
  const [withdrawal, setWithdrawal] = useState(DEFAULT_PARAMS.annual_withdrawal);
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      setError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col lg:flex-row gap-6 p-6 max-w-[1600px] mx-auto">
      {/* ── 左侧参数面板 ── */}
      <aside className="lg:w-[340px] shrink-0 space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">🔥 退休模拟参数</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              <NumberField
                label="初始资产 ($)"
                value={portfolio}
                onChange={setPortfolio}
                min={0}
              />
              <NumberField
                label="年提取额 ($)"
                value={withdrawal}
                onChange={setWithdrawal}
                min={0}
              />
            </div>

            <SidebarForm params={params} onChange={setParams} />

            <Button onClick={handleRun} className="w-full" disabled={loading}>
              {loading ? "运行中…" : "运行模拟"}
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

        {loading && <LoadingOverlay />}

        {result && !loading && (
          <>
            {/* 下载按钮组 */}
            <div className="flex flex-wrap gap-2">
              <DownloadButton
                label="下载资产轨迹"
                onClick={() =>
                  downloadTrajectories("资产轨迹", result.percentile_trajectories)
                }
              />
              {result.withdrawal_percentile_trajectories && (
                <DownloadButton
                  label="下载提取轨迹"
                  onClick={() =>
                    downloadTrajectories(
                      "提取金额轨迹",
                      result.withdrawal_percentile_trajectories!
                    )
                  }
                />
              )}
            </div>

            {/* 指标卡片 */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard label="成功率" value={pct(result.success_rate)} />
              <MetricCard label="中位数最终资产" value={fmt(result.final_median)} />
              <MetricCard label="平均最终资产" value={fmt(result.final_mean)} />
              <MetricCard
                label="初始提取率"
                value={pct(result.initial_withdrawal_rate)}
              />
            </div>

            {/* 资产轨迹扇形图 */}
            <Card>
              <CardContent className="pt-4">
                <FanChart
                  trajectories={result.percentile_trajectories}
                  title="资产组合轨迹 (通胀调整后)"
                />
              </CardContent>
            </Card>

            {/* 提取金额扇形图 */}
            {result.withdrawal_percentile_trajectories && (
              <Card>
                <CardContent className="pt-4">
                  <FanChart
                    trajectories={result.withdrawal_percentile_trajectories}
                    title="年度提取金额轨迹"
                    color="234, 88, 12" // orange
                  />
                </CardContent>
              </Card>
            )}

            {/* 统计表 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">统计摘要</CardTitle>
              </CardHeader>
              <CardContent>
                <StatsTable rows={result.final_values_summary} downloadName="统计摘要" />
              </CardContent>
            </Card>
          </>
        )}

        {!result && !loading && (
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            配置参数后点击「运行模拟」查看结果
          </div>
        )}
      </main>
    </div>
  );
}
