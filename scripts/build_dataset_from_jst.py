#!/usr/bin/env python3
"""Build FIRE simulator dataset from JST Macrohistory Database (R6).

Data source:
  Jordà, Schularick & Taylor (2017), "Macrofinancial History and the
  New Business Cycle Facts", NBER Macroeconomics Annual 2016, vol 31.
  https://www.macrohistory.net/database/
  License: CC BY-NC-SA 4.0

Reads JSTdatasetR6.xlsx and produces:
  - data/jst_returns.csv   (long format with core + housing columns)
  - data/jst_countries.json (country metadata with year ranges and housing flags)

Output columns (all NOMINAL — engine computes real values internally):
  Core (always present):
    Year, Country, Domestic_Stock, Global_Stock, Domestic_Bond, Inflation
  Housing (NaN for countries/years without data):
    Housing_CapGain  — nominal house price capital gain rate
    Housing_TR       — nominal total housing return (capital gain + rental income)
    Housing_Rent_YD  — rental yield (annual rent / house price, decimal)
    Rent_Growth      — nominal rent growth rate (derived from rent_yd * hpnom)
    Long_Rate        — long-term government bond yield (decimal, e.g. 0.05)

Design decisions:
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
  - Housing columns are optional: NaN values are preserved for countries/years
    without housing data (CAN, IRL have no housing returns in JST R6).
  - Housing_TR sourcing priority:
    1. JST R6 housing_tr (exact = housing_capgain + housing_rent_rtn)
    2. Reconstructed as (1+capgain)*(1+rent_yd)-1 (for extension data 2021-2025
       where housing_rent_rtn is unavailable; matches JST definition where
       rent_rtn ≈ rent_yd*(1+capgain))
    3. (1+capgain)*(1+country_median_rent_yd)-1 (for early years where rent_yd
       is missing but capgain exists; ~136 rows across 8 countries)
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
EXT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "jst_extension_2021_2025.csv")
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

    if os.path.exists(EXT_FILE):
        print(f"  Loading extension data from {os.path.basename(EXT_FILE)}...")
        ext = pd.read_csv(EXT_FILE)
        ext_years = sorted(ext["year"].unique())
        print(f"  Extension: {len(ext)} rows, years {ext_years[0]}-{ext_years[-1]}")
        raw = pd.concat([raw, ext], ignore_index=True)
        raw = raw.drop_duplicates(subset=["iso", "year"], keep="last")
        raw = raw.sort_values(["iso", "year"]).reset_index(drop=True)
        print(f"  Merged: {len(raw)} rows, countries: {raw['iso'].nunique()}")

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
        # Housing columns (all nominal; NaN when source data missing)
        # ----------------------------------------------------------
        # housing_capgain: nominal house price capital gain (already a rate)
        df["_housing_capgain"] = df.get("housing_capgain", np.nan)

        # housing_rent_yd: rental yield (rent / price ratio)
        df["_housing_rent_yd"] = df.get("housing_rent_yd", np.nan)

        # housing_tr: total nominal housing return (capgain + rental income)
        # Priority: use JST housing_tr directly; fall back to reconstruction
        df["_housing_tr"] = df.get("housing_tr", np.nan)

        # For rows with capgain but no housing_tr: reconstruct using
        # multiplicative formula: (1+capgain)*(1+rent_yd) - 1
        # This matches JST's definition: housing_tr = capgain + rent_rtn,
        # where rent_rtn ≈ rent_yd*(1+capgain). The multiplicative form
        # is more accurate than simple addition (97% of rows closer to
        # actual housing_tr; additive can err by ~5% in extreme years).
        #
        # Case A: housing_rent_yd available → multiplicative reconstruction
        can_reconstruct = (
            df["_housing_tr"].isna()
            & df["_housing_capgain"].notna()
            & df["_housing_rent_yd"].notna()
        )
        n_recon_a = int(can_reconstruct.sum())
        if n_recon_a > 0:
            cg = df.loc[can_reconstruct, "_housing_capgain"]
            yd = df.loc[can_reconstruct, "_housing_rent_yd"]
            df.loc[can_reconstruct, "_housing_tr"] = (1 + cg) * (1 + yd) - 1
            years_a = sorted(df.loc[can_reconstruct, "year"].astype(int).tolist())
            print(f"  {iso}: reconstructed Housing_TR = (1+cg)*(1+yd)-1 for {n_recon_a} rows: {years_a}")

        # Case B: no rent_yd → use country-median rent_yd
        median_yd = df["_housing_rent_yd"].median()  # NaN if no data at all
        need_median_fill = (
            df["_housing_tr"].isna()
            & df["_housing_capgain"].notna()
            & pd.notna(median_yd)
        )
        n_recon_b = int(need_median_fill.sum())
        if n_recon_b > 0:
            cg = df.loc[need_median_fill, "_housing_capgain"]
            df.loc[need_median_fill, "_housing_tr"] = (1 + cg) * (1 + median_yd) - 1
            # Also fill rent_yd for these rows so it's consistent
            df.loc[need_median_fill, "_housing_rent_yd"] = median_yd
            years_b = sorted(df.loc[need_median_fill, "year"].astype(int).tolist())
            print(f"  {iso}: filled Housing_TR = (1+cg)*(1+median_yd({median_yd:.4f}))-1 for {n_recon_b} rows: {years_b}")

        # ----------------------------------------------------------
        # Rent growth: derived from nominal rent level = rent_yd * hpnom
        # Uses the FILLED _housing_rent_yd series (including median-yd
        # fallback rows) so Rent_Growth is consistent with Housing_Rent_YD.
        #
        # However, pct_change() at boundaries where imputation status
        # changes (imputed→observed or observed→imputed) produces
        # artifacts: the growth rate reflects a jump between synthetic
        # and real rent levels, not actual rent dynamics. We NaN these
        # transition rows so they fall back to the inflation proxy.
        # ----------------------------------------------------------
        yd_was_imputed = need_median_fill.copy() if n_recon_b > 0 else pd.Series(False, index=df.index)
        if "hpnom" in df.columns:
            rent_level = df["_housing_rent_yd"] * df["hpnom"]
            df["_rent_growth"] = rent_level.pct_change()
            # NaN out transition rows at imputed↔observed boundaries
            if yd_was_imputed.any():
                prev_imputed = yd_was_imputed.shift(1, fill_value=False)
                transition = (yd_was_imputed != prev_imputed) & df["_rent_growth"].notna()
                n_transition = int(transition.sum())
                if n_transition > 0:
                    df.loc[transition, "_rent_growth"] = np.nan
                    years_t = sorted(df.loc[transition, "year"].astype(int).tolist())
                    print(f"  {iso}: NaN'd Rent_Growth at {n_transition} imputed/observed transition(s): {years_t}")
        else:
            df["_rent_growth"] = np.nan

        # Long-term rate: convert from percentage points to decimal
        if "ltrate" in df.columns:
            df["_long_rate"] = df["ltrate"] / 100.0
        else:
            df["_long_rate"] = np.nan

        # ----------------------------------------------------------
        # Fill missing Rent_Growth with inflation (conservative proxy)
        # corr(Rent_Growth, Inflation) ≈ 0.30 globally, mean diff ≈ +1%,
        # so inflation slightly underestimates rent growth (conservative).
        # This preserves extreme Housing_CapGain rows (wars, crises).
        # ----------------------------------------------------------
        rent_missing = df["_housing_capgain"].notna() & df["_rent_growth"].isna()
        n_rent_filled = int(rent_missing.sum())
        if n_rent_filled > 0:
            df.loc[rent_missing, "_rent_growth"] = df.loc[rent_missing, "inflation"]
            years_filled = sorted(df.loc[rent_missing, "year"].astype(int).tolist())
            print(f"  {iso}: filled Rent_Growth=inflation for {n_rent_filled} rows: {years_filled}")

        # ----------------------------------------------------------
        # Fill missing Long_Rate with forward/backward fill (within country)
        # Only affects isolated war-year gaps (~20 rows total across all countries).
        # ----------------------------------------------------------
        lr_missing_before = df["_long_rate"].isna() & df["_housing_capgain"].notna()
        df["_long_rate"] = df["_long_rate"].ffill().bfill()
        lr_missing_after = df["_long_rate"].isna() & df["_housing_capgain"].notna()
        n_lr_filled = int(lr_missing_before.sum() - lr_missing_after.sum())
        if n_lr_filled > 0:
            filled_mask = lr_missing_before & ~lr_missing_after
            years_filled = sorted(df.loc[filled_mask, "year"].astype(int).tolist())
            print(f"  {iso}: filled Long_Rate=ffill/bfill for {n_lr_filled} rows: {years_filled}")

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

            # Housing columns for this row (may be NaN)
            housing_capgain = row_x.get("_housing_capgain", np.nan)
            housing_tr = row_x.get("_housing_tr", np.nan)
            housing_rent_yd = row_x.get("_housing_rent_yd", np.nan)
            rent_growth = row_x.get("_rent_growth", np.nan)
            long_rate = row_x.get("_long_rate", np.nan)

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
                    "Housing_CapGain": housing_capgain,
                    "Housing_TR": housing_tr,
                    "Housing_Rent_YD": housing_rent_yd,
                    "Rent_Growth": rent_growth,
                    "Long_Rate": long_rate,
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
                "Housing_CapGain": housing_capgain,
                "Housing_TR": housing_tr,
                "Housing_Rent_YD": housing_rent_yd,
                "Rent_Growth": rent_growth,
                "Long_Rate": long_rate,
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
        housing_years = int(sub["Housing_CapGain"].notna().sum())
        housing_tr_years = int(sub["Housing_TR"].notna().sum())
        max_year = int(sub["Year"].max())
        jst_max = 2020  # JST R6 official data ends in 2020
        countries_meta.append({
            "iso": iso,
            "name_en": en_name,
            "name_zh": zh_name,
            "min_year": int(sub["Year"].min()),
            "max_year": max_year,
            "n_years": len(sub),
            "has_housing": housing_years > 0,
            "housing_years": housing_years,
            "housing_tr_years": housing_tr_years,
            "extended": max_year > jst_max,
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
        hcg = sub["Housing_CapGain"].dropna()
        htr = sub["Housing_TR"].dropna()
        hyd = sub["Housing_Rent_YD"].dropna()
        rg = sub["Rent_Growth"].dropna()
        lr = sub["Long_Rate"].dropna()
        housing_str = ""
        if len(hcg) > 0:
            htr_str = f" HousTR={htr.mean()*100:+.2f}%" if len(htr) > 0 else ""
            hyd_str = f" RentYD={hyd.mean()*100:.2f}%" if len(hyd) > 0 else ""
            housing_str = (f" HousCG={hcg.mean()*100:+.2f}%{htr_str}{hyd_str}"
                           f" RentGr={rg.mean()*100:+.2f}%"
                           f" LongRate={lr.mean()*100:.2f}%"
                           f" (n_cg={len(hcg)}, n_tr={len(htr)})")
        else:
            housing_str = " (no housing data)"
        print(f"  {iso}: DomStock={ds:+.2f}% GlobStock={gs:+.2f}% DomBond={db:+.2f}% Infl={inf:+.2f}%{housing_str}")

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
