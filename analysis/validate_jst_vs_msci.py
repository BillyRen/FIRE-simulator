#!/usr/bin/env python3
"""Validate JST non-US equity data against real investable indices (MSCI).

Plan: docs/plan-jst-intl-validation-2026-06-12.md (Codex-reviewed).

Two validations:
  V1  Seed a buy-and-hold portfolio with MSCI EAFE's actual Dec-1969 country
      weights, grow it with JST per-country USD nominal returns, compare to
      the real MSCI EAFE series (FIRE_dataset `International Stock`, 1970+).
      This is an ATTRIBUTION test (membership/free-float drift excluded), not
      an exact replication.
  V2  Per-country: JST USD nominal annualized return vs MSCI country index
      GRTR USD over the exact-matched window 2001-2025 (anonymous MSCI
      endpoint exposes ~25y of monthly levels), plus official-JST-only
      2001-2020 and post-free-float 2003-2025 sub-windows.

Stages (run in order; downloads are cached):
    python analysis/validate_jst_vs_msci.py download    # MSCI levels + ETF data
    python analysis/validate_jst_vs_msci.py identify    # code identity + variant diagnosis + xrusd/sanity checks
    python analysis/validate_jst_vs_msci.py v2          # per-country tables
    python analysis/validate_jst_vs_msci.py v1          # EAFE buy-and-hold attribution

Requires: pandas, openpyxl, requests, yfinance (validation only).
MSCI raw levels are cached under analysis/output/msci_cache/ (NOT committed).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW_XLSX = os.path.join(BASE, "data", "raw", "JSTdatasetR6.xlsx")
EXT_CSV = os.path.join(BASE, "data", "raw", "jst_extension_2021_2025.csv")
FIRE_CSV = os.path.join(BASE, "data", "FIRE_dataset.csv")
JST_RETURNS_CSV = os.path.join(BASE, "data", "jst_returns.csv")
CACHE = os.path.join(BASE, "analysis", "output", "msci_cache")

# MSCI index codes for getLevelDataForGraph: 9 + ISO3166-numeric + 00 for
# country standard (large+mid) indices (Germany uses West-Germany ISO 280).
# Verified empirically against iShares country ETFs in stage `identify`.
MSCI_CODES = {
    "AUS": "903600", "BEL": "905600", "CHE": "975600", "DEU": "928000",
    "DNK": "920800", "ESP": "972400", "FIN": "924600", "FRA": "925000",
    "GBR": "982600", "ITA": "938000", "JPN": "939200", "NLD": "952800",
    "NOR": "957800", "PRT": "962000", "SWE": "975200", "USA": "984000",
    "EAFE": "990300", "WORLD": "990100", "EM": "891800", "CAN": "912400",
}
ETF_MAP = {  # iShares MSCI country ETFs (NETR-ish minus fee) for identity check
    "AUS": "EWA", "BEL": "EWK", "CHE": "EWL", "DEU": "EWG", "DNK": "EDEN",
    "ESP": "EWP", "FIN": "EFNL", "FRA": "EWQ", "GBR": "EWU", "ITA": "EWI",
    "JPN": "EWJ", "NLD": "EWN", "NOR": "ENOR", "PRT": "PGAL", "SWE": "EWD",
    "USA": "IVV", "EAFE": "EFA",
}
EX_US = ["AUS", "BEL", "CHE", "DEU", "DNK", "ESP", "FIN", "FRA", "GBR",
         "ITA", "JPN", "NLD", "NOR", "PRT", "SWE"]

# ---- V1 weight tiers (Dec-1969 EAFE membership ∩ JST = 13 countries; FIN/PRT
# joined MSCI only in the late 1980s; Austria/HK/Singapore are EAFE members
# without JST data — their launch mass is reported separately).
V1_COUNTRIES = ["AUS", "BEL", "CHE", "DEU", "DNK", "ESP", "FRA", "GBR",
                "ITA", "JPN", "NLD", "NOR", "SWE"]
# Tier 2: Rajan-Zingales (2003, NBER w8178 Table 3) stock-market-cap/GDP 1970
# x JST nominal USD GDP 1969 (gdp/xrusd). Spain has no 1970 RZ value -> excluded
# from this tier (small market; documented).
RZ_CAP_GDP_1970 = {
    "AUS": 0.76, "BEL": 0.23, "CHE": 0.50, "DEU": 0.16, "DNK": 0.17,
    "FRA": 0.16, "GBR": 1.63, "ITA": 0.14, "JPN": 0.23, "NLD": 0.42,
    "NOR": 0.23, "SWE": 0.14,
}

GRAPH_URL = ("https://app2.msci.com/products/service/index/indexmaster/"
             "getLevelDataForGraph?currency_symbol=USD&index_variant={variant}"
             "&start_date=20001201&end_date=20260101"
             "&data_frequency=END_OF_MONTH&index_codes={code}")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0"}


# --------------------------------------------------------------------------
# data layer
# --------------------------------------------------------------------------

def load_jst() -> pd.DataFrame:
    """Long frame: year, iso, eq_tr (nominal local), xrusd, usd_ret, cpi, gdp.

    2021-2025 rows come from the unofficial extension and are flagged
    `extended=True`; headline windows in the report end at 2020.
    """
    df = pd.read_excel(RAW_XLSX)
    df = df[["year", "iso", "eq_tr", "xrusd", "cpi", "gdp", "rgdpmad", "pop"]].copy()
    df["extended"] = False
    ext = pd.read_csv(EXT_CSV)
    ext = ext[["year", "iso", "eq_tr", "xrusd", "cpi"]].copy()
    ext["gdp"] = np.nan
    ext["rgdpmad"] = np.nan
    ext["pop"] = np.nan
    ext["extended"] = True
    df = pd.concat([df, ext], ignore_index=True).sort_values(["iso", "year"])
    # USD nominal return: (1+eq_tr) * xrusd[t-1]/xrusd[t] - 1  (xrusd = local per USD)
    df["xrusd_prev"] = df.groupby("iso")["xrusd"].shift(1)
    df["usd_ret"] = (1.0 + df["eq_tr"]) * df["xrusd_prev"] / df["xrusd"] - 1.0
    return df


def usd_matrix(jst: pd.DataFrame, lo: int, hi: int) -> pd.DataFrame:
    """Wide year x iso matrix of USD nominal returns, years lo..hi inclusive."""
    sub = jst[(jst.year >= lo) & (jst.year <= hi)]
    return sub.pivot(index="year", columns="iso", values="usd_ret")


def fire_intl() -> pd.Series:
    fire = pd.read_csv(FIRE_CSV)
    s = fire.set_index("Year")["International Stock"]
    return s[s.index >= 1970]


def cagr(returns: pd.Series | np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return float("nan")
    return float(np.prod(1.0 + r) ** (1.0 / len(r)) - 1.0)


# --------------------------------------------------------------------------
# stage: download
# --------------------------------------------------------------------------

def _fetch_levels(code: str, variant: str) -> dict:
    import requests
    path = os.path.join(CACHE, f"{code}_{variant}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    url = GRAPH_URL.format(variant=variant, code=code)
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    data = r.json()
    levels = data.get("indexes", {}).get("INDEX_LEVELS", [])
    if not levels:
        raise RuntimeError(f"no levels for {code} {variant}: {str(data)[:200]}")
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def stage_download() -> None:
    os.makedirs(CACHE, exist_ok=True)
    jobs = [(iso, code, "GRTR") for iso, code in MSCI_CODES.items()]
    jobs += [("EAFE", MSCI_CODES["EAFE"], v) for v in ("NETR", "STRD")]
    for iso, code, variant in jobs:
        data = _fetch_levels(code, variant)
        n = len(data["indexes"]["INDEX_LEVELS"])
        first = data["indexes"]["INDEX_LEVELS"][0]["calc_date"]
        last = data["indexes"]["INDEX_LEVELS"][-1]["calc_date"]
        print(f"{iso:6s} {variant} code={code}: {n} monthly levels {first}..{last}")
        time.sleep(0.4)
    # ETF monthly data for identity validation
    import yfinance as yf
    tickers = sorted(set(ETF_MAP.values()))
    etf_path = os.path.join(CACHE, "etf_monthly.csv")
    if not os.path.exists(etf_path):
        px = yf.download(tickers, start="2000-12-01", interval="1mo",
                         auto_adjust=True, progress=False)["Close"]
        px.to_csv(etf_path)
        print(f"ETF monthly prices saved: {px.shape}")
    else:
        print("ETF monthly prices already cached")


# --------------------------------------------------------------------------
# msci helpers
# --------------------------------------------------------------------------

def msci_monthly(iso: str, variant: str = "GRTR") -> pd.Series:
    data = _fetch_levels(MSCI_CODES[iso], variant)
    lv = data["indexes"]["INDEX_LEVELS"]
    s = pd.Series({pd.Timestamp(str(d["calc_date"])): d["level_eod"] for d in lv})
    return s.sort_index()


def msci_annual(iso: str, variant: str = "GRTR", mode: str = "dec") -> pd.Series:
    """Calendar-year returns from monthly levels.

    mode='dec': Dec/Dec.  mode='avg': annual mean level / prev annual mean level
    (approximates annual-average index pricing used by some JST sources).
    """
    m = msci_monthly(iso, variant)
    if mode == "dec":
        dec = m[m.index.month == 12]
        ann = dec.pct_change().dropna()
        ann.index = ann.index.year
    else:
        yearly = m.groupby(m.index.year).mean()
        ann = yearly.pct_change().dropna()
        # need full 12-month coverage on both sides; first cached year (2000)
        # has only Dec -> drop the first ratio
        ann = ann.iloc[1:]
    return ann


# --------------------------------------------------------------------------
# stage: identify
# --------------------------------------------------------------------------

def stage_identify() -> None:
    jst = load_jst()

    print("== 1. MSCI code identity validation vs iShares country ETFs ==")
    etf_px = pd.read_csv(os.path.join(CACHE, "etf_monthly.csv"),
                         index_col=0, parse_dates=True)
    bad = []
    for iso, tkr in ETF_MAP.items():
        m = msci_monthly(iso, "GRTR").pct_change().dropna()
        m.index = m.index.to_period("M")
        e = etf_px[tkr].dropna().pct_change().dropna()
        e.index = e.index.to_period("M")
        common = m.index.intersection(e.index)
        c = float(np.corrcoef(m.loc[common], e.loc[common])[0, 1])
        flag = "OK " if c >= 0.98 else ("ok?" if c >= 0.95 else "BAD")
        if c < 0.95:
            bad.append(iso)
        print(f"  {iso:5s} vs {tkr:5s}: monthly corr {c:.4f} over {len(common)} m [{flag}]")
    if bad:
        print(f"  !! identity NOT confirmed for: {bad}")

    print("\n== 2. FIRE `International Stock` variant diagnosis (2001-2025) ==")
    fi = fire_intl()
    for variant in ("GRTR", "NETR", "STRD"):
        ea = msci_annual("EAFE", variant, "dec")
        common = fi.index.intersection(ea.index)
        d = fi.loc[common] - ea.loc[common]
        c = float(np.corrcoef(fi.loc[common], ea.loc[common])[0, 1])
        print(f"  vs EAFE {variant}: corr {c:.4f}  mean diff {d.mean()*100:+.2f}pp  "
              f"RMSE {np.sqrt((d**2).mean())*100:.2f}pp  ({len(common)}y)")
    # composition regression: the residual vs pure EAFE is explained by an
    # EM/Canada admixture + a fee-like constant (Simba-style fund splice)
    ea = msci_annual("EAFE", "GRTR", "dec")
    em = msci_annual("EM", "GRTR", "dec")
    can = msci_annual("CAN", "GRTR", "dec")
    common = fi.index.intersection(ea.index).intersection(em.index).intersection(can.index)
    A = np.column_stack([ea.loc[common], em.loc[common], can.loc[common],
                         np.ones(len(common))])
    y = fi.loc[common].to_numpy()
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ coef
    r2 = 1 - resid.var() / y.var()
    print(f"  OLS FIRE_intl ~ EAFE/EM/CAN + const ({len(common)}y): "
          f"betas {coef[0]:+.3f}/{coef[1]:+.3f}/{coef[2]:+.3f}, "
          f"const {coef[3]*100:+.2f}pp/yr, R2 {r2:.4f}")

    print("\n== 3. xrusd convention spot-check (year-end vs annual-average) ==")
    ref = {  # market year-end rates (local per USD)
        ("JPN", 1971): 314.8, ("JPN", 1972): 302.0,
        ("GBR", 1971): 0.3916, ("DEU", 1971): 3.268, ("DEU", 1973): 2.703,
    }
    for (iso, yr), v in ref.items():
        x = float(jst[(jst.iso == iso) & (jst.year == yr)]["xrusd"].iloc[0])
        print(f"  {iso} {yr}: JST {x:.4f} vs year-end ref {v:.4f} "
              f"({(x/v-1)*100:+.2f}%)")
    print("  JPN 1969/1970 (peg era was 360):",
          jst[(jst.iso == 'JPN') & jst.year.isin([1969, 1970])]["xrusd"].tolist())

    print("\n== 4. prior-study (2026-06-07) 5-country sanity reproduction ==")
    prior = {  # iso: (jst_cagr_prior_pct, msci_factsheet_pct, first_full_year)
        "JPN": (3.30, 3.23, 1995), "CHE": (9.35, 9.13, 1995),
        "DEU": (8.85, 8.54, 1988), "FRA": (9.18, 8.94, 1988),
        "AUS": (9.33, 9.49, 1988),
    }
    for iso, (jp, mp, y0) in prior.items():
        for hi in (2025,):
            sub = jst[(jst.iso == iso) & jst.year.between(y0, hi)]["usd_ret"]
            print(f"  {iso} {y0}-{hi}: JST USD CAGR {cagr(sub)*100:.2f}% "
                  f"(prior study {jp:.2f}%, MSCI factsheet {mp:.2f}%)")


# --------------------------------------------------------------------------
# stage: v2 per-country
# --------------------------------------------------------------------------

# JST equity pricing convention can differ per country AND per data era
# (empirical finding: JST USA is Dec-Dec through 2015 = CRSP era, but
# annual-average for the R6 2016-2020 update; our 2021-25 extension is
# annual-average by construction). Detect alignment per era.
# NB (Codex P4): alignment is selected IN-SAMPLE (one binary choice per era
# per country, min-RMSE between two fixed candidates); the raw Dec-Dec diff
# is reported alongside as the no-selection view. The 'avg' annualization is
# only available from 2002 (needs a full prior-year average), so an
# avg-selected first era falls back to Dec for 2001 — affected countries get
# an explicit avg-only sensitivity printed below the table.
ERAS = [("R5core_01-15", 2001, 2015), ("R6upd_16-20", 2016, 2020),
        ("ext_21-25", 2021, 2025)]


def detect_alignment(j: pd.Series, md: pd.Series, ma: pd.Series,
                     lo: int, hi: int) -> str:
    """'dec' or 'avg': which MSCI annualization matches JST better on lo..hi."""
    yrs_d = [y for y in range(lo, hi + 1) if y in j.index and y in md.index]
    yrs_a = [y for y in range(lo, hi + 1) if y in j.index and y in ma.index]
    if len(yrs_a) < 3 or len(yrs_d) < 3:
        return "dec"
    # RMSE is more robust than corr on short eras
    rmse_d = float(np.sqrt(((j.loc[yrs_d] - md.loc[yrs_d]) ** 2).mean()))
    rmse_a = float(np.sqrt(((j.loc[yrs_a] - ma.loc[yrs_a]) ** 2).mean()))
    return "dec" if rmse_d <= rmse_a else "avg"


def stage_v2() -> None:
    jst = load_jst()
    rows = []
    windows = [("2001-2025", 2001, 2025), ("2001-2020", 2001, 2020),
               ("2003-2025", 2003, 2025)]
    for iso in EX_US + ["USA"]:
        md = msci_annual(iso, "GRTR", "dec")
        ma = msci_annual(iso, "GRTR", "avg")
        j = jst[jst.iso == iso].set_index("year")["usd_ret"]
        # convention-aligned MSCI series (per era)
        conv = {}
        aligned = {}
        for era_name, lo, hi in ERAS:
            mode = detect_alignment(j, md, ma, lo, hi)
            conv[era_name] = mode
            src = md if mode == "dec" else ma
            for y in range(lo, hi + 1):
                aligned[y] = src.get(y, md.get(y, np.nan))
        mal = pd.Series(aligned).dropna()
        rec: dict = {"iso": iso,
                     "conv": "/".join(conv[e] for e, _, _ in ERAS)}
        for label, lo, hi in windows:
            yrs = [y for y in range(lo, hi + 1) if y in mal.index and y in j.index]
            jc, mc = cagr(j.loc[yrs]), cagr(mal.loc[yrs])
            rec[f"jst_{label}"] = jc * 100
            rec[f"msci_{label}"] = mc * 100
            rec[f"diff_{label}"] = (jc - mc) * 100
            # raw Dec-Dec reference for the headline window
            if label == "2001-2025":
                yrs_d = [y for y in range(lo, hi + 1)
                         if y in md.index and y in j.index]
                rec["diff_raw_dec"] = (cagr(j.loc[yrs_d]) - cagr(md.loc[yrs_d])) * 100
        yrs = [y for y in range(2001, 2026) if y in mal.index and y in j.index]
        dd = j.loc[yrs] - mal.loc[yrs]
        rec["corr_aligned"] = float(np.corrcoef(j.loc[yrs], mal.loc[yrs])[0, 1])
        yrs_d = [y for y in range(2001, 2026) if y in md.index and y in j.index]
        rec["corr_dec"] = float(np.corrcoef(j.loc[yrs_d], md.loc[yrs_d])[0, 1])
        rec["rmse_aligned"] = float(np.sqrt((dd ** 2).mean()) * 100)
        # worst year restricted to official JST (2001-2020), aligned caliber
        off = dd[dd.index <= 2020]
        worst = off.abs().idxmax()
        rec["worst_year"] = int(worst)
        rec["worst_gap"] = float(off.loc[worst] * 100)
        rows.append(rec)
    out = pd.DataFrame(rows).set_index("iso")
    pd.set_option("display.width", 240)
    cols1 = ["conv", "jst_2001-2025", "msci_2001-2025", "diff_2001-2025",
             "diff_raw_dec", "diff_2001-2020", "diff_2003-2025"]
    cols2 = ["corr_aligned", "corr_dec", "rmse_aligned", "worst_year", "worst_gap"]
    print("== V2 per-country: JST USD nominal vs MSCI country GRTR USD ==")
    print("   (MSCI annualization aligned to detected JST pricing convention per era;")
    print("    conv = R5core 2001-15 / R6update 2016-20 / extension 2021-25)")
    print(out[cols1].round(2).to_string())
    print()
    print(out[cols2].round(3).to_string())
    # avg-selected first era: 2001 fell back to Dec inside the aligned series;
    # show the 2002-2025 window (fallback-free) as a sensitivity
    for rec in rows:
        if rec["conv"].split("/")[0] != "avg":
            continue
        iso = rec["iso"]
        md = msci_annual(iso, "GRTR", "dec")
        ma = msci_annual(iso, "GRTR", "avg")
        j = jst[jst.iso == iso].set_index("year")["usd_ret"]
        aligned = {}
        for era_name, lo, hi in ERAS:
            src = md if detect_alignment(j, md, ma, lo, hi) == "dec" else ma
            for y in range(max(lo, 2002), hi + 1):
                aligned[y] = src.get(y, np.nan)
        mal = pd.Series(aligned).dropna()
        yrs = [y for y in mal.index if y in j.index]
        print(f"\n  sensitivity {iso} (era1=avg, no 2001 Dec-fallback): "
              f"2002-2025 aligned diff "
              f"{(cagr(j.loc[yrs]) - cagr(mal.loc[yrs]))*100:+.2f}pp")
    os.makedirs(os.path.join(BASE, "analysis", "output"), exist_ok=True)
    out.to_csv(os.path.join(BASE, "analysis", "output", "v2_per_country.csv"))
    print("\nsaved analysis/output/v2_per_country.csv")


# --------------------------------------------------------------------------
# stage: v1 buy-and-hold
# --------------------------------------------------------------------------

def gdp_1970_usd() -> pd.Series:
    """Nominal GDP 1970 in current USD (bn) for the V1 universe.

    Fetched from the World Bank API (NY.GDP.MKTP.CD, 1970) and cached.
    JST's own `gdp` column is local-currency with country-specific unit
    scaling, so it cannot be used for cross-country level comparisons.
    Switzerland has no World Bank value before 1980 -> UN National Accounts
    (AMA) 1970 estimate used as a documented constant.
    """
    path = os.path.join(CACHE, "wb_gdp_1970.json")
    if os.path.exists(path):
        with open(path) as f:
            vals = json.load(f)
    else:
        import requests
        iso3 = {"AUS": "AUS", "BEL": "BEL", "DEU": "DEU", "DNK": "DNK",
                "ESP": "ESP", "FRA": "FRA", "GBR": "GBR", "ITA": "ITA",
                "JPN": "JPN", "NLD": "NLD", "NOR": "NOR", "SWE": "SWE",
                "CHE": "CHE"}
        url = ("https://api.worldbank.org/v2/country/"
               + ";".join(iso3.values())
               + "/indicator/NY.GDP.MKTP.CD?date=1970&format=json&per_page=50")
        r = requests.get(url, timeout=40)
        r.raise_for_status()
        rows = r.json()[1]
        vals = {row["countryiso3code"]: row["value"] for row in rows}
        with open(path, "w") as f:
            json.dump(vals, f)
    s = pd.Series(vals, dtype=float) / 1e9
    if "CHE" not in s.index or pd.isna(s.get("CHE")):
        # UN National Accounts Main Aggregates: Switzerland 1970 nominal GDP
        s["CHE"] = 22.5
    return s


def weight_tiers(jst: pd.DataFrame) -> dict[str, pd.Series]:
    """Candidate Dec-1969 weight sets over V1_COUNTRIES (normalized)."""
    g69 = jst[(jst.year == 1969)].set_index("iso")
    tiers: dict[str, pd.Series] = {}
    # Tier 2: RZ cap/GDP 1970 x World Bank nominal USD GDP 1970
    # (Spain excluded: no RZ 1970 value)
    gdp = gdp_1970_usd()
    cap = (pd.Series(RZ_CAP_GDP_1970) * gdp).dropna()
    tiers["T2_rz_cap"] = cap / cap.sum()
    # Tier 3: engine-convention linear real GDP weights (rgdpmad x pop, 1969)
    rg = (g69["rgdpmad"] * g69["pop"]).reindex(V1_COUNTRIES)
    tiers["T3_gdp"] = rg / rg.sum()
    # Tier 4: equal weight
    eq = pd.Series(1.0, index=V1_COUNTRIES)
    tiers["T4_equal"] = eq / eq.sum()
    return tiers


def buy_and_hold(usd: pd.DataFrame, w0: pd.Series, lo: int, hi: int,
                 rebalance: bool = False) -> tuple[pd.Series, pd.DataFrame]:
    """Annual portfolio returns and weight path from initial weights w0."""
    countries = list(w0.index)
    w = w0.to_numpy(dtype=float).copy()
    rets, wpath = {}, {}
    for year in range(lo, hi + 1):
        r = usd.loc[year, countries].to_numpy(dtype=float)
        if np.isnan(r).any():
            raise ValueError(f"missing USD return in {year}")
        port = float(np.sum(w * r))
        rets[year] = port
        w = w * (1.0 + r)
        w = w / w.sum()
        if rebalance:
            w = w0.to_numpy(dtype=float).copy()
        wpath[year] = dict(zip(countries, w))
    return pd.Series(rets), pd.DataFrame(wpath).T


def _compare(name: str, port: pd.Series, target: pd.Series) -> dict:
    common = port.index.intersection(target.index)
    p, t = port.loc[common], target.loc[common]
    rec = {"weights": name}
    for label, lo, hi in [("1970-2020", 1970, 2020), ("1970-2025", 1970, 2025)]:
        yrs = [y for y in common if lo <= y <= hi]
        rec[f"jst_bh_{label}"] = cagr(p.loc[yrs]) * 100
        rec[f"msci_{label}"] = cagr(t.loc[yrs]) * 100
        rec[f"diff_{label}"] = rec[f"jst_bh_{label}"] - rec[f"msci_{label}"]
        rec[f"tw_ratio_{label}"] = float(
            np.prod(1 + p.loc[yrs]) / np.prod(1 + t.loc[yrs]))
    rec["corr"] = float(np.corrcoef(p, t)[0, 1])
    rec["rmse"] = float(np.sqrt(((p - t) ** 2).mean()) * 100)
    return rec


def stage_v1() -> None:
    jst = load_jst()
    usd = usd_matrix(jst, 1970, 2025)
    target = fire_intl()
    tiers = weight_tiers(jst)

    # face-validity references for the target series itself
    yrs = [y for y in target.index if 1970 <= y <= 2009]
    print(f"target (FIRE intl) 1970-2009 CAGR: {cagr(target.loc[yrs])*100:.2f}% "
          f"(published MSCI EAFE gross: 9.49%)")
    yrs = [y for y in target.index if 1970 <= y <= 1989]
    print(f"target (FIRE intl) 1970-1989 CAGR: {cagr(target.loc[yrs])*100:.2f}% "
          f"(published MSCI EAFE gross: 15.21%)")

    print("\n== Dec-1969 weight tiers (over EAFE∩JST members) ==")
    wtab = pd.DataFrame(tiers).mul(100).round(1)
    print(wtab.to_string())

    rows = []
    for name, w in tiers.items():
        port, wpath = buy_and_hold(usd, w, 1970, 2025)
        rows.append(_compare(name, port, target))
        if name == "T2_rz_cap":
            keep = wpath.loc[[1970, 1980, 1989, 2000, 2010, 2025]].mul(100).round(1)
            print(f"\nweight path (T2_rz_cap, %):\n{keep.to_string()}")
    # perturbations on the primary tier: JPN and GBR +-25% relative
    base = tiers["T2_rz_cap"]
    for iso in ("JPN", "GBR"):
        for k in (0.75, 1.25):
            w = base.copy()
            w[iso] = w[iso] * k
            w = w / w.sum()
            port, _ = buy_and_hold(usd, w, 1970, 2025)
            rows.append(_compare(f"T2 {iso} x{k}", port, target))
    # sensitivity: JPN pre-1971 xrusd anomaly (JST 376/380 vs 360 official peg)
    jst_fx = load_jst()
    fx_patch = {1969: 360.0, 1970: 357.65}
    for yr, v in fx_patch.items():
        jst_fx.loc[(jst_fx.iso == "JPN") & (jst_fx.year == yr), "xrusd"] = v
    jst_fx["xrusd_prev"] = jst_fx.groupby("iso")["xrusd"].shift(1)
    jst_fx["usd_ret"] = (1.0 + jst_fx["eq_tr"]) * jst_fx["xrusd_prev"] / jst_fx["xrusd"] - 1.0
    usd_fx = usd_matrix(jst_fx, 1970, 2025)
    port_fx, _ = buy_and_hold(usd_fx, base, 1970, 2025)
    rows.append(_compare("T2 JPNfx-360patch", port_fx, target))
    # annually-rebalanced diagnostic + GDP-weighted engine reference series
    port_rb, _ = buy_and_hold(usd, tiers["T2_rz_cap"], 1970, 2025, rebalance=True)
    rows.append(_compare("T2 rebalanced(diag)", port_rb, target))
    eng = pd.read_csv(JST_RETURNS_CSV)
    eng = eng[eng.Country == "USA"].set_index("Year")["Global_Stock"]
    rows.append(_compare("engine GDP-weighted", eng[eng.index >= 1970], target))

    out = pd.DataFrame(rows).set_index("weights")
    pd.set_option("display.width", 220)
    print("\n== V1: buy-and-hold (JST USD) vs real MSCI EAFE (FIRE intl) ==")
    print(out.round(3).to_string())
    out.to_csv(os.path.join(BASE, "analysis", "output", "v1_buy_and_hold.csv"))

    # per-decade CAGR localization for the primary tier
    port, _ = buy_and_hold(usd, tiers["T2_rz_cap"], 1970, 2025)
    print("\nper-decade CAGR (T2_rz_cap vs MSCI EAFE, pp):")
    for lo in range(1970, 2030, 10):
        yrs = [y for y in port.index if lo <= y <= lo + 9 and y in target.index]
        if not yrs:
            continue
        pc, tc = cagr(port.loc[yrs]) * 100, cagr(target.loc[yrs]) * 100
        print(f"  {lo}s: BH {pc:6.2f}  EAFE {tc:6.2f}  diff {pc-tc:+5.2f}")

    # 1990s attribution diagnostic: restart the buy-and-hold at Dec-1989 with
    # approximate REAL EAFE country weights (Japan ~62% at the bubble peak —
    # commonly cited "~60-65% of EAFE"; remaining weights from published
    # charts, approximate). If the 1990s gap collapses under real weights, the
    # decade residual is weight drift, not JST data inflation.
    w89 = pd.Series({"JPN": 62.0, "GBR": 13.0, "DEU": 6.0, "FRA": 5.0,
                     "CHE": 3.5, "NLD": 2.5, "ITA": 2.5, "AUS": 2.0,
                     "ESP": 1.5, "SWE": 1.5, "BEL": 1.0, "DNK": 0.5,
                     "NOR": 0.5})
    w89 = w89 / w89.sum()
    port89, _ = buy_and_hold(usd, w89, 1990, 1999)
    yrs = [y for y in port89.index if y in target.index]
    pc, tc = cagr(port89.loc[yrs]) * 100, cagr(target.loc[yrs]) * 100
    print(f"\n1990s diagnostic with approx real Dec-1989 EAFE weights "
          f"(JPN 62%): BH {pc:.2f}% vs EAFE {tc:.2f}% (diff {pc-tc:+.2f}pp; "
          f"drifted-T2 weights gave +3.96pp)")

    # modern sub-window vs PURE MSCI EAFE GRTR (the FIRE column blends in
    # EM/Canada + fund fees in recent decades: 0.80 EAFE + 0.15 EM + 0.03 CAN)
    ea = msci_annual("EAFE", "GRTR", "dec")
    yrs = [y for y in port.index if y in ea.index and y <= 2020]
    pc, ec = cagr(port.loc[yrs]) * 100, cagr(ea.loc[yrs]) * 100
    c = float(np.corrcoef(port.loc[yrs], ea.loc[yrs])[0, 1])
    print(f"\n2001-2020 BH vs pure MSCI EAFE GRTR: BH {pc:.2f}% vs EAFE {ec:.2f}% "
          f"(diff {pc-ec:+.2f}pp, corr {c:.3f})")
    print("\nsaved analysis/output/v1_buy_and_hold.csv")


# --------------------------------------------------------------------------
# stage: windowbc — factsheet long windows (B) + public DMS anchors (C)
# --------------------------------------------------------------------------

# MSCI country factsheet values, as of May 29, 2026 (fetched 2026-06-12).
# since_cagr: ANNUALIZED gross USD return since `since`; ytd: Dec-31-2025 ->
# May-29-2026 return used to strip 2026 YTD out of the factsheet CAGR so it
# can be compared with JST ending Dec-2025. FIN factsheet reports PRICE
# returns -> compared against a JST price-only (eq_capgain) USD series.
FACTSHEETS = {
    #        since-date    cagr%   ytd%    kind
    "JPN": ("1994-05-31",  3.23,  16.33, "gross"),
    "CHE": ("1994-05-31",  9.13,   None, "gross"),   # prior study; no fresh YTD
    "DEU": ("1987-12-31",  8.54,   None, "gross"),   # prior study
    "FRA": ("1987-12-31",  8.94,   None, "gross"),   # prior study
    "AUS": ("1987-12-31",  9.49,   None, "gross"),   # prior study
    "NLD": ("1994-05-31", 10.06,  25.06, "gross"),
    "GBR": ("1994-05-31",  7.17,   7.04, "gross"),
    "FIN": ("1987-12-31",  5.64,  19.33, "price"),
    "PRT": ("1987-12-31",  3.14,  12.93, "gross"),
}
FS_ASOF = pd.Timestamp("2026-05-29")


def stage_windowbc() -> None:
    jst = load_jst()
    # JST USD price-only series for the FIN price-caliber comparison
    raw = pd.read_excel(RAW_XLSX)[["year", "iso", "eq_capgain", "xrusd"]]
    raw["extended"] = False
    ext = pd.read_csv(EXT_CSV)[["year", "iso", "eq_capgain", "xrusd"]]
    ext["extended"] = True
    px = pd.concat([raw, ext], ignore_index=True).sort_values(["iso", "year"])
    px["xr_prev"] = px.groupby("iso")["xrusd"].shift(1)
    px["usd_px_ret"] = (1 + px["eq_capgain"]) * px["xr_prev"] / px["xrusd"] - 1

    print("== Window B: MSCI factsheet 'Since' windows vs JST ==")
    print("   (factsheet as of 2026-05-29; adj = 2026 YTD stripped so the MSCI")
    print("    window ends 2025-12-31, matching JST; JST window = first full")
    print("    calendar year after since-date .. 2025)")
    rows = []
    for iso, (since, fs_cagr, ytd, kind) in FACTSHEETS.items():
        since_ts = pd.Timestamp(since)
        # JST side: calendar years since.year(+1 if Dec since-date) .. 2025
        y_start = since_ts.year + 1 if since_ts.month == 12 else since_ts.year
        if kind == "price":
            s = px[(px.iso == iso) & px.year.between(y_start, 2025)]["usd_px_ret"]
        else:
            s = jst[(jst.iso == iso) & jst.year.between(y_start, 2025)]["usd_ret"]
        jst_cagr = cagr(s) * 100
        # strip 2026 YTD from factsheet CAGR
        if ytd is not None:
            t_total = (FS_ASOF - since_ts).days / 365.25
            t_dec25 = (pd.Timestamp("2025-12-31") - since_ts).days / 365.25
            cum = (1 + fs_cagr / 100) ** t_total / (1 + ytd / 100)
            fs_adj = (cum ** (1 / t_dec25) - 1) * 100
        else:
            fs_adj = np.nan
        rows.append({"iso": iso, "since": since, "kind": kind,
                     "jst_cagr": jst_cagr, "msci_factsheet": fs_cagr,
                     "msci_adj_dec25": fs_adj,
                     "diff_vs_adj": jst_cagr - (fs_adj if not math.isnan(fs_adj) else fs_cagr)})
    out = pd.DataFrame(rows).set_index("iso")
    print(out.round(2).to_string())
    out.to_csv(os.path.join(BASE, "analysis", "output", "windowB_factsheets.csv"))

    print("\n== Window C: public DMS yearbook anchors (license-only full table) ==")
    # public anchors from UBS GIRY Summary Edition 2024 (1900-2023):
    #   USA real local 6.5% | CHE real local 4.5% | World ex-US real USD 4.3%
    # NB: include the pre-window CPI base year so the first year's inflation
    # (and hence real return) is not dropped (Codex P7: 1900 off-by-one).
    cpi = pd.read_excel(RAW_XLSX)[["year", "iso", "cpi", "eq_tr"]]
    for iso, dms in [("USA", 6.5), ("CHE", 4.5)]:
        sub = cpi[(cpi.iso == iso) & cpi.year.between(1899, 2020)].copy()
        infl = sub["cpi"].pct_change()
        real = ((1 + sub["eq_tr"]) / (1 + infl) - 1)[sub["year"] >= 1900]
        real = real.dropna()
        y0 = int(sub.loc[real.index, "year"].min())
        c = cagr(real) * 100
        print(f"  {iso}: JST real local {y0}-2020 {c:.2f}% vs DMS 1900-2023 {dms:.1f}%")
    eng = pd.read_csv(JST_RETURNS_CSV)
    eng_g = eng[eng.Country == "USA"].set_index("Year")["Global_Stock"]
    us_cpi = cpi[cpi.iso == "USA"].set_index("year")["cpi"].pct_change()
    yrs = [y for y in range(1900, 2021) if y in eng_g.index]
    real_g = (1 + eng_g.loc[yrs]).to_numpy() / (1 + us_cpi.loc[yrs]).to_numpy() - 1
    print(f"  ex-US: JST GDP-weighted Global_Stock real USD 1900-2020 "
          f"{cagr(real_g)*100:.2f}% vs DMS cap-weighted World-ex-US 1900-2023 4.3% "
          f"(weighting schemes differ; context only)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["download", "identify", "v2", "v1", "windowbc"])
    args = ap.parse_args()
    {"download": stage_download, "identify": stage_identify,
     "v2": stage_v2, "v1": stage_v1, "windowbc": stage_windowbc}[args.stage]()


if __name__ == "__main__":
    main()
