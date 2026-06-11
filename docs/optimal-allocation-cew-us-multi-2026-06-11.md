# Optimal Allocation with Gold + US Real Estate — US FIRE Dataset (2026-06-11)

Extension of `docs/optimal-allocation-cew-us-2026-06-11.md` (3-asset US-lens
study, optimum 80/20/00 US/Intl/Bond) adding **gold** and **US residential real
estate as an individual owned property** (user spec: volatility 1.5x the
housing index, extra 2%/yr maintenance cost). Four universes tested as paired
slices of one 5-asset grid: base / +gold / +housing / +both; start windows
1900 / 1950 / 1970. Same objective:

```text
maximize    median CEW (CRRA gamma=2, time discount delta=0.02)
subject to  success_rate >= 0.90
            P(path funded_ratio < 0.5) <= 0.01   (severe-failure tail)
tie-break   consumption-path Ulcer Index
```

## TL;DR

- **Housing is the robust addition; gold is a regime bet.** In the primary
  1900 window the winner is **60/20/00/20/00 (US/Intl/Bond/Housing/Gold)** —
  a 20% housing sleeve (funded out of US stock; bonds were already zero in the
  3-asset optimum) beats the 3-asset optimum on *every* metric at N=10,000:
  median CEW +2.8% ($53.7K vs $52.2K), p10 CEW +11%, severe-fail 0.25% vs
  0.42%, initial SWR 3.99% vs 3.71%. Gold at 1900 adds nothing at the median
  (N=10k: $52,237 vs $52,234, an exact tie; +0.6% on the N=2,000 grid) and
  drops out of the +both optimum.
- **Why the difference**: gold spends 1900-1970 under the gold-standard /
  Bretton Woods peg — real geometric return **−1.4%/yr** over those 71 years —
  and only becomes an asset post-1971 (+4.6% real, corr ≈ 0 with everything).
  Housing earns 5.3-6.2% real *at the index level in every regime*
  (3.4-4.3% after the 2% maintenance haircut) with nominal-return/inflation
  corr 0.42, and wins the optimization even carrying maintenance plus the
  1.5x idiosyncratic vol.
- **In post-float windows gold takes over**: at 1970 the optimum is
  **70/00/00/00/30** — at N=10,000 median CEW +22% over base ($67.5K vs
  $55.5K), p10 +60%, SWR 5.52% — and gold crowds out both intl stock and
  housing. At
  1950 the gold sleeve (10-20%) also wins (+6.5%). **Do not read these as base
  cases**: 1950 is the known most-generous window (no 1929), and 1970 has only
  56 source years where every 50y path repeatedly resamples the two great gold
  bulls (1971-80, 2000s). They answer "what if the future resembles the fiat
  era", not "what is robust across regimes".
- **Bands, not points** (1900, optimizer's-curse-aware): the housing plateau is
  **US 50-70 / Intl 10-20 / Bond 0 / Housing 10-30 / Gold 0-10**; the 5-seed
  CEW spread inside it (~$54.1-54.5K mean) is within noise. Bonds are zero in
  every winning allocation in every window — same as the 3-asset study.
- **Cross-check with the pooled 5-asset study** (b809d13, global lens,
  10/60-70/0/20-30/0): both lenses independently put **housing at 20-30% and
  bonds at 0**; the stock split (US-heavy vs global-heavy) remains the
  perspective-conditional part, exactly as in the 3-asset comparison.

## Data

6-column nominal panel merged on Year (complete 1891-2025):

| Column | Source | Notes |
|---|---|---|
| US Stock, Intl Stock, US Bond, Inflation | `data/FIRE_dataset_intl.csv` | identical to the 3-asset base study (Shiller US; Intl = MSCI 1970+, JST Global_Stock backfill pre-1970, wedge k=0) |
| Housing_TR | `data/jst_returns.csv` (USA) | nominal housing total return (price + net rental yield) |
| Gold | `data/jst_gold.csv` (USA) | USD gold price return (xrusd = 1) |

Deflation uses the FIRE_dataset_intl US Inflation (Shiller CPI) throughout,
including the two JST-sourced columns. CPI vendor diagnostic (Shiller vs JST
USA CPI, 1891-2025): mean diff +0.23pp, corr 0.71, single-year max |diff| 17%
(early-sample measurement differences). Means are close so level effects are
small, but year-level disagreement is real — housing/gold real returns are
CPI-source dependent in individual years (Codex review #1).

Real returns by regime (geometric / stdev):

| Window | US stock | Intl stock | US bond | Housing | Gold |
|---|---|---|---|---|---|
| 1900-1970 | +6.3%/20% | +6.0%/25% | +0.7%/8% | +5.3%/9% | **−1.4%**/8% |
| 1971-2025 | +6.9%/17% | +4.8%/20% | +2.2%/7% | +6.2%/4% | **+4.6%**/21% |
| 1900-2025 | +6.6%/19% | +5.5%/23% | +1.4%/8% | +5.7%/7% | +1.2%/15% |

Real cross-correlations 1900-2025: housing vs US stock 0.25, vs intl 0.05;
gold vs everything −0.08 to +0.10. Nominal-return/inflation corr: housing
0.42, gold 0.24, bonds −0.14.

## Setup

Identical to the prior CEW studies except the asset menu: 50y horizon, $1M,
single-country moving-block bootstrap (5-15y blocks), guardrail tier F
(target=0.85, lower=0.75, upper=0.99, adj=0.05, mode=amount, mr=1), N=2,000
grid seed=42 (shared bootstrap per window, common random numbers across all
allocations), 10pp 5-asset simplex (1001 combos). The four universes are w=0
slices of the same grid, so cross-universe comparisons are paired. Each
universe includes the base corner (the added sleeve may be 0%), so "+X best ≈
base best" means the added asset earns no allocation, not that it was
excluded.

Asset modeling (matches the pooled 5-asset study):

- Financial assets and gold: 0.5%/yr expense. **Housing: 2.0%/yr maintenance**
  (user spec) as expense on the nominal return.
- **Individual property**: idiosyncratic real-space noise with
  sigma = sqrt(1.5² − 1) × sigma_index ⇒ standalone vol = 1.5x index, corr
  with the index ~2/3; individual real return floored at −100%. sigma_index
  estimated per window: 1900: 7.3% → idio 8.2%; 1950: 3.6% → 4.0%;
  1970: 3.8% → 4.3%.
- Phase 2: 5 seeds (42/5042/.../20042, spacing ≥ N per the seed-overlap
  pitfall) at 1900. Phase 3: N=10,000 seed=777000 at 1900 and 1970.

The guardrail variant target=0.80 was not re-run (runtime scoping; shown
dominated in the 3-asset study — that finding is not re-verified in 5-asset
space).

## Results — primary window 1900

### Universe comparison (best feasible, N=2,000 grid)

| Universe | Best alloc (US/In/Bd/Ho/Au) | median CEW | p10 CEW | success | severe | init SWR |
|---|---|---|---|---|---|---|
| base | 80/20/00/00/00 | $53,245 | $30,344 | 91.5% | 0.5% | 3.79% |
| +gold | 80/10/00/00/10 | $53,563 | $31,891 | 92.2% | 0.6% | 3.94% |
| +housing | **60/20/00/20/00** | $54,895 | $33,339 | 91.6% | 0.4% | 4.10% |
| +both | 60/20/00/20/00 (gold drops out) | $54,895 | $33,339 | 91.6% | 0.4% | 4.10% |

Feasibility is near-universal on US data (1000/1001 combos pass both gates),
so the binding question is the CEW ranking, not the constraints.

### 5-seed replication (21 candidates, all 5/5 robust on both gates)

Top of the cross-seed mean-CEW ranking is an unbroken block of housing
allocations: 70/10/00/20/00 ($54.5K), 60/20/00/20/00 ($54.4K),
60/10/00/30/00 ($54.2K), 70/20/00/10/00 ($54.1K), 50/20/00/30/00 ($54.1K) —
spread $0.4K, far inside seed noise. The best gold-only candidate
(80/10/00/00/10, $53.1K) and the 3-asset optimum (80/20/00/00/00, $53.0K) sit
~$1.3-1.4K below the housing block. (On the single-seed grid, mixed
housing+gold variants such as 70/10/00/10/10 at $54.1K land inside the
housing block's range; they were not part of the multiseed set.)

### N=10,000 confirmation (seed=777000)

| Alloc | success | severe | median CEW | p10 CEW | init SWR |
|---|---|---|---|---|---|
| **60/20/00/20/00** | 92.32% | 0.25% | **$53,695** | $33,027 | 3.99% |
| 70/10/00/20/00 | 92.31% | 0.22% | $53,672 | $32,645 | 3.94% |
| 80/10/00/00/10 | 92.02% | 0.40% | $52,237 | $31,580 | 3.85% |
| 80/20/00/00/00 (3-asset opt) | 91.85% | 0.42% | $52,234 | $29,643 | 3.71% |
| 70/30/00/00/00 | 91.81% | 0.46% | $51,948 | $30,327 | 3.75% |

The 20% housing sleeve is a **dominance move, not a trade-off**: vs the
3-asset optimum it raises median CEW (+2.8%), p10 CEW (+11%), success
(+0.5pp), initial SWR (+0.28pp ≈ +$2,800/yr on $1M) and halves the
severe-fail tail. The two housing finalists are statistically tied — read the
answer as the **band US 50-70 / Intl 10-20 / Housing 10-30 / Bond 0 /
Gold 0-10**, not a point. 10% gold is CEW-neutral-to-slightly-positive with a
better tail than base (80/10/00/00/10 p10 +6.5% vs 80/20) — the same
"tail variant" role it played in the pooled study, but it is not needed once
housing is in.

(3-asset baseline note: this harness reproduces the prior study's 80/20/00
within RNG-stream noise — $52.2K vs $53.1K at 10k, different bootstrap code
path, same window/seed conventions; all paired comparisons here use the same
stream so deltas are clean.)

## Results — 1950 and 1970 windows (regime scenarios)

| Window | base best | +gold best | +housing best | +both best |
|---|---|---|---|---|
| 1950 | 80/20/00/00/00, $64.0K | 80/00/00/00/20, **$68.2K** | 80/10/00/10/00, $64.6K | = +gold |
| 1970 | 100/00/00/00/00, $55.3K | 70/00/00/00/30, **$67.7K** | 70/00/00/30/00, $58.7K | = +gold |

N=10,000 confirmation at 1970: 70/00/00/00/30 — success 93.1%, severe 0.04%,
median CEW $67.5K (+22% over 100% US $55.5K), p10 CEW $49.7K (+60%), initial
SWR 5.52%. Housing-only 70/00/00/30/00: $58.9K (+6%), severe 0.06%.

Reading: in fiat-era windows gold is the single biggest CEW lever in the whole
five-asset menu — a 20-30% sleeve lifts the initial SWR by 0.8pp (1950) to
1.6pp (1970) because
its zero-correlation, inflation-spiking profile precisely fills the 1970s
stagflation hole that kills equity-only paths. But both windows carry the
composition-distortion caveats from the base study (1950: golden-era window
without 1929; 1970: 56 source years, heavy block recycling), and the gold
result additionally *conditions on the two great gold bulls recurring*. The
1900 window — which prices in 71 years of gold being pegged — is the honest
base case for a "will hold for 50 years" decision; there gold's contribution
is ~zero at the median. 1950/1970 results are exploratory (multi-seed
replication was run at 1900 only; 1970 finalists were confirmed at N=10k).

Housing, by contrast, survives every window (+1% to +6% CEW, always with a
better tail), which is what makes it the structural recommendation.

## Caveats

1. **JST Housing_TR is an index total return** (price appreciation + net
   rental yield per the JST/Rate-of-Return-on-Everything methodology, which
   already nets running costs from gross rents at the index level). The user's
   2%/yr maintenance is applied *on top*, as the incremental owner cost. If
   you read Housing_TR as fully net of owner costs this double-counts
   maintenance and the housing results are conservative; if you read it as
   gross it may still be too generous. Treat the housing sleeve size
   (20-30%) as first-order, not precise.
2. **Individual-property model is first-order**: 1.5x index vol via i.i.d.
   idiosyncratic noise omits local-market persistence, liquidity/transaction
   costs, lumpiness (you cannot hold 23.7% of a house), concentration, and
   leverage. The UPI study's literature calibration suggests even 1.5x may
   understate effective single-property risk on the heavily smoothed US index
   (index vol post-1950 is only ~4%).
3. **sigma_index is calibrated per window on the full future window**
   (hindsight); cross-window housing comparisons partly reflect recalibrated
   vol (1900: 8.2% idio vs 1950/1970: ~4%), not pure regime differences. Note
   housing wins at 1900 *despite* the doubled idio sigma.
4. Block length fixed at 5-15y (product default; the 3-asset study's
   block-length sensitivity showed class-level decisions invariant). CPI
   vendor mix per the Data section. Results conditional on guardrail tier F,
   gamma=2, delta=0.02, 0.5%/2.0% expense assumptions.
5. Survivorship/home-bias caveat from the base study applies unchanged: this
   is the US-lens answer. For the China-resident global investor the pooled
   5-asset result (10/60-70/0/20-30/0) remains the decision baseline — and its
   housing conclusion is the same.
6. N=2,000 grid feasibility near the 1% severe-fail line is noisy (~20 paths);
   all headline calls were re-confirmed at N=10,000 where severe-fail margins
   are wide (0.2-0.4% vs the 1% gate).

## Reproduction

```bash
python3 analysis/optimal_allocation_cew_us_multi.py   # all 3 phases, ~20 min
```

Outputs: `analysis/output/optimal_allocation/cew_us_multi_{results,multiseed,confirm10k}.csv`, `cew_us_multi_summary.md`.

Codex cross-validation: two rounds. (1) Plan reviewed pre-run (12 findings;
CPI diagnostic added as an action item, housing-TR cost semantics /
first-order dispersion model / per-window sigma hindsight / block-length
scoping / 1950-exploratory labeling adopted as caveats; shared-grid slicing
and 1970-as-regime-scenario endorsed). (2) Numeric verification post-run: all
result tables, multiseed means, regime statistics and correlations reproduced
from the CSVs/raw data; five wording/scope mismatches found and fixed
(housing funded from US stock not bonds; gold median tie at N=10k; 1970 TL;DR
numbers aligned to the 10k run; SWR lift range 0.8-1.6pp; index-level vs
post-maintenance housing returns disambiguated; plateau band widened to
housing 10-30%).
