"""Multi-asset long-horizon allocation study v4 (2026-05-31).

Question
--------
From a stocks+bonds base (domestic_stock + global_stock + domestic_bond — the
product's three financial assets), how does the optimal allocation change when
adding domestic real estate / gold / both? Real estate is studied two ways
(per docs/four-asset-allocation-analysis.md):

  - "index"      : diversified national housing index — vol as-is, holding
                   cost 1.5%.
  - "individual" : single owned property — index systematic return PLUS
                   idiosyncratic real-space noise that makes standalone vol =
                   1.5x index and dilutes cross-asset corr to 2/3. The
                   individual housing real return is floored at -100% (an
                   unlevered asset cannot lose more than its value).

Method — mirrors the product "optimal allocation" tool
------------------------------------------------------
- Block Bootstrap over JST returns (product engine); pooled (sqrt-GDP) +
  single countries; shared block indices keep cross-asset correlation.
- Portfolio real return = product convention (portfolio.py): weight nominal
  net of per-asset expense, deflate once. Per-asset expense: financial+gold
  0.5%, housing 1.5%. No winsorization (product-consistent).
- Fixed withdrawal via the product kernel; ranked by FUNDED RATIO (= product
  best = max(key=funded_ratio)), success rate as tie-break.
- Allocation grid step 0.05 (5%). Evaluation is vectorized in chunks so the
  finer grid stays fast. (A 1% grid for 5 assets = C(104,4) ~ 4.6M points is
  infeasible by brute force; the optimum sits on a flat plateau so 5% does not
  change conclusions — adjacent grid points differ <~0.2pp in funded ratio.)

Parameters (per user): initial 1,000,000; withdrawal 33,000 real (3.3%);
financial/gold expense 0.5%, housing 1.5%; block 5-15; 3000 sims; horizons
40 & 65y.

Extra analyses
--------------
- housing-expense {0.5..2.5}% and vol-mult {1.0..2.0}x sensitivity (65y).
- REGIME sub-period analysis: bootstrap restricted to historical windows
  (pre-WWII 1900-1945, post-WWII 1946+, post-gold-standard 1971+, modern
  1990+, vs full sample) for pooled + USA, to see how the optimum and the
  asset means shift across monetary regimes.

Outputs (analysis/output/multi_asset_allocation/): results.csv, asset_stats.csv,
expense_sensitivity.csv, vol_sensitivity.csv, regime_analysis.csv,
regime_asset_stats.csv. NOTE: analysis only — not wired into the product.
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
from simulator.statistics import compute_success_rate, compute_funded_ratio  # noqa: F401

# ──────────────────────────── parameters ────────────────────────────────────
INITIAL = 1_000_000.0
ANNUAL_WD = 33_000.0
FIN_EXPENSE = 0.005
HOUSING_EXPENSE = 0.015
INDIVIDUAL_VOL_MULT = 1.5
NUM_SIMS = 3_000
MIN_BLOCK = 5
MAX_BLOCK = 15
SEED = 42
NOISE_SEED = 1_234
STEP = 0.05
HORIZONS = [40, 65]
SENS_HORIZON = 65
CHUNK = 120                      # combos per vectorized batch (bounds memory)

SINGLE_COUNTRIES = ["USA", "JPN", "GBR", "DEU", "AUS"]

ASSETS = ["domestic_stock", "global_stock", "domestic_bond", "housing", "gold"]
ASSET_CODE = {"domestic_stock": "DS", "global_stock": "GS",
              "domestic_bond": "DB", "housing": "HO", "gold": "GO"}
NOMINAL_COLS = ["Domestic_Stock", "Global_Stock", "Domestic_Bond",
                "Housing_TR", "Gold_Nominal_Return", "Inflation"]
IDX_INFL = 5
N_ASSETS = len(ASSETS)
HOUSING_IDX = ASSETS.index("housing")
REAL_CLIP = (-0.95, 3.0)

MENUS = {
    "base_stocks_bonds": ["domestic_stock", "global_stock", "domestic_bond"],
    "add_housing":       ["domestic_stock", "global_stock", "domestic_bond", "housing"],
    "add_gold":          ["domestic_stock", "global_stock", "domestic_bond", "gold"],
    "add_both":          ASSETS,
}

REGIMES = {  # (year_min, year_max)
    "full":              (1871, 2025),
    "prewar_1900_1945":  (1900, 1945),
    "postwar_1946+":     (1946, 2025),
    "post_gold_1971+":   (1971, 2025),
    "modern_1990+":      (1990, 2025),
}

OUTPUT_DIR = ROOT / "analysis" / "output" / "multi_asset_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────── data prep ─────────────────────────────────────
def load_nominal_arrays(year_min: int | None = None,
                        year_max: int | None = None,
                        min_years: int = 30) -> dict[str, np.ndarray]:
    """Per-country common-sample nominal arrays (n_years, 6), optional window."""
    ret = pd.read_csv(ROOT / "data" / "jst_returns.csv")
    gold = pd.read_csv(ROOT / "data" / "jst_gold.csv")[
        ["Year", "Country", "Gold_Nominal_Return"]]
    df = ret.merge(gold, on=["Year", "Country"], how="left")
    if year_min is not None:
        df = df[df["Year"] >= year_min]
    if year_max is not None:
        df = df[df["Year"] <= year_max]
    out: dict[str, np.ndarray] = {}
    for iso, sub in df.groupby("Country"):
        cc = sub.sort_values("Year").dropna(subset=NOMINAL_COLS)
        if len(cc) >= min_years:
            out[iso] = cc[NOMINAL_COLS].to_numpy(dtype=np.float64)
    return out


def expense_vector(housing_expense: float) -> np.ndarray:
    e = np.full(N_ASSETS, FIN_EXPENSE)
    e[HOUSING_IDX] = housing_expense
    return e


def index_housing_real_vol(arrays: dict[str, np.ndarray], entity: str) -> float:
    def real_housing(nom):
        r = (1.0 + nom[:, HOUSING_IDX]) / (1.0 + nom[:, IDX_INFL]) - 1.0
        return np.clip(r, *REAL_CLIP)
    if entity == "ALL":
        vals = np.concatenate([real_housing(arrays[c]) for c in arrays])
        gw = get_gdp_weights(list(arrays.keys()))
        w = np.concatenate([np.full(len(arrays[c]), gw[c] / len(arrays[c]))
                            for c in arrays])
        w = w / w.sum()
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            mean = w @ vals
            var = w @ (vals - mean) ** 2
        return float(np.sqrt(var))
    return float(real_housing(arrays[entity]).std())


def sigma_real_for(vol_mult: float, v_idx: float) -> float:
    return float(np.sqrt(max(vol_mult ** 2 - 1.0, 0.0)) * v_idx)


# ─────────────────────── bootstrap nominal tensor ───────────────────────────
def bootstrap_tensor(arrays, entity, horizon, rng):
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


# ─────────────────────────── allocation grid ────────────────────────────────
def compositions(k: int, total: int):
    if k == 1:
        return [(total,)]
    res = []
    for first in range(total + 1):
        for rest in compositions(k - 1, total - first):
            res.append((first,) + rest)
    return res


def menu_allocations(allowed: list[str]) -> np.ndarray:
    n = int(round(1.0 / STEP))
    idxs = [ASSETS.index(a) for a in allowed]
    combos = compositions(len(allowed), n)
    mat = np.zeros((len(combos), N_ASSETS))
    for r, comp in enumerate(combos):
        for j, idx in enumerate(idxs):
            mat[r, idx] = comp[j] * STEP
    return mat


# ─────────────────────── vectorized evaluation ──────────────────────────────
def evaluate_menu(tensor, weights, horizon, expense_vec,
                  sigma_real=0.0, noise_unit=None):
    """Return per-combo (success, funded, median_final, p10_final) arrays.

    Vectorized in chunks of CHUNK combos. Individual-property idiosyncratic
    noise is applied in real space, scaled by the housing weight, with the
    individual housing real return floored at -100%.
    """
    nominal_assets = tensor[:, :, :N_ASSETS]            # (S,H,5)
    infl = tensor[:, :, IDX_INFL]                       # (S,H)
    one_plus_infl = 1.0 + infl

    delta_h = None
    if sigma_real > 0.0 and noise_unit is not None:
        e_h = expense_vec[HOUSING_IDX]
        hr_index = (1.0 + nominal_assets[:, :, HOUSING_IDX] - e_h) / one_plus_infl - 1.0
        hr_indiv = np.maximum(hr_index + sigma_real * noise_unit, -1.0)
        delta_h = hr_indiv - hr_index                   # (S,H)

    C = weights.shape[0]
    succ = np.empty(C); fund = np.empty(C)
    med = np.empty(C); p10 = np.empty(C)
    drag = weights @ expense_vec                         # (C,)

    for lo in range(0, C, CHUNK):
        hi = min(lo + CHUNK, C)
        W = weights[lo:hi]                               # (c,5)
        nom_port = np.einsum("sha,ca->csh", nominal_assets, W) - drag[lo:hi, None, None]
        real = (1.0 + nom_port) / one_plus_infl[None] - 1.0   # (c,S,H)
        if delta_h is not None:
            real = real + W[:, HOUSING_IDX][:, None, None] * delta_h[None]
        c = hi - lo
        traj, _, _, _ = _simulate_vectorized_fixed_from_matrix(
            real.reshape(c * NUM_SIMS, horizon), INITIAL, ANNUAL_WD, horizon)
        traj = traj.reshape(c, NUM_SIMS, horizon + 1)
        depleted = traj[:, :, 1:] <= 0
        any_dep = depleted.any(axis=2)
        dep_year = np.where(any_dep, depleted.argmax(axis=2) + 1, horizon)
        succ[lo:hi] = (dep_year >= horizon).mean(axis=1)
        fund[lo:hi] = np.minimum(dep_year / horizon, 1.0).mean(axis=1)
        final = traj[:, :, -1]
        med[lo:hi] = np.percentile(final, 50, axis=1)
        p10[lo:hi] = np.percentile(final, 10, axis=1)
    return succ, fund, med, p10


def best_row(weights, succ, fund, med, p10):
    """Funded-ratio-optimal combo (success tie-break)."""
    i = np.lexsort((succ, fund))[-1]          # primary fund, secondary succ
    return {
        "alloc": "/".join(f"{int(round(weights[i, j] * 100))}" for j in range(N_ASSETS)),
        **{a: weights[i, j] for j, a in enumerate(ASSETS)},
        "success_rate": float(succ[i]), "funded_ratio": float(fund[i]),
        "median_final": float(med[i]), "p10_final": float(p10[i]),
    }


# ─────────────────────────── descriptive stats ──────────────────────────────
def _weighted_moments(real, w):
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        mean = w @ real
        centered = real - mean
        cov = (centered * w[:, None]).T @ centered
    vol = np.sqrt(np.diag(cov))
    denom = np.outer(vol, vol)
    corr = np.divide(cov, denom, out=np.zeros_like(cov), where=denom > 0)
    return mean, vol, corr


def asset_real_means(arrays, entity):
    """GDP-weighted (ALL) clipped real mean per asset — for regime insight."""
    def to_real(nom):
        infl = nom[:, IDX_INFL:IDX_INFL + 1]
        return np.clip((1.0 + nom[:, :N_ASSETS]) / (1.0 + infl) - 1.0, *REAL_CLIP)
    if entity == "ALL":
        real = np.vstack([to_real(arrays[c]) for c in arrays])
        gw = get_gdp_weights(list(arrays.keys()))
        w = np.concatenate([np.full(len(arrays[c]), gw[c] / len(arrays[c]))
                            for c in arrays])
        w = w / w.sum()
        mean, vol, _ = _weighted_moments(real, w)
    else:
        real = to_real(arrays[entity])
        mean, vol, _ = _weighted_moments(real, np.full(len(real), 1.0 / len(real)))
    return mean, vol


def asset_descriptive(arrays, entity):
    mean, vol = asset_real_means(arrays, entity)

    def to_real(nom):
        infl = nom[:, IDX_INFL:IDX_INFL + 1]
        return np.clip((1.0 + nom[:, :N_ASSETS]) / (1.0 + infl) - 1.0, *REAL_CLIP)
    if entity == "ALL":
        real = np.vstack([to_real(arrays[c]) for c in arrays])
        gw = get_gdp_weights(list(arrays.keys()))
        w = np.concatenate([np.full(len(arrays[c]), gw[c] / len(arrays[c]))
                            for c in arrays])
        w = w / w.sum()
        _, _, corr = _weighted_moments(real, w)
    else:
        real = to_real(arrays[entity])
        _, _, corr = _weighted_moments(real, np.full(len(real), 1.0 / len(real)))
    rec = {"entity": entity, "n_obs": real.shape[0]}
    for j, a in enumerate(ASSETS):
        rec[f"mean_{a}"] = mean[j]; rec[f"vol_{a}"] = vol[j]
    for i in range(N_ASSETS):
        for j in range(i + 1, N_ASSETS):
            rec[f"corr_{ASSET_CODE[ASSETS[i]]}_{ASSET_CODE[ASSETS[j]]}"] = corr[i, j]
    return rec


# ─────────────────────────── runners ────────────────────────────────────────
def make_noise(horizon):
    return np.random.default_rng(NOISE_SEED).standard_normal((NUM_SIMS, horizon))


def run_main(arrays, entities):
    menu_w = {n: menu_allocations(a) for n, a in MENUS.items()}
    exp_vec = expense_vector(HOUSING_EXPENSE)
    results = []
    for entity in entities:
        v_idx = index_housing_real_vol(arrays, entity)
        for horizon in HORIZONS:
            rng = np.random.default_rng(SEED)
            tensor = bootstrap_tensor(arrays, entity, horizon, rng)
            noise = make_noise(horizon)
            for menu, weights in menu_w.items():
                has_house = "housing" in MENUS[menu]
                for scen in (["index", "individual"] if has_house else ["—"]):
                    sigma = (sigma_real_for(INDIVIDUAL_VOL_MULT, v_idx)
                             if scen == "individual" else 0.0)
                    metrics = evaluate_menu(tensor, weights, horizon, exp_vec, sigma, noise)
                    row = best_row(weights, *metrics)
                    row.update(entity=entity, horizon=horizon, menu=menu,
                               housing_scenario=scen)
                    results.append(row)
            print(f"  main {entity} H={horizon}")
    res = pd.DataFrame(results)
    cols = (["entity", "horizon", "menu", "housing_scenario", "alloc"] + ASSETS
            + ["success_rate", "funded_ratio", "median_final", "p10_final"])
    res[cols].to_csv(OUTPUT_DIR / "results.csv", index=False)
    print(f"Wrote results.csv ({len(res)} rows)")


def run_sensitivity(arrays, entities, kind):
    weights = menu_allocations(MENUS["add_housing"])
    grid = ([0.005, 0.010, 0.015, 0.020, 0.025] if kind == "expense"
            else [1.0, 1.25, 1.5, 1.75, 2.0])
    rows = []
    for entity in entities:
        v_idx = index_housing_real_vol(arrays, entity)
        tensor = bootstrap_tensor(arrays, entity, SENS_HORIZON,
                                  np.random.default_rng(SEED))
        noise = make_noise(SENS_HORIZON)
        for g in grid:
            exp_vec = expense_vector(g if kind == "expense" else HOUSING_EXPENSE)
            mult = INDIVIDUAL_VOL_MULT if kind == "expense" else g
            sigma = sigma_real_for(mult, v_idx)
            row = best_row(weights, *evaluate_menu(
                tensor, weights, SENS_HORIZON, exp_vec, sigma, noise))
            rows.append({
                "entity": entity,
                ("housing_expense" if kind == "expense" else "vol_mult"): g,
                "opt_housing_pct": int(round(row["housing"] * 100)),
                "alloc": row["alloc"], "success_rate": row["success_rate"],
                "funded_ratio": row["funded_ratio"], "p10_final": row["p10_final"],
            })
    pd.DataFrame(rows).to_csv(OUTPUT_DIR / f"{kind}_sensitivity.csv", index=False)
    print(f"Wrote {kind}_sensitivity.csv")


def run_regimes(entities, horizon=SENS_HORIZON):
    """How the optimum + asset means shift across monetary regimes."""
    exp_vec = expense_vector(HOUSING_EXPENSE)
    alloc_rows, stat_rows = [], []
    menu_w = {"base_stocks_bonds": menu_allocations(MENUS["base_stocks_bonds"]),
              "add_both_individual": menu_allocations(MENUS["add_both"])}
    for regime, (y0, y1) in REGIMES.items():
        arrays = load_nominal_arrays(y0, y1, min_years=20)
        for entity in entities:
            if entity != "ALL" and entity not in arrays:
                continue
            v_idx = index_housing_real_vol(arrays, entity)
            mean, vol = asset_real_means(arrays, entity)
            stat_rows.append({
                "regime": regime, "entity": entity,
                **{f"mean_{a}": mean[j] for j, a in enumerate(ASSETS)},
                **{f"vol_{a}": vol[j] for j, a in enumerate(ASSETS)},
            })
            tensor = bootstrap_tensor(arrays, entity, horizon,
                                      np.random.default_rng(SEED))
            noise = make_noise(horizon)
            for menu, weights in menu_w.items():
                sigma = (sigma_real_for(INDIVIDUAL_VOL_MULT, v_idx)
                         if menu == "add_both_individual" else 0.0)
                row = best_row(weights, *evaluate_menu(
                    tensor, weights, horizon, exp_vec, sigma, noise))
                row.update(regime=regime, entity=entity, menu=menu)
                alloc_rows.append(row)
        print(f"  regime {regime}")
    cols = (["regime", "entity", "menu", "alloc"] + ASSETS
            + ["success_rate", "funded_ratio", "median_final", "p10_final"])
    pd.DataFrame(alloc_rows)[cols].to_csv(OUTPUT_DIR / "regime_analysis.csv", index=False)
    pd.DataFrame(stat_rows).to_csv(OUTPUT_DIR / "regime_asset_stats.csv", index=False)
    print("Wrote regime_analysis.csv + regime_asset_stats.csv")


def main():
    arrays = load_nominal_arrays()
    entities = ["ALL"] + [c for c in SINGLE_COUNTRIES if c in arrays]
    print(f"Entities: {entities}  (grid step {STEP})")
    pd.DataFrame([asset_descriptive(arrays, e) for e in entities]).to_csv(
        OUTPUT_DIR / "asset_stats.csv", index=False)
    print("Wrote asset_stats.csv")
    run_main(arrays, entities)
    run_sensitivity(arrays, ["ALL", "USA"], "expense")
    run_sensitivity(arrays, ["ALL", "USA"], "vol")
    run_regimes(["ALL", "USA"])


if __name__ == "__main__":
    main()
