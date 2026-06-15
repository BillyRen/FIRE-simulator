/**
 * Pure log-scale helper for the DistributionStrip (ending-wealth distribution).
 * Handles the edge cases failure/depletion data produces: a zero/negative floor
 * (bankruptcy), all-equal percentiles, tiny ranges, and missing keys.
 */

export interface DistributionData {
  min?: number | null;
  p5?: number | null;
  p10?: number | null;
  p25?: number | null;
  p50?: number | null;
  p75?: number | null;
  p90?: number | null;
  p95?: number | null;
  max?: number | null;
  mean?: number | null;
}

export interface DistributionScale {
  /** true when the floor is ≤ 0 (bankruptcy) — render as a separate marker, not on the log axis. */
  hasZeroFloor: boolean;
  /** positive log-domain bounds */
  domainLo: number;
  domainHi: number;
  /** map a positive value → fractional x in [0,1] across the log domain (clamped) */
  pos: (v: number) => number;
  /** power-of-ten gridline values within the domain */
  ticks: number[];
  /** true when all positive values were ~equal (domain artificially expanded) */
  degenerate: boolean;
}

const VALUE_KEYS = [
  "p5", "p10", "p25", "p50", "p75", "p90", "p95", "mean", "max", "min",
] as const;

const HALF_DECADE = Math.sqrt(10); // 10^0.5

/**
 * Build a log scale from the available percentiles. Returns null if there is no
 * positive value to place (caller should then fall back to a plain table).
 */
export function buildDistributionScale(d: DistributionData): DistributionScale | null {
  const positives: number[] = [];
  let hasZeroFloor = false;

  for (const k of VALUE_KEYS) {
    const v = d[k];
    if (v === null || v === undefined || !Number.isFinite(v)) continue;
    if (v <= 0) {
      hasZeroFloor = true;
      continue;
    }
    positives.push(v);
  }

  if (positives.length === 0) return null;

  let lo = Math.min(...positives);
  let hi = Math.max(...positives);
  const degenerate = !(hi > lo);
  if (degenerate) {
    // All positive values equal → expand half a decade each side so the single
    // point sits mid-strip instead of dividing by a zero-width domain.
    const center = lo;
    lo = center / HALF_DECADE;
    hi = center * HALF_DECADE;
  }

  const logLo = Math.log10(lo);
  const logHi = Math.log10(hi);
  const span = logHi - logLo || 1; // guard divide-by-zero

  const pos = (v: number): number => {
    if (!Number.isFinite(v) || v <= 0) return 0;
    const f = (Math.log10(v) - logLo) / span;
    return Math.min(1, Math.max(0, f));
  };

  const ticks: number[] = [];
  for (let e = Math.ceil(logLo); e <= Math.floor(logHi); e++) {
    ticks.push(10 ** e);
  }

  return { hasZeroFloor, domainLo: lo, domainHi: hi, pos, ticks, degenerate };
}
