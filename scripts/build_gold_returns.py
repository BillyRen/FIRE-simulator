#!/usr/bin/env python3
"""Build per-country nominal gold returns for the JST simulator dataset.

This is a *data-preparation* step only — it produces a standalone
``data/jst_gold.csv`` parallel to ``data/jst_returns.csv``. It is NOT wired
into the simulator engine; it exists so a gold asset class can be added later
without re-deriving the source data.

Methodology
-----------
Gold trades on a single global market priced in USD. To express its return in
each country's home currency (the convention used by every other column in
``jst_returns.csv``, which are nominal local-currency returns), we convert the
USD gold price with the JST USD exchange rate ``xrusd`` (units of local
currency per USD) — exactly parallel to how ``build_dataset_from_jst.py``
converts foreign equity returns into the investor's home currency:

    gold_local[t]          = gold_usd[t] * xrusd[t]
    Gold_Nominal_Return[t] = gold_local[t] / gold_local[t-1] - 1
                           = (gold_usd[t]/gold_usd[t-1]) * (xrusd[t]/xrusd[t-1]) - 1

For the USA ``xrusd == 1.0``, so the column reduces to the plain USD gold
return. The result is a *nominal* return; the engine's existing real-return
conversion (divide by ``1 + Inflation``) applies uniformly, just like the
other asset columns.

Data sources
------------
- Gold price (USD / fine troy oz, annual average): ``data/raw/gold_usd_annual.csv``
  World Bank Commodity Markets "Pink Sheet" (1960-present) spliced with
  Timothy Green's historical series (1833-1959), as compiled by the National
  Mining Association. Mirror: github.com/datasets/gold-prices (CC0).
  Note: 1871-1933 values (~$18.9-20.7) reflect the classical gold standard;
  1934-1971 (~$35) Bretton Woods; floating market averages thereafter.
- Exchange rates ``xrusd``: JST Macrohistory Database R6 (1870-2020) plus the
  project's unofficial 2021-2025 extension (``jst_extension_2021_2025.csv``).

Keys are aligned exactly to ``data/jst_returns.csv`` (same Country/Year rows),
so this file can be joined 1:1 onto the existing dataset.

Output: ``data/jst_gold.csv`` with columns
    Year, Country, Gold_USD_per_oz, xrusd, Gold_Nominal_Return
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
RAW_FILE = os.path.join(HERE, "..", "data", "raw", "JSTdatasetR6.xlsx")
EXT_FILE = os.path.join(HERE, "..", "data", "raw", "jst_extension_2021_2025.csv")
GOLD_FILE = os.path.join(HERE, "..", "data", "raw", "gold_usd_annual.csv")
RETURNS_FILE = os.path.join(HERE, "..", "data", "jst_returns.csv")
OUT_CSV = os.path.join(HERE, "..", "data", "jst_gold.csv")


def load_xrusd() -> pd.DataFrame:
    """Return long-format (iso, year, xrusd) from JST raw + extension."""
    raw = pd.read_excel(RAW_FILE, sheet_name=0)[["iso", "year", "xrusd"]]
    if os.path.exists(EXT_FILE):
        ext = pd.read_csv(EXT_FILE)[["iso", "year", "xrusd"]]
        raw = pd.concat([raw, ext], ignore_index=True)
    # Extension rows take precedence over any overlapping raw rows.
    raw = raw.drop_duplicates(subset=["iso", "year"], keep="last")
    raw = raw.sort_values(["iso", "year"]).reset_index(drop=True)
    raw["year"] = raw["year"].astype(int)
    return raw


def main() -> None:
    print("Loading inputs...")
    keys = pd.read_csv(RETURNS_FILE)[["Year", "Country"]].copy()
    keys["Year"] = keys["Year"].astype(int)
    print(f"  jst_returns.csv keys: {len(keys)} rows, "
          f"{keys['Country'].nunique()} countries, "
          f"{keys['Year'].min()}-{keys['Year'].max()}")

    gold = pd.read_csv(GOLD_FILE)
    gold["Year"] = gold["Year"].astype(int)
    gold_by_year = gold.set_index("Year")["Gold_USD_per_oz"]
    print(f"  gold_usd_annual.csv: {len(gold)} rows, "
          f"{gold['Year'].min()}-{gold['Year'].max()}")

    fx = load_xrusd()
    print(f"  xrusd: {len(fx)} rows, {fx['year'].min()}-{fx['year'].max()}")

    # Guard against a fresh checkout missing the gitignored 2021-2025 extension:
    # raw JST xrusd ends at 2020, so without the extension every 2021-2025 key
    # would silently produce a NaN return and overwrite the committed file.
    max_fx_year = int(fx.loc[fx["xrusd"].notna(), "year"].max())
    max_key_year = int(keys["Year"].max())
    if max_key_year > max_fx_year:
        raise SystemExit(
            f"xrusd only covers through {max_fx_year} but jst_returns.csv keys "
            f"reach {max_key_year}. The JST extension "
            f"(data/raw/jst_extension_2021_2025.csv) is likely missing — "
            f"aborting to avoid writing NaN returns over the committed file."
        )

    # ------------------------------------------------------------------
    # Compute nominal local-currency gold return per country.
    # We iterate per country so prior-year (t-1) lookups respect the
    # country's own xrusd series (and its gaps), and we evaluate the
    # return only on the (Country, Year) keys present in jst_returns.csv.
    # ------------------------------------------------------------------
    out_rows = []
    nan_report: dict[str, list[int]] = {}

    for iso in sorted(keys["Country"].unique()):
        want_years = set(keys.loc[keys["Country"] == iso, "Year"].tolist())
        fx_iso = fx[fx["iso"] == iso].set_index("year")["xrusd"]

        for yr in sorted(want_years):
            g_t = gold_by_year.get(yr, np.nan)
            g_p = gold_by_year.get(yr - 1, np.nan)
            x_t = fx_iso.get(yr, np.nan)
            x_p = fx_iso.get(yr - 1, np.nan)

            if (
                pd.notna(g_t) and pd.notna(g_p) and g_p != 0
                and pd.notna(x_t) and pd.notna(x_p) and x_p != 0
            ):
                ret = (g_t / g_p) * (x_t / x_p) - 1.0
            else:
                ret = np.nan
                nan_report.setdefault(iso, []).append(yr)

            out_rows.append({
                "Year": yr,
                "Country": iso,
                "Gold_USD_per_oz": g_t,
                "xrusd": x_t,
                "Gold_Nominal_Return": ret,
            })

    out = pd.DataFrame(out_rows).sort_values(["Country", "Year"]).reset_index(drop=True)

    # Round for a tidy, diff-friendly CSV (8 dp matches jst_returns.csv).
    # xrusd is NOT fixed-decimal rounded: under hyperinflation (e.g. DEU early
    # 1920s) levels are ~1e-12, which round(6) would flatten to a misleading
    # 0.0 and break reproducibility. Use 10 significant figures instead so both
    # normal (~0.37) and tiny levels survive; NaN -> empty cell.
    out["Gold_USD_per_oz"] = out["Gold_USD_per_oz"].round(3)
    out["Gold_Nominal_Return"] = out["Gold_Nominal_Return"].round(8)
    out["xrusd"] = out["xrusd"].map(lambda v: f"{v:.10g}" if pd.notna(v) else "")

    out.to_csv(OUT_CSV, index=False)
    n_nan = int(out["Gold_Nominal_Return"].isna().sum())
    print(f"\nWrote {OUT_CSV}: {len(out)} rows, {n_nan} NaN returns.")
    if nan_report:
        print("NaN return years (missing/zero gold price or xrusd):")
        for iso, yrs in sorted(nan_report.items()):
            print(f"  {iso}: {yrs}")


if __name__ == "__main__":
    main()
