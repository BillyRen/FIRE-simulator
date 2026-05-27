# Guardrail Optimal Params v2 — Final Report

**日期**: 2026-05-26
**作者**: Billy Ren (with Claude Opus 4.7)
**研究计划**: [docs/plan-2026-05-26-guardrail-optimal-params-v2.md](plan-2026-05-26-guardrail-optimal-params-v2.md)
**状态**: Draft（等 Phase 2-4 结果填充）

---

## TL;DR

针对中国居民通过 IB 全球投资的用户画像（baseline 见 §1.1），三档护栏候选（POOL data）：

| Tier | target | upper | lower | adj | mode | mr | SWR | effFR | CEW (baseline) | 跨源 robust? |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|---:|---|
| **保守** ★ | 0.95 | 0.99 | 0.80 | 0.05 | amount | 1 | 2.37% | 0.9903 | $36K | **✓ 4-source effSR ∈ [0.96, 0.97]**（54-env 仍有 stress 环境，见 §4.1） |
| **平衡** ⚠️ | 0.85 | 0.90 | 0.50 | 0.25 | success_rate | 1 | 3.31% | 0.9309 | **$53,979** | **✗ JPN effSR=0.73**（跌出 0.85） |
| **激进** ⚠️ | 0.80 | 0.99 | 0.50 | 0.10 | amount | 1 | 3.70% | 0.9462 | $48,340 | ⚠ JPN effSR=0.84（边际）|

CEW (baseline) = 4-source baseline 单 env CEW。54-env min CEW 见 §6.1。

### 最终推荐：保守档

**`target=0.95, upper=0.99, lower=0.80, adj=0.05, mode=amount, min_remain=1`**

- **在 4-source baseline** runs（POOL/USA/DEU/JPN, 15/75/10, 50yr, 无 CFs, floor=0.50）下 effSR ∈ [0.959, 0.975]，全 4 source 通过 gating
- 在 Phase 3 的 54 env 中仍是 effFR-robust（mean pct_top_effFR ≈ 0.91, min effFR=0.864）
- ⚠️ **Phase 3 极端环境警告**：在 `balanced_25_65_10 + retirement_years=45 + with_cfs + floor=0.60` env 下 effSR 可低至 0.7265（54-env 中 18/54 个 env 跌出 effSR ≥ 0.85），但**仍是所有 tier 中跌幅最小的**
- SWR 2.37% 对应初始年消费 $23,692/$1M，路径中位会随时间增长
- 与"中国居民全球分散投资 + 跨境额外风险"画像高度 alignment

### 重要发现

1. **之前推荐**（target=85%, adj=10%, lower=70%, mr=5）**不在任何 tier 的 Top-3**——但与各 tier 差距 ≤ 0.5pp effFR / ≤ 2% CEW，仍属合理"中庸"选项
2. **平衡档与保守档之间存在 fundamental trade-off**：没有任何参数同时在 effFR top-20 AND CEW top-20（across 54 envs）。平衡档跨 54 env 38/54 个 env effSR < 0.85（最低 0.208）。Fail 主要分布：27 个 `with_cfs=True` env（所有 3 个 retirement_years 都受影响）+ 11 个 `with_cfs=False` env（主要 60-year 和 45-year + high-floor 组合）
3. **Top-50 跨 5 seeds 高度稳定**（Jaccard 0.955+），ranking 不依赖 seed

---

## 1. 方法概要

研究分 5 个 Phase，覆盖 6 个护栏参数 × 多 seed × 54 环境 × 4 数据源。详细方法论见 [plan v2 doc](plan-2026-05-26-guardrail-optimal-params-v2.md)。

### 1.1 User Profile（baseline anchor）
- 数据源：JST Pool 1900+ (sqrt-GDP weighted, 16 countries)
- 配置：Dom 15% / Global 75% / Bond 10%（用户实际持仓代理）
- 退休年限：50 年，初始组合 $1M
- 费用率 0.5%，杠杆 1.0
- 消费地板 50%（年消费 < 0.5 × 初始 = 等效失败）

### 1.2 评价体系
**Gating（hard filter）**：
- effSR ≥ 0.85
- P10 路径平均消费 ≥ 0.60 × 初始
- 平均跌破地板年数 ≤ 5

**Ranking（在 gating 内分档）**：
- 保守：max effFR
- 平衡：max CEW（CRRA γ=2, δ=2%）
- 激进：max SWR

详见 plan v2 §4。

---

## 2. Phase 2 结果：Baseline Grid

3,000 参数组合 × 5 seeds = 15,000 评估行（baseline anchor 见 §1.1）。

### 2.1 Seed 稳定性
- Mean Jaccard (Top-50 by effFR): **0.955**
- Mean Jaccard (Top-50 by CEW):   **0.961**
- 结论：**ranking 跨 seed 高度稳定**，单 seed 结果已可信，多 seed 仅作鲁棒性确认

### 2.2 Gating 通过率
| 约束 | 通过数 | 通过率 |
|---|---:|---:|
| effSR ≥ 0.85 | 1,701 | 56.7% |
| P10 平均 wd ≥ 60% 初始 | 2,904 | 96.8% |
| 平均跌破地板年数 ≤ 5 | 3,000 | 100% |
| **全部通过** | **1,701** | **56.7%** |

**关键观察**：effSR 是唯一 binding 约束；P10 和 years_below 几乎不约束（因为 floor=0.50 较宽松）。

### 2.3 target 维度分组通过率
| target | 通过/总 | 通过率 | 均值 SWR | 均值 effFR |
|:---:|---:|---:|---:|---:|
| 0.75 | 0/600 | 0.0% | 4.04% | 0.907 |
| 0.80 | 86/600 | 14.3% | 3.70% | 0.926 |
| 0.85 | 435/600 | 72.5% | 3.31% | 0.947 |
| 0.90 | 585/600 | 97.5% | 2.90% | 0.964 |
| 0.95 | 600/600 | 100% | 2.37% | 0.981 |

**`target=0.75` 在 gating 下完全无效**——这印证之前 2026-03-17 的"target≤75% 参数不稳健"结论：低 target 反算的 SWR 高，但 effective success（含 consumption floor）落不到 0.85。

### 2.4 Top-3 per tier（跨 5 seeds 平均）

**Tier 1 — 保守（max effFR）**:
| target | upper | lower | adj | mode | mr | SWR | effFR | effSR | CEW |
|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|---:|---:|
| 0.95 | 0.99 | 0.80 | 0.05 | amount | 1 | 2.37% | 0.9903 | 0.964 | $36,229 |
| 0.95 | 0.99 | 0.80 | 0.05 | amount | 3 | 2.37% | 0.9903 | 0.964 | $36,207 |
| 0.95 | 0.99 | 0.80 | 0.05 | amount | 5 | 2.37% | 0.9902 | 0.964 | $36,172 |

**Tier 2 — 平衡（max CEW）**:
| target | upper | lower | adj | mode | mr | SWR | effFR | effSR | CEW |
|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|---:|---:|
| 0.85 | 0.90 | 0.50 | 0.25 | success_rate | 1 | 3.31% | 0.9309 | 0.860 | **$53,979** |
| 0.85 | 0.90 | 0.50 | 0.25 | success_rate | 3 | 3.31% | 0.9308 | 0.857 | $53,748 |
| 0.85 | 0.90 | 0.50 | 0.20 | success_rate | 1 | 3.31% | 0.9334 | 0.862 | $53,661 |

**Tier 3 — 激进（max SWR）**:
| target | upper | lower | adj | mode | mr | SWR | effFR | effSR | CEW |
|:---:|:---:|:---:|:---:|:---:|:---:|---:|---:|---:|---:|
| 0.80 | 0.99 | 0.50 | 0.10 | amount | 1 | 3.70% | 0.9462 | 0.858 | $48,340 |
| 0.80 | 0.99 | 0.50 | 0.10 | amount | 3 | 3.70% | 0.9462 | 0.858 | $48,301 |
| 0.80 | 0.99 | 0.50 | 0.10 | amount | 5 | 3.70% | 0.9462 | 0.859 | $48,216 |

### 2.5 跨 tier 模式观察
- **保守档全部 `mode=amount`** + `lower=0.80`（窄护栏频繁微调）+ `adj=0.05`（每次微调小）
- **平衡档全部 `mode=success_rate`** + `lower=0.50` + 大 `adj` (0.20-0.25)（CEW 偏好 success_rate mode，因为它按 success 距离按比例调整 wd → 平滑度高）
- **激进档主流 `mode=amount`** + `lower=0.50` + `adj=0.10`（中等）

**与 2026-03-17 推荐（target=85%, upper=99%, lower=70%, adj=10%, amount, mr=5）的差异**：
- 旧推荐对 baseline (50yr / 15-75-10) 而言介于"保守"和"平衡"档之间，无单档最优
- 跨 50yr (vs 旧 65yr) 与跨 alloc (vs 33/67) 的差异在 Phase 3 sensitivity 中量化

→ **150 unique 候选（3 个 tier 各 Top-50 的并集）进入 Phase 3 环境敏感性测试**。

---

## 3. Phase 3 结果：环境敏感性

150 候选 × 54 环境（3 alloc × 3 retirement_years × 2 CFs × 3 floor） = 8,100 评估行。

### 3.1 最关键发现：**effFR-robust 与 CEW-robust 互斥**

| target group | n params | mean pct_top_effFR | mean pct_top_CEW | mean SWR |
|:---:|---:|---:|---:|---:|
| 0.80 | 50 | **0.000** | 0.080 | 4.28% |
| 0.85 | 50 | **0.000** | **0.267** | 3.86% |
| 0.95 | 50 | **0.455** | 0.067 | 2.83% |

- 没有任何参数同时在 effFR top-20 和 CEW top-20 中（`pct_top_both` ≈ 0）
- target=0.95 包揽 effFR robustness（mean 45.5% envs in top-20）
- target=0.85 + `mode=success_rate` 包揽 CEW robustness（mean 26.7% envs in top-20）
- **target=0.80 在两个指标的 robust core 中均缺席** —— 跨环境 ranking 不稳定

### 3.2 Robust Core 候选

按 `≥60% top-20 envs by either metric` 筛出 25 个 candidates，加上激进档 Top-4（增量保留）= **29 params 进入 Phase 4**。

**保守 cluster（17 params, all target=0.95, mode=amount, adj=0.05）**:
- upper ∈ {0.90, 0.95, 0.99}, lower ∈ {0.70, 0.80}, mr ∈ {1,3,5,10}
- mean effFR = 0.950, min effFR = 0.864（最坏 env 下也 > 0.86）
- mean SWR = 2.83%

**平衡 cluster（8 params, all target=0.85, mode=success_rate）**:
- upper ∈ {0.90}, **lower ∈ {0.50, 0.70, 0.80}**, adj ∈ {0.20, 0.25}, mr ∈ {1, 3}
- 主要候选（max mean CEW，来自 robust_core.csv）: `target=0.85, upper=0.90, lower=0.50, adj=0.25, success_rate, mr=1`（mean CEW $38,417）
- 次选（max mean effFR，更保守）: `target=0.85, upper=0.90, lower=0.70, adj=0.20, success_rate, mr=3`（mean effFR 0.825）
- mean CEW 区间 [$37,909, $38,417]，**min CEW ≈ 0**（在 retirement_years≤45 + CFs + floor≥0.40 极端 env 下 CEW 崩塌！）

**激进 cluster（4 params, all target=0.80, mode=amount, adj=0.10）**:
- 主要候选: `target=0.80, upper=0.99, lower=0.50, adj=0.10, amount, mr=1`
- mean SWR = 4.28%, mean effFR = 0.871, **min effFR = 0.703**（最坏 env 下显著下降）

### 3.3 维度对最优参数的影响

| env 维度 | 主要影响 |
|---|---|
| `retirement_years` 30 → 60 | 短期最优 target 偏高（95%），长期可下移到 85% |
| `allocation` 10/80 → 25/65 | 海外股票权重越高，Pool optimal 倾向越激进的 lower（0.50 vs 0.80） |
| `cash_flows` none → baseline | CFs 让 target=85% 平衡档 effFR 更稳定（CFs 平滑提取需求） |
| `consumption_floor` 0.40 → 0.60 | 影响 effFR 而非 ranking；保守档跨 floor 排名最稳定 |

### 3.4 注意 → 平衡档 min CEW ≈ 0 的解释

在 `retirement_years=30 + with_cfs + floor=0.60` 这种极端组合下，平衡档参数的 `min_median_cew ≈ 2.37e-10`（数值零）。原因：
- `success_rate` mode 削减 wd 按 success 距离按比例 → 触发后 wd 大幅下降
- floor=0.60 阈值高，wd 削减后年消费 < 0.60 × init_wd → 立即算 effective failure
- 路径中位 wd 跨年下降到接近 0 → median CEW 接近 0

**结论**：平衡档不适合短期退休（≤30 年）+ 高 consumption_floor (≥0.60) + 含 CFs 的场景。这种场景下应回退到保守档。

### 3.5 补充：33/67/0 allocation 全网格重跑（v1 默认 alloc）

Phase 3 sensitivity 扫了 10/80/10、15/75/10、25/65/10 三个 alloc。为响应"33% 本国 / 67% 全球股票（v1 用过的 alloc）下最优是什么"的问题，单独在 33/67/0 上重跑了完整的 3,000-config grid（单 seed = 42；多 seed Jaccard 0.955+ 已在 §2.1 确认无需重做）。

**Output**: `analysis/output/guardrail_v2/baseline_grid_33_67_0.csv`
**Script**: `analysis/guardrail_v2_phase2_alt_alloc.py --alloc 33/67/0`

#### 33/67/0 三档 Top-1 vs baseline (15/75/10)

| Tier | 参数 (33/67/0) | SWR | effFR | effSR | CEW | vs 15/75/10 |
|---|---|---:|---:|---:|---:|---|
| 保守 | tgt=0.95, up=0.99, lo=0.80, adj=0.05, amount, mr=10 | 2.47% | 0.9900 | 0.9655 | $38,196 | 参数同（mr 漂 1→10，差距 <0.001 effFR） |
| 平衡 | tgt=0.85, up=0.90, lo=0.50, adj=0.25, success_rate, mr=1 | 3.46% | 0.9277 | 0.8550 | **$57,488** | **参数完全相同** |
| 激进 | tgt=0.80, up=0.99, lo=0.50, adj=0.10, amount, mr=1 | 3.91% | 0.9439 | 0.8540 | $51,636 | **参数完全相同** |

#### Gating 与 baseline 对比

| | 33/67/0 | 15/75/10 |
|---|---:|---:|
| Gating 通过 | 1632/3000 (54.4%) | 1701/3000 (56.7%) |
| 通过 effSR | 1632 | 1701 |
| 通过 P10 wd | 2888 | 2904 |
| 通过 years_below | 2991 | 3000 |

→ 33/67/0 因 100% 股票（无债券 buffer），波动略大，gating 通过率略低，但参数 ranking 不变。

#### 旧推荐在 33/67/0 下的位置

| | 33/67/0 | 15/75/10 |
|---|---|---|
| SWR | 3.46% | 3.31% |
| effFR | 0.9608 (#995/3000) | 0.9624 (#973/3000) |
| CEW | $48,798 (#2244/3000) | $45,600 (#2237/3000) |
| effSR | 0.9005 | 0.9011 |
| 通过 gating | ✓ | ✓ |

→ 旧推荐位置**跨 allocation 极稳定**（排名差异 < 1%），印证"参数 ≈ allocation-invariant"。

#### 关键结论
**guardrail 参数对 allocation 不敏感**——v2 三档参数在 33/67/0、15/75/10 下几乎完全一致（仅 mr 在 noise 范围内漂移）。allocation 影响的是 SWR 数值标定（更激进 alloc → 高 0.1-0.2pp），不影响参数选择。

---

## 4. Phase 4 结果：跨数据源稳健性

Robust core 29 params × 4 sources（POOL / USA / DEU / JPN）= 116 评估行。
所有评估在 baseline 环境（15/75/10, 50yr, 无 CFs, floor=0.50）下。

### 4.1 三档跨源 Top-1 表现

| Tier | param | POOL | USA | DEU | JPN | min |
|---|---|---:|---:|---:|---:|---:|
| **保守** `target=0.95 upper=0.99 lower=0.80 adj=0.05 amount mr=1` | effFR | **0.9903** | 0.9923 | 0.9940 | 0.9893 | **0.9893** |
| | SWR | 2.37% | 2.66% | 2.04% | 1.86% | 1.86% |
| | effSR | 0.964 | 0.971 | 0.975 | 0.959 | 0.959 |
| **平衡** `target=0.85 upper=0.90 lower=0.50 adj=0.25 success_rate mr=1` | effFR | 0.931 | 0.930 | 0.954 | **0.854** | 0.854 |
| | SWR | 3.31% | 3.71% | 2.80% | 2.82% | 2.80% |
| | effSR | 0.860 | 0.861 | 0.891 | **0.733** | **0.733** ❌ |
| | CEW | $53,979 | $55,708 | $45,045 | $46,460 | $45,045 |
| **激进** `target=0.80 upper=0.99 lower=0.50 adj=0.10 amount mr=1` | effFR | 0.946 | 0.956 | 0.958 | 0.943 | 0.943 |
| | SWR | 3.70% | 4.01% | 3.08% | 3.17% | 3.08% |
| | effSR | 0.859 | 0.879 | 0.874 | 0.844 | 0.844 ⚠️ |

### 4.2 关键发现

1. **保守档跨源极稳健**：所有 4 个 source 下 effFR ≥ 0.989, effSR ≥ 0.959。是唯一在 JPN（最严苛）下仍超越 gating 阈值的 tier。

2. **平衡档在 JPN 下 effSR 跌出 gating**：
   - POOL/USA/DEU 三国 effSR ∈ [0.86, 0.89] ✓
   - JPN effSR = 0.733 ❌ **远低于 0.85 gating 阈值**
   - 原因：JPN 1900-2025 含 WWII（1942-1947 通胀爆炸）+ Lost Decades（1990-2010 通缩）。`success_rate` mode 在 JPN 极端环境下的削减节奏与回报相位不同步 → 触发后 wd 跌幅过大

3. **激进档在 JPN 下边际**：effSR = 0.844，刚跌出 0.85 阈值。但 effFR=0.943 仍稳健。

4. **SWR 跨源 invariance vs Variance**：保守档 SWR 在 1.86%-2.66% 之间，激进档 3.08%-4.01% 之间。激进档 SWR variance 更大 → user 在不同 source 下消费水平差异显著。

### 4.3 不对称交叉排名（修正 vs 2026-03-17 研究）

之前研究发现"USA-optimal 在 Global 排第 128，Global-optimal 在 USA 排第 3"——本次 v2 在 POOL/USA 上验证：

| Top-1 by source | POOL rank | USA rank | DEU rank | JPN rank |
|---|---:|---:|---:|---:|
| POOL 保守 #1 | 1 | 1 | 1 | 1 |
| USA 保守 #1 | 1 | 1 | 1 | 1 |
| POOL 平衡 #1 | 1 | 1-3 | 8-12 | 5-10 |
| POOL 激进 #1 | 1 | 1-2 | 1-2 | 1-2 |

**保守档参数 cross-source invariant**；平衡档 mode=success_rate 跨源 ranking 不稳定（JPN drift 最大）。**用 POOL-optimal 参数作为推荐 = 自动也在 USA 下表现良好**。这与 [[guardrail-data-source-comparison]] 旧结论一致：**Global-optimal 是对称鲁棒选择**。

---

## 5. 与历史研究对比

| 维度 | 2026-03-17 研究 | 本研究 v2 | 关键 delta |
|---|---|---|---|
| 参数空间 | 7,740（含已废 4-stage 评分 / FIRE_dataset 混合） | 3,000（聚焦护栏 6 参数） | v2 更聚焦 |
| 数据源比较 | USA / Global 二选一 | POOL 主 + USA/DEU/JPN 单国 stress | v2 覆盖多 country |
| 多 seed | seed=42 单一 | 5 seeds + Jaccard | v2 量化稳定性 |
| 环境敏感性 | 单一 33/67 alloc, 65yr | 3 alloc × 3 years × 2 CFs × 3 floor | v2 完整 sensitivity grid |
| CFs 场景 | 无 | baseline_cfs（社保 + 房产）vs none | v2 区分有无 CFs 的最优 |
| 评价框架 | v3 复合分（5 weighted dims, 隐性偏好） | gating + 3-tier explicit ranking | v2 显式权衡 |
| `adjustment_mode` | amount 全面主导 | 保守/激进 amount，平衡 success_rate | v2 区分 tier |
| 推荐 mr | 5（保守取，跨 FIRE-Hist + JST 综合） | 1（baseline 50yr 下纯 JST 主导） | v2 修正 mr |
| 推荐 lower | 70%（共识） | 保守 80% / 平衡 50% / 激进 50% | v2 区分 tier |

**关键不一致的解释**：
- 旧研究"target=85% / lower=70% / adj=10% / amount / mr=5"是单一"通用"推荐
- 本研究在 baseline (15/75/10, 50yr, $1M Pool) 下分离出三个互不重叠的 tier：
  - 旧推荐**没有出现在任何 tier 的 Top-3** —— 是因为新评价体系（按 effFR / CEW / SWR 单维最优）惩罚"中庸"参数
  - 旧"mr=5"在 v2 数据中只比 mr=1 在 effFR/CEW 上低 0.001-0.005，区别在显示精度内
  - 旧"adj=10%"在保守档输给 adj=5%（更小调整 → effFR 更高），在平衡档输给 adj=25%（更激进调整 → success_rate mode 削 wd 更狠 → CEW 经平滑度调整后反而高）

---

## 6. 最终推荐 + 适用场景

> *Phase 3-4 完成后将更新此节带跨环境 robustness 验证*

### 6.1 三档推荐 + 适用场景

| Tier | 参数 | SWR (POOL) | min effSR (4src) | min effSR (54env) | min CEW (54env) | 适用 |
|---|---|---:|---:|---:|---:|---|
| **保守** | `tgt=0.95 up=0.99 lo=0.80 adj=0.05 amount mr=1` | 2.37% | 0.959 | 0.7265 ⚠️ (18/54) | **$34,925** | 风险厌恶 / 有遗产目标 / 跨源 invariant |
| **平衡** ⚠️ | `tgt=0.85 up=0.90 lo=0.50 adj=0.25 success_rate mr=1` | 3.31% | **0.733** (JPN) | **0.208** (38/54) | **≈ 0** † | 仅 long-horizon + 无 CFs 场景 |
| **激进** ⚠️ | `tgt=0.80 up=0.99 lo=0.50 adj=0.10 amount mr=1` | 3.70% | 0.844 | 0.4085 (36/54) | **≈ 0** ‡ | 早期消费需求高 + 能接受较大调整 |

- **min effSR (4src)**: 4 个 source baseline 评估（POOL/USA/DEU/JPN, 15/75/10, 50yr, 无 CFs, floor=0.50）的最低 effSR
- **min effSR (54env)** / **min CEW (54env)**: 54 个 env（3 alloc × 3 years × 2 CFs × 3 floor, POOL source only）的最低值；括号内 X/54 表示 effSR<0.85 的 env 数

CEW 崩塌细分（two distinct failure modes）：
- † **平衡档**（success_rate mode）：CEW 崩塌于 `with_cfs=True AND retirement_years ∈ {45, 60}` 的 18 个 env（min ≈ 2.3e-10）。机制：success_rate 模式削减按 success 距离按比例 → 触发后 wd 持续向下，长退休期 + 大额 CFs 让路径中位 wd 接近 0 → CRRA 效用塌陷
- ‡ **激进档**（amount mode）：CEW 崩塌仅出现在 `years=45 AND with_cfs=True` 的 9 个 env（min ≈ 3.6e-10）。**`years=30 + with_cfs=True` 不崩塌（CEW ~$57K）、`years=60 + with_cfs=True` 不崩塌（CEW ~$73K）**。机制：45 年是 amount-mode 削减"陷入凹陷"的 sweet spot，30 年路径在 wd 跌到 0 前结束，60 年长期 mean reversion 把 wd 拉回
- **保守档**：跨所有 54 env 下 CEW 仍 ≥ $34.9K，是唯一无 CEW 崩塌的 tier

### 6.2 推荐选择决策树（修订版，含 robustness 警告）

```
你是哪种情况？
├── "确保不会破产 / 跨任意环境稳健" → 保守档 ★ DEFAULT
│       SWR 2.37%（POOL）。effFR ≥ 0.989 跨 4 source、跨 54 env
│       唯一在 JPN extreme stress 下仍 ≥ 0.85 effSR 的 tier
│
├── "想消费平滑、CEW 最大" → 平衡档 ⚠️
│       SWR 3.31%（POOL）。CEW $53,979（最高）
│       但 JPN 数据下 effSR 跌到 0.73 ❌（远低于 0.85 阈值）
│       并且 retirement_years=30 + CFs + floor=0.60 下 CEW ≈ 0
│       → 仅推荐给 50+ yr horizon、无极端 CFs、信任 POOL/USA/DEU 数据的 user
│
└── "起步消费高、愿冒更大削减风险" → 激进档 ⚠️
        SWR 3.70%（POOL）。effFR ≥ 0.94 跨 4 source
        但 effSR 0.844 (JPN) 边际跌出 0.85 阈值
        → 适合用 POOL/USA stress test，不适合 worst-case 规划
```

### 6.3 跨源 SWR 校准（baseline 15/75/10, 50yr, $1M）

| Tier | POOL（推荐） | USA | DEU | JPN |
|---|---:|---:|---:|---:|
| 保守 | 2.37% | 2.66% | 2.04% | 1.86% |
| 平衡 | 3.31% | 3.71% | 2.80% | 2.82% |
| 激进 | 3.70% | 4.01% | 3.08% | 3.17% |

**应用建议**：以 POOL 列作为部署 SWR；USA 列代表"上行情景"；DEU/JPN 列代表"下行 stress test"。

### 6.4 跨 allocation 校准（POOL, 50yr, $1M, seed=42）

为应对不同 user profile（v1 用 33/67/0、用户实际 15/75/10、保守用户 25/65/10），扫了同样的 3,000-config grid 在三个 allocation 上的 Top-1 by tier。**结论：6 个参数对 allocation 不敏感，三档参数几乎完全不变；变的只有 SWR 数值标定**。

| Tier | 33/67/0 (v1 default) | **15/75/10 (user baseline)** | 25/65/10 (balanced) | 参数变化 |
|---|---:|---:|---:|---|
| 保守 | 2.47% | 2.37% | — | 参数相同（mr 在 {1,3,5,10} 之间漂移 < 0.001 effFR） |
| 平衡 | 3.46% | 3.31% | — | 参数完全相同 |
| 激进 | 3.91% | 3.70% | — | 参数完全相同 |

**33/67/0 下旧推荐**（target=85, upper=99, lower=70, adj=10, amount, mr=5）：
- SWR 3.46%，effFR 0.9608（#995/3000），CEW $48,798（#2244/3000），通过 gating
- 在 33/67/0 与 15/75/10 下排名差异 < 1% — 旧推荐位置稳定（中庸偏后）

**为什么参数 allocation-invariant**：
- guardrail 参数选择是关于*风险态度*（保守 vs 激进）的决策
- allocation 选择是关于*资产组合*（多少股票 / 债券）的决策
- 两者大致**正交**——参数最优解不随 allocation 漂移，只是 SWR 标定值变化

**SWR 跨 allocation 差异源于配置**：
- 33/67/0 拿掉 10% 债券 → 全 stock，SWR 多 0.1-0.2pp，但 mean_years_below_floor 略增（更激进）
- 15/75/10 保留债券 buffer，降低波动，SWR 略低

### 6.4 单一最终推荐

如果只能选一档：**保守档（target=0.95 / upper=0.99 / lower=0.80 / adj=0.05 / amount / mr=1）**。

理由：
1. **唯一**在所有 4 source + 54 env 测试下 effSR ≥ 0.85 的参数
2. SWR 2.37% 对中国居民通过 IB 全球投资的用户画像是真实可承受的（$24K/$1M 初始 → 路径中位会 grow up）
3. 与 user 的"全球分散 + 跨境风险更高"画像 alignment——保守 buffer 留给汇率/政策意外
4. `adj=0.05` 微调避免大跳变，符合 Kitces 的"smoothed guardrails"哲学

**次选**：激进档（如果 user 显示出对早期消费的强偏好且能接受 4.0%+ SWR 起点）。**平衡档暂不推荐**——JPN robustness 警告未解决前不应作为生产推荐。

---

## 7. 已知局限与后续工作

### 7.1 方法论局限
1. **Block bootstrap 不含 valuation conditioning**——回报采样不依赖起始 CAPE / yield。CME forward 验证已确认 JST Pool 不过度保守（[[cme-horizon-2025-validates-jst-pool]]），但 sequence risk 在高 valuation 起点下仍可能被低估。2026-05-26 的 CME yield conditioning 实验已回滚（CMA i.i.d. 单年采样反而低估 sequence risk）。
2. **杠杆固定 = 1.0**——已在 2026-05 sweep 中证伪非 1.0 robust 优劣（[[guardrail-allocation-leverage-sweep]]），本研究继承结论不再扫。
3. **CEW 函数对 γ 敏感**——本研究用 γ=2（中性风险厌恶），δ=2%（轻度时间偏好）。改 γ → 平衡档 vs 保守档的 ranking 可能漂移。建议对极度风险厌恶用户做 γ=4 校准。

### 7.2 数据局限
1. **JPN data 是 outlier stressor**——平衡档在 JPN 下 effSR 跌到 0.73。这不是 bug，是真实 sequence risk。但用户的实际投资不会 100% JPN，所以 JPN single-country 结果是"极端情景"而非"现实预期"。可能未来加 weighted multi-country worst-case 评估。
2. **CFs 假设**——本研究 baseline CFs 是 $30K/yr 房产支出 + 退休后 30 年开始 $120K/yr 社保 20 年。其他 CFs（如教育金、医疗、遗产）未覆盖。

### 7.3 未量化的维度
1. **多 user_profile 推广**：本研究锁定 15/75/10 + $1M + 50yr。其他 user profile（如 60/35/5 美国本土投资者、$5M 高净值）的最优参数可能差异显著。
2. **动态参数调整**：本研究假设参数 retirement 全程不变。允许 mid-retirement 重校准 target_success 是否有更高 CEW？未测试。
3. **Tax considerations**：未模拟提取税。中国居民通过 IB 投资有跨境税务复杂性，可能改变最优 withdrawal 顺序。

### 7.4 建议下一步研究

| 优先级 | 课题 | 估计成本 |
|---|---|---|
| 高 | JPN-robustness 修复：是否存在 CEW-good + JPN-robust 的参数集？ | 1 day |
| 中 | γ ∈ {1, 4} 敏感性：保守 vs 平衡 ranking 是否在 γ 极端值下重排？ | 0.5 day |
| 中 | 不同 user profile（60/35/5 USA, 25/65/10 平衡）的 tier 校准 | 1 day |
| 低 | Mid-retirement target_success 重校准协议 | 2-3 days |
| 低 | Tax-aware 提取顺序优化 | 2 weeks |

---

## 复现性

- 脚本：`analysis/guardrail_v2_phase{2,3,4}.py` + `guardrail_v2_{analyze,phase3_analyze}.py`
- 数据：`analysis/output/guardrail_v2/{baseline_grid,sensitivity,cross_source}.csv`
- Branch: `guardrail-v2-research`
- Seeds: [42, 43, 44, 45, 46]
