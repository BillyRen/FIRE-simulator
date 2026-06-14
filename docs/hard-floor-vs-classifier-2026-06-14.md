# Hard Consumption Floor vs Post-hoc Classifier — Headline Success Delta

**Date**: 2026-06-14
**Script**: `analysis/hard_floor_vs_classifier.py`
**Feature**: `enforce_consumption_floor` (see `docs/superpowers/specs/2026-06-14-guardrail-hard-floor-design.md`)

## Question

For a 50% consumption floor, how much does the guardrail **headline success rate**
move when switching from the existing **post-hoc classifier** (free cut + "any year
spending < floor ⇒ path failed") to the opt-in **behavioral hard floor** (clamp
`wd ≥ floor` + pure-depletion success)? In both Monte Carlo and historical backtest.

## Setup

Seed 42, 5000 MC paths, blocks 5–15, data from 1900. Guardrail params: target 85%,
upper 99 / lower 60, adj 0.10 (amount), baseline 3.3%, allocation 30/70/00
(domestic/global/bond). `annual_withdrawal` is inverse-solved from the portfolio at
target 85% — identical across enforce on/off (the inverse solve is floor-independent),
so the two modes are directly comparable.

- **OLD headline** = effective success of the free-cut run (today's UI number:
  depletion OR any year < 50% of initial = fail).
- **NEW headline** = pure-depletion success of the hard-floor run (new UI number:
  only running out of money = fail).
- **metric-only Δ** = (free-cut pure-depletion) − OLD — isolates relaxing the
  `<floor = fail` rule.
- **behavior Δ** = NEW − (free-cut pure-depletion) — isolates the clamp causing
  earlier depletion.

## Results

| Config | MC OLD | MC NEW | **MC Δ** | BT OLD | BT NEW | **BT Δ** | pinned% (MC) |
|---|---|---|---|---|---|---|---|
| Pooled 30y | 91.2% | 92.3% | **+1.0 pp** | 97.7% | 98.3% | +0.6 pp | 4.8% (med 3y) |
| USA 30y | 93.2% | 93.9% | **+0.6 pp** | 100.0% | 100.0% | 0.0 pp | 3.3% (med 3y) |
| Pooled 50y | 89.6% | 91.6% | **+2.0 pp** | 98.8% | 99.6% | +0.8 pp | 8.0% (med 7y) |
| USA 50y | 91.0% | 92.6% | **+1.6 pp** | 100.0% | 100.0% | 0.0 pp | 6.8% (med 6y) |

### MC delta decomposition (pooled 50y, the largest)

| Component | Δ |
|---|---|
| metric-only (relax `<50% = fail`) | +3.9 pp |
| behavior (clamp → earlier depletion) | −1.8 pp |
| **net (NEW − OLD)** | **+2.0 pp** |

## Findings

1. **The headline difference is small** — MC **+0.6 to +2.0 pp**, historical backtest
   **0 to +0.8 pp**. Same order of magnitude as MC sampling noise.
2. **The new mode always reads slightly higher**, because the old classifier also
   fails "pinched but never broke" paths, while the new headline only counts true
   ruin.
3. **The gap widens with horizon** — ~+1 pp at 30y, ~+2 pp at 50y. Longer sequences
   hit the floor more (pinned paths 3–5% → 7–8%, median pinned years 3 → 6–7).
4. **Historical backtest barely moves** — US history never got bad enough to cut
   below 50% (0% pinned); only a few pooled bad sequences produce +0.8 pp.

## Caveat: small delta ≠ equivalent methods

The two approaches measure *different* failures; the small net delta is a near-cancellation:
the ~5–8% of paths the old classifier failed for dipping below 50% mostly become
"**solvent but pinned at floor**" under the new mode (median 6–7 years pinned at 50y),
and only a minority become true depletions (behavior Δ). That pinned cohort — the
lifestyle pain the old binary flag lumped into "failure" — is what the new
**pinned-at-floor** companion metric surfaces instead.

A higher floor (e.g. 70%) or a more aggressive withdrawal rate would bind far more
often and widen the delta materially. Re-run with `--floor 0.70` to see this.
