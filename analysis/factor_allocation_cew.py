"""Factor-tilt allocation study (2026-06-13).

Question
--------
On the product's three financial assets (US stock, Intl stock, US bond from
FIRE_dataset_intl), what is the optimal long-horizon allocation when adding
US SMALL VALUE and MOMENTUM, and what do assets 4-5 contribute to FIRE success
NET of their higher costs?

Mirrors optimal_allocation_cew_us_multi.py but with factor sleeves instead of
gold/housing (factors are pure index returns -> NO idiosyncratic noise).

Assets / costs (user spec; data is gross, costs modeled as per-asset expense):
  us_stock / intl_stock / us_bond : 0.5%   (broad index base)
  small_value (FF 2x3 SMALL HiBM) : 0.8%   (+0.3%, AVUV/DFSV-level)
  momentum    (FF 2x3 BIG HiPRIOR): 1.0%   (+0.5%, high-turnover drag)
GROSS run = all assets at 0.5% (no incremental factor cost) -> isolates drag.

Window 1927-2025 (forced by FF factor start; cannot extrapolate to 1900).
Deflation = FIRE_dataset_intl US Inflation (Shiller CPI), product convention
real=(1+nom_net)/(1+infl)-1.

Strategies (user: both):
  A. Guardrail tier F (target=0.85/lower=0.75) -> max median CEW s.t.
     success>=0.90, P(FR<0.5)<=0.01; tie-break consumption Ulcer. (optimal cfg)
  B. Fixed withdrawal via run_fixed_baseline -> SWR@90% success + success@{3.5,
     4.0,4.5}%, evaluated with compute_success_rate (last-year depletion=success;
     NOT build_success_rate_table's stricter values>0). (success contribution)

Codex review round 1 (all adopted): calendar-alignment diagnostic; SWR uses
compute_success_rate convention; report unconstrained AND sleeve-capped optima
(sv<=40%, mom<=20%); ~99-obs small-sample / window-sensitivity caveats.

Outputs: analysis/output/factor_allocation/{guardrail_grid,fixed_grid,
multiseed,confirm10k}.csv + console summary.
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
from simulator.guardrail import (
    build_success_rate_table, run_guardrail_simulation, run_fixed_baseline,
)
from simulator.statistics import compute_effective_funded_ratio, compute_success_rate

from multi_asset_allocation import compositions
from optimal_allocation_cew import (
    INITIAL_PORTFOLIO, NUM_SIMS, MIN_BLOCK, MAX_BLOCK, SEED, CONSUMPTION_FLOOR,
    GR_UPPER, GR_ADJ, GR_MODE, GR_MIN_REMAIN, SR_FLOOR, SEVERE_FAIL_MAX,
    CEW_NEAR_OPTIMAL, compute_cew, per_path_funded_ratio, consumption_ulcer,
)

# ─────────────── parameters ─────────────────────────────────────────────────
ASSETS = ["us_stock", "intl_stock", "us_bond", "small_value", "momentum"]
N_ASSETS = len(ASSETS)
IDX_SV, IDX_MOM = ASSETS.index("small_value"), ASSETS.index("momentum")
IDX_INFL = N_ASSETS
STEP = 0.10

NET_EXPENSE = np.array([0.005, 0.005, 0.005, 0.008, 0.010])
GROSS_EXPENSE = np.full(N_ASSETS, 0.005)

GR_TARGET, GR_LOWER = 0.85, 0.75

PRIMARY_START, PRIMARY_HORIZON = 1927, 65
GRID_CELLS = [(1927, 65), (1927, 50), (1970, 65)]   # (start_year, horizon)
FIXED_RATES = [0.030, 0.035, 0.040, 0.045, 0.050, 0.055]
SWR_SCAN = np.round(np.arange(0.025, 0.0701, 0.0025), 4)

SV_CAP, MOM_CAP = 0.40, 0.20      # realistic per-sleeve caps (Codex r1)

CONFIRM_SEEDS = [SEED + k for k in (5000, 10000, 15000, 20000)]   # spacing>=NUM_SIMS
HIGHN_SIMS, HIGHN_SEED = 10_000, 777_000
TOP_K = 6

OUTPUT_DIR = ROOT / "analysis" / "output" / "factor_allocation"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────── data ───────────────────────────────────────────────────────

def load_panel() -> pd.DataFrame:
    fire = pd.read_csv(ROOT / "data" / "FIRE_dataset_intl.csv").rename(columns={
        "US Stock": "us_stock", "International Stock": "intl_stock",
        "US Bond": "us_bond", "US Inflation": "Inflation"})
    sv = pd.read_csv(ROOT / "data" / "factors" / "annual_nominal"
                     / "us_size_value_2x3.csv")[["Year", "SMALL HiBM"]].rename(
        columns={"SMALL HiBM": "small_value"})
    mom = pd.read_csv(ROOT / "data" / "factors" / "annual_nominal"
                      / "us_size_momentum_2x3.csv")[["Year", "BIG HiPRIOR"]].rename(
        columns={"BIG HiPRIOR": "momentum"})
    df = (fire.merge(sv, on="Year").merge(mom, on="Year")
          .dropna(subset=ASSETS + ["Inflation"]).reset_index(drop=True))
    assert (df["Year"].diff().iloc[1:] == 1).all(), "year gaps in merged panel"
    return df


def alignment_diagnostic(panel: pd.DataFrame) -> str:
    """Codex r1 #6: prove FF calendar == FIRE calendar. Off-by-one would
    collapse same-year cross-asset correlation. FF-reconstructed market vs FIRE
    US Stock corr (≈0.9988 in session validation) + in-panel US-equity corrs."""
    head = pd.read_csv(ROOT / "data" / "factors" / "headline_nominal_us.csv"
                       )[["Year", "mkt"]]
    m = panel.merge(head, on="Year")
    c_mkt = float(np.corrcoef(m["mkt"], m["us_stock"])[0, 1])
    c_sv = float(np.corrcoef(panel["small_value"], panel["us_stock"])[0, 1])
    c_mom = float(np.corrcoef(panel["momentum"], panel["us_stock"])[0, 1])
    assert c_mkt >= 0.99, f"calendar misalignment? corr(FF mkt,FIRE)={c_mkt:.4f}"
    assert c_sv >= 0.75, f"SV alignment suspect: corr(SV,US)={c_sv:.4f}"
    return (f"alignment {int(panel.Year.min())}-{int(panel.Year.max())}: "
            f"corr(FF mkt, FIRE US)={c_mkt:.4f}  corr(SV,US)={c_sv:.4f}  "
            f"corr(MOM,US)={c_mom:.4f}")


def asset_stats(panel: pd.DataFrame, start: int) -> pd.DataFrame:
    sub = panel[panel["Year"] >= start]
    infl = sub["Inflation"].to_numpy()
    rows = {}
    for a in ASSETS:
        real = (1 + sub[a].to_numpy()) / (1 + infl) - 1
        cagr = np.prod(1 + real) ** (1 / len(real)) - 1
        rows[a] = {"real_cagr": cagr, "real_vol": float(np.std(real, ddof=1)),
                   "nom_cagr": np.prod(1 + sub[a].to_numpy()) ** (1/len(sub)) - 1}
    return pd.DataFrame(rows).T


# ─────────────── bootstrap + scenario ───────────────────────────────────────

def bootstrap_tensor(panel: pd.DataFrame, start: int, horizon: int,
                     num_sims: int, seed: int) -> np.ndarray:
    data = panel[panel["Year"] >= start][ASSETS + ["Inflation"]].to_numpy(float)
    rng = np.random.default_rng(seed)
    out = np.empty((num_sims, horizon, data.shape[1]))
    for s in range(num_sims):
        out[s] = block_bootstrap_np(data, len(data), horizon,
                                    MIN_BLOCK, MAX_BLOCK, rng)
    return out


def real_returns(tensor: np.ndarray, w: np.ndarray, expense: np.ndarray) -> np.ndarray:
    nominal = tensor[:, :, :N_ASSETS]
    one_plus_infl = 1.0 + tensor[:, :, IDX_INFL]
    nom_port = nominal @ w - float(w @ expense)
    return (1.0 + nom_port) / one_plus_infl - 1.0


def gen_allocations() -> np.ndarray:
    n = int(round(1.0 / STEP))
    return np.array(compositions(N_ASSETS, n), dtype=float) * STEP


def tag(w: np.ndarray) -> str:
    return "/".join(f"{int(round(x*100)):02d}" for x in w)


def universe_of(w: np.ndarray) -> str:
    sv, mom = w[IDX_SV] > 0, w[IDX_MOM] > 0
    return {(False, False): "base", (True, False): "+SV",
            (False, True): "+Mom", (True, True): "+SV+Mom"}[(sv, mom)]


# ─────────────── metrics ─────────────────────────────────────────────────────

def guardrail_metrics(rr: np.ndarray, horizon: int) -> dict:
    rate_grid, table = build_success_rate_table(rr)
    _, init_wd, traj, wds = run_guardrail_simulation(
        scenarios=rr, target_success=GR_TARGET, upper_guardrail=GR_UPPER,
        lower_guardrail=GR_LOWER, adjustment_pct=GR_ADJ, retirement_years=horizon,
        min_remaining_years=GR_MIN_REMAIN, table=table, rate_grid=rate_grid,
        adjustment_mode=GR_MODE, initial_portfolio=INITIAL_PORTFOLIO)
    cew = compute_cew(wds)
    fr = per_path_funded_ratio(traj, horizon)
    eff_fr, _ = compute_effective_funded_ratio(
        wds, init_wd, horizon, consumption_floor=CONSUMPTION_FLOOR, trajectories=traj)
    return {
        "init_swr": init_wd / INITIAL_PORTFOLIO,
        "success_rate": compute_success_rate(traj, horizon),
        "severe_fail_prob": float(np.mean(fr < 0.5)),
        "median_cew": float(np.median(cew)),
        "p10_cew": float(np.percentile(cew, 10)),
        "median_ulcer": float(np.median(consumption_ulcer(wds))),
        "eff_funded_ratio": eff_fr,
        "p10_min_wd": float(np.percentile(np.min(wds, axis=1), 10)),
    }


def fixed_metrics(rr: np.ndarray, horizon: int) -> dict:
    """SWR@90% (compute_success_rate convention) + success at fixed rates."""
    succ = {}
    for r in SWR_SCAN:
        traj, _ = run_fixed_baseline(rr, INITIAL_PORTFOLIO, float(r), horizon)
        succ[r] = compute_success_rate(traj, horizon)
    # highest rate meeting SR_FLOOR, linearly interpolated between brackets
    rates = list(SWR_SCAN)
    swr = 0.0
    for i in range(len(rates) - 1):
        s0, s1 = succ[rates[i]], succ[rates[i + 1]]
        if s0 >= SR_FLOOR > s1:
            frac = (s0 - SR_FLOOR) / (s0 - s1) if s0 != s1 else 0.0
            swr = rates[i] + frac * (rates[i + 1] - rates[i])
    if succ[rates[-1]] >= SR_FLOOR:
        swr = rates[-1]
    out = {"swr_at_90": swr}
    for r in FIXED_RATES:
        traj, _ = run_fixed_baseline(rr, INITIAL_PORTFOLIO, float(r), horizon)
        out[f"success_at_{int(r*1000)}"] = compute_success_rate(traj, horizon)
    return out


# ─────────────── phases ──────────────────────────────────────────────────────

def run_guardrail_grid(panel: pd.DataFrame) -> pd.DataFrame:
    allocs = gen_allocations()
    rows = []
    for (start, horizon) in GRID_CELLS:
        runs = [("net", NET_EXPENSE)]
        if (start, horizon) == (PRIMARY_START, PRIMARY_HORIZON):
            runs.append(("gross", GROSS_EXPENSE))
        tensor = bootstrap_tensor(panel, start, horizon, NUM_SIMS, SEED)
        for cost, exp in runs:
            n_src = int((panel["Year"] >= start).sum())
            print(f"[gr-grid] start={start} h={horizon}y cost={cost} "
                  f"(n={n_src}y, {len(allocs)} allocs, N={NUM_SIMS})")
            t0 = time.time()
            for i, w in enumerate(allocs):
                m = guardrail_metrics(real_returns(tensor, w, exp), horizon)
                rows.append({"start": start, "horizon": horizon, "cost": cost,
                             "alloc": tag(w), "universe": universe_of(w), "seed": SEED,
                             **{a: round(w[j], 4) for j, a in enumerate(ASSETS)}, **m})
                if (i + 1) % 250 == 0:
                    print(f"    {i+1}/{len(allocs)} ({time.time()-t0:.0f}s)")
            print(f"    done {time.time()-t0:.0f}s")
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "guardrail_grid.csv", index=False)
    print(f"wrote guardrail_grid.csv ({len(df)} rows)")
    return df


def run_fixed_grid(panel: pd.DataFrame) -> pd.DataFrame:
    allocs = gen_allocations()
    tensor = bootstrap_tensor(panel, PRIMARY_START, PRIMARY_HORIZON, NUM_SIMS, SEED)
    rows = []
    for cost, exp in (("net", NET_EXPENSE), ("gross", GROSS_EXPENSE)):
        print(f"[fixed-grid] {PRIMARY_START} h={PRIMARY_HORIZON}y cost={cost}")
        t0 = time.time()
        for i, w in enumerate(allocs):
            m = fixed_metrics(real_returns(tensor, w, exp), PRIMARY_HORIZON)
            rows.append({"cost": cost, "alloc": tag(w), "universe": universe_of(w),
                         **{a: round(w[j], 4) for j, a in enumerate(ASSETS)}, **m})
            if (i + 1) % 250 == 0:
                print(f"    {i+1}/{len(allocs)} ({time.time()-t0:.0f}s)")
        print(f"    done {time.time()-t0:.0f}s")
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "fixed_grid.csv", index=False)
    print(f"wrote fixed_grid.csv ({len(df)} rows)")
    return df


def feasible(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df.success_rate >= SR_FLOOR) & (df.severe_fail_prob <= SEVERE_FAIL_MAX)]


def best_per_universe(df: pd.DataFrame, by="median_cew", capped=False) -> pd.DataFrame:
    out = []
    for u in ["base", "+SV", "+Mom", "+SV+Mom"]:
        sub = feasible(df[df.universe == u])
        if capped:
            sub = sub[(sub.small_value <= SV_CAP) & (sub.momentum <= MOM_CAP)]
        if not sub.empty:
            out.append(sub.sort_values(by, ascending=False).iloc[0])
    return pd.DataFrame(out)


def run_multiseed(panel: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    prim = grid[(grid.start == PRIMARY_START) & (grid.horizon == PRIMARY_HORIZON)
                & (grid.cost == "net")]
    cand = feasible(prim).sort_values("median_cew", ascending=False).head(TOP_K)
    # ensure each universe's best is represented
    cand = pd.concat([cand, best_per_universe(prim)]).drop_duplicates(subset="alloc")
    weights = cand[ASSETS].to_numpy(float)
    tags = cand["alloc"].tolist()
    print(f"[multiseed] {len(tags)} candidates x seeds {CONFIRM_SEEDS}")
    rows = prim[prim.alloc.isin(tags)].assign(src="grid").to_dict("records")
    for seed in CONFIRM_SEEDS:
        tensor = bootstrap_tensor(panel, PRIMARY_START, PRIMARY_HORIZON, NUM_SIMS, seed)
        for w, t in zip(weights, tags):
            m = guardrail_metrics(real_returns(tensor, w, NET_EXPENSE), PRIMARY_HORIZON)
            rows.append({"start": PRIMARY_START, "horizon": PRIMARY_HORIZON,
                         "cost": "net", "alloc": t, "universe": universe_of(w),
                         "seed": seed,
                         **{a: round(w[j], 4) for j, a in enumerate(ASSETS)}, **m})
    ms = pd.DataFrame(rows)
    ms.to_csv(OUTPUT_DIR / "multiseed.csv", index=False)
    n_seeds = ms.seed.nunique()
    agg = ms.groupby(["alloc", "universe"]).agg(
        cew_mean=("median_cew", "mean"), cew_min=("median_cew", "min"),
        sr_mean=("success_rate", "mean"), sr_min=("success_rate", "min"),
        severe_max=("severe_fail_prob", "max"), swr_mean=("init_swr", "mean"),
        p10cew_mean=("p10_cew", "mean"),
        seeds_ok=("success_rate", lambda s: int((s >= SR_FLOOR).sum())),
    ).reset_index().sort_values("cew_mean", ascending=False)
    agg["robust"] = (agg.seeds_ok == n_seeds) & (agg.severe_max <= SEVERE_FAIL_MAX)
    print(f"[multiseed] aggregation (n_seeds={n_seeds}):")
    print(agg.to_string(index=False, formatters={
        "cew_mean": "{:,.0f}".format, "cew_min": "{:,.0f}".format,
        "p10cew_mean": "{:,.0f}".format, "swr_mean": "{:.3%}".format,
        "sr_mean": "{:.3f}".format, "sr_min": "{:.3f}".format}))
    return agg


def run_highn(panel: pd.DataFrame, agg: pd.DataFrame) -> pd.DataFrame:
    finalists = agg[agg.robust].sort_values("cew_mean", ascending=False).head(TOP_K)
    if finalists.empty:
        finalists = agg.sort_values("cew_mean", ascending=False).head(TOP_K)
    tensor = bootstrap_tensor(panel, PRIMARY_START, PRIMARY_HORIZON, HIGHN_SIMS, HIGHN_SEED)
    grid = gen_allocations()
    lut = {tag(w): w for w in grid}
    rows = []
    print(f"[highN] N={HIGHN_SIMS} confirm {len(finalists)} finalists")
    for t in finalists.alloc:
        w = lut[t]
        m = guardrail_metrics(real_returns(tensor, w, NET_EXPENSE), PRIMARY_HORIZON)
        rows.append({"alloc": t, "universe": universe_of(w),
                     **{a: round(w[j], 4) for j, a in enumerate(ASSETS)}, **m})
    hn = pd.DataFrame(rows).sort_values("median_cew", ascending=False)
    hn.to_csv(OUTPUT_DIR / "confirm10k.csv", index=False)
    print(hn.to_string(index=False, formatters={
        "median_cew": "{:,.0f}".format, "p10_cew": "{:,.0f}".format,
        "init_swr": "{:.3%}".format, "success_rate": "{:.3f}".format,
        "severe_fail_prob": "{:.4f}".format}))
    return hn


def summarize(panel, grid, fixedg):
    print("\n" + "=" * 78 + "\nSUMMARY\n" + "=" * 78)
    for start in sorted({c[0] for c in GRID_CELLS}):
        print(f"\n--- asset real stats {start}-2025 ---")
        print(asset_stats(panel, start).to_string(
            formatters={"real_cagr": "{:.2%}".format, "real_vol": "{:.2%}".format,
                        "nom_cagr": "{:.2%}".format}))

    print("\n--- GUARDRAIL: best per universe (CEW), NET, by (start,horizon) ---")
    for (start, horizon) in GRID_CELLS:
        sub = grid[(grid.start == start) & (grid.horizon == horizon) & (grid.cost == "net")]
        print(f"\n[{start} / {horizon}y]  unconstrained:")
        bu = best_per_universe(sub)
        if not bu.empty:
            print(bu[["universe", "alloc", "median_cew", "p10_cew", "init_swr",
                      "success_rate", "severe_fail_prob"]].to_string(
                index=False, formatters={"median_cew": "{:,.0f}".format,
                "p10_cew": "{:,.0f}".format, "init_swr": "{:.2%}".format,
                "success_rate": "{:.3f}".format, "severe_fail_prob": "{:.4f}".format}))
        bc = best_per_universe(sub, capped=True)
        if not bc.empty:
            print(f"[{start} / {horizon}y]  sleeve-capped (SV<={SV_CAP:.0%},MOM<={MOM_CAP:.0%}):")
            print(bc[["universe", "alloc", "median_cew", "init_swr",
                      "success_rate"]].to_string(index=False, formatters={
                "median_cew": "{:,.0f}".format, "init_swr": "{:.2%}".format,
                "success_rate": "{:.3f}".format}))

    print("\n--- COST DRAG: net vs gross best-per-universe CEW (1927/65y) ---")
    for cost in ("net", "gross"):
        sub = grid[(grid.start == PRIMARY_START) & (grid.horizon == PRIMARY_HORIZON)
                   & (grid.cost == cost)]
        bu = best_per_universe(sub)
        print(f"  [{cost}] " + "  ".join(
            f"{r.universe}:{r.median_cew:,.0f}({r.alloc})" for _, r in bu.iterrows()))

    print("\n--- FIXED: best-per-universe SWR@90% + success@4% (1927/65y) ---")
    for cost in ("net", "gross"):
        sub = fixedg[fixedg.cost == cost]
        out = []
        for u in ["base", "+SV", "+Mom", "+SV+Mom"]:
            s = sub[sub.universe == u]
            if not s.empty:
                b = s.sort_values("swr_at_90", ascending=False).iloc[0]
                out.append(f"{u}:SWR={b.swr_at_90:.3%}({b.alloc}),"
                           f"succ@4%={b.success_at_40:.3f}")
        print(f"  [{cost}] " + "  ".join(out))


def main():
    panel = load_panel()
    print(alignment_diagnostic(panel))
    grid = run_guardrail_grid(panel)
    fixedg = run_fixed_grid(panel)
    agg = run_multiseed(panel, grid)
    run_highn(panel, agg)
    summarize(panel, grid, fixedg)
    print("\nDONE.")


if __name__ == "__main__":
    main()
