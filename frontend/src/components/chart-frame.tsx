"use client";

import { type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Info, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { useIsMobile } from "@/lib/use-is-mobile";
import { chartHeight, CHART_HEIGHTS } from "@/lib/chart-theme";

interface ChartFrameProps {
  title: string;
  infoTooltip?: string;
  /** Height bucket — drives the loading skeleton size. */
  height?: keyof typeof CHART_HEIGHTS;
  showLogToggle?: boolean;
  /** Controlled log state. When provided, the toggle is controlled by the parent. */
  logScale?: boolean;
  onToggleLogScale?: () => void;
  /** Renders a "data CSV" button when provided. */
  onDownloadData?: () => void;
  loading?: boolean;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyHint?: string;
  children: ReactNode;
}

/**
 * Standard chrome for a chart: title + optional info tooltip, a right-aligned
 * control cluster (log toggle with aria-label, data download), and loading /
 * empty states. Charts placed inside should not render their own Plotly title.
 */
export function ChartFrame({
  title,
  infoTooltip,
  height = "md",
  showLogToggle,
  logScale,
  onToggleLogScale,
  onDownloadData,
  loading,
  isEmpty,
  emptyTitle,
  emptyHint,
  children,
}: ChartFrameProps) {
  const t = useTranslations();
  const isMobile = useIsMobile();
  const skeletonH = chartHeight(height, isMobile);

  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="inline-flex items-center gap-1 text-sm font-semibold">
          {title}
          {infoTooltip && (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    aria-label={infoTooltip}
                    className="inline-flex items-center text-muted-foreground hover:text-foreground"
                  >
                    <Info className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[240px] text-xs">
                  {infoTooltip}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </h3>
        <div className="flex items-center gap-1.5">
          {showLogToggle && (
            <Button
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={onToggleLogScale}
              aria-label={logScale ? t("common.linearScale") : t("common.logScale")}
            >
              {logScale ? t("common.linearScale") : t("common.logScale")}
            </Button>
          )}
          {onDownloadData && (
            <button
              onClick={onDownloadData}
              className="inline-flex h-6 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              aria-label={t("chartFrame.downloadData")}
            >
              <Download className="h-3 w-3" />
              CSV
            </button>
          )}
        </div>
      </div>
      {loading ? (
        <Skeleton className="w-full" style={{ height: skeletonH }} />
      ) : isEmpty ? (
        <EmptyState title={emptyTitle ?? "—"} hint={emptyHint} />
      ) : (
        children
      )}
    </div>
  );
}
