"""Import the FTSE Nareit U.S. Real Estate Index Series into data/reit_returns.csv.

Nareit (National Association of Real Estate Investment Trusts) publishes the
longest free, authoritative U.S. listed-REIT total-return series. Monthly index
values begin in **December 1971** (base = 100), so calendar-year total returns
start in **1972** — the same vintage as the JST housing series is most useful for
comparison.

Source (official):
  https://www.reit.com/data-research/reit-indexes/monthly-index-values-returns
  -> "Monthly Index Values & Returns" => MonthlyHistoricalReturns.xls

The live download sits behind a JavaScript bot-challenge (Fastly), so the raw
.xls is fetched once into data/raw/ (here, via the Internet Archive mirror) and
parsed offline. Re-run with a fresh copy of the .xls dropped in data/raw/.

Methodology (mirrors repo convention: nominal total return, decimal):
  - Calendar-year total return  = TR_index[Dec_t] / TR_index[Dec_{t-1}] - 1
  - Calendar-year price return  = Price_index[Dec_t] / Price_index[Dec_{t-1}] - 1
    (== capital appreciation, the analog of JST Housing_CapGain)
  - Calendar-year income return = prod_{m in year}(1 + income_return_m) - 1
    (the dividend/rent component of total return)
  - Year-end dividend yield     = reported yield at Dec_t (analog of JST rent yield)
  - 1971 (base) and any partial trailing year are dropped (need a full Jan-Dec).

Series extracted (all nominal, decimal):
  All REITs, All Equity REITs, Equity REITs, Mortgage REITs.
  "All Equity REITs" is the headline real-estate-owning benchmark and the most
  apt comparison to direct housing.

Usage:
  python scripts/import_nareit_reits.py                 # default raw path
  python scripts/import_nareit_reits.py path/to/file.xls

Output: data/reit_returns.csv
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import warnings

import pandas as pd

warnings.simplefilter("ignore")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_PATH = os.path.join(_BASE_DIR, "data", "raw", "MonthlyHistoricalReturns.xls")
OUT_PATH = os.path.join(_BASE_DIR, "data", "reit_returns.csv")

# group header (row 5) label -> output column prefix
GROUPS = {
    "All REITs": "AllREITs",
    "All Equity REITs": "AllEquityREITs",
    "Equity REITs": "EquityREITs",
    "Mortgage REITs": "MortgageREITs",
}

# fixed sub-column offsets from each group's start column (verified against file):
#   +0 Total Return, +1 Total Index, +2 Price Return, +3 Price Index,
#   +4 Income Return, +5 Dividend Yield
OFF_TR, OFF_TRIDX, OFF_PRICE, OFF_PRICEIDX, OFF_INCOME, OFF_YIELD = range(6)


def _locate(raw: pd.DataFrame) -> tuple[int, int, dict[str, int]]:
    """Return (group_header_row, first_data_row, {group_label: start_col})."""
    date_row = None
    for r in range(min(20, len(raw))):
        if str(raw.iloc[r, 0]).strip().lower() == "date":
            date_row = r
            break
    if date_row is None:
        raise SystemExit("error: could not find the 'Date' header row")

    group_row = date_row - 2  # group labels sit two rows above the Date/Return row
    group_cols: dict[str, int] = {}
    for c in range(raw.shape[1]):
        v = raw.iloc[group_row, c]
        if pd.notna(v) and str(v).strip() in GROUPS:
            group_cols[str(v).strip()] = c

    missing = set(GROUPS) - set(group_cols)
    if missing:
        raise SystemExit(f"error: missing expected groups in file: {missing}")

    first_data_row = date_row + 1
    while first_data_row < len(raw) and not isinstance(
        raw.iloc[first_data_row, 0], _dt.datetime
    ):
        first_data_row += 1
    return group_row, first_data_row, group_cols


def build(raw_path: str) -> pd.DataFrame:
    raw = pd.read_excel(raw_path, sheet_name="Index Data", header=None, engine="xlrd")
    _, first_data_row, group_cols = _locate(raw)

    body = raw.iloc[first_data_row:].copy()
    body = body[body.iloc[:, 0].apply(lambda x: isinstance(x, _dt.datetime))]
    dates = pd.to_datetime(body.iloc[:, 0])

    cols: dict[str, pd.Series] = {}
    for label, prefix in GROUPS.items():
        g = group_cols[label]
        cols[f"{prefix}_TRIndex"] = pd.to_numeric(body.iloc[:, g + OFF_TRIDX], errors="coerce")
        cols[f"{prefix}_PriceIndex"] = pd.to_numeric(body.iloc[:, g + OFF_PRICEIDX], errors="coerce")
        cols[f"{prefix}_IncomeRet_m"] = pd.to_numeric(body.iloc[:, g + OFF_INCOME], errors="coerce") / 100.0
        cols[f"{prefix}_DivYield"] = pd.to_numeric(body.iloc[:, g + OFF_YIELD], errors="coerce") / 100.0

    monthly = pd.DataFrame(cols)
    monthly["Year"] = dates.dt.year.values
    monthly["Month"] = dates.dt.month.values

    # December-anchored index level per calendar year (base year 1971 included)
    dec = monthly[monthly["Month"] == 12].set_index("Year")

    out: dict[str, pd.Series] = {}
    for prefix in GROUPS.values():
        tr = dec[f"{prefix}_TRIndex"]
        pr = dec[f"{prefix}_PriceIndex"]
        out[f"{prefix}_TR"] = tr / tr.shift(1) - 1.0
        out[f"{prefix}_PriceReturn"] = pr / pr.shift(1) - 1.0
        # annual income component: compound the 12 monthly income returns
        inc = (
            monthly.groupby("Year")[f"{prefix}_IncomeRet_m"]
            .apply(lambda s: (1.0 + s).prod() - 1.0)
        )
        out[f"{prefix}_IncomeReturn"] = inc
        # year-end (December) dividend yield
        out[f"{prefix}_DivYield"] = dec[f"{prefix}_DivYield"]

    df = pd.DataFrame(out)
    df.index.name = "Year"
    df = df.reset_index().sort_values("Year")

    # drop the base year (1971, all NaN returns) and any partial trailing year:
    # a complete calendar year must have all 12 monthly observations.
    full_years = monthly.groupby("Year")["Month"].nunique()
    complete = set(full_years[full_years == 12].index)
    df = df[df["Year"].isin(complete) & df[f"AllEquityREITs_TR"].notna()].reset_index(drop=True)
    return df


def main() -> None:
    raw_path = sys.argv[1] if len(sys.argv) > 1 else RAW_PATH
    if not os.path.exists(raw_path):
        raise SystemExit(
            f"error: raw file not found: {raw_path}\n"
            "Download MonthlyHistoricalReturns.xls from reit.com (Monthly Index "
            "Values & Returns) into data/raw/ and retry."
        )
    df = build(raw_path)

    pct_cols = [c for c in df.columns if c != "Year"]
    df[pct_cols] = df[pct_cols].round(6)
    df.to_csv(OUT_PATH, index=False)

    print(f"wrote {len(df)} rows -> {OUT_PATH}")
    print(f"  year range: {df['Year'].iloc[0]}-{df['Year'].iloc[-1]}")
    a = df.set_index("Year")["AllEquityREITs_TR"]
    cagr = (1.0 + a).prod() ** (1.0 / len(a)) - 1.0
    print(f"  All Equity REITs nominal CAGR ({df['Year'].iloc[0]}-{df['Year'].iloc[-1]}): {cagr:.4%}")
    print(f"  All Equity REITs annual vol: {a.std():.4%}")
    print(df.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
