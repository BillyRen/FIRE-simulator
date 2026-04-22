#!/usr/bin/env python3
"""Parse Horizon Actuarial Survey of Capital Market Assumptions into CSVs.

Extracts Exhibit 17 ("Average Survey Assumptions") — the canonical summary
table containing, for each asset class:
  - 10-year and 20-year expected returns (arithmetic + geometric)
  - Standard deviation
  - Lower-triangular correlation matrix (asset classes only; Inflation excluded)

Produces two CSV files under data/cme/:
  - horizon_<year>_assets.csv   : per-asset returns + volatility (decimals, not %)
  - horizon_<year>_corr.csv     : 17x17 full symmetric correlation matrix

Runs built-in sanity checks: shape, diagonal, symmetry, PSD, bounds.

Usage:
  python scripts/import_horizon_cma.py                     # parse latest in data/cme_raw/
  python scripts/import_horizon_cma.py --pdf PATH          # explicit PDF path
  python scripts/import_horizon_cma.py --year 2025         # select edition by filename
  python scripts/import_horizon_cma.py --out-dir DIR       # override output directory

Requires poppler (`brew install poppler`) for the `pdftotext` binary.

Source: Horizon Actuarial Services, LLC — Survey of Capital Market Assumptions.
License: © Horizon Actuarial Services, LLC. Attribution required when citing.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT / "data" / "cme_raw"
DEFAULT_OUT_DIR = ROOT / "data" / "cme"

# Parses a leading row index ("1".."17") or the literal "Inflation" tag.
ROW_HEAD_RE = re.compile(r"^\s*(\d+|Inflation)\s+(.+)$")
# Percentage values in the row body (5 of them: arith10, geom10, arith20, geom20, std).
PCT_RE = re.compile(r"(\d+\.\d+)%")
# Correlation tokens: "1.00", "0.89", "(0.01)" for negative, "0.00" or "-0.01".
CORR_TOKEN_RE = re.compile(r"\(\d+\.\d+\)|-?\d+\.\d+")


def run_pdftotext(pdf_path: Path) -> str:
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            "pdftotext not found. Install poppler: `brew install poppler` (macOS) "
            "or `apt-get install poppler-utils` (Debian/Ubuntu)."
        ) from exc
    return out.stdout


def find_exhibit_17_block(text: str) -> list[str]:
    """Return the lines between 'Exhibit 17' and the next exhibit or page footer."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"\s*Exhibit 17\b", line):
            start = i
            break
    if start is None:
        raise ValueError("Exhibit 17 marker not found in PDF text.")

    # Block ends at the next "Exhibit NN" or page-break header "Survey of Capital Market..."
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"\s*Exhibit \d+\b", lines[j]):
            end = j
            break
    return lines[start:end]


def parse_corr_token(tok: str) -> float:
    if tok.startswith("(") and tok.endswith(")"):
        return -float(tok[1:-1])
    return float(tok)


def parse_row(line: str) -> tuple[str, str, list[float], list[float]] | None:
    """Parse one data row. Returns (index_str, asset_name, [5 pcts], [corrs]) or None."""
    m = ROW_HEAD_RE.match(line)
    if not m:
        return None
    idx_str = m.group(1)
    rest = m.group(2)

    pct_matches = list(PCT_RE.finditer(rest))
    if len(pct_matches) < 5:
        return None
    pcts = [float(p.group(1)) for p in pct_matches[:5]]

    # Asset name: everything before the first % value, right-stripped.
    # For the Inflation row the leading token *is* the name and nothing precedes the first %.
    if idx_str == "Inflation":
        asset_name = "Inflation"
    else:
        asset_name = rest[: pct_matches[0].start()].rstrip()
    # Correlations: tokens after the 5th %.
    corr_text = rest[pct_matches[4].end():]
    corrs = [parse_corr_token(t) for t in CORR_TOKEN_RE.findall(corr_text)]

    return idx_str, asset_name, pcts, corrs


def parse_exhibit_17(block: list[str]) -> tuple[list[dict], np.ndarray]:
    """Parse Exhibit 17 block. Returns (assets list, 17x17 correlation matrix)."""
    assets: list[dict] = []
    corr_rows: list[list[float]] = []
    inflation_row: dict | None = None

    for line in block:
        parsed = parse_row(line)
        if parsed is None:
            continue
        idx_str, name, pcts, corrs = parsed
        arith10, geom10, arith20, geom20, std = (p / 100.0 for p in pcts)
        row = {
            "index": idx_str,
            "asset": name,
            "arith_10yr": arith10,
            "geom_10yr": geom10,
            "arith_20yr": arith20,
            "geom_20yr": geom20,
            "std_dev": std,
        }
        if idx_str == "Inflation":
            inflation_row = row
        else:
            assets.append(row)
            corr_rows.append(corrs)

    if len(assets) != 17:
        raise ValueError(
            f"Expected 17 asset rows in Exhibit 17, got {len(assets)}. "
            "PDF layout may have changed."
        )
    if inflation_row is None:
        raise ValueError("Inflation row not found in Exhibit 17.")

    # Build 17x17 symmetric matrix from lower-triangular data.
    n = len(assets)
    corr = np.full((n, n), np.nan)
    for i, row in enumerate(corr_rows):
        if len(row) != i + 1:
            raise ValueError(
                f"Row {i + 1} ({assets[i]['asset']!r}) has {len(row)} correlation "
                f"values, expected {i + 1}."
            )
        for j, v in enumerate(row):
            corr[i, j] = v
            corr[j, i] = v

    # Append inflation last with a fixed numeric index so downstream code can consume it.
    inflation_row["index"] = str(n + 1)
    assets.append(inflation_row)

    return assets, corr


def write_assets_csv(path: Path, assets: list[dict]) -> None:
    fieldnames = [
        "index",
        "asset",
        "arith_10yr",
        "geom_10yr",
        "arith_20yr",
        "geom_20yr",
        "std_dev",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in assets:
            w.writerow(
                {
                    "index": row["index"],
                    "asset": row["asset"],
                    "arith_10yr": f"{row['arith_10yr']:.6f}",
                    "geom_10yr": f"{row['geom_10yr']:.6f}",
                    "arith_20yr": f"{row['arith_20yr']:.6f}",
                    "geom_20yr": f"{row['geom_20yr']:.6f}",
                    "std_dev": f"{row['std_dev']:.6f}",
                }
            )


def write_corr_csv(path: Path, asset_names: list[str], corr: np.ndarray) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([""] + asset_names)
        for i, name in enumerate(asset_names):
            w.writerow([name] + [f"{corr[i, j]:.4f}" for j in range(len(asset_names))])


def validate(assets: list[dict], corr: np.ndarray) -> list[str]:
    """Run sanity checks. Returns list of error messages (empty = all pass)."""
    errors: list[str] = []
    n = corr.shape[0]

    # 1. Correlation diagonal = 1.0
    diag = np.diag(corr)
    if not np.allclose(diag, 1.0, atol=1e-6):
        errors.append(f"Correlation diagonal not all 1.0: {diag}")

    # 2. Symmetry
    if not np.allclose(corr, corr.T, atol=1e-8):
        errors.append("Correlation matrix is not symmetric.")

    # 3. Values in [-1, 1]
    if (corr < -1.0 - 1e-6).any() or (corr > 1.0 + 1e-6).any():
        errors.append(f"Correlation values out of [-1, 1]: min={corr.min()}, max={corr.max()}")

    # 4. Positive semi-definite
    eigvals = np.linalg.eigvalsh(corr)
    min_eig = float(eigvals.min())
    if min_eig < -1e-6:
        errors.append(
            f"Correlation matrix is not PSD (min eigenvalue {min_eig:.2e}). "
            "Needs regularization (nearest PSD) before use in multivariate sampling."
        )

    # 5. Arithmetic >= Geometric for each horizon (by Jensen's inequality given std>0)
    for row in assets:
        if row["arith_10yr"] < row["geom_10yr"] - 1e-9:
            errors.append(f"{row['asset']}: arith_10yr < geom_10yr")
        if row["arith_20yr"] < row["geom_20yr"] - 1e-9:
            errors.append(f"{row['asset']}: arith_20yr < geom_20yr")

    # 6. Returns and std in plausible bounds
    for row in assets:
        for k in ("arith_10yr", "geom_10yr", "arith_20yr", "geom_20yr"):
            v = row[k]
            if not (-0.05 < v < 0.20):
                errors.append(f"{row['asset']}: {k}={v:.4f} out of plausible range")
        s = row["std_dev"]
        if not (0.0 < s < 0.50):
            errors.append(f"{row['asset']}: std_dev={s:.4f} out of plausible range")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pdf", type=Path, help="Path to Horizon CMA survey PDF.")
    parser.add_argument("--year", type=int, help="Edition year (for filename resolution).")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for CSVs.")
    args = parser.parse_args()

    pdf_path: Path | None = args.pdf
    if pdf_path is None:
        candidates = sorted(DEFAULT_RAW_DIR.glob("horizon_cma_*.pdf"))
        if args.year:
            candidates = [p for p in candidates if str(args.year) in p.name]
        if not candidates:
            print(f"No PDFs found in {DEFAULT_RAW_DIR}", file=sys.stderr)
            return 1
        pdf_path = candidates[-1]

    year_match = re.search(r"(\d{4})", pdf_path.name)
    if not year_match:
        print(f"Cannot infer year from filename: {pdf_path.name}", file=sys.stderr)
        return 1
    year = int(year_match.group(1))

    print(f"Parsing {pdf_path.name}...")
    text = run_pdftotext(pdf_path)
    block = find_exhibit_17_block(text)
    assets, corr = parse_exhibit_17(block)
    asset_names = [a["asset"] for a in assets if a["asset"] != "Inflation"]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    assets_csv = args.out_dir / f"horizon_{year}_assets.csv"
    corr_csv = args.out_dir / f"horizon_{year}_corr.csv"
    write_assets_csv(assets_csv, assets)
    write_corr_csv(corr_csv, asset_names, corr)
    print(f"  -> {assets_csv.relative_to(ROOT)} ({len(assets)} rows)")
    print(f"  -> {corr_csv.relative_to(ROOT)} ({corr.shape[0]}x{corr.shape[1]})")

    print("\nValidation:")
    errors = validate(assets, corr)
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        return 1
    eigvals = np.linalg.eigvalsh(corr)
    print(f"  OK   shape: {len(assets)} assets (inc. Inflation), corr {corr.shape[0]}x{corr.shape[1]}")
    print(f"  OK   diagonal=1.0, symmetric, values in [-1, 1]")
    print(f"  OK   PSD (eigenvalues min={eigvals.min():.4f}, max={eigvals.max():.4f})")
    print(f"  OK   arith >= geom for all assets/horizons")
    print(f"  OK   returns and volatilities in plausible bounds")
    print("\nSpot checks (10-year geometric):")
    for target in ("US Equity - Large Cap", "US Treasuries (Cash Equivalents)", "Inflation"):
        row = next((a for a in assets if a["asset"] == target), None)
        if row:
            print(f"  {target:40s}  {row['geom_10yr'] * 100:5.2f}%   σ={row['std_dev'] * 100:5.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
