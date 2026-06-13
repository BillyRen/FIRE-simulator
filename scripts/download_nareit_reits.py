#!/usr/bin/env python3
"""Download & process the FTSE Nareit U.S. Real Estate Index Series.

WHY THIS SERIES
---------------
The repo already carries JST `Housing_TR` for the USA -- the total return to
*physical residential real estate* (rent yield + house-price appreciation).
A natural question is whether publicly-traded **equity REITs** (commercial real
estate, levered, traded like stocks) are a better/different "real estate" asset.
To answer it we need a long, clean REIT total-return series. The canonical free
source is Nareit's own monthly history of the FTSE Nareit U.S. Real Estate Index
Series, total-return back to December 1971 (base = 100), i.e. full years 1972+.

  Source file: reit.com/sites/default/files/returns/MonthlyHistoricalReturns.xls
  reit.com is behind a bot challenge (curl gets an HTML interstitial), so we
  pull the identical file from the Wayback Machine raw snapshot instead. Pass
  --xls <path> to parse a manually-downloaded copy.

INDEX VARIANTS WE KEEP (monthly TOTAL return, incl. dividends)
  all_reits        All REITs (equity + mortgage)            xls col 1
  all_equity_reits All Equity REITs (incl. timber/infra)    xls col 22  <- headline
  equity_reits     Equity REITs (classic property sectors)  xls col 29
  mortgage_reits   Mortgage REITs                            xls col 36
  + all_equity_reits dividend yield (month-end, %)           xls col 27

OUTPUTS (data/reits/)
  raw/nareit_monthly_historical.xls   unmodified Nareit workbook (gitignored)
  nareit_monthly_total_return.csv     Year,Month + decimal monthly TR per variant
  nareit_annual_total_return.csv      Jan-Dec compounded annual TR, DECIMAL,
                                      full calendar years only (drops partial tail)

CONVENTIONS (mirror data/factors/ + FIRE_dataset)
  * Returns are NOMINAL TOTAL returns (incl. dividends), USD, gross of fees.
  * Nareit stores percent; we divide by 100 -> decimal.
  * Annual = product(1+monthly) - 1 over the 12 calendar months; a year is
    emitted only if all 12 months are present (partial current year dropped).

Requires: xlrd (`pip install xlrd`) — data-prep only, not a backend runtime dep.
Run:  python3 scripts/download_nareit_reits.py [--skip-download] [--xls PATH]
"""
import argparse
import csv
import os
import urllib.request
from collections import defaultdict

import xlrd
from xlrd.xldate import xldate_as_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA = os.path.join(REPO, "data", "reits")
RAW_DIR = os.path.join(DATA, "raw")
RAW_XLS = os.path.join(RAW_DIR, "nareit_monthly_historical.xls")

# Wayback raw snapshot of the live reit.com workbook (live URL is bot-walled).
WAYBACK_URL = (
    "http://web.archive.org/web/20250519075754id_/"
    "https://www.reit.com/sites/default/files/returns/MonthlyHistoricalReturns.xls"
)

# Total-return column index in the "Index Data" sheet -> our label.
TR_COLS = {
    1: "all_reits",
    22: "all_equity_reits",
    29: "equity_reits",
    36: "mortgage_reits",
}
DIV_YIELD_COL = 27  # All Equity REITs dividend yield (month-end %)
HEADER_ROWS = 9     # rows 0..8 are titles/labels; row 9 = Dec-1971 base (no return)


def download(dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"downloading {WAYBACK_URL}")
    req = urllib.request.Request(WAYBACK_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
    if blob[:4] != b"\xd0\xcf\x11\xe0":  # OLE2 magic for .xls
        raise SystemExit("downloaded file is not an .xls (got HTML/bot wall?)")
    with open(dest, "wb") as f:
        f.write(blob)
    print(f"  -> {dest} ({len(blob):,} bytes)")


def parse(xls_path: str):
    """Return (monthly_rows, div_yield_by_ym). monthly_rows: list of dicts with
    keys Year, Month, <variants...>; values decimal returns (or '' if missing)."""
    wb = xlrd.open_workbook(xls_path)
    sh = wb.sheet_by_name("Index Data")
    dm = wb.datemode

    monthly = []
    div_yield = {}
    for r in range(HEADER_ROWS, sh.nrows):
        dval = sh.cell_value(r, 0)
        if not isinstance(dval, float) or dval == "":
            continue
        try:
            d = xldate_as_datetime(dval, dm)
        except Exception:
            continue
        row = {"Year": d.year, "Month": d.month}
        has_any = False
        for col, label in TR_COLS.items():
            v = sh.cell_value(r, col)
            if isinstance(v, float) and v != "":
                row[label] = v / 100.0  # percent -> decimal
                has_any = True
            else:
                row[label] = ""
        if not has_any:
            continue  # base row (Dec 1971) carries no return
        monthly.append(row)
        dv = sh.cell_value(r, DIV_YIELD_COL)
        if isinstance(dv, float) and dv != "":
            div_yield[(d.year, d.month)] = dv / 100.0
    return monthly, div_yield


def to_annual(monthly):
    """Compound Jan-Dec; emit a year only when all 12 months are present and
    non-missing for that variant."""
    by_year = defaultdict(dict)  # year -> {label: [returns...]}
    for row in monthly:
        y = row["Year"]
        for label in TR_COLS.values():
            v = row[label]
            if v != "":
                by_year[y].setdefault(label, []).append(v)
    annual = []
    for y in sorted(by_year):
        rec = {"Year": y}
        full = True
        for label in TR_COLS.values():
            rets = by_year[y].get(label, [])
            if len(rets) == 12:
                cum = 1.0
                for x in rets:
                    cum *= (1.0 + x)
                rec[label] = round(cum - 1.0, 8)
            else:
                rec[label] = ""
                if label == "all_equity_reits" and len(rets) != 12:
                    full = False
        if not full:
            print(f"  skip partial year {y} "
                  f"(all_equity_reits months={len(by_year[y].get('all_equity_reits', []))})")
            continue
        annual.append(rec)
    return annual


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in cols})
    print(f"  wrote {path} ({len(rows)} rows)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-download", action="store_true",
                    help="parse existing raw xls instead of re-downloading")
    ap.add_argument("--xls", default=RAW_XLS, help="path to Nareit .xls workbook")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    if not args.skip_download and args.xls == RAW_XLS:
        download(RAW_XLS)
    if not os.path.exists(args.xls):
        raise SystemExit(f"missing {args.xls}; run without --skip-download")

    monthly, div_yield = parse(args.xls)
    print(f"parsed {len(monthly)} monthly rows "
          f"({monthly[0]['Year']}-{monthly[0]['Month']:02d} .. "
          f"{monthly[-1]['Year']}-{monthly[-1]['Month']:02d})")

    variant_cols = list(TR_COLS.values())
    # attach All Equity REITs dividend yield to monthly output
    for row in monthly:
        row["all_equity_div_yield"] = div_yield.get((row["Year"], row["Month"]), "")
    write_csv(
        os.path.join(DATA, "nareit_monthly_total_return.csv"),
        monthly, ["Year", "Month"] + variant_cols + ["all_equity_div_yield"],
    )

    annual = to_annual(monthly)
    print(f"annual full years: {annual[0]['Year']}..{annual[-1]['Year']} "
          f"({len(annual)} years)")
    write_csv(
        os.path.join(DATA, "nareit_annual_total_return.csv"),
        annual, ["Year"] + variant_cols,
    )


if __name__ == "__main__":
    main()
