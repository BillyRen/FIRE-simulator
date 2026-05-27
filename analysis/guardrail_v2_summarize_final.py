"""Summarize the 4 final candidates (+ 1 dropped reference) across all
robustness checks. Reads cross_source.csv and sensitivity.csv from the
sibling output dir and writes final_candidates_summary.csv next to them."""
from pathlib import Path

import pandas as pd
import numpy as np

OUT_DIR = Path(__file__).resolve().parent / "output" / "guardrail_v2"
cs = pd.read_csv(OUT_DIR / "cross_source.csv")
sens = pd.read_csv(OUT_DIR / "sensitivity.csv")

CANDIDATES = [
    # name, target, upper, lower, adj, mode, min_remain, status
    ("A Conservative",     0.95, 0.99, 0.80, 0.05, "amount",        1,  "final"),
    ("B Legacy-v1",        0.85, 0.99, 0.70, 0.10, "amount",        5,  "final"),
    ("C Aggressive",       0.80, 0.99, 0.50, 0.10, "amount",        1,  "final"),
    ("D Composite-CEW",    0.85, 0.90, 0.50, 0.15, "amount",       10,  "final"),
    ("X Max-CEW (dropped)",0.85, 0.90, 0.50, 0.25, "success_rate",  1,  "dropped"),
]

print(f"{'Candidate':30s} | {'POOL':>8s} {'USA':>8s} {'DEU':>8s} {'JPN':>8s} | {'4src min':>9s} {'54env min':>10s} {'#<.85':>6s} | {'min CEW':>11s}")
print("-" * 130)

rows = []
for name, *params_status in CANDIDATES:
    p = params_status[:6]
    status = params_status[6]
    cs_sub = cs[(cs.target==p[0])&(cs.upper==p[1])&(cs.lower==p[2])&(cs.adj==p[3])&(cs['mode']==p[4])&(cs.min_remain==p[5])]
    sens_sub = sens[(sens.target==p[0])&(sens.upper==p[1])&(sens.lower==p[2])&(sens.adj==p[3])&(sens['mode']==p[4])&(sens.min_remain==p[5])]

    pool = cs_sub[cs_sub.source=="POOL"].iloc[0]
    usa = cs_sub[cs_sub.source=="USA"].iloc[0]
    deu = cs_sub[cs_sub.source=="DEU"].iloc[0]
    jpn = cs_sub[cs_sub.source=="JPN"].iloc[0]
    min_4src = min(pool.eff_success, usa.eff_success, deu.eff_success, jpn.eff_success)
    min_54env = sens_sub.eff_success.min()
    n_fail = (sens_sub.eff_success < 0.85).sum()
    min_cew_54 = sens_sub.median_cew.min()

    print(f"{name:25s} {status:8s} | "
          f"{pool.eff_success:8.3f} {usa.eff_success:8.3f} {deu.eff_success:8.3f} {jpn.eff_success:8.3f} | "
          f"{min_4src:9.3f} {min_54env:10.3f} {n_fail:>5d}/{len(sens_sub)} | "
          f"{min_cew_54:11.2e}")
    rows.append({
        "name": name, "status": status,
        "target": p[0], "upper": p[1], "lower": p[2],
        "adj": p[3], "mode": p[4], "min_remain": p[5],
        "pool_swr": pool.swr, "pool_effFR": pool.eff_funded, "pool_effSR": pool.eff_success, "pool_cew": pool.median_cew,
        "usa_effSR": usa.eff_success, "deu_effSR": deu.eff_success, "jpn_effSR": jpn.eff_success,
        "min_4src_effSR": min_4src, "min_54env_effSR": min_54env, "n_fail_54env": int(n_fail),
        "min_54env_cew": min_cew_54,
    })

print()
print("\n=== Full table (POOL baseline + worst-case) ===")
out = pd.DataFrame(rows)
out["pool_swr_pct"] = out.pool_swr * 100
print(out[["name","status","target","upper","lower","adj","mode","min_remain",
           "pool_swr_pct","pool_effFR","pool_effSR","pool_cew",
           "min_4src_effSR","min_54env_effSR","n_fail_54env","min_54env_cew"]].to_string(index=False))

out.to_csv(OUT_DIR / "final_candidates_summary.csv", index=False)
print("\n→ analysis/output/guardrail_v2/final_candidates_summary.csv")
