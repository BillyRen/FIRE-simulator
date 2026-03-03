import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format a number as USD currency string with compact notation for large values.
 *  e.g. 1234 → "$1,234", 123_456 → "$123,456", 1_234_567 → "$1.23M", 1_234_567_890 → "$1.23B" */
export function fmt(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

/** Format a decimal as a percentage string, e.g. 0.85 → "85.0%" */
export function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}
