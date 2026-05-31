"""Multi-asset long-horizon allocation study v2 (2026-05-31).

Question
--------
Starting from a stocks+bonds portfolio (domestic_stock + global_stock +
domestic_bond — the product's actual three financial assets), how does the
optimal allocation change when we additionally allow:
  (1) domestic real estate (JST Housing_TR)  -> a four-asset portfolio, or
  (2) gold (data/jst_gold.csv, local-currency nominal) -> four-asset, or
  (3) both -> five-asset?

Method — mirrors the product's "optimal allocation" tool
--------------------------------------------------------
- Block Bootstrap over historical JST returns (same engine as the product),
  pooled (sqrt-GDP weighted, matching country="ALL") + representative single
  countries. All asset columns are sampled with shared block indices so
  cross-asset correlation is preserved.
- Portfolio real return uses the product convention (portfolio.py):
      nominal_port = sum_a w_a * (nominal_a - expense_a)
      real_port    = (1 + nominal_port) / (1 + inflation) - 1
  i.e. weight nominal returns net of expense, then deflate ONCE by inflation.
  (This naturally tempers hyperinflation FX spikes in Global_Stock/gold via the
  inflation denominator, so NO winsorization is applied — matching the product.)
- Fixed withdrawal strategy, identical to the product: grow then withdraw a
  constant *real* amount, mark depletion when value <= 0. We import the
  product's own simulation kernel and metric functions so results match the
  tool exactly.
- Each allocation on a 0.1 grid is ranked by FUNDED RATIO (coverage) as the
  primary key — matching the product allocation page, which selects
  best = max(..., key=funded_ratio) — with SUCCESS RATE as the tie-breaker.

Parameters (per user)
---------------------
- initial portfolio   = 1,000,000
- annual withdrawal   = 33,000 real (3.3% initial), constant real
- expense ratio       = 0.5% on every asset
- block 5-15, leverage 1.0, num_sims = 3000
- horizons            = 40 and 65 years (65 = product default; 3.3% is
                        conservative, so only long horizons differentiate
                        allocations on success/funded ratio)

Outputs
-------
  analysis/output/multi_asset_allocation/results.csv     (optimum per menu)
  analysis/output/multi_asset_allocation/asset_stats.csv (real mean/vol/corr)

NOTE: analysis only — not wired into the product. Gold is a prep-only dataset
(see docs/gold-data-preparation.md).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.bootstrap import block_bootstrap_np, block_bootstrap_pooled_np
from simulator.config import get_gdp_weights
from simulator.monte_carlo import _simulate_vectorized_fixed_from_matrix
from simulator.statistics import compute_success_rate, compute_funded_ratio

# ──────────────────────────── parameters ────────────────────────────────────
INITIAL = 1_000_000.0
ANNUAL_WD = 33_000.0          # 3.3% real, constant
EXPENSE = 0.005               # 0.5% on every asset
NUM_SIMS = 3_000
MIN_BLOCK = 5
MAX_BLOCK = 15
SEED = 42
STEP = 0.1
HORIZONS = [40, 65]

SINGLE_COUNTRIES = ["USA", "JPN", "GBR", "DEU", "AUS"]

ASSETS = ["domestic_stock", "global_stock", "domestic_bond", "housing", "gold"]
ASSET_CODE = {"domestic_stock": "DS", "global_stock": "GS",
              "domestic_bond": "DB", "housing": "HO", "gold": "GO"}
NOMINAL_COLS = ["Domestic_Stock", "Global_Stock", "Domestic_Bond",
                "Housing_TR", "Gold_Nominal_Return", "Inflation"]
IDX_INFL = 5
N_ASSETS = len(ASSETS)

MENUS = {
    "base_stocks_bonds": ["domestic_stock", "global_stock", "domestic_bond"],
    "add_housing":       ["domestic_stock", "global_stock", "domestic_bond", "housing"],
    "add_gold":          ["domestic_stock", "global_stock", "domestic_bond", "gold"],
    "add_both":          ASSETS,
}

OUTPUT_DIR = ROOT / "analysis" / "output" / "multi_asset_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────── data prep ─────────────────────────────────────
def load_nominal_arrays() -> dict[str, np.ndarray]:
    """Per-country common-sample nominal arrays, shape (n_years, 6)."""
    ret = pd.read_csv(ROOT / "data" / "jst_returns.csv")
    gold = pd.read_csv(ROOT / "data" / "jst_gold.csv")[
        ["Year", "Country", "Gold_Nominal_Return"]
    ]
    df = ret.merge(gold, on=["Year", "Country"], how="left")
    out: dict[str, np.ndarray] = {}
    for iso, sub in df.groupby("Country"):
        sub = sub.sort_values("Year")
        cc = sub.dropna(subset=NOMINAL_COLS)
        if len(cc) >= 30:
            out[iso] = cc[NOMINAL_COLS].to_numpy(dtype=np.float64)
    return out


# ─────────────────────── bootstrap nominal tensor ───────────────────────────
def bootstrap_tensor(arrays: dict[str, np.ndarray], entity: str,
                     horizon: int, rng: np.random.Generator) -> np.ndarray:
    """Nominal tensor (NUM_SIMS, horizon, 6); ALL -> sqrt-GDP pooled draw."""
    out = np.empty((NUM_SIMS, horizon, len(NOMINAL_COLS)), dtype=np.float64)
    if entity == "ALL":
        clist = list(arrays.keys())
        carr = [arrays[c] for c in clist]
        clens = [len(a) for a in carr]
        gw = get_gdp_weights(clist)
        probs = np.array([gw[c] for c in clist])
        probs = probs / probs.sum()
        for s in range(NUM_SIMS):
            out[s] = block_bootstrap_pooled_np(
                carr, clens, probs, horizon, MIN_BLOCK, MAX_BLOCK, rng)
    else:
        data = arrays[entity]
        n = len(data)
        for s in range(NUM_SIMS):
            out[s] = block_bootstrap_np(data, n, horizon, MIN_BLOCK, MAX_BLOCK, rng)
    return out


def real_returns_for_alloc(tensor: np.ndarray, w: np.ndarray) -> np.ndarray:
    """(NUM_SIMS, horizon) real portfolio returns for weights w (len 5).

    Product convention: weight nominal returns net of per-asset expense, then
    deflate once by inflation.
    """
    nominal_assets = tensor[:, :, :N_ASSETS]               # (S, H, 5)
    nominal_port = nominal_assets @ w - EXPENSE * w.sum()  # (S, H)
    infl = tensor[:, :, IDX_INFL]
    return (1.0 + nominal_port) / (1.0 + infl) - 1.0


# ─────────────────────────── allocation grid ────────────────────────────────
def compositions(k: int, total: int) -> list[tuple[int, ...]]:
    if k == 1:
        return [(total,)]
    res = []
    for first in range(total + 1):
        for rest in compositions(k - 1, total - first):
            res.append((first,) + rest)
    return res


def menu_allocations(allowed: list[str]) -> np.ndarray:
    n_tenths = int(round(1.0 / STEP))
    allowed_idx = [ASSETS.index(a) for a in allowed]
    combos = compositions(len(allowed), n_tenths)
    mat = np.zeros((len(combos), N_ASSETS), dtype=np.float64)
    for r, comp in enumerate(combos):
        for j, idx in enumerate(allowed_idx):
            mat[r, idx] = comp[j] * STEP
    return mat


# ─────────────────────────── evaluation ─────────────────────────────────────
def eval_allocation(tensor: np.ndarray, w: np.ndarray, horizon: int):
    """Return (success_rate, funded_ratio, median_final, p10_final)."""
    real = real_returns_for_alloc(tensor, w)
    traj, _, _, _ = _simulate_vectorized_fixed_from_matrix(
        real, INITIAL, ANNUAL_WD, horizon)
    sr = compute_success_rate(traj, horizon)
    fr = compute_funded_ratio(traj, horizon)
    final = traj[:, -1]
    return sr, fr, float(np.median(final)), float(np.percentile(final, 10))


# ─────────────────────────── descriptive stats ──────────────────────────────
def _weighted_moments(real: np.ndarray, w: np.ndarray):
    # np.errstate guards a known spurious "divide by zero / overflow in matmul"
    # RuntimeWarning from the @ operator under macOS Accelerate BLAS — the
    # inputs are bounded (real is clipped) and the output is verified finite.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        mean = w @ real
        centered = real - mean
        cov = (centered * w[:, None]).T @ centered
    vol = np.sqrt(np.diag(cov))
    denom = np.outer(vol, vol)
    corr = np.divide(cov, denom, out=np.zeros_like(cov), where=denom > 0)
    return mean, vol, corr


def asset_descriptive(arrays: dict[str, np.ndarray], entity: str) -> dict:
    """Per-asset real mean/vol + corr. Real = deflate each asset by inflation.

    NOTE: the descriptive moments are computed on real returns clipped to a
    fixed [-95%, +300%] band, purely so this *display* table is readable —
    single hyperinflation/currency-reform years (where 1+inflation -> 0)
    otherwise make Global_Stock/gold real returns explode (no genuine asset-
    year real return lies outside this band). The main success/funded-ratio
    analysis uses RAW data (product-consistent); the portfolio-level deflation
    there tempers those spikes automatically.
    """
    def to_real(nom):
        infl = nom[:, IDX_INFL:IDX_INFL + 1]
        real = (1.0 + nom[:, :N_ASSETS]) / (1.0 + infl) - 1.0
        return np.clip(real, -0.95, 3.0)

    if entity == "ALL":
        real = np.vstack([to_real(arrays[c]) for c in arrays])
        gw = get_gdp_weights(list(arrays.keys()))
        per_row = np.concatenate([
            np.full(len(arrays[c]), gw[c] / len(arrays[c])) for c in arrays])
        per_row = per_row / per_row.sum()
        mean, vol, corr = _weighted_moments(real, per_row)
    else:
        real = to_real(arrays[entity])
        w = np.full(real.shape[0], 1.0 / real.shape[0])
        mean, vol, corr = _weighted_moments(real, w)
    rec = {"entity": entity, "n_obs": real.shape[0]}
    for j, a in enumerate(ASSETS):
        rec[f"mean_{a}"] = mean[j]
        rec[f"vol_{a}"] = vol[j]
    for i in range(N_ASSETS):
        for j in range(i + 1, N_ASSETS):
            rec[f"corr_{ASSET_CODE[ASSETS[i]]}_{ASSET_CODE[ASSETS[j]]}"] = corr[i, j]
    return rec


# ─────────────────────────── main ───────────────────────────────────────────
def main() -> None:
    arrays = load_nominal_arrays()
    entities = ["ALL"] + [c for c in SINGLE_COUNTRIES if c in arrays]
    print(f"Entities: {entities}")
    print("Common-sample sizes: "
          + ", ".join(f"{c}={len(arrays[c])}" for c in arrays))

    pd.DataFrame([asset_descriptive(arrays, e) for e in entities]).to_csv(
        OUTPUT_DIR / "asset_stats.csv", index=False)
    print(f"Wrote {OUTPUT_DIR / 'asset_stats.csv'}")

    menu_weights = {name: menu_allocations(allowed)
                    for name, allowed in MENUS.items()}

    results = []
    for entity in entities:
        for horizon in HORIZONS:
            rng = np.random.default_rng(SEED)   # identical draws across menus
            tensor = bootstrap_tensor(arrays, entity, horizon, rng)
            for menu, weights in menu_weights.items():
                rows = []
                for w in weights:
                    sr, fr, mfin, p10 = eval_allocation(tensor, w, horizon)
                    rows.append((sr, fr, mfin, p10))
                ev = pd.DataFrame(rows, columns=["success_rate", "funded_ratio",
                                                 "median_final", "p10_final"])
                for j, a in enumerate(ASSETS):
                    ev[a] = weights[:, j]
                # rank: funded_ratio desc (matches the product allocation page,
                # which selects best = max(..., key=funded_ratio)), then
                # success_rate desc as tie-breaker.
                ev = ev.sort_values(["funded_ratio", "success_rate"],
                                    ascending=False).reset_index(drop=True)
                best = ev.iloc[0].copy()
                best["alloc"] = "/".join(
                    f"{int(round(best[a] * 100))}" for a in ASSETS)
                best["entity"] = entity
                best["horizon"] = horizon
                best["menu"] = menu
                results.append(best)
            print(f"  done {entity} H={horizon}")

    res = pd.DataFrame(results)
    col_order = (["entity", "horizon", "menu", "alloc"] + ASSETS
                 + ["success_rate", "funded_ratio", "median_final", "p10_final"])
    res[col_order].to_csv(OUTPUT_DIR / "results.csv", index=False)
    print(f"Wrote {OUTPUT_DIR / 'results.csv'}  ({len(res)} rows)")


if __name__ == "__main__":
    main()
