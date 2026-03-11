#!/usr/bin/env python3
"""JST 起始年份对成功率曲线影响的敏感性分析。

对比 5 个起始年份 × 4 种资产配置下的 Monte Carlo 成功率曲线，
评估历史数据选择范围对 FIRE 规划结论的影响。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd

_CJK_FONTS = [
    "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
    "SimHei", "Noto Sans CJK SC", "STHeiti",
]
for _f in _CJK_FONTS:
    if any(_f in f.name for f in fm.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [_f, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        break

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from simulator.data_loader import load_returns_data, get_country_dfs
from simulator.portfolio import compute_real_portfolio_returns
from simulator.config import get_gdp_weights

# ═══════════════════════════════════════════════════════════════════════════
# 参数
# ═══════════════════════════════════════════════════════════════════════════

INITIAL_PORTFOLIO = 1_000_000
RETIREMENT_YEARS = 65
MIN_BLOCK = 5
MAX_BLOCK = 15
NUM_SIMS = 5000
SEED = 42

RATE_MIN = 0.0
RATE_MAX = 0.10
RATE_STEP = 0.001
RATES = np.round(np.arange(RATE_MIN, RATE_MAX + RATE_STEP / 2, RATE_STEP), 4)

OUTPUT_DIR = ROOT / "analysis" / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
START_YEAR_OUTPUT_DIR = OUTPUT_DIR / "start_year"
START_YEAR_OUTPUT_DIR.mkdir(exist_ok=True)

START_YEARS = [1871, 1900, 1926, 1950, 1970]

ALLOCATIONS = [
    {
        "label": "33/67 股票",
        "short": "A",
        "allocation": {"domestic_stock": 0.33, "global_stock": 0.67},
        "expense": {"domestic_stock": 0.005, "global_stock": 0.005},
    },
    {
        "label": "50/50 股票",
        "short": "B",
        "allocation": {"domestic_stock": 0.50, "global_stock": 0.50},
        "expense": {"domestic_stock": 0.005, "global_stock": 0.005},
    },
    {
        "label": "40/40/20 股债",
        "short": "C",
        "allocation": {"domestic_stock": 0.40, "global_stock": 0.40, "domestic_bond": 0.20},
        "expense": {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005},
    },
    {
        "label": "30/30/40 股债",
        "short": "D",
        "allocation": {"domestic_stock": 0.30, "global_stock": 0.30, "domestic_bond": 0.40},
        "expense": {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005},
    },
]

YEAR_COLORS = {
    1871: "#1f77b4",
    1900: "#e74c3c",
    1926: "#2ecc71",
    1950: "#9b59b6",
    1970: "#f39c12",
}

SUCCESS_THRESHOLDS = [95, 90, 85, 80, 70]


# ═══════════════════════════════════════════════════════════════════════════
# MC 引擎（复用 withdrawal_rate_analysis.py 的核心逻辑）
# ═══════════════════════════════════════════════════════════════════════════

def generate_scenarios_pooled(
    country_dfs: dict[str, pd.DataFrame],
    allocation: dict,
    expense: dict,
    num_sims: int,
    retirement_years: int,
    rng: np.random.Generator,
    weights: dict[str, float] | None = None,
) -> np.ndarray:
    isos = list(country_dfs.keys())
    country_rets = {}
    for iso, cdf in country_dfs.items():
        cdf_sorted = cdf.sort_values("Year").reset_index(drop=True)
        country_rets[iso] = compute_real_portfolio_returns(cdf_sorted, allocation, expense)

    if weights is not None:
        probs = np.array([weights.get(iso, 0.0) for iso in isos])
        probs = probs / probs.sum()
    else:
        probs = np.ones(len(isos)) / len(isos)

    scenarios = np.empty((num_sims, retirement_years))
    for i in range(num_sims):
        idx_list: list[float] = []
        while len(idx_list) < retirement_years:
            c_idx = rng.choice(len(isos), p=probs)
            iso = isos[c_idx]
            ret = country_rets[iso]
            n = len(ret)
            blen = rng.integers(MIN_BLOCK, MAX_BLOCK + 1)
            start = rng.integers(0, n)
            block_idx = (np.arange(start, start + blen) % n).tolist()
            idx_list.extend(ret[block_idx].tolist())
        scenarios[i] = np.array(idx_list[:retirement_years])
    return scenarios


def compute_success_rates(
    scenarios: np.ndarray,
    rates: np.ndarray,
    initial_portfolio: float,
    retirement_years: int,
) -> np.ndarray:
    num_sims = scenarios.shape[0]
    num_rates = len(rates)
    success_rates = np.empty(num_rates)
    growth = 1.0 + scenarios

    for r_idx, rate in enumerate(rates):
        annual_wd = initial_portfolio * rate
        portfolios = np.full(num_sims, initial_portfolio, dtype=np.float64)
        survived = np.ones(num_sims, dtype=bool)

        for year in range(retirement_years):
            portfolios[survived] = portfolios[survived] * growth[survived, year] - annual_wd
            newly_depleted = survived & (portfolios <= 0)
            portfolios[newly_depleted] = 0.0
            survived[newly_depleted] = False
            if not survived.any():
                break

        success_rates[r_idx] = survived.mean()

    return success_rates


def find_safe_wr(rates: np.ndarray, success: np.ndarray, threshold: float) -> float:
    above = success >= threshold / 100.0
    if not above.any():
        return 0.0
    return float(rates[above][-1])


# ═══════════════════════════════════════════════════════════════════════════
# 可视化
# ═══════════════════════════════════════════════════════════════════════════

def plot_main_grid(results: dict) -> None:
    """4 子图：每个配置一个，5 条起始年份曲线（2%-6% 区间）。"""
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))
    axes = axes.flatten()
    mask = (RATES >= 0.02) & (RATES <= 0.06)

    for ax_i, alloc in enumerate(ALLOCATIONS):
        ax = axes[ax_i]
        for sy in START_YEARS:
            key = f"{alloc['short']}_{sy}"
            sr = results[key]["success"]
            n_years = results[key]["n_data_years"]
            ax.plot(
                RATES[mask] * 100, sr[mask] * 100,
                color=YEAR_COLORS[sy], linewidth=2.2,
                label=f"{sy}+ ({n_years}y)",
                marker="o", markersize=1.5,
            )

        for pct in [95, 90, 85, 80, 70, 50]:
            ax.axhline(pct, color="gray", linewidth=0.6, linestyle=":", alpha=0.5)

        ax.set_xlabel("Withdrawal Rate (%)", fontsize=11)
        ax.set_ylabel("Success Rate (%)", fontsize=11)
        ax.set_title(f"{alloc['label']}  (国内/国际/债券)", fontsize=12, fontweight="bold")
        ax.legend(loc="lower left", fontsize=9, framealpha=0.9, title="起始年 (数据量)")
        ax.set_xlim(2, 6)
        ax.set_ylim(0, 105)
        ax.grid(True, alpha=0.3)

    fig.suptitle(
        f"JST 起始年份 vs 成功率曲线（{RETIREMENT_YEARS}年退休, {NUM_SIMS} MC, ALL GDP√池化, 费率0.5%）",
        fontsize=14, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = START_YEAR_OUTPUT_DIR / "start_year_sensitivity.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


def plot_heatmap(safe_wrs: dict) -> None:
    """安全提取率热力图：行=配置，列=起始年份。"""
    alloc_labels = [a["label"] for a in ALLOCATIONS]
    n_alloc = len(ALLOCATIONS)
    n_years = len(START_YEARS)

    fig, axes = plt.subplots(1, 3, figsize=(20, 5))
    for ax_i, thr in enumerate([95, 90, 80]):
        data = np.zeros((n_alloc, n_years))
        for i, alloc in enumerate(ALLOCATIONS):
            for j, sy in enumerate(START_YEARS):
                key = f"{alloc['short']}_{sy}"
                data[i, j] = safe_wrs[key].get(thr, 0) * 100

        im = axes[ax_i].imshow(data, aspect="auto", cmap="RdYlGn", vmin=1.5, vmax=5.5)
        axes[ax_i].set_xticks(range(n_years))
        axes[ax_i].set_xticklabels([str(y) for y in START_YEARS], fontsize=10)
        axes[ax_i].set_yticks(range(n_alloc))
        axes[ax_i].set_yticklabels(alloc_labels, fontsize=10)
        axes[ax_i].set_xlabel("起始年份", fontsize=11)
        axes[ax_i].set_title(f"{thr}% 成功率标准", fontsize=12, fontweight="bold")

        for i in range(n_alloc):
            for j in range(n_years):
                val = data[i, j]
                color = "white" if val < 2.5 or val > 4.5 else "black"
                axes[ax_i].text(j, i, f"{val:.1f}%", ha="center", va="center",
                                fontsize=10, color=color, fontweight="bold")

    fig.colorbar(im, ax=axes, label="Safe WR (%)", shrink=0.8, pad=0.02)
    fig.suptitle("安全提取率 by 起始年份 × 资产配置", fontsize=14, fontweight="bold")
    fig.subplots_adjust(top=0.88, bottom=0.12, wspace=0.3)
    path = START_YEAR_OUTPUT_DIR / "start_year_heatmap.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


def plot_swr_bar(safe_wrs: dict) -> None:
    """90% 安全提取率柱状图：按配置分组，起始年份并列。"""
    fig, ax = plt.subplots(figsize=(14, 7))
    thr = 90
    n_alloc = len(ALLOCATIONS)
    n_years = len(START_YEARS)
    bar_width = 0.15
    x = np.arange(n_alloc)

    for j, sy in enumerate(START_YEARS):
        vals = []
        for alloc in ALLOCATIONS:
            key = f"{alloc['short']}_{sy}"
            vals.append(safe_wrs[key].get(thr, 0) * 100)
        bars = ax.bar(x + j * bar_width, vals, bar_width,
                      label=f"{sy}+", color=YEAR_COLORS[sy], alpha=0.85)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                    f"{val:.1f}", ha="center", va="bottom", fontsize=8)

    ax.set_xlabel("资产配置", fontsize=12)
    ax.set_ylabel("Safe WR (%)", fontsize=12)
    ax.set_title(f"90% 成功率下的安全提取率（{RETIREMENT_YEARS}年退休）", fontsize=14)
    ax.set_xticks(x + bar_width * (n_years - 1) / 2)
    ax.set_xticklabels([a["label"] for a in ALLOCATIONS], fontsize=10)
    ax.legend(title="起始年份", fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    path = START_YEAR_OUTPUT_DIR / "start_year_swr_bar.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


def plot_return_stats(results: dict) -> None:
    """各起始年份 × 配置的年化实际回报统计。"""
    fig, axes = plt.subplots(2, 2, figsize=(18, 12))
    axes = axes.flatten()

    for ax_i, alloc in enumerate(ALLOCATIONS):
        ax = axes[ax_i]
        data_groups = []
        labels = []
        colors = []
        for sy in START_YEARS:
            key = f"{alloc['short']}_{sy}"
            rets = results[key]["scenarios"].flatten() * 100
            data_groups.append(rets)
            labels.append(f"{sy}+")
            colors.append(YEAR_COLORS[sy])

        bp = ax.boxplot(data_groups, vert=True, patch_artist=True, widths=0.6,
                        showfliers=False, medianprops=dict(color="black", linewidth=1.5))
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        ax.set_xticklabels(labels, fontsize=10)
        ax.set_ylabel("Annual Real Return (%)", fontsize=10)
        ax.set_title(f"{alloc['label']}", fontsize=12, fontweight="bold")
        ax.grid(True, axis="y", alpha=0.3)
        ax.axhline(0, color="gray", linewidth=0.8, linestyle="-")

    fig.suptitle("年化实际回报分布 by 起始年份 × 资产配置", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    path = START_YEAR_OUTPUT_DIR / "start_year_returns.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


# ═══════════════════════════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════════════════════════

def write_report(results: dict, safe_wrs: dict) -> None:
    path = START_YEAR_OUTPUT_DIR / "start_year_sensitivity_report.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write("# JST 起始年份敏感性分析报告\n\n")
        f.write(f"**参数**: {RETIREMENT_YEARS}年退休期, {NUM_SIMS}条MC路径, "
                f"初始资产${INITIAL_PORTFOLIO:,}, JST-ALL GDP√池化, 费率0.5%\n\n")

        # 配置说明
        f.write("## 资产配置\n\n")
        f.write("| 代号 | 配置 | 国内股票 | 国际股票 | 债券 |\n")
        f.write("|------|------|---------|---------|------|\n")
        for a in ALLOCATIONS:
            ds = a["allocation"].get("domestic_stock", 0)
            gs = a["allocation"].get("global_stock", 0)
            db = a["allocation"].get("domestic_bond", 0)
            f.write(f"| {a['short']} | {a['label']} | {ds:.0%} | {gs:.0%} | {db:.0%} |\n")

        # 数据覆盖
        f.write("\n## 数据覆盖\n\n")
        f.write("| 起始年份 | 数据年数 (约) | 涵盖重大事件 |\n")
        f.write("|---------|-------------|-------------|\n")
        sample_key = f"A_{START_YEARS[0]}"
        for sy in START_YEARS:
            key = f"A_{sy}"
            n = results[key]["n_data_years"]
            events = []
            if sy <= 1914:
                events.append("一战")
            if sy <= 1929:
                events.append("大萧条")
            if sy <= 1939:
                events.append("二战")
            if sy <= 1973:
                events.append("石油危机")
            events.append("互联网泡沫")
            events.append("2008金融危机")
            events.append("COVID-19")
            f.write(f"| {sy} | ~{n} | {', '.join(events)} |\n")

        # 安全提取率汇总
        f.write("\n## 安全提取率汇总\n\n")
        for thr in [95, 90, 85, 80]:
            f.write(f"### {thr}% 成功率标准\n\n")
            f.write("| 配置 | " + " | ".join(str(y) for y in START_YEARS) + " | 范围 |\n")
            f.write("|------|" + "|".join(["------"] * len(START_YEARS)) + "|------|\n")
            for a in ALLOCATIONS:
                vals = []
                for sy in START_YEARS:
                    key = f"{a['short']}_{sy}"
                    v = safe_wrs[key].get(thr, 0) * 100
                    vals.append(v)
                rng = max(vals) - min(vals)
                f.write(f"| {a['label']} | " +
                        " | ".join(f"{v:.1f}%" for v in vals) +
                        f" | {rng:.1f}pp |\n")
            f.write("\n")

        # 关键提取率对比
        f.write("## 关键提取率下的成功率\n\n")
        for a in ALLOCATIONS:
            f.write(f"### {a['label']}\n\n")
            f.write("| 提取率 | " + " | ".join(str(y) for y in START_YEARS) + " | 差距 |\n")
            f.write("|--------|" + "|".join(["------"] * len(START_YEARS)) + "|------|\n")
            for wr in [0.03, 0.035, 0.04, 0.045, 0.05]:
                idx = np.argmin(np.abs(RATES - wr))
                vals = []
                for sy in START_YEARS:
                    key = f"{a['short']}_{sy}"
                    vals.append(results[key]["success"][idx] * 100)
                spread = max(vals) - min(vals)
                f.write(f"| {wr:.1%} | " +
                        " | ".join(f"{v:.0f}%" for v in vals) +
                        f" | {spread:.1f}pp |\n")
            f.write("\n")

        # 回报统计
        f.write("## 回报特征\n\n")
        f.write("| 配置 | 起始年 | 年化均值 | 标准差 | P5 | P50 | P95 |\n")
        f.write("|------|--------|---------|--------|-----|------|-----|\n")
        for a in ALLOCATIONS:
            for sy in START_YEARS:
                key = f"{a['short']}_{sy}"
                rets = results[key]["scenarios"].flatten() * 100
                f.write(f"| {a['label']} | {sy} | {np.mean(rets):.1f}% | "
                        f"{np.std(rets):.1f}% | {np.percentile(rets, 5):.1f}% | "
                        f"{np.percentile(rets, 50):.1f}% | {np.percentile(rets, 95):.1f}% |\n")

        # 核心洞察
        f.write("\n## 核心洞察\n\n")

        # 1. 总体影响
        all_90_vals = []
        for a in ALLOCATIONS:
            for sy in START_YEARS:
                key = f"{a['short']}_{sy}"
                all_90_vals.append(safe_wrs[key].get(90, 0) * 100)
        f.write(f"### 1. 起始年份对安全提取率的总体影响\n\n")
        f.write(f"在90%成功率标准下，所有配置的安全提取率范围为 "
                f"**{min(all_90_vals):.1f}% ~ {max(all_90_vals):.1f}%**。\n\n")

        # 2. 哪个起始年份最保守
        for a in ALLOCATIONS:
            best_sy, worst_sy = None, None
            best_v, worst_v = -1, 999
            for sy in START_YEARS:
                key = f"{a['short']}_{sy}"
                v = safe_wrs[key].get(90, 0)
                if v > best_v:
                    best_v = v
                    best_sy = sy
                if v < worst_v:
                    worst_v = v
                    worst_sy = sy
            f.write(f"- **{a['label']}**: 最保守={worst_sy}+ ({worst_v:.1%}), "
                    f"最乐观={best_sy}+ ({best_v:.1%}), "
                    f"差距={abs(best_v - worst_v)*100:.1f}pp\n")

        f.write("\n### 2. 债券配置的影响\n\n")
        for sy in START_YEARS:
            pure_stock = safe_wrs[f"A_{sy}"].get(90, 0) * 100
            bond_40 = safe_wrs[f"D_{sy}"].get(90, 0) * 100
            diff = pure_stock - bond_40
            f.write(f"- {sy}+: 纯股票(A) {pure_stock:.1f}% vs 40%债券(D) {bond_40:.1f}% "
                    f"→ 差异 {diff:+.1f}pp\n")

        f.write("\n### 3. 推荐\n\n")
        f.write("基于分析结果：\n\n")
        f.write("1. **推荐采用 1900 年起始**：与 DMS 全球回报年鉴一致，"
                "数据质量合理，覆盖大萧条和两次世界大战等极端尾部风险。\n")
        f.write("2. **避免仅用 1970+ 数据**：样本量偏小（~50年），"
                "可能过于乐观（缺少大萧条等极端场景）。\n")
        f.write("3. **1871 vs 1900 差异通常较小**：说明 1871-1900 的数据"
                "虽然质量较差，但对总体分布影响有限。\n\n")

        f.write("## 图表清单\n\n")
        f.write("- `start_year_sensitivity.png`: 4配置×5起始年成功率曲线\n")
        f.write("- `start_year_heatmap.png`: 安全提取率热力图\n")
        f.write("- `start_year_swr_bar.png`: 90%安全提取率柱状图\n")
        f.write("- `start_year_returns.png`: 回报分布箱线图\n")
        f.write("- `start_year_sensitivity.csv`: 完整数据\n")

    print(f"  Report saved: {path}")


# ═══════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    print("=" * 70)
    print("  JST 起始年份敏感性分析")
    print("=" * 70)

    jst_df = load_returns_data()

    results: dict[str, dict] = {}
    safe_wrs: dict[str, dict] = {}

    total = len(START_YEARS) * len(ALLOCATIONS)
    count = 0

    for sy in START_YEARS:
        country_dfs = get_country_dfs(jst_df, sy)
        n_countries = len(country_dfs)
        sample_n = sum(len(df) for df in country_dfs.values())
        avg_years = sample_n // n_countries if n_countries > 0 else 0
        gdp_weights = get_gdp_weights(list(country_dfs.keys()))

        print(f"\n{'─'*50}")
        print(f"  起始年份: {sy}  ({n_countries} 国家, 平均 {avg_years} 年/国)")
        print(f"{'─'*50}")

        for alloc in ALLOCATIONS:
            count += 1
            key = f"{alloc['short']}_{sy}"
            print(f"  [{count}/{total}] {alloc['label']} ... ", end="", flush=True)

            rng = np.random.default_rng(SEED)
            scenarios = generate_scenarios_pooled(
                country_dfs, alloc["allocation"], alloc["expense"],
                NUM_SIMS, RETIREMENT_YEARS, rng, gdp_weights,
            )
            success = compute_success_rates(scenarios, RATES, INITIAL_PORTFOLIO, RETIREMENT_YEARS)

            swrs = {}
            for thr in SUCCESS_THRESHOLDS:
                swrs[thr] = find_safe_wr(RATES, success, thr)

            results[key] = {
                "success": success,
                "scenarios": scenarios,
                "n_data_years": avg_years,
            }
            safe_wrs[key] = swrs

            print(f"SWR@90%={swrs[90]:.1%}, SWR@80%={swrs[80]:.1%}")

    elapsed = time.time() - t0
    print(f"\n  Simulation complete in {elapsed:.1f}s")

    # CSV 输出
    print("\nSaving CSV...")
    csv_data = {"withdrawal_rate": RATES}
    for alloc in ALLOCATIONS:
        for sy in START_YEARS:
            key = f"{alloc['short']}_{sy}"
            csv_data[f"{alloc['short']}_{sy}_success"] = results[key]["success"]
    csv_df = pd.DataFrame(csv_data)
    csv_path = START_YEAR_OUTPUT_DIR / "start_year_sensitivity.csv"
    csv_df.to_csv(csv_path, index=False, float_format="%.6f")
    print(f"  Saved: {csv_path}")

    # 图表
    print("\nGenerating plots...")
    plot_main_grid(results)
    plot_heatmap(safe_wrs)
    plot_swr_bar(safe_wrs)
    plot_return_stats(results)

    # 报告
    print("\nWriting report...")
    write_report(results, safe_wrs)

    print(f"\nTotal elapsed: {time.time() - t0:.1f}s")
    print("Done!")


if __name__ == "__main__":
    main()
