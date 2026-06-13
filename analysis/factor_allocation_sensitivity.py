"""Factor-allocation sensitivities (Codex review round 2).

Adds to factor_allocation_cew.py:
  H. PREMIUM HAIRCUT (Codex Q1/Q5): shrink each factor's MEAN nominal excess over
     US large by h in {0,.25,.5,.75,1.0}, keeping vol & cross-correlation intact
     (factor_t -> factor_t - h*mean(factor - us_stock)). Re-optimize the full
     guardrail grid at 1927/65y/net and find the breakeven h where the best
     +SV+Mom CEW no longer beats base -> the honest "how much premium must persist"
     headline. Binding risk is persistence, not the modeled expense drag.
  C. REALISTIC MODERN COST (Codex Q4): base 0.05% (real broad-ETF) instead of the
     0.5% uniform spec, factors at realistic absolute (SV 0.30%, Mom 0.55%). Shows
     whether the 0.5% uniform base flattered factors.
  B. BASE at N=10000 (Codex Q6): apples-to-apples high-N base vs factor finalists.

Everything else (engine, guardrail tier F, window) reuses factor_allocation_cew.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))

import factor_allocation_cew as F

OUT = F.OUTPUT_DIR
PRIMARY_START, HORIZON = F.PRIMARY_START, F.PRIMARY_HORIZON
HAIRCUTS = [0.0, 0.25, 0.50, 0.75, 1.0]
# realistic modern ETF costs: broad 0.05%, SV 0.30% (AVUV), Mom 0.55% (MTUM+turnover)
REALISTIC_EXPENSE = np.array([0.0005, 0.0005, 0.0005, 0.0030, 0.0055])


def haircut_panel(panel: pd.DataFrame, h: float) -> pd.DataFrame:
    """Shrink SV & Mom mean nominal excess over US stock by fraction h."""
    df = panel.copy()
    base = df["us_stock"].to_numpy()
    for col in ("small_value", "momentum"):
        excess_mean = float((df[col].to_numpy() - base).mean())
        df[col] = df[col].to_numpy() - h * excess_mean
    return df


def grid_best_per_universe(panel: pd.DataFrame, expense: np.ndarray,
                           seed: int = F.SEED, num_sims: int = F.NUM_SIMS) -> pd.DataFrame:
    tensor = F.bootstrap_tensor(panel, PRIMARY_START, HORIZON, num_sims, seed)
    allocs = F.gen_allocations()
    rows = []
    for w in allocs:
        m = F.guardrail_metrics(F.real_returns(tensor, w, expense), HORIZON)
        rows.append({"alloc": F.tag(w), "universe": F.universe_of(w),
                     **{a: round(w[j], 4) for j, a in enumerate(F.ASSETS)}, **m})
    df = pd.DataFrame(rows)
    return F.best_per_universe(df)


def phase_haircut(panel):
    print("\n===== PHASE H: premium haircut (1927/65y, net cost) =====")
    rows = []
    for h in HAIRCUTS:
        hp = haircut_panel(panel, h)
        # show resulting factor real CAGR after haircut
        st = F.asset_stats(hp, PRIMARY_START)
        best = grid_best_per_universe(hp, F.NET_EXPENSE)
        cew = {r.universe: r.median_cew for _, r in best.iterrows()}
        alloc = {r.universe: r.alloc for _, r in best.iterrows()}
        base_cew = cew.get("base", float("nan"))
        for u in ["base", "+SV", "+Mom", "+SV+Mom"]:
            rows.append({"haircut": h, "universe": u,
                         "sv_real_cagr": st.loc["small_value", "real_cagr"],
                         "mom_real_cagr": st.loc["momentum", "real_cagr"],
                         "alloc": alloc.get(u), "median_cew": cew.get(u),
                         "uplift_vs_base": (cew.get(u, np.nan) - base_cew)})
        print(f"  h={h:.2f}  SV_real={st.loc['small_value','real_cagr']:.2%} "
              f"Mom_real={st.loc['momentum','real_cagr']:.2%} | "
              f"base={base_cew:,.0f}({alloc.get('base')})  "
              f"+SV+Mom={cew.get('+SV+Mom',float('nan')):,.0f}({alloc.get('+SV+Mom')})  "
              f"uplift={cew.get('+SV+Mom',np.nan)-base_cew:+,.0f} "
              f"({(cew.get('+SV+Mom',np.nan)/base_cew-1)*100:+.1f}%)")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "haircut.csv", index=False)
    print(f"  wrote haircut.csv")
    # breakeven: smallest h where +SV+Mom uplift over base <= ~MC noise (1% of base)
    piv = df[df.universe == "+SV+Mom"].set_index("haircut")
    base = df[df.universe == "base"].set_index("haircut")["median_cew"]
    print("  breakeven scan (+SV+Mom uplift % over base):")
    for h in HAIRCUTS:
        up = piv.loc[h, "median_cew"] / base.loc[h] - 1
        flag = "  <-- advantage ~gone" if up < 0.01 else ""
        print(f"    h={h:.2f}: {up*100:+.1f}%{flag}")
    return df


def phase_realistic_cost(panel):
    print("\n===== PHASE C: realistic modern cost (1927/65y) =====")
    print(f"  expense = {REALISTIC_EXPENSE.tolist()} (broad .05% / SV .30% / Mom .55%)")
    best = grid_best_per_universe(panel, REALISTIC_EXPENSE)
    print(best[["universe", "alloc", "median_cew", "init_swr", "success_rate"]].to_string(
        index=False, formatters={"median_cew": "{:,.0f}".format,
        "init_swr": "{:.2%}".format, "success_rate": "{:.3f}".format}))
    best.to_csv(OUT / "realistic_cost.csv", index=False)
    base_cew = best[best.universe == "base"]["median_cew"].iloc[0]
    svm = best[best.universe == "+SV+Mom"]["median_cew"].iloc[0]
    print(f"  +SV+Mom uplift vs base @ realistic cost: {svm-base_cew:+,.0f} "
          f"({svm/base_cew-1:+.1%})")
    return best


def phase_base_highn(panel):
    print("\n===== PHASE B: base optimal at N=10000 (apples-to-apples) =====")
    tensor = F.bootstrap_tensor(panel, PRIMARY_START, HORIZON, F.HIGHN_SIMS, F.HIGHN_SEED)
    # base optimal from the main grid was 50/50/00/00/00
    w = np.array([0.5, 0.5, 0.0, 0.0, 0.0])
    m = F.guardrail_metrics(F.real_returns(tensor, w, F.NET_EXPENSE), HORIZON)
    print(f"  base 50/50/00 @N=10000: CEW {m['median_cew']:,.0f}  "
          f"p10_cew {m['p10_cew']:,.0f}  SWR {m['init_swr']:.2%}  "
          f"success {m['success_rate']:.3f}  severe {m['severe_fail_prob']:.4f}")
    return m


def main():
    panel = F.load_panel()
    print(F.alignment_diagnostic(panel))
    phase_haircut(panel)
    phase_realistic_cost(panel)
    phase_base_highn(panel)
    print("\nDONE.")


if __name__ == "__main__":
    main()
