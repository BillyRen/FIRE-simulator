# CEW-Primary Optimization with Housing + Gold (2026-06-10)

Extension of `docs/optimal-allocation-cew-2026-06-10.md` from 3 financial
assets to 5: domestic_stock / global_stock / domestic_bond / **housing** /
**gold**. Same objective: max median CEW (gamma=2, delta=0.02) s.t.
success_rate >= 0.90, tie-break consumption Ulcer; same engine (pooled ALL
equal-prob 1900+, 50y, guardrail target=0.85 / lower=0.75 / upper=0.99 /
adj=0.05 / amount / mr=1).

## Asset modeling (user spec)

- **Housing = individual property**: JST `Housing_TR` index plus idiosyncratic
  real-space noise raising total vol to 1.5x the index
  (sigma_idio = sqrt(1.5^2-1) * 0.1184 = 0.1324, implies corr ~2/3 with index),
  individual real return floored at -100%, **2.0%/yr maintenance** as expense.
  Same method as `analysis/multi_asset_allocation.py` v3.
- **Gold**: `data/jst_gold.csv` local-currency nominal returns, 0.5%/yr cost.
- Financial assets: 0.5%/yr expense, as before.
- Data universe: 16 countries with complete housing+gold columns from 1900
  (DEU 100y, ITA 98y, PRT 94y, others ~120-126y). Slightly different sample
  than the 3-asset run, so comparisons use this grid's own 3-asset corner.

## Results (alloc = DS/GS/DB/H/G)

### Optimum plateau: ~10/60-70/0/20-30/0, statistically tied on CEW

High-N (10,000 sims) finalists, all 5/5 independent seeds >= 90%:

| Alloc | success | med CEW | p10 CEW | init SWR | P(FR<0.5) | Ulcer | P10 min wd |
|---|---|---|---|---|---|---|---|
| **10/70/00/20/00** | 90.63% | $52,675 | $28,574 | 3.86% | 1.12% | 0.0032 | $20,922 |
| 00/70/00/30/00 | 90.34% | $52,827 | $27,876 | 3.92% | 1.23% | 0.0032 | $19,565 |
| 10/60/00/30/00 | 90.58% | $52,327 | $29,211 | 3.91% | 1.05% | 0.0029 | $21,479 |

Primary pick: **10/70/00/20/00** — top multi-seed mean CEW; among the tied
plateau it leans least on the most-model-suspect asset (housing).

### Tail-robust alternative with gold: 10/60/00/20/10

Multi-seed confirmed (5/5): mean CEW $51,704 (-3% vs winner), but best
worst-decile profile of the whole feasible set — p10_CEW $30,014,
P10 min withdrawal $22,874, severe-fail 1.23%, Ulcer 0.0030.

### Key findings

1. **Housing replaces bonds entirely**: bond weight is 0 in 42 of the top-50
   feasible CEW allocations (rest 10%). Even at 1.5x vol + 2% maintenance,
   individual housing dominates bonds as the diversifier (inflation-linked
   real asset vs nominal bonds in a 125y sample with inflation regimes).
2. **Housing optimal weight 20-30%** — not the 40-90% of the index scenario
   (multi-asset study 2026-05-31); the user's vol/cost haircuts pull it to a
   realistic minority allocation.
3. **Gold ~0-10%**: zero in the CEW optimum, but a 10% sleeve is the single
   best worst-decile improver (p10_CEW +4-5%, P10 min wd +9%) for -3% median
   CEW. Regime caveat from the 2026-05-31 study still applies: gold's value
   is concentrated in the post-1971 fiat era.
4. **vs 3-asset corner (same universe)**: best 3-asset = 10/90/00/00/00 with
   CEW $51.1K @ 90.15%; the housing winner adds ~+5% CEW and +0.3pp SWR
   (3.97% vs 3.66% at seed 42) with better tails. The previous 3-asset
   recommendation 30/70/00 fails the 90% floor in this universe at seed 42
   (89.65%) — the floor sits inside sample noise, reinforcing the multi-seed
   discipline.
5. **Feasible set balloons**: 511/1001 combos pass the 90% floor (vs 21/66 in
   3-asset) — real-asset diversification makes the constraint much easier.

## Caveats (decision-relevant)

- **Annual frictionless rebalancing of housing is assumed** — unrealistic for
  a directly held property (cannot sell 3% of an apartment; guardrail cuts
  cannot harvest housing). Treat the housing sleeve as REIT-like or as an
  upper bound on direct ownership.
- JST Housing_TR likely still overstates investability (smoothed national
  index, no transaction/vacancy costs beyond the 2% maintenance, no leverage
  modeling). The 1.5x vol + 2% cost haircut narrows but does not close this.
- Success-floor margins (90.3-90.6% at N=10000) remain ~1-2 sigma above 0.90;
  the qualitative ranking is stable across 5 seeds, exact feasibility of any
  single allocation is not razor-sharp.
- Severe-fail tail (P(FR<0.5)) bottoms ~1.05% — the 1% framework default is
  still binding-everywhere at 50y; unchanged calibration conclusion.

## Reproduction

```bash
python3 analysis/optimal_allocation_cew_multi.py   # 3 phases, ~10 min
```
