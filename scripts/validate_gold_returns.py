#!/usr/bin/env python3
"""Sanity-check the prepared gold return data (``data/jst_gold.csv``).

Run after ``build_gold_returns.py``. Verifies structural alignment with
``jst_returns.csv`` and prints economic sanity statistics:

1. Key alignment: gold rows match jst_returns rows 1:1.
2. USA gold return == plain USD gold return (xrusd == 1).
3. Gold-standard era (<=1932) USA nominal returns are near zero.
4. Floating era (1972+) USA nominal vs real gold return, annualized.
5. Cross-country consistency: real gold returns should be similar across
   countries in a given year (gold is a single global real asset; spread
   reflects only deviations from relative PPP).
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
GOLD = os.path.join(HERE, "..", "data", "jst_gold.csv")
RETURNS = os.path.join(HERE, "..", "data", "jst_returns.csv")


def geo_mean(returns: pd.Series) -> float:
    r = returns.dropna()
    return float(np.expm1(np.log1p(r).mean()))


def main() -> None:
    gold = pd.read_csv(GOLD)
    ret = pd.read_csv(RETURNS)[["Year", "Country", "Inflation"]]
    df = gold.merge(ret, on=["Year", "Country"], how="left")
    df["gold_real"] = (1 + df["Gold_Nominal_Return"]) / (1 + df["Inflation"]) - 1

    print("=" * 64)
    print("1. KEY ALIGNMENT")
    g_keys = set(map(tuple, gold[["Year", "Country"]].values))
    r_keys = set(map(tuple, pd.read_csv(RETURNS)[["Year", "Country"]].values))
    print(f"   gold rows={len(gold)}  returns rows={len(r_keys)}  "
          f"identical_keys={g_keys == r_keys}")
    n_nan = int(gold["Gold_Nominal_Return"].isna().sum())
    print(f"   NaN nominal returns: {n_nan} "
          f"({gold.loc[gold['Gold_Nominal_Return'].isna(), ['Country','Year']].values.tolist()})")

    print("\n2. USA == PURE USD GOLD RETURN (xrusd==1)")
    usa = df[df["Country"] == "USA"]
    print(f"   all USA xrusd == 1.0: {bool((usa['xrusd'] == 1.0).all())}")

    print("\n3. GOLD-STANDARD ERA (USA, year<=1932) NEAR-ZERO NOMINAL")
    gs = usa[usa["Year"] <= 1932]["Gold_Nominal_Return"]
    print(f"   n={len(gs)}  mean={gs.mean():+.4%}  "
          f"max|r|={gs.abs().max():.4%}  std={gs.std():.4%}")

    print("\n4. FLOATING ERA (USA, 1972+) ANNUALIZED")
    fl = usa[usa["Year"] >= 1972]
    print(f"   n={len(fl)}")
    print(f"   nominal geo mean = {geo_mean(fl['Gold_Nominal_Return']):+.2%}/yr")
    print(f"   real    geo mean = {geo_mean(fl['gold_real']):+.2%}/yr")
    print(f"   real    std      = {fl['gold_real'].std():.2%}")
    print(f"   real    min/max  = {fl['gold_real'].min():+.1%} / {fl['gold_real'].max():+.1%}")

    print("\n   Full-sample (USA, 1871+) real geo mean = "
          f"{geo_mean(usa['gold_real']):+.2%}/yr")

    print("\n5. CROSS-COUNTRY REAL-RETURN CONSISTENCY (floating era 1972+)")
    fle = df[df["Year"] >= 1972]
    spread = fle.groupby("Year")["gold_real"].agg(["mean", "std", "min", "max"])
    print(f"   median across years of cross-country std(real gold return) = "
          f"{spread['std'].median():.2%}")
    print(f"   mean   across years of cross-country std(real gold return) = "
          f"{spread['std'].mean():.2%}")
    # Correlation of each country's real gold return vs USA real gold return.
    pivot = fle.pivot_table(index="Year", columns="Country", values="gold_real")
    corr_vs_usa = pivot.corrwith(pivot["USA"]).drop("USA").sort_values()
    print(f"   corr(country real gold, USA real gold): "
          f"min={corr_vs_usa.min():.2f} ({corr_vs_usa.idxmin()})  "
          f"median={corr_vs_usa.median():.2f}")

    print("\n" + "=" * 64)
    print("DONE")


if __name__ == "__main__":
    main()
