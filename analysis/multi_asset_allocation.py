"""Multi-asset long-horizon allocation study v3 (2026-05-31).

Question
--------
Starting from a stocks+bonds portfolio (domestic_stock + global_stock +
domestic_bond — the product's three financial assets), how does the optimal
allocation change when we additionally allow domestic real estate / gold /
both? Real estate is studied under two treatments (per the prior
docs/four-asset-allocation-analysis.md):

  - "index"      : a diversified national housing index — volatility as-is,
                   holding cost 1.5% (owner-occupied: maintenance ~1% + tax/
                   fees ~0.5%).
  - "individual" : a single owned property — index systematic return PLUS
                   idiosyncratic property-specific noise that scales total
                   volatility to 1.5x the index and dilutes its correlation
                   with other assets to 2/3 (added in REAL space, scaled by the
                   housing weight, so individual housing standalone vol is
                   exactly 1.5x and corr(individual, X) = corr(index, X)/1.5).

Method — mirrors the product's "optimal allocation" tool
--------------------------------------------------------
- Block Bootstrap over JST returns (same engine as the product); pooled
  (sqrt-GDP weighted, = country="ALL") + representative single countries.
  All asset columns share block indices so cross-asset correlation is kept.
- Portfolio real return uses the product convention (portfolio.py): weight
  nominal returns net of PER-ASSET expense, then deflate once by inflation.
  Per-asset expense: financial assets + gold 0.5%, housing 1.5% (configurable).
  No winsorization (product-consistent; portfolio deflation tempers FX spikes).
- Fixed withdrawal strategy via the product's own kernel
  (_simulate_vectorized_fixed_from_matrix) + compute_success_rate /
  compute_funded_ratio, so metrics match the tool exactly.
- Each allocation on a 0.1 grid is ranked by FUNDED RATIO (coverage) — the
  product allocation page selects best = max(..., key=funded_ratio) — with
  SUCCESS RATE as tie-breaker.

Parameters (per user)
---------------------
- initial 1,000,000; withdrawal 33,000 real (3.3%); financial/gold expense
  0.5%; housing expense 1.5%; block 5-15; leverage 1.0; num_sims 3000;
  horizons 40 & 65y (3.3% is conservative — only long horizons differentiate).

Sensitivity sweeps (challenge the 1.5% / 1.5x assumptions)
---------------------------------------------------------
- housing-expense sweep {0.5, 1.0, 1.5, 2.0, 2.5}% (individual vol, 65y)
- housing-vol-multiple sweep {1.0, 1.25, 1.5, 1.75, 2.0}x (1.5% expense, 65y)

Outputs (analysis/output/multi_asset_allocation/)
  results.csv            optimum per (entity, horizon, menu, housing_scenario)
  asset_stats.csv        real mean/vol/corr (display-clipped)
  expense_sensitivity.csv, vol_sensitivity.csv

NOTE: analysis only — not wired into the product.
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
FIN_EXPENSE = 0.005           # financial assets + gold: 0.5%
HOUSING_EXPENSE = 0.015       # owner-occupied holding cost: 1.5%
INDIVIDUAL_VOL_MULT = 1.5     # single property vol = 1.5x index
NUM_SIMS = 3_000
MIN_BLOCK = 5
MAX_BLOCK = 15
SEED = 42
NOISE_SEED = 1_234            # independent stream for idiosyncratic housing noise
STEP = 0.1
HORIZONS = [40, 65]
SENS_HORIZON = 65

SINGLE_COUNTRIES = ["USA", "JPN", "GBR", "DEU", "AUS"]

ASSETS = ["domestic_stock", "global_stock", "domestic_bond", "housing", "gold"]
ASSET_CODE = {"domestic_stock": "DS", "global_stock": "GS",
              "domestic_bond": "DB", "housing": "HO", "gold": "GO"}
NOMINAL_COLS = ["Domestic_Stock", "Global_Stock", "Domestic_Bond",
                "Housing_TR", "Gold_Nominal_Return", "Inflation"]
IDX_INFL = 5
N_ASSETS = len(ASSETS)
HOUSING_IDX = ASSETS.index("housing")
REAL_CLIP = (-0.95, 3.0)      # display/vol-calibration clip on real returns

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


def expense_vector(housing_expense: float) -> np.ndarray:
    """Per-asset expense in ASSETS order; housing differs from the rest."""
    e = np.full(N_ASSETS, FIN_EXPENSE)
    e[HOUSING_IDX] = housing_expense
    return e


def index_housing_real_vol(arrays: dict[str, np.ndarray], entity: str) -> float:
    """Index (systematic) real housing vol, clipped; GDP-weighted for ALL.

    Used to calibrate the idiosyncratic noise so individual housing vol becomes
    exactly INDIVIDUAL_VOL_MULT x this.
    """
    def real_housing(nom):
        infl = nom[:, IDX_INFL]
        r = (1.0 + nom[:, HOUSING_IDX]) / (1.0 + infl) - 1.0
        return np.clip(r, *REAL_CLIP)

    if entity == "ALL":
        vals = np.concatenate([real_housing(arrays[c]) for c in arrays])
        gw = get_gdp_weights(list(arrays.keys()))
        w = np.concatenate([np.full(len(arrays[c]), gw[c] / len(arrays[c]))
                            for c in arrays])
        w = w / w.sum()
        # np.errstate: spurious "matmul" RuntimeWarning under macOS Accelerate.
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            mean = w @ vals
            var = w @ (vals - mean) ** 2
        return float(np.sqrt(var))
    return float(real_housing(arrays[entity]).std())


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


def real_returns_for_alloc(tensor: np.ndarray, w: np.ndarray,
                           expense_vec: np.ndarray,
                           sigma_real: float = 0.0,
                           noise_unit: np.ndarray | None = None) -> np.ndarray:
    """(NUM_SIMS, horizon) real portfolio returns for weights w.

    Product convention: weight nominal returns net of per-asset expense, then
    deflate once by inflation. For the individual-property case, add real-space
    idiosyncratic housing noise scaled by the housing weight:
        real += w_housing * sigma_real * noise_unit
    which makes standalone individual housing vol = sqrt(V^2 + sigma_real^2) and
    dilutes its correlation with every other asset by V / sqrt(V^2+sigma^2).
    """
    nominal_assets = tensor[:, :, :N_ASSETS]
    nominal_port = nominal_assets @ w - (w @ expense_vec)
    infl = tensor[:, :, IDX_INFL]
    real = (1.0 + nominal_port) / (1.0 + infl) - 1.0
    if sigma_real > 0.0 and noise_unit is not None:
        real = real + w[HOUSING_IDX] * sigma_real * noise_unit
    return real


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
def eval_allocation(tensor, w, horizon, expense_vec, sigma_real, noise_unit):
    real = real_returns_for_alloc(tensor, w, expense_vec, sigma_real, noise_unit)
    traj, _, _, _ = _simulate_vectorized_fixed_from_matrix(
        real, INITIAL, ANNUAL_WD, horizon)
    sr = compute_success_rate(traj, horizon)
    fr = compute_funded_ratio(traj, horizon)
    final = traj[:, -1]
    return sr, fr, float(np.median(final)), float(np.percentile(final, 10))


def best_allocation(tensor, weights, horizon, expense_vec, sigma_real, noise_unit):
    """Return the funded-ratio-optimal allocation row (success_rate tie-break)."""
    rows = []
    for w in weights:
        sr, fr, mfin, p10 = eval_allocation(
            tensor, w, horizon, expense_vec, sigma_real, noise_unit)
        rows.append((sr, fr, mfin, p10))
    ev = pd.DataFrame(rows, columns=["success_rate", "funded_ratio",
                                     "median_final", "p10_final"])
    for j, a in enumerate(ASSETS):
        ev[a] = weights[:, j]
    ev = ev.sort_values(["funded_ratio", "success_rate"],
                        ascending=False).reset_index(drop=True)
    return ev.iloc[0]


# ─────────────────────────── descriptive stats ──────────────────────────────
def _weighted_moments(real: np.ndarray, w: np.ndarray):
    # np.errstate guards a spurious "matmul" RuntimeWarning under macOS
    # Accelerate BLAS — inputs are clipped/bounded and outputs verified finite.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        mean = w @ real
        centered = real - mean
        cov = (centered * w[:, None]).T @ centered
    vol = np.sqrt(np.diag(cov))
    denom = np.outer(vol, vol)
    corr = np.divide(cov, denom, out=np.zeros_like(cov), where=denom > 0)
    return mean, vol, corr


def asset_descriptive(arrays: dict[str, np.ndarray], entity: str) -> dict:
    """Per-asset real mean/vol + corr (moments on returns clipped to REAL_CLIP
    for display readability; the main analysis uses RAW data)."""
    def to_real(nom):
        infl = nom[:, IDX_INFL:IDX_INFL + 1]
        real = (1.0 + nom[:, :N_ASSETS]) / (1.0 + infl) - 1.0
        return np.clip(real, *REAL_CLIP)

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


# ─────────────────────────── main sweeps ────────────────────────────────────
def sigma_real_for(vol_mult: float, v_idx: float) -> float:
    return float(np.sqrt(max(vol_mult ** 2 - 1.0, 0.0)) * v_idx)


def run_main(arrays, entities):
    """Optimum per (entity, horizon, menu, housing_scenario)."""
    menu_weights = {n: menu_allocations(a) for n, a in MENUS.items()}
    exp_vec = expense_vector(HOUSING_EXPENSE)
    results = []
    for entity in entities:
        v_idx = index_housing_real_vol(arrays, entity)
        for horizon in HORIZONS:
            rng = np.random.default_rng(SEED)        # identical draws across menus
            tensor = bootstrap_tensor(arrays, entity, horizon, rng)
            noise_rng = np.random.default_rng(NOISE_SEED)
            noise_unit = noise_rng.standard_normal((NUM_SIMS, horizon))
            for menu, weights in menu_weights.items():
                has_house = "housing" in MENUS[menu]
                scenarios = (["index", "individual"] if has_house else ["—"])
                for scen in scenarios:
                    if scen == "individual":
                        sigma = sigma_real_for(INDIVIDUAL_VOL_MULT, v_idx)
                    else:
                        sigma = 0.0
                    best = best_allocation(
                        tensor, weights, horizon, exp_vec, sigma, noise_unit)
                    best = best.copy()
                    best["alloc"] = "/".join(
                        f"{int(round(best[a] * 100))}" for a in ASSETS)
                    best["entity"] = entity
                    best["horizon"] = horizon
                    best["menu"] = menu
                    best["housing_scenario"] = scen
                    results.append(best)
            print(f"  done {entity} H={horizon}")
    res = pd.DataFrame(results)
    cols = (["entity", "horizon", "menu", "housing_scenario", "alloc"] + ASSETS
            + ["success_rate", "funded_ratio", "median_final", "p10_final"])
    res[cols].to_csv(OUTPUT_DIR / "results.csv", index=False)
    print(f"Wrote results.csv ({len(res)} rows)")


def run_sensitivity(arrays, entities, kind: str):
    """Sweep housing expense or vol-multiple for the +housing menu at 65y."""
    weights = menu_allocations(MENUS["add_housing"])
    grid = ([0.005, 0.010, 0.015, 0.020, 0.025] if kind == "expense"
            else [1.0, 1.25, 1.5, 1.75, 2.0])
    rows = []
    for entity in entities:
        v_idx = index_housing_real_vol(arrays, entity)
        rng = np.random.default_rng(SEED)
        tensor = bootstrap_tensor(arrays, entity, SENS_HORIZON, rng)
        noise_unit = np.random.default_rng(NOISE_SEED).standard_normal(
            (NUM_SIMS, SENS_HORIZON))
        for g in grid:
            if kind == "expense":
                exp_vec = expense_vector(g)
                sigma = sigma_real_for(INDIVIDUAL_VOL_MULT, v_idx)  # individual
            else:
                exp_vec = expense_vector(HOUSING_EXPENSE)
                sigma = sigma_real_for(g, v_idx)
            best = best_allocation(tensor, weights, SENS_HORIZON,
                                   exp_vec, sigma, noise_unit)
            rows.append({
                "entity": entity,
                ("housing_expense" if kind == "expense" else "vol_mult"): g,
                "opt_housing_pct": int(round(best["housing"] * 100)),
                "alloc": "/".join(f"{int(round(best[a] * 100))}" for a in ASSETS),
                "success_rate": best["success_rate"],
                "funded_ratio": best["funded_ratio"],
                "p10_final": best["p10_final"],
            })
    fn = f"{kind}_sensitivity.csv"
    pd.DataFrame(rows).to_csv(OUTPUT_DIR / fn, index=False)
    print(f"Wrote {fn}")


def main() -> None:
    arrays = load_nominal_arrays()
    entities = ["ALL"] + [c for c in SINGLE_COUNTRIES if c in arrays]
    print(f"Entities: {entities}")
    print("Common-sample sizes: "
          + ", ".join(f"{c}={len(arrays[c])}" for c in arrays))

    pd.DataFrame([asset_descriptive(arrays, e) for e in entities]).to_csv(
        OUTPUT_DIR / "asset_stats.csv", index=False)
    print("Wrote asset_stats.csv")

    run_main(arrays, entities)
    run_sensitivity(arrays, ["ALL", "USA"], "expense")
    run_sensitivity(arrays, ["ALL", "USA"], "vol")


if __name__ == "__main__":
    main()
