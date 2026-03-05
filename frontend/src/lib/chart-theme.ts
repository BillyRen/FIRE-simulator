export const CHART_COLORS = {
  primary:   { hex: "#3b82f6", rgb: "59,130,246" },
  secondary: { hex: "#10b981", rgb: "16,185,129" },
  accent:    { hex: "#8b5cf6", rgb: "139,92,246" },
  warning:   { hex: "#f59e0b", rgb: "245,158,11" },
  danger:    { hex: "#ef4444", rgb: "239,68,68" },
  neutral:   { hex: "#9ca3af", rgb: "156,163,175" },
  orange:    { hex: "#ea580c", rgb: "234,88,12" },
} as const;

const chartFont =
  "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, " +
  "'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";

const axisBase = {
  showline: false,
  zeroline: false,
  automargin: true,
  tickfont: { size: 11, color: "#9ca3af" },
  title: { font: { size: 12, color: "#6b7280" } },
};

const defaultLayout: Record<string, unknown> = {
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  font: { family: chartFont, size: 12, color: "#374151" },
  xaxis: { ...axisBase, showgrid: false },
  yaxis: { ...axisBase, showgrid: true, gridcolor: "rgba(0,0,0,0.06)", gridwidth: 1 },
  hoverlabel: {
    bgcolor: "white",
    bordercolor: "#e5e7eb",
    font: { size: 12, family: chartFont, color: "#1f2937" },
  },
  legend: { bgcolor: "transparent", borderwidth: 0, font: { size: 11 } },
  hovermode: "x unified",
};

const defaultConfig: Record<string, unknown> = {
  responsive: true,
  displayModeBar: "hover",
  modeBarButtonsToRemove: [
    "lasso2d", "select2d", "autoScale2d",
    "zoomIn2d", "zoomOut2d",
  ],
  toImageButtonOptions: { format: "png", height: 800, width: 1200, scale: 2 },
};

export const MARGINS = {
  default: (mobile: boolean) =>
    mobile ? { l: 45, r: 10, t: 10, b: 30 } : { l: 60, r: 20, t: 10, b: 40 },
  withTitle: (mobile: boolean) =>
    mobile ? { l: 45, r: 10, t: 10, b: 30 } : { l: 70, r: 20, t: 50, b: 40 },
  dualAxis: (mobile: boolean) =>
    mobile ? { l: 45, r: 35, t: 10, b: 30 } : { l: 60, r: 60, t: 10, b: 40 },
  dualAxisWithTitle: (mobile: boolean) =>
    mobile ? { l: 45, r: 35, t: 10, b: 30 } : { l: 70, r: 60, t: 50, b: 40 },
};

/* eslint-disable @typescript-eslint/no-explicit-any */
function deepMerge(base: any, override: any): any {
  const result = { ...base };
  for (const key of Object.keys(override)) {
    const ov = override[key];
    if (ov === undefined) continue;
    const bv = base[key];
    if (
      ov !== null && typeof ov === "object" && !Array.isArray(ov) &&
      bv !== null && typeof bv === "object" && !Array.isArray(bv)
    ) {
      result[key] = deepMerge(bv, ov);
    } else {
      result[key] = ov;
    }
  }
  return result;
}

export function mergeLayout(custom?: any): any {
  return deepMerge(defaultLayout, custom || {});
}

export function mergeConfig(custom?: any): any {
  return deepMerge(defaultConfig, custom || {});
}
/* eslint-enable @typescript-eslint/no-explicit-any */
