"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { GuardrailBatchPathSummary } from "@/lib/types";
import { countryFlag } from "@/lib/utils";

/**
 * Historical stress-test narrative for the guardrail strategy.
 *
 * Income Lab's signature credibility pitch is "in 2008 the guardrail only
 * required an X% income cut." We reproduce that from the batch backtest: for a
 * set of famous stress-start years, find the matching path (preferring USA) and
 * report the worst real spending cut the guardrail strategy ever imposed, plus
 * whether the plan survived. Pure frontend — derived from existing batch data.
 */

interface StressEvent {
  year: number;
  /** i18n key suffix under guardrail.stress.event_* */
  key: string;
}

const STRESS_EVENTS: StressEvent[] = [
  { year: 1929, key: "1929" }, // Great Depression
  { year: 1937, key: "1937" }, // 1937 recession
  { year: 1966, key: "1966" }, // Stagflation era onset (classic worst-case)
  { year: 1973, key: "1973" }, // Oil crisis / stagflation
  { year: 2000, key: "2000" }, // Dot-com bust
  { year: 2008, key: "2008" }, // Global financial crisis
];

type Outcome = "survived" | "depleted" | "ongoing";

interface StressRow {
  year: number;
  key: string;
  country: string;
  worstCutPct: number; // 0..1, fraction below starting income
  outcome: Outcome;
  years: number;
}

/** Pick the path for a stress year: prefer USA, else the most-complete one.
 *  Match on `start_year` — the first *sampled* return year — since a batch
 *  path's year_labels[0] is the pre-retirement label (start_year - 1). */
function pickPath(
  paths: GuardrailBatchPathSummary[],
  year: number,
): GuardrailBatchPathSummary | null {
  const matches = paths.filter((p) => p.start_year === year);
  if (matches.length === 0) return null;
  const usa = matches.find((p) => p.country === "USA");
  if (usa) return usa;
  return matches.reduce((a, b) => (b.years_simulated > a.years_simulated ? b : a));
}

export function GuardrailStressNarrative({
  paths,
}: {
  paths: GuardrailBatchPathSummary[];
}) {
  const t = useTranslations("guardrail");

  const rows = useMemo<StressRow[]>(() => {
    const out: StressRow[] = [];
    for (const ev of STRESS_EVENTS) {
      const p = pickPath(paths, ev.year);
      if (!p || p.g_withdrawals.length === 0) continue;
      const initial = p.g_withdrawals[0];
      if (!(initial > 0)) continue;
      const minWd = Math.min(...p.g_withdrawals);
      const worstCutPct = Math.max(0, 1 - minWd / initial);
      // Determine true asset depletion from the portfolio trajectory rather than
      // g_has_failed, which also flags consumption-floor breaches on solvent
      // paths. For a complete plan, a zero only in the final horizon year counts
      // as survived (project convention), so we look before the last point. For
      // a censored (incomplete) path, the last point is where data ended, not
      // the horizon, so a zero there is a genuine depletion and must count.
      const port = p.g_portfolio;
      const depleted = p.is_complete
        ? port.slice(0, -1).some((v) => v <= 0)
        : port.some((v) => v <= 0);
      // Three states: truly depleted, a complete survivor, or a censored path
      // that simply ran out of historical data (still solvent).
      const outcome: Outcome = depleted
        ? "depleted"
        : p.is_complete
          ? "survived"
          : "ongoing";
      out.push({
        year: ev.year, key: ev.key, country: p.country,
        worstCutPct, outcome, years: p.years_simulated,
      });
    }
    return out;
  }, [paths]);

  if (rows.length === 0) return null;

  return (
    <div className="space-y-2">
      <div>
        <h3 className="text-sm font-medium">{t("stress.title")}</h3>
        <p className="text-xs text-muted-foreground">{t("stress.subtitle")}</p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {rows.map((r) => (
          <div key={r.year} className="rounded-md border p-2.5">
            <div className="text-xs text-muted-foreground">
              {countryFlag(r.country)} {t("stress.retireIn", { year: r.year })}
            </div>
            <div className="text-[11px] text-muted-foreground mb-1">
              {t(`stress.event_${r.key}`)}
            </div>
            <div className="text-lg font-semibold tabular-nums">
              {r.worstCutPct > 0 ? "−" : ""}{(r.worstCutPct * 100).toFixed(1)}%
            </div>
            <div className="text-[11px] text-muted-foreground">{t("stress.worstCut")}</div>
            <div
              className={`text-xs mt-1 ${
                r.outcome === "survived"
                  ? "text-green-600"
                  : r.outcome === "depleted"
                    ? "text-destructive"
                    : "text-muted-foreground"
              }`}
            >
              {r.outcome === "survived"
                ? t("stress.survived")
                : r.outcome === "depleted"
                  ? t("stress.depleted")
                  : t("stress.ongoing", { years: r.years })}
            </div>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground leading-snug">{t("stress.footnote")}</p>
    </div>
  );
}
