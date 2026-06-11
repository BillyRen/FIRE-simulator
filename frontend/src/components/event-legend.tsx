"use client";

import { memo } from "react";
import { useTranslations } from "next-intl";
import type { EventLegendItem } from "@/lib/historical-events";

interface EventLegendProps {
  items: EventLegendItem[];
}

export const EventLegend = memo(function EventLegend({ items }: EventLegendProps) {
  const tc = useTranslations("common");
  if (items.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
      {items.map((it) => (
        <span
          key={it.num}
          className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground"
          title={tc(`eventCategory.${it.category}`)}
        >
          <span
            className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px] font-medium leading-none text-white"
            style={{ backgroundColor: it.color }}
          >
            {it.num}
          </span>
          <span>{it.label}</span>
          <span className="text-muted-foreground/60">{it.yearText}</span>
        </span>
      ))}
    </div>
  );
});
