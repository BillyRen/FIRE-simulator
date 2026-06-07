"""Import Robert Shiller's CAPE (PE10) series into data/shiller_cape.csv.

The Shiller CAPE (cyclically-adjusted price/earnings, aka PE10) is a US S&P 500
valuation measure used by valuation-aware withdrawal strategies (e.g. the
CAPE-based / Bogleheads variable-percentage method). It is **US-specific**.

Source: tidied CSV of Robert Shiller's monthly data
  https://raw.githubusercontent.com/datasets/s-and-p-500/master/data/data.csv
  (field PE10; 0 for 1871-1880 when <10y of trailing real earnings exist, and
  0 for recent FRED-extension months that lack earnings.)

Methodology:
  - We take the **January** PE10 of each year as that year's start-of-year CAPE,
    matching the simulator's calendar-year return convention (the CAPE known at
    the start of a retirement year sets that year's withdrawal).
  - Only years with a real (>0) January PE10 are written (≈1881-present). Edge
    gaps (pre-1881, latest year before earnings post) are handled at load time
    in data_loader via forward/backward fill — the CSV stays raw.

Usage:
  python scripts/import_shiller_cape.py            # download + write
  python scripts/import_shiller_cape.py local.csv  # use a local Shiller CSV

Output: data/shiller_cape.csv with columns Year, CAPE.
"""
from __future__ import annotations

import csv
import io
import os
import sys
import urllib.request

SOURCE_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500/master/data/data.csv"
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(_BASE_DIR, "data", "shiller_cape.csv")


def _load_source(arg: str | None) -> str:
    if arg:
        with open(arg, encoding="utf-8") as f:
            return f.read()
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


def extract_annual_cape(raw_csv: str) -> list[tuple[int, float]]:
    """Return sorted [(year, january_cape)] for years with a real PE10."""
    reader = csv.DictReader(io.StringIO(raw_csv))
    out: list[tuple[int, float]] = []
    for row in reader:
        date = row["Date"]  # YYYY-MM-DD
        if not date.endswith("-01-01"):
            continue  # January only
        try:
            cape = float(row["PE10"])
        except (KeyError, ValueError):
            continue
        if cape <= 0:
            continue  # 1871-1880 and earnings-less extension rows
        out.append((int(date[:4]), round(cape, 2)))
    out.sort()
    return out


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    raw = _load_source(arg)
    rows = extract_annual_cape(raw)
    if not rows:
        raise SystemExit("error: no valid CAPE rows extracted")

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Year", "CAPE"])
        w.writerows(rows)

    years = [y for y, _ in rows]
    capes = [c for _, c in rows]
    print(f"wrote {len(rows)} rows -> {OUT_PATH}")
    print(f"  year range: {years[0]}-{years[-1]}")
    print(f"  CAPE range: {min(capes):.2f}-{max(capes):.2f}")
    print(f"  first: {rows[0]}  last: {rows[-1]}")


if __name__ == "__main__":
    main()
