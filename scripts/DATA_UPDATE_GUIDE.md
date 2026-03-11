# JST 数据年度更新指南

本文档记录了将 JST Macrohistory Database 扩展到最新年份所需的全部知识，
供未来 AI 模型或人类维护者参考。

## 1. 背景

JST (Jordà-Schularick-Taylor) Macrohistory Database R6 官方数据覆盖 1870-2020 年，
涵盖 18 个发达经济体（本项目使用其中 16 个，排除 CAN 和 IRL）。
我们使用公开数据源将其扩展到 2025 年。

### 相关脚本

| 脚本 | 作用 |
|------|------|
| `scripts/extend_jst_2021_2025.py` | 生成扩展数据 → `data/raw/jst_extension_2021_2025.csv` |
| `scripts/build_dataset_from_jst.py` | 合并 JST 原始 + 扩展数据 → `data/jst_returns.csv` |
| `scripts/validate_jst_extension.py` | 验证扩展数据质量（5 维度验证） |

### 数据流

```
JSTdatasetR6.xlsx (1870-2020)
        +
jst_extension_2021_2025.csv (2021-2025)
        │
        ▼
build_dataset_from_jst.py
        │
        ├──► data/jst_returns.csv      (模拟器使用的最终数据)
        └──► data/jst_countries.json    (国家元数据，含 extended 标记)
```

---

## 2. 关键方法论 (Critical Methodology)

### 2.1 股票资本利得：年度平均价格法

**这是最重要的方法论细节。**

JST 的 `eq_capgain` 使用的是**日均价格的年度平均值**之间的变化率，
而不是年末收盘价的变化率。

```
eq_capgain[t] = avg_daily_price[t] / avg_daily_price[t-1] - 1
```

举例：2018 年 S&P 500 年末下跌约 -4.4%，但日均价格同比变化为 +14.2%（因为
2018 年大部分时间价格高于 2017 年平均水平）。

**验证方法**：用 yfinance 下载 S&P 500 日线数据，计算年度均价，
与 JST 的 `eq_capgain` 对比。对 USA 的误差 < 0.15%。

**计算步骤**：
```python
import yfinance as yf
data = yf.download("^GSPC", start="2019-01-01", end="2026-01-01")
annual_avg = data["Close"].resample("YE").mean()
capgain = annual_avg.pct_change()
```

### 2.2 非美国国家股指的局限性

JST 使用自行构建的广义市场指数（参见 "Rate of Return on Everything", Jordà et al. 2019），
而非公开的国家头条指数。我们使用 yfinance 上最接近的替代指数：

| 国家 | yfinance ticker | 与 JST 的偏差 | 注意事项 |
|------|----------------|-------------|---------|
| USA | ^GSPC | < 0.15% | 完美匹配 |
| GBR | ^FTSE | ~5-10% | JST 用 FTSE All-Share，yfinance 为 FTSE 100 |
| JPN | ^N225 | ~5-10% | JST 用 TOPIX，N225 为价格加权 |
| DEU | ^GDAXI | 特殊 | **DAX 是全收益指数，dividend_yield 必须设 0** |
| AUS | ^AXJO | ~5% | S&P/ASX 200 |
| FRA | ^FCHI | ~5% | CAC 40 |
| 其他 | 见脚本注释 | ~5-10% | 均使用各国主要指数 |

### 2.3 欧元区遗留货币汇率

**这是最容易出错的地方。**

JST 对 8 个欧元区国家存储的 `xrusd` 是**前欧元遗留货币/USD**，不是 EUR/USD。

必须将 EUR/USD 乘以固定兑换因子转换：

```python
_EURO_CONVERSION = {
    "BEL": 40.3399,   # 比利时法郎 / EUR
    "DEU": 1.95583,   # 德国马克 / EUR
    "ESP": 166.386,   # 西班牙比塞塔 / EUR
    "FIN": 5.94573,   # 芬兰马克 / EUR
    "FRA": 6.55957,   # 法国法郎 / EUR
    "ITA": 1936.27,   # 意大利里拉 / EUR
    "NLD": 2.20371,   # 荷兰盾 / EUR
    "PRT": 200.482,   # 葡萄牙埃斯库多 / EUR
}

# 正确的转换方式
xrusd_legacy = eur_per_usd * legacy_per_eur
# 例如 DEU 2021: 0.879 EUR/USD * 1.95583 DEM/EUR = 1.719 DEM/USD
```

**如果直接使用 EUR/USD（约 0.9）而不乘以转换因子**，会导致：
- `fx_change` 计算时，从 JST 2020 值（如 DEU: 1.74 DEM/USD）跳到 0.879 EUR/USD
- `Global_Stock` 被夸大数百倍（因为 FX 变化率异常）

### 2.4 债券总回报估算

JST 的 `bond_tr` 基于实际债券价格序列，我们用 modified duration 近似：

```
bond_tr ≈ coupon + price_change
        ≈ ltrate[t-1]/100 + (-D × (ltrate[t] - ltrate[t-1]) / 100)
```

- D = 8.0（10 年期政府债券的近似修正久期）
- 利率上升 → 价格下跌 → 负的 price_change
- 该近似在利率变化较小时精度较好，大幅加息周期会有累计误差

与 FIRE_dataset 的 USA 交叉验证：5 年累计误差约 -11.6%，主要来自
2022 年大幅加息（+1.5pp 单年变化超出线性近似范围）。

### 2.5 Housing Rent Yield 拼接

`housing_rent_yd`（住房租金收益率）变化缓慢。扩展数据必须从 JST 最后一年
（2020）的精确值 carry forward，而不是使用通用近似值。

```python
# 正确做法：从 JST 2020 加载
raw = pd.read_excel("data/raw/JSTdatasetR6.xlsx", sheet_name=0)
rent_yd = raw[(raw["iso"] == "USA") & (raw["year"] == 2020)]["housing_rent_yd"].iloc[0]

# 错误做法：使用固定常数（会导致 Rent_Growth 在 2020→2021 跳变）
```

`Rent_Growth` 由 `build_dataset_from_jst.py` 计算：
```
rent_level = housing_rent_yd × hpnom
Rent_Growth = rent_level.pct_change()
```

如果 `housing_rent_yd` 在 2020 和 2021 之间不连续，会产生极端的 `Rent_Growth`
（实测可达 88%）。

### 2.6 CPI、GDP、人口：链式连接

这些指标使用**增长率从 JST 2020 基准值链式连接**：

```python
cpi[2021] = cpi_jst[2020] × (1 + inflation_rate[2021])
cpi[2022] = cpi[2021] × (1 + inflation_rate[2022])
# rgdpmad 和 pop 同理
```

增长率来源于 IMF WEO（年度平均 CPI 变化率）。
注意 JST 的 CPI 也是年度平均值，与 IMF WEO 方法论一致。

---

## 3. 数据源清单

每个变量的具体来源和获取方式：

| 变量 | 来源 | URL | 注意事项 |
|------|------|-----|---------|
| eq_capgain | yfinance 日线数据 | `yf.download(ticker)` | 计算年度均价后取同比变化 |
| dividend_yield | OECD MEI / 各国统计局 | oecd.org | DEU 设为 0（DAX 全收益） |
| inflation_rate | IMF WEO Oct edition | imf.org/weo | 年度平均 CPI 变化率 |
| xrusd | IMF IFS / FRED | data.imf.org | 年末值；欧元区需转换遗留货币 |
| ltrate | OECD MEI | oecd.org | 10 年期国债收益率，年度平均，% |
| rgdp_growth | IMF WEO | imf.org/weo | 实际人均 GDP 增长率 |
| pop_growth | IMF WEO | imf.org/weo | 人口增长率 |
| housing_capgain | OECD Housing Prices DB | oecd.org | 名义住房价格指数同比变化 |

---

## 4. 逐步更新流程

假设要添加 2026 年的数据：

### Step 1: 收集数据

为 16 个国家收集上述 8 个变量的 2026 年数据。

**股票数据**：
```python
import yfinance as yf

tickers = {
    "USA": "^GSPC", "GBR": "^FTSE", "JPN": "^N225", "DEU": "^GDAXI",
    "FRA": "^FCHI", "AUS": "^AXJO", "CHE": "^SSMI", "NLD": "^AEX",
    "BEL": "^BFX",  "ESP": "^IBEX", "ITA": "FTSEMIB.MI",
    "SWE": "^OMX",  "NOR": "OSEBX.OL", "DNK": "^OMXC25",
    "FIN": "^OMXH25", "PRT": "PSI20.LS",
}

for iso, ticker in tickers.items():
    data = yf.download(ticker, start="2025-01-01", end="2027-01-01")
    avg_2025 = data["Close"]["2025"].mean()
    avg_2026 = data["Close"]["2026"].mean()
    capgain = avg_2026 / avg_2025 - 1
    print(f"{iso}: {capgain:.4f}")
```

**宏观数据**：从 IMF WEO（通常 4 月和 10 月更新）和 OECD 获取。

### Step 2: 更新扩展脚本

在 `scripts/extend_jst_2021_2025.py` 中：

1. 将文件名改为 `extend_jst_2021_2026.py`（或保持原名并扩展 YEARS 列表）
2. 在 `YEARS` 列表中添加 `2026`
3. 在每个常量字典中添加 2026 年的值：
   - `EQUITY_CAPGAIN`, `DIVIDEND_YIELD`, `INFLATION_RATE`
   - `XRUSD`（注意欧元区遗留货币转换！）, `LTRATE`
   - `RGDP_GROWTH`, `POP_GROWTH`, `HOUSING_CAPGAIN`

### Step 3: 运行脚本

```bash
# 1. 生成扩展数据
python scripts/extend_jst_2021_2025.py
# 输出: data/raw/jst_extension_2021_2025.csv

# 2. 构建最终数据集
python scripts/build_dataset_from_jst.py
# 输出: data/jst_returns.csv, data/jst_countries.json

# 3. 运行验证
python scripts/validate_jst_extension.py
```

### Step 4: 检查验证结果

验证脚本包含 5 个维度的自动检查：

1. **分布一致性**：扩展期 vs 历史期的均值/标准差 z-score < 2.0
2. **USA 交叉验证**：与 `FIRE_dataset.csv` 对比（如该文件也更新到 2026）
3. **全球指数构建**：GDP 加权全球指数 vs MSCI World ETF
4. **汇率拼接点**：2020→2021 边界的 fx_change 是否在历史范围内
5. **债券回报方向**：利率大幅上升时债券回报应为负

**预期结果**：大部分 PASS，通胀在极端年份可能 WARN（z-score > 2.0 但有合理解释）。

### Step 5: 更新前端

- `frontend/messages/en.json` 和 `zh.json`：更新 `dataSourceJst` 年份范围
- `data/historical_events.json`：添加重大市场事件
- 如需要，更新 `FIRE_dataset.csv`（这是独立的 USA-only 数据源）

---

## 5. 常见陷阱

### 5.1 DAX 双重计算

德国 DAX (^GDAXI) 是**全收益指数**（price index + reinvested dividends）。
如果为 DEU 设置了非零的 `dividend_yield`，总回报会被重复计算：

```
eq_tr = eq_capgain + dividend_yield  ← capgain 已包含分红
```

**解决方案**：DEU 的 `dividend_yield` 必须设为 0。

### 5.2 EUR/USD 年末值来源

IMF IFS 提供的 EUR/USD 年末值可能与 FRED 或路透社略有不同
（因为"年末"可以是 12 月 31 日、最后一个交易日、或 12 月平均等）。
JST 使用的是期末值（end of period），建议优先使用 IMF IFS。

### 5.3 2025 年数据的时效性

如果在 2025 年中期更新，部分 2025 年数据可能是 IMF 预测值而非实际值。
建议在 2026 年初使用 WEO Oct edition 的实际值替换。
股票数据如果 2025 年尚未结束，yfinance 只会返回截至当前日期的均价。

### 5.4 FIRE_dataset 独立更新

`data/FIRE_dataset.csv` 是 USA-only 数据源（Bogleheads Simba's Spreadsheet），
与 JST 扩展**完全独立**。它的更新来源和方法论不同，
但可以用于交叉验证 USA 的股票和债券回报。

### 5.5 bond_tr 累计误差

Modified duration 近似在单年利率变化超过 ~1.5pp 时精度下降。
2022 年美国利率从 1.44% 上升到 2.95%（+1.51pp），导致单年估算偏差约 -3%。
多年累计后误差会放大。如果需要更高精度，可以考虑使用实际债券价格指数。

---

## 6. 输出格式参考

`jst_extension_2021_2025.csv` 必须包含以下列（与 JSTdatasetR6.xlsx 兼容）：

```
year, country, iso, cpi, eq_tr, eq_capgain, eq_dp, eq_div_rtn,
bond_tr, ltrate, xrusd, rgdpmad, pop, housing_capgain, housing_rent_yd, hpnom
```

- `country` 字段可以为空（build 脚本不依赖它）
- `ltrate` 单位为百分比（如 4.21 表示 4.21%）
- `xrusd` 为本地货币/USD（欧元区为遗留货币/USD）
- `cpi`, `rgdpmad`, `pop`, `hpnom` 为**绝对水平值**（从 JST 2020 链式连接而来）
- `eq_tr`, `bond_tr`, `eq_capgain` 等为**回报率**（小数，如 0.15 表示 15%）

---

## 7. 验证脚本详解

`scripts/validate_jst_extension.py` 的 5 个验证维度：

1. **check_distribution_consistency()**
   - 对比 extension (2021-2025)、recent (2011-2020)、long (1970-2020) 三个时期
   - 计算 Domestic_Stock, Domestic_Bond, Inflation 的均值和标准差
   - 用 z-score 判断扩展数据是否在历史分布范围内

2. **check_usa_cross_validation()**
   - 将 JST 扩展的 USA 数据与 FIRE_dataset.csv 逐年对比
   - 检查累计收益和符号一致性（同涨同跌）

3. **check_global_index_construction()**
   - 从 JST 数据构建 GDP 加权全球指数
   - 与 yfinance 的 MSCI World (URTH)、MSCI ACWI (ACWI)、FTSE ex-US (VEU) 对比
   - 验证 FX 转换逻辑是否正确

4. **check_fx_splice()**
   - 检查 2020→2021 边界的 fx_change 是否在历史范围内
   - 验证欧元区 8 国的遗留货币转换因子一致性

5. **check_bond_validation()**
   - USA 债券与 FIRE_dataset 交叉验证
   - 方向性检查：利率大幅上升年份的债券回报应为负
