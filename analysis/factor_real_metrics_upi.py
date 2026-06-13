"""Factor index real metrics + value/momentum UPI-optimal allocation (2026-06-13).

Question
--------
Over 1927-2025 (Kenneth French factor data start), compare US stocks/bonds and
the long-only factor portfolios on INFLATION-ADJUSTED (real) buy-and-hold terms:
annualized return (CAGR), volatility, max drawdown, Ulcer Index, UPI (Martin
ratio), Sharpe. Then find the real-UPI-optimal allocation over the investable
sleeves {US Stock, US Bond, Small Value, Large Momentum}, and over the two
factor sleeves {Small Value, Large Momentum} alone.

This is a SINGLE-PATH, in-sample, buy-and-hold study (no Monte Carlo, no
simulator engine). It quantifies the historical realized efficiency of factor
tilts; it is NOT a FIRE withdrawal-sustainability optimum. Per
project-portfolio-optimization-objective, UPI on asset prices is a tie-break
input, not the FIRE decision objective (which is guardrail-CEW on the
post-withdrawal trajectory). Treat the optima here as inputs / intuition pumps.

Data
----
  data/factors/headline_nominal_us.csv                       factor portfolios, nominal + us_inflation
  data/FIRE_dataset.csv                                      US Stock / US Bond (nominal)
  data/factors/annual_nominal/us_size_momentum_2x3.csv       BIG/SMALL HiPRIOR (momentum)
  data/factors/annual_nominal/ref_ff3_factors_longshort.csv  RF (risk-free, T-bill)
All French series are gross VW total returns (no fees). FIRE_dataset US Stock is
nominal (portfolio.py deflates internally). Window 1927-2025 forced by FF start.

Method
------
  real   = (1 + nominal) / (1 + US_inflation) - 1          (Shiller CPI, product convention)
  net    = (1 + real_gross) * (1 - incremental_cost) - 1   (annual expense drag)
  UPI    = (real_CAGR% - real_RF_CAGR%) / UlcerIndex%      (Martin ratio)
  Ulcer  = sqrt(mean(dd%^2)) over cumulative real-wealth path (incl. t0 = 1.0),
           dd = wealth / running_max - 1  (<= 0)
  RF (T-bills) carries NO incremental cost. Real RF CAGR ~= 0.28%.

Incremental cost over a broad-market index fund (modern-ETF implementation lens;
turnover x one-way cost + expense-ratio premium). Anchors small_value +0.30% and
large_momentum +0.50% are the Codex-vetted values from the factor-allocation
plan (docs/factor-allocation-2026-06-13-plan.md); the rest are extrapolated by
analogy. These are flat annual drags -> OPTIMISTIC for pre-1975 (fixed
commissions / wide spreads), most so for high-turnover momentum.

Calendar-alignment diagnostic: assert corr(FF-reconstructed market, FIRE US
Stock) >= 0.99 (verified 0.9988 @ 1927-2025). A one-year misalignment collapses
this correlation, so it doubles as proof the factor series align with the
product's deflator year-by-year.

Outputs: analysis/output/factor_real_metrics/{gross,net,opt4,opt2}.csv + console.

Caveats
-------
- Single historical path, in-sample -> point optima overfit; we report plateaus
  and 1927-1975 / 1976-2025 sub-period stability instead of trusting one number.
- Costs are gross-of-tax and assume modern fund execution; the early decades are
  optimistic for ALL tilts, momentum most.
- 4-asset UPI optimum is a DRAWDOWN-EFFICIENCY optimum (heavy bonds), not a
  growth / FIRE-sustainability optimum; bond UPI is inflated by the 1982-2020
  secular rate decline (forward-looking optimistic).
- Small Value vs Large Momentum is size-mismatched; the AQR-comparable test is
  size-matched, risk-equalized large value vs large momentum (TODO).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "analysis" / "output" / "factor_real_metrics"

WINDOW = (1927, 2025)

# Incremental annual cost over a broad-market index fund (see module docstring).
COST = {
    "US Stock (broad)": 0.000,
    "US Bond (10y)": 0.000,
    "T-Bills (RF)": 0.000,
    "US Mkt (FF)": 0.000,
    "Small Value": 0.0030,
    "Small Neutral": 0.0025,
    "Small Growth": 0.0035,
    "Large Value": 0.0015,
    "Large Neutral": 0.0010,
    "Large Growth": 0.0010,
    "Micro-cap (Lo10)": 0.0150,
    "Small-cap (Lo20)": 0.0020,
    "Large-cap (Hi10)": 0.0005,
    "Large Momentum": 0.0050,
    "Small Momentum": 0.0120,
}


def _slice(df: pd.DataFrame) -> pd.DataFrame:
    lo, hi = WINDOW
    out = df[(df.Year >= lo) & (df.Year <= hi)].reset_index(drop=True)
    return out


def load_series() -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Return {name: gross real return array}, inflation array, year array."""
    fire = _slice(pd.read_csv(ROOT / "data/FIRE_dataset.csv"))
    head = _slice(pd.read_csv(ROOT / "data/factors/headline_nominal_us.csv"))
    mom = _slice(pd.read_csv(ROOT / "data/factors/annual_nominal/us_size_momentum_2x3.csv"))
    ff3 = _slice(pd.read_csv(ROOT / "data/factors/annual_nominal/ref_ff3_factors_longshort.csv"))

    years = fire.Year.values
    for d, label in ((head, "headline"), (mom, "momentum"), (ff3, "ff3")):
        if not np.array_equal(d.Year.values, years):
            raise ValueError(f"year axis mismatch: {label}")

    infl = fire["US Inflation"].values

    def real(nom):
        return (1.0 + np.asarray(nom, float)) / (1.0 + infl) - 1.0

    series = {
        "US Stock (broad)": real(fire["US Stock"].values),
        "US Bond (10y)": real(fire["US Bond"].values),
        "T-Bills (RF)": real(ff3["RF"].values),
        "US Mkt (FF)": real(head["mkt"].values),
        "Small Value": real(head["small_value"].values),
        "Small Neutral": real(head["small_neutral"].values),
        "Small Growth": real(head["small_growth"].values),
        "Large Value": real(head["large_value"].values),
        "Large Neutral": real(head["large_neutral"].values),
        "Large Growth": real(head["large_growth"].values),
        "Micro-cap (Lo10)": real(head["size_smallest_decile"].values),
        "Small-cap (Lo20)": real(head["size_small_quintile"].values),
        "Large-cap (Hi10)": real(head["size_biggest_decile"].values),
        "Large Momentum": real(mom["BIG HiPRIOR"].values),
        "Small Momentum": real(mom["SMALL HiPRIOR"].values),
    }

    # Calendar-alignment diagnostic (see docstring).
    corr = np.corrcoef(series["US Mkt (FF)"], series["US Stock (broad)"])[0, 1]
    if corr < 0.99:
        raise ValueError(f"calendar misalignment: corr(FF mkt, FIRE US Stock)={corr:.4f} < 0.99")
    print(f"[diag] corr(FF mkt, FIRE US Stock) = {corr:.4f} (>=0.99 OK; calendar aligned)")

    return series, infl, years


def net_of_cost(name: str, gross_real: np.ndarray) -> np.ndarray:
    fee = COST[name]
    return (1.0 + gross_real) * (1.0 - fee) - 1.0


def cagr(r: np.ndarray) -> float:
    r = np.asarray(r, float)
    return float(np.prod(1.0 + r) ** (1.0 / len(r)) - 1.0)


def metrics(r: np.ndarray, rf_real: np.ndarray, rf_cagr: float) -> dict:
    r = np.asarray(r, float)
    vol = float(r.std(ddof=1))
    wealth = np.concatenate([[1.0], np.cumprod(1.0 + r)])
    dd = wealth / np.maximum.accumulate(wealth) - 1.0
    maxdd = float(dd.min())
    ulcer = float(np.sqrt(np.mean((dd * 100.0) ** 2)))
    c = cagr(r)
    upi = (c * 100.0 - rf_cagr * 100.0) / ulcer if ulcer > 0 else float("nan")
    # Canonical Sharpe (Sharpe 1994): mean / std of the EXCESS return. With a
    # time-varying real RF, sigma(R - Rf) != sigma(R); using excess-return vol
    # matters for low-vol sleeves (e.g. bonds move with RF -> lower excess vol).
    excess = r - rf_real
    ex_sd = excess.std(ddof=1)
    sharpe = float(excess.mean() / ex_sd) if ex_sd > 0 else float("nan")
    return dict(cagr=c, vol=vol, maxdd=maxdd, ulcer=ulcer, upi=upi, sharpe=sharpe,
                best=float(r.max()), worst=float(r.min()))


# --------------------------------------------------------------------------- #
# Part 1+2: per-asset gross vs net real metrics                                #
# --------------------------------------------------------------------------- #
def per_asset_table(series, rf_real, rf_cagr) -> pd.DataFrame:
    rows = []
    for name, g in series.items():
        n = net_of_cost(name, g)
        mg, mn = metrics(g, rf_real, rf_cagr), metrics(n, rf_real, rf_cagr)
        rows.append(dict(asset=name, cost=COST[name],
                         cagr_gross=mg["cagr"], cagr_net=mn["cagr"],
                         vol=mn["vol"], maxdd=mn["maxdd"], ulcer=mn["ulcer"],
                         upi_gross=mg["upi"], upi_net=mn["upi"], sharpe_net=mn["sharpe"],
                         best=mg["best"], worst=mg["worst"]))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Part 3: UPI-optimal 4-asset {Stock, Bond, SmallVal, LgMom}                    #
# --------------------------------------------------------------------------- #
def _simplex(step: int):
    for a in range(0, 101, step):
        for b in range(0, 101 - a, step):
            for c in range(0, 101 - a - b, step):
                yield np.array([a, b, c, 100 - a - b - c], float) / 100.0


def optimize_4asset(series, rf_real, rf_cagr, years, step=5) -> pd.DataFrame:
    names = ["Stock", "Bond", "SmallVal", "LgMom"]
    cols = ["US Stock (broad)", "US Bond (10y)", "Small Value", "Large Momentum"]
    A = np.vstack([net_of_cost(c, series[c]) for c in cols]).T  # (years, 4)

    rows = []
    for w in _simplex(step):
        m = metrics(A @ w, rf_real, rf_cagr)
        rows.append({**{names[i]: w[i] for i in range(4)}, **m})
    df = pd.DataFrame(rows).sort_values("upi", ascending=False).reset_index(drop=True)

    corr = np.corrcoef(A.T)
    print("\n[4-asset] net real correlations:")
    print("          " + "".join(f"{n:>10}" for n in names))
    for i, n in enumerate(names):
        print(f"{n:>9} " + "".join(f"{corr[i, j]:>10.2f}" for j in range(4)))

    best = df.iloc[0]
    print(f"\n[4-asset] UPI-optimal: Stock {best.Stock:.0%} / Bond {best.Bond:.0%} / "
          f"SmallVal {best.SmallVal:.0%} / LgMom {best.LgMom:.0%}  "
          f"UPI {best.upi:.3f}  CAGR {best.cagr:.1%}  MaxDD {best.maxdd:.1%}")
    plat = df[df.upi >= best.upi * 0.98]
    print("[4-asset] plateau (UPI within 2% of max):")
    for c in names:
        print(f"    {c:>9}: {plat[c].min():.0%}-{plat[c].max():.0%} (median {plat[c].median():.0%})")

    # sub-period robustness
    half = years <= 1975
    print("[4-asset] sub-period UPI-optima:")
    for lbl, mask in [("1927-1975", half), ("1976-2025", ~half)]:
        sub = max(_simplex(step),
                  key=lambda w: metrics((A @ w)[mask], rf_real[mask], cagr(rf_real[mask]))["upi"])
        u = metrics((A @ sub)[mask], rf_real[mask], cagr(rf_real[mask]))["upi"]
        full_here = metrics((A @ best[names].values)[mask], rf_real[mask], cagr(rf_real[mask]))["upi"]
        print(f"    {lbl}: {sub[0]:.0%}/{sub[1]:.0%}/{sub[2]:.0%}/{sub[3]:.0%} "
              f"(UPI {u:.3f}); full-period optimum scores {full_here:.3f} here")
    return df


# --------------------------------------------------------------------------- #
# Part 5: UPI-optimal 2-asset {SmallVal, LgMom}                                 #
# --------------------------------------------------------------------------- #
def optimize_2asset(series, rf_real, rf_cagr, years) -> pd.DataFrame:
    SV = net_of_cost("Small Value", series["Small Value"])
    LM = net_of_cost("Large Momentum", series["Large Momentum"])
    corr = float(np.corrcoef(SV, LM)[0, 1])
    print(f"\n[2-asset] corr(SmallVal, LgMom) net real = {corr:.3f}")

    rows = []
    for i in range(101):
        w = i / 100.0
        m = metrics(w * SV + (1 - w) * LM, rf_real, rf_cagr)
        rows.append({"SmallVal": w, "LgMom": 1 - w, **m})
    df = pd.DataFrame(rows)

    opt_upi = df.loc[df.upi.idxmax()]
    opt_shp = df.loc[df.sharpe.idxmax()]
    plat = df[df.upi >= opt_upi.upi * 0.98]
    print(f"[2-asset] UPI-optimal: SmallVal {opt_upi.SmallVal:.0%} / LgMom {opt_upi.LgMom:.0%}  "
          f"UPI {opt_upi.upi:.3f}  CAGR {opt_upi.cagr:.1%}  MaxDD {opt_upi.maxdd:.1%}")
    print(f"[2-asset] Sharpe-optimal: SmallVal {opt_shp.SmallVal:.0%} / LgMom {opt_shp.LgMom:.0%} "
          f"(Sharpe {opt_shp.sharpe:.3f})")
    print(f"[2-asset] plateau (UPI within 2% of max): SmallVal {plat.SmallVal.min():.0%}-{plat.SmallVal.max():.0%}")
    print(f"[2-asset] 50/50 UPI = {df.loc[df.SmallVal == 0.5, 'upi'].iloc[0]:.3f}")

    half = years <= 1975
    print("[2-asset] sub-period UPI-optimal SmallVal weight:")
    for lbl, mask in [("1927-1975", half), ("1976-2025", ~half)]:
        best = max(range(101),
                   key=lambda i: metrics((i / 100 * SV + (1 - i / 100) * LM)[mask],
                                         rf_real[mask], cagr(rf_real[mask]))["upi"])
        u = metrics((best / 100 * SV + (1 - best / 100) * LM)[mask],
                    rf_real[mask], cagr(rf_real[mask]))["upi"]
        print(f"    {lbl}: SmallVal {best/100:.0%} / LgMom {1-best/100:.0%} (UPI {u:.3f})")
    return df


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    series, infl, years = load_series()
    rf_real = series["T-Bills (RF)"]
    rf_cagr = cagr(rf_real)
    lo, hi = WINDOW
    n = len(years)
    print(f"\nReal (inflation-adjusted), {lo}-{hi} ({n} yrs). "
          f"Real RF CAGR {rf_cagr*100:.2f}%, inflation CAGR {cagr(infl)*100:.2f}%.")

    tbl = per_asset_table(series, rf_real, rf_cagr)
    tbl.to_csv(OUT / "per_asset.csv", index=False)
    pd.set_option("display.width", 160, "display.max_columns", 20)
    print("\n[per-asset] gross vs net real metrics (sorted by net UPI):")
    show = tbl.sort_values("upi_net", ascending=False).copy()
    for _, r in show.iterrows():
        print(f"  {r.asset:<18} cost {r.cost*100:>4.2f}%  CAGR {r.cagr_gross*100:>5.2f}->{r.cagr_net*100:>5.2f}%  "
              f"vol {r.vol*100:>4.1f}%  maxDD {r.maxdd*100:>6.1f}%  ulcer {r.ulcer:>4.1f}  "
              f"UPI {r.upi_gross:.2f}->{r.upi_net:.2f}  Shp {r.sharpe_net:.2f}")

    df4 = optimize_4asset(series, rf_real, rf_cagr, years)
    df4.head(20).to_csv(OUT / "opt4_top20.csv", index=False)

    df2 = optimize_2asset(series, rf_real, rf_cagr, years)
    df2.to_csv(OUT / "opt2_curve.csv", index=False)

    print(f"\nCSVs written to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
