import type { HistoricalEvent } from "./types";

const CATEGORY_COLORS: Record<string, string> = {
  crisis: "rgba(239,68,68,0.5)",
  war: "rgba(107,114,128,0.5)",
  bubble: "rgba(249,115,22,0.5)",
  policy: "rgba(59,130,246,0.5)",
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

export function eventShapes(
  events: HistoricalEvent[],
  yMax: number,
): Partial<Plotly.Shape>[] {
  return events.map((e) => ({
    type: "line" as const,
    x0: e.year,
    x1: e.year,
    y0: 0,
    y1: yMax,
    line: {
      color: CATEGORY_COLORS[e.category] ?? "rgba(107,114,128,0.4)",
      width: 1.5,
      dash: "dot" as const,
    },
  }));
}

export function eventAnnotations(
  events: HistoricalEvent[],
  locale: string,
  yMax: number,
): Record<string, unknown>[] {
  return events.map((e, idx) => ({
    x: e.year,
    y: yMax,
    text: locale === "zh" ? e.label_zh : e.label_en,
    showarrow: false,
    textangle: "-45",
    font: {
      size: 8,
      color: CATEGORY_COLORS[e.category] ?? "rgba(107,114,128,0.8)",
    },
    xanchor: "left",
    yanchor: "bottom",
    yshift: 4 + (idx % 3) * 10,
  }));
}
