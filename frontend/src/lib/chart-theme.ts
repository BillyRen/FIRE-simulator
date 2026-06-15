/**
 * Central chart theme. Palette B ("refined professional"): deep azure /
 * emerald / slate, slightly desaturated for a financial-dashboard feel.
 * Every chart routes through `PlotlyChart` → `mergeLayout(custom, isDark)`,
 * so this module is the single source of truth for chart styling and the
 * single point where light/dark theming is applied.
 *
 * NOTE: `mergeLayout` only themes the default x/y axes + legend. Custom
 * sub-layouts (ternary axes, colorbars, secondary y-axes, annotations) are
 * NOT auto-themed — use the `themed*` helpers below at those call sites.
 */

export const CHART_COLORS = {
  primary:   { hex: "#2f6bd8", rgb: "47,107,216" },
  secondary: { hex: "#0e9f6e", rgb: "14,159,110" },
  accent:    { hex: "#6d5bd0", rgb: "109,91,208" },
  warning:   { hex: "#d99a3d", rgb: "217,154,61" },
  danger:    { hex: "#d64550", rgb: "214,69,80" },
  neutral:   { hex: "#7b8494", rgb: "123,132,148" },
  orange:    { hex: "#dd6b33", rgb: "221,107,51" },
} as const;

/** Ordered hues for multi-series categorical charts (stacked / grouped bars). */
export const CATEGORICAL: readonly string[] = [
  CHART_COLORS.primary.hex,
  CHART_COLORS.secondary.hex,
  CHART_COLORS.warning.hex,
  CHART_COLORS.accent.hex,
  CHART_COLORS.orange.hex,
  CHART_COLORS.danger.hex,
  CHART_COLORS.neutral.hex,
];

/** Fan-chart band fill opacities: [outer P10–P90, inner P25–P75]. */
export const BAND_OPACITIES = [0.14, 0.3] as const;

/**
 * Sequential colorscale for funded-ratio maps (allocation ternary / Pareto).
 * RdYlBu reversed — low = red (bad), high = blue (good). Colorblind-safer than
 * RdYlGn and pairs with the azure primary.
 */
export const FUNDED_RATIO_COLORSCALE: [number, string][] = [
  [0, "#d73027"],
  [0.25, "#f46d43"],
  [0.5, "#fee090"],
  [0.75, "#74add1"],
  [1, "#4575b4"],
];

/** Allocation marker sizes by grid step (consumed in P3). */
export const MARKER_SIZES = {
  point: (step: number) => (step <= 0.05 ? 8 : step <= 0.1 ? 14 : 20),
  best: (step: number) => (step <= 0.05 ? 14 : step <= 0.1 ? 20 : 26),
} as const;

/** Standard chart heights — replaces the ad-hoc 260/280/300/380/400/450 spread. */
export const CHART_HEIGHTS = {
  sm: { mobile: 260, desktop: 360 },
  md: { mobile: 280, desktop: 400 },
  lg: { mobile: 300, desktop: 450 },
} as const;
export function chartHeight(size: keyof typeof CHART_HEIGHTS, mobile: boolean): number {
  return CHART_HEIGHTS[size][mobile ? "mobile" : "desktop"];
}

const chartFont =
  "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, " +
  "'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";

/* ===== Theme tokens ===== */
interface ChartTokens {
  text: string;
  tick: string;
  title: string;
  grid: string;
  hoverBg: string;
  hoverBorder: string;
  hoverText: string;
  axisLine: string;
}

const LIGHT_TOKENS: ChartTokens = {
  text: "#374151",
  tick: "#9ca3af",
  title: "#6b7280",
  grid: "rgba(0,0,0,0.06)",
  hoverBg: "#ffffff",
  hoverBorder: "#e5e7eb",
  hoverText: "#1f2937",
  axisLine: "rgba(0,0,0,0.15)",
};

// Neutral grays to match the app's chroma-0 dark palette (globals.css .dark).
const DARK_TOKENS: ChartTokens = {
  text: "#d4d4d8",
  tick: "#a1a1aa",
  title: "#a1a1aa",
  grid: "rgba(255,255,255,0.08)",
  hoverBg: "#262626",
  hoverBorder: "#404040",
  hoverText: "#fafafa",
  axisLine: "rgba(255,255,255,0.18)",
};

export function getChartTokens(isDark: boolean): ChartTokens {
  return isDark ? DARK_TOKENS : LIGHT_TOKENS;
}

function buildDefaultLayout(tk: ChartTokens): Record<string, unknown> {
  const axisBase = {
    showline: false,
    zeroline: false,
    automargin: true,
    tickfont: { size: 11, color: tk.tick },
    title: { font: { size: 12, color: tk.title } },
  };
  return {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { family: chartFont, size: 12, color: tk.text },
    xaxis: { ...axisBase, showgrid: false },
    yaxis: { ...axisBase, showgrid: true, gridcolor: tk.grid, gridwidth: 1 },
    hoverlabel: {
      bgcolor: tk.hoverBg,
      bordercolor: tk.hoverBorder,
      font: { size: 12, family: chartFont, color: tk.hoverText },
    },
    legend: { bgcolor: "transparent", borderwidth: 0, font: { size: 11, color: tk.text } },
    hovermode: "x unified",
  };
}

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
    mobile ? { l: 45, r: 10, t: 10, b: 30 } : { l: 70, r: 20, t: 80, b: 40 },
  dualAxis: (mobile: boolean) =>
    mobile ? { l: 45, r: 35, t: 10, b: 30 } : { l: 60, r: 60, t: 10, b: 40 },
  dualAxisWithTitle: (mobile: boolean) =>
    mobile ? { l: 45, r: 35, t: 10, b: 30 } : { l: 70, r: 60, t: 80, b: 40 },
  // Wide left margin for horizontal bar charts with long category labels
  // (scenario / tornado). Replaces the per-page magic margin objects.
  barLabels: (mobile: boolean) =>
    mobile ? { l: 120, r: 40, t: 10, b: 40 } : { l: 180, r: 60, t: 40, b: 50 },
} as const;

/* ===== Themed sub-layout helpers (for custom Plotly layouts) ===== */

/** Ternary diagram axes + background (allocation simplex). */
export function themedTernary(isDark: boolean) {
  const tk = getChartTokens(isDark);
  const axis = {
    linewidth: 1,
    linecolor: tk.axisLine,
    gridcolor: tk.grid,
    tickfont: { color: tk.tick },
    title: { font: { color: tk.title } },
  };
  return {
    bgcolor: "transparent",
    aaxis: { ...axis },
    baxis: { ...axis },
    caxis: { ...axis },
  };
}

/** Colorbar tick/title colors (continuous color maps). */
export function themedColorbar(isDark: boolean) {
  const tk = getChartTokens(isDark);
  return {
    outlinewidth: 0,
    tickfont: { color: tk.tick },
    title: { font: { color: tk.title } },
  };
}

/** Secondary (right) y-axis font colors for dual-axis charts. */
export function themedAxis2(isDark: boolean) {
  const tk = getChartTokens(isDark);
  return {
    tickfont: { size: 11, color: tk.tick },
    title: { font: { size: 12, color: tk.title } },
  };
}

/** Semi-transparent legend background that reads on both themes. */
export function legendBg(isDark: boolean): string {
  return isDark ? "rgba(38,38,38,0.7)" : "rgba(255,255,255,0.7)";
}

/** Default text color for Plotly annotations. */
export function annotationColor(isDark: boolean): string {
  return getChartTokens(isDark).text;
}

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

export function mergeLayout(custom?: any, isDark = false): any {
  return deepMerge(buildDefaultLayout(getChartTokens(isDark)), custom || {});
}

export function mergeConfig(custom?: any): any {
  return deepMerge(defaultConfig, custom || {});
}
/* eslint-enable @typescript-eslint/no-explicit-any */
