import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format a number as USD currency string, e.g. $1,234,567 */
export function fmt(n: number): string {
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

/** Format a decimal as a percentage string, e.g. 0.85 → "85.0%" */
export function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}
