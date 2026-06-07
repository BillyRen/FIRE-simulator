"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import PlotlyChart from "@/components/plotly-chart";
import { CHART_COLORS, MARGINS } from "@/lib/chart-theme";
import { useIsMobile } from "@/components/fan-chart";
import { usePersistedState } from "@/lib/use-persisted-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { richBrokeDeadSeries, type MortalitySex } from "@/lib/mortality";

/**
 * "Rich / Broke / Dead" stacked-area chart (inspired by engaging-data).
 * Combines the per-year solvency curve with SSA-calibrated mortality to show,
 * for each future age, the probability of being: alive with money (rich),
 * alive but depleted (broke), or deceased (dead). The three bands sum to 100%.
 */
export function RichBrokeDeadChart({
  solvencyByYear,
  retirementAge,
}: {
  solvencyByYear: number[];
  retirementAge: number;
}) {
  const t = useTranslations("richBrokeDead");
  const isMobile = useIsMobile();
  const [sex, setSex] = usePersistedState<MortalitySex>("fire:rbd:sex", "blended");

  const series = useMemo(
    () => richBrokeDeadSeries(solvencyByYear, retirementAge, sex),
    [solvencyByYear, retirementAge, sex],
  );

  const ages = series.map((p) => p.age);
  const toPct = (v: number) => Math.round(v * 1000) / 10;

  // Stacked from bottom: dead → broke → rich, so "rich" sits on top and the
  // shrinking green band reads as the chance of a money-and-life success.
  const traces = [
    {
      x: ages,
      y: series.map((p) => toPct(p.dead)),
      name: t("dead"),
      stackgroup: "one",
      mode: "none" as const,
      fillcolor: `rgba(${CHART_COLORS.neutral.rgb},0.75)`,
      hovertemplate: `%{x}: %{y:.1f}% ${t("dead")}<extra></extra>`,
    },
    {
      x: ages,
      y: series.map((p) => toPct(p.broke)),
      name: t("broke"),
      stackgroup: "one",
      mode: "none" as const,
      fillcolor: `rgba(${CHART_COLORS.warning.rgb},0.8)`,
      hovertemplate: `%{x}: %{y:.1f}% ${t("broke")}<extra></extra>`,
    },
    {
      x: ages,
      y: series.map((p) => toPct(p.solvent)),
      name: t("rich"),
      stackgroup: "one",
      mode: "none" as const,
      fillcolor: `rgba(${CHART_COLORS.secondary.rgb},0.8)`,
      hovertemplate: `%{x}: %{y:.1f}% ${t("rich")}<extra></extra>`,
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-end gap-2 mb-1">
        <Label className="text-xs text-muted-foreground">{t("mortalityTable")}</Label>
        <Select value={sex} onValueChange={(v) => setSex(v as MortalitySex)}>
          <SelectTrigger className="h-7 text-xs w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="blended">{t("sexBlended")}</SelectItem>
            <SelectItem value="male">{t("sexMale")}</SelectItem>
            <SelectItem value="female">{t("sexFemale")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <PlotlyChart
        data={traces}
        layout={{
          title: isMobile ? undefined : { text: t("title"), font: { size: 14 } },
          xaxis: { title: { text: t("ageAxis") } },
          yaxis: {
            title: { text: t("probabilityAxis") },
            range: [0, 100],
            ticksuffix: "%",
          },
          margin: MARGINS.withTitle(isMobile),
          height: isMobile ? 280 : 400,
          showlegend: true,
          legend: { orientation: "h", y: -0.2 },
          hovermode: "x unified",
        }}
        config={{ displayModeBar: false }}
      />
      <p className="text-[11px] text-muted-foreground mt-1 leading-snug">{t("footnote")}</p>
    </div>
  );
}
