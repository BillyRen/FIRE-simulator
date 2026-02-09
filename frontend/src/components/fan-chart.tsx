"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import PlotlyChart from "./plotly-chart";

export function useIsMobile(breakpoint = 640) {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < breakpoint);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [breakpoint]);
  return isMobile;
}

export function mobileMargin(isMobile: boolean) {
  return isMobile
    ? { l: 45, r: 10, t: 50, b: 40 }
    : { l: 80, r: 30, t: 80, b: 50 };
}

export function mobileMarginDualAxis(isMobile: boolean) {
  return isMobile
    ? { l: 45, r: 35, t: 50, b: 40 }
    : { l: 80, r: 60, t: 100, b: 50 };
}

interface FanChartProps {
  /** 分位数轨迹 { "10": [...], "25": [...], "50": [...], "75": [...], "90": [...] } */
  trajectories: Record<string, number[]>;
  /** 图表标题 */
  title: string;
  /** Y 轴标签 */
  yTitle?: string;
  /** X 轴标签 */
  xLabels?: (number | string)[];
  /** 可选的额外 traces (如基准线) */
  extraTraces?: Plotly.Data[];
  /** 图表高度 */
  height?: number;
  /** 主色 */
  color?: string;
}

const BAND_PAIRS: [string, string][] = [
  ["10", "90"],
  ["25", "75"],
];
const BAND_OPACITIES = [0.15, 0.3];

export function FanChart({
  trajectories,
  title,
  yTitle,
  xLabels,
  extraTraces = [],
  height = 450,
  color = "59, 130, 246", // blue-500 RGB
}: FanChartProps) {
  const t = useTranslations();
  const isMobile = useIsMobile();
  const n = trajectories["50"]?.length ?? 0;
  const x = xLabels ?? Array.from({ length: n }, (_, i) => i);

  const resolvedYTitle = yTitle ?? t("common.amount");

  const traces: Plotly.Data[] = [];

  // Band fills
  for (let i = 0; i < BAND_PAIRS.length; i++) {
    const [lo, hi] = BAND_PAIRS[i];
    const opacity = BAND_OPACITIES[i];
    if (!trajectories[lo] || !trajectories[hi]) continue;
    traces.push({
      x: [...x, ...[...x].reverse()],
      y: [...trajectories[hi], ...[...trajectories[lo]].reverse()],
      fill: "toself",
      fillcolor: `rgba(${color}, ${opacity})`,
      line: { color: "transparent" },
      showlegend: true,
      name: `P${lo}–P${hi}`,
      hoverinfo: "skip",
      type: "scatter",
    });
  }

  // Percentile traces (ordered high to low so hover tooltip reads P90 > P75 > P50 > P25 > P10)
  const PERCENTILE_ORDER = ["90", "75", "50", "25", "10"];
  for (const p of PERCENTILE_ORDER) {
    if (!trajectories[p]) continue;
    if (p === "50") {
      traces.push({
        x: x as Plotly.Datum[],
        y: trajectories["50"],
        mode: "lines",
        name: t("common.median"),
        line: { color: `rgb(${color})`, width: 2.5 },
        type: "scatter",
        hovertemplate: `P50: %{y:$,.0f}<extra></extra>`,
      });
    } else {
      traces.push({
        x: x as Plotly.Datum[],
        y: trajectories[p],
        mode: "lines",
        line: { width: 0, color: "transparent" },
        name: `P${p}`,
        showlegend: false,
        type: "scatter",
        hovertemplate: `P${p}: %{y:$,.0f}<extra></extra>`,
      });
    }
  }

  traces.push(...extraTraces);

  const chartHeight = isMobile ? 300 : (height ?? 450);

  return (
    <PlotlyChart
      data={traces}
      layout={{
        title: isMobile
          ? { text: title, font: { size: 12 }, y: 0.98, yanchor: "top" as const }
          : { text: title, font: { size: 14 } },
        xaxis: {
          title: xLabels ? undefined : { text: t("fanChart.yearAxis") },
          tickfont: { size: isMobile ? 9 : 12 },
        },
        yaxis: {
          title: isMobile ? undefined : { text: resolvedYTitle },
          tickformat: isMobile ? "$~s" : "$,.0f",
          tickfont: { size: isMobile ? 9 : 12 },
        },
        height: chartHeight,
        margin: isMobile
          ? { l: 45, r: 10, t: 35, b: 60 }
          : { l: 80, r: 30, t: 80, b: 50 },
        legend: isMobile
          ? { x: 0.5, y: -0.25, xanchor: "center", yanchor: "top", orientation: "h", font: { size: 9 } }
          : { x: 0, y: 1.0, yanchor: "bottom", orientation: "h" },
        hovermode: "x unified",
      }}
      config={{
        responsive: true,
        displayModeBar: isMobile ? false : "hover",
        modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] as Plotly.ModeBarDefaultButtons[],
        toImageButtonOptions: { format: "png", height: 800, width: 1200, scale: 2 },
      }}
      style={{ width: "100%" }}
    />
  );
}
