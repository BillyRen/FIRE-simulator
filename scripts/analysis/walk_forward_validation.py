"""Walk-forward 验证：蒙特卡洛 vs 历史回测的预测准确性（校准框架）。

离线分析脚本，不进产品/后端。设计见 docs/walk-forward-validation-spec.md。

对每个决策年 T：
  - 仅用 Year <= T-1 的数据算两种预测成功率（MC block bootstrap、历史重叠 30y 窗口）
  - 用 Year >= T 的真实 30 年观察每国真实成败 (0/1)
按预测成功率分箱，对比预测 vs 真实频率 → 校准图 + Brier/ECE/偏差 + moving-block CI。

输出：
  docs/data/walk_forward_samples.csv         per-sample
  docs/data/walk_forward_calibration.csv      校准分箱表
  docs/data/walk_forward_metrics.csv          每方法/每WR 指标 + CI
  docs/walk-forward-mc-vs-backtest.html        自包含 Plotly 报告
  并向 stdout 打印关键数字（供写 markdown 报告）。
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

# 让脚本能从仓库根导入 simulator 包
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from simulator.backtest_batch import _has_failed_depletion  # noqa: E402
from simulator.data_loader import load_returns_data, load_fire_dataset  # noqa: E402
from simulator.monte_carlo import (  # noqa: E402
    batch_backtest_fixed_vectorized,
    run_simulation,
)
from simulator.portfolio import compute_real_portfolio_returns  # noqa: E402
from simulator.statistics import compute_success_rate  # noqa: E402

# ---------------------------------------------------------------------------
# 配置（见 spec §3）
# ---------------------------------------------------------------------------
RETIREMENT_YEARS = 30
MIN_BLOCK = 5
MAX_BLOCK = 15
# Block-length distribution for the MC predictor (set via CLI in main()).
# Default "uniform" reproduces the canonical validated run exactly.
BLOCK_DIST = "uniform"
MEAN_BLOCK: int | None = None
NUM_SIMULATIONS = 8000
BASE_SEED = 20260608
INITIAL_PORTFOLIO = 1_000_000.0
EXPENSE = 0.005  # 0.5% 小数制（勿用 config.DEFAULT_EXPENSE_RATIOS=0.50）
WR_GRID = [0.030, 0.035, 0.040, 0.045, 0.050, 0.055, 0.060, 0.070, 0.080]
WR_PRACTICAL = (0.030, 0.060)  # 实用子集闭区间
MIN_INSAMPLE_HB_WINDOWS = 10  # 每国 pre-T 至少 10 个完整 30y 窗口

# 主区间下界：最晚起步国(1900)需 1909-1938 第10窗口 → T>=1939；上界 T+29<=2025
T_MIN_PRIMARY = 1939
T_MAX = 1995

OUT_DATA_DIR = os.path.join(_REPO_ROOT, "docs", "data")
OUT_HTML = os.path.join(_REPO_ROOT, "docs", "walk-forward-mc-vs-backtest.html")

ALLOC_POOL = {"domestic_stock": 0.50, "global_stock": 0.50, "domestic_bond": 0.0}
ALLOC_US = {"domestic_stock": 1.0, "global_stock": 0.0, "domestic_bond": 0.0}
EXPENSE_RATIOS = {"domestic_stock": EXPENSE, "global_stock": EXPENSE, "domestic_bond": EXPENSE}


# ---------------------------------------------------------------------------
# 数据准备
# ---------------------------------------------------------------------------
def prepare_country_arrays(df: pd.DataFrame, allocation: dict) -> dict:
    """每国预计算 {iso: {years, real, df_sorted}}（real=实际组合收益数组）。"""
    out = {}
    for iso, g in df.groupby("Country"):
        g = g.sort_values("Year").reset_index(drop=True)
        years = g["Year"].to_numpy(dtype=int)
        # 窗口构造依赖年份连续（否则 real[i:i+30] 会跨年缺口）。JST/US 实测连续；
        # 若将来数据有缺口必须显式处理，故此处硬报错而非静默。
        if len(years) > 1 and not np.all(np.diff(years) == 1):
            raise ValueError(f"{iso} 年份不连续，窗口构造假设失效；需先按连续段切分。")
        real = compute_real_portfolio_returns(g, allocation, EXPENSE_RATIOS)
        out[str(iso)] = {"years": years, "real": np.asarray(real, dtype=float), "df": g}
    return out


def path_success_vec(real_2d: np.ndarray, annual_wd: float) -> np.ndarray:
    """批量 30 年真实路径的成功 0/1 向量（口径同 compute_success_rate）。"""
    if real_2d.shape[0] == 0:
        return np.empty(0, dtype=int)
    port, _, _ = batch_backtest_fixed_vectorized(real_2d, INITIAL_PORTFOLIO, annual_wd)
    return np.array([
        0 if _has_failed_depletion(port[i], RETIREMENT_YEARS, RETIREMENT_YEARS) else 1
        for i in range(port.shape[0])
    ], dtype=int)


def success_rate_for_matrix(real_2d: np.ndarray, annual_wd: float) -> float:
    """给定收益矩阵 (n,30) 与取款额，返回聚合成功率。"""
    port, _, _ = batch_backtest_fixed_vectorized(real_2d, INITIAL_PORTFOLIO, annual_wd)
    return compute_success_rate(port, RETIREMENT_YEARS)


# ---------------------------------------------------------------------------
# 单数据源 walk-forward
# ---------------------------------------------------------------------------
def run_source(
    source: str,
    df: pd.DataFrame,
    allocation: dict,
    pooled: bool,
    t_min: int,
    t_max: int,
) -> pd.DataFrame:
    """对一个数据源跑 walk-forward，返回 per-sample DataFrame。"""
    carr = prepare_country_arrays(df, allocation)
    countries = list(carr.keys())
    rows = []

    for T in range(t_min, t_max + 1):
        # --- 每国 pre-T 完整 30y in-sample 窗口（HB）与 realized 路径 ---
        hb_country_windows: dict[str, np.ndarray] = {}  # iso -> (k_c, 30) 矩阵
        realized_paths = []  # list of (iso, (30,) real-return)
        insample_years_total = 0
        for iso in countries:
            years = carr[iso]["years"]
            real = carr[iso]["real"]
            # pre-T 索引：year <= T-1
            pre_mask = years <= (T - 1)
            n_pre = int(pre_mask.sum())
            insample_years_total += n_pre
            # 完整 30y 窗口：起点 i，要求 years[i+29] <= T-1
            # years 连续 → i+29 < n_pre 且 years[i]+29 <= T-1
            wins = [real[i:i + RETIREMENT_YEARS] for i in range(0, n_pre - RETIREMENT_YEARS + 1)]
            if wins:
                hb_country_windows[iso] = np.array(wins)
            # realized：从 year T 起 30 年（需 T 存在且 T+29 <= max year）
            idx_T = np.searchsorted(years, T)
            if idx_T < len(years) and years[idx_T] == T and idx_T + RETIREMENT_YEARS <= len(years):
                realized_paths.append((iso, real[idx_T:idx_T + RETIREMENT_YEARS]))

        if not realized_paths:
            continue
        n_hb = int(sum(m.shape[0] for m in hb_country_windows.values()))
        n_hb_countries = len(hb_country_windows)

        # --- MC：每个 T 只生成一次 bootstrap 收益矩阵，跨 WR 复用 ---
        pre_df = df[df["Year"] <= (T - 1)]
        if pooled:
            country_dfs = {}
            for iso, g in pre_df.groupby("Country"):
                gg = g.sort_values("Year").reset_index(drop=True)
                if len(gg) >= 2:
                    country_dfs[str(iso)] = gg
            n_pool = len(country_dfs)
            country_weights = {iso: 1.0 / n_pool for iso in country_dfs}  # 等权
            returns_df_arg = pre_df  # pooled 路径不读取，仅占位
        else:
            country_dfs = None
            country_weights = None
            returns_df_arg = pre_df.sort_values("Year").reset_index(drop=True)

        _, _, mc_real_matrix, _ = run_simulation(
            initial_portfolio=INITIAL_PORTFOLIO,
            annual_withdrawal=WR_GRID[0] * INITIAL_PORTFOLIO,  # 占位，矩阵与 WR 无关
            allocation=allocation,
            expense_ratios=EXPENSE_RATIOS,
            retirement_years=RETIREMENT_YEARS,
            min_block=MIN_BLOCK,
            max_block=MAX_BLOCK,
            num_simulations=NUM_SIMULATIONS,
            returns_df=returns_df_arg,
            seed=BASE_SEED + T,
            withdrawal_strategy="fixed",
            leverage=1.0,
            country_dfs=country_dfs,
            country_weights=country_weights,
            block_dist=BLOCK_DIST,
            mean_block=MEAN_BLOCK,
        )

        hb_all_matrix = (np.concatenate(list(hb_country_windows.values()))
                         if n_hb else np.empty((0, RETIREMENT_YEARS)))
        realized_isos = [iso for iso, _ in realized_paths]
        realized_matrix = np.array([rr for _, rr in realized_paths])

        for wr in WR_GRID:
            annual_wd = wr * INITIAL_PORTFOLIO
            p_mc = success_rate_for_matrix(mc_real_matrix, annual_wd)
            # p_hb = 国家等权（先算每国窗口成功率再跨国等权平均）→ 与估计量一致。
            # p_hb_windoweq = 窗口等权（长历史国家权重更大）→ 仅作敏感性对照。
            if n_hb:
                per_country_rates = [
                    success_rate_for_matrix(m, annual_wd) for m in hb_country_windows.values()
                ]
                p_hb = float(np.mean(per_country_rates))
                p_hb_windoweq = success_rate_for_matrix(hb_all_matrix, annual_wd)
            else:
                p_hb = np.nan
                p_hb_windoweq = np.nan
            realized_vec = path_success_vec(realized_matrix, annual_wd)
            for iso, realized in zip(realized_isos, realized_vec):
                rows.append({
                    "source": source,
                    "decision_year": T,
                    "withdrawal_rate": wr,
                    "country": iso,
                    "p_mc": p_mc,
                    "p_hb": p_hb,
                    "p_hb_windoweq": p_hb_windoweq,
                    "realized": int(realized),
                    "n_insample_hb_windows": n_hb,
                    "n_insample_hb_countries": n_hb_countries,
                    "n_insample_years": insample_years_total,
                })
        print(f"  [{source}] T={T}  pool_n={len(country_dfs) if pooled else 1}  "
              f"hb_windows={n_hb}  realized_countries={len(realized_paths)}", flush=True)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 校准指标
# ---------------------------------------------------------------------------
def calibration_metrics(p: np.ndarray, y: np.ndarray) -> dict:
    """Brier / ECE / 平均偏差。"""
    mask = ~np.isnan(p)
    p, y = p[mask], y[mask]
    if len(p) == 0:
        return {"brier": np.nan, "ece": np.nan, "bias": np.nan, "n": 0}
    brier = float(np.mean((p - y) ** 2))
    bias = float(np.mean(p) - np.mean(y))
    # ECE：固定 0.1 等宽箱
    edges = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, 9)
    ece = 0.0
    for b in range(10):
        m = idx == b
        if m.sum() == 0:
            continue
        ece += (m.sum() / len(p)) * abs(np.mean(p[m]) - np.mean(y[m]))
    return {"brier": brier, "ece": float(ece), "bias": bias, "n": int(len(p))}


def calibration_table(p: np.ndarray, y: np.ndarray, equal_count: bool = False) -> pd.DataFrame:
    """分箱表：mean_pred, freq_real, n。"""
    mask = ~np.isnan(p)
    p, y = p[mask], y[mask]
    if len(p) == 0:
        return pd.DataFrame()
    if equal_count:
        ranks = pd.qcut(pd.Series(p).rank(method="first"), 10, labels=False)
        idx = ranks.to_numpy()
    else:
        edges = np.linspace(0, 1, 11)
        idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, 9)
    out = []
    for b in range(10):
        m = idx == b
        if m.sum() == 0:
            continue
        out.append({
            "bin": b,
            "mean_pred": float(np.mean(p[m])),
            "freq_real": float(np.mean(y[m])),
            "n": int(m.sum()),
        })
    return pd.DataFrame(out)


def moving_block_ci(
    df: pd.DataFrame, metric_fn, block_len: int = 20, n_boot: int = 1000, seed: int = 7
) -> tuple:
    """对按 decision_year 的连续块做 moving-block bootstrap，返回 (lo, hi)。

    metric_fn(sub_df) -> float。块内保留该年全部行。
    """
    rng = np.random.default_rng(seed)
    years = np.sort(df["decision_year"].unique())
    n_years = len(years)
    if n_years == 0:
        return (np.nan, np.nan)
    # block_len >= n_years 会退化为原样本（零变异）→ 上限到 n_years-1
    block_len = max(1, min(block_len, n_years - 1)) if n_years > 1 else 1
    # 预分组
    groups = {yr: df[df["decision_year"] == yr] for yr in years}
    n_blocks_needed = int(np.ceil(n_years / block_len))
    vals = []
    for _ in range(n_boot):
        picked_years = []
        for _b in range(n_blocks_needed):
            start = rng.integers(0, n_years)  # 循环 moving-block
            for k in range(block_len):
                picked_years.append(years[(start + k) % n_years])
        picked_years = picked_years[:n_years]
        sub = pd.concat([groups[yr] for yr in picked_years], ignore_index=True)
        v = metric_fn(sub)
        if not np.isnan(v):
            vals.append(v)
    if not vals:
        return (np.nan, np.nan)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


# ---------------------------------------------------------------------------
# 聚合与报告
# ---------------------------------------------------------------------------
def summarize_source(samples: pd.DataFrame, source: str) -> dict:
    """对一个数据源计算指标 + 配对差异 CI。返回 dict（含打印用文本）。"""
    s = samples[samples["source"] == source]
    res = {"source": source}

    def subset(df, wr_lo=None, wr_hi=None):
        if wr_lo is None:
            return df
        return df[(df["withdrawal_rate"] >= wr_lo - 1e-9) & (df["withdrawal_rate"] <= wr_hi + 1e-9)]

    for label, sub in [("all", s), ("practical_3_6", subset(s, *WR_PRACTICAL))]:
        y = sub["realized"].to_numpy(dtype=float)
        mc = calibration_metrics(sub["p_mc"].to_numpy(dtype=float), y)
        hb = calibration_metrics(sub["p_hb"].to_numpy(dtype=float), y)
        res[f"{label}_mc"] = mc
        res[f"{label}_hb"] = hb

        # 配对差异 CI：MC - HB 的 bias 与 brier
        def diff_bias(d):
            yy = d["realized"].to_numpy(dtype=float)
            return calibration_metrics(d["p_mc"].to_numpy(float), yy)["bias"] - \
                   calibration_metrics(d["p_hb"].to_numpy(float), yy)["bias"]

        def diff_brier(d):
            yy = d["realized"].to_numpy(dtype=float)
            return calibration_metrics(d["p_mc"].to_numpy(float), yy)["brier"] - \
                   calibration_metrics(d["p_hb"].to_numpy(float), yy)["brier"]

        def mc_bias(d):
            return calibration_metrics(d["p_mc"].to_numpy(float), d["realized"].to_numpy(float))["bias"]

        def hb_bias(d):
            return calibration_metrics(d["p_hb"].to_numpy(float), d["realized"].to_numpy(float))["bias"]

        res[f"{label}_diff_bias_ci"] = moving_block_ci(sub, diff_bias)
        res[f"{label}_diff_brier_ci"] = moving_block_ci(sub, diff_brier)
        res[f"{label}_mc_bias_ci"] = moving_block_ci(sub, mc_bias)
        res[f"{label}_hb_bias_ci"] = moving_block_ci(sub, hb_bias)

    # per-WR 指标
    per_wr = []
    for wr in sorted(s["withdrawal_rate"].unique()):
        sub = s[s["withdrawal_rate"] == wr]
        y = sub["realized"].to_numpy(dtype=float)
        mc = calibration_metrics(sub["p_mc"].to_numpy(float), y)
        hb = calibration_metrics(sub["p_hb"].to_numpy(float), y)
        per_wr.append({
            "wr": wr, "n": mc["n"],
            "realized": float(np.mean(y)),
            "mc_pred": float(np.nanmean(sub["p_mc"])), "hb_pred": float(np.nanmean(sub["p_hb"])),
            "mc_bias": mc["bias"], "hb_bias": hb["bias"],
            "mc_brier": mc["brier"], "hb_brier": hb["brier"],
        })
    res["per_wr"] = per_wr
    res["calib_mc"] = calibration_table(s["p_mc"].to_numpy(float), s["realized"].to_numpy(float))
    res["calib_hb"] = calibration_table(s["p_hb"].to_numpy(float), s["realized"].to_numpy(float))
    res["calib_mc_eqc"] = calibration_table(s["p_mc"].to_numpy(float), s["realized"].to_numpy(float), equal_count=True)
    res["calib_hb_eqc"] = calibration_table(s["p_hb"].to_numpy(float), s["realized"].to_numpy(float), equal_count=True)

    # 时间序列（WR=4% 与 6%）
    ts = {}
    for wr in (0.040, 0.060):
        sub = s[np.isclose(s["withdrawal_rate"], wr)]
        g = sub.groupby("decision_year").agg(
            realized=("realized", "mean"),
            p_mc=("p_mc", "mean"),
            p_hb=("p_hb", "mean"),
        ).reset_index()
        ts[wr] = g
    res["timeseries"] = ts
    return res


def fmt_pp(x):
    return f"{x * 100:+.1f}pp" if x == x else "n/a"


def fmt_ci(ci):
    lo, hi = ci
    if lo != lo:
        return "n/a"
    return f"[{lo * 100:+.1f}, {hi * 100:+.1f}]pp"


def print_summary(res: dict):
    src = res["source"]
    print(f"\n{'=' * 70}\n数据源: {src}\n{'=' * 70}")
    for label in ("all", "practical_3_6"):
        mc, hb = res[f"{label}_mc"], res[f"{label}_hb"]
        print(f"\n[{label}]  n={mc['n']}")
        print(f"  真实均值成功率: {np.nan}  (见 per-WR)")
        print(f"  MC : 平均偏差 {fmt_pp(mc['bias'])}  Brier {mc['brier']:.4f}  ECE {mc['ece']:.4f}")
        print(f"  HB : 平均偏差 {fmt_pp(hb['bias'])}  Brier {hb['brier']:.4f}  ECE {hb['ece']:.4f}")
        print(f"  MC 偏差 95%CI {fmt_ci(res[f'{label}_mc_bias_ci'])}")
        print(f"  HB 偏差 95%CI {fmt_ci(res[f'{label}_hb_bias_ci'])}")
        print(f"  配对 MC-HB 偏差差 95%CI {fmt_ci(res[f'{label}_diff_bias_ci'])}")
        db = res[f'{label}_diff_brier_ci']
        print(f"  配对 MC-HB Brier差 95%CI [{db[0]:+.4f}, {db[1]:+.4f}]")
    print("\n per-WR:")
    print(f"  {'WR':>5} {'n':>5} {'real':>6} {'MC_pred':>8} {'HB_pred':>8} {'MC_bias':>8} {'HB_bias':>8}")
    for r in res["per_wr"]:
        print(f"  {r['wr'] * 100:>4.1f}% {r['n']:>5} {r['realized']:>6.2f} "
              f"{r['mc_pred']:>8.2f} {r['hb_pred']:>8.2f} {fmt_pp(r['mc_bias']):>8} {fmt_pp(r['hb_bias']):>8}")


# ---------------------------------------------------------------------------
# HTML 报告（Plotly CDN）
# ---------------------------------------------------------------------------
def build_html(results: list[dict]) -> str:
    figs = []
    for res in results:
        src = res["source"]
        # 校准图
        cm, ch = res["calib_mc"], res["calib_hb"]
        figs.append({
            "id": f"calib_{src}", "title": f"校准图 — {src}（固定0.1箱）",
            "traces": [
                {"x": [0, 1], "y": [0, 1], "mode": "lines", "name": "完美校准",
                 "line": {"dash": "dot", "color": "#888"}},
                {"x": cm["mean_pred"].tolist() if len(cm) else [],
                 "y": cm["freq_real"].tolist() if len(cm) else [],
                 "text": cm["n"].tolist() if len(cm) else [],
                 "mode": "lines+markers", "name": "MC", "line": {"color": "#2563eb"}},
                {"x": ch["mean_pred"].tolist() if len(ch) else [],
                 "y": ch["freq_real"].tolist() if len(ch) else [],
                 "text": ch["n"].tolist() if len(ch) else [],
                 "mode": "lines+markers", "name": "历史回测", "line": {"color": "#dc2626"}},
            ],
            "xaxis": "预测成功率", "yaxis": "真实成功频率",
        })
        # 时间序列
        for wr, g in res["timeseries"].items():
            figs.append({
                "id": f"ts_{src}_{int(wr*1000)}", "title": f"时间序列 — {src}  WR={wr*100:.1f}%",
                "traces": [
                    {"x": g["decision_year"].tolist(), "y": g["realized"].tolist(),
                     "mode": "lines+markers", "name": "真实频率", "line": {"color": "#16a34a"}},
                    {"x": g["decision_year"].tolist(), "y": g["p_mc"].tolist(),
                     "mode": "lines", "name": "MC 预测", "line": {"color": "#2563eb"}},
                    {"x": g["decision_year"].tolist(), "y": g["p_hb"].tolist(),
                     "mode": "lines", "name": "历史回测预测", "line": {"color": "#dc2626"}},
                ],
                "xaxis": "决策年", "yaxis": "成功率",
            })
    figs_json = json.dumps(figs)
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>Walk-Forward: MC vs 历史回测 校准</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:system-ui,sans-serif;max-width:1000px;margin:2em auto;padding:0 1em}}
.chart{{margin:2em 0}}h1{{font-size:1.4em}}</style></head>
<body><h1>Walk-Forward 验证：蒙特卡洛 vs 历史回测的预测准确性</h1>
<p>校准框架。估计量 = "从面板随机抽一国的真实 30 年退休结局"（等权）。
对角线下方 = 系统性高估（过度乐观）。详见 docs/walk-forward-mc-vs-backtest.md。</p>
<div id="charts"></div>
<script>
const figs = {figs_json};
const root = document.getElementById('charts');
figs.forEach(f => {{
  const div = document.createElement('div'); div.className='chart';
  div.innerHTML = '<h3>'+f.title+'</h3>'; const plot=document.createElement('div');
  div.appendChild(plot); root.appendChild(div);
  Plotly.newPlot(plot, f.traces, {{
    xaxis:{{title:f.xaxis,range:f.id.startsWith('calib')?[0,1.02]:undefined}},
    yaxis:{{title:f.yaxis,range:[0,1.02]}}, margin:{{t:10}}, legend:{{orientation:'h'}}
  }}, {{responsive:true}});
}});
</script></body></html>"""


# ---------------------------------------------------------------------------
def main():
    import argparse
    global BLOCK_DIST, MEAN_BLOCK
    ap = argparse.ArgumentParser(description="Walk-forward MC vs HB calibration")
    ap.add_argument("--block-dist", choices=["uniform", "geometric"],
                    default="uniform",
                    help="MC predictor block-length law (default uniform).")
    ap.add_argument("--mean-block", type=int, default=None,
                    help="Geometric mean block length (default = uniform midpoint=10).")
    ap.add_argument("--tag", default="",
                    help="Output filename suffix (avoid overwriting canonical run).")
    ap.add_argument("--sources", default="main",
                    choices=["main", "all"],
                    help="'main' = JST_pool + US only (faster); 'all' adds early appendix.")
    args = ap.parse_args()
    BLOCK_DIST = args.block_dist
    MEAN_BLOCK = args.mean_block
    suffix = f"_{args.tag}" if args.tag else ""

    os.makedirs(OUT_DATA_DIR, exist_ok=True)
    print(f"[config] block_dist={BLOCK_DIST} mean_block={MEAN_BLOCK} "
          f"sources={args.sources} tag={args.tag!r}", flush=True)

    print("加载数据 ...", flush=True)
    jst = load_returns_data()
    us = load_fire_dataset()

    all_samples = []

    print("\n>>> JST 池化（等权，50/50 本国/全球股）", flush=True)
    jst_samples = run_source("JST_pool_eqw", jst, ALLOC_POOL, pooled=True,
                             t_min=T_MIN_PRIMARY, t_max=T_MAX)
    all_samples.append(jst_samples)

    print("\n>>> 美国单国（FIRE_dataset，100% 本国股）", flush=True)
    us_samples = run_source("US_100stock", us, ALLOC_US, pooled=False,
                            t_min=T_MIN_PRIMARY, t_max=T_MAX)
    all_samples.append(us_samples)

    if args.sources == "all":
        # 附录：早期有限历史 1915-1938（realized 含 DEU 1920s / JPN 1940s 灾难）。
        # 部分国家 pre-T < 30y → 0 个 in-sample 窗口，预测池国家集与 realized 集不完全
        # 对齐（见 spec §4.2 附录说明）。仅作时期依赖性对照，不进主结论。
        print("\n>>> 附录：JST 池化 早期 1915-1938（有限历史）", flush=True)
        early = run_source("JST_pool_early_1915_1938", jst, ALLOC_POOL, pooled=True,
                           t_min=1915, t_max=1938)
        all_samples.append(early)

    samples = pd.concat(all_samples, ignore_index=True)
    samples.to_csv(os.path.join(OUT_DATA_DIR, f"walk_forward_samples{suffix}.csv"),
                   index=False)
    print(f"\n样本表已存: {len(samples)} 行", flush=True)

    results = []
    calib_rows = []
    metric_rows = []
    for src in samples["source"].unique():
        res = summarize_source(samples, src)
        results.append(res)
        print_summary(res)
        for name in ("calib_mc", "calib_hb", "calib_mc_eqc", "calib_hb_eqc"):
            t = res[name]
            if len(t):
                t = t.assign(source=src, which=name)
                calib_rows.append(t)
        for r in res["per_wr"]:
            metric_rows.append({"source": src, **r})

    if calib_rows:
        pd.concat(calib_rows, ignore_index=True).to_csv(
            os.path.join(OUT_DATA_DIR, f"walk_forward_calibration{suffix}.csv"),
            index=False)
    pd.DataFrame(metric_rows).to_csv(
        os.path.join(OUT_DATA_DIR, f"walk_forward_metrics{suffix}.csv"), index=False)

    out_html = OUT_HTML if not suffix else OUT_HTML.replace(".html", f"{suffix}.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(build_html(results))
    print(f"\nHTML 报告: {out_html}", flush=True)


if __name__ == "__main__":
    main()
