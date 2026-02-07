"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface StatsTableProps {
  rows: Array<Record<string, string>>;
}

export function StatsTable({ rows }: StatsTableProps) {
  if (!rows || rows.length === 0) return null;
  const keys = Object.keys(rows[0]);

  return (
    <div className="rounded-md border overflow-auto max-h-[500px]">
      <Table>
        <TableHeader>
          <TableRow>
            {keys.map((k) => (
              <TableHead key={k} className="whitespace-nowrap">{k}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, i) => (
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
  );
}
