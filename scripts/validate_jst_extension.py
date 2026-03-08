#!/usr/bin/env python3
"""Validate JST 2021-2025 extension data for robustness.

Five validation dimensions:
  1. Statistical distribution consistency (extension vs historical)
  2. USA cross-validation against FIRE_dataset.csv
  3. Global index construction vs MSCI World (yfinance)
  4. Exchange rate splice-point check (2020→2021)
  5. Bond return validation against known benchmarks

Usage:
  python scripts/validate_jst_extension.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")
JST_CSV = os.path.join(DATA_DIR, "jst_returns.csv")
FIRE_CSV = os.path.join(DATA_DIR, "FIRE_dataset.csv")
EXT_CSV = os.path.join(DATA_DIR, "raw", "jst_extension_2021_2025.csv")
JST_RAW = os.path.join(DATA_DIR, "raw", "JSTdatasetR6.xlsx")

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

W = 72


def header(title: str) -> None:
    print(f"\n{'=' * W}")
    print(f"  {title}")
    print(f"{'=' * W}")


def status_line(label: str, status: str, detail: str = "") -> None:
    symbol = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
    line = f"  {symbol} {label}"
    if detail:
        line += f" — {detail}"
    print(line)


# =========================================================================
# Validation 1: Statistical distribution consistency
# =========================================================================
def validate_distribution(jst: pd.DataFrame) -> list[str]:
    header("Validation 1: Statistical Distribution Consistency")
    results = []

    ext = jst[jst["Year"] >= 2021]
    recent = jst[(jst["Year"] >= 2011) & (jst["Year"] <= 2020)]
    modern = jst[(jst["Year"] >= 1970) & (jst["Year"] <= 2020)]

    cols = ["Domestic_Stock", "Domestic_Bond", "Inflation"]
    period_labels = [
        ("Extension 2021-25", ext),
        ("Recent 2011-20", recent),
        ("Modern 1970-2020", modern),
    ]

    for col in cols:
        print(f"\n  --- {col} ---")
        print(f"  {'Period':<22s} {'N':>5s} {'Mean':>8s} {'Std':>8s} {'Min':>8s} {'Max':>8s}")
        for label, df in period_labels:
            v = df[col].dropna()
            print(f"  {label:<22s} {len(v):>5d} {v.mean():>8.4f} {v.std():>8.4f} "
                  f"{v.min():>8.4f} {v.max():>8.4f}")

        ext_mean = ext[col].mean()
        recent_mean = recent[col].mean()
        recent_std = recent[col].std()
        if recent_std > 0:
            z = abs(ext_mean - recent_mean) / recent_std
        else:
            z = 0.0

        if z > 2.0:
            s = WARN
            detail = f"mean z-score={z:.2f} vs recent"
        else:
            s = PASS
            detail = f"mean z-score={z:.2f} vs recent"
        status_line(col, s, detail)
        results.append(s)

    return results


# =========================================================================
# Validation 2: USA cross-validation against FIRE_dataset
# =========================================================================
def validate_usa_cross(jst: pd.DataFrame) -> list[str]:
    header("Validation 2: USA Cross-Validation (JST Extension vs FIRE_dataset)")
    results = []

    fire = pd.read_csv(FIRE_CSV)
    fire = fire[fire["Year"] >= 2021].set_index("Year")

    usa = jst[(jst["Country"] == "USA") & (jst["Year"] >= 2021)].set_index("Year")

    pairs = [
        ("Domestic_Stock", "US Stock"),
        ("Domestic_Bond", "US Bond"),
        ("Inflation", "US Inflation"),
        ("Global_Stock", "International Stock"),
    ]

    for jst_col, fire_col in pairs:
        print(f"\n  --- {jst_col} vs {fire_col} ---")
        print(f"  {'Year':>6s} {'JST ext':>10s} {'FIRE':>10s} {'Diff':>10s} {'Same sign':>10s}")

        diffs = []
        same_sign = 0
        total = 0
        for yr in range(2021, 2026):
            if yr in usa.index and yr in fire.index:
                j = usa.loc[yr, jst_col]
                f = fire.loc[yr, fire_col]
                d = j - f
                ss = "Yes" if (j >= 0) == (f >= 0) else "NO"
                if ss == "Yes":
                    same_sign += 1
                total += 1
                diffs.append(abs(d))
                print(f"  {yr:>6d} {j:>10.4f} {f:>10.4f} {d:>+10.4f} {ss:>10s}")

        avg_diff = np.mean(diffs) if diffs else 0
        sign_pct = same_sign / total * 100 if total else 0

        # Cumulative return comparison
        jst_cum = np.prod(1 + usa[jst_col].values) - 1
        fire_cum = np.prod(1 + fire[fire_col].values) - 1
        cum_diff = jst_cum - fire_cum
        print(f"\n  Cumulative (5yr): JST={jst_cum:.4f} FIRE={fire_cum:.4f} diff={cum_diff:+.4f}")

        if avg_diff > 0.15:
            s = WARN
        else:
            s = PASS
        detail = f"avg|diff|={avg_diff:.4f}, sign agree={sign_pct:.0f}%, cum diff={cum_diff:+.4f}"
        status_line(f"{jst_col}", s, detail)
        results.append(s)

    return results


# =========================================================================
# Validation 3: Global index construction vs MSCI World
# =========================================================================
def validate_global_index(jst: pd.DataFrame) -> list[str]:
    header("Validation 3: Global Index (JST GDP-weighted) vs MSCI World")
    results = []

    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance not installed, skipping MSCI comparison")
        status_line("MSCI World comparison", WARN, "yfinance not available")
        return [WARN]

    # JST Global_Stock for USA = GDP-weighted other countries' returns in USD
    usa_gs = jst[(jst["Country"] == "USA") & (jst["Year"] >= 2021)].set_index("Year")

    # Download MSCI World ETF (URTH) and MSCI ACWI (ACWI) daily data
    msci_returns = {}
    for ticker, label in [("URTH", "MSCI World"), ("ACWI", "MSCI ACWI"), ("VEU", "FTSE All-World ex-US")]:
        try:
            data = yf.download(ticker, start="2020-01-01", end="2026-01-01",
                             interval="1d", progress=False)
            if len(data) == 0:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                close = data[("Close", ticker)].dropna()
            else:
                close = data["Close"].dropna()

            df = pd.DataFrame({"Close": close.values}, index=close.index)
            df["Year"] = df.index.year
            annual_avg = df.groupby("Year")["Close"].mean()
            cg = annual_avg.pct_change()
            msci_returns[label] = {yr: cg[yr] for yr in range(2021, 2026) if yr in cg.index}
        except Exception as e:
            print(f"  {label} download failed: {e}")

    if not msci_returns:
        status_line("MSCI comparison", WARN, "no MSCI data downloaded")
        return [WARN]

    print(f"\n  {'Year':>6s} {'JST GlobStock':>14s}", end="")
    for label in msci_returns:
        print(f" {label:>18s}", end="")
    print()

    for yr in range(2021, 2026):
        jst_val = usa_gs.loc[yr, "Global_Stock"] if yr in usa_gs.index else float("nan")
        print(f"  {yr:>6d} {jst_val:>14.4f}", end="")
        for label, rets in msci_returns.items():
            val = rets.get(yr, float("nan"))
            print(f" {val:>18.4f}", end="")
        print()

    # Compare cumulative returns
    jst_cum = np.prod(1 + usa_gs["Global_Stock"].values) - 1

    print(f"\n  Cumulative (5yr):")
    print(f"    JST Global_Stock (USD view): {jst_cum:.4f} ({jst_cum*100:.1f}%)")

    for label, rets in msci_returns.items():
        vals = [rets.get(yr, 0) for yr in range(2021, 2026)]
        cum = np.prod([1 + v for v in vals]) - 1
        diff = jst_cum - cum
        print(f"    {label}: {cum:.4f} ({cum*100:.1f}%), diff vs JST: {diff:+.4f}")

    # Direction agreement with best proxy (VEU = ex-US, closest to JST Global_Stock)
    best_proxy = "FTSE All-World ex-US" if "FTSE All-World ex-US" in msci_returns else list(msci_returns.keys())[0]
    proxy = msci_returns[best_proxy]
    same_dir = sum(
        1 for yr in range(2021, 2026)
        if yr in proxy and yr in usa_gs.index
        and (usa_gs.loc[yr, "Global_Stock"] >= 0) == (proxy[yr] >= 0)
    )
    total = sum(1 for yr in range(2021, 2026) if yr in proxy and yr in usa_gs.index)

    s = PASS if same_dir == total else WARN
    status_line(f"Direction agreement ({best_proxy})", s, f"{same_dir}/{total} years")
    results.append(s)

    return results


# =========================================================================
# Validation 4: Exchange rate splice-point check
# =========================================================================
def validate_fx_splice(jst: pd.DataFrame) -> list[str]:
    header("Validation 4: Exchange Rate Splice-Point Check (2020→2021)")
    results = []

    ext = pd.read_csv(EXT_CSV)
    raw = pd.read_excel(JST_RAW, sheet_name=0)

    # Eurozone conversion factors
    euro_conv = {
        "BEL": 40.3399, "DEU": 1.95583, "ESP": 166.386, "FIN": 5.94573,
        "FRA": 6.55957, "ITA": 1936.27, "NLD": 2.20371, "PRT": 200.482,
    }

    print(f"\n  {'Country':<6s} {'JST 2020':>12s} {'Ext 2021':>12s} {'fx_change':>12s} "
          f"{'Hist mean':>12s} {'Hist std':>10s} {'z-score':>10s} {'Status':>8s}")

    issues = []
    for iso in sorted(ext["iso"].unique()):
        jst_row = raw[(raw["iso"] == iso) & (raw["year"] == 2020)]
        ext_row = ext[(ext["iso"] == iso) & (ext["year"] == 2021)]

        if len(jst_row) == 0 or len(ext_row) == 0:
            continue

        xr_2020 = jst_row.iloc[0]["xrusd"]
        xr_2021 = ext_row.iloc[0]["xrusd"]
        fx_change = xr_2021 / xr_2020

        # Compute historical fx_change for this country
        country_raw = raw[raw["iso"] == iso].sort_values("year")
        country_raw["fx_change"] = country_raw["xrusd"] / country_raw["xrusd"].shift(1)
        hist_recent = country_raw[(country_raw["year"] >= 2000) & (country_raw["year"] <= 2020)]
        hist_mean = hist_recent["fx_change"].mean()
        hist_std = hist_recent["fx_change"].std()

        if hist_std > 0:
            z = abs(fx_change - hist_mean) / hist_std
        else:
            z = 0

        s = PASS if z < 2.5 else WARN
        if s == WARN:
            issues.append(iso)

        print(f"  {iso:<6s} {xr_2020:>12.4f} {xr_2021:>12.4f} {fx_change:>12.4f} "
              f"{hist_mean:>12.4f} {hist_std:>10.4f} {z:>10.2f} {s:>8s}")

    # Eurozone consistency check
    print(f"\n  --- Eurozone Legacy Currency Consistency ---")
    eur_usd_2021 = ext[(ext["iso"] == "DEU") & (ext["year"] == 2021)].iloc[0]["xrusd"] / euro_conv["DEU"]
    print(f"  Implied EUR/USD from DEU 2021: {eur_usd_2021:.6f}")

    euro_ok = True
    for iso, factor in euro_conv.items():
        ext_row = ext[(ext["iso"] == iso) & (ext["year"] == 2021)]
        if len(ext_row) == 0:
            continue
        implied = ext_row.iloc[0]["xrusd"] / factor
        diff = abs(implied - eur_usd_2021)
        ok = diff < 1e-6
        if not ok:
            euro_ok = False
        print(f"  {iso}: xrusd={ext_row.iloc[0]['xrusd']:.4f}, "
              f"implied EUR/USD={implied:.6f}, "
              f"match={'OK' if ok else 'MISMATCH'}")

    s = PASS if euro_ok else FAIL
    status_line("Eurozone consistency", s,
                "all 8 countries derive same EUR/USD" if euro_ok else "EUR/USD mismatch!")
    results.append(s)

    # Check internal consistency of fx_change within extension (2021-2025)
    print(f"\n  --- Internal FX Consistency (2022-2025 within extension) ---")
    for iso in ["USA", "GBR", "JPN", "DEU"]:
        rows = ext[ext["iso"] == iso].sort_values("year")
        xr = rows.set_index("year")["xrusd"]
        print(f"  {iso}: ", end="")
        for yr in range(2022, 2026):
            if yr in xr.index and yr - 1 in xr.index:
                fc = xr[yr] / xr[yr - 1]
                print(f"{yr}:{fc:.4f} ", end="")
        print()

    s = PASS if len(issues) == 0 else WARN
    detail = f"{len(issues)} countries with z>2.5" if issues else "all within historical range"
    status_line("FX splice z-scores", s, detail)
    results.append(s)

    return results


# =========================================================================
# Validation 5: Bond return validation
# =========================================================================
def validate_bonds(jst: pd.DataFrame) -> list[str]:
    header("Validation 5: Bond Return Validation")
    results = []

    # USA: compare with FIRE_dataset
    fire = pd.read_csv(FIRE_CSV)
    fire = fire[fire["Year"] >= 2021].set_index("Year")
    usa = jst[(jst["Country"] == "USA") & (jst["Year"] >= 2021)].set_index("Year")

    print(f"\n  --- USA Bond Returns: JST Extension vs FIRE_dataset ---")
    print(f"  {'Year':>6s} {'JST ext':>10s} {'FIRE':>10s} {'Diff':>10s}")

    diffs = []
    for yr in range(2021, 2026):
        if yr in usa.index and yr in fire.index:
            j = usa.loc[yr, "Domestic_Bond"]
            f = fire.loc[yr, "US Bond"]
            d = j - f
            diffs.append(abs(d))
            print(f"  {yr:>6d} {j:>10.4f} {f:>10.4f} {d:>+10.4f}")

    jst_cum = np.prod(1 + usa["Domestic_Bond"].values) - 1
    fire_cum = np.prod(1 + fire["US Bond"].values) - 1
    print(f"\n  Cumulative: JST={jst_cum:.4f}, FIRE={fire_cum:.4f}, diff={jst_cum - fire_cum:+.4f}")

    avg_diff = np.mean(diffs) if diffs else 0
    s = PASS if avg_diff < 0.05 else WARN
    status_line("USA bond returns", s, f"avg|diff|={avg_diff:.4f}")
    results.append(s)

    # Bond return sign check: when rates rose sharply, returns should be negative
    print(f"\n  --- Bond Return Sanity: Rate Rise → Negative Return ---")
    ext = pd.read_csv(EXT_CSV)

    print(f"  {'Country':<6s} {'Year':>6s} {'Δltrate':>10s} {'bond_tr':>10s} {'Consistent':>12s}")
    issues = 0
    for _, row in ext.iterrows():
        iso, yr = row["iso"], row["year"]
        if yr == 2021:
            # need JST 2020 ltrate for comparison
            raw = pd.read_excel(JST_RAW, sheet_name=0)
            jst_row = raw[(raw["iso"] == iso) & (raw["year"] == 2020)]
            if len(jst_row) == 0:
                continue
            prev_lt = jst_row.iloc[0].get("ltrate", np.nan)
        else:
            prev_rows = ext[(ext["iso"] == iso) & (ext["year"] == yr - 1)]
            if len(prev_rows) == 0:
                continue
            prev_lt = prev_rows.iloc[0]["ltrate"]

        if pd.isna(prev_lt):
            continue

        delta_lt = row["ltrate"] - prev_lt
        bond_tr = row["bond_tr"]

        # When rates rise significantly (>0.5pp), bond returns should be negative
        if abs(delta_lt) > 0.5:
            consistent = (delta_lt > 0 and bond_tr < 0) or (delta_lt < 0 and bond_tr > 0) or abs(delta_lt) < 0.1
            ok = "OK" if consistent else "INCONSISTENT"
            if not consistent:
                issues += 1
            print(f"  {iso:<6s} {yr:>6.0f} {delta_lt:>+10.2f} {bond_tr:>10.4f} {ok:>12s}")

    s = PASS if issues == 0 else WARN
    status_line("Bond rate/return consistency", s, f"{issues} inconsistencies")
    results.append(s)

    return results


# =========================================================================
# Main
# =========================================================================
def main() -> None:
    print("=" * W)
    print("  JST EXTENSION DATA VALIDATION REPORT")
    print("=" * W)

    jst = pd.read_csv(JST_CSV)
    print(f"\n  Dataset: {len(jst)} rows, {jst['Country'].nunique()} countries, "
          f"{jst['Year'].min()}-{jst['Year'].max()}")
    print(f"  Extension rows (2021-2025): {len(jst[jst['Year'] >= 2021])}")

    all_results = []

    r1 = validate_distribution(jst)
    all_results.extend(r1)

    r2 = validate_usa_cross(jst)
    all_results.extend(r2)

    r3 = validate_global_index(jst)
    all_results.extend(r3)

    r4 = validate_fx_splice(jst)
    all_results.extend(r4)

    r5 = validate_bonds(jst)
    all_results.extend(r5)

    # Summary
    header("VALIDATION SUMMARY")
    n_pass = sum(1 for r in all_results if r == PASS)
    n_warn = sum(1 for r in all_results if r == WARN)
    n_fail = sum(1 for r in all_results if r == FAIL)
    print(f"\n  Total checks: {len(all_results)}")
    print(f"  PASS: {n_pass}  |  WARN: {n_warn}  |  FAIL: {n_fail}")

    if n_fail > 0:
        print(f"\n  RESULT: VALIDATION FAILED — {n_fail} critical issue(s)")
    elif n_warn > 0:
        print(f"\n  RESULT: VALIDATION PASSED WITH WARNINGS — {n_warn} item(s) to review")
    else:
        print(f"\n  RESULT: ALL CHECKS PASSED")

    print()


if __name__ == "__main__":
    main()
