# Plan: Pre-1970 Non-US Equity Backfill for FIRE_dataset

**Date:** 2026-06-01
**Status:** Proposal — revised after Codex review (see §10)
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
| **linear-GDP JST ex-US = engine's `Global_Stock`** | ~8pp | 0.923 | **10.25%** |
| sqrt(GDP)-weighted JST ex-US (pooling weights only) | 8.05pp | 0.921 | 9.87% |
| Free-fit static weights (min squared tracking error) | 5.79pp | 0.964 | 10.44% |
| MSCI actual | — | — | **8.41%** |

> **Weighting clarification (Codex finding, §10):** the engine's
> `Global_Stock` column in `jst_returns.csv` is built by
> `scripts/build_dataset_from_jst.py` with **linear, time-varying full-GDP
> weights** (`weight = gdp/total_gdp`, `gdp = rgdpmad*pop`). The `sqrt(GDP)`
> weights in `simulator/config.py` are a *static* scheme used **only** for
> bootstrap country pooling — they are NOT how `Global_Stock` is computed. The
> backfill must follow the `Global_Stock` (linear-GDP) convention to stay
> consistent with the post-1970 international series the engine already uses.

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

**Step A — shape/correlation:** use the **existing `Global_Stock` series for the
`USA` row of `jst_returns.csv`** (linear time-varying GDP weights, USD nominal).
Critically, this column **already exists for 1872–1969 with zero missing values**
(98 pre-1970 rows verified) — so the shape basis needs **no reconstruction from
the raw xlsx**; we read it straight from the engine's own data file. It tracks
MSCI at corr 0.92 and preserves the real low US-correlation (~0.24 in the
1960s) — the property we are trying to restore.

**Step B — level calibration (the "reverse-engineering"):** apply a constant
multiplicative haircut `k` so the series' geometric level matches MSCI over the
overlap window:

```
intl_backfill[t] = (1 + global_stock_usa[t]) / (1 + k) - 1
```

where `(1 + k)` is the ratio of geometric mean gross returns over 1970–2025:

```
1 + k = geomean(1 + global_stock_usa | 1970-2025) / geomean(1 + msci | 1970-2025)
```

Measured numbers: `Global_Stock ≈ 10.25%`, `msci ≈ 8.41%` → **`k ≈ 1.69pp/yr`**.
(Note this is larger than the sqrt-GDP-basis 1.35pp, because `Global_Stock`'s
linear-GDP level is higher — using the correct basis matters.)

**Decision point (needs review/sign-off):** whether to use the full-window
measured wedge (`k ≈ 1.69pp`) or a **larger, conservative wedge** for the 1960s
given Finding 3 (wedge was likely bigger pre-1970). Per-decade wedges on the
`Global_Stock` basis: 1970s +2.03pp, 1980s +1.75pp, 1990s +2.82pp, 2000s +1.35pp,
2010s +0.84pp, 2020s +1.17pp. Candidate conservative value: the **two earliest
overlap decades** (1970s+1980s ≈ **+1.9pp**) as the pre-1970 estimate. Leaning
toward the conservative (larger) wedge, but flag explicitly. **Caveat (Codex,
§10):** the per-decade trend is noisy and non-monotonic (1990s is the *peak* at
+2.82pp, not the 1970s), so "wedge shrinks over time ⇒ 1960s wedge was bigger"
is a weak extrapolation, not a law. Treat the conservative wedge as a
sensitivity bound, not a point estimate.

With `k ≈ 1.69pp` the 1960s non-US series is **~5.5% CAGR** (vs US 7.73%); with
the conservative `k ≈ 1.9pp` it is **~5.3%**. Either way vol ~10% and
US-correlation ~0.24 — i.e. realistic level *and* realistic diversification. The
final series should be published as a **range / sensitivity**, not a single
point, given R1.

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
   - **Shape source = read `jst_returns.csv` `USA` `Global_Stock` directly** for
     the target pre-1970 rows (already complete, no missing values). No raw-xlsx
     reconstruction on the critical path.
   - Compute wedge `k` on the 1970–2025 overlap from the **same** `Global_Stock`
     series vs `International Stock` (parameterized: measured `1.69` vs
     conservative `~1.9`, exposed as a CLI flag with the measured value as
     default).
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

- **Sanity (optional cross-check):** a raw-xlsx reconstruction of the
  linear-GDP ex-US blend should reproduce `jst_returns.csv` `USA` `Global_Stock`
  to within float tolerance — confirms understanding of the pipeline. This is a
  *diagnostic*, not a dependency: the backfill reads `Global_Stock` directly.
- **Overlap check:** post-haircut series geomean over 1970–2025 ≈ MSCI geomean
  (by construction; assert |diff| < 5bp).
- **Correlation preserved:** pre-1970 corr(US, backfilled-intl) is in the
  0.15–0.35 band, NOT ~1.0.
- **No regression:** `pytest tests/` still green (data-only change; existing
  data-loader tests should still pass — confirm none hard-code pre-1970
  International==US).
- **Frontend build unaffected** (no schema/type change).

## 7. Risks & open questions

- **R1 — Unverifiable wedge pre-1970.** The wedge is measured 1970+ and assumed
  to hold for the 1960s. There is no MSCI ground truth before 1970 to validate,
  and the per-decade wedge is noisy/non-monotonic (peaks in the 1990s), so we
  cannot claim it "grows backward." *Mitigation:* publish a range (measured
  1.69pp ↔ conservative 1.9pp); label pre-1970 as a calibrated estimate, not
  real index data.
- **R6 — Block-bootstrap regime mixing.** The simulator samples *blocks* of
  consecutive years. After the backfill, pre-1970 blocks carry a US/non-US
  correlation of ~0.24 while post-1970 blocks carry ~0.58. Blocks that straddle
  1970 will splice two regimes. This is *more* realistic than the current
  correlation=1 everywhere, but consumers should know the pre-1970 segment has a
  structurally lower (and more uncertain) cross-correlation — it is not a flaw,
  but it changes diversification statistics in long-horizon draws.
- **R2 — How far back to trust JST USD reconstruction.** xrusd / eq_tr coverage
  and quality degrade for some countries pre-WWII. This plan's confident range
  is the **1960s**; replacing 1871–1959 may import noisier data. *Decision
  needed:* (a) backfill only 1960–1969 and leave ≤1959 as placeholder, or
  (b) backfill all pre-1970. Leaning (a) for the credible window unless review
  argues otherwise.
- **R3 — Static wedge vs time-varying.** A single `k` ignores that the wedge
  drifts. For a 10-year window (1960s) a constant `k` is acceptable; for a
  full 1871–1969 backfill it is more questionable (argues for R2 option a).
- **R4 — Weighting choice.** We use the engine's `Global_Stock` linear-GDP
  weighting (not MSCI cap-weighting, not sqrt-GDP). Accepted because (a) it
  tracks MSCI at corr 0.92, (b) the level is fixed by the haircut anyway, (c)
  cap weights for the 1960s are not in our data, (d) it is *consistent with the
  post-1970 international series the engine already serves*, so pre- and
  post-1970 use one convention. Alternatives rejected: free-fit weights
  (overfits, §2 finding 2); sqrt-GDP (pooling-only, not the `Global_Stock`
  basis — Codex §10).
- **R5 — Downstream consumers.** Anything that assumed pre-1970 US==Intl (e.g.
  cached results, docs, the 60/40 backtest numbers in memory) will shift.
  Acceptable and intended, but should be noted in the changelog.

## 8. Rollback

Single data file + single new script. Revert = `git checkout data/FIRE_dataset.csv`
and delete the script. No engine or schema dependency, so rollback is clean.

## 9. Decision summary (signed off 2026-06-01)

1. **Method:** `Global_Stock` (linear-GDP) JST ex-US shape, read directly from
   `jst_returns.csv`, + multiplicative level wedge. ✅ implemented
2. **Wedge size:** **1.69pp** single measured value (1970–2025 overlap). The
   `--wedge` CLI flag remains for sensitivity runs (e.g. 1.9pp), but the shipped
   dataset uses the auto-estimated 1.69pp. ✅ decided
3. **Backfill range:** **all pre-1970** (1872–1969; 1871 has no JST
   `Global_Stock` and keeps its placeholder). Downstream consumers filter by
   `data_start_year` at use time. ✅ decided
4. **Delivery: separate data source, NOT overwrite.** New
   `data/FIRE_dataset_intl.csv` + `data_source="fire_dataset_intl"` enum value,
   selectable in the frontend. Canonical `FIRE_dataset.csv` untouched, so the
   placeholder-vs-backfill effect stays A/B-able and provenance is clear.
   ✅ decided & implemented
5. **Data-only engine change, atomic write, idempotent, provenance in this
   doc + script docstring.** ✅ implemented

### Implementation map
- `scripts/backfill_pre1970_intl.py` — generates the variant CSV (idempotent,
  atomic, `--wedge` flag).
- `data/FIRE_dataset_intl.csv` — generated output (98 pre-1970 rows recalibrated).
- `simulator/data_loader.py` — `_fire_dataset_intl_path()` + dispatch in
  `load_returns_by_source` / `load_country_list_by_source`.
- `backend/schemas.py` — enum pattern `^(jst|fire_dataset|fire_dataset_intl)$`.
- `backend/deps.py`, `backend/routes/simulate.py` — treat the new source like
  `fire_dataset` for the country=USA forcing.
- `frontend/src/lib/types.ts` (8 unions), `sidebar-form.tsx` (Select + reset),
  `messages/{en,zh}.json` (`dataSourceFireIntl{,Desc}`).

## 10. Codex review log

Reviewed via `codex-review` on commit `5744d40`. Findings incorporated:

- **[P2 — accepted, material] Weighting basis was wrong.** Original plan used
  sqrt(GDP) as the shape basis and proposed validating it against
  `Global_Stock`. But `Global_Stock` is built with **linear time-varying GDP
  weights**, while sqrt(GDP) is a *static pooling-only* scheme. The sanity check
  would have failed and the calibration would have targeted the wrong series.
  *Fix:* switched the shape basis to the engine's actual `Global_Stock` series
  (read directly — it already covers 1872–1969 with no gaps), recomputed the
  wedge on that basis (1.35pp → **1.69pp**), and dropped raw-xlsx reconstruction
  from the critical path (now an optional diagnostic). See §2 note, §3, §5, §6.
- **Self-initiated hardening** (prompted by the review's scrutiny): flagged the
  non-monotonic wedge trend as a weak basis for "1960s wedge was bigger" (§3
  caveat, R1), and added **R6** on block-bootstrap regime mixing across the 1970
  boundary.
