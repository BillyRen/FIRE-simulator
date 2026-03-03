#!/usr/bin/env python3
"""Build FIRE simulator dataset from JST Macrohistory Database (R6).

Data source:
  Jordà, Schularick & Taylor (2017), "Macrofinancial History and the
  New Business Cycle Facts", NBER Macroeconomics Annual 2016, vol 31.
  https://www.macrohistory.net/database/
  License: CC BY-NC-SA 4.0

Reads JSTdatasetR6.xlsx and produces:
  - data/jst_returns.csv   (long format: Year, Country, Domestic_Stock, Global_Stock, Domestic_Bond, Inflation)
  - data/jst_countries.json (country metadata with year ranges)

Design decisions:
  - Output columns are NOMINAL returns + inflation (engine computes real returns).
  - Global_Stock is GDP-weighted average of other countries' equity returns,
    converted to investor's home currency via exchange rates.
  - GDP weights use rgdpmad * pop (Maddison real GDP per capita in intl $
    times population) for cross-country comparability.
  - Rows are kept if eq_tr is available; missing bond_tr is filled with 0
    (conservative: bonds earn zero nominal return, get eroded by inflation).
  - For known market-closure periods (e.g. JPN 1946-1947), eq_tr is set to 0
    (assets frozen, no nominal gain; real value destroyed by inflation).
  - Countries with < 30 complete years are excluded.
  - FX conversion: eq_tr_F_in_X = (1 + eq_tr_F) * (fx_change_X / fx_change_F) - 1
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_COMPLETE_YEARS = 30
RAW_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "JSTdatasetR6.xlsx")
OUT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "jst_returns.csv")
OUT_JSON = os.path.join(os.path.dirname(__file__), "..", "data", "jst_countries.json")

COUNTRY_NAMES = {
    "AUS": ("Australia", "澳大利亚"),
    "BEL": ("Belgium", "比利时"),
    "CAN": ("Canada", "加拿大"),
    "CHE": ("Switzerland", "瑞士"),
    "DEU": ("Germany", "德国"),
    "DNK": ("Denmark", "丹麦"),
    "ESP": ("Spain", "西班牙"),
    "FIN": ("Finland", "芬兰"),
    "FRA": ("France", "法国"),
    "GBR": ("United Kingdom", "英国"),
    "IRL": ("Ireland", "爱尔兰"),
    "ITA": ("Italy", "意大利"),
    "JPN": ("Japan", "日本"),
    "NLD": ("Netherlands", "荷兰"),
    "NOR": ("Norway", "挪威"),
    "PRT": ("Portugal", "葡萄牙"),
    "SWE": ("Sweden", "瑞典"),
    "USA": ("United States", "美国"),
}

# Known market-closure periods: stock exchanges shut, assets frozen.
# We model these as eq_tr = 0 (frozen nominal value, eroded by inflation).
MARKET_CLOSURE_ROWS = [
    # JPN: Tokyo Stock Exchange closed Aug 1945 - May 1949
    # JST has bond_tr and CPI for 1946-1947 but no eq_tr
    {"iso": "JPN", "year": 1946},
    {"iso": "JPN", "year": 1947},
]


def main() -> None:
    print("Reading JST dataset...")
    raw = pd.read_excel(RAW_FILE, sheet_name=0)
    print(f"  Raw rows: {len(raw)}, countries: {raw['iso'].nunique()}")

    # ------------------------------------------------------------------
    # 1. Per-country: compute inflation and fx_change, filter rows
    # ------------------------------------------------------------------
    country_frames: dict[str, pd.DataFrame] = {}

    for iso in sorted(raw["iso"].unique()):
        df = raw[raw["iso"] == iso].sort_values("year").copy()

        # Compute inflation from CPI
        df["inflation"] = df["cpi"].pct_change()

        # Compute FX change (xrusd[t] / xrusd[t-1])
        df["fx_change"] = df["xrusd"] / df["xrusd"].shift(1)

        # ----------------------------------------------------------
        # Inject market-closure rows: set eq_tr = 0 for frozen markets
        # ----------------------------------------------------------
        for mc in MARKET_CLOSURE_ROWS:
            if mc["iso"] != iso:
                continue
            mask = df["year"] == mc["year"]
            if mask.any() and pd.isna(df.loc[mask, "eq_tr"].iloc[0]):
                df.loc[mask, "eq_tr"] = 0.0
                print(f"  {iso} {mc['year']}: injected eq_tr=0 (market closure)")

        # ----------------------------------------------------------
        # Fill missing bond_tr with 0 (conservative: zero nominal return)
        # ----------------------------------------------------------
        bond_missing = df["eq_tr"].notna() & df["bond_tr"].isna()
        n_filled = bond_missing.sum()
        if n_filled > 0:
            df.loc[bond_missing, "bond_tr"] = 0.0
            years_filled = sorted(df.loc[bond_missing, "year"].astype(int).tolist())
            print(f"  {iso}: filled bond_tr=0 for {n_filled} rows: {years_filled}")

        # ----------------------------------------------------------
        # Core requirement: must have eq_tr + inflation + fx_change
        # (bond_tr is now filled; fx_change can be NaN for isolated years)
        # ----------------------------------------------------------
        # Minimum: eq_tr and inflation must exist
        required_strict = ["eq_tr", "inflation"]
        df = df.dropna(subset=required_strict)

        if len(df) < MIN_COMPLETE_YEARS:
            print(f"  {iso}: {len(df)} usable years < {MIN_COMPLETE_YEARS}, skipping")
            continue

        country_frames[iso] = df.reset_index(drop=True)
        yr_min, yr_max = int(df["year"].min()), int(df["year"].max())
        print(f"  {iso}: {len(df)} usable years ({yr_min}-{yr_max})")

    valid_isos = sorted(country_frames.keys())
    print(f"\n{len(valid_isos)} countries pass threshold: {valid_isos}")

    # ------------------------------------------------------------------
    # 2. Build per-year lookup tables for GDP weights and FX-adjusted returns
    # ------------------------------------------------------------------
    # Collect all (iso, year, eq_tr, fx_change, gdp_comparable) into a flat table
    all_records = []
    for iso, df in country_frames.items():
        for _, row in df.iterrows():
            rgdpmad = row.get("rgdpmad", np.nan)
            pop_val = row.get("pop", np.nan)
            if pd.notna(rgdpmad) and pd.notna(pop_val) and rgdpmad > 0 and pop_val > 0:
                gdp_val = rgdpmad * pop_val
            else:
                gdp_val = np.nan
            all_records.append({
                "iso": iso,
                "year": int(row["year"]),
                "eq_tr": row["eq_tr"],
                "fx_change": row["fx_change"],
                "gdp": gdp_val,
            })

    lookup_df = pd.DataFrame(all_records)

    # ------------------------------------------------------------------
    # 3. For each country X and each year, compute Global_Stock
    # ------------------------------------------------------------------
    output_rows = []

    for iso_x in valid_isos:
        df_x = country_frames[iso_x]

        for _, row_x in df_x.iterrows():
            year = int(row_x["year"])
            fx_change_x = row_x["fx_change"]

            # If fx_change is missing for this row, we cannot compute
            # FX-adjusted global returns → fall back to Domestic_Stock
            if pd.isna(fx_change_x):
                global_stock = row_x["eq_tr"]  # fallback: assume global ≈ domestic
                output_rows.append({
                    "Year": year,
                    "Country": iso_x,
                    "Domestic_Stock": row_x["eq_tr"],
                    "Global_Stock": global_stock,
                    "Domestic_Bond": row_x["bond_tr"],
                    "Inflation": row_x["inflation"],
                })
                print(f"  {iso_x} {year}: fx_change missing, Global_Stock = Domestic_Stock ({global_stock:.4f})")
                continue

            # Get all other countries' data for this year
            others = lookup_df[
                (lookup_df["year"] == year) & (lookup_df["iso"] != iso_x)
            ].copy()

            # Filter to those with valid eq_tr, fx_change, and gdp
            others = others.dropna(subset=["eq_tr", "fx_change", "gdp"])

            if len(others) > 0:
                # FX-adjusted nominal return of foreign equity in X's currency
                others["eq_in_x"] = (
                    (1.0 + others["eq_tr"]) * (fx_change_x / others["fx_change"]) - 1.0
                )

                # GDP-weighted average
                total_gdp = others["gdp"].sum()
                others["weight"] = others["gdp"] / total_gdp
                global_stock = (others["eq_in_x"] * others["weight"]).sum()
            else:
                global_stock = np.nan

            output_rows.append({
                "Year": year,
                "Country": iso_x,
                "Domestic_Stock": row_x["eq_tr"],
                "Global_Stock": global_stock,
                "Domestic_Bond": row_x["bond_tr"],
                "Inflation": row_x["inflation"],
            })

    result = pd.DataFrame(output_rows)

    # Drop rows where Global_Stock is NaN (no other countries available)
    before = len(result)
    result = result.dropna(subset=["Global_Stock"])
    after = len(result)
    if before != after:
        print(f"\nDropped {before - after} rows with missing Global_Stock")

    result = result.sort_values(["Country", "Year"]).reset_index(drop=True)
    print(f"\nFinal dataset: {len(result)} rows, {result['Country'].nunique()} countries")

    # ------------------------------------------------------------------
    # 4. Output CSV
    # ------------------------------------------------------------------
    result.to_csv(OUT_CSV, index=False, float_format="%.8f")
    print(f"Wrote {OUT_CSV}")

    # ------------------------------------------------------------------
    # 5. Output country metadata JSON
    # ------------------------------------------------------------------
    countries_meta = []
    for iso in sorted(result["Country"].unique()):
        sub = result[result["Country"] == iso]
        en_name, zh_name = COUNTRY_NAMES.get(iso, (iso, iso))
        countries_meta.append({
            "iso": iso,
            "name_en": en_name,
            "name_zh": zh_name,
            "min_year": int(sub["Year"].min()),
            "max_year": int(sub["Year"].max()),
            "n_years": len(sub),
        })

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(countries_meta, f, ensure_ascii=False, indent=2)
    print(f"Wrote {OUT_JSON}")

    # ------------------------------------------------------------------
    # 6. Summary statistics
    # ------------------------------------------------------------------
    print("\n=== Summary Statistics (annualized mean) ===")
    for iso in sorted(result["Country"].unique()):
        sub = result[result["Country"] == iso]
        ds = sub["Domestic_Stock"].mean() * 100
        gs = sub["Global_Stock"].mean() * 100
        db = sub["Domestic_Bond"].mean() * 100
        inf = sub["Inflation"].mean() * 100
        print(f"  {iso}: DomStock={ds:+.2f}% GlobStock={gs:+.2f}% DomBond={db:+.2f}% Infl={inf:+.2f}%")

    # ------------------------------------------------------------------
    # 7. Report filled/injected rows
    # ------------------------------------------------------------------
    print("\n=== Filled / Injected Rows Summary ===")
    for mc in MARKET_CLOSURE_ROWS:
        row = result[(result["Country"] == mc["iso"]) & (result["Year"] == mc["year"])]
        if len(row) > 0:
            r = row.iloc[0]
            print(f"  {mc['iso']} {mc['year']} (market closure): "
                  f"DomStock={r['Domestic_Stock']:.4f}, DomBond={r['Domestic_Bond']:.4f}, "
                  f"Infl={r['Inflation']:.4f}")


if __name__ == "__main__":
    main()
