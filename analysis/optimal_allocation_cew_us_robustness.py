"""Robustness checks for the US-dataset CEW study (Codex review items).

1. Bridge run: JST data restricted to USA (single-country bootstrap,
   start=1900) — separates "pooling -> single country" from
   "JST -> Shiller/MSCI data" when comparing against the JST pooled study.
2. Block-length sensitivity: finalists re-run with (3,7) and (10,20)
   blocks on the primary fire_dataset_intl 1900 window.

Output: analysis/output/optimal_allocation/cew_us_robustness.csv (+ stdout)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import load_returns_data, load_returns_by_source
from simulator.sweep import pregenerate_raw_scenarios

from optimal_allocation_cew import (
    NUM_SIMS, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK, SEED, EXPENSE,
)
from optimal_allocation_cew_us_multiseed import eval_alloc

START_YEAR = 1900
FINALISTS = [
    (0.80, 0.20, 0.00),
    (0.70, 0.30, 0.00),
    (0.90, 0.10, 0.00),
    (0.70, 0.20, 0.10),
]
BLOCK_VARIANTS = [(3, 7), (5, 15), (10, 20)]

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"


def bootstrap_for(returns_df: pd.DataFrame, min_block: int, max_block: int,
                  seed: int) -> dict:
    return pregenerate_raw_scenarios(
        expense_ratios=EXPENSE,
        retirement_years=RETIREMENT_YEARS,
        min_block=min_block, max_block=max_block,
        num_simulations=NUM_SIMS,
        returns_df=returns_df,
        seed=seed,
        country_dfs=None, country_weights=None,
    )


def main() -> None:
    t0 = time.time()
    rows: list[dict] = []

    # 1. JST-USA bridge (same grid finalists + the JST-pool winner 30/70/00)
    jst = load_returns_data()
    jst_usa = jst[(jst["Country"] == "USA")
                  & (jst["Year"] >= START_YEAR)].reset_index(drop=True)
    print(f"[bridge] JST-USA single-country, n={len(jst_usa)}y, "
          f"start={START_YEAR}, N={NUM_SIMS}, seed={SEED}")
    raw = bootstrap_for(jst_usa, MIN_BLOCK, MAX_BLOCK, SEED)
    for w_ds, w_gs, w_db in FINALISTS + [(0.30, 0.70, 0.00)]:
        r = eval_alloc(raw, w_ds, w_gs, w_db, SEED)
        r.update(variant="jst_usa", min_block=MIN_BLOCK, max_block=MAX_BLOCK)
        rows.append(r)

    # 2. Block-length sensitivity on fire_dataset_intl 1900
    fire = load_returns_by_source("fire_dataset_intl")
    fire = fire[fire["Year"] >= START_YEAR].reset_index(drop=True)
    for min_b, max_b in BLOCK_VARIANTS:
        print(f"[blocklen] fire_dataset_intl, blocks {min_b}-{max_b}  "
              f"({time.time()-t0:.0f}s)")
        raw = bootstrap_for(fire, min_b, max_b, SEED)
        for w_ds, w_gs, w_db in FINALISTS:
            r = eval_alloc(raw, w_ds, w_gs, w_db, SEED)
            r.update(variant="fire_intl", min_block=min_b, max_block=max_b)
            rows.append(r)

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "cew_us_robustness.csv", index=False)
    fmt = {
        "median_cew": "{:,.0f}".format, "p10_cew": "{:,.0f}".format,
        "p10_min_wd": "{:,.0f}".format, "init_swr": "{:.3%}".format,
        "success_rate": "{:.4f}".format, "severe_fail_prob": "{:.4f}".format,
    }
    print("\n== JST-USA bridge (start=1900, target=0.85) ==")
    print(df[df["variant"] == "jst_usa"]
          .sort_values("median_cew", ascending=False)
          .to_string(index=False, formatters=fmt))
    print("\n== Block-length sensitivity (fire_dataset_intl, 1900) ==")
    print(df[df["variant"] == "fire_intl"]
          .sort_values(["min_block", "median_cew"], ascending=[True, False])
          .to_string(index=False, formatters=fmt))
    print(f"\nTotal {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
