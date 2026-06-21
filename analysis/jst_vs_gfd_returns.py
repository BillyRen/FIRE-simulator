"""JST vs GFD(Anarkulova-Cederburg-O'Doherty "Beyond the Status Quo", 1890-2023)
逐国 domestic-stock 年化实际(本币)回报对比。

口径对齐:
  - 资产: domestic stocks(本国股票总回报)
  - real: 用本国 CPI 平减(JST: (1+Domestic_Stock)/(1+Inflation)-1; 论文已是 real)
  - 货币: 本币(local), 不做汇率换算 -> 规避汇率口径问题
  - 年化: 论文 = (1+月度几何均值)^12-1; JST = 年度 real 的几何 CAGR(数学等价)
  - 窗口: 按论文 Table II 各国 sample start -> 2023 对齐
          (额外给 start->2020 官方段, 因 JST 2021-2025 为非官方年均口径扩展)

论文数: Beyond the Status Quo (SSRN 4590406, March 2025), Table II, domestic stocks 列。
"""

import numpy as np
import pandas as pd

# iso: (论文 domestic-stock 月度几何均值实际回报 %, 论文样本起始年)
PAPER = {
    "DNK": (0.46, 1890),
    "FRA": (0.26, 1890),
    "DEU": (0.25, 1890),
    "GBR": (0.41, 1890),
    "USA": (0.52, 1890),
    "BEL": (0.21, 1897),
    "AUS": (0.57, 1901),
    "SWE": (0.47, 1910),
    "NLD": (0.41, 1914),
    "NOR": (0.37, 1914),
    "CHE": (0.38, 1914),
    "JPN": (0.31, 1930),
    "ITA": (0.19, 1931),
    "PRT": (0.14, 1934),
    "ESP": (0.28, 1959),
    "FIN": (0.73, 1969),
}
PAPER_END = 2023
NAME = {
    "DNK": "Denmark", "FRA": "France", "DEU": "Germany", "GBR": "United Kingdom",
    "USA": "United States", "BEL": "Belgium", "AUS": "Australia", "SWE": "Sweden",
    "NLD": "Netherlands", "NOR": "Norway", "CHE": "Switzerland", "JPN": "Japan",
    "ITA": "Italy", "PRT": "Portugal", "ESP": "Spain", "FIN": "Finland",
}


def cagr(real_returns: np.ndarray) -> float:
    n = len(real_returns)
    if n == 0:
        return np.nan
    return float(np.prod(1.0 + real_returns) ** (1.0 / n) - 1.0)


def main() -> None:
    df = pd.read_csv("data/jst_returns.csv")
    df["real"] = (1.0 + df["Domestic_Stock"]) / (1.0 + df["Inflation"]) - 1.0

    rows = []
    for iso, (m, start) in PAPER.items():
        paper_ann = (1.0 + m / 100.0) ** 12 - 1.0
        sub = df[df["Country"] == iso]

        w23 = sub[(sub["Year"] >= start) & (sub["Year"] <= PAPER_END)]
        w20 = sub[(sub["Year"] >= start) & (sub["Year"] <= 2020)]
        jst23 = cagr(w23["real"].to_numpy())
        jst20 = cagr(w20["real"].to_numpy())
        # 排除德国 1923 恶性通胀年的稳健性版本
        w23x = w23[w23["Year"] != 1923]
        jst23x = cagr(w23x["real"].to_numpy())

        rows.append({
            "iso": iso,
            "country": NAME[iso],
            "window": f"{start}-{PAPER_END}",
            "paper_%": round(paper_ann * 100, 2),
            "jst_to2023_%": round(jst23 * 100, 2),
            "diff_pp": round((jst23 - paper_ann) * 100, 2),
            "jst_to2020_%": round(jst20 * 100, 2),
            "jst_ex1923_%": round(jst23x * 100, 2),
            "n_yrs": len(w23),
        })

    out = pd.DataFrame(rows).sort_values("diff_pp", key=lambda s: s.abs(), ascending=False)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)
    print(out.to_string(index=False))

    d = out["diff_pp"]
    print("\n--- diff(JST_to2023 - paper) 摘要 (pp) ---")
    print(f"median |diff| = {d.abs().median():.2f}; mean diff = {d.mean():.2f}; "
          f"<=0.5pp: {(d.abs() <= 0.5).sum()}/{len(d)}; <=1.0pp: {(d.abs() <= 1.0).sum()}/{len(d)}")

    out.to_csv("analysis/output/jst_vs_gfd_returns.csv", index=False)
    print("\nsaved -> analysis/output/jst_vs_gfd_returns.csv")


if __name__ == "__main__":
    main()
