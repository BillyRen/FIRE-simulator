"use client";

import { useState } from "react";
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
import { FanChart } from "@/components/fan-chart";
import { MetricCard } from "@/components/metric-card";
import { StatsTable } from "@/components/stats-table";
import { LoadingOverlay } from "@/components/loading-overlay";
import PlotlyChart from "@/components/plotly-chart";
import { runGuardrail, runBacktest } from "@/lib/api";
import { downloadCSV, downloadTrajectories } from "@/lib/csv";
import { DownloadButton } from "@/components/download-button";
import { DEFAULT_PARAMS } from "@/lib/types";
import type { FormParams, GuardrailResponse, BacktestResponse } from "@/lib/types";

function fmt(n: number): string {
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export default function GuardrailPage() {
  const [params, setParams] = useState<FormParams>(DEFAULT_PARAMS);
  const [withdrawal, setWithdrawal] = useState(40_000);

  // Guardrail-specific params
  const [targetSuccess, setTargetSuccess] = useState(0.8);
  const [upperGuardrail, setUpperGuardrail] = useState(0.99);
  const [lowerGuardrail, setLowerGuardrail] = useState(0.5);
  const [adjustmentPct, setAdjustmentPct] = useState(0.5);
  const [adjustmentMode, setAdjustmentMode] = useState<"amount" | "success_rate">("amount");
  const [minRemainingYears, setMinRemainingYears] = useState(10);
  const [baselineRate, setBaselineRate] = useState(0.033);

  // Backtest
  const [histStartYear, setHistStartYear] = useState(1990);

  // Results
  const [mcResult, setMcResult] = useState<GuardrailResponse | null>(null);
  const [btResult, setBtResult] = useState<BacktestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [btLoading, setBtLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const guardrailReqBase = () => ({
    annual_withdrawal: withdrawal,
    allocation: params.allocation,
    expense_ratios: params.expense_ratios,
    retirement_years: params.retirement_years,
    min_block: params.min_block,
    max_block: params.max_block,
    num_simulations: params.num_simulations,
    data_start_year: params.data_start_year,
    target_success: targetSuccess,
    upper_guardrail: upperGuardrail,
    lower_guardrail: lowerGuardrail,
    adjustment_pct: adjustmentPct,
    adjustment_mode: adjustmentMode,
    min_remaining_years: minRemainingYears,
    baseline_rate: baselineRate,
    cash_flows: params.cash_flows,
  });

  const handleRunMC = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runGuardrail(guardrailReqBase());
      setMcResult(res);
      setBtResult(null); // 重置回测
    } catch (e) {
      setError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setLoading(false);
    }
  };

  const handleRunBacktest = async () => {
    if (!mcResult) return;
    setBtLoading(true);
    setError(null);
    try {
      const res = await runBacktest({
        ...guardrailReqBase(),
        initial_portfolio: mcResult.initial_portfolio,
        hist_start_year: histStartYear,
      });
      setBtResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setBtLoading(false);
    }
  };

  return (
    <div className="flex flex-col lg:flex-row gap-6 p-6 max-w-[1600px] mx-auto">
      {/* ── 左侧参数面板 ── */}
      <aside className="lg:w-[340px] shrink-0 space-y-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">🛡️ 风险护栏参数</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <NumberField
              label="年提取金额 ($)"
              value={withdrawal}
              onChange={setWithdrawal}
              min={0}
            />

            <SidebarForm
              params={params}
              onChange={setParams}
              showWithdrawalStrategy={false}
            >
              <Separator />
              <div>
                <h3 className="text-sm font-semibold mb-2">🛡️ 护栏设置</h3>
                <div className="grid grid-cols-2 gap-2">
                  <NumberField
                    label="目标成功率 %"
                    value={+(targetSuccess * 100).toFixed(0)}
                    onChange={(v) => setTargetSuccess(v / 100)}
                    min={1}
                    max={99}
                  />
                  <NumberField
                    label="基准提取率 %"
                    value={+(baselineRate * 100).toFixed(1)}
                    onChange={(v) => setBaselineRate(v / 100)}
                    min={0.1}
                    max={50}
                    step={0.1}
                  />
                  <NumberField
                    label="上护栏 %"
                    value={+(upperGuardrail * 100).toFixed(0)}
                    onChange={(v) => setUpperGuardrail(v / 100)}
                    min={1}
                    max={100}
                  />
                  <NumberField
                    label="下护栏 %"
                    value={+(lowerGuardrail * 100).toFixed(0)}
                    onChange={(v) => setLowerGuardrail(v / 100)}
                    min={0}
                    max={99}
                  />
                </div>

                <div className="mt-2 space-y-2">
                  <div>
                    <Label className="text-xs">调整模式</Label>
                    <Select
                      value={adjustmentMode}
                      onValueChange={(v) => setAdjustmentMode(v as "amount" | "success_rate")}
                    >
                      <SelectTrigger className="h-8 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="amount">金额调整百分比</SelectItem>
                        <SelectItem value="success_rate">成功率调整百分比</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <NumberField
                    label="调整百分比 %"
                    value={+(adjustmentPct * 100).toFixed(0)}
                    onChange={(v) => setAdjustmentPct(v / 100)}
                    min={1}
                    max={100}
                    help={
                      adjustmentMode === "amount"
                        ? "对目标金额差距的调整比例"
                        : "对目标成功率差距的调整比例"
                    }
                  />
                  <NumberField
                    label="最少剩余计算年限"
                    value={minRemainingYears}
                    onChange={(v) => setMinRemainingYears(Math.round(v))}
                    min={1}
                    max={30}
                  />
                </div>
              </div>
            </SidebarForm>

            <Button onClick={handleRunMC} className="w-full" disabled={loading}>
              {loading ? "运行中…" : "运行 Guardrail 模拟"}
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

        {loading && <LoadingOverlay message="Guardrail 模拟中…" />}

        {mcResult && !loading && (
          <Tabs defaultValue="mc">
            <TabsList className="mb-4">
              <TabsTrigger value="mc">Monte Carlo 分析</TabsTrigger>
              <TabsTrigger value="backtest">历史回测</TabsTrigger>
            </TabsList>

            {/* ═══ MC Tab ═══ */}
            <TabsContent value="mc" className="space-y-6">
              {/* 下载按钮组 */}
              <div className="flex flex-wrap gap-2">
                <DownloadButton
                  label="下载资产轨迹"
                  onClick={() =>
                    downloadTrajectories("Guardrail_资产轨迹", mcResult.g_percentile_trajectories)
                  }
                />
                <DownloadButton
                  label="下载提取轨迹"
                  onClick={() =>
                    downloadTrajectories("Guardrail_提取轨迹", mcResult.g_withdrawal_percentiles)
                  }
                />
                <DownloadButton
                  label="下载基准轨迹"
                  onClick={() =>
                    downloadTrajectories("基准_资产轨迹", mcResult.b_percentile_trajectories)
                  }
                />
              </div>

              {/* 指标卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <MetricCard
                  label="初始资产"
                  value={fmt(mcResult.initial_portfolio)}
                />
                <MetricCard
                  label="初始提取率"
                  value={pct(mcResult.initial_rate)}
                />
                <MetricCard
                  label="Guardrail 成功率"
                  value={pct(mcResult.g_success_rate)}
                />
                <MetricCard
                  label="基准成功率"
                  value={pct(mcResult.b_success_rate)}
                  sub={`提取率 ${(baselineRate * 100).toFixed(1)}%`}
                />
              </div>

              {/* 资产轨迹对比 */}
              <Card>
                <CardContent className="pt-4">
                  <FanChart
                    trajectories={mcResult.g_percentile_trajectories}
                    title="资产组合轨迹对比"
                    extraTraces={[
                      {
                        y: mcResult.b_percentile_trajectories["50"],
                        mode: "lines",
                        name: "基准 P50",
                        line: { color: "rgb(234,88,12)", width: 2, dash: "dash" },
                        type: "scatter",
                      },
                    ]}
                  />
                </CardContent>
              </Card>

              {/* 提取金额轨迹 */}
              <Card>
                <CardContent className="pt-4">
                  <FanChart
                    trajectories={mcResult.g_withdrawal_percentiles}
                    title="Guardrail 年度提取金额"
                    color="16, 185, 129" // green
                    extraTraces={[
                      {
                        y: Array(
                          mcResult.g_withdrawal_percentiles["50"]?.length ?? 0
                        ).fill(mcResult.baseline_annual_wd),
                        mode: "lines",
                        name: `基准 ${fmt(mcResult.baseline_annual_wd)}/年`,
                        line: { color: "rgb(234,88,12)", width: 2, dash: "dash" },
                        type: "scatter",
                      },
                      {
                        y: Array(
                          mcResult.g_withdrawal_percentiles["50"]?.length ?? 0
                        ).fill(withdrawal),
                        mode: "lines",
                        name: `初始提取 ${fmt(withdrawal)}/年`,
                        line: { color: "gray", width: 1, dash: "dot" },
                        type: "scatter",
                      },
                    ]}
                  />
                </CardContent>
              </Card>

              {/* 指标对比表 */}
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">关键指标对比</CardTitle>
                </CardHeader>
                <CardContent>
                  <StatsTable rows={mcResult.metrics} downloadName="Guardrail_指标对比" />
                </CardContent>
              </Card>
            </TabsContent>

            {/* ═══ 回测 Tab ═══ */}
            <TabsContent value="backtest" className="space-y-6">
              <Card>
                <CardContent className="pt-4 space-y-3">
                  <div className="flex items-end gap-3">
                    <div className="w-28">
                      <NumberField
                        label="回测起始年"
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
                      {btLoading ? "回测中…" : "运行回测"}
                    </Button>
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    初始资产 {fmt(mcResult.initial_portfolio)}（由 MC 阶段计算）
                  </p>
                </CardContent>
              </Card>

              {btLoading && <LoadingOverlay message="历史回测中…" />}

              {btResult && !btLoading && (
                <>
                  {/* 下载按钮 */}
                  <div className="flex flex-wrap gap-2">
                    <DownloadButton
                      label="下载回测数据"
                      onClick={() => {
                        const n = btResult.years_simulated;
                        const headers = [
                          "年份",
                          "Guardrail_资产",
                          "Guardrail_提取额",
                          "Guardrail_成功率",
                          "基准_资产",
                          "基准_提取额",
                        ];
                        const rows: (string | number)[][] = [];
                        for (let i = 0; i < n; i++) {
                          rows.push([
                            btResult.year_labels[i],
                            Math.round(btResult.g_portfolio[i]),
                            Math.round(btResult.g_withdrawals[i]),
                            `${(btResult.g_success_rates[i] * 100).toFixed(1)}%`,
                            Math.round(btResult.b_portfolio[i]),
                            Math.round(btResult.b_withdrawals[i]),
                          ]);
                        }
                        // 追加最后一年末的资产值
                        if (btResult.g_portfolio.length > n) {
                          rows.push([
                            btResult.year_labels[n] ?? btResult.year_labels[n - 1] + 1,
                            Math.round(btResult.g_portfolio[n]),
                            "",
                            "",
                            Math.round(btResult.b_portfolio[n]),
                            "",
                          ]);
                        }
                        downloadCSV("历史回测数据", headers, rows);
                      }}
                    />
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <MetricCard
                      label="Guardrail 总消费"
                      value={fmt(btResult.g_total_consumption)}
                    />
                    <MetricCard
                      label="基准总消费"
                      value={fmt(btResult.b_total_consumption)}
                    />
                    <MetricCard
                      label="Guardrail 最终资产"
                      value={fmt(btResult.g_portfolio[btResult.g_portfolio.length - 1])}
                    />
                    <MetricCard
                      label="基准最终资产"
                      value={fmt(btResult.b_portfolio[btResult.b_portfolio.length - 1])}
                    />
                  </div>

                  {/* 资产轨迹 */}
                  <Card>
                    <CardContent className="pt-4">
                      <PlotlyChart
                        data={[
                          {
                            x: btResult.year_labels,
                            y: btResult.g_portfolio,
                            type: "scatter",
                            mode: "lines",
                            name: "Guardrail",
                            line: { color: "rgb(59,130,246)", width: 2 },
                          },
                          {
                            x: btResult.year_labels,
                            y: btResult.b_portfolio,
                            type: "scatter",
                            mode: "lines",
                            name: "基准",
                            line: {
                              color: "rgb(234,88,12)",
                              width: 2,
                              dash: "dash",
                            },
                          },
                        ]}
                        layout={{
                          title: { text: "历史资产轨迹对比", font: { size: 14 } },
                          xaxis: { title: { text: "年份" } },
                          yaxis: { title: { text: "资产 ($)" }, tickformat: "$,.0f" },
                          height: 400,
                          margin: { l: 80, r: 30, t: 80, b: 50 },
                          legend: { x: 0, y: 1.0, yanchor: "bottom", orientation: "h" },
                          hovermode: "x unified",
                        }}
                        config={{
                          responsive: true,
                          displayModeBar: "hover",
                          modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
                          toImageButtonOptions: { format: "png", height: 800, width: 1200, scale: 2 },
                        }}
                        style={{ width: "100%" }}
                      />
                    </CardContent>
                  </Card>

                  {/* 提取金额 + 成功率 */}
                  <Card>
                    <CardContent className="pt-4">
                      <PlotlyChart
                        data={[
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: btResult.g_withdrawals,
                            type: "scatter",
                            mode: "lines",
                            name: "Guardrail 提取额",
                            line: { color: "rgb(59,130,246)", width: 2 },
                            yaxis: "y",
                          },
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: btResult.b_withdrawals,
                            type: "scatter",
                            mode: "lines",
                            name: "基准提取额",
                            line: {
                              color: "rgb(234,88,12)",
                              width: 2,
                              dash: "dash",
                            },
                            yaxis: "y",
                          },
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: btResult.g_success_rates.map((s) => s * 100),
                            type: "scatter",
                            mode: "lines",
                            name: "成功率 (%)",
                            line: { color: "rgba(100,100,100,0.5)", width: 1 },
                            fill: "tozeroy",
                            fillcolor: "rgba(100,100,100,0.08)",
                            yaxis: "y2",
                          },
                          // 上下护栏参考线
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: Array(btResult.years_simulated).fill(
                              upperGuardrail * 100
                            ),
                            type: "scatter",
                            mode: "lines",
                            name: `上护栏 ${(upperGuardrail * 100).toFixed(0)}%`,
                            line: {
                              color: "green",
                              width: 1,
                              dash: "dot",
                            },
                            yaxis: "y2",
                          },
                          {
                            x: btResult.year_labels.slice(0, btResult.years_simulated),
                            y: Array(btResult.years_simulated).fill(
                              lowerGuardrail * 100
                            ),
                            type: "scatter",
                            mode: "lines",
                            name: `下护栏 ${(lowerGuardrail * 100).toFixed(0)}%`,
                            line: {
                              color: "red",
                              width: 1,
                              dash: "dot",
                            },
                            yaxis: "y2",
                          },
                        ]}
                        layout={{
                          title: {
                            text: "提取金额 & 成功率",
                            font: { size: 14 },
                          },
                          xaxis: { title: { text: "年份" } },
                          yaxis: {
                            title: { text: "提取金额 ($)" },
                            tickformat: "$,.0f",
                            side: "left",
                          },
                          yaxis2: {
                            title: { text: "成功率 (%)" },
                            overlaying: "y",
                            side: "right",
                            range: [0, 105],
                          },
                          height: 450,
                          margin: { l: 80, r: 60, t: 100, b: 50 },
                          legend: { x: 0, y: 1.0, yanchor: "bottom", orientation: "h" },
                          hovermode: "x unified",
                        }}
                        config={{
                          responsive: true,
                          displayModeBar: "hover",
                          modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
                          toImageButtonOptions: { format: "png", height: 800, width: 1200, scale: 2 },
                        }}
                        style={{ width: "100%" }}
                      />
                    </CardContent>
                  </Card>
                </>
              )}

              {!btResult && !btLoading && (
                <div className="flex items-center justify-center h-32 text-muted-foreground">
                  选择起始年后点击「运行回测」
                </div>
              )}
            </TabsContent>
          </Tabs>
        )}

        {!mcResult && !loading && (
          <div className="flex items-center justify-center h-64 text-muted-foreground">
            配置参数后点击「运行 Guardrail 模拟」查看结果
          </div>
        )}
      </main>
    </div>
  );
}
