import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  hint?: string;
  className?: string;
}

/** Centered placeholder for "no data yet / nothing to show" states. */
export function EmptyState({ icon: Icon, title, hint, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 py-12 text-center text-muted-foreground",
        className,
      )}
    >
      {Icon && <Icon className="h-8 w-8 opacity-40" aria-hidden="true" />}
      <p className="text-sm font-medium">{title}</p>
      {hint && <p className="max-w-sm text-xs opacity-80">{hint}</p>}
    </div>
  );
}
