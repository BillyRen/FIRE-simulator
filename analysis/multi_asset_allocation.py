"""Multi-asset long-horizon allocation study (2026-05-31).

Question
--------
Starting from a stocks+bonds portfolio, how does the *optimal* long-horizon
asset allocation change when we additionally allow:
  (1) domestic real estate (JST Housing_TR), or
  (2) gold (data/jst_gold.csv, local-currency nominal), or
  (3) both?

Asset universe
--------------
Real (inflation-adjusted), four assets:
  domestic_stock, domestic_bond, housing, gold.
Base "stocks+bonds" menu = {domestic_stock, domestic_bond}.

We use *domestic* equity as the equity sleeve rather than the FX-converted
Global_Stock column: in the pooled / hyperinflation samples (JPN/DEU postwar)
the FX-converted world-equity and gold series share the same exchange-rate
shock and produce single-year measurement spikes (vol > 100%, spurious mutual
correlation ~0.9) that distort moments. Domestic equity is local-currency and
artifact-free, and is the standard per-country equity series in the
"rate of return on everything" literature. Gold intentionally keeps its FX
exposure (gold = USD price x local FX) since currency-debasement hedging is a
genuine part of its return for a non-USD investor.

Robustness transforms
----------------------
- Common sample: per country we keep only years where ALL four assets +
  inflation exist, so every menu is evaluated on the identical window
  (isolates the effect of *adding* an asset, not of changing the period).
- Winsorize each asset's real annual return at the per-country [1, 99]
  percentiles before bootstrapping, to cap residual currency-collapse
  measurement spikes (mainly gold in JPN/DEU). Clean assets (stock/bond/
  housing) are barely affected.

Method
------
- Joint block bootstrap (same engine as the product) over the winsorized real
  arrays, sampling all assets with shared block indices to preserve
  cross-asset correlation. Pooled draws are GDP-sqrt weighted (matches the
  product's country="ALL").
- For each allocation on a 0.1 grid: terminal-wealth metrics, ranked by CRRA
  certainty-equivalent (gamma in {1,2,4,8}), plus annualized real vol,
  reward/vol, and 10th-percentile terminal wealth. Headline optimum uses
  gamma=2 (moderate risk aversion); the gamma=4 optimum is reported only as a
  "downside-averse" direction-of-shift comparison (its CE magnitude and gold
  weights are tail-dominated — see PRIMARY_GAMMA note below).
- Decumulation lens: for each menu's optimum, max constant real withdrawal
  sustaining 90% success, and success at a 4% rate, over the horizon.

Outputs
-------
  analysis/output/multi_asset_allocation/results.csv     (optimum per menu)
  analysis/output/multi_asset_allocation/asset_stats.csv (real mean/vol/corr)

NOTE: analysis only — nothing here is wired into the simulator/product. Gold
is a prep-only dataset (see docs/gold-data-preparation.md).
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

# ──────────────────────────── parameters ────────────────────────────────────
NUM_SIMS = 5_000
MIN_BLOCK = 5
MAX_BLOCK = 15
SEED = 42
STEP = 0.1                       # allocation grid step (tenths)
HORIZONS = [30, 40]
GAMMAS = [1.0, 2.0, 4.0, 8.0]    # CRRA risk aversion for certainty equivalent
PRIMARY_GAMMA = 2.0              # headline optimum (moderate risk aversion).
# NOTE: gamma=4 CE is dominated by the extreme left tail (a few near-zero
# terminal-wealth paths make E[W^-3] explode), so its *magnitude* and the gold
# weights it picks are tail-artifacts and not a sensible recommendation. We use
# gamma=2 for the headline optimum and report the gamma=4 optimum only as a
# "downside-averse" direction-of-shift comparison.
WINSOR = (1.0, 99.0)             # per-country percentile clip on real returns
SWR_SUCCESS_TARGET = 0.90        # decumulation: max SWR at this success
SWR_TEST_RATE = 0.04             # decumulation: success at this rate

SINGLE_COUNTRIES = ["USA", "JPN", "GBR", "DEU", "AUS"]

ASSETS = ["domestic_stock", "domestic_bond", "housing", "gold"]
ASSET_CODE = {"domestic_stock": "ST", "domestic_bond": "BD",
              "housing": "HO", "gold": "GO"}
NOMINAL_COLS = ["Domestic_Stock", "Domestic_Bond", "Housing_TR",
                "Gold_Nominal_Return", "Inflation"]
IDX_INFL = 4  # inflation index within NOMINAL_COLS
N_ASSETS = len(ASSETS)

MENUS = {
    "base_stocks_bonds": ["domestic_stock", "domestic_bond"],
    "add_housing":       ["domestic_stock", "domestic_bond", "housing"],
    "add_gold":          ["domestic_stock", "domestic_bond", "gold"],
    "add_both":          ASSETS,
}

OUTPUT_DIR = ROOT / "analysis" / "output" / "multi_asset_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────── data prep ─────────────────────────────────────
def load_real_arrays() -> dict[str, np.ndarray]:
    """Per-country winsorized REAL arrays, shape (n_years, N_ASSETS)."""
    ret = pd.read_csv(ROOT / "data" / "jst_returns.csv")
    gold = pd.read_csv(ROOT / "data" / "jst_gold.csv")[
        ["Year", "Country", "Gold_Nominal_Return"]
    ]
    df = ret.merge(gold, on=["Year", "Country"], how="left")

    out: dict[str, np.ndarray] = {}
    for iso, sub in df.groupby("Country"):
        sub = sub.sort_values("Year")
        cc = sub.dropna(subset=NOMINAL_COLS)
        if len(cc) < 30:
            continue
        nom = cc[NOMINAL_COLS].to_numpy(dtype=np.float64)
        infl = nom[:, IDX_INFL:IDX_INFL + 1]
        real = (1.0 + nom[:, :N_ASSETS]) / (1.0 + infl) - 1.0
        # winsorize per asset at per-country percentiles
        lo = np.percentile(real, WINSOR[0], axis=0)
        hi = np.percentile(real, WINSOR[1], axis=0)
        out[iso] = np.clip(real, lo, hi)
    return out


# ─────────────────────── bootstrap real-return tensor ───────────────────────
def bootstrap_tensor(arrays: dict[str, np.ndarray], entity: str,
                     horizon: int, rng: np.random.Generator) -> np.ndarray:
    """Real-return tensor (NUM_SIMS, horizon, N_ASSETS).

    entity == "ALL" -> GDP-sqrt-weighted pooled draw across all countries.
    """
    out = np.empty((NUM_SIMS, horizon, N_ASSETS), dtype=np.float64)
    if entity == "ALL":
        country_list = list(arrays.keys())
        country_arrays = [arrays[c] for c in country_list]
        country_lens = [len(a) for a in country_arrays]
        wdict = get_gdp_weights(country_list)
        probs = np.array([wdict[c] for c in country_list])
        probs = probs / probs.sum()
        for s in range(NUM_SIMS):
            out[s] = block_bootstrap_pooled_np(
                country_arrays, country_lens, probs,
                horizon, MIN_BLOCK, MAX_BLOCK, rng)
    else:
        data = arrays[entity]
        n = len(data)
        for s in range(NUM_SIMS):
            out[s] = block_bootstrap_np(data, n, horizon, MIN_BLOCK, MAX_BLOCK, rng)
    return out


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


# ─────────────────────────── metrics ────────────────────────────────────────
def ce_annual(log_growth: np.ndarray, terminal: np.ndarray,
              gamma: float, horizon: int) -> float:
    """Annualized CRRA certainty-equivalent return of terminal wealth."""
    if abs(gamma - 1.0) < 1e-9:
        ce = float(np.exp(log_growth.mean()))
    else:
        w = np.clip(terminal, 1e-9, None)
        ce = float(np.mean(w ** (1.0 - gamma)) ** (1.0 / (1.0 - gamma)))
    return ce ** (1.0 / horizon) - 1.0


def evaluate(R: np.ndarray, weights: np.ndarray, horizon: int) -> pd.DataFrame:
    port = np.einsum("sta,ca->cst", R, weights)         # (n_combos, sims, H)
    log_growth = np.log1p(port).sum(axis=2)             # (n_combos, sims)
    terminal = np.exp(log_growth)
    cagr = np.expm1(log_growth / horizon)

    rows = []
    for c in range(weights.shape[0]):
        annual_vol = float(port[c].std())
        cagr_mean = float(cagr[c].mean())
        rec = {
            "cagr_mean": cagr_mean,
            "annual_vol": annual_vol,
            "reward_per_vol": cagr_mean / annual_vol if annual_vol > 0 else np.nan,
            "p10_terminal": float(np.percentile(terminal[c], 10)),
            "p50_terminal": float(np.percentile(terminal[c], 50)),
        }
        for g in GAMMAS:
            rec[f"ce_g{int(g)}"] = ce_annual(log_growth[c], terminal[c], g, horizon)
        rows.append(rec)
    df = pd.DataFrame(rows)
    for j, a in enumerate(ASSETS):
        df[a] = weights[:, j]
    return df


def max_swr_at_success(R_opt: np.ndarray, horizon: int,
                       target: float = SWR_SUCCESS_TARGET) -> float:
    best = 0.0
    # start at 0 so portfolios whose 90% SWR is below 2% (e.g. JPN equity-only)
    # report a valid sub-2% rate rather than a misleading 0%.
    for c in np.arange(0.0025, 0.0801, 0.0025):
        wealth = np.ones(R_opt.shape[0])
        alive = np.ones(R_opt.shape[0], dtype=bool)
        for t in range(horizon):
            wealth = wealth * (1.0 + R_opt[:, t]) - c
            alive &= wealth > 0
        if alive.mean() >= target:
            best = c
    return best


def success_at_rate(R_opt: np.ndarray, horizon: int, rate: float) -> float:
    wealth = np.ones(R_opt.shape[0])
    alive = np.ones(R_opt.shape[0], dtype=bool)
    for t in range(horizon):
        wealth = wealth * (1.0 + R_opt[:, t]) - rate
        alive &= wealth > 0
    return float(alive.mean())


# ─────────────────────────── descriptive stats ──────────────────────────────
def _weighted_moments(real: np.ndarray, w: np.ndarray):
    """Probability-weighted mean / vol / corr (w normalized to sum 1)."""
    mean = w @ real
    centered = real - mean
    cov = (centered * w[:, None]).T @ centered
    vol = np.sqrt(np.diag(cov))
    denom = np.outer(vol, vol)
    corr = np.divide(cov, denom, out=np.zeros_like(cov), where=denom > 0)
    return mean, vol, corr


def asset_descriptive(arrays: dict[str, np.ndarray], entity: str) -> dict:
    if entity == "ALL":
        # Weight rows to match the pooled bootstrap's sampling distribution:
        # country chosen with prob sqrt(GDP), then a uniform row within it, so
        # each row's weight = gdp_weight[country] / n_rows[country]. Equal-row
        # concatenation would over-represent long-history countries.
        real = np.vstack([arrays[c] for c in arrays])
        gw = get_gdp_weights(list(arrays.keys()))
        per_row = np.concatenate([
            np.full(len(arrays[c]), gw[c] / len(arrays[c])) for c in arrays
        ])
        per_row = per_row / per_row.sum()
        mean, vol, corr = _weighted_moments(real, per_row)
    else:
        real = arrays[entity]
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
    arrays = load_real_arrays()
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
            R = bootstrap_tensor(arrays, entity, horizon, rng)
            for menu, weights in menu_weights.items():
                ev = evaluate(R, weights, horizon)
                # headline optimum = max CRRA CE at PRIMARY_GAMMA (moderate)
                best = ev.loc[ev[f"ce_g{int(PRIMARY_GAMMA)}"].idxmax()].copy()
                w_opt = best[ASSETS].to_numpy(dtype=np.float64)
                R_opt = np.einsum("sta,a->st", R, w_opt)
                best["swr90"] = max_swr_at_success(R_opt, horizon)
                best["success_at_4pct"] = success_at_rate(R_opt, horizon, SWR_TEST_RATE)
                # downside-averse comparison: gamma=4 optimal allocation (string)
                best4 = ev.loc[ev["ce_g4"].idxmax()]
                best["alloc_g4_downside"] = "/".join(
                    f"{int(round(best4[a] * 100))}" for a in ASSETS)
                best["entity"] = entity
                best["horizon"] = horizon
                best["menu"] = menu
                results.append(best)
            print(f"  done {entity} H={horizon}")

    res = pd.DataFrame(results)
    # headline allocation (gamma=2 optimum) as a compact string
    res["alloc_g2"] = res.apply(
        lambda r: "/".join(f"{int(round(r[a] * 100))}" for a in ASSETS), axis=1)
    col_order = (
        ["entity", "horizon", "menu", "alloc_g2", "alloc_g4_downside"] + ASSETS
        + ["cagr_mean", "annual_vol", "reward_per_vol",
           "ce_g1", "ce_g2", "ce_g4", "ce_g8",
           "p10_terminal", "p50_terminal", "swr90", "success_at_4pct"]
    )
    res[col_order].to_csv(OUTPUT_DIR / "results.csv", index=False)
    print(f"Wrote {OUTPUT_DIR / 'results.csv'}  ({len(res)} rows)")


if __name__ == "__main__":
    main()
