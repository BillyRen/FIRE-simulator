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
import { Button } from "@/components/ui/button";
import { downloadTableRows } from "@/lib/csv";

interface StatsTableProps {
  rows: Array<Record<string, string>>;
  /** CSV download filename (without extension), empty = no download button */
  downloadName?: string;
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

  return (
    <div className="space-y-1">
      {downloadName && (
        <div className="flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-xs text-muted-foreground gap-1 px-2"
            onClick={() => downloadTableRows(downloadName, translatedRows)}
          >
            <Download className="h-3 w-3" />
            CSV
          </Button>
        </div>
      )}
      <div className="rounded-md border overflow-auto max-h-[500px] -mx-1 px-1">
        <Table>
          <TableHeader>
            <TableRow>
              {keys.map((k) => (
                <TableHead key={k} className="whitespace-nowrap">{k}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {translatedRows.map((row, i) => (
              <TableRow key={i}>
                {keys.map((k) => (
                  <TableCell key={k} className="whitespace-nowrap tabular-nums">
                    {row[k]}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
});
