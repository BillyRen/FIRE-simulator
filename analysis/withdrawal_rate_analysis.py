#!/usr/bin/env python3
"""提取率-成功率曲线对比分析。

对比 5 种数据源/配置下，不同固定提取率的 Monte Carlo 成功率。
全向量化实现，高效运行。
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

# 尝试加载中文字体
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

from simulator.data_loader import load_returns_data, load_fire_dataset, get_country_dfs, filter_by_country
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

SCENARIOS = [
    {
        "label": "JST-ALL-GDP√",
        "source": "jst",
        "country": "ALL",
        "pooling": "gdp_sqrt",
        "data_start_year": None,
        "allocation": {"domestic_stock": 0.33, "global_stock": 0.67},
        "expense": {"domestic_stock": 0.005, "global_stock": 0.005},
        "color": "#e74c3c",
        "linestyle": "-",
    },
    {
        "label": "JST-USA",
        "source": "jst",
        "country": "USA",
        "pooling": None,
        "data_start_year": None,
        "allocation": {"domestic_stock": 0.33, "global_stock": 0.67},
        "expense": {"domestic_stock": 0.005, "global_stock": 0.005},
        "color": "#2ecc71",
        "linestyle": "-",
    },
    {
        "label": "FIRE-1970-高费",
        "source": "fire",
        "country": "USA",
        "pooling": None,
        "data_start_year": 1970,
        "allocation": {"domestic_stock": 0.33, "global_stock": 0.67},
        "expense": {"domestic_stock": 0.025, "global_stock": 0.005},
        "color": "#3498db",
        "linestyle": "-",
    },
    {
        "label": "FIRE-1970-低费",
        "source": "fire",
        "country": "USA",
        "pooling": None,
        "data_start_year": 1970,
        "allocation": {"domestic_stock": 0.33, "global_stock": 0.67},
        "expense": {"domestic_stock": 0.005, "global_stock": 0.005},
        "color": "#9b59b6",
        "linestyle": "--",
    },
    {
        "label": "FIRE-ALL-US",
        "source": "fire",
        "country": "USA",
        "pooling": None,
        "data_start_year": None,
        "allocation": {"domestic_stock": 1.0, "global_stock": 0.0},
        "expense": {"domestic_stock": 0.015, "global_stock": 0.0},
        "color": "#f39c12",
        "linestyle": "-",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# 向量化 bootstrap + 模拟
# ═══════════════════════════════════════════════════════════════════════════

def generate_scenarios_single(
    returns_df: pd.DataFrame,
    allocation: dict,
    expense: dict,
    num_sims: int,
    retirement_years: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """从单一国家数据生成向量化的 MC real-return scenarios。"""
    real_ret = compute_real_portfolio_returns(returns_df, allocation, expense)
    n = len(real_ret)

    scenarios = np.empty((num_sims, retirement_years))
    for i in range(num_sims):
        idx = []
        while len(idx) < retirement_years:
            blen = rng.integers(MIN_BLOCK, MAX_BLOCK + 1)
            start = rng.integers(0, n)
            idx.extend((np.arange(start, start + blen) % n).tolist())
        scenarios[i] = real_ret[np.array(idx[:retirement_years])]
    return scenarios


def generate_scenarios_pooled(
    country_dfs: dict[str, pd.DataFrame],
    allocation: dict,
    expense: dict,
    num_sims: int,
    retirement_years: int,
    rng: np.random.Generator,
    weights: dict[str, float] | None = None,
) -> np.ndarray:
    """从多国池化数据生成向量化的 MC real-return scenarios (GDP-sqrt 加权)。"""
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
    """向量化计算每个提取率的成功率。

    scenarios: (num_sims, retirement_years) 实际回报率
    rates: (num_rates,) 提取率数组
    返回: (num_rates,) 成功率数组
    """
    num_sims = scenarios.shape[0]
    num_rates = len(rates)
    success_rates = np.empty(num_rates)

    growth = 1.0 + scenarios  # (num_sims, retirement_years)

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


def compute_funded_ratios(
    scenarios: np.ndarray,
    rates: np.ndarray,
    initial_portfolio: float,
    retirement_years: int,
) -> np.ndarray:
    """向量化计算每个提取率的中位覆盖率。"""
    num_sims = scenarios.shape[0]
    num_rates = len(rates)
    median_funded = np.empty(num_rates)
    growth = 1.0 + scenarios

    for r_idx, rate in enumerate(rates):
        annual_wd = initial_portfolio * rate
        portfolios = np.full(num_sims, initial_portfolio, dtype=np.float64)
        depletion_years = np.full(num_sims, retirement_years, dtype=np.float64)

        for year in range(retirement_years):
            portfolios = portfolios * growth[:, year] - annual_wd
            depleted = (portfolios <= 0) & (depletion_years == retirement_years)
            depletion_years[depleted] = year + 1
            portfolios[depleted] = 0.0

        median_funded[r_idx] = np.median(depletion_years / retirement_years)

    return median_funded


# ═══════════════════════════════════════════════════════════════════════════
# 可视化
# ═══════════════════════════════════════════════════════════════════════════

def plot_success_curves(results: dict, rates: np.ndarray) -> None:
    """主图：成功率曲线对比。"""
    fig, ax = plt.subplots(figsize=(14, 8))

    for sc in SCENARIOS:
        label = sc["label"]
        ax.plot(rates * 100, results[label]["success"] * 100,
                color=sc["color"], linestyle=sc["linestyle"],
                linewidth=2.2, label=label)

    ax.axhline(95, color="gray", linewidth=0.8, linestyle=":", alpha=0.6)
    ax.axhline(90, color="gray", linewidth=0.8, linestyle=":", alpha=0.6)
    ax.axhline(80, color="gray", linewidth=0.8, linestyle=":", alpha=0.6)
    ax.axhline(50, color="gray", linewidth=0.8, linestyle=":", alpha=0.4)

    for pct in [95, 90, 80, 50]:
        ax.text(rates[-1] * 100 + 0.1, pct, f"{pct}%", va="center",
                fontsize=8, color="gray")

    for wr in [3.0, 3.5, 4.0]:
        ax.axvline(wr, color="gray", linewidth=0.6, linestyle="--", alpha=0.4)

    ax.set_xlabel("Withdrawal Rate (%)", fontsize=12)
    ax.set_ylabel("Success Rate (%)", fontsize=12)
    ax.set_title(f"Withdrawal Rate vs Success Rate ({RETIREMENT_YEARS}-Year, {NUM_SIMS} MC Paths)", fontsize=14)
    ax.legend(loc="lower left", fontsize=10, framealpha=0.9)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_success_curves.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_success_curves.png'}")


def plot_success_zoomed(results: dict, rates: np.ndarray) -> None:
    """放大图：2%-6% 提取率区间。"""
    mask = (rates >= 0.02) & (rates <= 0.06)
    fig, ax = plt.subplots(figsize=(14, 8))

    for sc in SCENARIOS:
        label = sc["label"]
        ax.plot(rates[mask] * 100, results[label]["success"][mask] * 100,
                color=sc["color"], linestyle=sc["linestyle"],
                linewidth=2.5, label=label, marker="o", markersize=2)

    for pct in [95, 90, 85, 80, 70, 50]:
        ax.axhline(pct, color="gray", linewidth=0.7, linestyle=":", alpha=0.5)
        ax.text(6.05, pct, f"{pct}%", va="center", fontsize=8, color="gray")

    ax.set_xlabel("Withdrawal Rate (%)", fontsize=12)
    ax.set_ylabel("Success Rate (%)", fontsize=12)
    ax.set_title(f"Success Rate Detail (2%-6%, {RETIREMENT_YEARS}-Year)", fontsize=14)
    ax.legend(loc="lower left", fontsize=10, framealpha=0.9)
    ax.set_xlim(2, 6)
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_success_zoomed.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_success_zoomed.png'}")


def plot_funded_ratio(results: dict, rates: np.ndarray) -> None:
    """中位覆盖率曲线。"""
    mask = (rates >= 0.02) & (rates <= 0.08)
    fig, ax = plt.subplots(figsize=(14, 8))

    for sc in SCENARIOS:
        label = sc["label"]
        ax.plot(rates[mask] * 100, results[label]["funded"][mask] * 100,
                color=sc["color"], linestyle=sc["linestyle"],
                linewidth=2.2, label=label)

    ax.axhline(100, color="gray", linewidth=0.8, linestyle=":", alpha=0.5)
    ax.set_xlabel("Withdrawal Rate (%)", fontsize=12)
    ax.set_ylabel("Median Funded Ratio (%)", fontsize=12)
    ax.set_title(f"Withdrawal Rate vs Median Funded Ratio ({RETIREMENT_YEARS}-Year)", fontsize=14)
    ax.legend(loc="lower left", fontsize=10, framealpha=0.9)
    ax.set_xlim(2, 8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_funded_ratio.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_funded_ratio.png'}")


def plot_scenario_spread(results: dict, rates: np.ndarray) -> None:
    """场景间差距图：各提取率下成功率的最大最小值之差。"""
    mask = (rates >= 0.02) & (rates <= 0.07)
    all_sr = np.array([results[sc["label"]]["success"] for sc in SCENARIOS])
    spread = (all_sr.max(axis=0) - all_sr.min(axis=0)) * 100

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.fill_between(rates[mask] * 100, 0, spread[mask], alpha=0.3, color="#e74c3c")
    ax.plot(rates[mask] * 100, spread[mask], color="#e74c3c", linewidth=2)
    ax.set_xlabel("Withdrawal Rate (%)", fontsize=12)
    ax.set_ylabel("Max - Min Success Rate (pp)", fontsize=12)
    ax.set_title("Cross-Scenario Disagreement by Withdrawal Rate", fontsize=14)
    ax.set_xlim(2, 7)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_scenario_spread.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_scenario_spread.png'}")


def plot_safe_wr_comparison(safe_wrs: dict) -> None:
    """安全提取率柱状图。"""
    thresholds = [95, 90, 80]
    labels = [sc["label"] for sc in SCENARIOS]
    colors = [sc["color"] for sc in SCENARIOS]

    fig, axes = plt.subplots(1, 3, figsize=(16, 6), sharey=True)
    for ax_i, thr in enumerate(thresholds):
        vals = [safe_wrs[lab].get(thr, 0) * 100 for lab in labels]
        bars = axes[ax_i].barh(range(len(labels)), vals, color=colors, height=0.6)
        axes[ax_i].set_title(f"{thr}% Success Threshold", fontsize=12)
        axes[ax_i].set_xlabel("Safe Withdrawal Rate (%)")
        axes[ax_i].set_yticks(range(len(labels)))
        axes[ax_i].set_yticklabels(labels, fontsize=9)
        axes[ax_i].set_xlim(0, max(vals) * 1.3 if max(vals) > 0 else 5)
        axes[ax_i].grid(True, axis="x", alpha=0.3)
        for bar, val in zip(bars, vals):
            axes[ax_i].text(val + 0.05, bar.get_y() + bar.get_height() / 2,
                           f"{val:.1f}%", va="center", fontsize=9)

    fig.suptitle(f"Safe Withdrawal Rates by Scenario ({RETIREMENT_YEARS}-Year)", fontsize=14)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_safe_comparison.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_safe_comparison.png'}")


def plot_heatmap(results: dict, rates: np.ndarray) -> None:
    """成功率热力图：场景 × 提取率。"""
    labels = [sc["label"] for sc in SCENARIOS]
    wr_ticks = np.arange(0.01, 0.081, 0.005)
    wr_indices = [np.argmin(np.abs(rates - w)) for w in wr_ticks]

    data = np.array([[results[lab]["success"][idx] * 100 for idx in wr_indices]
                     for lab in labels])

    fig, ax = plt.subplots(figsize=(16, 5))
    im = ax.imshow(data, aspect="auto", cmap="RdYlGn", vmin=0, vmax=100)
    ax.set_xticks(range(len(wr_ticks)))
    ax.set_xticklabels([f"{w*100:.1f}%" for w in wr_ticks], rotation=45, fontsize=8)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("Withdrawal Rate", fontsize=12)
    ax.set_title(f"Success Rate Heatmap ({RETIREMENT_YEARS}-Year)", fontsize=14)

    for i in range(len(labels)):
        for j in range(len(wr_ticks)):
            val = data[i, j]
            color = "white" if val < 40 or val > 85 else "black"
            ax.text(j, i, f"{val:.0f}", ha="center", va="center",
                    fontsize=7, color=color, fontweight="bold")

    fig.colorbar(im, ax=ax, label="Success Rate (%)", shrink=0.8)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_heatmap.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_heatmap.png'}")


def plot_return_distributions(results: dict) -> None:
    """各场景的年化实际回报分布（箱线图+小提琴图）。"""
    labels = [sc["label"] for sc in SCENARIOS]
    colors = [sc["color"] for sc in SCENARIOS]

    mean_rets = [results[lab]["scenarios"].mean(axis=1) * 100 for lab in labels]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    bp = ax1.boxplot(mean_rets, vert=True, patch_artist=True, widths=0.6,
                     showfliers=False, medianprops=dict(color="black", linewidth=1.5))
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax1.set_xticklabels(labels, rotation=20, fontsize=9)
    ax1.set_ylabel("Mean Path Return (%/year)", fontsize=11)
    ax1.set_title("Return Distribution by Scenario", fontsize=13)
    ax1.grid(True, axis="y", alpha=0.3)

    for i, (lab, rets) in enumerate(zip(labels, mean_rets)):
        stats = {
            "mean": np.mean(rets),
            "std": np.std(rets),
            "p5": np.percentile(rets, 5),
            "p50": np.percentile(rets, 50),
        }
        ax1.text(i + 1, ax1.get_ylim()[1] * 0.95,
                f"μ={stats['mean']:.1f}\nσ={stats['std']:.1f}",
                ha="center", va="top", fontsize=7,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

    annual_rets = [results[lab]["scenarios"].flatten() * 100 for lab in labels]
    for i, (rets, color, lab) in enumerate(zip(annual_rets, colors, labels)):
        hist_vals, bin_edges = np.histogram(rets, bins=100, range=(-60, 80), density=True)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        ax2.plot(bin_centers, hist_vals, color=color, linewidth=1.5, label=lab, alpha=0.8)
        ax2.fill_between(bin_centers, hist_vals, alpha=0.1, color=color)

    ax2.set_xlabel("Annual Real Return (%)", fontsize=11)
    ax2.set_ylabel("Density", fontsize=11)
    ax2.set_title("Annual Return Distribution", fontsize=13)
    ax2.legend(fontsize=8, loc="upper right")
    ax2.set_xlim(-50, 70)
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_return_distributions.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_return_distributions.png'}")


def plot_fee_impact(results: dict, rates: np.ndarray) -> None:
    """费率影响专题图。"""
    mask = (rates >= 0.02) & (rates <= 0.07)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    s_high = results["FIRE-1970-高费"]["success"][mask] * 100
    s_low = results["FIRE-1970-低费"]["success"][mask] * 100
    diff = s_low - s_high

    ax1.plot(rates[mask] * 100, s_high, color="#3498db", linewidth=2.2,
             label="FIRE-1970-高费 (dom 2.5%)")
    ax1.plot(rates[mask] * 100, s_low, color="#9b59b6", linewidth=2.2,
             label="FIRE-1970-低费 (dom 0.5%)")
    ax1.fill_between(rates[mask] * 100, s_high, s_low, alpha=0.15, color="#8e44ad")
    ax1.set_xlabel("Withdrawal Rate (%)", fontsize=11)
    ax1.set_ylabel("Success Rate (%)", fontsize=11)
    ax1.set_title("Fee Impact: 2.5% vs 0.5% Domestic Fee", fontsize=13)
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2.bar(rates[mask] * 100, diff, width=0.08, color="#8e44ad", alpha=0.7)
    ax2.set_xlabel("Withdrawal Rate (%)", fontsize=11)
    ax2.set_ylabel("Success Rate Improvement (pp)", fontsize=11)
    ax2.set_title("Low Fee Advantage (pp)", fontsize=13)
    ax2.grid(True, axis="y", alpha=0.3)
    ax2.axhline(0, color="gray", linewidth=0.5)

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_fee_impact.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_fee_impact.png'}")


def plot_us_exceptionalism(results: dict, rates: np.ndarray) -> None:
    """美国例外论专题图。"""
    mask = (rates >= 0.02) & (rates <= 0.07)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    s_all = results["JST-ALL-GDP√"]["success"][mask] * 100
    s_usa = results["JST-USA"]["success"][mask] * 100
    s_fire = results["FIRE-ALL-US"]["success"][mask] * 100

    ax1.plot(rates[mask] * 100, s_all, color="#e74c3c", linewidth=2.2, label="JST-ALL-GDP√ (16 countries)")
    ax1.plot(rates[mask] * 100, s_usa, color="#2ecc71", linewidth=2.2, label="JST-USA")
    ax1.plot(rates[mask] * 100, s_fire, color="#f39c12", linewidth=2.2, label="FIRE-ALL-US (100% dom)")
    ax1.fill_between(rates[mask] * 100, s_all, s_usa, alpha=0.12, color="#c0392b")
    ax1.set_xlabel("Withdrawal Rate (%)", fontsize=11)
    ax1.set_ylabel("Success Rate (%)", fontsize=11)
    ax1.set_title("US Exceptionalism: Global vs US-Only", fontsize=13)
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    gap_jst = s_usa - s_all
    gap_fire = s_fire - s_all
    ax2.plot(rates[mask] * 100, gap_jst, color="#2ecc71", linewidth=2,
             label="JST-USA minus JST-ALL")
    ax2.plot(rates[mask] * 100, gap_fire, color="#f39c12", linewidth=2,
             label="FIRE-ALL-US minus JST-ALL")
    ax2.axhline(0, color="gray", linewidth=0.5)
    ax2.fill_between(rates[mask] * 100, 0, gap_jst, alpha=0.1, color="#2ecc71")
    ax2.set_xlabel("Withdrawal Rate (%)", fontsize=11)
    ax2.set_ylabel("Success Rate Difference (pp)", fontsize=11)
    ax2.set_title("US Advantage over Global Baseline (pp)", fontsize=13)
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_us_exceptionalism.png", dpi=150)
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_us_exceptionalism.png'}")


def plot_portfolio_survival(results: dict, rates: np.ndarray) -> None:
    """3个关键提取率下的资产存活曲线。"""
    key_rates = [0.03, 0.04, 0.05]
    fig, axes = plt.subplots(1, 3, figsize=(18, 5), sharey=True)

    for ax, wr in zip(axes, key_rates):
        for sc in SCENARIOS:
            lab = sc["label"]
            scenarios = results[lab]["scenarios"]
            annual_wd = INITIAL_PORTFOLIO * wr

            portfolios = np.full(scenarios.shape[0], INITIAL_PORTFOLIO, dtype=np.float64)
            survival = np.zeros(RETIREMENT_YEARS)

            for year in range(RETIREMENT_YEARS):
                portfolios = portfolios * (1.0 + scenarios[:, year]) - annual_wd
                portfolios = np.maximum(portfolios, 0.0)
                survival[year] = (portfolios > 0).mean() * 100

            ax.plot(range(1, RETIREMENT_YEARS + 1), survival,
                    color=sc["color"], linestyle=sc["linestyle"],
                    linewidth=1.8, label=lab)

        ax.set_xlabel("Year", fontsize=10)
        ax.set_title(f"WR = {wr:.0%}", fontsize=12)
        ax.axhline(50, color="gray", linewidth=0.5, linestyle=":")
        ax.set_xlim(0, RETIREMENT_YEARS)
        ax.set_ylim(0, 105)
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("Portfolio Survival (%)", fontsize=11)
    axes[0].legend(fontsize=7, loc="lower left")
    fig.suptitle(f"Portfolio Survival Curves by Year ({RETIREMENT_YEARS}-Year Horizon)", fontsize=14, y=1.02)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "wr_survival_curves.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {OUTPUT_DIR / 'wr_survival_curves.png'}")


# ═══════════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════════

def find_safe_wr(rates: np.ndarray, success: np.ndarray, threshold: float) -> float:
    """找到满足 success >= threshold 的最大提取率。"""
    mask = success >= threshold
    if not mask.any():
        return 0.0
    return float(rates[mask][-1])


def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║       提取率-成功率曲线对比分析                                ║")
    print(f"║  {NUM_SIMS} MC paths × {len(RATES)} rates × {len(SCENARIOS)} scenarios             ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # 加载数据
    print("Loading data...")
    t0 = time.time()
    jst_df = load_returns_data()
    fire_df = load_fire_dataset()
    print(f"  JST: {len(jst_df)} rows, FIRE: {len(fire_df)} rows ({time.time()-t0:.1f}s)")

    results: dict[str, dict] = {}

    for sc in SCENARIOS:
        label = sc["label"]
        print(f"\n{'='*60}")
        print(f"  Scenario: {label}")
        print(f"{'='*60}")

        rng = np.random.default_rng(SEED)
        t0 = time.time()

        # 生成 MC scenarios
        if sc["source"] == "jst" and sc["country"] == "ALL":
            start_year = sc["data_start_year"]
            country_dfs = get_country_dfs(jst_df, start_year) if start_year else get_country_dfs(jst_df, 1871)
            weights = get_gdp_weights(list(country_dfs.keys())) if sc["pooling"] == "gdp_sqrt" else None
            print(f"  Countries: {len(country_dfs)}, pooling={sc['pooling']}")
            if weights:
                top3 = sorted(weights.items(), key=lambda x: -x[1])[:3]
                print(f"  Top weights: {', '.join(f'{k}={v:.1%}' for k, v in top3)}")
            scenarios = generate_scenarios_pooled(
                country_dfs, sc["allocation"], sc["expense"],
                NUM_SIMS, RETIREMENT_YEARS, rng, weights,
            )
        elif sc["source"] == "jst":
            df = filter_by_country(jst_df, sc["country"],
                                   sc["data_start_year"] or 1871)
            print(f"  Data: JST {sc['country']}, {len(df)} years")
            scenarios = generate_scenarios_single(
                df, sc["allocation"], sc["expense"],
                NUM_SIMS, RETIREMENT_YEARS, rng,
            )
        else:
            df = fire_df.copy()
            if sc["data_start_year"]:
                df = df[df["Year"] >= sc["data_start_year"]].reset_index(drop=True)
            print(f"  Data: FIRE {sc['country']}, {len(df)} years (from {int(df['Year'].min())})")
            scenarios = generate_scenarios_single(
                df, sc["allocation"], sc["expense"],
                NUM_SIMS, RETIREMENT_YEARS, rng,
            )

        t_gen = time.time() - t0
        mean_ret = scenarios.mean() * 100
        std_ret = scenarios.std() * 100
        print(f"  Scenarios: {scenarios.shape}, mean={mean_ret:.2f}%, std={std_ret:.2f}% ({t_gen:.1f}s)")

        # 计算成功率
        t0 = time.time()
        success = compute_success_rates(scenarios, RATES, INITIAL_PORTFOLIO, RETIREMENT_YEARS)
        t_sr = time.time() - t0

        # 计算覆盖率
        t0 = time.time()
        funded = compute_funded_ratios(scenarios, RATES, INITIAL_PORTFOLIO, RETIREMENT_YEARS)
        t_fr = time.time() - t0

        results[label] = {"success": success, "funded": funded, "scenarios": scenarios}
        print(f"  Success rates computed ({t_sr:.1f}s), funded ratios ({t_fr:.1f}s)")

        # 关键提取率
        for wr in [0.03, 0.035, 0.04, 0.05]:
            idx = np.argmin(np.abs(RATES - wr))
            print(f"    WR={wr:.1%}: success={success[idx]:.1%}, funded={funded[idx]:.3f}")

    # ── 安全提取率汇总 ──
    print(f"\n{'='*70}")
    print("  Safe Withdrawal Rates (最高提取率使得成功率 >= 阈值)")
    print(f"{'='*70}")
    safe_wrs: dict[str, dict] = {}
    for sc in SCENARIOS:
        label = sc["label"]
        safe_wrs[label] = {}
        vals = []
        for thr in [95, 90, 85, 80, 70, 50]:
            swr = find_safe_wr(RATES, results[label]["success"], thr / 100)
            safe_wrs[label][thr] = swr
            vals.append(f"{thr}%→{swr:.1%}")
        print(f"  {label:20s}: {', '.join(vals)}")

    # ── 场景间差距分析 ──
    print(f"\n{'='*70}")
    print("  Cross-Scenario Spread (成功率最大-最小差距)")
    print(f"{'='*70}")
    all_sr = np.array([results[sc["label"]]["success"] for sc in SCENARIOS])
    spread = (all_sr.max(axis=0) - all_sr.min(axis=0)) * 100
    for wr in [0.02, 0.025, 0.03, 0.035, 0.04, 0.045, 0.05, 0.06]:
        idx = np.argmin(np.abs(RATES - wr))
        vals_str = "  ".join(f"{sc['label'][:12]:>12}={results[sc['label']]['success'][idx]:.1%}"
                             for sc in SCENARIOS)
        print(f"  WR={wr:.1%}: spread={spread[idx]:.1f}pp  | {vals_str}")

    max_spread_idx = np.argmax(spread)
    print(f"\n  Maximum spread: {spread[max_spread_idx]:.1f}pp at WR={RATES[max_spread_idx]:.1%}")

    # ── 保存 CSV ──
    csv_data = {"withdrawal_rate": RATES}
    for sc in SCENARIOS:
        label = sc["label"]
        csv_data[f"{label}_success"] = results[label]["success"]
        csv_data[f"{label}_funded"] = results[label]["funded"]
    csv_df = pd.DataFrame(csv_data)
    csv_path = OUTPUT_DIR / "wr_analysis.csv"
    csv_df.to_csv(csv_path, index=False, float_format="%.6f")
    print(f"\n  CSV saved: {csv_path}")

    # ── 生成图表 ──
    print("\nGenerating plots...")
    plot_success_curves(results, RATES)
    plot_success_zoomed(results, RATES)
    plot_funded_ratio(results, RATES)
    plot_scenario_spread(results, RATES)
    plot_safe_wr_comparison(safe_wrs)
    plot_heatmap(results, RATES)
    plot_return_distributions(results)
    plot_fee_impact(results, RATES)
    plot_us_exceptionalism(results, RATES)
    plot_portfolio_survival(results, RATES)

    # ── 洞察报告 ──
    print(f"\n{'='*70}")
    print("  INSIGHTS REPORT")
    print(f"{'='*70}")

    labels = [sc["label"] for sc in SCENARIOS]
    swr_95 = {lab: safe_wrs[lab][95] for lab in labels}
    swr_90 = {lab: safe_wrs[lab][90] for lab in labels}

    most_conservative = min(swr_95, key=swr_95.get)
    most_optimistic = max(swr_95, key=swr_95.get)

    print(f"""
  1. SAFE WITHDRAWAL RATE RANGE (95% success):
     Most conservative: {most_conservative} → {swr_95[most_conservative]:.1%}
     Most optimistic:   {most_optimistic} → {swr_95[most_optimistic]:.1%}
     Range: {swr_95[most_conservative]:.1%} ~ {swr_95[most_optimistic]:.1%}

  2. 4% RULE TEST ({RETIREMENT_YEARS}-year horizon):""")
    for lab in labels:
        idx_4 = np.argmin(np.abs(RATES - 0.04))
        sr = results[lab]["success"][idx_4]
        verdict = "PASS" if sr >= 0.90 else ("MARGINAL" if sr >= 0.80 else "FAIL")
        print(f"     {lab:20s}: {sr:.1%} [{verdict}]")

    wr_3 = np.argmin(np.abs(RATES - 0.03))
    wr_35 = np.argmin(np.abs(RATES - 0.035))
    wr_4 = np.argmin(np.abs(RATES - 0.04))
    wr_5 = np.argmin(np.abs(RATES - 0.05))

    print(f"""
  3. CONSENSUS ZONES:
     At WR=3.0%: all scenarios agree within {spread[wr_3]:.1f}pp
     At WR=3.5%: all scenarios agree within {spread[wr_35]:.1f}pp
     At WR=4.0%: all scenarios agree within {spread[wr_4]:.1f}pp
     At WR=5.0%: all scenarios agree within {spread[wr_5]:.1f}pp

  4. FEE IMPACT (FIRE-1970 高费 vs 低费):
     At WR=3.5%: {results['FIRE-1970-高费']['success'][wr_35]:.1%} vs {results['FIRE-1970-低费']['success'][wr_35]:.1%}
     At WR=4.0%: {results['FIRE-1970-高费']['success'][wr_4]:.1%} vs {results['FIRE-1970-低费']['success'][wr_4]:.1%}
     At WR=5.0%: {results['FIRE-1970-高费']['success'][wr_5]:.1%} vs {results['FIRE-1970-低费']['success'][wr_5]:.1%}

  5. US EXCEPTIONALISM TEST (JST-ALL vs JST-USA):
     At WR=3.5%: {results['JST-ALL-GDP√']['success'][wr_35]:.1%} vs {results['JST-USA']['success'][wr_35]:.1%}
     At WR=4.0%: {results['JST-ALL-GDP√']['success'][wr_4]:.1%} vs {results['JST-USA']['success'][wr_4]:.1%}
     At WR=5.0%: {results['JST-ALL-GDP√']['success'][wr_5]:.1%} vs {results['JST-USA']['success'][wr_5]:.1%}
""")

    # ── 写入洞察报告 Markdown ──
    report_path = OUTPUT_DIR / "wr_analysis_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# 提取率-成功率曲线对比分析报告\n\n")
        f.write(f"**参数**: {RETIREMENT_YEARS}年退休期, {NUM_SIMS}条MC路径, 初始资产${INITIAL_PORTFOLIO:,}\n\n")

        f.write("## 场景配置\n\n")
        f.write("| # | 标签 | 数据源 | 配置 | 费率 |\n")
        f.write("|---|------|--------|------|------|\n")
        for i, sc in enumerate(SCENARIOS, 1):
            alloc_str = "/".join(f"{int(v*100)}" for v in sc["allocation"].values())
            exp_str = "/".join(f"{v*100:.1f}%" for v in sc["expense"].values())
            src = f"{sc['source'].upper()} {sc['country']}"
            if sc["data_start_year"]:
                src += f" ({sc['data_start_year']}+)"
            if sc["pooling"]:
                src += f" [{sc['pooling']}]"
            f.write(f"| {i} | {sc['label']} | {src} | {alloc_str} | {exp_str} |\n")

        f.write("\n## 安全提取率汇总\n\n")
        f.write("| 场景 | 95%成功 | 90%成功 | 85%成功 | 80%成功 |\n")
        f.write("|------|---------|---------|---------|--------|\n")
        for lab in labels:
            f.write(f"| {lab} | {safe_wrs[lab][95]:.1%} | {safe_wrs[lab][90]:.1%} | {safe_wrs[lab][85]:.1%} | {safe_wrs[lab][80]:.1%} |\n")

        f.write("\n## 关键提取率对比\n\n")
        f.write("| 提取率 | " + " | ".join(labels) + " | 差距 |\n")
        f.write("|--------|" + "|".join(["--------"] * len(labels)) + "|------|\n")
        for wr_val in [0.025, 0.03, 0.035, 0.04, 0.045, 0.05, 0.06]:
            idx = np.argmin(np.abs(RATES - wr_val))
            vals = [results[lab]["success"][idx] for lab in labels]
            f.write(f"| {wr_val:.1%} | " + " | ".join(f"{v:.1%}" for v in vals) + f" | {(max(vals)-min(vals))*100:.1f}pp |\n")

        f.write("\n## 核心洞察\n\n")
        f.write(f"### 1. 安全提取率范围\n\n")
        f.write(f"在95%成功率标准下，5种场景的安全提取率范围为 **{min(swr_95.values()):.1%} ~ {max(swr_95.values()):.1%}**。\n\n")
        f.write(f"- 最保守: {most_conservative} ({swr_95[most_conservative]:.1%})\n")
        f.write(f"- 最乐观: {most_optimistic} ({swr_95[most_optimistic]:.1%})\n\n")

        f.write(f"### 2. 4%法则在{RETIREMENT_YEARS}年退休期的适用性\n\n")
        for lab in labels:
            sr = results[lab]["success"][wr_4]
            f.write(f"- **{lab}**: {sr:.1%}")
            if sr >= 0.90:
                f.write(" ✓\n")
            elif sr >= 0.80:
                f.write(" △ (边缘)\n")
            else:
                f.write(" ✗\n")

        f.write(f"\n### 3. 费率影响\n\n")
        fee_diff_35 = results["FIRE-1970-低费"]["success"][wr_35] - results["FIRE-1970-高费"]["success"][wr_35]
        fee_diff_4 = results["FIRE-1970-低费"]["success"][wr_4] - results["FIRE-1970-高费"]["success"][wr_4]
        f.write(f"美股费率从0.5%提高到2.5%（+2.0pp），对成功率的影响:\n\n")
        f.write(f"- WR=3.5%: 成功率下降 {fee_diff_35*100:.1f}pp\n")
        f.write(f"- WR=4.0%: 成功率下降 {fee_diff_4*100:.1f}pp\n\n")

        swr_diff = safe_wrs["FIRE-1970-低费"][95] - safe_wrs["FIRE-1970-高费"][95]
        f.write(f"95%安全提取率差异: {swr_diff*100:.1f}pp（低费={safe_wrs['FIRE-1970-低费'][95]:.1%}, 高费={safe_wrs['FIRE-1970-高费'][95]:.1%}）\n\n")

        f.write(f"### 4. 数据源敏感性\n\n")
        f.write(f"各提取率下5场景成功率最大差距:\n\n")
        f.write(f"- WR=3.0%: {spread[wr_3]:.1f}pp（共识度{'高' if spread[wr_3]<5 else '中' if spread[wr_3]<15 else '低'}）\n")
        f.write(f"- WR=4.0%: {spread[wr_4]:.1f}pp（共识度{'高' if spread[wr_4]<5 else '中' if spread[wr_4]<15 else '低'}）\n")
        f.write(f"- WR=5.0%: {spread[wr_5]:.1f}pp（共识度{'高' if spread[wr_5]<5 else '中' if spread[wr_5]<15 else '低'}）\n")
        f.write(f"- 最大分歧点: WR={RATES[max_spread_idx]:.1%} (差距{spread[max_spread_idx]:.1f}pp)\n\n")

        f.write("### 5. 可执行建议\n\n")
        consensus_wr = 0.0
        for r_idx in range(len(RATES) - 1, -1, -1):
            if all(results[lab]["success"][r_idx] >= 0.90 for lab in labels):
                consensus_wr = RATES[r_idx]
                break
        f.write(f"1. **所有场景均达90%成功率的最高提取率**: {consensus_wr:.1%}\n")
        f.write(f"   → 这是跨数据源的\"共识安全提取率\"，最具鲁棒性。\n\n")

        consensus_80 = 0.0
        for r_idx in range(len(RATES) - 1, -1, -1):
            if all(results[lab]["success"][r_idx] >= 0.80 for lab in labels):
                consensus_80 = RATES[r_idx]
                break
        f.write(f"2. **所有场景均达80%成功率的最高提取率**: {consensus_80:.1%}\n")
        f.write(f"   → 适合风险承受能力较高的投资者。\n\n")

        f.write(f"3. **费率每增加1%，安全提取率约降低**: ~{abs(swr_diff)/2*100:.1f}pp\n")
        f.write(f"   → 选择低费率ETF（VTI 0.03%, VT 0.07%）可显著提高安全边际。\n\n")

        f.write(f"4. **对中国VT投资者的建议**: 使用JST-ALL-GDP√的结果作为基准（最保守、最多样），\n")
        f.write(f"   安全提取率{safe_wrs['JST-ALL-GDP√'][90]:.1%}~{safe_wrs['JST-ALL-GDP√'][80]:.1%}（80-90%成功率），\n")
        f.write(f"   配合风险护栏策略动态调整提取额，效果更佳。\n\n")

        # 收敛区间分析
        f.write("### 6. 收敛与分歧区间\n\n")
        low_spread_wrs = []
        high_spread_wrs = []
        for idx, wr in enumerate(RATES):
            if 0.02 <= wr <= 0.07:
                if spread[idx] < 5:
                    low_spread_wrs.append(wr)
                elif spread[idx] > 15:
                    high_spread_wrs.append(wr)
        if low_spread_wrs:
            f.write(f"- **高度共识区间** (差距<5pp): {low_spread_wrs[0]:.1%} ~ {low_spread_wrs[-1]:.1%}\n")
            f.write(f"  → 在此范围内，数据源选择对结论影响最小。\n")
        else:
            f.write("- **高度共识区间**: 无（2%-7%内各场景差距均>=5pp）\n")
        if high_spread_wrs:
            f.write(f"- **高度分歧区间** (差距>15pp): {high_spread_wrs[0]:.1%} ~ {high_spread_wrs[-1]:.1%}\n")
            f.write(f"  → 在此范围内，数据源选择对结论影响显著，需谨慎。\n\n")
        else:
            f.write("- **高度分歧区间**: 无\n\n")

        # 回报统计
        f.write("### 7. 各场景回报特征\n\n")
        f.write("| 场景 | 年化均值 | 年化标准差 | P5 | P50 | P95 |\n")
        f.write("|------|---------|-----------|----|----|----|\n")
        for lab in labels:
            rets = results[lab]["scenarios"].flatten() * 100
            f.write(f"| {lab} | {np.mean(rets):.1f}% | {np.std(rets):.1f}% | "
                    f"{np.percentile(rets, 5):.1f}% | {np.percentile(rets, 50):.1f}% | "
                    f"{np.percentile(rets, 95):.1f}% |\n")

        # 排名分析
        f.write("\n### 8. 各提取率下的场景排名\n\n")
        f.write("| 提取率 | 最乐观 | 最保守 |\n")
        f.write("|--------|--------|--------|\n")
        for wr_val in [0.025, 0.03, 0.035, 0.04, 0.05, 0.06]:
            idx = np.argmin(np.abs(RATES - wr_val))
            srs = {lab: results[lab]["success"][idx] for lab in labels}
            best = max(srs, key=srs.get)
            worst = min(srs, key=srs.get)
            f.write(f"| {wr_val:.1%} | {best} ({srs[best]:.1%}) | {worst} ({srs[worst]:.1%}) |\n")

        REF_SPEND = 100_000
        f.write("\n### 9. 给中国VT投资者的分层建议\n\n")
        f.write(f"以下以年支出${REF_SPEND:,}为例，计算所需退休资产规模。\n\n")

        swr_95_min = min(swr_95.values())
        f.write("#### 保守派（追求95%+成功率）\n")
        f.write(f"- 基准提取率: {swr_95_min:.1%}（基于JST-ALL-GDP√，最保守场景）\n")
        f.write(f"- 必须配合风险护栏策略，在市场下行时削减提取\n")
        f.write(f"- 所需资产: ${REF_SPEND:,} / {swr_95_min:.1%} = **${REF_SPEND/swr_95_min:,.0f}**\n")
        f.write(f"- $4M资产对应年支出: **${4_000_000*swr_95_min:,.0f}/年**\n\n")

        f.write("#### 平衡派（接受80-90%成功率）\n")
        f.write(f"- 基准提取率: {consensus_wr:.1%}~{consensus_80:.1%}（所有场景均认可的范围）\n")
        f.write(f"- 建议使用风险护栏策略，可在乐观市况下适度提高消费\n")
        f.write(f"- 所需资产: **${REF_SPEND/consensus_80:,.0f}~${REF_SPEND/consensus_wr:,.0f}**\n")
        f.write(f"- $4M资产对应年支出: **${4_000_000*consensus_wr:,.0f}~${4_000_000*consensus_80:,.0f}/年**\n\n")

        f.write("#### 激进派（接受70%成功率）\n")
        swr_70 = {lab: safe_wrs[lab][70] for lab in labels}
        conservative_70 = min(swr_70.values())
        f.write(f"- 基准提取率: {conservative_70:.1%}（最保守场景的70%安全线）\n")
        f.write(f"- 必须配合灵活的支出调整策略和备用收入来源\n")
        f.write(f"- 所需资产: **${REF_SPEND/conservative_70:,.0f}**\n")
        f.write(f"- $4M资产对应年支出: **${4_000_000*conservative_70:,.0f}/年**\n\n")

        f.write("## 图表清单\n\n")
        f.write("- `wr_success_curves.png`: 全景成功率曲线\n")
        f.write("- `wr_success_zoomed.png`: 2%-6%放大图\n")
        f.write("- `wr_funded_ratio.png`: 中位覆盖率曲线\n")
        f.write("- `wr_scenario_spread.png`: 场景间分歧度\n")
        f.write("- `wr_safe_comparison.png`: 安全提取率柱状图\n")
        f.write("- `wr_heatmap.png`: 成功率热力图\n")
        f.write("- `wr_return_distributions.png`: 回报分布对比\n")
        f.write("- `wr_fee_impact.png`: 费率影响专题\n")
        f.write("- `wr_us_exceptionalism.png`: 美国例外论专题\n")
        f.write("- `wr_survival_curves.png`: 资产存活曲线\n")

    print(f"\n  Report saved: {report_path}")
    print("\nDone!")


if __name__ == "__main__":
    main()
