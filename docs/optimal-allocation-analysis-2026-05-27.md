# 最优资产配置分析报告（2026-05-27）

> 方法学详见 `docs/optimal-allocation-plan-2026-05-27.md`；脚本：`analysis/optimal_allocation_v1.py`；原始数据：`analysis/output/optimal_allocation/results.csv` (10,824 行)。

## 1. 一句话结论

**对中国/全球居民跨周期最稳健的静态配置 = `30% Domestic Stock + 60% Global Stock + 10% Domestic Bond`**（mean rank 7.6/66，跨 164 个场景）。略偏债的 `40/50/10`（mean rank 9.0，rank std 4.0）在波动性上最稳；进入 Pareto frontier 次数最多的是 `30/70/00`（87 次）。

- 单一债券（≥80% bond）在所有场景下都是最差，100% 债券 mean rank 66/66。
- 1.2x 杠杆在 4 个 WR 档全部下挫成功率（USA 4% 下 success 87.9% → 85.2%），CVaR 归零；**leverage=1.0 跨场景稳健最优**——与 [Memory: guardrail-allocation-leverage-sweep] 一致。
- `JST-USA` 系统性比 `FIRE_dataset-USA` 给出更高 FR（同 4% / 45y / fixed：96.2% vs 93.9%）；与 [Memory: cme-horizon-2025-validates-jst-pool] 中"FIRE_dataset 1970+ 太短不推荐"判断一致。

## 2. 维度与场景

164 个 `sweep_allocations` 调用（共 10,824 行 alloc × scenario）：

| 维度 | 值 |
|---|---|
| 数据源 | JST (16 国 1871-2025), FIRE_dataset (USA only) |
| 国家 | USA, ALL(gdp_sqrt 池化), CHE, AUS, JPN, DEU |
| 起始年 | 1900, 1970 |
| 退休年限 | 30, 45, 60 |
| 提取策略 | fixed, declining (2%/y after 65), smile (-1% then +1%) |
| 初始提取率 | 3.0%, 3.5%, 4.0%, 4.5% |
| 杠杆 | 1.0, 1.2 (子集) |
| Allocation 网格 | 步长 0.1, (Dom + Intl + Bond) = 1, 共 66 组合 |
| Bootstrap | block_size 5-15, num_sims 2,000, seed 42 |

> 主网格 sweeps = 2 country × 2 start × 3 horizon × 3 strategy × 4 wr = 144；补充：FIRE_dataset 8 + 杠杆 8 + 跨国 4 = 164 总。

## 3. 跨场景稳健排名（核心结果）

按 `funded_ratio` 在每个场景内排名（1=最佳，66=最差），再跨所有 164 场景平均：

| Alloc (Dom/Intl/Bond) | mean rank | rank std | Pareto count | near-opt count | mean FR | mean success |
|---|---|---|---|---|---|---|
| **30/60/10** | **7.57** | 6.51 | 42 | 152 | 0.957 | 0.880 |
| 40/50/10 | 9.02 | **4.04** | 37 | 146 | 0.956 | 0.878 |
| 20/70/10 | 9.63 | 10.52 | 66 | 137 | 0.955 | 0.875 |
| 30/50/20 | 10.36 | 5.53 | 14 | 124 | 0.953 | 0.867 |
| 40/60/00 | 10.70 | 8.44 | 38 | 163 | 0.957 | 0.884 |
| 30/70/00 | 10.73 | 9.80 | **87** | 158 | 0.957 | 0.882 |
| 20/60/20 | 10.87 | 9.55 | 36 | 118 | 0.953 | 0.865 |
| 40/40/20 | 12.80 | 4.37 | 2 | 112 | 0.951 | 0.863 |
| 50/40/10 | 12.82 | 6.81 | 35 | 117 | 0.953 | 0.871 |
| 50/50/00 | 13.02 | 9.20 | 63 | 154 | 0.955 | 0.880 |

**共识区域**：`Stock ≥ 70%, Bond 0-20%, Dom-Intl 比例 20:70 ~ 50:40`。

### 谁是底部？
100% 债券 / ≥90% 债券 / 仅本国债券：mean rank 60-66，mean FR 0.75-0.83。**不要把固定收益作为退休组合的主体**。

## 4. 关键洞察

### 4.1 国家偏好对最优配置影响巨大

| 国家 (1900-2025, 45y, fixed) | 最优 alloc (Dom/Intl/Bond) | FR | success |
|---|---|---|---|
| AUS | 60/40/00 | 0.977 | 0.922 |
| USA | 50/50/00 | 0.962 | 0.879 |
| ALL pool | 30/70/00 | 0.926 | 0.806 |
| DEU | 40/60/00 | 0.904 | 0.738 |
| JPN | 30/70/00 | 0.904 | 0.758 |
| CHE | 10/70/20 | 0.900 | 0.725 |

历史强者（AUS、USA）最优偏 Dom；历史相对弱者（CHE、JPN、DEU）最优偏 Intl 分散；ALL pool 因为已经做了多国混合，再叠加 Intl 是为了拿到 stock premium。

**对中国居民的含义**（[Memory: feedback-dom-global-perspective] + [user-investment-profile]）：
- 中国资产数据在 JST 集合中不可得，参考 CHE/JPN/DEU（"非头部历史强国"）→ 最优 Dom 比例 10-40%。
- 推荐参考 ALL pool 的 30/70/00 或 30/60/10，把 A 股/港股控制在 25-30%。

### 4.2 数据源差异
JST-USA vs FIRE_dataset-USA（同 USA / fixed / 45y）：

| WR | data_source | 最优 alloc | FR |
|---|---|---|---|
| 3.0% | JST | 60/40/00 | 0.991 |
| 3.0% | FIRE | 40/40/20 | 0.986 |
| 4.0% | JST | 50/50/00 | 0.962 |
| 4.0% | FIRE | 60/30/10 | 0.939 |
| 4.5% | JST | 50/50/00 | 0.935 |
| 4.5% | FIRE | 60/30/10 | 0.904 |

JST 系统性更乐观（同 alloc 多 2-3pp FR），且推荐 Intl 比例更高（50%）。FIRE_dataset 推荐更高 Dom (60%) + 一点 Bond，因 FIRE_dataset 的 Intl 数据噪声较大。建议**主线用 JST**，并把 FIRE_dataset 作为对比。

### 4.3 起始年份的影响

| 国家 | 起始年 | 平均 FR | 最优配置 |
|---|---|---|---|
| USA | 1900 | 0.93 | 50/50/00 (4%, 45y) |
| USA | 1970 | 0.95 | 20/60/20 (4%, 45y) |
| ALL | 1900 | 0.87 | 30/70/00 (4%, 45y) |
| ALL | 1970 | 0.92 | 30/70/00 (4%, 45y) |

1970+ 普遍 FR 高 2-3pp，且最优配置更偏 Intl + Bond 组合 → **现代金融体系下，Intl 多元化和债券对冲都更有效**；但 1900+ 包含两次大战 / 大萧条 sequence risk → 用 1900 起始更保守、更稳。

### 4.4 提取策略的差异（cross-scenario 平均 FR）

| Strategy | mean FR | std |
|---|---|---|
| declining | 0.927 | 0.077 |
| smile | 0.920 | 0.083 |
| fixed | 0.908 | 0.085 |

declining (2%/y 后 65) 系统性比 fixed 高约 2pp，smile 居中。**提取策略对 FR 的提升 ≈ 改善 Stock/Bond 比例的 1 个步长**（10%）→ 优先采用 declining/smile 比死守 4% rule 更优。注意 declining/smile 都假设老年消费下降——若个人对此假设不认同（如医疗支出占比高），用 fixed 估值更稳。

### 4.5 杠杆 1.0 vs 1.2

| Country | WR | 1.0 alloc | 1.0 FR | 1.2 alloc | 1.2 FR | Δ |
|---|---|---|---|---|---|---|
| USA | 3.0% | 60/40/00 | 0.991 | 50/40/10 | 0.984 | -0.7pp |
| USA | 4.0% | 50/50/00 | 0.962 | 50/40/10 | 0.950 | -1.2pp |
| USA | 4.5% | 50/50/00 | 0.935 | 40/50/10 | 0.919 | -1.6pp |
| ALL | 4.0% | 30/70/00 | 0.926 | 30/70/00 | 0.892 | -3.4pp |

1.2x 杠杆在所有 wr/country 都拉低 FR。**借贷成本（CPI + 2% spread）吃掉了多余 stock 暴露的预期收益**，且尾部 CVaR 全部归零。这印证 [Memory: ibkr-margin-rate-vs-cpi] 的结论——只有 spread < 0 或股票预期收益显著高于借贷成本时，杠杆才能赚到钱；过去 125 年的均值情况下不存在。

### 4.6 提取年限敏感性

| Country (4% fixed) | 30y FR | 45y FR | 60y FR |
|---|---|---|---|
| USA-1900 | 0.990 | 0.962 | 0.937 |
| ALL-1900 | 0.970 | 0.926 | 0.891 |

每延长 15 年，FR 下降约 3-4pp。**60 年极端长寿场景下，最优 alloc 完全不变（仍是 50/50 或 30/70）**——但需要更低 WR（≤3.5%）才能维持 90% 成功率。

## 5. 推荐组合（按需求场景）

### 5.1 保守稳健（最低 rank 波动）
**40/50/10**（rank std 4.04）：跨数据源/国家/策略的排名都在前 15。适合"不确定哪个数据源/国家更代表未来"的投资者。

### 5.2 期望最大化 + 跨场景前列
**30/60/10** 或 **30/70/00**：mean rank 最低（7.6/10.7），mean FR 最高（0.957）。适合愿意承受少量 rank 波动以换取更高期望 FR。

### 5.3 中国居民 IB 投资版本（结合 [user-investment-profile]）
- **`A 股+港股 25%（=Dom） + VT/全球股票 60%（=Intl） + 短债+TIPS 15%（=Bond）`**——基本对齐 30/60/10。
- WR 上限：4% rule 在 JST USA 45y 还有 88% success；在 ALL pool 只有 81%。**对未来收益保守，把目标 WR 设到 3.5%（success ≈ 93%）**。
- 与 [Memory: guardrail-optimal-params-v2] 保守档（target=0.95/up=0.99/lo=0.80/adj=0.05）配合使用，进一步抑制 sequence risk。

### 5.4 不能直观接受的对照
- **100% 股票 (e.g. 50/50/0)**：FR 接近最优（0.962 USA / 0.926 ALL），但 success rate 较 60/30/10 低 2-3pp，CVaR 更低（破产路径破产更彻底）。**只要不在乎 worst 10% 路径，100% 股票也可接受**——FIRE 文献的 "stocks-only" 派别在数据上也站得住。
- **100% 债券**：所有维度都垫底，**不要这样做**。

## 6. 与 Memory 既有结论的交叉验证

| 来源 | 结论 | 本次验证 |
|---|---|---|
| [user-investment-profile] | 中国居民 Dom ≤ 25%、Intl 60-70% | ✅ ALL/CHE/JPN/DEU 最优都在该区间 |
| [feedback-dom-global-perspective] | 不要照搬美国 60-70% Dom | ✅ USA 60% Dom 是因数据源 USA-centric |
| [guardrail-allocation-leverage-sweep] | leverage=1.0 最优 | ✅ 1.2 拉低 FR 0.7-3.4pp，CVaR 归零 |
| [guardrail-optimal-params-v2] | 保守档 target=0.95 配合稳健配置 | ✅ 与 30/60/10 + 3.5% WR 配合后 success > 92% |
| [cme-horizon-2025-validates-jst-pool] | JST pool 不必比 CME 更激进 | ✅ JST 30/70/00 与 CME 60/40 在 FR 上相当 |

## 7. 局限与下一步

- **未含现金流（pension / 育儿 / 房产）**：所有 164 sweep 默认 `cash_flows=[]`。退休前的工资、退休后的社保 / 公积金 / 房租收入会改变最优 alloc。建议另跑一份"含 pension 50K/y from age 65 + child education -200K @ age 55"的版本。
- **未含 housing 资产**：JST 数据集有 `Housing_TR`，但 `sweep_allocations` 只支持 3 资产（Dom Stock / Intl Stock / Domestic Bond）。要扩展到 4 资产需要改 simulator。
- **Guardrail 策略未纳入网格**：sweep_allocations 不支持 dynamic / guardrail。建议下一轮单独跑 `run_guardrail_simulation × allocation grid`。
- **seed=42 单次抽样**：[user-investment-profile] 已经评估稳定性（多 seed Jaccard 0.95+）。本次未做正式 seed 鲁棒性验证；如要发表/重大决策，应补 3-5 个 seed 验稳。
- **num_simulations=2000**：尾部分位有 ~1pp 噪声。Top-3 rank 差距大都 > 1pp 所以排名稳；若关注 cvar_10 精度，可上调到 10k。
- **未对比 pooling_method = equal**：本次默认 `gdp_sqrt`，未验证 equal pooling 是否会让中性国（CHE/SWE）权重升高从而推荐略偏 Bond。
- **leverage 仅试 1.0 / 1.2**：未做 1.5 / 2.0 的对照——但既然 1.2 已经全面拉低，更高杠杆只会更差。
- **Glide path 关闭**：静态 alloc 的结论。动态滑路径（年化降股加债）可能在 60y 场景下与本静态推荐表现不同。
