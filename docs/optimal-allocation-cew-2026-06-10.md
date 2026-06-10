# Optimal Allocation under the CEW-Primary Objective (2026-06-10)

First full application of the portfolio-optimization framework agreed on
2026-06-10 (Claude + Codex independent convergence):

```text
maximize    median CEW (CRRA gamma=2, time discount delta=0.02)
subject to  success_rate >= 0.90
            P(path funded_ratio < 0.5) <= 0.01   (severe-failure tail)
tie-break   consumption-path Ulcer Index (lower is better)
```

Sharpe is excluded from the objective (single-period, symmetric, liability-blind);
success rate serves as a constraint, not an argmax target (binary cliff metric,
saturates, MC-noisy); UPI is recast as a consumption-path Ulcer tie-break rather
than an asset-price statistic.

## Setup

| Item | Value |
|---|---|
| Data | JST pooled ALL, equal-probability, start 1900 |
| Horizon | 50 years, $1M initial, expense ratio 0.005/asset |
| Withdrawal | Risk-based guardrail, v2 tier-F family: upper=0.99, adj=0.05, mode=amount, mr=1 |
| Guardrail variants | target=0.80 / lower=0.70 (tier F) and target=0.85 / lower=0.75 (gap=10pp philosophy) |
| Grid | dom_stock/global_stock/dom_bond simplex, 10pp steps (66 allocations) |
| Sims | 2000 (grid), shared bootstrap across allocations (common random numbers), seed=42 |
| Scripts | `analysis/optimal_allocation_cew.py`, `analysis/optimal_allocation_cew_multiseed.py` |
| Output | `analysis/output/optimal_allocation/cew_{results,multiseed}.csv`, `cew_summary.md` |

## Results

### 1. target=0.80 is incompatible with the 90% success floor

Across the entire 66-allocation grid at 50y, the best realized success rate at
target=0.80 is **87.5%** (consistent with the ~13-14% baseline depletion rate
documented for tier E/F in the v2 study). Meeting `success_rate >= 0.90`
requires **target=0.85**. All results below are target=0.85 / lower=0.75.

### 2. Finalists (5 independent seeds + N=10,000 confirmation)

Single-seed grid leaders (20/80/00, 10/90/00, 10/80/10) failed replication:
1-2 of 5 independent seeds dropped below the 90% floor, with bad-seed
p10_CEW / p10_min_wd collapsing to $10-15K. Robust finalists (5/5 seeds >= 0.90),
confirmed at N=10,000 (stderr ±0.30pp), seed=777000:

| Alloc (Dom/Glob/Bond) | success | median CEW | init SWR | P(FR<0.5) | Ulcer (med) | P10 min wd |
|---|---|---|---|---|---|---|
| **30/70/00** | 90.31% | **$49,415** | **3.57%** | 1.35% | 0.0046 | $15,738 |
| **20/70/10** | 90.25% | $47,107 | 3.47% | **1.19%** | 0.0041 | $15,405 |
| 30/60/10 | 90.35% | $45,899 | 3.39% | 1.21% | **0.0035** | $16,040 |
| 20/80/00 (excluded) | 90.11% | $50,166 | 3.60% | 1.39% | 0.0047 | $14,705 |

### 3. Decision

- **Framework optimum: 30/70/00** — highest median CEW in the feasible set
  (+4.7% over runner-up, beyond noise). Independently matches the
  cross-strategy study's "ALL pool optimum 30/70/00" (2026-05-27).
- **Tail-robust alternative: 20/70/10** — gives up $2.3K/yr median CEW for the
  lowest severe-failure probability, smoother consumption drawdown, larger
  multi-seed margin, and a direct mapping to the China-resident profile
  (~20% A-shares/HK + 70% global UCITS + 10% short bonds/TIPS).

## Calibration findings

1. **The 1% severe-failure threshold is structurally infeasible at 50y pooled**
   (grid minimum ~1.2%, N=10000 minimum 1.19%). The threshold must be
   horizon-calibrated; ~1.5-2% is realistic at 50y, or switch to a CVaR form.
2. **Realized success under guardrail is allocation-insensitive** (90.1-91.0%
   across the feasible set): the guardrail's dynamic cuts equalize survival, so
   the optimization genuinely trades consumption level (CEW) against tail
   metrics — empirical support for not using success rate as the argmax target.
3. **MC noise discipline matters**: at 2000 sims the 90% floor has stderr
   ±0.7pp; the feasibility boundary sits inside the noise band. The single-seed
   grid winner changed after independent-seed replication.

## Bootstrap seed-overlap pitfall (discovered here)

`pregenerate_raw_scenarios` derives per-path rng as `default_rng(seed + sim_index)`
(`simulator/sweep.py`). Adjacent seeds therefore share 1999/2000 path streams —
five "different" seeds 42-46 produced identical success rates to 4 decimal
places. **Replication seeds must be spaced >= num_simulations** (e.g. 42, 5042,
10042, ...). This also means the v2 study's SEEDS=[42..46] cross-seed stability
evidence is void (its substantive conclusions rest on 54-env / 4-source checks,
which are unaffected). A product-level fix would be `SeedSequence(seed).spawn(n)`,
but that changes RNG semantics and breaks seed reproducibility — defer to a
reviewed change.

## Reproduction

```bash
python3 analysis/optimal_allocation_cew.py            # 66-alloc grid, ~40s
python3 analysis/optimal_allocation_cew_multiseed.py  # 5-seed finalists, ~15s
```

Codex review: commit 7007e6c reviewed, 1 P2 (per-seed tail gating in multiseed
aggregation) fixed in a590276.

Caveat: results exclude LTC tail risk — per the 2026-05-27 utility discussion,
ring-fence 10-15% of the portfolio as a separate conservative LTC fund before
applying the allocation above.
