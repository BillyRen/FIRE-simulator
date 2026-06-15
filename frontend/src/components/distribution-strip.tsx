"use client";

import { type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { fmt } from "@/lib/utils";
import { CHART_COLORS } from "@/lib/chart-theme";
import { buildDistributionScale, type DistributionData } from "@/lib/distribution-scale";

interface DistributionStripProps {
  data: DistributionData;
  numSimulations?: number;
  /** Optional exact-figures table, revealed under a "show exact" disclosure. */
  exactContent?: ReactNode;
}

// SVG geometry (viewBox 640×140).
const X_ZERO = 24;
const X_LEFT = 64;
const X_RIGHT = 600;
const PLOT_W = X_RIGHT - X_LEFT;
const BAND_TOP = 50;
const BAND_H = 40;
const WHISKER_Y = 70;
const MED_TOP = 44;
const MED_BOT = 96;
const AXIS_Y = 110;
const LABEL_GAP = 70; // min px between P10 / P90 labels before we drop them

/** Compact power-of-ten tick label: 1e6 → "1M", 1e9 → "1B". */
function tickLabel(v: number): string {
  return fmt(v).replace(".00", "");
}

/**
 * Distribution-first view of ending wealth: a log-scale percentile strip
 * (box P25–P75, light band P10–P90, whisker P5–P95, median line, mean diamond,
 * a bankruptcy floor marker, and a dashed extension to the maximum). Only the
 * median and the two ends are labeled inline to avoid label collisions; the
 * mean and other detail live in the caption / exact table.
 */
export function DistributionStrip({ data, numSimulations, exactContent }: DistributionStripProps) {
  const t = useTranslations("distributionStrip");
  const scale = buildDistributionScale(data);

  if (!scale) {
    return exactContent ? <div>{exactContent}</div> : null;
  }

  const X = (v?: number | null): number | null =>
    v !== null && v !== undefined && Number.isFinite(v) && v > 0
      ? X_LEFT + scale.pos(v) * PLOT_W
      : null;

  const xP5 = X(data.p5);
  const xP10 = X(data.p10);
  const xP25 = X(data.p25);
  const xP50 = X(data.p50);
  const xP75 = X(data.p75);
  const xP90 = X(data.p90);
  const xP95 = X(data.p95);
  const xMax = X(data.max);
  const xMean = X(data.mean);

  const showEndLabels = xP10 !== null && xP90 !== null && xP90 - xP10 >= LABEL_GAP;
  const primary = CHART_COLORS.primary.hex;
  const primaryRgb = CHART_COLORS.primary.rgb;

  return (
    <div>
      <svg viewBox="0 0 640 140" className="w-full" style={{ maxHeight: 170 }} role="img">
        {/* bands */}
        {xP10 !== null && xP90 !== null && (
          <rect
            x={xP10}
            y={BAND_TOP}
            width={Math.max(0, xP90 - xP10)}
            height={BAND_H}
            fill={`rgba(${primaryRgb},0.14)`}
          />
        )}
        {xP25 !== null && xP75 !== null && (
          <rect
            x={xP25}
            y={BAND_TOP}
            width={Math.max(0, xP75 - xP25)}
            height={BAND_H}
            fill={`rgba(${primaryRgb},0.30)`}
          />
        )}

        {/* whisker P5–P95 */}
        {xP5 !== null && xP95 !== null && (
          <>
            <line x1={xP5} y1={WHISKER_Y} x2={xP95} y2={WHISKER_Y} stroke={CHART_COLORS.neutral.hex} strokeWidth={1.5} />
            <line x1={xP5} y1={WHISKER_Y - 8} x2={xP5} y2={WHISKER_Y + 8} stroke={CHART_COLORS.neutral.hex} strokeWidth={1.5} />
            <line x1={xP95} y1={WHISKER_Y - 8} x2={xP95} y2={WHISKER_Y + 8} stroke={CHART_COLORS.neutral.hex} strokeWidth={1.5} />
          </>
        )}

        {/* dashed extension to max */}
        {xP95 !== null && xMax !== null && xMax > xP95 + 2 && (
          <>
            <line x1={xP95} y1={WHISKER_Y} x2={xMax - 8} y2={WHISKER_Y} stroke={CHART_COLORS.neutral.hex} strokeWidth={1} strokeDasharray="4 3" />
            <polygon points={`${xMax},${WHISKER_Y} ${xMax - 8},${WHISKER_Y - 4} ${xMax - 8},${WHISKER_Y + 4}`} fill={CHART_COLORS.neutral.hex} />
          </>
        )}

        {/* median */}
        {xP50 !== null && (
          <line x1={xP50} y1={MED_TOP} x2={xP50} y2={MED_BOT} stroke={primary} strokeWidth={2.6} />
        )}

        {/* mean diamond */}
        {xMean !== null && (
          <polygon
            points={`${xMean},${WHISKER_Y - 6} ${xMean + 6},${WHISKER_Y} ${xMean},${WHISKER_Y + 6} ${xMean - 6},${WHISKER_Y}`}
            fill={CHART_COLORS.orange.hex}
          />
        )}

        {/* bankruptcy floor */}
        {scale.hasZeroFloor && (
          <rect x={X_ZERO - 4} y={WHISKER_Y - 4} width={9} height={9} fill={CHART_COLORS.danger.hex} />
        )}

        {/* axis + ticks */}
        <line x1={X_ZERO} y1={AXIS_Y} x2={X_RIGHT} y2={AXIS_Y} className="stroke-border" strokeWidth={1} />
        {scale.ticks.map((tv) => {
          const x = X_LEFT + scale.pos(tv) * PLOT_W;
          return (
            <g key={tv}>
              <line x1={x} y1={AXIS_Y - 3} x2={x} y2={AXIS_Y + 3} className="stroke-border" />
              <text x={x} y={AXIS_Y + 14} textAnchor="middle" fontSize={10} className="fill-muted-foreground">
                {tickLabel(tv)}
              </text>
            </g>
          );
        })}

        {/* inline labels: median (top), ends (left/right) */}
        {xP50 !== null && (
          <text x={xP50} y={MED_TOP - 6} textAnchor="middle" fontSize={11.5} fontWeight={600} fill={primary}>
            {t("median")} {fmt(data.p50 as number)}
          </text>
        )}
        {scale.hasZeroFloor && (
          <text x={X_ZERO - 6} y={WHISKER_Y - 12} textAnchor="start" fontSize={9} fill={CHART_COLORS.danger.hex}>
            {t("bankruptcyFloor")}
          </text>
        )}
        {xMax !== null && (
          <text x={xMax} y={WHISKER_Y - 12} textAnchor="end" fontSize={9.5} className="fill-muted-foreground">
            {t("highest")} {fmt(data.max as number)}
          </text>
        )}
        {showEndLabels && (
          <>
            <text x={xP10 as number} y={MED_BOT + 12} textAnchor="middle" fontSize={9} className="fill-muted-foreground">
              P10 {fmt(data.p10 as number)}
            </text>
            <text x={xP90 as number} y={MED_BOT + 12} textAnchor="middle" fontSize={9} className="fill-muted-foreground">
              P90 {fmt(data.p90 as number)}
            </text>
          </>
        )}
      </svg>

      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
        {t("bandLegend")}
        {data.mean !== null && data.mean !== undefined && Number.isFinite(data.mean) && (
          <>
            {" · "}
            <span style={{ color: CHART_COLORS.orange.hex }}>◆ {t("mean")} {fmt(data.mean)}</span>
            {" "}（{t("meanPulled")}）
          </>
        )}
        <br />
        {t("logNote")}
        {numSimulations ? ` · ${t("basedOn", { n: numSimulations.toLocaleString("en-US") })}` : ""}
      </p>

      {exactContent && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs text-primary">{t("showExact")}</summary>
          <div className="mt-2">{exactContent}</div>
        </details>
      )}
    </div>
  );
}
