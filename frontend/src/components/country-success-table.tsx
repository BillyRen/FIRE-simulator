"use client";

import { memo, useMemo } from "react";
import { useTranslations } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { fmt, pct } from "@/lib/utils";
import type { CountrySuccessRow } from "@/lib/country-success";

interface Props {
  rows: CountrySuccessRow[];
  countryLabel: (iso: string) => string;
}

function CountrySuccessTableImpl({ rows, countryLabel }: Props) {
  const tc = useTranslations("common");

  // best / worst among rows with a defined success rate (suppress when all tied)
  const { bestCountry, worstCountry } = useMemo(() => {
    const rated = rows.filter((r) => r.successRate !== null);
    if (rated.length < 2) return { bestCountry: null, worstCountry: null };
    let best = rated[0];
    let worst = rated[0];
    for (const r of rated) {
      if ((r.successRate as number) > (best.successRate as number)) best = r;
      if ((r.successRate as number) < (worst.successRate as number)) worst = r;
    }
    if (best.successRate === worst.successRate) {
      return { bestCountry: null, worstCountry: null };
    }
    return { bestCountry: best.country, worstCountry: worst.country };
  }, [rows]);

  const columns: DataTableColumn<CountrySuccessRow>[] = [
    {
      key: "country",
      header: tc("countryCol"),
      sortable: true,
      sortValue: (r) => r.country,
      csvValue: (r) => countryLabel(r.country),
      render: (r) => (
        <span>
          {countryLabel(r.country)}
          {r.country === bestCountry && (
            <span className="ml-2 text-xs text-emerald-600 dark:text-emerald-400">{tc("bestTag")}</span>
          )}
          {r.country === worstCountry && (
            <span className="ml-2 text-xs text-red-600 dark:text-red-400">{tc("worstTag")}</span>
          )}
        </span>
      ),
    },
    {
      key: "successRate",
      header: tc("successRate"),
      align: "right",
      sortable: true,
      sortValue: (r) => r.successRate,
      csvValue: (r) => (r.successRate === null ? "" : pct(r.successRate)),
      render: (r) => (r.successRate === null ? "—" : pct(r.successRate)),
    },
    {
      key: "eligible",
      header: tc("pathCountCol"),
      align: "right",
      sortable: true,
      sortValue: (r) => r.eligible,
      csvValue: (r) => `${r.eligible}/${r.total}`,
      render: (r) => (
        <span className="text-muted-foreground">
          {r.eligible}/{r.total}
        </span>
      ),
    },
    {
      key: "medianMinWithdrawal",
      header: tc("minWithdrawalCol"),
      align: "right",
      sortable: true,
      sortValue: (r) => r.medianMinWithdrawal,
      csvValue: (r) => (r.medianMinWithdrawal === null ? "" : fmt(r.medianMinWithdrawal)),
      render: (r) => (r.medianMinWithdrawal === null ? "—" : fmt(r.medianMinWithdrawal)),
    },
  ];

  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{tc("successByCountry")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">{tc("successByCountryDesc")}</p>
        <DataTable
          columns={columns}
          rows={rows}
          getRowKey={(r) => r.country}
          defaultSort={{ key: "successRate", dir: -1 }}
          maxHeight={480}
          downloadName="country_success"
          rowClassName={(r) =>
            r.country === bestCountry
              ? "shadow-[inset_3px_0_0_#0e9f6e]"
              : r.country === worstCountry
                ? "shadow-[inset_3px_0_0_#d64550]"
                : ""
          }
        />
      </CardContent>
    </Card>
  );
}

export const CountrySuccessTable = memo(CountrySuccessTableImpl);
