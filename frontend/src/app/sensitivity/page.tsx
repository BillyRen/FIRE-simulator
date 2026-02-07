"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SidebarForm, NumberField } from "@/components/sidebar-form";
import { StatsTable } from "@/components/stats-table";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { runSweep } from "@/lib/api";
import { DEFAULT_PARAMS } from "@/lib/types";
import type { FormParams, SweepResponse } from "@/lib/types";

export default function SensitivityPage() {
  const [params, setParams] = useState<FormParams>(DEFAULT_PARAMS);
  const [portfolio, setPortfolio] = useState(DEFAULT_PARAMS.initial_portfolio);
  const [withdrawal, setWithdrawal] = useState(DEFAULT_PARAMS.annual_withdrawal);
  const [rateMax, setRateMax] = useState(0.12);
  const [rateStep, setRateStep] = useState(0.002);
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
      setError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setLoading(false);
    }
  };

  // 计算分析 2 的数据
  const analysis2Data = result
    ? (() => {
        const portfolioNeeded = result.rates
          .filter((r) => r > 0)
          .map((r, i) => ({
            portfolio: withdrawal / r,
            success: result.success_rates[result.rates.indexOf(r)] ?? result.success_rates[i],
          }));
        // 动态 x 轴范围
        const highSr = portfolioNeeded.filter((d) => d.success >= 0.995);
        const xMax = highSr.length > 0
          ? Math.min(...highSr.map((d) => d.portfolio)) * 2
          : Math.max(...portfolioNeeded.map((d) => d.portfolio));
        return { portfolioNeeded, xMax };
      })()
    : null;

  return (
    <div className="flex flex-col lg:flex-row gap-6 p-6 max-w-[1600px] mx-auto">
      {/* ── 左侧参数 ── */}
      <aside className="lg:w-[340px] shrink-0 space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">📈 敏感性分析参数</CardTitle>
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

            <div className="grid grid-cols-2 gap-2">
              <NumberField
                label="最大扫描提取率 %"
                value={+(rateMax * 100).toFixed(1)}
                onChange={(v) => setRateMax(v / 100)}
                min={0.1}
                max={50}
                step={0.5}
              />
              <NumberField
                label="扫描步长 %"
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

            <Button onClick={handleRun} className="w-full" disabled={loading}>
              {loading ? "分析中…" : "运行分析"}
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

        {loading && <LoadingOverlay message="敏感性扫描中…" />}

        {result && !loading && (
          <>
            {/* 分析 1: 成功率 vs 提取率 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  分析 1: 成功率 vs 提取率 (资产 ${portfolio.toLocaleString()})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <PlotlyChart
                  data={[
                    {
                      x: result.rates.map((r) => r * 100),
                      y: result.success_rates.map((s) => s * 100),
                      type: "scatter",
                      mode: "lines+markers",
                      marker: { size: 4 },
                      line: { color: "rgb(59,130,246)", width: 2 },
                      name: "成功率",
                    },
                  ]}
                  layout={{
                      xaxis: { title: { text: "年度提取率 (%)" } },
                      yaxis: { title: { text: "成功率 (%)" }, range: [0, 105] },
                    height: 400,
                    margin: { l: 60, r: 30, t: 30, b: 50 },
                    hovermode: "x unified",
                  }}
                  config={{ responsive: true, displayModeBar: false }}
                  style={{ width: "100%" }}
                />
              </CardContent>
            </Card>

            {/* 目标成功率表格 */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  各目标成功率对应的提取率和金额
                </CardTitle>
              </CardHeader>
              <CardContent>
                <StatsTable
                  rows={result.target_results.map((r) => ({
                    "目标成功率": r.target_success,
                    "提取率": r.rate ?? "N/A",
                    "年提取额": r.annual_withdrawal ?? "N/A",
                    "所需资产": r.needed_portfolio ?? "N/A",
                  }))}
                />
              </CardContent>
            </Card>

            {/* 分析 2: 成功率 vs 所需资产 */}
            {analysis2Data && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">
                    分析 2: 成功率 vs 所需初始资产 (年提取 ${withdrawal.toLocaleString()})
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <PlotlyChart
                    data={[
                      {
                        x: analysis2Data.portfolioNeeded.map((d) => d.portfolio),
                        y: analysis2Data.portfolioNeeded.map((d) => d.success * 100),
                        type: "scatter",
                        mode: "lines+markers",
                        marker: { size: 4 },
                        line: { color: "rgb(16,185,129)", width: 2 },
                        name: "成功率",
                      },
                    ]}
                    layout={{
                      xaxis: {
                        title: { text: "初始资产 ($)" },
                        tickformat: "$,.0f",
                        range: [0, analysis2Data.xMax],
                      },
                      yaxis: { title: { text: "成功率 (%)" }, range: [0, 105] },
                      height: 400,
                      margin: { l: 60, r: 30, t: 30, b: 50 },
                      hovermode: "x unified",
                    }}
                    config={{ responsive: true, displayModeBar: false }}
                    style={{ width: "100%" }}
                  />
                </CardContent>
              </Card>
            )}
          </>
        )}

        {!result && !loading && (
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            配置参数后点击「运行分析」查看结果
          </div>
        )}
      </main>
    </div>
  );
}
