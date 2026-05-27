# 护栏最优参数 v2：全面研究计划

**日期**: 2026-05-26
**作者**: Billy Ren
**状态**: Draft (待 Codex review)
**目标读者**: 自己 + Codex reviewer

---

## 0. TL;DR

之前关于"最优护栏参数"的研究（2026-03-17 7,740 grid + 2026-05-18 allocation/leverage sweep）分散在多个 ad hoc 脚本中，存在三类未深入的盲点：

1. **维度盲点**：target / retirement_years / consumption_floor / CFs / seed 都是单点固定，没做敏感性
2. **指标盲点**：单一 effFR 排序有偏（bond-heavy 陷阱），复合分加权未充分论证
3. **稳健性盲点**：跨数据源对称性、Top-K 邻域分布、bootstrap 置信区间都没量化

本研究目标：**对中国居民全球投资者（user profile 见 §3），给出一组在合理 user profile 邻域内 robust 的护栏推荐参数，并量化其相对最优损失（regret）和敏感性。**

整个研究分 5 个 Phase 跑完。当前 Phase 1 = 本计划文档。

---

## 1. 历史研究脉络与已知结论

### 1.1 已完成的工作
| 时间 | 研究 | 主要产出 | 文件 |
|---|---|---|---|
| 2026-03-17 | 7,740 参数 grid search (USA vs Global) | target=85% 下推荐 `upper=99/lower=70/adj=10/amount/mr=5` | `docs/guardrail-data-source-analysis.md` |
| 2026-04-22 | CME Horizon 2025 vs JST Pool cross-check | Pool Dom_Stock 4.35% ≈ CME 4.49%，非过度保守 | `memory/cme-horizon-2025-validates-jst-pool.md` |
| 2026-05-18-19 | Allocation × Leverage 二维扫描 | Pool 最优 10/80/10，杠杆=1.0 robust | `memory/guardrail-allocation-leverage-sweep.md` |
| 2026-05-26 | CME forward CMA + yield filter 实验（**回滚**） | CMA i.i.d. 低估 sequence risk；plan 文档保留 | `docs/plan-2026-05-26-cme-yield-conditioning.md` |

### 1.2 已知结论（作为本研究的输入假设）
1. **数据源**：JST Pool 1900+ 是非美投资者的 baseline；JST USA 是上行 stress；FIRE_dataset 1970+ 太短不推荐
2. **target 甜蜜点**：80-85% 护栏增值 16-23%；≥90% 增值消失；95% 增值为负
3. **杠杆**：1.0 全局 robust 最优（不再扫）
4. **数据源风险天然对冲**：护栏把 18pp 数据源差压缩到 2pp
5. **Pool 与 USA 参数不对称**：Global-optimal 在 USA 仍排前 5；USA-optimal 在 Global 排第 100+

### 1.3 已知陷阱（要在 §4 评价体系里 explicit 规避）
1. **effFR 单指标偏 bond-heavy**：SWR 低 → 不触发护栏 → effFR ≈ rawFR → 排名虚高
2. **min_remaining_years 1 vs 5 矛盾**：纯 MC 偏好 1，加入历史回测偏好 5 → 之前保守取 5，未证伪
3. **单 seed 排名稳定性未量化**：所有之前 sweep 都用 seed=42
4. **CFs 缺席**：之前 sweep 都是无 cash flow 场景；用户真实 profile 含养老金 + 房产，CFs 改变护栏触发频率

---

## 2. 研究问题与决策结构

### 2.1 决策变量
6 个护栏参数 + 1 个 target 选择：

| 参数 | 取值集合 | 维度 |
|---|---|---:|
| `target_success` | {0.75, 0.80, 0.85, 0.90, 0.95} | 5 |
| `upper_guardrail` | {0.90, 0.95, 0.99} | 3 |
| `lower_guardrail` | {0.10, 0.20, 0.50, 0.70, 0.80} | 5 |
| `adjustment_pct` | {0.05, 0.10, 0.15, 0.20, 0.25} | 5 |
| `adjustment_mode` | {amount, success_rate} | 2 |
| `min_remaining_years` | {1, 3, 5, 10} | 4 |

**全组合 = 5 × 3 × 5 × 5 × 2 × 4 = 3,000** （扣除 lower ≥ upper 等无效组合，实际 ~2,000–2,500）

> **Codex review 修正 (2026-05-26)**: 移除了 `rate` mode。`backend/schemas.py:198/252/371` 用 `pattern="^(amount|success_rate)$"` 验证，`rate` 在 schema 层失败、在 simulator 层会落入 amount 分支（重复采样）。如未来扩展独立 rate-mode 实现，再纳入。

### 2.2 环境变量（决策外的"世界状态"）
| 维度 | 取值集合 | 说明 |
|---|---|---|
| `data_source` | {JST Pool, JST USA, JST DEU/JPN（单国 stress）} | Pool 主，USA/DEU/JPN 做不对称稳健性 |
| `allocation` | {10/80/10, 25/65/10, 60/30/10} | 用户实际 + 美投资者 baseline + 中等 |
| `retirement_years` | {30, 45, 60} | 早 FIRE 用 60，普通 FIRE 用 45，传统退休 30 |
| `cash_flows` | {无, 用户真实 CFs} | 无 = 纯学术；CFs = 含中国社保 + 房产 |
| `consumption_floor` | {0.40, 0.50, 0.60} | 50% 是 baseline，扫前后量化敏感性 |
| `seed` | 10 个不同 seed | 量化排名稳定性 |

### 2.3 评价输出（每个组合都要算）
- `success_rate`（终值 > 0 完整路径占比，已修正 censored）
- `effective_success_rate`（含 consumption_floor 等效失败）
- `funded_ratio`, `effective_funded_ratio`
- `initial_withdrawal`（target 反算的 SWR）
- `CEW`（CRRA γ=2，2% 时间偏好）
- `P10/P50/P90 年度消费分布`
- `max_drawdown`（最大单年消费跌幅）
- `years_below_floor`（年消费低于 floor 的累计年数）

---

## 3. User Profile 定义（Baseline 锁定）

为了使最终推荐对用户有实际意义，定义 baseline user profile（中国居民通过 IB 全球投资）：

```yaml
data_source: JST Pool 1900+ (country=ALL, pooling=gdp_sqrt)
allocation:
  dom_stock: 0.15    # A 股/港股
  global_stock: 0.75 # IWDA / VWRA
  bond: 0.10         # BNDW / 人民币定期
expense_ratio: 0.005
leverage: 1.0
retirement_years: 50
consumption_floor: 0.50
initial_portfolio: 1_000_000
cash_flows:
  # CashFlowItem schema: amount > 0 = income, amount < 0 = expense
  # start_year (relative to retirement start) + duration (years)
  - { name: "中国社保", amount: 120_000, start_year: 30, duration: 20, inflation_adjusted: true }   # 退休后 30 年（约 60 岁）开始领，覆盖 20 年
  - { name: "房产维护", amount: -30_000, start_year: 0, duration: 50, inflation_adjusted: true }    # 全程支出
seed: 42
num_simulations: 2000
```

> **Codex review 修正 (2026-05-26)**: 原版用了 simulator 不支持的 `start/end/type` 字段且符号反了（社保被建模为 -120K 支出、房产被建模为 +30K 收入）。已改用 `simulator/cashflow.py` 的真实 schema（`start_year/duration/amount`，正号 = 收入、负号 = 支出）。

**这个 profile 是 Phase 2 的 anchor**。Phase 3-4 围绕它做敏感性。

---

## 4. 评价指标体系设计（本研究的核心方法论部分）

这一节本身是研究问题之一，不是给定的。

### 4.1 候选指标家族

| 家族 | 例子 | 优点 | 缺点 |
|---|---|---|---|
| **概率类** | success_rate, effSR | 直观、易解释 | binary，对消费质量盲 |
| **比例类** | funded_ratio, effFR | 连续、含尾部信息 | 与 SWR 反相关时偏 bond-heavy（陷阱） |
| **效用类** | CEW (CRRA), 时间贴现期望效用 | 经济学严谨、含风险偏好 | 对 γ 敏感、解释门槛高 |
| **分位类** | P10 消费、P50/初始消费倍数 | 用户友好，反映"最差年"和"中位日子" |  |
| **过程类** | max_drawdown, years_below_floor | 反映平滑度 | 与最终成败弱相关 |

### 4.2 拟定多指标设计原则
1. **gating + ranking 二段式**：先用 hard constraint 过滤明显不安全方案，再在合格集合内排序
2. **多指标 Pareto 前沿**：不强求单一最优；给"保守 / 平衡 / 激进"三档推荐
3. **指标透明可解释**：用户能理解每个推荐的取舍

### 4.3 拟定指标体系（待 Codex review 验证）

**Gating 层**（hard constraint，必须同时满足）：
- `effective_success_rate ≥ 0.85`（数据源稍弱时仍可改）
- `P10 年消费 ≥ initial_withdrawal × 0.6`（最差 10% 路径仍有 60% 初始消费）
- `years_below_floor ≤ 5`（中位路径上跌破地板年份不超过 5 年）

**Ranking 层**（在 gating 通过集合内）：
- **保守目标**：max `effFR`（保护本金；倾向 bond-heavy / 低 SWR 候选）
- **平衡目标**：max `CEW`（CRRA γ=2 时间贴现 2% 的确定性等价年消费；天然平衡水平 × 平滑度 × 下行）
- **激进目标**：max `initial_withdrawal`（在 gating 内最大化 SWR；倾向 stock-heavy / 高消费起点）

> **Codex review 修正 (2026-05-26)**: 原版用 `CEW × initial_withdrawal` 作为 balanced ranking 是错误的。`analysis/guardrail_optimization.py:219` 中 `compute_cew()` 返回的是年消费 dollar amount（按 `(mean_utility × (1-γ))^(1/(1-γ))` 反 utility），本身已经是绝对消费水平。再乘 initial_withdrawal 会做 dollar^2 单位 + 重复计入水平 → 严重偏向激进。改用直接 max CEW（CRRA 已内嵌"水平 × 平滑度 × 风险厌恶"的 trade-off）。

**为什么不直接用复合分公式**：复合分加权是隐藏的偏好——明确分档让用户/读者看到取舍。

### 4.4 关键稳健性检查（每个候选参数都要算）
1. **跨 seed 排名稳定性**：10 个 seed 下 Top-50 集合的 Jaccard 相似度
2. **跨数据源不对称性**：Pool Top-1 在 USA 排名 + USA Top-1 在 Pool 排名
3. **邻域 regret**：在最优参数附近 ±1 step 邻域内，最差性能与最优的差值
4. **Bootstrap 置信区间**：对 Top-K 的 CEW 给出 95% CI（避免过拟合到 seed）

---

## 5. 实验设计（5 个 Phase）

### Phase 1：研究计划 + Codex review（当前）
- 输出：本文档
- Codex review：方法论、指标体系、参数空间、user profile 合理性
- 修正：根据 review 反馈调整参数空间或指标设计

### Phase 2：Baseline 全参数 grid（user profile anchor）
- 锁定 §3 baseline，扫 §2.1 有效组合（~2,000–2,500 个，扣除 lower ≥ upper）
- 每个组合 2,000 sim × 10 seed = 20,000 paths
- 总计约 **2,500 × 20,000 = 5×10⁷ paths（5 千万）**
- 输出：`analysis/output/guardrail_v2/baseline_grid.csv`
- 预计算时长：单 seed 8-12 分钟（vectorized sweep fast path），10 seed = 1.5-2 小时
- 产出：Top-50 候选，分 gating/ranking 三档

> **Codex review 修正 (2026-05-26)**: 原版"3,000 × 20,000 = 6 亿"算术错。3000 × 20000 = 6×10⁷ = 6 千万；扣除无效组合后 ~5 千万。Phase 2 预算口径已对齐。

### Phase 3：环境敏感性扫描
对 Phase 2 的 Top-50 候选，在 §2.2 的环境变量上做 sensitivity：
- 3 个 retirement_years × 3 个 allocation × 2 个 CFs 场景 × 3 个 floor = **54 个环境**（按 §2.2 表对齐）
- Top-50 × 54 = 2,700 个评估点
- 输出：`analysis/output/guardrail_v2/sensitivity.csv`
- 目标：找出在所有 54 个环境下 effFR/CEW 排名都在前 20 的参数集（"robust core"）

> **Codex review 修正 (2026-05-26)**: 原版写 "5 个 retirement_years"，与 §2.2 表中的 3 个值（30/45/60）不一致。统一为 3 × 3 × 2 × 3 = 54 环境。

### Phase 4：跨数据源稳健性
- 锁定 Phase 3 的 robust core (~10-15 组参数)
- 跑 JST USA、JST DEU、JST JPN（单国 stress test）
- 量化不对称交叉排名 + emergency-case behavior
- 输出：`analysis/output/guardrail_v2/cross_source.csv`

### Phase 5：最终推荐 + Codex review + 集成到 UI
- 综合 Phase 2-4，给出三档推荐（保守/平衡/激进），每档给：
  - 推荐参数
  - 在 baseline profile 下的预期表现（4.4 全指标）
  - 邻域 regret + 跨源 worst-case
  - 适用场景说明
- 写成报告 `docs/guardrail-optimal-params-v2.md`
- Codex review 报告
- 把推荐预设写进前端 `/guardrail` 页面 preset 按钮

---

## 6. 计算预算与 Timeline

| Phase | 计算量 | 实际时长 | 备注 |
|---|---|---|---|
| 1 | 0 | 0.5 day | 写 plan + review 周期 |
| 2 | 5 千万 paths | 2-3 小时 | vectorized fast path |
| 3 | 5.4 百万 paths | 10-15 分钟 | Top-50 × 54 env × 2000 sim |
| 4 | 1 百万 paths | 2-3 分钟 | 15 × 3 source × 2000 sim × 1 seed |
| 5 | 0 | 1 day | 写报告 + UI 集成 + review |

总：约 **3-4 个工作日**（含两次 Codex review 周期）

**降级方案**（如 Phase 2 太慢）：
- 单 seed → 用 Phase 2.5 阶段补 10-seed 稳定性（只对 Top-100）
- 参数 grid 粗化（adj 减到 3 档、lower 减到 3 档）

---

## 7. 产出 Deliverables

1. **本计划文档** + Codex review 反馈
2. **3 个 CSV**: baseline_grid / sensitivity / cross_source
3. **最终报告** `docs/guardrail-optimal-params-v2.md`
4. **复现脚本** `analysis/guardrail_v2_optimization.py`（保留，不删）
5. **UI preset**: 3 档推荐进 `/guardrail` 页面 dropdown
6. **更新 memory**: `guardrail-optimal-params-v2.md` 替代旧条目

---

## 8. 风险与失败模式（Pre-mortem）

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| Gating 太严无候选通过 | hard constraint 设置过激进 | Phase 2 先无 gating 跑全网格，根据 CDF 校准 |
| Top-50 跨环境完全不重叠 | 参数对环境过度敏感 | 退而求其次：按环境分组给推荐（牺牲单一性） |
| 单 seed 排名极不稳定 | bootstrap variance 太大 | 增加 num_simulations 到 5,000 或 seed 到 20 |
| 推荐参数与之前 7740 grid 推荐相同 | 没有新增价值 | 至少把"为什么是相同的"量化（rabust core 大小、邻域 regret） |
| CFs 场景改变最优参数显著 | user profile 偏向真实，假设需重新审视 | Phase 3 单独报告"有/无 CFs"对比 |
| Codex review 指出指标体系根本性问题 | 加权或 gating 设计有逻辑漏洞 | 在 Phase 2 跑之前修正，节省计算 |

---

## 9. 复现性 + Commit 策略

- 全部脚本 commit 到 `analysis/` 目录（**不**删除一次性脚本，这次保留作为可复现 evidence）
- 所有 raw CSV 输出 commit（小于 10 MB）
- 每个 Phase 完成后单独 commit + 更新 plan 状态
- Phase 2-4 用 feature branch `guardrail-v2-research`，最终 squash 到 main

---

## 10. 待 Codex review 的关键决策点

请 reviewer 特别检查以下设计选择：

1. **§2.1 参数空间够全吗？** 还有没遗漏的护栏参数（如 floor amount、CFs adj coefficient）？
2. **§2.2 环境变量是否合理？** allocation 三档 / years 三档 / CFs 二档 是否够代表性？
3. **§3 user profile 锚定是否过窄？** 锁定 15/75/10 是否会让结论失去普适性？
4. **§4.3 gating 阈值（effSR≥0.85、P10≥60% initial、years_below_floor≤5）合理吗？** 是否有更好的校准方法？
5. **§4.4 稳健性检查指标完整吗？** 还有什么常见的过拟合检测我没考虑？
6. **§5 Phase 划分有没有逻辑遗漏？** 比如 Phase 3 用 Top-50 是否会错过 Phase 2 单 seed 排名靠后但跨环境 robust 的方案？
7. **§8 风险列表有没有遗漏？** 特别是隐藏的实验性偏见。

请保持 critical，不要客气。
