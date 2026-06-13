# Factor Index Real Metrics & Value/Momentum UPI-Optimal Allocation (2026-06-13)

Inflation-adjusted (real) buy-and-hold comparison of US stocks/bonds and the
Kenneth French long-only factor portfolios over **1927–2025** (99 years, the
French factor-data start), plus the real-UPI-optimal allocation over the
investable factor sleeves.

**This is a single-path, in-sample, buy-and-hold study** — no Monte Carlo, no
simulator engine. It quantifies the *historical realized efficiency* of factor
tilts. It is **not** a FIRE withdrawal-sustainability optimum. Per
`memory/project-portfolio-optimization-objective.md`, UPI on asset prices is a
**tie-break input**, not the FIRE decision objective (that is guardrail-CEW on
the post-withdrawal trajectory). Treat the optima below as intuition pumps.

Source data: `memory/project-french-factor-data.md` (`data/factors/`).
Reproduce: `python3 analysis/factor_real_metrics_upi.py`.

## TL;DR

- **Net-of-cost real UPI ranking:** Large Momentum ≈ Small Momentum **0.56** >
  Small/Large Value **0.44** > Large/Small Neutral 0.37–0.40 > US broad market
  **0.36** > … > Small Growth **0.17** (the "black hole"). Value beats growth at
  both size tiers; the "size premium" is really a *small-value* premium.
- **In real terms, bonds and cash carry deep drawdowns** (US Bond −49.9%,
  T-Bills −47.7%) from the 1940s and 1970s inflation episodes. Real RF CAGR is
  only **0.28%**. "Cash is safe" is a nominal illusion.
- **Cost separates the bankable from the mirage.** Value premium is barely
  dented (Small Value −0.33pp); momentum pays a real toll but the premium
  survives; **micro-cap (Lo10) is destroyed by cost** (UPI 0.29→0.22), confirming
  it is uninvestable. **Value and momentum are the clear net winners**; size-tilted
  neutral sleeves edge broad market only thinly (Small Neutral 0.40 vs 0.36) at
  much deeper drawdowns, and pure small-cap/growth do not net-beat broad on UPI.
- **UPI-optimal 4-asset {Stock, Bond, Small Value, Large Momentum} = 0/55/15/30**
  (UPI 0.737). But this is a **drawdown-efficiency** optimum (heavy bonds), not a
  growth/FIRE optimum. Plain broad stock goes to **0%** because Large Momentum
  second-order-dominates it net of cost.
- **AQR's 50/50 value+momentum** holds for **long-short** factors (strongly
  negatively correlated, −0.5 to −0.65). Our **long-only** sleeves are **+0.78**
  correlated — the 50/50 diversification rationale largely evaporates.
- **UPI-optimal {Small Value, Large Momentum} = 20/80** (Sharpe-opt 21/79
  agrees; plateau 8–34% value; 50/50 only 6.5% below). But the **1976–2025**
  sub-period optimum drifts to **44/56 ≈ AQR's 50/50** — the more-investable
  modern era looks much more like 50/50.

## Data

| Series | Source | Notes |
|---|---|---|
| US Stock, US Bond | `data/FIRE_dataset.csv` | nominal; deflated here |
| Factor portfolios | `data/factors/headline_nominal_us.csv` | nominal + `us_inflation` |
| Momentum (BIG/SMALL HiPRIOR) | `data/factors/annual_nominal/us_size_momentum_2x3.csv` | gross VW |
| RF (T-bill) | `data/factors/annual_nominal/ref_ff3_factors_longshort.csv` | risk-free |

French series are gross value-weighted total returns. FIRE_dataset "US Stock" is
nominal. Window 1927–2025 is forced by the FF factor start (cannot extrapolate
to 1900). **Calendar-alignment diagnostic:** corr(FF-reconstructed market, FIRE
US Stock) = **0.9989** (≥0.99 asserted in-script; a one-year misalignment would
collapse it, so it doubles as proof the factor series align with the deflator).

## Method

```text
real   = (1 + nominal) / (1 + US_inflation) - 1          (Shiller CPI)
net    = (1 + real_gross) * (1 - incremental_cost) - 1   (annual expense drag)
UPI    = (real_CAGR% - real_RF_CAGR%) / UlcerIndex%       (Martin ratio)
Ulcer  = sqrt(mean(dd%^2)) over cumulative real-wealth path (incl. t0 = 1.0)
         dd = wealth / running_max - 1   (<= 0)
```

T-bills carry no incremental cost (real RF CAGR ≈ 0.28%). Portfolios are
annually rebalanced to fixed weights.

### Incremental cost over a broad-market index fund

Modern-ETF implementation lens (turnover × one-way cost + expense-ratio
premium). **Anchors** `small_value +0.30%` and `large_momentum +0.50%` are the
Codex-vetted values from `docs/factor-allocation-2026-06-13-plan.md`; the rest
are extrapolated by analogy.

| Sleeve | +cost | | Sleeve | +cost |
|---|--:|---|---|--:|
| Broad market / bond / cash | 0.00% | | Small Value | 0.30% |
| Large Value | 0.15% | | Small Neutral | 0.25% |
| Large Neutral / Growth | 0.10% | | Small Growth | 0.35% |
| Large-cap (Hi10) | 0.05% | | Small-cap (Lo20) | 0.20% |
| Large Momentum | 0.50% | | Micro-cap (Lo10) | 1.50% |
| | | | Small Momentum | 1.20% |

These are **flat annual drags** → optimistic for pre-1975 (fixed commissions,
wide spreads), most so for high-turnover momentum.

## Results

### Part 1+2 — Per-asset real metrics (gross → net of cost), 1927–2025

Sorted by net UPI.

Sharpe is the canonical excess-return form: mean(R−Rf) / σ(R−Rf), real.

| Asset | +cost | CAGR gross→net | Vol | MaxDD | Ulcer | UPI g→n | Sharpe |
|---|--:|--:|--:|--:|--:|--:|--:|
| Large Momentum | 0.50% | 10.14→**9.59%** | 21.9% | −50.8% | 16.7 | 0.61→**0.56** | 0.52 |
| Small Momentum | 1.20% | 13.42→**12.06%** | 28.3% | −70.0% | 21.2 | 0.66→**0.56** | 0.53 |
| Large Value | 0.15% | 9.00→8.84% | 25.6% | −71.1% | 19.2 | 0.46→0.44 | 0.44 |
| Small Value | 0.30% | 10.84→10.50% | 29.9% | −80.4% | 23.3 | 0.46→0.44 | 0.46 |
| Small Neutral | 0.25% | 9.42→9.14% | 26.5% | −71.1% | 22.2 | 0.42→0.40 | 0.45 |
| Large Neutral | 0.10% | 6.88→6.77% | 19.8% | −69.4% | 17.5 | 0.38→0.37 | 0.41 |
| US Stock (broad) | — | 6.96→6.96% | 19.5% | −57.9% | 18.5 | 0.36→0.36 | 0.43 |
| Large-cap (Hi10) | 0.05% | 6.75→6.69% | 18.8% | −52.5% | 20.6 | 0.32→0.31 | 0.43 |
| Large Growth | 0.10% | 7.00→6.90% | 20.2% | −54.9% | 22.2 | 0.31→0.30 | 0.43 |
| Small-cap (Lo20) | 0.20% | 8.32→8.10% | 34.7% | −85.0% | 30.0 | 0.27→0.26 | 0.36 |
| Micro-cap (Lo10) | 1.50% | 8.90→**7.27%** | 36.4% | −82.3% | 32.3 | 0.29→**0.22** | 0.34 |
| Small Growth | 0.35% | 5.63→5.26% | 30.1% | −80.9% | 29.9 | 0.18→0.17 | 0.30 |
| US Bond (10y) | — | 1.63→1.63% | 7.2% | −49.9% | 21.8 | 0.06→0.06 | 0.29 |
| T-Bills (RF) | — | 0.28→0.28% | 3.8% | −47.7% | 27.8 | 0.00→0.00 | — |

Takeaways: (1) momentum leads on drawdown-adjusted return; **large momentum has
the lowest drawdown (−50.8%) and Ulcer (16.7) of any equity sleeve**. (2) Value
premium is nearly cost-immune → bankable. (3) Micro-cap loses 1.63pp to cost →
mirage. (4) Small Growth is the black hole (5.26% net for 30% vol). (5) **Value
and momentum are the clear net winners**; the size-tilted neutral sleeves (Small
Neutral 0.40, Large Neutral 0.37) edge broad market (0.36) by a thin, noisy
margin at much deeper drawdowns, while pure small-cap (Lo20 0.26), micro-cap
(0.22) and growth do **not** net-beat broad on UPI.

### Part 3 — UPI-optimal 4-asset {Stock, Bond, Small Value, Large Momentum}

Net real, annual rebalance, 5% grid.

Net real correlations:

| | Stock | Bond | SmallVal | LgMom |
|---|--:|--:|--:|--:|
| Stock | 1.00 | 0.17 | 0.82 | 0.94 |
| Bond | | 1.00 | 0.08 | 0.12 |
| SmallVal | | | 1.00 | 0.78 |
| LgMom | | | | 1.00 |

**Optimum: 0% Stock / 55% Bond / 15% Small Value / 30% Large Momentum, UPI
0.737** (CAGR 6.1%, MaxDD −31.1%).

Plateau (UPI within 2% of max): Stock **0%**, Bond **45–60%**, Small Value
**5–20%**, Large Momentum **20–45%** — equity tilted ~2:1 to momentum.

Mechanisms: (a) broad stock → 0 because Large Momentum *second-order-dominates*
it net of cost (higher return **and** lower drawdown); (b) heavy bonds because
UPI rewards low drawdown — this is a **drawdown-efficiency** optimum, not a
growth optimum; (c) value+momentum diversification.

Sub-period robustness (period-consistent RF):

| Period | sub-period optimum | UPI | full-period optimum scores |
|---|---|--:|--:|
| 1927–1975 | 0/50/0/50 | 0.579 | 0.558 (−4%) |
| 1976–2025 | 0/40/30/30 | 1.563 | 1.451 (−7%) |

The full-period optimum is near-best in both halves → structurally robust. The
1976–2025 UPI is far higher mainly because of the 1982–2020 bond bull market.

### Part 5 — UPI-optimal 2-asset {Small Value, Large Momentum}

Net real, 1% grid. corr(SmallVal, LgMom) = **+0.775** (long-only, positive).

**Optimum: Small Value 20% / Large Momentum 80%, UPI 0.586** (Sharpe-optimal
21/79 agrees; CAGR 10.0%, MaxDD −56.1%). Plateau: Small Value **8–34%**.
**50/50 → UPI 0.548** (only 6.5% below the optimum).

| SmallVal | LgMom | UPI | CAGR | Vol | MaxDD | Sharpe |
|--:|--:|--:|--:|--:|--:|--:|
| 0% | 100% | 0.558 | 9.6% | 21.9% | −50.8% | 0.520 |
| **20%** | **80%** | **0.586** | 10.0% | 22.5% | −56.1% | 0.528 |
| 50% | 50% | 0.548 | 10.4% | 24.4% | −65.9% | 0.516 |
| 100% | 0% | 0.439 | 10.5% | 29.9% | −80.4% | 0.465 |

Momentum-heavy (not 50/50) because long-only sleeves are **+0.78** correlated
(no negative-correlation free lunch) and Large Momentum dominates on UPI (its
−51% drawdown vs Small Value's −80%, which UPI punishes).

**Regime split:**

| Period | UPI-optimal SmallVal / LgMom | UPI |
|---|---|--:|
| 1927–1975 | 0% / 100% (pure momentum) | 0.485 |
| 1976–2025 | **44% / 56% (≈ AQR 50/50)** | 1.324 |

The full-period 80/20 is pulled by the momentum-dominated first half; the modern
era looks much more like AQR's 50/50.

## On AQR's 50/50 value+momentum

AQR's canonical 50/50 (Asness–Moskowitz–Pedersen, *Value and Momentum
Everywhere*, 2013) applies to **long-short** factors, which are strongly
**negatively** correlated (−0.5 to −0.65; Japan −0.63) with roughly equal
Sharpe — equal-weight is then near risk-optimal and hedges illiquidity risk.
Our **long-only investable** sleeves share the long market beta and are **+0.78**
correlated, so that rationale largely evaporates. AQR's actual products (Style
Premia / QSPIX) are risk-weighted multi-style, not a literal 50/50.

## Caveats

1. **UPI-optimal ≠ FIRE-optimal.** The 4-asset optimum (6.1% real CAGR, 55%
   bonds) may be too conservative for a 30–50yr retirement. UPI is a tie-break,
   and should ultimately be computed on the *post-withdrawal trajectory*, not on
   asset prices.
2. **Bond UPI is inflated by 1982–2020** falling rates; not repeatable from
   today's yields.
3. **"Stock → 0" hinges on the momentum +0.50% cost.** Monthly-rebalanced
   academic momentum may cost more; if so, broad stock re-enters as cheaper beta
   and value's weight rises.
4. **Single 99-yr path, in-sample.** Point optima overfit; trust the plateaus
   and sub-period stability, not the exact weights.
5. **Costs are gross-of-tax** and assume modern fund execution; pre-1975 is
   optimistic for all tilts, momentum most.
6. **Small Value vs Large Momentum is size-mismatched** — small value carries
   extra small-cap drawdown that UPI penalizes. The AQR-comparable test is
   size-matched, risk-equalized **Large Value vs Large Momentum** (TODO).

## Reproduction

```bash
python3 analysis/factor_real_metrics_upi.py
# console summary + analysis/output/factor_real_metrics/{per_asset,opt4_top20,opt2_curve}.csv
```

Cost schedule lives in the `COST` dict at the top of the script.
