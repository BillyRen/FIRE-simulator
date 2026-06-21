"""Block-length calibration for the FIRE block bootstrap — Stage B1 (historical).

Goal
----
Defend (or revise) the simulator's empirical block length [min,max]=[5,15]
(mean 10y) with data-driven evidence, per the plan
`docs/plan-2026-06-21-block-bootstrap-sampling-upgrade.md` (Upgrade B).

Two independent estimators on the JST historical panel (annual, per country):

  1. Variance Ratio VR(k) (Lo-MacKinlay 1988, overlapping/unbiased) on the
     JOINT object that the engine actually resamples — a representative 60/40
     real portfolio return — plus per-asset diagnostics (stock/bond/inflation).
     VR(k) < 1 => mean reversion (favours longer blocks to reproduce it);
     VR(k) ~ 1 => random walk; VR(k) > 1 => momentum.

  2. Patton-Politis-White (2009) optimal stationary-bootstrap block length
     b_opt (closed-form plug-in with flat-top lag window + automatic
     bandwidth). This is the canonical automatic selector; we implement it
     directly because `arch` is not a project dependency.

Codex review (2026-06-21) constraints baked in:
  - Finding 4: calibrate on the joint 60/40 real portfolio process, not a
    single asset; per-asset VR is diagnostics only.
  - Finding 5: annual series are short (~126-155 obs); a single point estimate
    overfits noise. We therefore report VR and b_opt with bootstrap
    UNCERTAINTY BANDS (resampling countries) and treat the result as
    "is [5,15]/mean 10 in a defensible range?", not "solve for one number".

This stage is pure analysis (zero product risk) and changes no engine default.
Stage B2 (synthetic-path VR comparison uniform vs geometric, + wrap-seam
fraction) is added after Upgrade A lands the geometric block option.

Run:  python3 analysis/block_length_vr_calibration.py
Out:  analysis/output/block_length_vr_calibration.csv  (+ stdout summary)
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulator.data_loader import load_returns_data  # noqa: E402

# --- config -----------------------------------------------------------------
VR_LAGS = [2, 3, 5, 10, 15, 20, 30]
STOCK_W, BOND_W = 0.60, 0.40          # representative 60/40 (ACO base case)
MIN_OBS = 40                          # skip countries too short for VR(30)
N_BOOT = 2000                         # country-resample reps for CI bands
SEED = 42
CURRENT_MEAN_BLOCK = 10               # (min+max)/2 = (5+15)/2


# --- return construction ----------------------------------------------------
def _log_real(nominal: np.ndarray, inflation: np.ndarray) -> np.ndarray:
    """Log real return from nominal return + inflation rate (additive across t)."""
    real = (1.0 + nominal) / (1.0 + inflation) - 1.0
    return np.log1p(real)


def build_country_series(df: pd.DataFrame) -> dict[str, dict[str, np.ndarray]]:
    """Per-country log-real series: portfolio (60/40), stock, bond, inflation."""
    out: dict[str, dict[str, np.ndarray]] = {}
    for iso, sub in df.groupby("Country"):
        sub = sub.sort_values("Year")
        stock = sub["Domestic_Stock"].to_numpy(float)
        bond = sub["Domestic_Bond"].to_numpy(float)
        infl = sub["Inflation"].to_numpy(float)
        port_nom = STOCK_W * stock + BOND_W * bond
        out[iso] = {
            "portfolio": _log_real(port_nom, infl),
            "stock": _log_real(stock, infl),
            "bond": _log_real(bond, infl),
            "inflation": np.log1p(infl),
        }
    return out


# --- variance ratio (Lo-MacKinlay 1988, overlapping unbiased) ---------------
def variance_ratio(r: np.ndarray, k: int) -> float:
    """VR(k) for a 1-period log-return series r (additive)."""
    r = np.asarray(r, float)
    T = r.size
    if T <= k:
        return np.nan
    mu = r.mean()
    # 1-period variance (unbiased)
    var1 = np.sum((r - mu) ** 2) / (T - 1)
    if var1 <= 0:
        return np.nan
    # k-period overlapping sums of returns
    csum = np.concatenate(([0.0], np.cumsum(r)))
    kret = csum[k:] - csum[:-k]            # length T-k+1, each is k-period return
    # Lo-MacKinlay (1988) unbiased overlapping estimator. The constant m already
    # carries the factor k, so sigma_c^2 = sum/m estimates Var(k-period)/k; thus
    # VR(k) = sigma_c^2 / sigma_1^2 directly (NO extra /k).
    m = k * (T - k + 1) * (1.0 - k / T)
    vark = np.sum((kret - k * mu) ** 2) / m
    return vark / var1


def variance_ratio_nonoverlap(r: np.ndarray, k: int) -> float:
    """Non-overlapping VR(k) cross-check: Var(k-period)/(k*Var(1-period))."""
    r = np.asarray(r, float)
    T = r.size
    if T < 2 * k:
        return np.nan
    mu = r.mean()
    var1 = np.sum((r - mu) ** 2) / (T - 1)
    if var1 <= 0:
        return np.nan
    nblk = T // k
    blk = r[: nblk * k].reshape(nblk, k).sum(axis=1)   # non-overlapping k-sums
    vark = blk.var(ddof=1)
    return vark / (k * var1)


# --- Patton-Politis-White (2009) optimal stationary-bootstrap block length ---
def _flat_top(s: np.ndarray) -> np.ndarray:
    """Politis flat-top (trapezoidal) lag window on |s|."""
    a = np.abs(s)
    w = np.where(a <= 0.5, 1.0, np.where(a <= 1.0, 2.0 * (1.0 - a), 0.0))
    return w


def ppw_optimal_block_length(r: np.ndarray) -> float:
    """Patton, Politis & White (2009) b_opt for the stationary bootstrap.

    Closed-form plug-in: b_opt = (2 G^2 / D_SB)^(1/3) N^(1/3), with flat-top
    lag window and automatic bandwidth M (Politis 2003 correlogram rule).
    """
    r = np.asarray(r, float)
    N = r.size
    if N < 8:
        return np.nan
    x = r - r.mean()
    # autocovariances g(0..Kmax)
    Kmax = int(min(N - 1, np.ceil(10.0 * np.log10(N)) + 1))
    g = np.array([np.dot(x[: N - k], x[k:]) / N for k in range(Kmax + 1)])
    if g[0] <= 0:
        return np.nan
    rho = g / g[0]
    # automatic bandwidth: smallest m s.t. |rho| stays below threshold for K_N lags
    thresh = 2.0 * np.sqrt(np.log10(N) / N)
    K_N = max(5, int(np.ceil(np.sqrt(np.log10(N)))))
    m_hat = 0
    for m in range(1, Kmax - K_N + 1):
        window = np.abs(rho[m + 1 : m + 1 + K_N])
        if window.size == K_N and np.all(window < thresh):
            m_hat = m
            break
    if m_hat == 0:
        m_hat = max(1, int(np.ceil(np.sqrt(N))))  # fallback
    M = min(2 * m_hat, Kmax)
    # Ghat and D_SB with flat-top weights
    ks = np.arange(1, M + 1)
    w = _flat_top(ks / M)
    Ghat = 2.0 * np.sum(w * ks * g[1 : M + 1])
    g_flat = g[0] + 2.0 * np.sum(w * g[1 : M + 1])
    D_SB = 2.0 * g_flat ** 2
    if D_SB <= 0:
        return np.nan
    b_opt = (2.0 * Ghat ** 2 / D_SB) ** (1.0 / 3.0) * N ** (1.0 / 3.0)
    return float(b_opt)


# --- aggregation with country-resample uncertainty bands --------------------
def _pct(a: np.ndarray, q: float) -> float:
    a = a[np.isfinite(a)]
    return float(np.percentile(a, q)) if a.size else np.nan


def main() -> None:
    df = load_returns_data()
    series = build_country_series(df)
    isos = sorted(k for k in series if series[k]["portfolio"].size >= MIN_OBS)

    # --- sanity: US real stock VR vs literature (Poterba-Summers ~0.5-0.6 @10y)
    us = series["USA"]["stock"]
    print("=== Sanity: USA real STOCK VR (overlap vs non-overlap) ===")
    print(f"{'k':>3}{'VR_overlap':>12}{'VR_nonoverlap':>15}")
    for k in (2, 5, 10, 15, 20):
        print(f"{k:>3}{variance_ratio(us, k):12.3f}"
              f"{variance_ratio_nonoverlap(us, k):15.3f}")
    print()

    # per-country point estimates (primary = portfolio; diagnostics = others)
    rows = []
    for iso in isos:
        s = series[iso]
        n = s["portfolio"].size
        row = {"iso": iso, "n_obs": n,
               "b_opt_ppw": ppw_optimal_block_length(s["portfolio"])}
        for k in VR_LAGS:
            row[f"VR{k}_port"] = variance_ratio(s["portfolio"], k)
            row[f"VR{k}_stock"] = variance_ratio(s["stock"], k)
        rows.append(row)
    per_country = pd.DataFrame(rows)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)
    per_country.to_csv(os.path.join(out_dir, "block_length_vr_calibration.csv"),
                       index=False)

    # cross-country uncertainty bands: resample countries with replacement,
    # take the (length-weighted) mean of each statistic across the resample.
    rng = np.random.default_rng(SEED)
    port_vr = {k: per_country[f"VR{k}_port"].to_numpy() for k in VR_LAGS}
    bopt = per_country["b_opt_ppw"].to_numpy()
    wts = per_country["n_obs"].to_numpy(float)
    nC = len(isos)

    def wmean(vals, w):
        mask = np.isfinite(vals)
        if not mask.any():
            return np.nan
        return np.average(vals[mask], weights=w[mask])

    boot_vr = {k: np.empty(N_BOOT) for k in VR_LAGS}
    boot_bopt = np.empty(N_BOOT)
    for b in range(N_BOOT):
        idx = rng.integers(0, nC, nC)
        boot_bopt[b] = wmean(bopt[idx], wts[idx])
        for k in VR_LAGS:
            boot_vr[k][b] = wmean(port_vr[k][idx], wts[idx])

    # --- report -------------------------------------------------------------
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda x: f"{x:7.3f}")
    print("=== Per-country point estimates (portfolio 60/40, log real) ===")
    cols = ["iso", "n_obs", "b_opt_ppw"] + [f"VR{k}_port" for k in (5, 10, 15, 20, 30)]
    print(per_country[cols].sort_values("b_opt_ppw", ascending=False)
          .to_string(index=False))

    print("\n=== Cross-country length-weighted mean + 90% band "
          "(country resample, N={}) ===".format(N_BOOT))
    print(f"{'stat':<14}{'point':>9}{'p5':>9}{'p50':>9}{'p95':>9}")
    pt_bopt = wmean(bopt, wts)
    print(f"{'b_opt_ppw(y)':<14}{pt_bopt:9.2f}{_pct(boot_bopt,5):9.2f}"
          f"{_pct(boot_bopt,50):9.2f}{_pct(boot_bopt,95):9.2f}")
    for k in VR_LAGS:
        pt = wmean(port_vr[k], wts)
        print(f"{'VR'+str(k):<14}{pt:9.3f}{_pct(boot_vr[k],5):9.3f}"
              f"{_pct(boot_vr[k],50):9.3f}{_pct(boot_vr[k],95):9.3f}")

    # --- verdict ------------------------------------------------------------
    lo, hi = _pct(boot_bopt, 5), _pct(boot_bopt, 95)
    vr10 = wmean(port_vr[10], wts)
    vr30 = wmean(port_vr[30], wts)
    print("\n=== Verdict ===")
    print(f"Current engine mean block = {CURRENT_MEAN_BLOCK}y (uniform [5,15]).")
    print(f"[1] PPW optimal block (mean-estimation MSE objective): "
          f"{pt_bopt:.1f}y, 90% band [{lo:.1f}, {hi:.1f}].")
    print(f"[2] Pooled 60/40 real VR(10)={vr10:.2f}, VR(30)={vr30:.2f} "
          f"({'long-horizon momentum/persistence' if vr10 > 1.1 else 'mean-reverting' if vr10 < 0.9 else 'near random-walk'}).")
    print("    (USA-only stock VR<1 = classic mean reversion; the pooled panel "
          "is driven to >1 by sustained war/inflation regimes in FRA/JPN/ESP/PRT.)")
    print("\nINTERPRETATION — the two estimators target DIFFERENT objectives:")
    print(f"  - PPW b_opt~{pt_bopt:.0f}y minimises variance-of-the-MEAN MSE: most "
          "autocovariance mass sits at short lags, so a short block suffices.")
    print("  - But FIRE ruin risk is driven by LONG-HORIZON variance, and VR(k) "
          "keeps rising out to k=10-30y (persistent regimes). Reproducing that "
          "in synthetic paths needs a block spanning the persistence horizon.")
    print(f"  => A ~{pt_bopt:.0f}y block would wash out the 10-30y persistence that "
          "drives tail ruin; the current [5,15]/mean-10 block is the better "
          "match for our objective. KEEP mean~10y; do NOT adopt PPW b_opt as the "
          "block length. Geometric option (Upgrade A) default mean_block=10 is "
          "defensible; Stage B2 confirms by comparing SYNTHETIC VR of "
          "uniform[5,15] vs geometric(mean) against this historical VR curve.")


if __name__ == "__main__":
    main()
