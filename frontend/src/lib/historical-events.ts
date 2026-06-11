import type { HistoricalEvent } from "./types";

interface CategoryStyle {
  solid: string;
  line: string;
  band: string;
}

const CATEGORY_STYLES: Record<string, CategoryStyle> = {
  crisis: { solid: "#dc2626", line: "rgba(220,38,38,0.40)", band: "rgba(220,38,38,0.06)" },
  war: { solid: "#6b7280", line: "rgba(107,114,128,0.40)", band: "rgba(107,114,128,0.06)" },
  bubble: { solid: "#ea580c", line: "rgba(234,88,12,0.40)", band: "rgba(234,88,12,0.06)" },
  policy: { solid: "#2563eb", line: "rgba(37,99,235,0.40)", band: "rgba(37,99,235,0.06)" },
};

const FALLBACK_STYLE: CategoryStyle = {
  solid: "#6b7280",
  line: "rgba(107,114,128,0.40)",
  band: "rgba(107,114,128,0.06)",
};

export function filterEvents(
  events: HistoricalEvent[],
  country: string,
  startYear: number,
  endYear: number,
): HistoricalEvent[] {
  return events.filter((e) => {
    const countryMatch =
      country === "ALL"
        ? e.countries.includes("ALL")
        : e.countries.includes("ALL") || e.countries.includes(country);
    const yearMatch = e.year <= endYear && (e.year_end ?? e.year) >= startYear;
    return countryMatch && yearMatch;
  });
}

export interface EventLegendItem {
  num: number;
  label: string;
  yearText: string;
  color: string;
  category: HistoricalEvent["category"];
}

export interface EventOverlay {
  shapes: Partial<Plotly.Shape>[];
  /** Numbered marker trace (empty array when no events). Append to chart data. */
  traces: Plotly.Data[];
  /** Number -> label mapping for rendering an <EventLegend> below the chart. */
  legendItems: EventLegendItem[];
}

/**
 * Hidden overlay axis for event markers. Pins markers at a fixed relative
 * height so they stay put under the log-scale toggle and zooming.
 * Assign to `layout.yaxis2` whenever the overlay traces are used.
 */
export const EVENT_MARKER_AXIS = {
  overlaying: "y" as const,
  range: [0, 1],
  visible: false,
  fixedrange: true,
};

const MARKER_Y = 0.96;
const MARKER_Y_STEP = 0.07; // vertical stagger for same-year events

export function buildEventOverlay(
  events: HistoricalEvent[],
  locale: string,
  xMin: number,
  xMax: number,
): EventOverlay {
  const sorted = [...events].sort((a, b) => a.year - b.year);
  const shapes: Partial<Plotly.Shape>[] = [];
  const legendItems: EventLegendItem[] = [];
  const xs: number[] = [];
  const ys: number[] = [];
  const colors: string[] = [];
  const texts: string[] = [];
  const hovers: string[] = [];
  const perYearCount = new Map<number, number>();

  sorted.forEach((e, i) => {
    const style = CATEGORY_STYLES[e.category] ?? FALLBACK_STYLE;
    const label = locale === "zh" ? e.label_zh : e.label_en;
    const isRange = e.year_end != null && e.year_end > e.year;
    // Clamp to the visible year range: events may start before the path begins.
    const markerYear = Math.max(e.year, xMin);

    if (isRange) {
      shapes.push({
        type: "rect",
        x0: markerYear,
        x1: Math.min(e.year_end as number, xMax),
        yref: "paper",
        y0: 0,
        y1: 1,
        fillcolor: style.band,
        line: { width: 0 },
        layer: "below",
      });
    }
    if (e.year >= xMin) {
      shapes.push({
        type: "line",
        x0: e.year,
        x1: e.year,
        yref: "paper",
        y0: 0,
        y1: 1,
        line: { color: style.line, width: 1, dash: "dot" },
        layer: "below",
      });
    }

    const stack = perYearCount.get(markerYear) ?? 0;
    perYearCount.set(markerYear, stack + 1);

    const yearText = isRange ? `${e.year}–${e.year_end}` : `${e.year}`;
    xs.push(markerYear);
    ys.push(MARKER_Y - stack * MARKER_Y_STEP);
    colors.push(style.solid);
    texts.push(String(i + 1));
    hovers.push(`${label} (${yearText})`);
    legendItems.push({ num: i + 1, label, yearText, color: style.solid, category: e.category });
  });

  const traces: Plotly.Data[] =
    sorted.length === 0
      ? []
      : [
          {
            x: xs,
            y: ys,
            yaxis: "y2",
            type: "scatter",
            mode: "text+markers",
            marker: { size: 15, color: colors, line: { color: "#ffffff", width: 1 } },
            text: texts,
            textposition: "middle center",
            textfont: { size: 9, color: "#ffffff" },
            hovertext: hovers,
            hovertemplate: "%{hovertext}<extra></extra>",
            showlegend: false,
          } as Plotly.Data,
        ];

  return { shapes, traces, legendItems };
}
