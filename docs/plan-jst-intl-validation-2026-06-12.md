# Plan: JST Non-US Data Validation vs Real Investable Indices

**Date:** 2026-06-12
**Status:** Revised after Codex review (see §7)
**Trigger:** User request — validate JST non-US country data two ways:
(1) does a buy-and-hold portfolio seeded with MSCI EAFE's actual 1970 country
weights, built purely from JST per-country returns, reproduce the real MSCI
non-US return (the post-1970 `International Stock` column of FIRE_dataset)?
(2) per-country, is JST's annualized return comparable to the country's real
investable index (MSCI country index or equivalent)?

## 0. Context & prior art

- `data/FIRE_dataset_intl.csv` `International Stock` is **real MSCI EAFE (USD
  nominal, gross-of-fee, US-investor view) from 1970 onward**; pre-1970 is a JST
  `Global_Stock` backfill (not used as ground truth here).
- Prior study (2026-06-07, memory `project-intl-investability-calibration`)
  already validated **5 countries** (JPN/CHE since 1994-05, DEU/FRA/AUS since
  1987-12) against MSCI factsheet "Since" annualized gross USD returns: JST
  matched within ~±0.3pp. It also established:
  - FX conversion: `USD_ret = (1 + eq_tr) / fx_change - 1`,
    `fx_change = xrusd[t] / xrusd[t-1]` (xrusd = local per USD).
  - The +1.69pp 1970-2025 wedge of JST `Global_Stock` (linear-GDP-weighted
    15-country ex-US basket) vs MSCI EAFE is a **weighting/composition
    artifact**, not per-country data inflation.
- This task extends that to (a) an **aggregate cap-weight replication test**
  (new) and (b) **all 15 ex-US countries** instead of 5 (new), with USA as a
  16th control.

## 1. Data sources

| Piece | Source | Notes |
|---|---|---|
| JST per-country nominal equity TR, local ccy | `data/raw/JSTdatasetR6.xlsx` (`eq_tr`) + `data/raw/jst_extension_2021_2025.csv` | official JST ends 2020; 2021-2025 is our unofficial extension — **headline windows end 2020**, extension windows reported separately |
| FX (local per USD) | same files, `xrusd` | Eurozone legacy currencies already handled upstream |
| Real MSCI EAFE annual | `data/FIRE_dataset_intl.csv` `International Stock`, Year ≥ 1970 | ground truth for V1 |
| MSCI per-country monthly GR USD | `app2.msci.com .../getLevelDataForGraph` JSON endpoint, `index_variant=GRTR`, `currency_symbol=USD`, monthly | **anonymous access only returns data from 2000-12-29** (rolling ~25y window) → exact-matched per-country window = **2001-2025** |
| MSCI index codes | known: World 990100, EAFE 990300, Europe 990500, Pacific 990800, Japan 939200 | remaining 14 codes harvested via web search of `msci.com/indexes/index/<code>` pages; **every code independently validated** by correlating its 2001+ monthly returns against the matching iShares country ETF (yfinance: EWA EWK EWL EWG EDEN EWP EFNL EWQ EWU EWI EWJ EWN ENOR PGAL EWD + SPY for USA), require monthly corr ≥ 0.98 over the ETF's life |
| 1970 EAFE initial country weights | best public source, in order of preference: (a) published MSCI EAFE historical country-weight data (e.g. anniversary research, third-party charts citing MSCI), (b) end-1969/1970 equity market capitalizations from Ibbotson-Siegel-Love (1985) *World Wealth: Market Values and Returns*, (c) Rajan-Zingales (2003) 1970 stock-cap/GDP × World Bank 1970 nominal USD GDP | weights restricted to the 15 JST countries and renormalized; excluded EAFE members (Austria, Hong Kong, Singapore, ...) reported with their dropped weight; **weight-source uncertainty handled by sensitivity runs, not a single point estimate** |
| (optional) MSCI country factsheet "Since" rows | `msci.com/documents/10199/255599/msci-<country>-index.pdf` | extends window back to 1987/1994/1999 per country; only if PDFs fetch cleanly |
| (optional) DMS Yearbook real local CAGRs 1900-2024 | public UBS yearbook summary | century-horizon cross-compilation check; skip if paywalled |

## 2. Validation 1 — EAFE buy-and-hold attribution test (1970→)

A cap-weighted index with a fixed constituent set **is** a buy-and-hold
portfolio (price drift = cap drift), so seeding actual Dec-1969 EAFE weights
and letting them drift with JST per-country USD returns approximates the index
*excluding* reconstitution effects. **Framing (Codex F1): this is an
attribution / plausibility test, not an exact replication** — membership
changes, stock-level reconstitution, and the 2001-02 free-float transition all
create residuals unrelated to JST data quality. Conclusions are phrased as
"explains / fails to explain the GDP-weighting wedge", never as exact
reproduction.

Portfolio membership = countries actually in EAFE at Dec-1969 ∩ JST coverage
= 13 (AUS BEL CHE DEU DNK ESP FRA GBR ITA JPN NLD NOR SWE). FIN/PRT join MSCI
only in the late 1980s and are excluded from V1 (as they were from the real
1970 index); Austria/Hong Kong/Singapore are in EAFE but not in JST — their
launch weight mass is quantified and reported as a known bias bound (Codex F2,
feasible part: exact membership-drift decomposition needs proprietary MSCI
weight history; instead we (a) quantify excluded launch mass, (b) localize
divergence by decade, (c) widen verdict language accordingly).

Procedure:
1. `w_i,1969` = normalized 1970 EAFE weights over the 15 JST countries.
2. Wealth recursion in **nominal USD**, no rebalancing:
   `W_i,t = W_i,t-1 × (1 + r_i,t^USD)`; portfolio year-t return
   `= Σ W_i,t-1 r_i,t / Σ W_i,t-1`.
3. Compare vs `International Stock` (= real MSCI EAFE) on 1970-2025 and
   1970-2020:
   - CAGR difference (primary), per-decade CAGR table,
   - annual-return correlation + tracking RMSE,
   - terminal wealth ratio,
   - weight-path table (1970/1980/1990/2000/2010/2025) vs known EAFE history
     (e.g. Japan peak ~65% in 1989) as a face-validity check.
4. Reference lines: the engine's GDP-weighted `Global_Stock` (USA row), known
   to sit ~+1.7pp above EAFE — expectation: cap-weight buy-and-hold lands much
   closer to EAFE than the GDP-weighted series.
5. Sensitivity:
   - alternative weight sources from §1 (each candidate weight set),
   - annually-rebalanced-to-initial-weights variant (diagnostic only),
   - excluded-members effect: note EAFE additions (FIN 1988, PRT/IRL, HK/SG
     in index since 1969, GRC 2001-13, ISR 2010-) as expected drift sources.

Diagnostics before comparison: regress FIRE `International Stock` 2001-2025
against MSCI EAFE **GRTR vs NETR vs STRD** annual returns (endpoint data) to
pin down which variant the FIRE column actually is — this sets the expected
sign/size of any residual level gap (GR−NR ≈ 0.4-0.6pp for EAFE).

Success criteria (pre-registered, tightened per Codex F6):
- Verdict is based on the **band across weight sources + perturbations**, not
  a single point, and is reported alongside the terminal-wealth ratio.
- Band center |CAGR diff| ≤ 0.5pp over 1970-2020 AND TW ratio in [0.78, 1.28]
  (≈ ±0.5pp compounded 50y) ⇒ JST + real cap weights **explain the
  GDP-weighting wedge**; per-country JST levels consistent with the investable
  index.
- 0.5-1.0pp ⇒ consistent only with a **named, quantified** residual cause
  (variant mismatch, excluded-member mass, free-float transition).
- > 1.0pp or band width > 1.0pp ⇒ inconclusive/flagged — no validation claim.
- Weight perturbation (Codex F5): ±25% relative on JPN and GBR weights
  (renormalized) defines the band width reported with each weight source;
  weight sources are tiered by provenance quality.

## 3. Validation 2 — per-country JST vs real index

**Window A (primary, exact-matched): 2001-2025.**
For each of the 15 ex-US countries + USA control:
- JST: annual USD nominal return (eq_tr + xrusd; 2021-25 from extension —
  reported, plus a 2001-2020 official-only column).
- MSCI: country GRTR USD, calendar-year returns from monthly levels.
- Metrics: CAGR diff, annual corr, RMSE, worst single-year gap.
- Pipeline sanity: reproduce the prior study's 5-country factsheet numbers
  (JPN 3.30 vs 3.23 since 1994-05 etc.) before trusting new outputs.

**Window B (required best-effort, elevated per Codex F10): factsheet "Since"
windows** (1987-12 / 1994-05 / 1999-ish per country) for whichever factsheet
PDFs fetch cleanly — extends the check back another ~14 years for the big
markets.

**Window C (required best-effort, elevated per Codex F10): century real-local
CAGR** vs DMS yearbook (1900-2020/2024) — different compilation, catches gross
level errors in the deep history that MSCI can't see. If no public table is
obtainable, the report says so explicitly and scopes deep-history claims
accordingly (no silent skip).

**Claim-scoping map (Codex F10, critical):** per-country exact validation
covers 2001-2025 only; 1970-2000 per-country quality is supported *indirectly*
by the V1 aggregate (cap-weighted combination) plus Window B (1987+) and
Window C (century). The report must state explicitly that 1970s stagflation /
Bretton Woods aftermath / Japan-bubble era data is validated only at the
aggregate level and (if available) by DMS cross-compilation, not per-country
vs MSCI.

Verdict bands (annual CAGR diff, tightened per Codex F7): ≤0.5pp match;
0.5-1.0pp explainable **only with a documented caliber/timing cause**;
1.0-1.5pp provisional — fails pending decomposition; >1.5pp flagged.
Correlation gate: annual corr ≥ 0.90 expected for Dec-Dec-priced countries;
for annual-average-priced countries the corr is computed against **both**
Dec-Dec MSCI returns and annual-average MSCI returns (from monthly levels) —
whichever aligns better also *identifies* the country's JST pricing
convention (diagnostic bonus). A CAGR match with corr < 0.80 under both
alignments is not a pass.
Robustness sub-window: **2003-2025** (post free-float transition, Codex F9) —
2001-02 gaps are classified as index-methodology transition, not JST error.

Known caveats to document up front:
- JST equity pricing for several countries uses **annual-average** index
  levels (extension guide), MSCI uses Dec-end → annual correlations are
  structurally dampened for those countries; CAGR only suffers endpoint
  effects (~±0.3pp on 25y). Primary criterion is CAGR, corr is diagnostic.
- **xrusd timing convention (Codex F3): determine empirically before use** —
  spot-check JST xrusd vs known year-end vs annual-average market rates
  (e.g. JPY 1970-71 around the Smithsonian revaluation, GBP 1970s) and
  document which convention JST follows; align interpretation of annual
  deviations accordingly.
- MSCI = 85% free-float coverage, large+mid; JST = broad market academic
  series → small persistent caliber gap is expected and not a data error.
- GRTR (gross, no withholding) matches JST's gross dividend treatment. The
  GRTR/NETR/STRD diagnosis of the FIRE intl column is a **hard gate** before
  any V1 headline (Codex F4): if the column matches NETR, the expected GR−NR
  gap is removed from the verdict rather than counted as JST error.
- Worst-single-year gaps may reflect dividend/corporate-action timing rather
  than JST data error (Codex F8) — reported but not over-interpreted.

## 4. Deliverables

- `analysis/validate_jst_vs_msci.py` — single script, subcommands or flags for
  V1/V2; caches MSCI downloads under `analysis/output/msci_cache/` (raw MSCI
  levels stay local-only, not committed); deterministic, re-runnable.
- `docs/jst-intl-validation-2026-06-12.md` — 中文报告: methodology, all
  tables, verdicts per country, V1 conclusion, caveats.
- No simulator/product code touched. Data files untouched.

## 5. Execution order

1. Pipeline bootstrap: JST USD per-country series; reproduce prior 5-country
   factsheet numbers (sanity gate).
2. Harvest + validate MSCI country codes; download 2001-2025 GRTR.
3. V2 Window A tables.
4. FIRE intl column variant diagnosis (GRTR/NETR/STRD).
5. 1970 weights sourcing (search → fallback reconstruction); V1 run +
   sensitivities.
6. Optional windows B/C if cheap.
7. Report; Codex number-verification round; fix; finalize.

## 6. Risks

- **MSCI endpoint blocks/changes** → fall back to factsheet windows (B) as
  primary per-country evidence + ETF-based 1996-2025 NAV comparison (fees
  noted).
- **1970 weights not findable to better than ±few pp** → present V1 as a
  weight-band (run all candidate sets); the conclusion is robust if the band
  is narrow vs the GDP-weighted +1.7pp wedge.
- **Conflating extension (2021-25) quality with JST quality** → headline
  windows end 2020 everywhere; extension years shown separately.
- **Survivorship/composition drift in EAFE membership** → documented, treated
  as expected drift, quantified by the per-decade table rather than hidden in
  a single 55-year number.

## 7. Codex review log (2026-06-12)

Plan reviewed by Codex (gpt-5.5) before implementation. 10 findings, all
accepted (one in weakened form):

- **F1 (Major)** V1 reframed as attribution/plausibility test, never "exact
  replication" — §2 rewritten.
- **F2 (Major, accepted weakened)** exact membership-drift decomposition needs
  proprietary MSCI weight history; substituted launch-mass quantification +
  per-decade divergence localization + widened verdict language.
- **F3 (Minor)** xrusd timing convention determined empirically and
  documented — added to §3 caveats.
- **F4 (Note)** GRTR/NETR/STRD diagnosis kept as hard gate; variant mismatch
  removed from verdict rather than counted as JST error.
- **F5 (Major)** weight sources tiered by provenance; ±25% relative
  perturbation on JPN/GBR weights defines the reported band.
- **F6 (Major)** V1 bands tightened (0.5/1.0pp + TW-ratio + band-width
  criterion); "reproduce" language dropped.
- **F7 (Major)** V2 middle band split (0.5-1.0 explainable-with-cause /
  1.0-1.5 provisional-fail); correlation gate added with dual-alignment
  diagnostic for annual-average countries.
- **F8 (Minor)** worst-year gaps caveated against over-interpretation.
- **F9 (Major)** 2003-2025 post-free-float robustness sub-window added;
  2001-02 anomalies classified as index-methodology transition.
- **F10 (Critical)** claim-scoping map added: per-country exact = 2001+ only;
  deep history (1970-2000) validated only via aggregate V1 + Window B/C;
  Windows B/C elevated from optional to required-best-effort with explicit
  no-silent-skip.
