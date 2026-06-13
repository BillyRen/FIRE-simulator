#!/usr/bin/env python3
"""Compare US equity REITs (FTSE Nareit All Equity REITs TR) against JST's USA
physical-housing total return, plus US stocks/bonds for context.

Question: are publicly-traded equity REITs the same "real estate" asset that JST
`Housing_TR` measures? Answer (spoiler): no. REITs are levered, traded commercial
real-estate *equity* (stock-like vol, high stock correlation); JST housing is the
unlevered, appraisal/transaction-smoothed total return to residential dwellings
(bond-like measured vol, low stock correlation). This script quantifies the gap.

All comparisons over the overlapping window 1972-2024 (REIT data starts Dec 1971).
Returns are NOMINAL TOTAL returns; real = (1+nom)/(1+infl)-1 using JST USA CPI.
Everything gross of fees/transaction costs (both indices are).
"""
import csv
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
REIT_CSV = os.path.join(REPO, "data", "reits", "nareit_annual_total_return.csv")
REIT_MONTHLY_CSV = os.path.join(REPO, "data", "reits", "nareit_monthly_total_return.csv")
JST_CSV = os.path.join(REPO, "data", "jst_returns.csv")

START, END = 1972, 2024  # full-year overlap


def load_reit():
    out = {}
    with open(REIT_CSV) as f:
        for row in csv.DictReader(f):
            y = int(row["Year"])
            out[y] = {
                "reit_equity": float(row["all_equity_reits"]),
                "reit_all": float(row["all_reits"]),
                "reit_mortgage": float(row["mortgage_reits"]),
            }
    return out


def load_jst_usa():
    out = {}
    with open(JST_CSV) as f:
        for row in csv.DictReader(f):
            if row["Country"] != "USA":
                continue
            y = int(row["Year"])

            def g(k):
                v = row.get(k, "")
                return float(v) if v not in ("", None) else None

            out[y] = {
                "stock": g("Domestic_Stock"),
                "bond": g("Domestic_Bond"),
                "infl": g("Inflation"),
                "housing_tr": g("Housing_TR"),
                "housing_cap": g("Housing_CapGain"),
                "housing_rent": g("Housing_Rent_YD"),
            }
    return out


def stats(nom, infl):
    """nom, infl: aligned numpy arrays of nominal returns and inflation."""
    real = (1.0 + nom) / (1.0 + infl) - 1.0
    n = len(real)
    geo_nom = float(np.prod(1.0 + nom) ** (1.0 / n) - 1.0)
    geo_real = float(np.prod(1.0 + real) ** (1.0 / n) - 1.0)
    vol_real = float(np.std(real, ddof=1))
    # max drawdown on REAL cumulative wealth
    wealth = np.cumprod(1.0 + real)
    peak = np.maximum.accumulate(wealth)
    mdd = float(np.min(wealth / peak) - 1.0)
    return {
        "cagr_nom": geo_nom,
        "cagr_real": geo_real,
        "mean_real": float(np.mean(real)),
        "vol_real": vol_real,
        "ret_vol": geo_real / vol_real if vol_real else float("nan"),
        "worst": float(np.min(real)),
        "best": float(np.max(real)),
        "mdd": mdd,
        "real": real,
    }


def main():
    reit = load_reit()
    jst = load_jst_usa()

    years = [y for y in range(START, END + 1) if y in reit and y in jst]
    # require complete JST fields over the window
    missing = [y for y in years if any(
        jst[y][k] is None for k in ("stock", "bond", "infl", "housing_tr"))]
    if missing:
        print("WARNING missing JST fields for:", missing)
    years = [y for y in years if y not in missing]
    print(f"overlap window: {years[0]}-{years[-1]} ({len(years)} years)\n")

    infl = np.array([jst[y]["infl"] for y in years])
    series = {
        "US Equity REITs (Nareit)": np.array([reit[y]["reit_equity"] for y in years]),
        "JST US Housing (TR)":      np.array([jst[y]["housing_tr"] for y in years]),
        "US Stocks (JST)":          np.array([jst[y]["stock"] for y in years]),
        "US Bonds (JST)":           np.array([jst[y]["bond"] for y in years]),
    }

    st = {name: stats(nom, infl) for name, nom in series.items()}

    # ---- summary table (real terms) ----
    hdr = f"{'asset':26s} {'CAGRnom':>8s} {'CAGRreal':>9s} {'vol':>7s} " \
          f"{'ret/vol':>8s} {'worst':>8s} {'maxDD':>8s}"
    print(hdr)
    print("-" * len(hdr))
    for name, s in st.items():
        print(f"{name:26s} {s['cagr_nom']*100:7.2f}% {s['cagr_real']*100:8.2f}% "
              f"{s['vol_real']*100:6.1f}% {s['ret_vol']:8.2f} "
              f"{s['worst']*100:7.1f}% {s['mdd']*100:7.1f}%")

    # ---- correlation matrix (real annual returns) ----
    names = list(series.keys())
    M = np.vstack([st[n]["real"] for n in names])
    C = np.corrcoef(M)
    print("\ncorrelation matrix (real annual returns):")
    short = ["REIT", "Housing", "Stocks", "Bonds"]
    print(" " * 10 + "".join(f"{s:>9s}" for s in short))
    for i, s in enumerate(short):
        print(f"{s:10s}" + "".join(f"{C[i, j]:9.2f}" for j in range(len(short))))

    # ---- income comparison: REIT dividend yield vs housing rent yield ----
    rent = np.array([jst[y]["housing_rent"] for y in years
                     if jst[y]["housing_rent"] is not None])
    reit_dy = []
    with open(REIT_MONTHLY_CSV) as f:
        for row in csv.DictReader(f):
            if START <= int(row["Year"]) <= END and row["all_equity_div_yield"] != "":
                reit_dy.append(float(row["all_equity_div_yield"]))
    print(f"\nincome yields (avg over window):")
    print(f"  JST housing rent yield      : {np.mean(rent)*100:.2f}%")
    print(f"  REIT dividend yield (Nareit): {np.mean(reit_dy)*100:.2f}%")

    # ---- decade CAGRs (real) for REIT vs Housing ----
    print("\nreal CAGR by sub-period (REIT vs Housing vs Stocks):")
    for a, b in [(1972, 1989), (1990, 2009), (2010, 2024), (1972, 2024)]:
        idx = [i for i, y in enumerate(years) if a <= y <= b]
        if not idx:
            continue
        line = f"  {a}-{b} ({len(idx)}y): "
        for label, name in [("REIT", "US Equity REITs (Nareit)"),
                            ("Housing", "JST US Housing (TR)"),
                            ("Stocks", "US Stocks (JST)")]:
            r = st[name]["real"][idx]
            cagr = float(np.prod(1.0 + r) ** (1.0 / len(r)) - 1.0)
            line += f"{label:>8s}={cagr*100:5.1f}%  "
        print(line)


if __name__ == "__main__":
    main()
