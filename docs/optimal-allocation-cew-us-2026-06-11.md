# Optimal Allocation under CEW-Primary Objective — US FIRE Dataset (2026-06-11)

Re-run of the 2026-06-10 CEW-primary allocation study with the data source
switched from JST 16-country pooled (`country=ALL`, equal probability) to the
US-perspective `fire_dataset_intl`. Same objective:

```text
maximize    median CEW (CRRA gamma=2, time discount delta=0.02)
subject to  success_rate >= 0.90
            P(path funded_ratio < 0.5) <= 0.01   (severe-failure tail)
tie-break   consumption-path Ulcer Index (lower is better)
```

## TL;DR

- **The optimum flips from global-tilted to US-heavy: 80/20/00 (US/Intl/Bond)**,
  median CEW **$53.1K** at N=10,000 (vs JST pooled 30/70/00, $49.4K). The flat
  part of the answer is the **zero-bond band 60/40/00-90/10/00**: spread $1.1K
  (2.0%) at N=10,000, on par with MC noise (2×SE ≈ $1.1K). The 10%-bond
  variants (70/20/10 family) sit a distinct 4-5% lower in CEW and are
  **tail-robustness trade-offs, not part of the flat plateau**. All candidates
  pass all gates on all 5 seeds.
- **The flip is caused by the single-country US perspective, not by the
  dataset vendor**: a bridge run on JST data restricted to USA reproduces the
  same US-heavy ranking and rejects 30/70/00 (success 89.9% < floor).
- **1970 is the wrong start year.** The dataset actually spans 1871-2025; only
  the *real MSCI international series* starts in 1970. A 1970 start leaves a
  56-year window for 50-year horizons (heavily overlapped blocks, no 1929, no
  1966) and distorts the *composition*: the optimum becomes 100% US equity.
  Primary window chosen: **1900** (matched to the JST study for clean
  attribution); 1871/1929/1950/1970 run as sensitivities.
- target=0.85/lower=0.75 is again the preferred variant under the constrained
  search: at 0.80 the 90% floor forces bond-heavy allocations with far lower
  best-feasible CEW ($35.7K at 1900). (Not per-allocation Pareto dominance —
  bond-heavy allocations can score higher CEW at 0.80 thanks to the larger
  initial withdrawal.)
- Unlike the pooled study, the **1% severe-failure constraint is comfortably
  feasible** on US data (0.36-0.61% at N=10,000 vs pooled minimum ~1.2%).

## Data

`data/FIRE_dataset_intl.csv` (US Stock / International Stock / US Bond /
US Inflation, 1871-2025, Shiller-based):

- International Stock = real MSCI data from 1970; **pre-1970 backfilled with
  JST `Global_Stock`** (linear-GDP-weighted 15-country, USD) — per the user's
  requirement to fill the international leg with JST data.
- The backfill is **uncalibrated (wedge k=0)** — verified exact match to JST
  `Global_Stock` for 1872-1969. This is the deliberate outcome of the
  2026-06-07 investability calibration study (per-country JST ≈ MSCI ±0.3pp;
  the 1.7pp JST-vs-EAFE gap is composition/weighting, not data inflation),
  which reverted the earlier +1.69pp wedge.
- The single 1871 row keeps the US-copy placeholder (JST starts 1872);
  irrelevant for the 1900 primary window.
- Single-country moving-block bootstrap (blocks 5-15y), no pooling — USD
  inflation, bonds and perspective throughout.

Regime structure (real returns, diagnostic for the splice):

| Window | US geo | Intl geo | Bond geo | corr(US,Intl) |
|---|---|---|---|---|
| 1871-1899 | 7.9% | 8.2% | 5.5% | 0.27 |
| 1900-1969 | 6.4% | 6.4% | 0.1% | 0.35 |
| 1970-2025 | 6.8% | 4.3% | 2.4% | 0.69 |

The corr(US,Intl) 0.35 -> 0.69 shift at 1970 is consistent with the real
globalization regime change, though it also coincides with the JST -> MSCI
source splice, so the two cannot be fully separated; the bootstrap
intentionally samples across both regimes, exactly as the JST pooled study
mixes pre/post-war regimes. The 1871-1899 segment shows implausibly low intl
volatility (7.8% — thin early JST coverage), one more reason to prefer 1900
over 1871.

## Why not start at 1970 (user challenge answered)

| start | n source years | optimum (t=0.85) | median CEW | comment |
|---|---|---|---|---|
| 1871 | 155 | 80/20/00 | $56.0K | early intl data smoothed; inflates CEW |
| **1900** | **126** | **80/20/00** | **$51.7K** | **primary: matches JST study window; has 1929, 1966** |
| 1929 | 97 | 70/30/00 | $51.7K | plateau intact, point optimum wobbles |
| 1950 | 76 | 80/20/00 | $62.7K | most generous window — known trap (no 1929, golden era) |
| 1970 | 56 | **100/00/00** | $54.3K | composition distortion: kills diversification |

(single seed, N=2000, target=0.85; CEW = best feasible)

A 1970 start is only mildly optimistic in *level* (+5% CEW vs 1900) but badly
distorted in *composition*: with only the post-Bretton-Woods regime in the
pool, 100% US equity dominates and international stock looks pointless
(post-1970 intl geo return is just 4.3%). It also rests on 56 source years for
50-year paths — blocks recycle the same regime repeatedly. **Verdict: treat
1970 as a "post-1970 regime scenario", not a base case. 1900 is the primary
window.**

The **US-heavy zero-bond band (60-90% US stock) tops the feasible set in every
window except 1970** (1871, 1900, 1929, 1950); only the point optimum moves
inside it. That is the robust answer.

## Setup

Identical to the JST pooled study except the data source:
50y horizon, $1M, expense 0.005/asset, risk-based guardrail tier-F family
(upper=0.99, adj=0.05, mode=amount, mr=1), variants target=0.80/lower=0.70 and
0.85/0.75; 66-allocation 10pp simplex grid, N=2000 shared bootstrap (common
random numbers) seed=42; finalists replicated on 5 seeds spaced 5000
(42/5042/.../20042, seed-overlap pitfall respected); winners confirmed at
N=10,000 seed=777000.

## Results (primary window 1900, target=0.85)

### Grid + 5-seed replication

All 66 allocations pass both gates at target=0.85 (US data sits well above the
90% floor — realized success 91-92%). All 9 finalist candidates pass 5/5 seeds
on both gates (sr_min >= 0.909) — no JST-style boundary churn.

### N=10,000 confirmation (seed=777000)

| Alloc (US/Intl/Bond) | success | median CEW | p10 CEW | init SWR | P(FR<0.5) | Ulcer(med) | P10 min wd |
|---|---|---|---|---|---|---|---|
| **80/20/00** | 91.80% | **$53,063** | $30,053 | 3.79% | 0.49% | 0.0045 | $22,816 |
| 70/30/00 | 91.91% | $52,785 | $30,872 | 3.81% | 0.51% | 0.0052 | $23,803 |
| 90/10/00 | 91.74% | $52,514 | $29,353 | 3.73% | 0.61% | 0.0046 | $22,174 |
| 60/40/00 | 91.79% | $51,993 | $30,836 | 3.79% | 0.54% | 0.0052 | $23,755 |
| **70/20/10** | 92.16% | $50,876 | $30,557 | 3.74% | **0.36%** | **0.0041** | $23,923 |
| 80/10/10 | 91.96% | $50,770 | $29,887 | 3.71% | 0.36% | 0.0042 | $23,191 |
| 60/30/10 | 92.12% | $50,510 | $30,927 | 3.74% | 0.36% | 0.0046 | $24,509 |

- **Framework optimum: 80/20/00** — but the zero-bond band 60/40/00-90/10/00
  spans only $1.1K (2.0%) CEW, on par with MC noise; the point estimate should
  not be over-read.
- **Tail-robust alternative: 70/20/10** — a step down, not part of the flat
  band: gives up $2.2K/yr (4.1%) median CEW for the lowest severe-failure
  probability, lowest consumption Ulcer and higher P10 floor (same role
  20/70/10 played in the pooled study).

### target=0.80 is dominated (again)

At 1900, target=0.80 leaves only 13/66 feasible — all bond-heavy (best:
40/00/60, CEW $35.7K). Equity-heavy allocations draw higher initial rates
(4.1%+) and land at 87-88% success. Same qualitative conclusion as the pooled
study: with a 90% realized-success floor, **target=0.85 is the preferred
variant** (best-feasible CEW; not per-allocation dominance — see TL;DR).

## Bridge decomposition: what actually flipped the answer

Same window (1900+), same objective, finalists + the pooled winner
(single seed, N=2000):

| Run | data | sampling | best of finalists | 30/70/00 status |
|---|---|---|---|---|
| JST pooled (2026-06-10)* | JST 16 countries | pooled equal-prob | 30/70/00, $49.4K | **winner** (90.3%) |
| **JST-USA bridge** | JST, USA rows only | single country | 70/30/00, $56.0K | **infeasible** (89.9%, severe 1.5%) |
| fire_dataset_intl | Shiller US + MSCI/JST intl | single country | 80/20/00, $51.7K | not in top set |

\* Pooled-study headline numbers ($49.4K / 90.3%) are the N=10,000 confirm from
`docs/optimal-allocation-cew-2026-06-10.md`; the underlying grid/multiseed CSVs
(`cew_results.csv`, `cew_multiseed.csv`) were regenerated on 2026-06-11 (fixed
seeds) for traceability — regenerated 30/70/00 multiseed cew_mean $48.4K,
sr 5/5 >= 0.90, severe-fail 1.15-1.75% (consistent with the doc).

Moving from the pooled regime library to the US single-country lens is what
flips the answer to US-heavy; switching JST-USA -> Shiller/MSCI then *lowers*
CEW ~6-8% (Shiller series is the more conservative US dataset) while keeping
the US-heavy zero-bond class on top (point optimum shifts 70/30/00 ->
80/20/00, within the flat band). "Domestic" in the pooled study means "each sampled
country's own market" — its 30% domestic is **not** comparable to 30% US here.

Cross-source CEW numbers are therefore *perspective-conditional*, not a welfare
ranking: the US run answers "what if the future resembles the US past"
(survivor's path — the best-performing major market of the sample period); the
pooled run answers "what if the US is not guaranteed to repeat as the winner".

## Robustness

- **Block length** (3-7 / 5-15 / 10-20, finalists, 1900, single seed N=2000):
  the US-heavy class stays on top in all three, but the point optimum at 3-7
  is 70/30/00 — 80/20/00 shows severe_fail 1.05% there, nominally over the 1%
  gate (within single-seed noise, stderr ~0.22pp, but it means short blocks
  favor the slightly more diversified end of the band). Longer blocks raise
  both success and CEW. Class-level decision invariant; point optimum is not.
- **Start year**: plateau stable for all windows with >= 97 source years (see
  table above).
- **Severe-fail tail**: 0.36-0.61% at N=10,000 — the 1% constraint that was
  structurally infeasible at 50y pooled is comfortably met on US data.

## Caveats

1. **Survivorship/home-bias caveat dominates everything else**: this entire
   study conditions on the US historical record. For a China-resident global
   investor, the JST pooled result (30/70/00 family) remains the
   decision-relevant baseline; the US-lens result quantifies the home-bias
   premium *if* the future resembles the US past (~+$3.6K/yr median CEW and a
   +0.2pp initial SWR).
2. Guardrail initial rate is calibrated on the same scenario set it is
   evaluated on (product semantics, shared by all runs compared here);
   rankings unaffected, absolute success rates slightly flattered.
3. Guardrail failure-year withdrawals are recorded before depletion clipping
   (`simulator/guardrail.py` withdrawal loop) — may slightly inflate CEW on
   failed paths (~8% of paths, one year). Affects all allocations equally;
   flagged as product-level follow-up.
4. Median CEW + p10 CEW + tail constraints per the agreed framework; expected
   utility across paths not separately optimized.
5. LTC tail risk not modeled — ring-fence 10-15% separately (2026-05-27
   utility discussion).

## Reproduction

```bash
python3 analysis/optimal_allocation_cew_us.py             # 5-start grid, ~3min
python3 analysis/optimal_allocation_cew_us_multiseed.py   # 5-seed + 10k confirm
python3 analysis/optimal_allocation_cew_us_robustness.py  # bridge + block length
```

Outputs: `analysis/output/optimal_allocation/cew_us_{results,multiseed,confirm10k,confirm10k_tail,robustness}.csv`, `cew_us_summary.md`.

Codex cross-validation: plan reviewed pre-run (wedge description corrected to
k=0, bridge run and 1929/1950 windows + block-length sensitivity added on its
recommendation; formal break-point tests and 5pp grid refinement declined with
reasons — regime shift is economically real, and the optimum is a plateau wider
than seed noise).
