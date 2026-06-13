#!/usr/bin/env python3
"""Does REIT risk/return converge to DIRECT real estate at long horizons?

User hypothesis: REITs are stock-like short-term (sentiment/beta) but their
underlying asset IS real estate, so long-term their risk/return should look more
like direct real estate than like stocks. This is a real, studied question
(Hoesli & Oikarinen 2012). Three confounds must be handled:

  (1) Appraisal/transaction SMOOTHING biases JST housing's short-horizon vol and
      correlations DOWNWARD. -> diagnose via AR(1); correct via Geltner unsmoothing.
  (2) Smoothing washes out as horizon grows, so a rising long-horizon corr is
      PARTLY mechanical, not purely convergence. -> report, don't over-claim.
  (3) REITs lead appraisal-based RE. -> lead-lag test corr(REIT_t, Housing_{t+k}).

Data: real annual returns 1972-2024 (REIT = Nareit All Equity; Housing = JST USA
Housing_TR; Stocks = JST USA Domestic_Stock). Deflated by JST USA CPI.

CAVEAT: only 53 annual obs. Non-overlapping h=10 windows -> 5 points; long-horizon
correlations are illustrative, not statistically tight. We print n for every cell.
"""
import csv
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
REIT_CSV = os.path.join(REPO, "data", "reits", "nareit_annual_total_return.csv")
JST_CSV = os.path.join(REPO, "data", "jst_returns.csv")
START, END = 1972, 2024


def load():
    reit = {}
    with open(REIT_CSV) as f:
        for row in csv.DictReader(f):
            reit[int(row["Year"])] = float(row["all_equity_reits"])
    jst = {}
    with open(JST_CSV) as f:
        for row in csv.DictReader(f):
            if row["Country"] != "USA":
                continue
            y = int(row["Year"])

            def g(k):
                v = row.get(k, "")
                return float(v) if v not in ("", None) else None
            jst[y] = {"stock": g("Domestic_Stock"), "infl": g("Inflation"),
                      "housing": g("Housing_TR")}
    years = [y for y in range(START, END + 1)
             if y in reit and y in jst
             and all(jst[y][k] is not None for k in ("stock", "infl", "housing"))]
    infl = np.array([jst[y]["infl"] for y in years])
    real = lambda nom: (1 + np.array(nom)) / (1 + infl) - 1
    return (years,
            real([reit[y] for y in years]),
            real([jst[y]["housing"] for y in years]),
            real([jst[y]["stock"] for y in years]))


def ar1(x):
    """lag-1 autocorrelation."""
    return float(np.corrcoef(x[:-1], x[1:])[0, 1])


def geltner_unsmooth(r, rho=None):
    """First-order Geltner unsmoothing: r*_t = (r_t - rho*r_{t-1})/(1-rho).
    rho defaults to the series' own lag-1 autocorrelation."""
    if rho is None:
        rho = ar1(r)
    out = (r[1:] - rho * r[:-1]) / (1 - rho)
    return out, rho  # length n-1, aligned to years[1:]


def block_logret(r, h):
    """Non-overlapping h-year cumulative LOG returns from the start."""
    lr = np.log1p(r)
    n = len(lr) // h
    return np.array([lr[i * h:(i + 1) * h].sum() for i in range(n)])


def corr(a, b):
    return float(np.corrcoef(a, b)[0, 1])


def main():
    years, reit, housing, stock = load()
    print(f"window {years[0]}-{years[-1]}  ({len(years)} annual obs)\n")

    # ---- (0) baseline h=1 ----
    print("== h=1 baseline (real annual returns) ==")
    print(f"  vol: REIT {np.std(reit, ddof=1)*100:4.1f}%  "
          f"Housing {np.std(housing, ddof=1)*100:4.1f}%  "
          f"Stocks {np.std(stock, ddof=1)*100:4.1f}%")
    print(f"  corr(REIT, Stocks)  = {corr(reit, stock):+.2f}")
    print(f"  corr(REIT, Housing) = {corr(reit, housing):+.2f}")
    print(f"  corr(Housing,Stocks)= {corr(housing, stock):+.2f}")

    # ---- (1) smoothing diagnostics: AR(1) ----
    print("\n== AR(1) autocorrelation (smoothing signature) ==")
    print(f"  REIT {ar1(reit):+.2f}   Housing {ar1(housing):+.2f}   "
          f"Stocks {ar1(stock):+.2f}")
    print("  (high positive Housing AR(1) = appraisal smoothing; "
          "liquid assets ~0)")

    # ---- (2) Geltner unsmoothing of housing, re-test ----
    h_un, rho = geltner_unsmooth(housing)
    reit_al = reit[1:]   # align to years[1:]
    stock_al = stock[1:]
    print(f"\n== Geltner-unsmoothed Housing (rho={rho:.2f}) ==")
    print(f"  Housing vol: raw {np.std(housing, ddof=1)*100:4.1f}%  ->  "
          f"unsmoothed {np.std(h_un, ddof=1)*100:4.1f}%")
    print(f"  corr(REIT, Housing):  raw {corr(reit_al, housing[1:]):+.2f}  ->  "
          f"unsmoothed {corr(reit_al, h_un):+.2f}")
    print(f"  corr(Stocks,Housing): raw {corr(stock_al, housing[1:]):+.2f}  ->  "
          f"unsmoothed {corr(stock_al, h_un):+.2f}")

    # ---- (3) horizon-dependent correlation (non-overlapping) ----
    print("\n== horizon-dependent corr (NON-overlapping blocks) ==")
    print(f"  {'h':>3} {'n':>3} {'corr(REIT,Stocks)':>18} {'corr(REIT,Housing)':>19}")
    for h in (1, 2, 3, 5, 10):
        R, H, S = block_logret(reit, h), block_logret(housing, h), block_logret(stock, h)
        n = len(R)
        if n < 3:
            print(f"  {h:>3} {n:>3}   (too few blocks)")
            continue
        print(f"  {h:>3} {n:>3} {corr(R, S):>18.2f} {corr(R, H):>19.2f}")

    # ---- (3b) overlapping (more points, autocorrelated -> illustrative) ----
    print("\n== horizon-dependent corr (OVERLAPPING, illustrative only) ==")
    lr_R, lr_H, lr_S = np.log1p(reit), np.log1p(housing), np.log1p(stock)

    def roll_sum(x, h):
        return np.array([x[i:i + h].sum() for i in range(len(x) - h + 1)])
    print(f"  {'h':>3} {'n':>3} {'corr(REIT,Stocks)':>18} {'corr(REIT,Housing)':>19}")
    for h in (1, 3, 5, 7, 10):
        R, H, S = roll_sum(lr_R, h), roll_sum(lr_H, h), roll_sum(lr_S, h)
        print(f"  {h:>3} {len(R):>3} {corr(R, S):>18.2f} {corr(R, H):>19.2f}")

    # ---- (4) lead-lag: does REIT lead Housing? ----
    print("\n== lead-lag  corr(REIT_t, Housing_{t+k})  (real annual) ==")
    print("  k<0: housing leads REIT | k>0: REIT leads housing")
    for k in range(-3, 4):
        if k < 0:
            a, b = reit[-k:], housing[:k]
        elif k > 0:
            a, b = reit[:-k], housing[k:]
        else:
            a, b = reit, housing
        print(f"  k={k:+d} (n={len(a):2d}): {corr(a, b):+.2f}")

    # ---- (5) long-run CAGR closeness ----
    g = lambda r: float(np.prod(1 + r) ** (1 / len(r)) - 1)
    print(f"\n== full-window real CAGR ==")
    print(f"  REIT {g(reit)*100:.2f}%   Housing {g(housing)*100:.2f}%   "
          f"Stocks {g(stock)*100:.2f}%")


if __name__ == "__main__":
    main()
