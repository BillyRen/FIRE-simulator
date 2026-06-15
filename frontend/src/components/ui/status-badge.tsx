import { Check, X, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export type StatusVariant = "ok" | "bad" | "censored";

const VARIANT_STYLES: Record<StatusVariant, string> = {
  ok: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  bad: "bg-red-500/15 text-red-700 dark:text-red-400",
  censored: "bg-muted text-muted-foreground",
};

const VARIANT_ICONS: Record<StatusVariant, typeof Check> = {
  ok: Check,
  bad: X,
  censored: HelpCircle,
};

interface StatusBadgeProps {
  variant: StatusVariant;
  label: string;
  /** Accessible label; defaults to `label`. */
  ariaLabel?: string;
  className?: string;
}

/** Colored pill replacing bare ✓/✗/? glyphs. Carries text + an aria-label. */
export function StatusBadge({ variant, label, ariaLabel, className }: StatusBadgeProps) {
  const Icon = VARIANT_ICONS[variant];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        VARIANT_STYLES[variant],
        className,
      )}
      aria-label={ariaLabel ?? label}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {label}
    </span>
  );
}
