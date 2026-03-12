"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MetricCard } from "@/components/metric-card";
import { FanChart, useIsMobile } from "@/components/fan-chart";
import { PdfExportButton } from "@/components/pdf-export-button";
import { CHART_COLORS } from "@/lib/chart-theme";
import { runSimulation } from "@/lib/api";
import { useSharedParams } from "@/lib/params-context";
import { fmt, pct } from "@/lib/utils";
import { ErrorBanner } from "@/components/error-banner";
import type { SimulationResponse } from "@/lib/types";

function computeScore(result: SimulationResponse): number {
  const srScore = Math.min(result.success_rate * 100, 100);
  const frScore = Math.min(result.funded_ratio * 100, 100);
  const wrScore = result.initial_withdrawal_rate <= 0.04
    ? 100
    : Math.max(0, 100 - (result.initial_withdrawal_rate - 0.04) * 2000);
  return Math.round(srScore * 0.5 + frScore * 0.3 + wrScore * 0.2);
}

function ScoreRing({ score }: { score: number }) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color =
    score >= 80 ? "text-green-500" : score >= 60 ? "text-yellow-500" : "text-red-500";

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width="140" height="140" className="-rotate-90">
        <circle
          cx="70" cy="70" r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="8"
          className="text-muted/20"
        />
        <circle
          cx="70" cy="70" r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className={color}
        />
      </svg>
      <span className="absolute text-3xl font-bold">{score}</span>
    </div>
  );
}

export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const tc = useTranslations("common");
  const tf = useTranslations("fanChart");
  const isMobile = useIsMobile();

  const { params } = useSharedParams();
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runSimulation({
        ...params,
        initial_portfolio: params.initial_portfolio,
        annual_withdrawal: params.annual_withdrawal,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : tc("unknownError"));
    } finally {
      setLoading(false);
    }
  };

  const score = result ? computeScore(result) : null;
  const stockPct = params.allocation.domestic_stock + params.allocation.global_stock;

  const insight = score !== null
    ? score >= 80 ? t("insightGreat")
      : score >= 60 ? t("insightGood")
      : score >= 40 ? t("insightCaution")
      : t("insightDanger")
    : null;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">{t("title")}</h1>
          <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
        </div>
        <div className="flex gap-2">
          {result && <PdfExportButton targetId="dashboard-content" filename="fire-dashboard.pdf" />}
          <Button onClick={handleRun} disabled={loading}>
            {loading ? tc("running") : t("runAnalysis")}
          </Button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      {/* Parameter summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{t("paramSummary")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">{t("initialPortfolio")}</span>
              <p className="font-semibold">{fmt(params.initial_portfolio)}</p>
            </div>
            <div>
              <span className="text-muted-foreground">{t("annualWithdrawal")}</span>
              <p className="font-semibold">{fmt(params.annual_withdrawal)}</p>
            </div>
            <div>
              <span className="text-muted-foreground">{t("retirementYears")}</span>
              <p className="font-semibold">{params.retirement_years}</p>
            </div>
            <div>
              <span className="text-muted-foreground">{t("stockAllocation")}</span>
              <p className="font-semibold">{pct(stockPct)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {result && score !== null && (
        <div id="dashboard-content" className="space-y-6">
          {/* Score + key metrics */}
          <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-6">
            <Card className="flex flex-col items-center justify-center py-6 px-8">
              <ScoreRing score={score} />
              <p className="text-sm font-semibold mt-2">{t("scoreLabel")}</p>
              <p className="text-[10px] text-muted-foreground text-center max-w-[200px]">
                {t("scoreDescription")}
              </p>
            </Card>

            <div className="grid grid-cols-2 md:grid-cols-2 gap-3">
              <MetricCard label={t("successRate")} value={pct(result.success_rate)} />
              <MetricCard label={t("fundedRatio")} value={pct(result.funded_ratio)} />
              <MetricCard label={t("medianFinal")} value={fmt(result.final_median)} />
              <MetricCard label={t("safeWithdrawalRate")} value={pct(result.initial_withdrawal_rate)} />
            </div>
          </div>

          {/* Insights */}
          {insight && (
            <Card className={
              score >= 80 ? "border-green-200 bg-green-50/50 dark:bg-green-950/20"
              : score >= 60 ? "border-yellow-200 bg-yellow-50/50 dark:bg-yellow-950/20"
              : "border-red-200 bg-red-50/50 dark:bg-red-950/20"
            }>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm">{t("keyInsights")}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm">{insight}</p>
              </CardContent>
            </Card>
          )}

          {/* Mini charts */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <CardContent className="pt-4">
                <FanChart
                  trajectories={result.percentile_trajectories}
                  title={t("portfolioMini")}
                  xLabels={Array.from({ length: result.percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i)}
                  xTitle={tf("ageAxis")}
                  height={isMobile ? 220 : 280}
                />
              </CardContent>
            </Card>
            {result.withdrawal_percentile_trajectories && (
              <Card>
                <CardContent className="pt-4">
                  <FanChart
                    trajectories={result.withdrawal_percentile_trajectories}
                    title={t("withdrawalMini")}
                    xLabels={Array.from({ length: result.withdrawal_percentile_trajectories["50"]?.length ?? 0 }, (_, i) => params.retirement_age + i)}
                    xTitle={tf("ageAxis")}
                    color={CHART_COLORS.orange.rgb}
                    height={isMobile ? 220 : 280}
                  />
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
