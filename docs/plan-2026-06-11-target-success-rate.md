# Plan: 用户个人目标成功率研究（固定提取 vs 风险护栏）— 2026-06-11

## 0. 问题定义

用户（35 岁中国居民，配偶+孩子，IB 全球投资）问：

1. **固定提取**策略下，目标成功率应该定多少？（由此反解可持续的基础年消费）
2. **风险护栏**策略下，目标应该定在**最终（realized）成功率**上而非初始 target——那 realized 目标定多少？（由此反推 guardrail `target_success` 参数）

### 口径定义（必须在报告中显式区分）

| 口径 | 含义 | 代码 |
|---|---|---|
| 固定提取 success_rate | 65 年内资产从未耗尽（last-year depletion = success） | `compute_success_rate(traj, years)` |
| Guardrail **raw realized** success | 同上，但提款被护栏逐年调整后 | 同上，应用于 guardrail traj |
| Guardrail **effective** success | 资产未耗尽 **且** 年消费未跌破 floor（默认 0.5×初始提款，等效耗尽口径） | `compute_effective_funded_ratio(...)` —— 产品 `/guardrail` 页报给用户的就是这个 |
| 死亡率加权破产概率 | P(在世时破产) = Σ P(首次破产=t) × P(35+t 岁仍在世)，Gompertz SSA 2021 | 分析脚本内实现（参数取自 `frontend/src/lib/mortality.ts`），单人 male + 夫妻 joint(至少一人在世) 两个口径 |

**Guardrail 关键语义**（已验证代码）：模拟本身没有硬消费 floor——提款只受 `adj=5%` 每年最多削减一次约束，可以一路降；floor 只存在于评价指标。因此 raw realized success 可以靠"消费崩塌"换来，**不能单独作为目标**——必须配 CEW / P10 min wd / effective 口径一起看（与 memory [[project-portfolio-optimization-objective]] 一致：success_rate 只做硬约束，CEW 做主目标）。

### Codex 计划评审后的修订（2026-06-11）

采纳：(1) effective success 增加**绝对 essential floor 口径**（基础消费 ¥30 万，敏感性 ¥25/35 万）与相对 0.5 口径并列，并报告跌破 floor 的深度/久度；(2) 决策框架重构——**决策变量是"稳健消费水平"**，三数据源是同一消费水平的三个成功率读数，不再"每个模型配一个目标"（避免混淆模型保守性与风险偏好）；(3) fixed N=20,000 + 反解点 Wilson CI，99% 反解标注外推；(4) 增加 fragile-success（成功路径中终值 < 3 年总支出比例）、bridge 诊断（yr<25 破产概率、guardrail 首次下调时点）；(5) block 8-20 对照（POOL fixed，轻量）；(6) 文献修正：Bengen=历史 SAFEMAX 锚点而非 95% 目标、Trinity=成功率矩阵、补 Scott-Sharpe-Watson 2009 与 Finke-Pfau-Blanchett 2013、Morningstar/Income Lab 数字需 WebSearch 核实。

明确跳过：guardrail 规则族敏感性（v2 3000-config 已覆盖，固定 F 族）；allocation 网格（v2 不变性结论，结论条件于 33/67/0 附近）；branch-aware lookup table（产品级改造；表偏差被 target→realized 实测映射吸收）；中国生命表（SSA 寿命偏长 = 破产风险方向上保守）；税/FX/资本管制建模（POOL 数据源即其代理，列为 caveat）。Guardrail 内部 CF 分支抽样不可注入 CRN——以 3-seed 漂移量化该噪声。

## 1. 用户场景（fire-scenario-2026-06-07.json）

- 初始组合 ¥24,000,000；基础年提取 ¥500,000（初始 2.08%，**这只是基础消费，不含下列 CF**）
- 配置 33/67/0（dom/global/bond），expense 0.005，block 5-15，65y（35→100 岁）
- 现金流（概率组，per-path 抽样）：
  - 教育（yr3 起 12 年）：-5 万 (25%) / -15 万 (75%)
  - 大学（yr15 起 4 年，growth 1%）：-70 万 (30%) / -10 万 (40%) / -40 万 (30%)
  - 社保收入（yr25 起 41 年）：+20 万 (50%) / +10 万 (50%)
  - 住房（65 年）：租房 -25 万×65y (90%) / 买房 -25 万×5y + -45 万×30y@yr6 (10%)
  - 确定项：yr1 一次性 +300 万；社保缴费类 -6 万×65y、-3 万×23y、-3 万×15y
- 前 24 年 gross 支出 ≈ 50+25+15+9 ≈ 99 万/年（民办+租房情形）≈ 初始组合 4.1%；yr25 后社保 +10~20 万对冲。**前 25 年（教育期+无社保）是风险窗口**，sequence risk 被 CF 结构放大。
- 文件里 `country="USA"`；但 memory 长期结论 + 用户本次确认：**JST ALL 池化（等概率, 1900+）是用户默认 baseline**；另跑两个美国对照源——**JST USA 1900+**（长史，含 1929 / 1966-82 完整危机）与 **FIRE_dataset US 1970+**（现代美国真实数据，用户指定的重要参考）。结论以 POOL 为主、三源配套陈述。

## 2. 实验设计

共享设置：`initial=24M`、alloc 33/67/0、expense 0.005、block 5-15、65y、用户全部 14 项 CF、`pregenerate_raw_scenarios` 共享 bootstrap（common random numbers，同源同 seed 下固定提取扫描各点用同一组路径）。N=10,000（90% 处 stderr ≈ ±0.3pp）。Seed=42 为主，关键结论点用 seed ∈ {42, 60042, 120042} 三 seed 复核（间隔 > N，规避 [[project-bootstrap-seed-overlap-pitfall]]）。

### 实验 A：固定提取——成功率 vs 基础年消费曲线
- 扫描 base `annual_withdrawal` ∈ [30 万, 80 万]，步长 2.5 万（21 点）× {POOL, JST_USA, FIRE_US}
- 每点输出：success_rate、median/p10 final、funded_ratio、失败路径破产年分布（p10/p25/p50）、死亡率加权 P(broke while alive)（单人 + joint）
- 读数 1：用户当前 50 万处在曲线什么位置（两个数据源下各多少成功率）——讨论锚点
- 读数 2：反解各目标成功率（75/80/85/90/95/97.5/99%）对应的最大基础消费 → **边际代价表**："从 90% 提到 95% 要每年少花 X 万"
- 读数 3：失败时间结构 + 死亡率折扣后，"模型内失败"中有多大比例发生在大概率已离世的年纪

### 实验 B：模型不确定性定标
- 同一消费水平（如 50 万）在 USA vs POOL 的成功率差值（预计 10-20pp）→ 论证"数据源选择的影响 >> 目标成功率 5pp 之争"，目标成功率必须与数据源配套陈述
- 参考 [[project-walk-forward-mc-vs-backtest]]：POOL MC 在动荡期 out-of-sample 偏保守（−7.6pp），良性期略保守 → POOL 模型内 90% 在真实历史的 out-of-sample 含义

### 实验 C：guardrail target 扫描（核心）
- F 族固定：`upper=0.99 / adj=0.05 / amount / mr=1`；`lower = target − 0.10`（用户哲学约束 gap≥10pp）
- target ∈ {0.70, 0.75, 0.80, 0.85, 0.90, 0.95} × {POOL, JST_USA, FIRE_US}
- 产品全语义：2D 表 + CF-aware 3D 表（`build_representative_cf_schedule` 期望值口径，与产品一致）+ `initial_portfolio=24M` 反算 init_wd
- 每点输出：init_wd（基础消费起点，与固定提取的 50 万直接可比）、init SWR、**raw realized success**、**effective success（floor=0.5）**、CEW(γ=2, δ=2%) median/p10、P10 min wd、P10 avg wd、severe_fail = P(funded_ratio<0.5)、mean years below floor、median final
- 读数 1：**65y + 用户 CF 下的 target → realized 映射表**（50y 无 CF 时 0.85→90.3%；65y 怎么移）
- 读数 2：realized-success vs 初始消费 vs CEW 的 frontier → 在哪个 realized 水平边际交换比恶化
- 读数 3：CF 刚性占比高（教育/租房不可调）对调整杠杆的削弱——guardrail 在该场景的调整空间还剩多少

### 实验 D：稳健性
- 实验 A 的 2 个关键点（90%/95% 对应消费）+ 实验 C 的 2 个关键 target（0.85/0.90）× 3 seeds
- 若 3 seed 间 realized 漂移 > 1pp，结论数字给区间而非点值

### 实验 E：失败/低消费的时间结构（轻量，从 A/C 现有输出推导）
- 固定提取：破产年份直方图 + 死亡率加权
- guardrail：消费跌破 floor 的首次年份分布、跌破后是否回升（[[consumption-floor-recovery]] 已有方法可借）

实现：新脚本 `analysis/target_success_rate_2026_06_11.py`（复用 `optimal_allocation_cew.py` 框架 + `run_simulation` / `run_guardrail_simulation` + 用户 JSON 直接解析为 `CashFlowItem`）。输出 `analysis/output/target_success/`。

## 3. 文献/业界对照清单（与实验并行）

| 来源 | 立场要点 | 用途 |
|---|---|---|
| Bengen 1994 / Trinity 1998 | 30y 95%+ 成功率传统；4% rule 的语义是"历史全成功" | 基线，但 30y≠65y |
| Kitces（probability of success 系列） | 高 PoS 的隐性代价=中位巨额遗产；有调整能力时 70-90% 即合理；50% 亦有论证 | 支持"固定提取目标不必 99%" |
| Income Lab / Hatchet (Fitzpatrick) | risk-based guardrails 哲学：把"破产概率"换成"调整概率"；实务初始 PoS 常用 70-85% | guardrail target 的业界锚 |
| Morningstar State of Retirement Income 2022-24 | 90% 成功率为基准的 SWR 年度研究（30y） | 90% 是业界事实标准 |
| ERN SWR series（60y horizon） | 长 horizon 渐近永续；非美/估值调整后建议 ~3.25-3.5%；失败率对提款率极敏感 | 65y 特殊性 |
| Pfau 国际数据研究 | 非美国家 4% 失败率可 >50%；模型选择 >> 目标微调 | 支持 POOL baseline + 配套陈述 |
| Milevsky（ruin probability / mortality-weighted） | 用死亡率加权破产概率替代固定 horizon | 实验 E 的理论依据 |
| Blanchett（spending smile/dynamic） | 实际消费随龄下降；固定实际提款本身偏保守 | 解读 65y 固定提取的保守度 |

WebSearch 仅用于核对我记忆中的具体数字/标题是否准确（如 Morningstar 最新年度数字、Income Lab 的默认 PoS 区间），不依赖搜索结果做核心论证。

## 4. 决策框架（从数据到建议）

**固定提取目标成功率** = f(边际代价曲线斜率, 死亡率加权折扣, 模型误差量级, 家庭刚性/调整能力, 业界规范)：
- 若 65y 下 90→95% 的年消费代价 < ~3 万（占基础消费 6%），倾向高档（95%）；若代价 > ~6 万，倾向 90% 并指出 95% 买的是模型内伪精度
- 死亡率加权后若 95% 模型内目标的"在世破产率"已 <1-2%，则更高目标无意义
- 数据源配套：给 (POOL, X%) 和 (USA, Y%) 两套配套建议，X ≤ Y（POOL 自带模型保守性）

**Guardrail realized 目标** = 硬约束(raw realized ≥ 下限) + 软目标(CEW 最大) + 尾部(severe_fail, P10 min wd)：
- 下限候选 90%（与 50y 研究一致）vs 85%（65y 更难）——由实验 C 的 frontier 定
- 必须同时报 effective(floor=0.5) 口径，防"消费崩塌换名义成功"
- 给出推荐 target 参数（F 族）+ 预期 realized + init_wd，与固定提取方案同表对比

## 5. 交付物

1. `analysis/target_success_rate_2026_06_11.py` + `analysis/output/target_success/*.csv`
2. `docs/target-success-rate-2026-06-11.md` 完整报告
3. 对用户的中文总结：两个明确的目标成功率建议数字（含数据源配套、对应年消费、不确定性区间）、两策略对照表、LTC ring-fence 等已知 caveat 重申

## 6. 流程

1. 本计划 → Codex 评审（max effort，评实验设计/文献/决策框架）
2. 吸收意见 → 跑实验 A-E
3. 结果 + 我的初步结论 → Codex 第二意见（独立给数字 + 批判我的推理）
4. 分歧消化 → 最终总结
