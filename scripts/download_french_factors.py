#!/usr/bin/env python3
"""Download & process the Kenneth R. French Data Library factor portfolios.

WHY THESE SERIES
----------------
The user wants *investable* factor exposure (small cap, small value, ...) with
the *longest possible history* (ideally pre-1970). Those two goals conflict for
real ETFs (oldest small-value fund DFSVX starts 1993). The resolution: French's
library publishes, alongside the famous LONG-SHORT factors (SMB/HML/WML — which
are zero-cost, leveraged, NOT investable), a set of LONG-ONLY sorted PORTFOLIOS
— ordinary value-weighted baskets of real stocks (the academic blueprint DFA/
VBR/IWN replicate) going back to July 1926. We harvest the value-weighted (=
cap-weighted, ETF-like) monthly returns from those portfolios.

  US (1926+):   size deciles, size x value (2x3 & 5x5), size x momentum (1927+)
  US (1963+):   size x profitability, size x investment (need Compustat)
  Intl (1990+): Developed / ex-US / Europe / Japan / Asia-Pac / N.Am / Emerging
                (no free investable factor data exists before ~1990; pre-1970
                 international factor premia exist only as long-short/proprietary
                 series — DMS Yearbook, AQR Century of Factor Premia.)
  Reference:    FF 3-factor (Mkt-RF/SMB/HML/RF) + momentum — LONG-SHORT, kept
                only for the risk-free rate and market-return reconstruction.

OUTPUTS (data/factors/)
  raw/<file>.zip + .csv  unmodified French downloads
  monthly/<label>.csv    value-weighted monthly TOTAL returns, DECIMAL
  annual_nominal/<label> monthly compounded to annual (Jan-Dec, full years), DECIMAL
  annual_real/<label>    annual_nominal deflated by US CPI (FIRE_dataset)
  headline_nominal_us.csv / _intl_developed.csv  analysis-ready, mirrors
                         FIRE_dataset convention (nominal returns + us_inflation col)

CONVENTIONS
  * Returns are NOMINAL TOTAL returns (incl. dividends), in USD.
  * French stores percent; we divide by 100 -> decimal.
  * Missing sentinels -99.99 / -999 -> NaN.
  * Value-weighted only (equal-weighted overweights illiquid microcaps).

Run:  python3 scripts/download_french_factors.py [--skip-download]
"""
import argparse
import os
import re
import sys
import urllib.request
import zipfile

import numpy as np
import pandas as pd

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "factors")
FIRE = os.path.join(ROOT, "data", "FIRE_dataset.csv")

# raw zip stem -> (clean label, region)
DATASETS = {
    "Portfolios_Formed_on_ME":                     ("us_size_portfolios", "US"),
    "6_Portfolios_2x3":                            ("us_size_value_2x3", "US"),
    "25_Portfolios_5x5":                           ("us_size_value_5x5", "US"),
    "6_Portfolios_ME_Prior_12_2":                  ("us_size_momentum_2x3", "US"),
    "6_Portfolios_ME_OP_2x3":                      ("us_size_profitability_2x3", "US"),
    "6_Portfolios_ME_INV_2x3":                     ("us_size_investment_2x3", "US"),
    "F-F_Research_Data_Factors":                   ("ref_ff3_factors_longshort", "US"),
    "F-F_Momentum_Factor":                         ("ref_momentum_factor_longshort", "US"),
    "Developed_6_Portfolios_ME_BE-ME":             ("intl_developed_size_value_2x3", "INTL"),
    "Developed_ex_US_6_Portfolios_ME_BE-ME":       ("intl_developed_ex_us_size_value_2x3", "INTL"),
    "Europe_6_Portfolios_ME_BE-ME":                ("intl_europe_size_value_2x3", "INTL"),
    "Japan_6_Portfolios_ME_BE-ME":                 ("intl_japan_size_value_2x3", "INTL"),
    "Asia_Pacific_ex_Japan_6_Portfolios_ME_BE-ME": ("intl_asiapac_ex_japan_size_value_2x3", "INTL"),
    "North_America_6_Portfolios_ME_BE-ME":         ("intl_north_america_size_value_2x3", "INTL"),
    "Emerging_Markets_6_Portfolios_ME_BE-ME":      ("intl_emerging_size_value_2x3", "INTL"),
}

DATE_RE = re.compile(r"^\d{6}$")
RENAME_2x3 = {"SMALL LoBM": "small_growth", "ME1 BM2": "small_neutral", "SMALL HiBM": "small_value",
              "BIG LoBM": "large_growth", "ME2 BM2": "large_neutral", "BIG HiBM": "large_value"}


def download(skip):
    raw = os.path.join(OUT, "raw"); os.makedirs(raw, exist_ok=True)
    for stem in DATASETS:
        zpath = os.path.join(raw, stem + "_CSV.zip")
        if skip and os.path.exists(zpath):
            pass
        else:
            url = f"{BASE}/{stem}_CSV.zip"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
            with open(zpath, "wb") as f:
                f.write(data)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(raw)
        print(f"  ok  {stem}")


def extract_vw_monthly(lines):
    """First ',' header line + following YYYYMM rows = value-weighted monthly."""
    hdr = next(i for i, ln in enumerate(lines) if ln.startswith(","))
    cols = [c.strip() for c in lines[hdr].rstrip("\n").split(",")]; cols[0] = "date"
    rows = []
    for ln in lines[hdr + 1:]:
        parts = [p.strip() for p in ln.strip().split(",")]
        if not parts or not DATE_RE.match(parts[0]):
            break
        rows.append(parts)
    df = pd.DataFrame(rows, columns=cols).apply(pd.to_numeric, errors="coerce")
    vals = [c for c in cols if c != "date"]
    df[vals] = df[vals].replace({-99.99: np.nan, -999.0: np.nan}) / 100.0
    return df, vals


def compound_annual(df, vals):
    df = df.copy(); df["year"] = df["date"] // 100
    out = {}
    for yr, g in df.groupby("year"):
        if len(g) != 12:
            continue
        out[yr] = {c: (float(np.prod(1.0 + g[c].values) - 1.0) if not g[c].isna().any() else np.nan)
                   for c in vals}
    a = pd.DataFrame.from_dict(out, orient="index"); a.index.name = "Year"
    return a[vals]


def process():
    raw = os.path.join(OUT, "raw")
    for sub in ("monthly", "annual_nominal", "annual_real"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    cpi = pd.read_csv(FIRE)[["Year", "US Inflation"]].set_index("Year")["US Inflation"]
    monthly_cache = {}
    for stem, (label, _region) in DATASETS.items():
        with open(os.path.join(raw, stem + ".csv")) as f:
            lines = f.readlines()
        mdf, vals = extract_vw_monthly(lines)
        mdf[["date"] + vals].to_csv(os.path.join(OUT, "monthly", label + ".csv"), index=False)
        monthly_cache[label] = mdf[["date"] + vals]
        ann = compound_annual(mdf, vals)
        ann.to_csv(os.path.join(OUT, "annual_nominal", label + ".csv"))
        common = ann.index.intersection(cpi.index)
        real = ann.loc[common].copy()
        for c in vals:
            real[c] = (1.0 + real[c]).div(1.0 + cpi.loc[common], axis=0) - 1.0
        real.to_csv(os.path.join(OUT, "annual_real", label + ".csv"))
    return monthly_cache, cpi


def _all_vals(df):
    return [c for c in df.columns if c != "date"]


def headline(monthly_cache, cpi):
    # US market total return reconstructed from FF factors: Mkt = Mkt-RF + RF
    ff = monthly_cache["ref_ff3_factors_longshort"].copy()
    ff["mkt"] = ff["Mkt-RF"] + ff["RF"]
    mkt = compound_annual(ff[["date", "mkt"]], ["mkt"])
    sv = compound_annual(monthly_cache["us_size_value_2x3"],
                         _all_vals(monthly_cache["us_size_value_2x3"])).rename(columns=RENAME_2x3)
    sz = compound_annual(monthly_cache["us_size_portfolios"], ["Lo 10", "Lo 20", "Hi 10"]).rename(
        columns={"Lo 10": "size_smallest_decile", "Lo 20": "size_small_quintile", "Hi 10": "size_biggest_decile"})
    us = mkt.join(sv, how="outer").join(sz, how="outer").join(cpi.rename("us_inflation"), how="left").round(6)
    us = us[["mkt", "small_value", "small_neutral", "small_growth", "large_value", "large_neutral",
             "large_growth", "size_smallest_decile", "size_small_quintile", "size_biggest_decile", "us_inflation"]]
    us.to_csv(os.path.join(OUT, "headline_nominal_us.csv"))
    dev = compound_annual(monthly_cache["intl_developed_size_value_2x3"],
                          _all_vals(monthly_cache["intl_developed_size_value_2x3"])).rename(
        columns=RENAME_2x3).join(cpi.rename("us_inflation"), how="left").round(6)
    dev.to_csv(os.path.join(OUT, "headline_nominal_intl_developed.csv"))
    return us


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true", help="reuse existing raw zips")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    print("[1/3] download + extract ..."); download(args.skip_download)
    print("[2/3] parse VW-monthly -> monthly/annual_nominal/annual_real ...")
    cache, cpi = process()
    print("[3/3] headline tables ..."); us = headline(cache, cpi)
    n = len(us)
    print(f"done. headline_nominal_us.csv {int(us.index.min())}-{int(us.index.max())} (n={n})")


if __name__ == "__main__":
    sys.exit(main())
