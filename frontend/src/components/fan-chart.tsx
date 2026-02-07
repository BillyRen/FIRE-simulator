"use client";

import PlotlyChart from "./plotly-chart";

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
  yTitle = "金额 ($)",
  xLabels,
  extraTraces = [],
  height = 450,
  color = "59, 130, 246", // blue-500 RGB
}: FanChartProps) {
  const n = trajectories["50"]?.length ?? 0;
  const x = xLabels ?? Array.from({ length: n }, (_, i) => i);

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

  // Median line
  if (trajectories["50"]) {
    traces.push({
      x: x as Plotly.Datum[],
      y: trajectories["50"],
      mode: "lines",
      name: "P50 (中位数)",
      line: { color: `rgb(${color})`, width: 2.5 },
      type: "scatter",
    });
  }

  traces.push(...extraTraces);

  return (
    <PlotlyChart
      data={traces}
      layout={{
        title: { text: title, font: { size: 14 } },
        xaxis: { title: xLabels ? undefined : { text: "年" } },
        yaxis: { title: { text: yTitle }, tickformat: "$,.0f" },
        height,
        margin: { l: 80, r: 30, t: 50, b: 50 },
        legend: { x: 0, y: 1.15, orientation: "h" },
        hovermode: "x unified",
      }}
      config={{ responsive: true, displayModeBar: false }}
      style={{ width: "100%" }}
    />
  );
}
