"""CEW-primary allocation on US FIRE_dataset_intl + gold + US real estate (2026-06-11).

Extends optimal_allocation_cew_us.py (3 assets: US/Intl stock + US bond) to 5
assets by adding gold and US residential real estate, mirroring the pooled
5-asset study (optimal_allocation_cew_multi.py) but with single-country US
bootstrap.

Data (6-column nominal panel merged on Year, complete 1891-2025):
  - US_Stock / Intl_Stock / US_Bond / Inflation: data/FIRE_dataset_intl.csv
    (identical to the 3-asset base study)
  - Housing_TR: data/jst_returns.csv USA rows (nominal total return)
  - Gold: data/jst_gold.csv USA rows (USD gold price nominal return)
  Deflation uses the FIRE_dataset_intl US Inflation throughout (Shiller CPI);
  a JST-vs-Shiller CPI comparison is printed as a diagnostic (Codex review #1).

Asset modeling (user spec, same as the pooled 5-asset study):
  - Housing = INDIVIDUAL property: 2.0%/yr maintenance as expense; idiosyncratic
    real-space noise sigma = sqrt(1.5^2-1)*sigma_index (standalone vol = 1.5x
    index, corr ~2/3 with index), individual real return floored at -100%.
    sigma_index = std of US real housing index returns per start-year window.
  - Gold: 0.5%/yr holding cost. Financial assets: 0.5%/yr expense.

Objective (identical to prior CEW studies):
    maximize    median CEW (CRRA gamma=2, delta=0.02)
    subject to  success_rate >= 0.90
                P(path funded_ratio < 0.5) <= 0.01
    tie-break   consumption-path Ulcer Index
Guardrail tier F: target=0.85/lower=0.75, upper=0.99, adj=0.05, amount, mr=1.

Grid: one 10pp 5-asset simplex (1001 combos) per start year {1900, 1950, 1970};
the four universes (base / +gold / +housing / +both) are exact slices of the
same grid sharing one bootstrap draw (w_housing=0 rows are unaffected by the
idio noise), so cross-universe comparisons are paired.

Phases:
  1. Grid 1001 x 3 start years, N=2000, seed=42 (shared bootstrap per window)
  2. Multi-seed confirm at 1900: seeds [42,5042,10042,15042,20042]
     (spacing >= NUM_SIMS per the seed-overlap pitfall)
  3. High-N (10000, seed=777000) confirm at 1900 and 1970 (gold regime changes
     post-1971; 1970 stays a regime scenario, not a base case)

Output: analysis/output/optimal_allocation/cew_us_multi_{results,multiseed,
confirm10k}.csv + cew_us_multi_summary.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

from simulator.bootstrap import block_bootstrap_np
from simulator.guardrail import build_success_rate_table, run_guardrail_simulation
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate

from multi_asset_allocation import compositions
from optimal_allocation_cew import (
    INITIAL_PORTFOLIO, NUM_SIMS, RETIREMENT_YEARS, MIN_BLOCK, MAX_BLOCK,
    SEED, CONSUMPTION_FLOOR, GR_UPPER, GR_ADJ, GR_MODE, GR_MIN_REMAIN,
    SR_FLOOR, SEVERE_FAIL_MAX, CEW_NEAR_OPTIMAL,
    compute_cew, per_path_funded_ratio, consumption_ulcer,
)

# ─────────────── parameters ────────────────────────────────────────────────
ASSETS = ["us_stock", "intl_stock", "us_bond", "housing", "gold"]
N_ASSETS = len(ASSETS)
HOUSING_IDX = ASSETS.index("housing")
IDX_INFL = N_ASSETS  # last column of the nominal panel
STEP = 0.10

START_YEARS = [1900, 1950, 1970]
PRIMARY_START = 1900
HIGHN_STARTS = [1900, 1970]

FIN_EXPENSE = 0.005
HOUSING_EXPENSE = 0.020          # user spec: 2%/yr maintenance
GOLD_EXPENSE = 0.005
VOL_MULT = 1.5                   # user spec: individual property vol 1.5x index
REAL_CLIP = (-0.95, 3.0)         # vol-estimation clip, same as pooled study

EXPENSE_VEC = np.full(N_ASSETS, FIN_EXPENSE)
EXPENSE_VEC[HOUSING_IDX] = HOUSING_EXPENSE
EXPENSE_VEC[ASSETS.index("gold")] = GOLD_EXPENSE

GR_TARGET, GR_LOWER = 0.85, 0.75

CONFIRM_SEEDS = [5042, 10042, 15042, 20042]
HIGHN_SIMS = 10_000
HIGHN_SEED = 777_000
TOP_K_CONFIRM = 5    # per universe, by median CEW
TOP_TAIL_CONFIRM = 2  # per universe, by p10_cew

UNIVERSES = ["base", "add_gold", "add_housing", "add_both"]

OUTPUT_DIR = ROOT / "analysis" / "output" / "optimal_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────── data ───────────────────────────────────────────────────────

def load_panel() -> pd.DataFrame:
    """Merged nominal panel: Year + 5 asset returns + Inflation (1891-2025)."""
    fire = pd.read_csv(ROOT / "data" / "FIRE_dataset_intl.csv")
    fire = fire.rename(columns={
        "US Stock": "us_stock", "International Stock": "intl_stock",
        "US Bond": "us_bond", "US Inflation": "Inflation"})
    jst = pd.read_csv(ROOT / "data" / "jst_returns.csv")
    usa = jst[jst["Country"] == "USA"][["Year", "Housing_TR", "Inflation"]]
    usa = usa.rename(columns={"Housing_TR": "housing",
                              "Inflation": "jst_inflation"})
    gold = pd.read_csv(ROOT / "data" / "jst_gold.csv")
    gold = gold[gold["Country"] == "USA"][["Year", "Gold_Nominal_Return"]]
    gold = gold.rename(columns={"Gold_Nominal_Return": "gold"})

    df = fire.merge(usa, on="Year").merge(gold, on="Year").dropna(
        subset=ASSETS + ["Inflation"]).reset_index(drop=True)
    assert (df["Year"].diff().iloc[1:] == 1).all(), "year gaps in merged panel"
    return df


def cpi_diagnostic(df: pd.DataFrame) -> str:
    """Shiller CPI (deflator used) vs JST USA CPI — Codex review item #1."""
    d = df.dropna(subset=["jst_inflation"])
    diff = d["Inflation"] - d["jst_inflation"]
    corr = float(np.corrcoef(d["Inflation"], d["jst_inflation"])[0, 1])
    return (f"CPI diagnostic {int(d['Year'].min())}-{int(d['Year'].max())}: "
            f"Shiller-JST mean diff {diff.mean():+.4f}, std {diff.std():.4f}, "
            f"max |diff| {diff.abs().max():.4f}, corr {corr:.4f}")


def housing_index_real_vol(panel: pd.DataFrame, start_year: int) -> float:
    sub = panel[panel["Year"] >= start_year]
    r = (1.0 + sub["housing"].to_numpy()) / (1.0 + sub["Inflation"].to_numpy()) - 1.0
    return float(np.std(np.clip(r, *REAL_CLIP)))


# ─────────────── bootstrap / scenario builder ───────────────────────────────

def bootstrap_tensor(panel: pd.DataFrame, start_year: int,
                     num_sims: int, seed: int) -> np.ndarray:
    """Single-country block bootstrap of the (assets..., Inflation) panel."""
    sub = panel[panel["Year"] >= start_year]
    data = sub[ASSETS + ["Inflation"]].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    out = np.empty((num_sims, RETIREMENT_YEARS, data.shape[1]))
    for s in range(num_sims):
        out[s] = block_bootstrap_np(data, len(data), RETIREMENT_YEARS,
                                    MIN_BLOCK, MAX_BLOCK, rng)
    return out


def make_scenario_builder(tensor: np.ndarray, sigma_real: float, noise_seed: int):
    """Precompute shared pieces; return f(weights) -> real returns (S,H).

    Same construction as the pooled 5-asset study: portfolio nominal return net
    of per-asset expense, deflated once; the individual-vs-index housing delta
    (idiosyncratic real-space noise, floored at -100%) is added weighted by
    w_housing. w_housing=0 rows are exactly the financial-assets-only model.
    """
    nominal_assets = tensor[:, :, :N_ASSETS]
    one_plus_infl = 1.0 + tensor[:, :, IDX_INFL]
    rng = np.random.default_rng(noise_seed)
    noise_unit = rng.standard_normal(tensor.shape[:2])
    e_h = EXPENSE_VEC[HOUSING_IDX]
    hr_index = (1.0 + nominal_assets[:, :, HOUSING_IDX] - e_h) / one_plus_infl - 1.0
    hr_indiv = np.maximum(hr_index + sigma_real * noise_unit, -1.0)
    delta_h = hr_indiv - hr_index

    def build(w: np.ndarray) -> np.ndarray:
        nom_port = nominal_assets @ w - float(w @ EXPENSE_VEC)
        real = (1.0 + nom_port) / one_plus_infl - 1.0
        return real + w[HOUSING_IDX] * delta_h

    return build


# ─────────────── per-allocation metrics ─────────────────────────────────────

def alloc_metrics(real_returns: np.ndarray) -> dict:
    rate_grid, table = build_success_rate_table(real_returns)
    _, init_wd, traj, wds, _ = run_guardrail_simulation(
        scenarios=real_returns,
        target_success=GR_TARGET,
        upper_guardrail=GR_UPPER,
        lower_guardrail=GR_LOWER,
        adjustment_pct=GR_ADJ,
        retirement_years=RETIREMENT_YEARS,
        min_remaining_years=GR_MIN_REMAIN,
        table=table, rate_grid=rate_grid,
        adjustment_mode=GR_MODE,
        initial_portfolio=INITIAL_PORTFOLIO,
    )
    cew = compute_cew(wds)
    fr_paths = per_path_funded_ratio(traj, RETIREMENT_YEARS)
    min_wd = np.min(wds, axis=1)
    eff_fr, _ = compute_effective_funded_ratio(
        wds, init_wd, RETIREMENT_YEARS,
        consumption_floor=CONSUMPTION_FLOOR, trajectories=traj,
    )
    return {
        "init_swr": init_wd / INITIAL_PORTFOLIO,
        "success_rate": compute_success_rate(traj, RETIREMENT_YEARS),
        "severe_fail_prob": float(np.mean(fr_paths < 0.5)),
        "median_cew": float(np.median(cew)),
        "p10_cew": float(np.percentile(cew, 10)),
        "median_ulcer": float(np.median(consumption_ulcer(wds))),
        "eff_funded_ratio": eff_fr,
        "p10_min_wd": float(np.percentile(min_wd, 10)),
        "median_final": float(np.median(traj[:, -1])),
    }


def gen_allocations() -> np.ndarray:
    n = int(round(1.0 / STEP))
    return np.array(compositions(N_ASSETS, n), dtype=float) * STEP


def tag(w: np.ndarray) -> str:
    return "/".join(f"{int(round(x*100)):02d}" for x in w)


def universe_mask(df: pd.DataFrame, universe: str) -> pd.Series:
    h0 = df["housing"] == 0
    g0 = df["gold"] == 0
    return {"base": h0 & g0, "add_gold": h0, "add_housing": g0,
            "add_both": pd.Series(True, index=df.index)}[universe]


# ─────────────── phases ─────────────────────────────────────────────────────

def run_phase1(panel: pd.DataFrame, sigmas: dict[int, float]) -> pd.DataFrame:
    allocs = gen_allocations()
    rows: list[dict] = []
    for start_year in START_YEARS:
        n_src = int((panel["Year"] >= start_year).sum())
        print(f"[phase1] start={start_year} (n={n_src}y), grid {len(allocs)} "
              f"combos, {NUM_SIMS} sims, seed={SEED}, "
              f"sigma_idio={sigmas[start_year]:.4f}")
        tensor = bootstrap_tensor(panel, start_year, NUM_SIMS, SEED)
        build = make_scenario_builder(tensor, sigmas[start_year],
                                      noise_seed=SEED * 7 + 1234)
        t0 = time.time()
        for i, w in enumerate(allocs):
            m = alloc_metrics(build(w))
            rows.append({"start_year": start_year, "alloc": tag(w), "seed": SEED,
                         **{a: round(w[j], 4) for j, a in enumerate(ASSETS)},
                         **m})
            if (i + 1) % 200 == 0:
                print(f"  {i+1}/{len(allocs)}  ({time.time()-t0:.0f}s)")
        print(f"[phase1] start={start_year} done {time.time()-t0:.0f}s")
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "cew_us_multi_results.csv", index=False)
    print(f"Wrote {OUTPUT_DIR / 'cew_us_multi_results.csv'} ({len(df)} rows)")
    return df


def feasible_of(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df.success_rate >= SR_FLOOR)
              & (df.severe_fail_prob <= SEVERE_FAIL_MAX)]


def pick_candidates(df1900: pd.DataFrame) -> pd.DataFrame:
    """Per universe: top-K by CEW + top tail by p10_cew among feasible."""
    picks = []
    for u in UNIVERSES:
        feas = feasible_of(df1900[universe_mask(df1900, u)])
        if feas.empty:
            continue
        picks.append(feas.sort_values("median_cew", ascending=False)
                     .head(TOP_K_CONFIRM))
        picks.append(feas.sort_values("p10_cew", ascending=False)
                     .head(TOP_TAIL_CONFIRM))
    return pd.concat(picks).drop_duplicates(subset="alloc")


def run_phase2(panel: pd.DataFrame, sigma: float, df: pd.DataFrame) -> pd.DataFrame:
    df1900 = df[df.start_year == PRIMARY_START]
    cand = pick_candidates(df1900)
    weights = cand[ASSETS].to_numpy(dtype=float)
    tags = cand["alloc"].tolist()
    print(f"\n[phase2] {len(tags)} candidates across seeds {CONFIRM_SEEDS}: {tags}")
    rows = df1900[df1900.alloc.isin(tags)].to_dict("records")
    for seed in CONFIRM_SEEDS:
        tensor = bootstrap_tensor(panel, PRIMARY_START, NUM_SIMS, seed)
        build = make_scenario_builder(tensor, sigma, noise_seed=seed * 7 + 1234)
        for w, t in zip(weights, tags):
            m = alloc_metrics(build(w))
            rows.append({"start_year": PRIMARY_START, "alloc": t, "seed": seed,
                         **{a: round(w[j], 4) for j, a in enumerate(ASSETS)},
                         **m})
    ms = pd.DataFrame(rows)
    ms.to_csv(OUTPUT_DIR / "cew_us_multi_multiseed.csv", index=False)
    n_seeds = 1 + len(CONFIRM_SEEDS)
    agg = ms.groupby("alloc").agg(
        sr_mean=("success_rate", "mean"),
        sr_min=("success_rate", "min"),
        seeds_sr_ok=("success_rate", lambda s: int((s >= SR_FLOOR).sum())),
        seeds_tail_ok=("severe_fail_prob",
                       lambda s: int((s <= SEVERE_FAIL_MAX).sum())),
        severe_mean=("severe_fail_prob", "mean"),
        severe_max=("severe_fail_prob", "max"),
        cew_mean=("median_cew", "mean"),
        cew_min=("median_cew", "min"),
        p10cew_mean=("p10_cew", "mean"),
        ulcer_mean=("median_ulcer", "mean"),
        swr_mean=("init_swr", "mean"),
        p10wd_mean=("p10_min_wd", "mean"),
    ).sort_values("cew_mean", ascending=False)
    agg["robust"] = (agg.seeds_sr_ok == n_seeds) & (agg.seeds_tail_ok == n_seeds)
    print(f"\n[phase2] cross-seed aggregation (n_seeds={n_seeds}):")
    print(agg.to_string(formatters={
        "cew_mean": "{:,.0f}".format, "cew_min": "{:,.0f}".format,
        "p10cew_mean": "{:,.0f}".format, "p10wd_mean": "{:,.0f}".format,
        "swr_mean": "{:.3%}".format}))
    return agg


def run_phase3(panel: pd.DataFrame, sigmas: dict[int, float],
               df: pd.DataFrame, agg: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for start_year in HIGHN_STARTS:
        sub = df[df.start_year == start_year]
        finalists: list[str] = []
        for u in UNIVERSES:
            feas = feasible_of(sub[universe_mask(sub, u)]).sort_values(
                ["median_cew", "median_ulcer"], ascending=[False, True])
            if start_year == PRIMARY_START and agg is not None:
                robust = agg[agg.robust].index
                feas = feas[feas.alloc.isin(robust)]
            for t in feas.alloc.head(2):
                if t not in finalists:
                    finalists.append(t)
        if not finalists:
            print(f"[phase3] start={start_year}: no finalists")
            continue
        print(f"\n[phase3] start={start_year}, N={HIGHN_SIMS}, "
              f"seed={HIGHN_SEED}: {finalists}")
        tensor = bootstrap_tensor(panel, start_year, HIGHN_SIMS, HIGHN_SEED)
        build = make_scenario_builder(tensor, sigmas[start_year],
                                      noise_seed=HIGHN_SEED * 7 + 1234)
        lookup = sub.set_index("alloc")
        for t in finalists:
            w = lookup.loc[t, ASSETS].to_numpy(dtype=float)
            m = alloc_metrics(build(w))
            rows.append({"start_year": start_year, "alloc": t,
                         "seed": HIGHN_SEED, "num_sims": HIGHN_SIMS,
                         **{a: round(w[j], 4) for j, a in enumerate(ASSETS)},
                         **m})
            print(f"  {t}  success={m['success_rate']:.4f} "
                  f"severe={m['severe_fail_prob']:.4f} "
                  f"CEW={m['median_cew']:,.0f} p10CEW={m['p10_cew']:,.0f} "
                  f"SWR={m['init_swr']:.3%}")
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT_DIR / "cew_us_multi_confirm10k.csv", index=False)
    return out


# ─────────────── summary ─────────────────────────────────────────────────────

def write_summary(df: pd.DataFrame, sigmas: dict[int, float],
                  cpi_note: str) -> None:
    lines: list[str] = []
    add = lines.append
    add("# CEW-Primary Allocation — US dataset + gold + US real estate (2026-06-11)")
    add("")
    add(f"Data: FIRE_dataset_intl + JST-USA Housing_TR + USD gold; "
        f"single-country bootstrap, {RETIREMENT_YEARS}y, {NUM_SIMS} sims, "
        f"seed={SEED} (shared per start year)")
    add(f"Housing: individual property — {HOUSING_EXPENSE:.1%}/yr maintenance, "
        f"vol {VOL_MULT}x index (idio sigma per window: "
        + ", ".join(f"{y}: {s:.4f}" for y, s in sigmas.items()) + ")")
    add(f"Guardrail F: target={GR_TARGET}/lower={GR_LOWER}, upper={GR_UPPER}, "
        f"adj={GR_ADJ}, {GR_MODE}, mr={GR_MIN_REMAIN}")
    add(f"Objective: max median CEW s.t. success >= {SR_FLOOR}, "
        f"P(FR<0.5) <= {SEVERE_FAIL_MAX}; tie-break Ulcer")
    add(f"{cpi_note}")
    add("")
    add("Alloc key: US stock / Intl stock / US bond / Housing / Gold")
    add("")

    add("## Universe comparison (best feasible median CEW)")
    add("")
    add("| start | universe | best alloc | median_CEW | p10_CEW | success | "
        "severe | init_SWR |")
    add("|---|---|---|---|---|---|---|---|")
    for start_year in START_YEARS:
        sub = df[df.start_year == start_year]
        for u in UNIVERSES:
            feas = feasible_of(sub[universe_mask(sub, u)]).sort_values(
                ["median_cew", "median_ulcer"], ascending=[False, True])
            if feas.empty:
                add(f"| {start_year} | {u} | (none feasible) | | | | | |")
                continue
            r = feas.iloc[0]
            add(f"| {start_year} | {u} | {r['alloc']} | ${r['median_cew']:,.0f} | "
                f"${r['p10_cew']:,.0f} | {r['success_rate']:.3f} | "
                f"{r['severe_fail_prob']:.3f} | {r['init_swr']:.2%} |")
    add("")

    for start_year in START_YEARS:
        sub = df[df.start_year == start_year]
        add(f"# start_year = {start_year}")
        add("")
        for u in UNIVERSES:
            usub = sub[universe_mask(sub, u)]
            feas = feasible_of(usub).sort_values(
                ["median_cew", "median_ulcer"], ascending=[False, True])
            add(f"## {u} ({len(feas)}/{len(usub)} feasible)")
            add("")
            if feas.empty:
                relaxed = usub.sort_values("success_rate", ascending=False).head(3)
                add("**No feasible allocation.** Closest by success_rate:")
                add("")
                add("| Alloc | success | severe | median_CEW | init_SWR |")
                add("|---|---|---|---|---|")
                for _, r in relaxed.iterrows():
                    add(f"| {r['alloc']} | {r['success_rate']:.3f} | "
                        f"{r['severe_fail_prob']:.3f} | ${r['median_cew']:,.0f} | "
                        f"{r['init_swr']:.2%} |")
                add("")
                continue
            best_cew = feas["median_cew"].iloc[0]
            near = feas["median_cew"] >= best_cew * (1 - CEW_NEAR_OPTIMAL)
            add(f"Near-optimal set (within {CEW_NEAR_OPTIMAL:.0%}): {int(near.sum())}")
            add("")
            add("| Alloc (US/In/Bd/Ho/Au) | median_CEW | p10_CEW | Ulcer | "
                "success | severe | init_SWR | P10_min_wd | near |")
            add("|---|---|---|---|---|---|---|---|---|")
            for (_, r), nflag in zip(feas.head(10).iterrows(), near.head(10)):
                add(f"| {r['alloc']} | ${r['median_cew']:,.0f} | "
                    f"${r['p10_cew']:,.0f} | {r['median_ulcer']:.4f} | "
                    f"{r['success_rate']:.3f} | {r['severe_fail_prob']:.3f} | "
                    f"{r['init_swr']:.2%} | ${r['p10_min_wd']:,.0f} | "
                    f"{'Y' if nflag else ''} |")
            add("")

    text = "\n".join(lines)
    (OUTPUT_DIR / "cew_us_multi_summary.md").write_text(text)
    print(f"\nWrote {OUTPUT_DIR / 'cew_us_multi_summary.md'}")


def main() -> None:
    panel = load_panel()
    print(f"Panel {int(panel['Year'].min())}-{int(panel['Year'].max())} "
          f"({len(panel)} years)")
    cpi_note = cpi_diagnostic(panel)
    print(cpi_note)
    sigmas = {}
    for y in START_YEARS:
        v_idx = housing_index_real_vol(panel, y)
        sigmas[y] = float(np.sqrt(VOL_MULT**2 - 1.0) * v_idx)
        print(f"start={y}: housing index real vol {v_idx:.4f}, "
              f"idio sigma {sigmas[y]:.4f}")

    df = run_phase1(panel, sigmas)
    write_summary(df, sigmas, cpi_note)
    agg = run_phase2(panel, sigmas[PRIMARY_START], df)
    run_phase3(panel, sigmas, df, agg)


if __name__ == "__main__":
    main()
