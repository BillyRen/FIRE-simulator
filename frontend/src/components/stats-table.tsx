"use client";

import { memo } from "react";
import { useMessages } from "next-intl";
import { Download } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { downloadTableRows } from "@/lib/csv";

interface StatsTableProps {
  rows: Array<Record<string, string>>;
  /** CSV download filename (without extension), empty = no download button */
  downloadName?: string;
}

// A value that reads as a number / percentage / formatted amount (commas, sign,
// decimals, optional % or M/B suffix). Used to right-align numeric columns.
const NUMERIC_RE = /^[-+]?[\d,]+(\.\d+)?\s*[%MBK]?$/;
const NEUTRAL_CELLS = new Set(["", "—", "-", "N/A", "n/a", "NA"]);

function isNumericValue(v: string): boolean {
  return NUMERIC_RE.test(v.trim());
}

function isNegativeValue(v: string): boolean {
  const s = v.trim();
  return s.startsWith("-") && isNumericValue(s);
}

export const StatsTable = memo(function StatsTable({ rows, downloadName }: StatsTableProps) {
  const messages = useMessages();
  const backendMap = (messages?.backendKeys ?? {}) as Record<string, string>;

  if (!rows || rows.length === 0) return null;

  /** Translate a backend string via plain lookup; return as-is if no match */
  const tr = (s: string): string => backendMap[s] ?? s;

  /** Translate all keys and known values in rows */
  const translatedRows = rows.map((row) => {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(row)) {
      out[tr(k)] = tr(v);
    }
    return out;
  });

  const keys = Object.keys(translatedRows[0]);

  // A column is numeric if every non-neutral value parses as a number and at
  // least one value is present → right-align it with tabular figures.
  const numericKeys = new Set(
    keys.filter((k) => {
      let sawValue = false;
      for (const row of translatedRows) {
        const v = (row[k] ?? "").trim();
        if (NEUTRAL_CELLS.has(v)) continue;
        if (!isNumericValue(v)) return false;
        sawValue = true;
      }
      return sawValue;
    }),
  );

  return (
    <div className="space-y-1">
      {downloadName && (
        <div className="flex justify-end">
          <button
            onClick={() => downloadTableRows(downloadName, translatedRows)}
            className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <Download className="h-3 w-3" />
            CSV
          </button>
        </div>
      )}
      <div className="overflow-auto rounded-md border max-h-[500px]">
        <Table>
          <TableHeader>
            <TableRow>
              {keys.map((k, i) => (
                <TableHead
                  key={k}
                  className={cn(
                    "sticky top-0 z-10 whitespace-nowrap bg-background",
                    numericKeys.has(k) && i > 0 ? "text-right" : "text-left",
                  )}
                >
                  {k}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {translatedRows.map((row, i) => (
              <TableRow key={i}>
                {keys.map((k, j) => {
                  const v = row[k];
                  const numeric = numericKeys.has(k) && j > 0;
                  return (
                    <TableCell
                      key={k}
                      className={cn(
                        "whitespace-nowrap",
                        numeric && "text-right tabular-nums",
                        j === 0 && "text-muted-foreground",
                        numeric && isNegativeValue(v) && "text-red-600 dark:text-red-400",
                      )}
                    >
                      {v}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
});
