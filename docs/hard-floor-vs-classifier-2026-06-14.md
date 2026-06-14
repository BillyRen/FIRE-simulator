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

### Floor = 70% (a binding floor)

Re-running with `--floor 0.70` — the delta widens sharply, especially in the
historical backtest:

| Config | MC OLD | MC NEW | **MC Δ** | BT OLD | BT NEW | **BT Δ** | pinned% (MC) |
|---|---|---|---|---|---|---|---|
| Pooled 30y | 87.3% | 90.6% | **+3.3 pp** | 89.7% | 97.1% | **+7.4 pp** | 11.4% (med 5y) |
| USA 30y | 89.2% | 92.7% | +3.5 pp | 96.9% | 100.0% | +3.1 pp | 9.8% (med 5y) |
| Pooled 50y | 84.1% | 89.0% | **+4.9 pp** | 88.3% | 98.6% | **+10.3 pp** | 14.1% (med 9y) |
| USA 50y | 86.4% | 90.4% | +4.0 pp | 100.0% | 100.0% | 0.0 pp | 12.1% (med 8y) |

At 70% the floor is genuinely binding: 10–14% of MC paths get pinned (median
8–9 years at 50y). The old classifier fails most of them (backtest success
collapses to 88–90%), while the pure-depletion headline stays ~98–99%. The MC
decomposition at pooled 50y is metric-only +9.3 pp vs behavior −4.4 pp — i.e.
the hard floor creates materially more true ruin, masked by no longer penalizing
the spending crash. (USA 50y backtest stays 0 pp: US history never cut below
70% even over 50-year windows.)

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

A higher floor (e.g. 70%) or a more aggressive withdrawal rate binds far more
often and widens the delta materially — see the 70% table above.

## At a 70% floor: which criterion is more appropriate?

Independent analysis by Claude and Codex (no shared priors) converged. Verdict:
**at a 70% floor neither A nor B is "correct"; the right answer hinges on whether
the 70% is backed by non-portfolio income** — and in most un-backed cases 70%
should not be a hard threshold at all.

**Consensus points:**

1. **A has a logical flaw, not just conservatism.** The policy lets withdrawals
   be cut below 70% freely, yet the failure metric fails any path that does so —
   it uses one rule's *behavior* to trigger another rule's *penalty*. At 70% this
   mislabels many "pinched for a few years but never broke" paths as failures
   (backtest success drops to 88–90%).
2. **B's +3.3–4.9 pp is not reduced risk — it is a redefinition of failure.** The
   behavior Δ (−3 to −4 pp) shows the hard floor manufactures *more true ruin*; it
   only reads higher because it stops penalizing the lifestyle crash.
3. **"Pinned at 70% then ruined" is usually worse than "cut to 50% but never
   broke."** Spending flexibility is the very mechanism that prevents ruin
   (sequence-of-returns risk); hard-pinning a high floor turns a *reversible*
   pinch into *irreversible* depletion. Exception (a non-linear threshold): if 50%
   breaches a survival/dignity/healthcare line, then 50% itself is unacceptable —
   which makes this a value judgment about what 70% *is* (preference, subsistence,
   or contractual obligation), not a statistical one.
4. **The engine's "depletion is terminal, pensions stop too" assumption overstates
   B's ruin** (in reality you fall back to guaranteed income, not to zero). So the
   current B is, ironically, pessimistic on the ruin it does report.
5. **70% is too high for a generic floor** — it leaves too little room for bad
   sequences and force-accelerates depletion on unlucky paths.

**Decision by case:**

| The 70% is… | More appropriate | Why |
|---|---|---|
| Backed by pension/SS/annuity (~covers 70%) | **B (hard floor + pure depletion)** | This is the correct floor-and-upside form: the floor was never the portfolio's job. But model post-depletion fallback income (direction B) or B reads pessimistically on ruin. |
| Pure preference, no backstop | **Neither as a hard 70% threshold** | A is logically inconsistent + over-punitive; B is dangerous (more true ruin, 10–14% pinned 8–9 yrs then $0). Instead: lower the hard floor to ~50% (survival) and treat 70% as a *soft* warning line via the pinned-at-floor metric. |

**The "third criterion" both reviewers independently pointed to** is the real fix:
on depletion, fall back to a guaranteed-income track rather than terminal zero, and
layer spending (essential / important-flexible / discretionary) with a separate
indicator per layer — instead of one 70% cliff. This is direction B + the known
limitation already logged in the design spec.
