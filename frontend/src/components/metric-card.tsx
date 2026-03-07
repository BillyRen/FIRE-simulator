"use client";

import { Info } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface MetricCardProps {
  label: string;
  value: string;
  sub?: string;
  className?: string;
  delta?: string;
  tooltip?: string;
}

export function MetricCard({ label, value, sub, className = "", delta, tooltip }: MetricCardProps) {
  return (
    <Card className={`${className} overflow-hidden`}>
      <CardContent className="pt-4 pb-3 px-4">
        <p className="text-xs text-muted-foreground mb-1 truncate inline-flex items-center gap-1">
          {label}
          {tooltip && (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="h-3 w-3 text-muted-foreground cursor-help shrink-0" />
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[220px] text-xs">
                  {tooltip}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
        </p>
        <p className="text-lg font-bold tabular-nums leading-tight" title={value}>{value}</p>
        {delta && (
          <span
            className={`text-xs font-medium tabular-nums ${
              delta.startsWith("+") ? "text-green-600 dark:text-green-400"
              : delta.startsWith("-") ? "text-red-500 dark:text-red-400"
              : "text-muted-foreground"
            }`}
          >
            {delta}
          </span>
        )}
        {sub && <p className="text-xs text-muted-foreground mt-0.5 truncate">{sub}</p>}
      </CardContent>
    </Card>
  );
}
