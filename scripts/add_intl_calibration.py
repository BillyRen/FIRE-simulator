#!/usr/bin/env python3
"""Add a source-level investability-calibrated Global_Stock column to
data/jst_returns.csv (purely additive — existing columns are untouched).

Why
---
`Global_Stock` in jst_returns.csv is a GDP-weighted, FX-converted, leave-one-out
basket of *academic* total-return equity series. Academic total-return indices
run systematically hotter than the *investable* float-adjusted indices a retiree
can actually hold (fees, float, frictions). `scripts/backfill_pre1970_intl.py`
already measured this wedge on the JST-USA vs MSCI EAFE 1970-2025 overlap
(k ~= 1.69 pp/yr) and applied it to the pre-1970 FIRE_dataset_intl backfill — but
the canonical multi-country engine series (jst_returns.csv) was never calibrated,
leaving an inconsistent state (pre-1970 US backfill haircut, main engine raw).

Key asymmetry (verified): JST US-domestic equity tracks the investable US index
almost exactly (JST US ~6.71% vs Bogleheads US ~6.75% real, 1970+), so the wedge
lives on the *non-US* academic series, not on US data. We therefore apply the
haircut at the SOURCE: each foreign contributor F to country X's Global basket is
divided by (1 + wedge_F), with wedge_US = 0 and wedge_{non-US} = k, *before* the
GDP-weighted blend. This yields, naturally:
  - US investor (Global = 100% ex-US): full ~k haircut
  - non-US investor (US ~40% of GDP basket): effective ~(1 - w_US) * k ~= 1.0 pp

Limitation: only US (Bogleheads) and ex-US-aggregate (MSCI EAFE) investable
anchors exist, so "wedge_US = 0, wedge_{non-US} = k uniform" is the cleanest
defensible calibration — per-country wedges are not separately identified.

Method
------
We reconstruct, per (country X, year t), the US gross contribution A_X = w_US *
(1 + eq_in_X_US) and total gross S = 1 + Global_Stock_raw using the exact same
decomposition as build_dataset_from_jst.py, then:
  Global_Stock_calibrated = A_X + (S - A_X) / (1 + k) - 1
For the USA row (US excluded from its own basket, A_X = 0) this collapses to the
backfill formula (1 + Global_raw) / (1 + k) - 1.

A self-validation gate asserts the reconstructed raw Global matches the committed
Global_Stock column to 1e-6 for every row; if it does not, the script aborts
without writing (proves the decomposition matches the generator).

Usage
-----
    python scripts/add_intl_calibration.py [--wedge PP]
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

import numpy as np
import pandas as pd

# Reuse the single source of truth for the wedge estimate.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_pre1970_intl import estimate_wedge  # noqa: E402


def atomic_write_csv(df: pd.DataFrame, path: str) -> None:
    """Write CSV atomically with %.8f formatting (matches build_dataset_from_jst.py
    so existing columns stay byte-identical and only the new column is a real diff).
    """
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            df.to_csv(f, index=False, float_format="%.8f")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW_FILE = os.path.join(_BASE_DIR, "data", "raw", "JSTdatasetR6.xlsx")
EXT_FILE = os.path.join(_BASE_DIR, "data", "raw", "jst_extension_2021_2025.csv")
JST_CSV = os.path.join(_BASE_DIR, "data", "jst_returns.csv")
FIRE_CSV = os.path.join(_BASE_DIR, "data", "FIRE_dataset.csv")

MIN_COMPLETE_YEARS = 30  # must match build_dataset_from_jst.py
MARKET_CLOSURE_ROWS = [  # must match build_dataset_from_jst.py
    {"iso": "JPN", "year": 1946},
    {"iso": "JPN", "year": 1947},
]


def build_country_lookup() -> dict[tuple[str, int], dict[str, float]]:
    """Reconstruct the per-(iso, year) eq_tr / fx_change / gdp lookup exactly as
    build_dataset_from_jst.py does, so the blended raw Global matches the engine.
    """
    raw = pd.read_excel(RAW_FILE, sheet_name=0)
    if os.path.exists(EXT_FILE):
        ext = pd.read_csv(EXT_FILE)
        raw = pd.concat([raw, ext], ignore_index=True)
        raw = raw.drop_duplicates(subset=["iso", "year"], keep="last")
        raw = raw.sort_values(["iso", "year"]).reset_index(drop=True)

    lookup: dict[tuple[str, int], dict[str, float]] = {}
    for iso in sorted(raw["iso"].unique()):
        df = raw[raw["iso"] == iso].sort_values("year").copy()
        df["inflation"] = df["cpi"].pct_change()
        df["fx_change"] = df["xrusd"] / df["xrusd"].shift(1)

        # Inject market-closure eq_tr = 0 (frozen markets) before filtering.
        for mc in MARKET_CLOSURE_ROWS:
            if mc["iso"] != iso:
                continue
            mask = df["year"] == mc["year"]
            if mask.any() and pd.isna(df.loc[mask, "eq_tr"].iloc[0]):
                df.loc[mask, "eq_tr"] = 0.0

        # Core requirement (matches build): eq_tr + inflation must exist.
        df = df.dropna(subset=["eq_tr", "inflation"])
        if len(df) < MIN_COMPLETE_YEARS:
            continue

        for _, row in df.iterrows():
            rgdpmad = row.get("rgdpmad", np.nan)
            pop_val = row.get("pop", np.nan)
            if pd.notna(rgdpmad) and pd.notna(pop_val) and rgdpmad > 0 and pop_val > 0:
                gdp_val = rgdpmad * pop_val
            else:
                gdp_val = np.nan
            lookup[(iso, int(row["year"]))] = {
                "eq_tr": float(row["eq_tr"]),
                "fx_change": float(row["fx_change"]) if pd.notna(row["fx_change"]) else np.nan,
                "gdp": float(gdp_val) if pd.notna(gdp_val) else np.nan,
            }
    return lookup


def compute_calibrated(jst: pd.DataFrame, lookup: dict, k: float) -> pd.DataFrame:
    """Return jst with reconstructed raw Global (for validation) and calibrated."""
    # Index lookup by year for fast "others" filtering.
    by_year: dict[int, list[tuple[str, dict]]] = {}
    for (iso, yr), rec in lookup.items():
        by_year.setdefault(yr, []).append((iso, rec))

    raw_recon = np.full(len(jst), np.nan)
    calibrated = np.full(len(jst), np.nan)

    for i, (yr, iso_x) in enumerate(zip(jst["Year"].astype(int), jst["Country"])):
        rec_x = lookup.get((iso_x, yr))
        fxx = rec_x["fx_change"] if rec_x else np.nan

        if rec_x is None or np.isnan(fxx):
            # build's fallback: Global_Stock = Domestic_Stock (home market, no FX).
            # No foreign wedge applies — calibrated equals raw.
            raw_recon[i] = float(jst["Domestic_Stock"].iloc[i])
            calibrated[i] = float(jst["Global_Stock"].iloc[i])
            continue

        others = [
            (iso_f, r) for iso_f, r in by_year.get(yr, [])
            if iso_f != iso_x
            and not np.isnan(r["eq_tr"]) and not np.isnan(r["fx_change"]) and not np.isnan(r["gdp"])
        ]
        if not others:
            raw_recon[i] = np.nan
            calibrated[i] = float(jst["Global_Stock"].iloc[i])
            continue

        total_gdp = sum(r["gdp"] for _, r in others)
        gross_raw = 0.0
        gross_cal = 0.0
        for iso_f, r in others:
            w = r["gdp"] / total_gdp
            eq_in_x = (1.0 + r["eq_tr"]) * (fxx / r["fx_change"]) - 1.0
            gross_raw += w * (1.0 + eq_in_x)
            wedge_f = 0.0 if iso_f == "USA" else k
            gross_cal += w * (1.0 + eq_in_x) / (1.0 + wedge_f)
        raw_recon[i] = gross_raw - 1.0
        calibrated[i] = gross_cal - 1.0

    out = jst.copy()
    out["_raw_recon"] = raw_recon
    out["Global_Stock_calibrated"] = calibrated
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wedge", type=float, default=None,
                    help="override wedge in pp/yr (e.g. 1.9); default = auto 1970-2025")
    args = ap.parse_args()

    jst = pd.read_csv(JST_CSV)
    # Idempotent: if a previous run already appended the calibrated column, drop
    # it so the script recomputes from the raw Global_Stock instead of selecting
    # the column twice (which would write a duplicate and corrupt the CSV).
    if "Global_Stock_calibrated" in jst.columns:
        jst = jst.drop(columns=["Global_Stock_calibrated"])
    fire = pd.read_csv(FIRE_CSV)
    jst_us = jst[jst["Country"] == "USA"][["Year", "Global_Stock"]].copy()
    k = (args.wedge / 100.0) if args.wedge is not None else estimate_wedge(fire, jst_us)

    lookup = build_country_lookup()
    out = compute_calibrated(jst, lookup, k)

    # --- self-validation gate: reconstructed raw must match committed Global ---
    valid = out["_raw_recon"].notna() & out["Global_Stock"].notna()
    diff = (out.loc[valid, "_raw_recon"] - out.loc[valid, "Global_Stock"]).abs()
    max_diff = float(diff.max()) if len(diff) else 0.0
    if max_diff > 1e-6:
        worst = out.loc[valid].assign(d=diff).nlargest(5, "d")[
            ["Year", "Country", "Global_Stock", "_raw_recon"]]
        print("ABORT: reconstructed raw Global does not match committed Global_Stock.")
        print(f"  max abs diff = {max_diff:.3e} (tol 1e-6). Worst rows:\n{worst}")
        sys.exit(1)
    print(f"self-check OK: reconstructed raw Global matches committed (max diff {max_diff:.2e})")

    out = out.drop(columns=["_raw_recon"])
    # Preserve original column order; append calibrated as the last column.
    cols = list(jst.columns) + ["Global_Stock_calibrated"]
    out = out[cols]
    atomic_write_csv(out, JST_CSV)

    # --- summary ---
    def geo(s):
        r = np.asarray(s.dropna(), float)
        return (np.prod(1 + r) ** (1 / len(r)) - 1) * 100 if len(r) else float("nan")

    real_raw = (1 + out["Global_Stock"]) / (1 + out["Inflation"]) - 1
    real_cal = (1 + out["Global_Stock_calibrated"]) / (1 + out["Inflation"]) - 1
    usa = out[out["Country"] == "USA"]
    usa_raw = (1 + usa["Global_Stock"]) / (1 + usa["Inflation"]) - 1
    usa_cal = (1 + usa["Global_Stock_calibrated"]) / (1 + usa["Inflation"]) - 1
    print(f"wedge k = {k*100:.3f} pp/yr")
    print(f"pooled Global real geo:  raw {geo(real_raw):.2f}%  ->  calibrated {geo(real_cal):.2f}%")
    print(f"USA   Global real geo:   raw {geo(usa_raw):.2f}%  ->  calibrated {geo(usa_cal):.2f}%")
    print(f"wrote {JST_CSV} (+1 column Global_Stock_calibrated, existing columns unchanged)")


if __name__ == "__main__":
    main()
