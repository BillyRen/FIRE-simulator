"""Visualize core guardrail v2 metrics.

Generates 4 figures into docs/figures/guardrail_v2/:
  1. target=0.85 lower × adj heatmap for effFR and CEW (gated subset)
  2. CEW vs effFR Pareto scatter at target=0.85 (color by mode, mark candidates)
  3. 54-env effSR distribution box plot for 6 candidates
  4. CEW collapse rate by (lower, adj) across all 153 fully-sampled params
"""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

# Use a Chinese-capable font on macOS (fallback: keep default)
for font_name in ["PingFang SC", "Heiti SC", "STHeiti", "Arial Unicode MS"]:
    try:
        from matplotlib.font_manager import findfont, FontProperties
        path = findfont(FontProperties(family=font_name), fallback_to_default=False)
        if path and not path.endswith("DejaVuSans.ttf"):
            mpl.rcParams["font.family"] = font_name
            mpl.rcParams["axes.unicode_minus"] = False
            break
    except Exception:
        continue

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "figures" / "guardrail_v2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path(__file__).resolve().parent / "output" / "guardrail_v2"
agg = pd.read_csv(DATA_DIR / "baseline_agg.csv")
sens = pd.read_csv(DATA_DIR / "sensitivity.csv")

# --- Apply gating to agg ---
agg["init_wd_floor60"] = agg["init_wd_mean"] * 0.60
agg["gating_pass"] = (
    (agg["eff_success_mean"] >= 0.85)
    & (agg["p10_avg_wd_mean"] >= agg["init_wd_floor60"])
    & (agg["mean_years_below_floor_mean"] <= 5)
)

CANDIDATES = [
    ("A", 0.95, 0.99, 0.80, 0.05, "amount",        1,  "Conservative", "tab:blue"),
    ("B", 0.85, 0.99, 0.70, 0.10, "amount",        5,  "Legacy-v1",    "tab:green"),
    ("D", 0.85, 0.90, 0.50, 0.15, "amount",       10,  "Composite-CEW","tab:orange"),
    ("E", 0.80, 0.99, 0.80, 0.05, "amount",        1,  "Aggressive-robust (dep)", "tab:gray"),
    ("F", 0.80, 0.99, 0.70, 0.05, "amount",        1,  "Aggressive-gap10","tab:red"),
    ("X", 0.85, 0.90, 0.50, 0.25, "success_rate",  1,  "Max-CEW (dropped)", "tab:purple"),
]


# ========================================================
# Figure 1: target=0.85 lower × adj heatmap (effFR + CEW)
# ========================================================
def fig1_target85_heatmaps():
    t85 = agg[(agg["target"] == 0.85) & agg["gating_pass"]]

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle("target=0.85: lower × adj effect on effFR & CEW (gated subset)\nAll 4 panels: rows=lower (0.10→0.80), cols=adj (0.05→0.25)", fontsize=13)

    for col_idx, mode in enumerate(["amount", "success_rate"]):
        sub = t85[t85["mode"] == mode]
        if len(sub) == 0:
            continue
        # average over min_remain and upper for each (lower, adj)
        pivot_fr = sub.pivot_table(index="lower", columns="adj", values="eff_funded_mean", aggfunc="mean")
        pivot_cew = sub.pivot_table(index="lower", columns="adj", values="median_cew_mean", aggfunc="mean")

        # effFR heatmap
        ax = axes[0, col_idx]
        im = ax.imshow(pivot_fr.values, cmap="RdYlGn", aspect="auto", vmin=0.92, vmax=0.97)
        ax.set_xticks(range(len(pivot_fr.columns)))
        ax.set_xticklabels([f"{a:.2f}" for a in pivot_fr.columns])
        ax.set_yticks(range(len(pivot_fr.index)))
        ax.set_yticklabels([f"{l:.1f}" for l in pivot_fr.index])
        ax.set_xlabel("adj")
        ax.set_ylabel("lower")
        ax.set_title(f"effFR — mode={mode}")
        for i in range(len(pivot_fr.index)):
            for j in range(len(pivot_fr.columns)):
                v = pivot_fr.values[i, j]
                if not np.isnan(v):
                    ax.text(j, i, f"{v:.3f}", ha="center", va="center", fontsize=8,
                            color="white" if v < 0.94 else "black")
        plt.colorbar(im, ax=ax, fraction=0.04)

        # CEW heatmap
        ax = axes[1, col_idx]
        im = ax.imshow(pivot_cew.values, cmap="viridis", aspect="auto", vmin=43000, vmax=54000)
        ax.set_xticks(range(len(pivot_cew.columns)))
        ax.set_xticklabels([f"{a:.2f}" for a in pivot_cew.columns])
        ax.set_yticks(range(len(pivot_cew.index)))
        ax.set_yticklabels([f"{l:.1f}" for l in pivot_cew.index])
        ax.set_xlabel("adj")
        ax.set_ylabel("lower")
        ax.set_title(f"median CEW ($) — mode={mode}")
        for i in range(len(pivot_cew.index)):
            for j in range(len(pivot_cew.columns)):
                v = pivot_cew.values[i, j]
                if not np.isnan(v):
                    ax.text(j, i, f"${v/1000:.1f}K", ha="center", va="center", fontsize=8,
                            color="white" if v < 49000 else "black")
        plt.colorbar(im, ax=ax, fraction=0.04, format="$%.0f")

    # Mark B and D positions on amount panels
    # B: lower=0.70, adj=0.10 → row 3, col 1 (in amount panel)
    # D: lower=0.50, adj=0.15 → row 2, col 2 (in amount panel)
    for ax in [axes[0, 0], axes[1, 0]]:
        ax.scatter([1], [3], marker="*", s=300, color="lime", edgecolor="black", linewidth=2, zorder=10, label="B")
        ax.scatter([2], [2], marker="*", s=300, color="orange", edgecolor="black", linewidth=2, zorder=10, label="D")
        ax.legend(loc="upper right", fontsize=9)
    for ax in [axes[0, 1], axes[1, 1]]:
        # X: lower=0.5, adj=0.25 in success_rate panel
        ax.scatter([4], [2], marker="X", s=300, color="purple", edgecolor="black", linewidth=2, zorder=10, label="X (dropped)")
        ax.legend(loc="upper right", fontsize=9)

    plt.tight_layout()
    plt.savefig(OUT_DIR / "01_target85_lower_adj_heatmap.png", dpi=120, bbox_inches="tight")
    plt.close()
    print(f"→ {OUT_DIR / '01_target85_lower_adj_heatmap.png'}")


# ========================================================
# Figure 2: CEW vs effFR scatter at target=0.85
# ========================================================
def fig2_pareto_scatter():
    t85 = agg[(agg["target"] == 0.85)].copy()  # 含 gating fail 来展示

    fig, ax = plt.subplots(figsize=(10, 7))

    # 不通过 gating: light gray
    fail = t85[~t85["gating_pass"]]
    ax.scatter(fail["eff_funded_mean"], fail["median_cew_mean"],
               c="lightgray", s=30, alpha=0.5, label="gating fail")

    # 通过 gating 分 mode 着色
    for mode, color in [("amount", "tab:blue"), ("success_rate", "tab:red")]:
        sub = t85[(t85["gating_pass"]) & (t85["mode"] == mode)]
        ax.scatter(sub["eff_funded_mean"], sub["median_cew_mean"],
                   c=color, s=40, alpha=0.6, label=f"gating pass: {mode}")

    # Mark candidates
    for code, t, u, lo, adj, m, mr, name, _ in CANDIDATES:
        if t != 0.85:
            continue
        r = agg[(agg.target==t)&(agg.upper==u)&(agg.lower==lo)&(agg.adj==adj)&(agg["mode"]==m)&(agg.min_remain==mr)]
        if len(r) == 0:
            continue
        r = r.iloc[0]
        ax.scatter([r.eff_funded_mean], [r.median_cew_mean],
                   marker="*", s=500, color="yellow", edgecolor="black", linewidth=2, zorder=10)
        ax.annotate(f"{code} {name}", (r.eff_funded_mean, r.median_cew_mean),
                    xytext=(10, 10), textcoords="offset points", fontsize=11, fontweight="bold")

    ax.set_xlabel("effFR (eff_funded_mean)")
    ax.set_ylabel("median CEW ($)")
    ax.set_title("target=0.85: CEW vs effFR (each dot = 1 config, 600 total)\nB and D are final candidates; X is dropped (success_rate mode)")
    ax.axhline(45000, ls="--", color="gray", alpha=0.4)
    ax.axvline(0.95, ls="--", color="gray", alpha=0.4)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "02_target85_cew_vs_effFR_scatter.png", dpi=120, bbox_inches="tight")
    plt.close()
    print(f"→ {OUT_DIR / '02_target85_cew_vs_effFR_scatter.png'}")


# ========================================================
# Figure 3: 54-env effSR distribution per candidate
# ========================================================
def fig3_stress_distribution():
    fig, ax = plt.subplots(figsize=(11, 6))
    data = []
    labels = []
    colors = []
    for code, t, u, lo, adj, m, mr, name, color in CANDIDATES:
        sub = sens[(sens.target==t)&(sens.upper==u)&(sens.lower==lo)&(sens.adj==adj)&(sens["mode"]==m)&(sens.min_remain==mr)]
        if len(sub) == 0:
            continue
        data.append(sub["eff_success"].values)
        labels.append(f"{code} {name}")
        colors.append(color)

    bp = ax.boxplot(data, labels=labels, patch_artist=True, showmeans=True, widths=0.6)
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.5)
    ax.axhline(0.85, ls="--", color="red", alpha=0.6, label="gating threshold 0.85")
    ax.set_ylabel("effective success rate (effSR)")
    ax.set_title("effSR distribution across 54 stress envs per candidate\n(box = IQR, whiskers 1.5×IQR, mean ▲, median —)\n3 alloc × 3 retirement_years × 2 with_CFs × 3 floors")
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(loc="lower left")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "03_54env_effSR_boxplot.png", dpi=120, bbox_inches="tight")
    plt.close()
    print(f"→ {OUT_DIR / '03_54env_effSR_boxplot.png'}")


# ========================================================
# Figure 4: CEW collapse rate by (lower, adj)
# ========================================================
def fig4_cew_collapse_heatmap():
    g = sens.groupby(["target", "upper", "lower", "adj", "mode", "min_remain"]).agg(
        min_cew=("median_cew", "min"),
        n=("env", "count"),
    ).reset_index()
    full = g[g["n"] == 54].copy()
    full["collapsed"] = full["min_cew"] < 100

    pivot = full.pivot_table(index="lower", columns="adj", values="collapsed", aggfunc="mean")
    counts = full.pivot_table(index="lower", columns="adj", values="collapsed", aggfunc="count")

    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(pivot.values, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{a:.2f}" for a in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{l:.1f}" for l in pivot.index])
    ax.set_xlabel("adj (adjustment_pct)")
    ax.set_ylabel("lower (lower_guardrail)")
    ax.set_title("CEW collapse rate by (lower, adj)\n(min median_CEW across 54 envs; collapsed if <$100)\nRed = always collapse, Green = always non-collapse")
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            v = pivot.values[i, j]
            n = counts.values[i, j]
            if not np.isnan(v):
                label = f"{v*100:.0f}%\n({int(n)} configs)"
                ax.text(j, i, label, ha="center", va="center", fontsize=9,
                        color="white" if v > 0.5 else "black")
    plt.colorbar(im, ax=ax, label="collapse rate")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "04_cew_collapse_rate_lower_adj.png", dpi=120, bbox_inches="tight")
    plt.close()
    print(f"→ {OUT_DIR / '04_cew_collapse_rate_lower_adj.png'}")


# ========================================================
# Figure 5: target=0.85 specifically — lower as 1D effect
# ========================================================
def fig5_lower_1d_at_target85():
    t85 = agg[(agg["target"] == 0.85) & agg["gating_pass"]].copy()

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("target=0.85: how lower alone affects key metrics (gated subset)\nLines = average over upper/adj/mr; points = mode-specific data", fontsize=12)

    for ax, col, ylabel, title in zip(
        axes,
        ["eff_funded_mean", "median_cew_mean", "p10_avg_wd_mean"],
        ["effFR", "median CEW ($)", "P10 avg withdrawal ($)"],
        ["effFR", "Median CEW (中位路径年消费)", "P10 average wd (worst-10% 路径)"],
    ):
        for mode, color, marker in [("amount", "tab:blue", "o"), ("success_rate", "tab:red", "^")]:
            sub = t85[t85["mode"] == mode]
            grp = sub.groupby("lower")[col].agg(["mean", "std"]).reset_index()
            ax.errorbar(grp["lower"], grp["mean"], yerr=grp["std"], marker=marker,
                        color=color, label=mode, capsize=4, lw=2, markersize=8)
        # Highlight the "V-shape" peak at lower=0.5
        ax.axvline(0.5, ls=":", color="green", alpha=0.5, label="lo=0.5 (baseline-optimal)")
        ax.axvline(0.7, ls=":", color="purple", alpha=0.5, label="lo=0.7 (Legacy v1 B)")
        ax.set_xlabel("lower_guardrail")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(alpha=0.3)
        if ax is axes[0]:
            ax.legend(loc="best", fontsize=9)

    plt.tight_layout()
    plt.savefig(OUT_DIR / "05_target85_lower_1d_effect.png", dpi=120, bbox_inches="tight")
    plt.close()
    print(f"→ {OUT_DIR / '05_target85_lower_1d_effect.png'}")


if __name__ == "__main__":
    print(f"Generating figures into {OUT_DIR}")
    fig1_target85_heatmaps()
    fig2_pareto_scatter()
    fig3_stress_distribution()
    fig4_cew_collapse_heatmap()
    fig5_lower_1d_at_target85()
    print("\nAll done.")
