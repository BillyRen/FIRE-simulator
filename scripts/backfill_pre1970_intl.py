#!/usr/bin/env python3
"""Generate data/FIRE_dataset_intl.csv: FIRE_dataset with a real pre-1970
non-US equity series instead of the US-placeholder.

Background
----------
`data/FIRE_dataset.csv` carries a real MSCI international-equity series
(`International Stock`, USD nominal, US-investor view, MSCI EAFE) only from 1970
onward. Before 1970 the column is a placeholder equal to `US Stock`, which forces
US/non-US correlation to 1.0 and destroys the diversification structure that
pre-1970 history actually contained.

Method (see docs/plan-pre1970-intl-backfill.md)
-----------------------------------------------
1. Shape basis: the engine's own `Global_Stock` series for the `USA` row of
   `data/jst_returns.csv` (linear time-varying GDP-weighted ex-US equity, USD
   nominal). It already covers 1872-1969 with no gaps and tracks MSCI at
   corr ~0.92 over the overlap.
2. NO level haircut by default (k=0): intl_backfill[t] = Global_Stock_USA[t].
   We originally applied a multiplicative "investability wedge" (~1.69pp/yr,
   estimated on the 1970-2025 JST-vs-MSCI-EAFE overlap), but a per-country
   check (2026-06) found JST single-country USD returns match the MSCI country
   indices within ~0.3pp (1988-2025). The aggregate JST-USA-Global vs MSCI EAFE
   gap is therefore a GDP-weighting/composition artifact, not per-country data
   inflation, so we no longer haircut the series. Pass --wedge to re-enable one.
3. 1970+ International is left untouched (it is the real MSCI series).

This is a CALIBRATED ESTIMATE, not a real index. It is shipped as a SEPARATE
data source (`fire_dataset_intl`), never overwriting the canonical file, so the
provenance stays auditable and the placeholder vs backfill effect is A/B-able.

Usage
-----
    python scripts/backfill_pre1970_intl.py [--wedge PP]

`--wedge` overrides the auto-estimated haircut (in percentage points, e.g.
`--wedge 1.9` for the conservative 1970s+1980s-average bound). Default: the
1970-2025 measured value (~1.69pp).
"""
from __future__ import annotations

import argparse
import os
import tempfile

import numpy as np
import pandas as pd

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIRE_CSV = os.path.join(_BASE_DIR, "data", "FIRE_dataset.csv")
JST_CSV = os.path.join(_BASE_DIR, "data", "jst_returns.csv")
OUT_CSV = os.path.join(_BASE_DIR, "data", "FIRE_dataset_intl.csv")

OVERLAP_LO, OVERLAP_HI = 1970, 2025  # years where both MSCI and JST exist
INTL_COL = "International Stock"


def geomean_gross(returns: pd.Series) -> float:
    """Geometric mean gross return (1 + CAGR) of a return series."""
    r = np.asarray(returns, dtype=float)
    return float(np.prod(1.0 + r) ** (1.0 / len(r)))


def estimate_wedge(fire: pd.DataFrame, jst_us: pd.DataFrame) -> float:
    """Multiplicative level wedge k on the 1970-2025 overlap."""
    m = fire.merge(jst_us, on="Year")
    ov = m[(m.Year >= OVERLAP_LO) & (m.Year <= OVERLAP_HI)]
    g_global = geomean_gross(ov["Global_Stock"])
    g_msci = geomean_gross(ov[INTL_COL])
    return g_global / g_msci - 1.0


def atomic_write_csv(df: pd.DataFrame, path: str) -> None:
    """Write CSV atomically (temp file in same dir + os.replace)."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            df.to_csv(f, index=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def build(wedge_override: float | None = None) -> None:
    # Always recompute from canonical sources — never read OUT_CSV (idempotent).
    fire = pd.read_csv(FIRE_CSV)
    jst = pd.read_csv(JST_CSV)
    jst_us = jst[jst["Country"] == "USA"][["Year", "Global_Stock"]].copy()

    if INTL_COL not in fire.columns:
        raise ValueError(f"{FIRE_CSV} missing column {INTL_COL!r}")

    # No investability haircut by default. Per-country JST equity returns were
    # verified comparable to the MSCI country indices (1988-2025, USD, within
    # ~0.3pp), so the pre-1970 backfill uses the JST Global_Stock series directly.
    # The ~1.7pp JST-USA-Global vs MSCI EAFE gap is a GDP-weighting/composition
    # artifact (GDP-weighted 15-country basket vs cap-weighted EAFE), NOT a
    # per-country data-quality issue, so haircutting the series is unwarranted.
    # estimate_wedge() is retained for reference; pass --wedge to re-enable one.
    k = wedge_override if wedge_override is not None else 0.0

    # Map year -> Global_Stock (USA, linear-GDP ex-US, USD nominal).
    gs = dict(zip(jst_us["Year"].astype(int), jst_us["Global_Stock"]))

    out = fire.copy()
    orig = out[INTL_COL].to_numpy(dtype=float).copy()
    new = orig.copy()
    n_changed = 0
    skipped_years = []
    for i, yr in enumerate(out["Year"].astype(int)):
        if yr >= OVERLAP_LO:
            continue  # real MSCI — leave untouched
        g = gs.get(yr)
        if g is None or pd.isna(g):
            skipped_years.append(yr)  # no JST Global_Stock (e.g. 1871) — keep placeholder
            continue
        new[i] = (1.0 + g) / (1.0 + k) - 1.0
        n_changed += 1
    out[INTL_COL] = new

    atomic_write_csv(out, OUT_CSV)

    # ---- summary ----
    pre = out["Year"] < OVERLAP_LO
    yrs = out.loc[pre, "Year"]
    print(f"wedge k = {k*100:.3f} pp/yr "
          f"({'override' if wedge_override is not None else 'auto, 1970-2025 overlap'})")
    print(f"rows changed (pre-{OVERLAP_LO}): {n_changed}")
    if skipped_years:
        print(f"skipped (no JST Global_Stock, kept placeholder): {skipped_years}")
    print(f"wrote {OUT_CSV}")

    def cagr(mask):
        r = new[mask.to_numpy()]
        return np.prod(1.0 + r) ** (1.0 / len(r)) - 1.0 if len(r) else float("nan")

    us = fire["US Stock"].to_numpy(dtype=float)
    for lo in range(1870, 1970, 10):
        m = (out["Year"] >= lo) & (out["Year"] <= lo + 9)
        if not m.any():
            continue
        ig = np.prod(1.0 + new[m.to_numpy()]) ** (1.0 / m.sum()) - 1.0
        ug = np.prod(1.0 + us[m.to_numpy()]) ** (1.0 / m.sum()) - 1.0
        print(f"  {lo}s: intl_backfill CAGR={ig*100:6.2f}%  US={ug*100:6.2f}%")

    # correlation check on the changed pre-1970 span
    cm = pre & ~np.isclose(new, orig)
    if cm.sum() > 2:
        c = np.corrcoef(new[cm.to_numpy()], us[cm.to_numpy()])[0, 1]
        print(f"  corr(backfilled intl, US) pre-{OVERLAP_LO}: {c:.3f} "
              f"(placeholder was 1.000)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wedge", type=float, default=None,
                    help="override wedge in pp/yr (e.g. 1.9); default = auto 1970-2025")
    args = ap.parse_args()
    build(wedge_override=None if args.wedge is None else args.wedge / 100.0)


if __name__ == "__main__":
    main()
