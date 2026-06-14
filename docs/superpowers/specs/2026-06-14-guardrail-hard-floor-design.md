# Guardrail Hard Consumption Floor — Design Spec

**Date**: 2026-06-14
**Status**: Approved (design), pending Codex cross-validation + implementation
**Branch**: `feat/guardrail-hard-floor`

## Problem

The risk-based guardrail strategy currently lets withdrawals be cut arbitrarily
low when the success-rate lookup says the portfolio is in trouble. "Failure" is
then judged *after the fact* via `compute_effective_funded_ratio`: any year whose
spending drops below `max(initial_withdrawal * consumption_floor,
consumption_floor_amount)` (default 50% of initial) is treated as an *effective
depletion*.

Two weaknesses motivated this work:

1. The post-hoc classifier is **binary and over-punitive**: a single transient
   dip to 49% in (say) year 29 fails the whole path, equal to being destitute
   for 20 years.
2. It does not model what a real retiree actually does: **stop cutting at a
   minimum living standard** (a hard floor) and let the portfolio absorb the
   risk instead.

## Decision (what we are building)

Add a **new, opt-in mode** to the guardrail strategy — a *behavioral hard floor*
— without removing or changing the existing post-hoc classifier behavior
(default stays exactly as today).

When the mode is **on**:
- Withdrawals are clamped: the strategy never plans to withdraw less than the
  floor. `wd = max(wd, floor_val)`.
- Success is judged by **pure portfolio depletion** (same semantics as the fixed
  / other strategies): did the portfolio hit \$0 before the horizon.
- A lightweight **"pinned at floor"** companion metric exposes lifestyle pain so
  that "miserable but solvent" paths are not silently scored as perfect
  successes.

When the mode is **off** (default): **zero behavioral change**; the existing
`compute_effective_funded_ratio` classifier is used exactly as today.

### Resolved design questions (the CF accounting)

The floor is on the **portfolio withdrawal `wd`** (the control variable the
guardrail adjusts), NOT on total consumption / standard of living.

- **"50% of what?"** → 50% of the initial annual portfolio withdrawal `wd₀`
  (`annual_wd`, real / inflation-adjusted, like all engine values). A constant
  real floor; no extra inflation handling.
- **Does the floor include custom income/expense CFs?** → **No.** The floor
  governs only how much is pulled from the portfolio. Income CFs (pensions) and
  expense CFs continue to flow through the portfolio exactly as today (expense
  before the depletion check, income after), and are not part of the floor
  formula.
- **Absolute floor (e.g. ¥500k) include CFs?** → **No**, same as above —
  `consumption_floor_amount` is a floor on the portfolio withdrawal alone.

Rationale: `wd` is the only knob the guardrail controls, so a hard floor is most
naturally a clamp on it (clean, testable). A pension already flows into the
portfolio and automatically lets `wd` stay above the floor longer, so its benefit
is captured by portfolio mechanics without folding it into the floor. "Total
consumption" is ambiguous in this engine because income CFs hit the portfolio,
not consumption directly; netting them in would conflict with the rest of the
engine's CF accounting. Under pure-depletion success, the old `wd + expense`
consumption metric no longer drives the verdict, so the simplest basis is also
the most self-consistent.

## Approaches considered

- **A (chosen)**: behavioral clamp on `wd` + pure-depletion success + "pinned"
  companion metric; depletion stays **terminal** (consistent with every other
  strategy in the engine). New `enforce_consumption_floor` flag reusing the
  existing `consumption_floor` / `consumption_floor_amount` level params.
- **B (deferred)**: as A, but also model post-depletion fallback income (true
  floor-and-upside — after the portfolio hits \$0 the retiree lives on pension /
  income CFs instead of \$0). More economically correct for retirees with
  guaranteed income (Codex: "portfolio zero ≠ consumption zero"), but it changes
  the **engine-wide "depletion is terminal" assumption**, would make this new
  option's depletion semantics *inconsistent* with fixed/other strategies (against
  the "same as the others" goal), and has a large blast radius + re-tuning cost.
  Logged as a separate future feature.
- **C (rejected)**: no behavioral clamp, just make the existing effective metric
  duration-aware. This was the earlier minimal-change idea the user set aside in
  favor of a real behavioral floor.

## Detailed design

### 1. Behavior — the floor clamp

In both `simulator/guardrail.py::run_guardrail_simulation` and
`run_historical_backtest`, inside the per-year loop, **after**
`apply_guardrail_adjustment` produces the new planned `wd`:

```python
floor_val = max(consumption_floor * annual_wd, consumption_floor_amount)
if enforce_consumption_floor:
    wd_unclamped = wd
    wd = max(wd, floor_val)
    floored_year = wd_unclamped < floor_val   # record for the companion metric
```

- Lower bound only — **upside is unrestricted**; the upper guardrail still raises
  `wd` normally when markets recover.
- The clamped `wd` becomes the state basis for the next year's guardrail logic
  (the retiree actually spends the floored amount; next year adjusts relative to
  it).
- The depletion-year cap `actual_wd = min(wd, max(value_after_growth, 0))` is
  retained — the floor bounds the *planned* withdrawal; if wealth genuinely runs
  out, `actual_wd` is still capped by available wealth and the path depletes.
- CFs unchanged: expense CFs applied before the depletion check, income CFs
  after; neither enters `floor_val`.

`floor_val` is computed once per simulation (uses `annual_wd`, the initial
withdrawal), not per year.

### 2. Success rate + "pinned at floor" companion metric

When `enforce_consumption_floor` is on:

- **Headline success = `compute_success_rate(traj_g, retirement_years)`**
  (pure depletion). The guardrail route currently reports
  `compute_effective_funded_ratio(...)` as the headline; in this mode it switches
  to the pure-depletion value. `funded_ratio` likewise uses the plain
  `compute_funded_ratio`.
- **Companion (new fields)**: from a per-path-year boolean `floored_year`
  (clamp actually bound, i.e. `wd_unclamped < floor_val`, counted only for years
  before the path depletes):
  - `pct_paths_floored`: fraction of paths with ≥1 floored year.
  - `median_floored_years`: median number of floored years among the paths that
    were ever floored (0 reported when no path is floored).

When off: headline + funded_ratio stay on the effective classifier exactly as
today; no companion fields populated (or returned as null/0).

The aggregation helper lives in `simulator/statistics.py` (e.g.
`compute_floor_exposure(floored_matrix, depletion_info)`), taking the boolean
matrix produced by the sim loop.

### 3. Scope + known limitation

- **In scope**: main MC projection (`/api/guardrail`), single-path historical
  backtest (`/api/guardrail/backtest`), and batch backtest
  (`/api/guardrail/backtest-batch`) — all route through
  `run_guardrail_simulation` / `run_historical_backtest`. The fixed-rate baseline
  comparator (`run_fixed_baseline`) is unaffected.
- **Sensitivity / scenarios endpoints**: pass the flag through so behavior is
  consistent, but the headline-metric switch follows the same rule.
- **Known limitation (documented, not fixed)**: the engine treats depletion as
  **terminal** — after the portfolio hits \$0, income CFs (pensions) also stop,
  so for a retiree with a pension "depletion" is modeled as \$0 total consumption,
  harsher than reality. This is exactly what approach B would address; it is out
  of scope here and noted as a future feature.

### 4. Schema + params

- Reuse existing `consumption_floor` (float, default 0.50) and
  `consumption_floor_amount` (float, default 0.0) as the floor *levels*.
- Add `enforce_consumption_floor: bool = False` to the guardrail request
  schemas (`GuardrailSimulationParams` and the backtest request models that
  carry guardrail params). Default `False` ⇒ fully backward compatible.
- Add companion response fields: `pct_paths_floored: float | None`,
  `median_floored_years: float | None` (and the guardrail-prefixed variants if
  the schema separates guardrail vs baseline, e.g. `g_pct_paths_floored`).

### 5. Frontend

- Guardrail page sidebar: a new toggle **「强制消费下限 / Enforce spending
  floor」**. The existing `consumption_floor` / `consumption_floor_amount` inputs
  are grouped under it. Toggle off ⇒ those inputs remain the post-hoc classifier
  (today's meaning); on ⇒ they become the behavioral floor level.
- Results: when on, headline shows the pure-depletion success rate plus a small
  "pinned at floor" readout (`pct_paths_floored`, `median_floored_years`).
- i18n keys in `messages/zh.json` + `messages/en.json`.
- TypeScript types in `src/lib/types.ts` mirror the schema additions; API client
  in `src/lib/api.ts` passes the flag.

### 6. Testing

- **Equivalence / regression**: with `enforce_consumption_floor=False`, outputs
  are element-wise identical to current behavior (protects the default path).
- **Clamp active**: a crash-sequence fixture where the unconstrained guardrail
  would cut below the floor — assert `wd` never drops below `floor_val`, and that
  the path depletes earlier than the free-cutting variant (the intended
  trade-off).
- **`floor_val = max(pct, amount)`**: cases where the percentage binds and where
  the absolute amount binds.
- **Companion metric**: `pct_paths_floored` / `median_floored_years` match a
  hand-computed fixture.
- **Historical backtest**: single-path + batch paths honor the clamp too.
- Run full `pytest tests/` and `(cd frontend && npx next build)` before merge.

## Out of scope / future

- Approach B (post-depletion fallback income / true floor-and-upside).
- Re-tuning the default guardrail params (`target=0.85`, etc.) for the new mode —
  those defaults were calibrated against the effective-classifier semantics. The
  new mode ships off-by-default; tuning its recommended params is follow-up
  research (would touch `guardrail-optimal-params-v2`).
