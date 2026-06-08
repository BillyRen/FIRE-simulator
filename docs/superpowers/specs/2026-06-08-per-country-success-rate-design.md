# Per-Country Success Rate Breakdown — Design

Date: 2026-06-08

## Goal

In the historical batch backtest (multi-country pool, `country = "ALL"`), show a per-country
breakdown of success rate so the user can see which countries had the highest / lowest success
rate. Applies to both the main simulator page and the guardrail page.

## Background

The batch backtest already returns a `paths` array where each path carries `country`,
`is_complete`, and `has_failed` (`g_has_failed` on the guardrail page). The censored-aware
success rate the backend reports at the top of the panel can therefore be reproduced per country
entirely on the frontend — **no backend change required**.

### Censored-aware semantics (must match backend `backtest_batch.py`)

- **eligible (denominator)** = complete ∪ (incomplete ∧ failed) = `is_complete || has_failed`
- **succeeded (numerator)** = `is_complete && !has_failed`
- **excluded** = incomplete ∧ not-failed (insufficient data → dropped)
- **success_rate** = succeeded / eligible; `null` when eligible == 0

Invariant: summing per-country `eligible` and `succeeded` reproduces the panel's overall
denominator/numerator. This is the key consistency check for review.

## Components

### 1. `frontend/src/lib/country-success.ts` (pure, testable)

```ts
export interface CountrySuccessStatInput {
  country: string;
  is_complete: boolean;
  has_failed?: boolean;
  minWithdrawal: number; // Math.min(...withdrawals) for the relevant strategy
}

export interface CountrySuccessRow {
  country: string;
  total: number;            // all paths for the country
  eligible: number;         // denominator
  succeeded: number;        // numerator
  excluded: number;         // censored, not failed
  successRate: number | null;        // null when eligible === 0
  medianMinWithdrawal: number | null; // median over eligible paths; null when none
}

export function computeCountrySuccessStats(
  paths: CountrySuccessStatInput[],
): CountrySuccessRow[];
```

`medianMinWithdrawal` is computed over **eligible** paths only, to keep the denominator
consistent with the success-rate denominator.

### 2. `frontend/src/components/country-success-table.tsx` (presentational)

Props: `rows: CountrySuccessRow[]`, `countryLabel: (iso: string) => string`.

- Columns: `国家 | 成功率 | 路径数 (eligible/total) | 中位最小取款`.
- Default sort: success rate descending; rows with `successRate === null` sort last.
- Clickable headers toggle sort on country / successRate / eligible / medianMinWithdrawal.
- **best/worst highlight**: among rows with `eligible > 0`, the max-success-rate row gets a green
  tint and the min gets a red tint, with a small `最高`/`最低` tag. Highlight only renders when
  there are ≥ 2 such rows (ties: first in sort order wins the tag, acceptable).
- `React.memo`.

## Integration

Both pages render a new `<Card>` titled "各国成功率" inside the **aggregate** sub-tab
(`TabsContent value="aggregate"`), placed before the stats summary table. Rendered only when
`availableCountries.length > 1` (i.e. the pooled `country = "ALL"` run).

- Main page (`simulator-client.tsx`): map paths with
  `has_failed: p.has_failed, minWithdrawal: Math.min(...p.withdrawals)`.
- Guardrail page (`guardrail/page.tsx`): map paths with
  `has_failed: p.g_has_failed, minWithdrawal: Math.min(...p.g_withdrawals)` (guardrail strategy).

## i18n

New keys (en.json + zh.json), reusing existing `country` / `successRate` / `minWithdrawal`:

- `successByCountry` — card title ("各国成功率" / "Success Rate by Country")
- `successByCountryDesc` — one-line caption explaining eligible-denominator semantics
- `pathCountCol` — "路径数" / "Paths"
- `bestCountryTag` / `worstCountryTag` — "最高" / "最低"

Add under the namespaces each page already uses for its backtest strings.

## Out of scope (YAGNI)

- CSV export.
- Per-country funded ratio (needs trajectory data; per-country approximation would mislead).
- Bar chart.
- Backend changes.

## Verification

- `cd frontend && npx next build` and `npx eslint src/` clean.
- `computeCountrySuccessStats` logic verified with a throwaway `/tmp` script (deleted after).
- Manual: run a pooled (`ALL`) backtest on both pages; confirm per-country `eligible` sums equal
  the panel's overall denominator, and best/worst tags land on the right rows.
- Codex review on the final diff.
