"use client";

import { Card, CardContent } from "@/components/ui/card";

interface MetricCardProps {
  label: string;
  value: string;
  sub?: string;
  className?: string;
}

export function MetricCard({ label, value, sub, className = "" }: MetricCardProps) {
  return (
    <Card className={`${className} overflow-hidden`}>
      <CardContent className="pt-4 pb-3 px-4">
        <p className="text-xs text-muted-foreground mb-1 truncate">{label}</p>
        <p className="text-xl font-bold tabular-nums truncate" title={value}>{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-0.5 truncate">{sub}</p>}
      </CardContent>
    </Card>
  );
}
