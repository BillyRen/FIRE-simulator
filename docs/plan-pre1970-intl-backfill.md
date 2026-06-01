# Plan: Pre-1970 Non-US Equity Backfill for FIRE_dataset

**Date:** 2026-06-01
**Status:** Proposal — pending review
**Author:** investigation triggered by "1960s 用美国代替非美靠谱吗 / 能否反推 MSCI"

## 1. Problem

`data/FIRE_dataset.csv` carries a real MSCI international-equity series
(`International Stock`, USD nominal, US-investor view) **only from 1970 onward**.
For every year before 1970, `International Stock` is a **placeholder equal to
`US Stock`** (verified: `International == US Stock` for all pre-1970 rows).

This placeholder is benign for US-only modeling, but it is wrong for any
multi-asset simulation that holds **both** US and international equity, because
it forces their correlation to **1.0** for the entire pre-1970 sample. The real
1960s US/non-US correlation was **~0.16–0.24** (near-uncorrelated), and real
non-US in the 1960s had **lower volatility** (~10% vs US ~15%). The placeholder
therefore **destroys the diversification structure** that pre-1970 history
actually contained, understating diversification benefit and overstating
combined-portfolio sequence risk.

Goal: replace the pre-1970 `International Stock` placeholder with a defensible
**real non-US equity series** that preserves the true co-movement structure
while matching MSCI's investable return *level*.

## 2. What the calibration experiment found (evidence base)

Source of truth for pre-1970 non-US returns: the **JST panel** (`data/raw/JSTdatasetR6.xlsx`
+ `data/raw/jst_extension_2021_2025.csv`), 15 developed countries ex-US, going
back to 1871. Per-country USD-nominal equity return reconstructed as
`usd_ret_i = (1 + eq_tr_i) * xrusd_i[t-1] / xrusd_i[t] - 1`.

Over the 1970–2025 **overlap window** (where both JST and MSCI exist):

| Series | Annual tracking RMSE vs MSCI | corr | own CAGR |
|---|---:|---:|---:|
| sqrt(GDP)-weighted JST ex-US (current engine convention) | 8.05pp | 0.921 | 9.87% |
| Free-fit static weights (min squared tracking error) | 5.79pp | 0.964 | 10.44% |
| MSCI actual | — | — | **8.41%** |

**Three findings that shape this plan:**

1. **The JST↔MSCI gap is a LEVEL wedge, not a weighting artifact.** Even the
   best-tracking linear combination of JST USD country returns compounds to
   **10.44%/yr** — *higher* than MSCI's 8.41%, and higher than sqrt(GDP). You
   cannot reweight your way to MSCI's level. The wedge is the classic
   academic-total-return-index vs investable-float-adjusted-index difference
   (breadth, no float adjustment, no fees, FX annual-average pricing).

2. **Free-fitting country weights overfits and does not generalize.** Fitted
   weights are wildly unstable across subperiods (DEU 0%→31%, JPN 21%→3%,
   AUS 24%→7%, BEL 14%→0% between 1970–97 and 1998–2025). Out-of-sample (fit
   1990–2025, test 1970–1989) the fitted RMSE (8.46pp) barely beats sqrt(GDP)
   (9.70pp) and is far worse than its own in-sample 5.79pp. 15 parameters on 56
   annual points → noise fitting. **Reject weight-refit.**

3. **The wedge is shrinking over time** (JST Global_Stock − MSCI by decade:
   1970s +2.2pp, 1980s +2.1pp, 1990s +3.0pp, 2000s +1.4pp, 2010s +0.9pp,
   2020s +1.3pp). Extrapolating *backward* to the 1960s implies the wedge was
   plausibly **≥ the 1970+ average**, i.e. raw JST overstates 1960s non-US by
   *at least* the measured amount. This matters for how big a haircut to apply.

## 3. Proposed method: calibrate the LEVEL, keep the SHAPE

Two-step construction for each pre-1970 year `t`, non-US series:

**Step A — shape/correlation:** use the **sqrt(GDP)-weighted JST ex-US** blend
(same convention the engine already uses for `Global_Stock`). It tracks MSCI at
corr 0.92, is stable, and preserves the real low US-correlation (~0.24 in the
1960s) — the property we are trying to restore.

**Step B — level calibration (the "reverse-engineering"):** apply a constant
multiplicative haircut `k` so the blend's geometric level matches MSCI over the
overlap window:

```
intl_backfill[t] = (1 + sqrtgdp_exus[t]) / (1 + k) - 1
```

where `(1 + k)` is the ratio of geometric mean gross returns over 1970–2025:

```
1 + k = geomean(1 + sqrtgdp_exus | 1970-2025) / geomean(1 + msci | 1970-2025)
```

With current numbers `sqrtgdp ≈ 9.87%`, `msci ≈ 8.41%` → `k ≈ 1.35pp/yr`.

**Decision point (needs review/sign-off):** whether to use the measured
1970–2025 wedge (`k ≈ 1.35pp`) or a **larger, conservative wedge** for the 1960s
given Finding 3 (wedge was likely bigger pre-1970). Candidate: use the
**average of the two earliest overlap decades** (1970s+1980s ≈ +2.15pp on the
Global_Stock basis, or the sqrt-GDP-basis equivalent) as a more honest pre-1970
estimate. Leaning toward the conservative (larger) wedge, but flag explicitly.

This yields a 1960s non-US series of roughly **5.0–5.7% CAGR** (vs US 7.73%),
with vol ~10% and US-correlation ~0.24 — i.e. realistic level *and* realistic
diversification.

## 4. Scope

- **Years replaced:** all `Year < 1970` rows of `International Stock` in
  `data/FIRE_dataset.csv`. (Open question: do we extend coverage earlier than
  the current dataset start, or only overwrite existing placeholder rows? FIRE
  already spans 1871+, so this is an *overwrite*, not an extension. No new years
  added.)
- **Columns touched:** **only** `International Stock`. `US Stock`, `US Bond`,
  `US Inflation` are untouched.
- **Engine semantics:** `International Stock` → `Global_Stock` (per
  `data_loader.py` column map). Values stay USD nominal; the engine deflates by
  `US Inflation` internally. No code change needed in the simulator — this is a
  **data-only** change.

## 5. Implementation steps

1. **New script** `scripts/backfill_pre1970_intl.py`:
   - Read raw JST xlsx (+extension), reconstruct per-country USD returns.
   - Build sqrt(GDP) ex-US blend for 1871–1969 (the script can cover the full
     pre-1970 span, not just the 1960s, since the placeholder is wrong for all
     of it — but see §7 open question on how far back the JST USD reconstruction
     is trustworthy).
   - Compute wedge `k` on the 1970–2025 overlap (parameterized: measured vs
     conservative).
   - Apply haircut, write the corrected `International Stock` column back into
     `data/FIRE_dataset.csv` for pre-1970 rows only. **Atomic write** (temp file
     + os.replace), preserve column order, float formatting consistent with the
     existing file.
   - Print a before/after diff summary (rows changed, decade CAGRs, US-corr).
2. **Idempotency:** running twice produces identical output. The script must
   *not* read the already-corrected column as if it were a placeholder — guard
   by always recomputing from raw JST, never from the current FIRE column.
3. **Provenance:** write a short header note / companion doc recording the wedge
   value used and the date, so the unofficial backfill is traceable (mirror the
   `scripts/DATA_UPDATE_GUIDE.md` discipline used for the 2021–2025 extension).

## 6. Validation / tests

- **Sanity:** reconstructed sqrt(GDP) ex-US blend over 1970–2025 must reproduce
  the existing `jst_returns.csv` `USA` `Global_Stock` column to within float
  tolerance (confirms the USD reconstruction matches the engine's own pipeline).
- **Overlap check:** post-haircut blend geomean over 1970–2025 ≈ MSCI geomean
  (by construction; assert |diff| < 5bp).
- **Correlation preserved:** pre-1970 corr(US, backfilled-intl) is in the
  0.15–0.35 band, NOT ~1.0.
- **No regression:** `pytest tests/` still green (data-only change; existing
  data-loader tests should still pass — confirm none hard-code pre-1970
  International==US).
- **Frontend build unaffected** (no schema/type change).

## 7. Risks & open questions

- **R1 — Unverifiable wedge pre-1970.** The wedge is measured 1970+ and assumed
  to hold (or grow) for the 1960s. There is no MSCI ground truth before 1970 to
  validate. *Mitigation:* use the conservative (larger) wedge; label pre-1970 as
  a calibrated estimate, not real index data.
- **R2 — How far back to trust JST USD reconstruction.** xrusd / eq_tr coverage
  and quality degrade for some countries pre-WWII. This plan's confident range
  is the **1960s**; replacing 1871–1959 may import noisier data. *Decision
  needed:* (a) backfill only 1960–1969 and leave ≤1959 as placeholder, or
  (b) backfill all pre-1970. Leaning (a) for the credible window unless review
  argues otherwise.
- **R3 — Static wedge vs time-varying.** A single `k` ignores that the wedge
  drifts. For a 10-year window (1960s) a constant `k` is acceptable; for a
  full 1871–1969 backfill it is more questionable (argues for R2 option a).
- **R4 — Weighting choice.** sqrt(GDP) is the engine convention but is itself
  *not* MSCI's cap-weighting. We accept it because (a) it tracks MSCI at
  corr 0.92, (b) the level is fixed by the haircut anyway, (c) cap weights for
  the 1960s are not in our data. Alternative considered and rejected:
  free-fit weights (overfits, §2 finding 2).
- **R5 — Downstream consumers.** Anything that assumed pre-1970 US==Intl (e.g.
  cached results, docs, the 60/40 backtest numbers in memory) will shift.
  Acceptable and intended, but should be noted in the changelog.

## 8. Rollback

Single data file + single new script. Revert = `git checkout data/FIRE_dataset.csv`
and delete the script. No engine or schema dependency, so rollback is clean.

## 9. Decision summary (for sign-off)

1. **Method:** sqrt(GDP) JST ex-US shape + multiplicative level wedge. ✅ proposed
2. **Wedge size:** measured 1.35pp vs conservative ~2pp — **needs decision**.
3. **Backfill range:** 1960–1969 only vs all pre-1970 — **needs decision**.
4. **Data-only, atomic write, idempotent, provenance documented.** ✅ proposed
