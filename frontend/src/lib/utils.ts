import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format a number as a currency-neutral string with compact notation for large values.
 *  e.g. 1234 → "1,234", 123_456 → "123,456", 1_234_567 → "1.23M", 1_234_567_890 → "1.23B".
 *  No currency symbol: the simulation models real (inflation-adjusted) returns of the
 *  selected market with no FX conversion, so amounts are in whatever currency the user
 *  inputs. See common.currencyNote in i18n. */
export function fmt(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  return `${sign}${abs.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

/** Format a decimal as a percentage string, e.g. 0.85 → "85.0%" */
export function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

/** Format difference as percentage-point delta, e.g. +2.3pp or -1.0pp */
export function deltaPct(cur: number, pin: number): string {
  const d = cur - pin;
  const sign = d >= 0 ? "+" : "";
  return `${sign}${(d * 100).toFixed(1)}pp`;
}

/** Format difference as a currency-neutral delta, e.g. +12,345 or -6.78M */
export function deltaFmt(cur: number, pin: number): string {
  const d = cur - pin;
  const sign = d >= 0 ? "+" : "";
  return `${sign}${fmt(d)}`;
}

/** Format a sensitivity-analysis parameter value by its key (amounts, years,
 *  allocation/target percentages, else 2-decimal). Shared by the simulator and
 *  guardrail sensitivity tables. */
export function formatParamValue(v: number, key: string): string {
  if (key === "initial_portfolio" || key === "annual_withdrawal")
    return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (key === "retirement_years") return v.toFixed(0);
  if (key === "stock_allocation" || key === "target_success")
    return `${(v * 100).toFixed(0)}%`;
  return v.toFixed(2);
}

const ISO3_TO_ALPHA2: Record<string, string> = {
  AUS: "AU", BEL: "BE", CHE: "CH", DEU: "DE",
  DNK: "DK", ESP: "ES", FIN: "FI", FRA: "FR",
  GBR: "GB", ITA: "IT", JPN: "JP", NLD: "NL",
  NOR: "NO", PRT: "PT", SWE: "SE", USA: "US",
};

/** Convert ISO 3166-1 alpha-3 country code to its flag emoji via regional indicator symbols. */
export function countryFlag(iso3: string): string {
  const alpha2 = ISO3_TO_ALPHA2[iso3];
  if (!alpha2) return "";
  return String.fromCodePoint(
    ...alpha2.split("").map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)
  );
}
