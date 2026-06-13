"""美国 4 资产最优配置：房地产用 REIT 还是 直接房地产，最优组合变化大么？

资产菜单（同一 overlap 窗口 1972-2024，REIT 起点约束）：
  US Stock / Non-US Stock / US Bond  —— 全部来自 FIRE_dataset（名义）
  + 房地产 sleeve（四选一变体）：
     REIT          FTSE Nareit All Equity REITs（data/reit_returns.csv；可交易、未平滑）
     House_raw     JST USA Housing_TR（评估价/成交价指数，强平滑 → σ 被低估）
     House_desm    House_raw 经 Geltner 一阶去平滑（还原"真实"波动）
     House_desm_net House_desm 再扣 -2pp 持有成本（≈ 真正自住一套房，参考 Chambers 2021）

口径 / 方法（对齐 docs/upi-optimal-allocation-2026-06-10.md 的既有经验）：
  - 实际收益：real=(1+nom)/(1+infl)-1，统一用 FIRE_dataset 的 US Inflation 平减
  - 年度再平衡，组合实际收益 = 权重 · 各资产实际收益
  - UPI (Martin ratio)：UI=sqrt(mean(回撤%²))（实际财富路径含 t=0=1.0，floor 1.0pct），
    UPI = 实际CAGR×100 / UI，rf=0
  - 单线最优：1972-2024 历史单路径上网格扫描（4 资产单纯形，步长 2%），分别取
    max-UPI / max-Sharpe / min-vol
  - 稳健最优：circular block bootstrap（块长 U[5,15]、30 年、2000 路径、seed 42、
    联合同块采样保留相关性），目标 = max P10(UPI)（坏运气情景），网格 5%
  - 桥接敏感性：把 House_raw 的波动按 mult 放大 r'=mean+mult*(r-mean)，看最优房产
    权重随 mult 如何向 REIT 收敛（REIT 实际 σ≈17-18%，House_raw≈4-5%）

输出（analysis/output/reit_vs_housing_allocation/）：
  asset_stats.csv  optimal_weights.csv  vol_sensitivity.csv  reit_vs_housing_allocation.png
用法：python analysis/reit_vs_housing_allocation.py
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(_BASE, "analysis", "output", "reit_vs_housing_allocation")
os.makedirs(OUT_DIR, exist_ok=True)

Y0, Y1 = 1972, 2024
ASSETS = ["US_Stock", "NonUS_Stock", "US_Bond", "RealEstate"]
NA = len(ASSETS)
RE_IDX = 3

# bootstrap
NUM_SIMS = 2000
HORIZON = 30
MIN_BLOCK, MAX_BLOCK = 5, 15
SEED = 42
COST_NET = 0.02  # -2pp 持有成本（House_desm_net）


# ───────────────────────── 数据 ─────────────────────────
def load_real() -> dict[str, np.ndarray]:
    """返回 {variant: (T,4) 实际收益矩阵}，列序 = ASSETS。窗口 1972-2024。"""
    f = pd.read_csv(os.path.join(_BASE, "data", "FIRE_dataset.csv"))
    r = pd.read_csv(os.path.join(_BASE, "data", "reit_returns.csv"))
    j = pd.read_csv(os.path.join(_BASE, "data", "jst_returns.csv"))
    j = j[j["Country"] == "USA"][["Year", "Housing_TR"]]

    fwin = f[(f["Year"] >= Y0) & (f["Year"] <= Y1)].sort_values("Year")
    infl = fwin["US Inflation"].to_numpy()
    us = (1 + fwin["US Stock"].to_numpy()) / (1 + infl) - 1
    intl = (1 + fwin["International Stock"].to_numpy()) / (1 + infl) - 1
    bond = (1 + fwin["US Bond"].to_numpy()) / (1 + infl) - 1

    reit = r[(r["Year"] >= Y0) & (r["Year"] <= Y1)].sort_values("Year")["AllEquityREITs_TR"].to_numpy()
    reit_real = (1 + reit) / (1 + infl) - 1

    # housing real, plus 1971 lag for desmoothing
    fall = f[(f["Year"] >= Y0 - 1) & (f["Year"] <= Y1)].sort_values("Year")
    infl_ext = fall["US Inflation"].to_numpy()
    jall = j[(j["Year"] >= Y0 - 1) & (j["Year"] <= Y1)].sort_values("Year")["Housing_TR"].to_numpy()
    house_real_ext = (1 + jall) / (1 + infl_ext) - 1   # length T+1 (1971..2024)
    house_raw = house_real_ext[1:]                      # 1972..2024

    # Geltner 一阶去平滑：phi = lag1 自相关；r* = (r - phi r_{-1})/(1-phi)
    phi = float(np.corrcoef(house_real_ext[:-1], house_real_ext[1:])[0, 1])
    house_desm = (house_real_ext[1:] - phi * house_real_ext[:-1]) / (1 - phi)
    house_desm_net = house_desm - COST_NET

    base3 = np.column_stack([us, intl, bond])
    variants = {
        "REIT": np.column_stack([base3, reit_real]),
        "House_raw": np.column_stack([base3, house_raw]),
        "House_desm": np.column_stack([base3, house_desm]),
        "House_desm_net": np.column_stack([base3, house_desm_net]),
    }
    variants["_phi"] = phi  # stash for reporting
    return variants


# ───────────────────────── 指标 ─────────────────────────
def upi_from_port(port: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """port: (..., T) 实际收益。返回 (CAGR, UI, UPI)，broadcast 在前导维上。"""
    T = port.shape[-1]
    ones = np.ones(port.shape[:-1] + (1,))
    wealth = np.concatenate([ones, np.cumprod(1 + port, axis=-1)], axis=-1)
    peak = np.maximum.accumulate(wealth, axis=-1)
    dd = (wealth / peak - 1.0) * 100.0
    ui = np.sqrt(np.mean(dd * dd, axis=-1))
    ui = np.maximum(ui, 1.0)
    cagr = wealth[..., -1] ** (1.0 / T) - 1.0
    upi = cagr * 100.0 / ui
    return cagr, ui, upi


def port_stats(port: np.ndarray) -> dict:
    cagr, ui, upi = upi_from_port(port)
    mean = port.mean(axis=-1)
    vol = port.std(axis=-1, ddof=1)
    wealth = np.concatenate([np.ones(port.shape[:-1] + (1,)), np.cumprod(1 + port, axis=-1)], -1)
    peak = np.maximum.accumulate(wealth, -1)
    maxdd = (wealth / peak - 1.0).min(axis=-1)
    return {"cagr": cagr, "vol": vol, "mean": mean, "sharpe": mean / vol,
            "upi": upi, "ui": ui, "maxdd": maxdd}


# ───────────────────────── 网格 ─────────────────────────
def simplex(k: int, n: int) -> np.ndarray:
    def comp(k, total):
        if k == 1:
            return [(total,)]
        out = []
        for a in range(total + 1):
            for rest in comp(k - 1, total - a):
                out.append((a,) + rest)
        return out
    return np.array(comp(k, n), dtype=float) / n


def grid_weights(step_pct: int, active: list[int]) -> np.ndarray:
    n = int(round(100 / step_pct))
    sub = simplex(len(active), n)
    W = np.zeros((sub.shape[0], NA))
    for j, idx in enumerate(active):
        W[:, idx] = sub[:, j]
    return W


# ───────────────────────── 单线最优 ─────────────────────────
def single_line_optima(R: np.ndarray, active: list[int], step_pct: int = 2) -> dict:
    W = grid_weights(step_pct, active)         # (C, NA)
    port = W @ R.T                             # (C, T)
    st = port_stats(port)
    out = {}
    for key, arr, sense in [("maxUPI", st["upi"], 1), ("maxSharpe", st["sharpe"], 1),
                            ("minVol", st["vol"], -1)]:
        i = int(np.argmax(arr * sense))
        out[key] = {"w": W[i], **{m: float(st[m][i]) for m in
                    ["cagr", "vol", "sharpe", "upi", "maxdd"]}}
    return out


# ───────────────────── circular block bootstrap ─────────────────────
def bootstrap_paths(R: np.ndarray, rng) -> np.ndarray:
    """返回 (S, H, NA) 实际收益路径（circular moving-block，块长 U[min,max]）。"""
    T = R.shape[0]
    out = np.empty((NUM_SIMS, HORIZON, R.shape[1]))
    for s in range(NUM_SIMS):
        filled = 0
        rows = []
        while filled < HORIZON:
            L = rng.integers(MIN_BLOCK, MAX_BLOCK + 1)
            start = rng.integers(0, T)
            idx = (start + np.arange(L)) % T
            rows.append(idx)
            filled += L
        idx = np.concatenate(rows)[:HORIZON]
        out[s] = R[idx]
    return out


def bootstrap_p10_optimum(R: np.ndarray, active: list[int], step_pct: int = 5,
                          chunk: int = 150) -> dict:
    rng = np.random.default_rng(SEED)
    paths = bootstrap_paths(R, rng)            # (S,H,NA)
    W = grid_weights(step_pct, active)         # (C,NA)
    C = W.shape[0]
    p10 = np.empty(C)
    med = np.empty(C)
    for lo in range(0, C, chunk):
        hi = min(lo + chunk, C)
        Wc = W[lo:hi]
        port = np.einsum("sha,ca->csh", paths, Wc)   # (c,S,H)
        _, _, upi = upi_from_port(port)              # (c,S)
        p10[lo:hi] = np.percentile(upi, 10, axis=1)
        med[lo:hi] = np.percentile(upi, 50, axis=1)
    i = int(np.argmax(p10))
    return {"w": W[i], "p10_upi": float(p10[i]), "median_upi": float(med[i])}


# ───────────────────── 资产描述统计 ─────────────────────
def asset_table(variants: dict) -> pd.DataFrame:
    base = variants["REIT"][:, :3]
    rows = []
    names = {"US_Stock": base[:, 0], "NonUS_Stock": base[:, 1], "US_Bond": base[:, 2]}
    for v in ["REIT", "House_raw", "House_desm", "House_desm_net"]:
        names[v] = variants[v][:, RE_IDX]
    usd = base[:, 0]
    for nm, x in names.items():
        T = len(x)
        cagr = np.prod(1 + x) ** (1 / T) - 1
        w = np.concatenate([[1.0], np.cumprod(1 + x)])
        dd = (w / np.maximum.accumulate(w) - 1).min()
        rows.append({
            "asset": nm, "real_CAGR": cagr, "real_mean": x.mean(),
            "real_vol": x.std(ddof=1), "sharpe": x.mean() / x.std(ddof=1),
            "maxDD": dd, "ac_lag1": float(np.corrcoef(x[:-1], x[1:])[0, 1]),
            "corr_USstock": float(np.corrcoef(x, usd)[0, 1]),
        })
    return pd.DataFrame(rows)


# ───────────────────── vol 桥接敏感性 ─────────────────────
def vol_sensitivity(variants: dict, active: list[int]) -> pd.DataFrame:
    raw = variants["House_raw"][:, RE_IDX]
    base = variants["House_raw"][:, :3]
    mu = raw.mean()
    reit_opt = single_line_optima(variants["REIT"], active)["maxUPI"]["w"][RE_IDX]
    rows = []
    for mult in [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0]:
        scaled = mu + mult * (raw - mu)
        R = np.column_stack([base, scaled])
        o = single_line_optima(R, active)["maxUPI"]
        rows.append({"vol_mult": mult, "house_real_vol": scaled.std(ddof=1),
                     "opt_RE_weight": o["w"][RE_IDX], "upi": o["upi"],
                     "reit_opt_RE_weight": reit_opt})
    return pd.DataFrame(rows)


# ───────────────────────── 图 ─────────────────────────
def make_figure(variants, opt_rows, sens, atab, path):
    fig, ax = plt.subplots(2, 2, figsize=(15, 11))
    fig.suptitle("US 4-asset optimum: real-estate sleeve = REIT vs Housing (1972-2024, real, max-UPI)",
                 fontsize=14, fontweight="bold")
    order = ["REIT", "House_raw", "House_desm", "House_desm_net"]
    colors = {"US_Stock": "#1f77b4", "NonUS_Stock": "#17becf", "US_Bond": "#2ca02c", "RealEstate": "#d62728"}

    # (1) optimal weights stacked bars (max-UPI single line)
    a = ax[0, 0]
    bottoms = np.zeros(len(order))
    for ai, an in enumerate(ASSETS):
        vals = [opt_rows[(v, "maxUPI")]["w"][ai] * 100 for v in order]
        a.bar(order, vals, bottom=bottoms, label=an, color=colors[an])
        bottoms += vals
    a.set_title("Optimal weights (max-UPI, single historical path)")
    a.set_ylabel("weight (%)"); a.legend(fontsize=8, ncol=2, loc="center left"); a.set_ylim(0, 100)
    for i, v in enumerate(order):
        re = opt_rows[(v, "maxUPI")]["w"][RE_IDX] * 100
        a.text(i, 100 - re / 2, f"RE\n{re:.0f}%", ha="center", va="center",
               fontsize=9, color="white", fontweight="bold")

    # (2) bootstrap P10 optimal weights
    a = ax[0, 1]
    bottoms = np.zeros(len(order))
    for ai, an in enumerate(ASSETS):
        vals = [opt_rows[(v, "bootP10")]["w"][ai] * 100 for v in order]
        a.bar(order, vals, bottom=bottoms, label=an, color=colors[an])
        bottoms += vals
    a.set_title("Robust optimal weights (block-bootstrap, max P10-UPI)")
    a.set_ylabel("weight (%)"); a.legend(fontsize=8, ncol=2, loc="center left"); a.set_ylim(0, 100)
    for i, v in enumerate(order):
        re = opt_rows[(v, "bootP10")]["w"][RE_IDX] * 100
        a.text(i, 100 - re / 2, f"RE\n{re:.0f}%", ha="center", va="center",
               fontsize=9, color="white", fontweight="bold")

    # (3) efficient frontiers (real)
    a = ax[1, 0]
    active = [0, 1, 2, 3]
    W = grid_weights(2, active)
    for v, col in zip(order, ["#d62728", "#9467bd", "#8c564b", "#e377c2"]):
        R = variants[v]
        st = port_stats(W @ R.T)
        a.scatter(st["vol"] * 100, st["cagr"] * 100, s=3, alpha=0.12, color=col)
        # frontier upper hull
        vv, cc = st["vol"] * 100, st["cagr"] * 100
        order_idx = np.argsort(vv)
        vv, cc = vv[order_idx], cc[order_idx]
        hull_v, hull_c, cmax = [], [], -1e9
        for k in range(len(vv)):
            if cc[k] > cmax:
                cmax = cc[k]; hull_v.append(vv[k]); hull_c.append(cc[k])
        a.plot(hull_v, hull_c, color=col, lw=2, label=v)
    # base 3-asset frontier
    Wb = grid_weights(2, [0, 1, 2])
    stb = port_stats(Wb @ variants["REIT"].T)
    vv, cc = stb["vol"] * 100, stb["cagr"] * 100
    oi = np.argsort(vv); vv, cc = vv[oi], cc[oi]
    hv, hc, cm = [], [], -1e9
    for k in range(len(vv)):
        if cc[k] > cm:
            cm = cc[k]; hv.append(vv[k]); hc.append(cc[k])
    a.plot(hv, hc, color="black", lw=1.6, ls="--", label="Stocks+Bond only")
    a.set_title("Efficient frontier (real CAGR vs real vol)")
    a.set_xlabel("real vol (%)"); a.set_ylabel("real CAGR (%)"); a.legend(fontsize=8); a.grid(alpha=0.3)

    # (4) vol bridge
    a = ax[1, 1]
    a.plot(sens["house_real_vol"] * 100, sens["opt_RE_weight"] * 100, "-o", color="#9467bd", label="Housing opt RE weight")
    reit_re = opt_rows[("REIT", "maxUPI")]["w"][RE_IDX] * 100
    reit_vol = atab.set_index("asset").loc["REIT", "real_vol"] * 100
    a.axhline(reit_re, color="#d62728", ls="--", lw=2, label=f"REIT opt RE weight ({reit_re:.0f}%)")
    a.axvline(reit_vol, color="#d62728", ls=":", lw=1.2, label=f"REIT real vol ({reit_vol:.0f}%)")
    desm_vol = atab.set_index("asset").loc["House_desm", "real_vol"] * 100
    a.axvline(desm_vol, color="#8c564b", ls=":", lw=1.2, label=f"desmoothed housing vol ({desm_vol:.0f}%)")
    a.set_title("Why they differ: optimal housing weight vs assumed housing vol")
    a.set_xlabel("housing real vol (%) [raw → amplified]")
    a.set_ylabel("optimal real-estate weight (%)"); a.legend(fontsize=8); a.grid(alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path, dpi=130); plt.close(fig)


# ───────────────────────── main ─────────────────────────
def main():
    variants = load_real()
    phi = variants.pop("_phi")
    active = [0, 1, 2, 3]

    atab = asset_table(variants)
    atab.round(4).to_csv(os.path.join(OUT_DIR, "asset_stats.csv"), index=False)

    order = ["REIT", "House_raw", "House_desm", "House_desm_net"]
    opt_rows = {}
    rec = []
    # base (no RE)
    base_opt = single_line_optima(variants["REIT"], [0, 1, 2])["maxUPI"]
    for v in order:
        R = variants[v]
        sl = single_line_optima(R, active)
        for key in ["maxUPI", "maxSharpe", "minVol"]:
            opt_rows[(v, key)] = sl[key]
        bp = bootstrap_p10_optimum(R, active)
        opt_rows[(v, "bootP10")] = bp
        for key in ["maxUPI", "maxSharpe", "minVol"]:
            w = sl[key]["w"]
            rec.append({"variant": v, "objective": key,
                        **{ASSETS[i]: round(w[i] * 100, 1) for i in range(NA)},
                        "real_CAGR%": round(sl[key]["cagr"] * 100, 2),
                        "real_vol%": round(sl[key]["vol"] * 100, 2),
                        "sharpe": round(sl[key]["sharpe"], 3),
                        "UPI": round(sl[key]["upi"], 3),
                        "maxDD%": round(sl[key]["maxdd"] * 100, 1)})
        w = bp["w"]
        rec.append({"variant": v, "objective": "bootP10_UPI",
                    **{ASSETS[i]: round(w[i] * 100, 1) for i in range(NA)},
                    "real_CAGR%": np.nan, "real_vol%": np.nan, "sharpe": np.nan,
                    "UPI": round(bp["p10_upi"], 3), "maxDD%": np.nan})
    opt_df = pd.DataFrame(rec)
    opt_df.to_csv(os.path.join(OUT_DIR, "optimal_weights.csv"), index=False)

    sens = vol_sensitivity(variants, active)
    sens.round(4).to_csv(os.path.join(OUT_DIR, "vol_sensitivity.csv"), index=False)

    make_figure(variants, opt_rows, sens, atab,
                os.path.join(OUT_DIR, "reit_vs_housing_allocation.png"))

    # ───── 控制台 ─────
    pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30)
    print("=" * 92)
    print(f"美国 4 资产最优配置  US股/非美股/US债 + 房地产sleeve   窗口 {Y0}-{Y1}（{len(variants['REIT'])}年, 实际收益）")
    print("=" * 92)
    print(f"\nGeltner 去平滑系数 phi(房地产实际收益 lag-1 自相关) = {phi:.2f}")

    print("\n【资产实际收益特征】")
    show = atab.copy()
    for c in ["real_CAGR", "real_mean", "real_vol", "maxDD"]:
        show[c] = (show[c] * 100).round(2)
    show["sharpe"] = show["sharpe"].round(3); show["ac_lag1"] = show["ac_lag1"].round(2)
    show["corr_USstock"] = show["corr_USstock"].round(2)
    print(show.to_string(index=False))

    print(f"\n【基准：仅 股/债（无房地产）max-UPI】 "
          f"US{base_opt['w'][0]*100:.0f}/Intl{base_opt['w'][1]*100:.0f}/Bond{base_opt['w'][2]*100:.0f}"
          f"  UPI={base_opt['upi']:.3f} CAGR={base_opt['cagr']*100:.2f}% vol={base_opt['vol']*100:.2f}% MaxDD={base_opt['maxdd']*100:.1f}%")

    print("\n【单线最优 max-UPI（各房地产变体）】  权重 US/Intl/Bond/RE")
    for v in order:
        o = opt_rows[(v, "maxUPI")]; w = o["w"]
        print(f"  {v:15s} {w[0]*100:4.0f}/{w[1]*100:4.0f}/{w[2]*100:4.0f}/{w[3]*100:4.0f}   "
              f"UPI={o['upi']:.3f}  CAGR={o['cagr']*100:5.2f}%  vol={o['vol']*100:5.2f}%  MaxDD={o['maxdd']*100:6.1f}%")

    print("\n【单线最优 max-Sharpe】  权重 US/Intl/Bond/RE")
    for v in order:
        o = opt_rows[(v, "maxSharpe")]; w = o["w"]
        print(f"  {v:15s} {w[0]*100:4.0f}/{w[1]*100:4.0f}/{w[2]*100:4.0f}/{w[3]*100:4.0f}   Sharpe={o['sharpe']:.3f}")

    print("\n【稳健最优 bootstrap max-P10(UPI)】  权重 US/Intl/Bond/RE")
    for v in order:
        bp = opt_rows[(v, "bootP10")]; w = bp["w"]
        print(f"  {v:15s} {w[0]*100:4.0f}/{w[1]*100:4.0f}/{w[2]*100:4.0f}/{w[3]*100:4.0f}   P10-UPI={bp['p10_upi']:.3f}")

    print("\n【vol 桥接：房地产波动放大 → 最优房产权重】")
    s = sens.copy(); s["house_real_vol"] = (s["house_real_vol"] * 100).round(1)
    s["opt_RE_weight"] = (s["opt_RE_weight"] * 100).round(0)
    s["reit_opt_RE_weight"] = (s["reit_opt_RE_weight"] * 100).round(0)
    print(s[["vol_mult", "house_real_vol", "opt_RE_weight", "reit_opt_RE_weight", "upi"]].to_string(index=False))

    print("\n输出目录:", OUT_DIR)


if __name__ == "__main__":
    main()
