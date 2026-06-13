# 因子组合数据（Kenneth French Data Library）

长周期、**可投资口径**的因子收益数据（小盘、小盘价值、动量等），供长周期组合分析使用。

## 核心思路：long-only 排序组合 ≠ long-short 因子

| | long-short 因子 (SMB/HML/WML) | **long-only 排序组合（本数据）** |
|---|---|---|
| 构造 | 多空对冲、零成本、隐含杠杆 | 真实股票的市值加权篮子 |
| 可投资性 | ❌ 普通人买不到 | ✅ 就是指数基金持有的东西（DFA/VBR/IWN 复制的学术蓝本）|
| 历史 | 1926+ | 1926+ |

本数据全部取自 French 库每个文件里的 **"Average Value Weighted Returns -- Monthly"** 表（市值加权 = ETF 口径）。`ref_*_longshort` 两个文件是多空因子，**仅作参考**（提供无风险利率、重构市场收益），不要当成可投资标的。

## 历史覆盖（重要约束）

- **美国 1926+**：size / size×value / size×momentum 回到 **1926-07**（年度 1927 起）
- **美国 1963+**：size×profitability / size×investment（需 Compustat 会计数据）
- **国际仅 1990+**：所有发达/区域市场从 **1990-07**（年度 1991 起），Emerging 从 **1989-07**（年度 1990）

> ⚠️ **不存在免费、可投资、1970 年前的国际因子数据。** 唯一回到 1900 年的国际 size/value 溢价是 DMS（瑞信/UBS 全球投资回报年鉴）与 AQR Century of Factor Premia——两者均为**多空溢价 + 专有数据**，正好踩中"不要多空、要可投资"两条红线。本项目的 JST 数据（1871+）已覆盖国际*宽基*，因子拆分只能到 1990+。

## 数据来源与复现

- 来源：https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- 下载根：`https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/<stem>_CSV.zip`
- 本次快照：French `202604` CRSP database（数据截至 2026-04，月度）
- 一键复现（FF 月度更新后可重拉）：
  ```bash
  python3 scripts/download_french_factors.py              # 重新下载
  python3 scripts/download_french_factors.py --skip-download   # 复用 raw/ 仅重算
  ```

## 目录结构

```
data/factors/
├── raw/                      # 原始 French zip + 解压 csv（未改动）
├── monthly/<label>.csv       # VW 月度总收益，列: date(YYYYMM) + 各组合，DECIMAL
├── annual_nominal/<label>.csv# 月度复合成年度（1-12 月，仅完整年），DECIMAL 名义
├── annual_real/<label>.csv   # annual_nominal 用美国 CPI 去通胀 = 实际收益
├── headline_nominal_us.csv          # 分析就绪：美国旗舰组合（见下）
└── headline_nominal_intl_developed.csv  # 国际发达，USD 名义
```

### 数据集清单（label）

| label | 内容 | 列 | 起始年 |
|---|---|---|---|
| `us_size_portfolios` | 市值分组：十分位/五分位/三分位 | `Lo 10`…`Hi 10`, `Lo 20`…, `Lo 30`… | 1927 |
| `us_size_value_2x3` | 2×3 市值×账面市值比 | SMALL/BIG × LoBM/BM2/HiBM | 1927 |
| `us_size_value_5x5` | 5×5 市值×账面市值比 | 25 组合 | 1927 |
| `us_size_momentum_2x3` | 2×3 市值×动量 | SMALL/BIG × Lo/2/HiPRIOR | 1927 |
| `us_size_profitability_2x3` | 2×3 市值×盈利能力 | | 1964 |
| `us_size_investment_2x3` | 2×3 市值×投资 | | 1964 |
| `intl_developed_size_value_2x3` | 发达市场 2×3 | 同 2×3，USD | 1991 |
| `intl_developed_ex_us_…` / `europe` / `japan` / `asiapac_ex_japan` / `north_america` | 各区域 2×3 | USD | 1991 |
| `intl_emerging_size_value_2x3` | 新兴市场 2×3 | USD | 1990 |
| `ref_ff3_factors_longshort` | **多空**：Mkt-RF, SMB, HML, RF | | 1927 |
| `ref_momentum_factor_longshort` | **多空**：Mom | | 1927 |

### 2×3 组合列名 → 含义

| French 列名 | 含义 | headline 列名 |
|---|---|---|
| `SMALL LoBM` | 小盘成长（著名"黑洞"，长期最差）| `small_growth` |
| `SMALL HiBM` | **小盘价值** | `small_value` |
| `ME1 BM2` | 小盘中性 | `small_neutral` |
| `BIG LoBM` | 大盘成长 | `large_growth` |
| `BIG HiBM` | 大盘价值 | `large_value` |
| `ME2 BM2` | 大盘中性 | `large_neutral` |

### headline 文件列（分析就绪，对齐 FIRE_dataset 口径）

`Year, mkt, small_value, small_neutral, small_growth, large_value, large_neutral, large_growth, size_smallest_decile, size_small_quintile, size_biggest_decile, us_inflation`

镜像 `FIRE_dataset.csv` 约定：**名义总收益 + 单独的 `us_inflation` 列**，可直接与 `FIRE_dataset.csv` 按 Year 拼列。`mkt` 由 FF 因子重构（Mkt-RF + RF）。

## 口径与约定

- **名义 USD 总收益**（含股息）。French 存百分数，本数据已 ÷100 转十进制。
- 缺失哨兵 `-99.99` / `-999` → NaN。
- 仅取**市值加权（VW）**：等权（EW）会严重超配不可投资的微盘股，收益虚高。
- **年度 = 月度复合（1-12 月，仅完整 12 个月的年份）**；2026 因只有 1-4 月被丢弃。
- 实际收益用美国 CPI（FIRE_dataset `US Inflation`）去通胀：`real=(1+nom)/(1+infl)-1`。国际为 USD 名义→用美国 CPI 去通胀（对 USD 投资者口径正确，与 simulator 一致）。

## ⚠️ 可投资性告诫

- **最小市值十分位 `Lo 10`** 含微盘/纳盘股，波动率 ~38%、流动性差、买卖价差大——**不是实际可投资的代理**。真实小盘 ETF（IWM/IJR）持有的是较大的小盘股。
- 实际可投资的"小盘"代理：用 **`Lo 20`（最小五分位）** 或 2×3 的 **SMALL** 系列（NYSE 中位数以下，宽基小盘）。
- 实际可投资的"小盘价值"代理：**`small_value`（SMALL HiBM）**——VBR/IWN/DFSVX 对标的对象。
- VW 组合仍未扣管理费/交易成本/税；做长周期比较时可对 ETF 实现扣 0.1–0.5%/yr 损耗。

## 验证（已通过）

1. **解析正确性**：自算月度复合年度 vs French 自带年度表，`maxAnnDiff` ≤ 0.0011（纯舍入，French 仅给 2 位小数）。
2. **经济合理性**（美国 2×3，1927–2025 名义 CAGR）：小盘价值 **14.16%** > 小盘中性 12.70% > 大盘价值 12.27% > 大盘成长 10.21% ≈ 大盘中性 10.08% > **小盘成长 8.80%**——教科书排序；size 十分位最小 `Lo 10` 12.17%(vol 37.78%) 单调降到最大 `Hi 10` 9.95%(vol 18.90%)。
3. **外部交叉验证**：FF 重构名义美国市场 CAGR 1927–2025 = **10.27%** vs `FIRE_dataset` "US Stock" = **10.17%**（gap +0.10pp，corr 0.9988，年度 mean|diff| 0.63pp）——独立来源 99 年吻合到 0.1pp，且确认 FIRE_dataset 为名义口径。
4. 通胀 CAGR 3.00%，符合美国长期通胀。

## 引用

Eugene F. Fama and Kenneth R. French, Data Library, Tuck School of Business at Dartmouth. © 2026 Fama & French.
