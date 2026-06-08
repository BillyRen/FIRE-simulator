"use client";

import { memo, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmt, pct } from "@/lib/utils";
import type { CountrySuccessRow } from "@/lib/country-success";

type SortKey = "country" | "successRate" | "eligible" | "medianMinWithdrawal";

interface Props {
  rows: CountrySuccessRow[];
  countryLabel: (iso: string) => string;
}

// Nulls always sort last regardless of direction.
function compareNullable(a: number | null, b: number | null, dir: 1 | -1): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return (a - b) * dir;
}

function CountrySuccessTableImpl({ rows, countryLabel }: Props) {
  const tc = useTranslations("common");
  const [sortKey, setSortKey] = useState<SortKey>("successRate");
  const [sortDir, setSortDir] = useState<1 | -1>(-1); // default: success rate desc

  // best / worst among rows with a defined success rate
  const { bestCountry, worstCountry } = useMemo(() => {
    const rated = rows.filter((r) => r.successRate !== null);
    if (rated.length < 2) return { bestCountry: null, worstCountry: null };
    let best = rated[0];
    let worst = rated[0];
    for (const r of rated) {
      if ((r.successRate as number) > (best.successRate as number)) best = r;
      if ((r.successRate as number) < (worst.successRate as number)) worst = r;
    }
    // All tied: no meaningful best/worst, suppress both badges.
    if (best.successRate === worst.successRate) {
      return { bestCountry: null, worstCountry: null };
    }
    return { bestCountry: best.country, worstCountry: worst.country };
  }, [rows]);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      let cmp: number;
      if (sortKey === "country") {
        cmp = a.country < b.country ? -1 : a.country > b.country ? 1 : 0;
        cmp *= sortDir;
      } else if (sortKey === "eligible") {
        cmp = (a.eligible - b.eligible) * sortDir;
      } else if (sortKey === "medianMinWithdrawal") {
        cmp = compareNullable(a.medianMinWithdrawal, b.medianMinWithdrawal, sortDir);
      } else {
        cmp = compareNullable(a.successRate, b.successRate, sortDir);
      }
      // stable tie-break by country
      return cmp !== 0 ? cmp : a.country < b.country ? -1 : 1;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 1 ? -1 : 1));
    } else {
      setSortKey(key);
      // numeric columns default to descending, country to ascending
      setSortDir(key === "country" ? 1 : -1);
    }
  }

  function indicator(key: SortKey) {
    if (key !== sortKey) return "";
    return sortDir === 1 ? " ▲" : " ▼";
  }

  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{tc("successByCountry")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">{tc("successByCountryDesc")}</p>
        <div className="rounded-md border overflow-auto max-h-[480px]">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 sticky top-0">
              <tr>
                <th
                  className="px-3 py-2 text-left cursor-pointer select-none whitespace-nowrap"
                  onClick={() => handleSort("country")}
                >
                  {tc("countryCol")}{indicator("country")}
                </th>
                <th
                  className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap"
                  onClick={() => handleSort("successRate")}
                >
                  {tc("successRate")}{indicator("successRate")}
                </th>
                <th
                  className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap"
                  onClick={() => handleSort("eligible")}
                >
                  {tc("pathCountCol")}{indicator("eligible")}
                </th>
                <th
                  className="px-3 py-2 text-right cursor-pointer select-none whitespace-nowrap"
                  onClick={() => handleSort("medianMinWithdrawal")}
                >
                  {tc("minWithdrawalCol")}{indicator("medianMinWithdrawal")}
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const isBest = r.country === bestCountry;
                const isWorst = r.country === worstCountry;
                const rowCls = isBest
                  ? "bg-green-500/10"
                  : isWorst
                    ? "bg-red-500/10"
                    : "";
                return (
                  <tr key={r.country} className={`border-t ${rowCls}`}>
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      {countryLabel(r.country)}
                      {isBest && (
                        <span className="ml-2 text-xs text-green-600">{tc("bestTag")}</span>
                      )}
                      {isWorst && (
                        <span className="ml-2 text-xs text-red-500">{tc("worstTag")}</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono">
                      {r.successRate === null ? "—" : pct(r.successRate)}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-muted-foreground">
                      {r.eligible}/{r.total}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono">
                      {r.medianMinWithdrawal === null ? "—" : fmt(r.medianMinWithdrawal)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export const CountrySuccessTable = memo(CountrySuccessTableImpl);
