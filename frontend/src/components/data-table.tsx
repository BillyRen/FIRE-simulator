"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ChevronUp, ChevronDown, ChevronsUpDown, Download, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";
import { compareNullable } from "@/lib/sort";
import { downloadCSV } from "@/lib/csv";
import { EmptyState } from "@/components/empty-state";

export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  /** Cell + header alignment. Numeric columns should be "right". */
  align?: "left" | "right";
  sortable?: boolean;
  /** Value used for sorting; defaults to row[key]. null sorts last. */
  sortValue?: (row: T) => number | string | null;
  /** Custom cell content; defaults to String(row[key]). */
  render?: (row: T) => ReactNode;
  /** Plain-text value for CSV export; required when `render` is custom and the
   *  raw row[key] is not the desired export value. Defaults to String(row[key]). */
  csvValue?: (row: T) => string;
  /** Header text for CSV; defaults to the string header, else the key. */
  csvHeader?: string;
  className?: string;
  headerClassName?: string;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowKey: (row: T, index: number) => string | number;
  onRowClick?: (row: T) => void;
  /** Per-row className (e.g. best/worst highlight). */
  rowClassName?: (row: T) => string;
  /** Filename (no extension) → renders a CSV button that exports the current sort order. */
  downloadName?: string;
  defaultSort?: { key: string; dir: 1 | -1 };
  maxHeight?: number | string;
  emptyTitle?: string;
  emptyHint?: string;
  className?: string;
}

function cellText<T>(col: DataTableColumn<T>, row: T): string {
  if (col.csvValue) return col.csvValue(row);
  const raw = (row as Record<string, unknown>)[col.key];
  return raw === null || raw === undefined ? "" : String(raw);
}

function defaultSortValue<T>(col: DataTableColumn<T>, row: T): number | string | null {
  if (col.sortValue) return col.sortValue(row);
  const raw = (row as Record<string, unknown>)[col.key];
  if (raw === null || raw === undefined) return null;
  return typeof raw === "number" ? raw : String(raw);
}

export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  onRowClick,
  rowClassName,
  downloadName,
  defaultSort,
  maxHeight = 500,
  emptyTitle = "—",
  emptyHint,
  className,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(defaultSort?.key ?? null);
  const [sortDir, setSortDir] = useState<1 | -1>(defaultSort?.dir ?? -1);

  const sorted = useMemo(() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col) return rows;
    // stable sort: decorate with original index
    return rows
      .map((row, i) => ({ row, i }))
      .sort((a, b) => {
        const cmp = compareNullable(
          defaultSortValue(col, a.row),
          defaultSortValue(col, b.row),
          sortDir,
        );
        return cmp !== 0 ? cmp : a.i - b.i;
      })
      .map((d) => d.row);
  }, [rows, columns, sortKey, sortDir]);

  function handleSort(col: DataTableColumn<T>) {
    if (!col.sortable) return;
    if (col.key === sortKey) {
      setSortDir((d) => (d === 1 ? -1 : 1));
    } else {
      setSortKey(col.key);
      setSortDir(col.align === "right" ? -1 : 1); // numeric desc, text asc
    }
  }

  function exportCsv() {
    if (!downloadName) return;
    const headers = columns.map(
      (c) => c.csvHeader ?? (typeof c.header === "string" ? c.header : c.key),
    );
    const data = sorted.map((row) => columns.map((c) => cellText(c, row)));
    downloadCSV(downloadName, headers, data);
  }

  if (rows.length === 0) {
    return <EmptyState icon={Inbox} title={emptyTitle} hint={emptyHint} />;
  }

  return (
    <div className={cn("space-y-1", className)}>
      {downloadName && (
        <div className="flex justify-end">
          <button
            onClick={exportCsv}
            className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <Download className="h-3 w-3" />
            CSV
          </button>
        </div>
      )}
      <div
        className="overflow-auto rounded-md border"
        style={{ maxHeight: typeof maxHeight === "number" ? `${maxHeight}px` : maxHeight }}
      >
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-background">
            <tr className="border-b-2">
              {columns.map((col) => {
                const active = col.key === sortKey;
                const ariaSort = active
                  ? sortDir === 1
                    ? "ascending"
                    : "descending"
                  : col.sortable
                    ? "none"
                    : undefined;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={ariaSort}
                    className={cn(
                      "whitespace-nowrap px-3 py-2 font-medium text-muted-foreground",
                      col.align === "right" ? "text-right" : "text-left",
                      col.headerClassName,
                    )}
                  >
                    {col.sortable ? (
                      <button
                        type="button"
                        onClick={() => handleSort(col)}
                        className={cn(
                          "inline-flex select-none items-center gap-1 font-medium hover:text-foreground",
                          col.align === "right" && "flex-row-reverse",
                        )}
                      >
                        {col.header}
                        {active ? (
                          sortDir === 1 ? (
                            <ChevronUp className="h-3.5 w-3.5 text-foreground" />
                          ) : (
                            <ChevronDown className="h-3.5 w-3.5 text-foreground" />
                          )
                        ) : (
                          <ChevronsUpDown className="h-3.5 w-3.5 opacity-40" />
                        )}
                      </button>
                    ) : (
                      <span
                        className={cn(
                          "inline-flex items-center gap-1",
                          col.align === "right" && "flex-row-reverse",
                        )}
                      >
                        {col.header}
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => {
              const clickable = !!onRowClick;
              return (
                <tr
                  key={getRowKey(row, i)}
                  className={cn(
                    "border-b transition-colors last:border-0 hover:bg-muted/40",
                    clickable && "cursor-pointer",
                    rowClassName?.(row),
                  )}
                  {...(clickable
                    ? {
                        role: "button",
                        tabIndex: 0,
                        onClick: () => onRowClick(row),
                        onKeyDown: (e: React.KeyboardEvent) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onRowClick(row);
                          }
                        },
                      }
                    : {})}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={cn(
                        "whitespace-nowrap px-3 py-1.5",
                        col.align === "right" && "text-right tabular-nums",
                        col.className,
                      )}
                    >
                      {col.render ? col.render(row) : cellText(col, row)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
