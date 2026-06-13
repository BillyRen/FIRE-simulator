"""美国 4 资产最优配置（退休覆盖率目标）：REIT vs 房地产，最优组合变化大么？

与 analysis/reit_vs_housing_allocation.py 同设定（资产菜单、窗口 1972-2024、实际收益、
4 个房地产变体 REIT/House_raw/House_desm/House_desm_net），但**目标函数换成产品的
"退休覆盖率"**而非 UPI：

  - 固定实际取款（initial=$1,000,000，年取 rate×initial），年度再平衡
  - 用产品内核 `_simulate_vectorized_fixed_from_matrix` 跑取款路径
  - circular block bootstrap（产品 `block_bootstrap_np`，块长 [5,15]、2000 路径、seed 42，
    四资产同块采样保留相关性）
  - 排序 = Funded Ratio（覆盖率，product best）→ 成功率 → 中位终值（tie-break）
  - 多取款率 sweep（覆盖率在低取款率会饱和到 ~1，无法区分；高取款率才能识别最优）

输出（analysis/output/reit_vs_housing_allocation/）：
  funded_optimal_weights.csv  funded_vol_sensitivity.csv  reit_vs_housing_allocation_funded.png
用法：python analysis/reit_vs_housing_allocation_funded.py
"""
from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, "analysis"))

from simulator.bootstrap import block_bootstrap_np
from simulator.monte_carlo import _simulate_vectorized_fixed_from_matrix

# 复用上一轮的数据加载与网格（保证口径完全一致）
from reit_vs_housing_allocation import (  # noqa: E402
    ASSETS, NA, RE_IDX, Y0, Y1, load_real, grid_weights,
)

OUT_DIR = os.path.join(_BASE, "analysis", "output", "reit_vs_housing_allocation")
os.makedirs(OUT_DIR, exist_ok=True)

INITIAL = 1_000_000.0
NUM_SIMS = 2000
HORIZON = 40
MIN_BLOCK, MAX_BLOCK = 5, 15
SEED = 42
STEP = 5
RATES = [0.035, 0.040, 0.045, 0.050]
RATE_HEADLINE = 0.045
ORDER = ["REIT", "House_raw", "House_desm", "House_desm_net"]


def build_paths(R: np.ndarray, horizon: int, seed: int = SEED) -> np.ndarray:
    """(S, horizon, NA) circular-block-bootstrap 实际收益路径。"""
    rng = np.random.default_rng(seed)
    out = np.empty((NUM_SIMS, horizon, R.shape[1]))
    n = len(R)
    for s in range(NUM_SIMS):
        out[s] = block_bootstrap_np(R, n, horizon, MIN_BLOCK, MAX_BLOCK, rng)
    return out


def eval_grid(paths: np.ndarray, W: np.ndarray, rate: float, horizon: int,
              chunk: int = 120):
    """对每个权重组合返回 (funded, success, median_terminal)。"""
    C = W.shape[0]
    annual_wd = rate * INITIAL
    fund = np.empty(C); succ = np.empty(C); med = np.empty(C)
    for lo in range(0, C, chunk):
        hi = min(lo + chunk, C); Wc = W[lo:hi]; c = hi - lo
        port = np.einsum("sha,ca->csh", paths, Wc)          # (c,S,H)
        traj, _, _, _ = _simulate_vectorized_fixed_from_matrix(
            port.reshape(c * NUM_SIMS, horizon), INITIAL, annual_wd, horizon)
        traj = traj.reshape(c, NUM_SIMS, horizon + 1)
        depleted = traj[:, :, 1:] <= 0
        any_dep = depleted.any(axis=2)
        dep_year = np.where(any_dep, depleted.argmax(axis=2) + 1, horizon)
        fund[lo:hi] = np.minimum(dep_year / horizon, 1.0).mean(axis=1)
        succ[lo:hi] = (dep_year >= horizon).mean(axis=1)
        med[lo:hi] = np.median(traj[:, :, -1], axis=1)
    return fund, succ, med


def best(W, fund, succ, med):
    i = int(np.lexsort((med, succ, fund))[-1])     # primary fund, then succ, then med
    fmax = fund.max()
    at_f = np.isclose(fund, fmax)
    smax = succ[at_f].max()
    tied = at_f & np.isclose(succ, smax)
    return {"w": W[i], "funded": float(fund[i]), "success": float(succ[i]),
            "median": float(med[i]), "n_tied": int(tied.sum())}


def main():
    variants = load_real()
    variants.pop("_phi", None)
    active = [0, 1, 2, 3]
    W = grid_weights(STEP, active)
    Wbase = grid_weights(STEP, [0, 1, 2])

    # 预生成路径（每变体一次，seed 对齐 → 跨变体配对比较）
    paths = {v: build_paths(variants[v], HORIZON) for v in ORDER}
    paths_base = build_paths(variants["REIT"], HORIZON)  # 股债基准（RE 列权重恒为 0）

    rec = []
    opt = {}          # (variant, rate) -> best dict
    for v in ORDER:
        for rate in RATES:
            fund, succ, med = eval_grid(paths[v], W, rate, HORIZON)
            b = best(W, fund, succ, med)
            opt[(v, rate)] = b
            w = b["w"]
            rec.append({"variant": v, "withdrawal_rate": rate,
                        **{ASSETS[i]: round(w[i] * 100, 1) for i in range(NA)},
                        "funded_ratio": round(b["funded"], 4),
                        "success_rate": round(b["success"], 4),
                        "median_terminal": round(b["median"], 0),
                        "n_tied": b["n_tied"]})
    # 基准（仅股债）
    base = {}
    for rate in RATES:
        fb, sb, mb = eval_grid(paths_base, Wbase, rate, HORIZON)
        bb = best(Wbase, fb, sb, mb)
        base[rate] = bb
        w = bb["w"]
        rec.append({"variant": "base_stocks_bonds", "withdrawal_rate": rate,
                    **{ASSETS[i]: round(w[i] * 100, 1) for i in range(NA)},
                    "funded_ratio": round(bb["funded"], 4),
                    "success_rate": round(bb["success"], 4),
                    "median_terminal": round(bb["median"], 0),
                    "n_tied": bb["n_tied"]})
    pd.DataFrame(rec).to_csv(os.path.join(OUT_DIR, "funded_optimal_weights.csv"), index=False)

    # vol 桥接：House_raw 波动放大 → 最优房产权重（@ RATE_HEADLINE）
    raw = variants["House_raw"][:, RE_IDX]; base3 = variants["House_raw"][:, :3]; mu = raw.mean()
    reit_re = opt[("REIT", RATE_HEADLINE)]["w"][RE_IDX]
    sens_rows = []
    for mult in [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0]:
        scaled = mu + mult * (raw - mu)
        R = np.column_stack([base3, scaled])
        p = build_paths(R, HORIZON)
        f, s, m = eval_grid(p, W, RATE_HEADLINE, HORIZON)
        b = best(W, f, s, m)
        sens_rows.append({"vol_mult": mult, "house_real_vol": scaled.std(ddof=1),
                          "opt_RE_weight": b["w"][RE_IDX], "funded_ratio": b["funded"],
                          "reit_opt_RE_weight": reit_re})
    sens = pd.DataFrame(sens_rows)
    sens.round(4).to_csv(os.path.join(OUT_DIR, "funded_vol_sensitivity.csv"), index=False)

    make_figure(opt, base, sens, variants)

    # ───── 控制台 ─────
    pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30)
    print("=" * 96)
    print(f"美国 4 资产最优配置（退休覆盖率目标）  窗口 {Y0}-{Y1}  H={HORIZON}y  initial=$1M  "
          f"bootstrap {NUM_SIMS}×circular block[5,15]")
    print("=" * 96)
    for rate in RATES:
        print(f"\n── 取款率 {rate*100:.1f}%  (年取 ${rate*INITIAL:,.0f}) ──   权重 US/Intl/Bond/RE")
        bb = base[rate]; w = bb["w"]
        print(f"  {'base 股+债':16s} {w[0]*100:4.0f}/{w[1]*100:4.0f}/{w[2]*100:4.0f}/{w[3]*100:4.0f}"
              f"   funded={bb['funded']:.4f} succ={bb['success']:.3f} n_tied={bb['n_tied']}")
        for v in ORDER:
            b = opt[(v, rate)]; w = b["w"]
            print(f"  {v:16s} {w[0]*100:4.0f}/{w[1]*100:4.0f}/{w[2]*100:4.0f}/{w[3]*100:4.0f}"
                  f"   funded={b['funded']:.4f} succ={b['success']:.3f} RE={w[RE_IDX]*100:.0f}% n_tied={b['n_tied']}")

    print(f"\n── vol 桥接 @ 取款率 {RATE_HEADLINE*100:.1f}% ──")
    s = sens.copy(); s["house_real_vol"] = (s["house_real_vol"] * 100).round(1)
    s["opt_RE_weight"] = (s["opt_RE_weight"] * 100).round(0)
    s["reit_opt_RE_weight"] = (s["reit_opt_RE_weight"] * 100).round(0)
    print(s[["vol_mult", "house_real_vol", "opt_RE_weight", "reit_opt_RE_weight", "funded_ratio"]].to_string(index=False))
    print("\n输出目录:", OUT_DIR)


def make_figure(opt, base, sens, variants):
    colors = {"US_Stock": "#1f77b4", "NonUS_Stock": "#17becf", "US_Bond": "#2ca02c", "RealEstate": "#d62728"}
    fig, ax = plt.subplots(2, 2, figsize=(15, 11))
    fig.suptitle(f"US 4-asset optimum by RETIREMENT COVERAGE (funded ratio): REIT vs Housing "
                 f"({Y0}-{Y1}, real, H={HORIZON}y)", fontsize=13, fontweight="bold")

    # (1) optimal weights @ headline rate
    a = ax[0, 0]
    bottoms = np.zeros(len(ORDER))
    for ai, an in enumerate(ASSETS):
        vals = [opt[(v, RATE_HEADLINE)]["w"][ai] * 100 for v in ORDER]
        a.bar(ORDER, vals, bottom=bottoms, label=an, color=colors[an]); bottoms += vals
    a.set_title(f"Funded-ratio optimal weights @ {RATE_HEADLINE*100:.1f}% withdrawal")
    a.set_ylabel("weight (%)"); a.legend(fontsize=8, ncol=2, loc="center left"); a.set_ylim(0, 100)
    for i, v in enumerate(ORDER):
        re = opt[(v, RATE_HEADLINE)]["w"][RE_IDX] * 100
        a.text(i, 100 - re / 2, f"RE\n{re:.0f}%", ha="center", va="center", fontsize=9, color="white", fontweight="bold")

    # (2) optimal RE weight vs withdrawal rate
    a = ax[0, 1]
    for v, c in zip(ORDER, ["#d62728", "#9467bd", "#8c564b", "#e377c2"]):
        a.plot([r * 100 for r in RATES], [opt[(v, r)]["w"][RE_IDX] * 100 for r in RATES], "-o", color=c, label=v)
    a.set_title("Optimal real-estate weight vs withdrawal rate")
    a.set_xlabel("withdrawal rate (%)"); a.set_ylabel("optimal RE weight (%)"); a.legend(fontsize=8); a.grid(alpha=0.3)

    # (3) funded ratio at optimum vs rate
    a = ax[1, 0]
    a.plot([r * 100 for r in RATES], [base[r]["funded"] for r in RATES], marker="o", color="black", ls="--", label="base stocks+bonds")
    for v, c in zip(ORDER, ["#d62728", "#9467bd", "#8c564b", "#e377c2"]):
        a.plot([r * 100 for r in RATES], [opt[(v, r)]["funded"] for r in RATES], "-o", color=c, label=v)
    a.set_title("Funded ratio at the optimum (higher = survives longer)")
    a.set_xlabel("withdrawal rate (%)"); a.set_ylabel("funded ratio"); a.legend(fontsize=8); a.grid(alpha=0.3)

    # (4) vol bridge
    a = ax[1, 1]
    a.plot(sens["house_real_vol"] * 100, sens["opt_RE_weight"] * 100, "-o", color="#9467bd", label="Housing opt RE weight")
    reit_re = opt[("REIT", RATE_HEADLINE)]["w"][RE_IDX] * 100
    a.axhline(reit_re, color="#d62728", ls="--", lw=2, label=f"REIT opt RE weight ({reit_re:.0f}%)")
    reit_vol = variants["REIT"][:, RE_IDX].std(ddof=1) * 100
    desm_vol = variants["House_desm"][:, RE_IDX].std(ddof=1) * 100
    a.axvline(reit_vol, color="#d62728", ls=":", lw=1.2, label=f"REIT real vol ({reit_vol:.0f}%)")
    a.axvline(desm_vol, color="#8c564b", ls=":", lw=1.2, label=f"desmoothed housing vol ({desm_vol:.0f}%)")
    a.set_title(f"Why they differ: opt housing weight vs assumed vol @ {RATE_HEADLINE*100:.1f}%")
    a.set_xlabel("housing real vol (%) [raw → amplified]"); a.set_ylabel("optimal RE weight (%)")
    a.legend(fontsize=8); a.grid(alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(os.path.join(OUT_DIR, "reit_vs_housing_allocation_funded.png"), dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
