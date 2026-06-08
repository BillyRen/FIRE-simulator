// Per-country censored-aware success-rate aggregation for batch backtests.
//
// Semantics mirror backend `simulator/backtest_batch.py`:
//   eligible (denominator) = complete ∪ (incomplete ∧ failed) = is_complete || has_failed
//   succeeded (numerator)  = is_complete && !has_failed
//   excluded               = incomplete ∧ !failed (insufficient data → dropped)
// Summing per-country eligible/succeeded reproduces the panel's overall denominator/numerator.

export interface CountrySuccessStatInput {
  country: string;
  is_complete: boolean;
  has_failed?: boolean;
  /** Math.min(...withdrawals) for the relevant strategy on this path. */
  minWithdrawal: number;
}

export interface CountrySuccessRow {
  country: string;
  /** All paths for the country (including excluded/censored). */
  total: number;
  /** Denominator: complete ∪ (incomplete ∧ failed). */
  eligible: number;
  /** Numerator: complete ∧ !failed. */
  succeeded: number;
  /** Censored, not failed — dropped from the success-rate calculation. */
  excluded: number;
  /** succeeded / eligible; null when eligible === 0. */
  successRate: number | null;
  /** Median min-withdrawal over eligible paths; null when none eligible. */
  medianMinWithdrawal: number | null;
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

export function computeCountrySuccessStats(
  paths: CountrySuccessStatInput[],
): CountrySuccessRow[] {
  const byCountry = new Map<string, CountrySuccessStatInput[]>();
  for (const p of paths) {
    const list = byCountry.get(p.country);
    if (list) list.push(p);
    else byCountry.set(p.country, [p]);
  }

  const rows: CountrySuccessRow[] = [];
  for (const [country, list] of byCountry) {
    let eligible = 0;
    let succeeded = 0;
    let excluded = 0;
    const eligibleMins: number[] = [];
    for (const p of list) {
      const failed = p.has_failed === true;
      const isEligible = p.is_complete || failed;
      if (isEligible) {
        eligible += 1;
        eligibleMins.push(p.minWithdrawal);
        if (p.is_complete && !failed) succeeded += 1;
      } else {
        excluded += 1;
      }
    }
    rows.push({
      country,
      total: list.length,
      eligible,
      succeeded,
      excluded,
      successRate: eligible > 0 ? succeeded / eligible : null,
      medianMinWithdrawal: median(eligibleMins),
    });
  }
  return rows;
}
