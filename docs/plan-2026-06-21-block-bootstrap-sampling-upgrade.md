# Plan: Block Bootstrap 采样升级 — 2026-06-21

> 本计划覆盖三项候选改动（用户 #1/#2/#3）：
> - **#1 = 升级 D**：block 跨国/跨代边界处理（同国 circular wrap vs 截断 vs ACO 跨国接续）—— **开放问题，交 Codex 裁决**。
> - **#2 = 升级 A**：几何分布块长（stationary bootstrap），feature-flag，默认关。
> - **#3 = 升级 C**：observation-weighted 国家权重（研究对照维度）。
> - 另含 **升级 B**：variance ratio 块长校准（纯分析脚本，为 #2 提供数据驱动的 mean_block）。

## 标题（原）：几何块长 + VR 校准 + 观测加权对照

## 0. 背景与动机

起因：将本仓库的 JST 多国面板与 **Anarkulova-Cederburg-O'Doherty (ACO) "Beyond the Status Quo"（SSRN 4590406, 2025，数据源 GFD，1890–2023，39 国）** 做逐国年化实际回报对比（脚本 `analysis/jst_vs_gfd_returns.py`，输出 `analysis/output/jst_vs_gfd_returns.csv`）。

结论：16 个 JST 国家中 **13/16 ≤1.0pp、9/16 ≤0.5pp**（美国对照 +0.22pp），水平高度可比；仅 FRA/JPN/PRT 差 1.4–2.7pp，已定位为战争/革命停市期的**指数重构口径差**（ACO 用黑市价/金马克/占领期成交价显式逐事件重构，见其 Internet Appendix §A.2.1 与 Table A.III；JST 是年度官方学术序列），非数据错误。

在比对回报水平的同时，复核了 ACO 的**采样方法**（其正文 Section 4.4），发现其 block bootstrap 设计与本仓库 `simulator/bootstrap.py` 有几处差异，其中一处可能改善本仓库一个**已被实证记录的缺陷**。

### 本仓库已知的相关实证（不要推翻）

- `docs/walk-forward-mc-vs-backtest.md`：out-of-sample 滑窗校准显示，本仓库的 MC（block bootstrap）成功率预测**系统性偏保守 −3~−8pp**（从不在灾难前高估，这是优点；但绝对水平略悲观）。结论在 **block 长度 10/20/30 下定性稳健**。
- 因此本升级的**默认行为不得改变**、方向性结论不得推翻；目标是新增可选机制并量化其对该保守偏差的影响。

## 1. 现状 vs ACO 采样方法

| 维度 | ACO (GFD) | 本仓库 `bootstrap.py` |
|---|---|---|
| 抽国家概率 | 隐式 ∝ 各国数据月数（在全样本 country-month 上等概率抽**起点**） | 产品已统一为**等权 1/N**（`backend/deps.py:293-299` `resolve_country_weights` 恒返回 `None`）；sqrt(GDP) 加权已降级为 research-only（`simulator/config.py:80-83`） |
| 何时换国 | 仅当 block 撞到某国样本末尾才续抽另一国 | **每个 block 都重新抽国** |
| 块长分布 | **几何分布**（stationary bootstrap, Politis-Romano 1994），均值 120 月（≈10 年），**无上界** | **均匀分布** `randint[min_block, max_block]`，默认 [5,15]，**硬上界 15** |
| 块内边界 | 跨国从新国开头接续 | circular wrap（`% n`，**同国**绕回开头） |
| 数据频率 | 月度 | 年度 |

关键代码位置：
- `simulator/bootstrap.py`：`_block_bootstrap_core`（单国，约 30–48 行）、`_block_bootstrap_pooled_core`（多国，约 172–201 行）；块长公式 `block_size = min(rng.integers(min_block, max_block + 1), retirement_years - pos)`；circular wrap `indices = np.arange(start, start + block_size) % n`。
- `simulator/config.py`：`DEFAULT_MIN_BLOCK = 5`、`DEFAULT_MAX_BLOCK = 15`。
- 参数流：`backend/schemas.py`（3 处 `min_block`/`max_block` Field：约 54–55、625–626、689–690 行，及约 84–86 行 validator）→ `backend/routes/{simulate,guardrail,sensitivity,buy_vs_rent,accumulation}.py` → `simulator/{monte_carlo,sweep,buy_vs_rent,accumulation}.py` 的 `min_block/max_block` 形参。

## 2. 目标与非目标

**目标**
1. 在 `bootstrap.py` 引入**可选的几何分布块长**（stationary bootstrap），默认关闭。
2. 用 JST 历史的 **variance ratio (VR)** 数据驱动地校准/验证块长，把当前的经验值 [5,15] 升级为可辩护的选择。
3. 把 **observation-weighted 国家权重**作为第三个研究用对照维度（与现有 1/N、sqrt-GDP 并列）。
4. 量化几何块长能否收窄 walk-forward 记录的 **−3~−8pp 保守偏差**。

**非目标（明确跳过）**
- 不改产品默认采样行为（默认仍 uniform [5,15] + 现有权重方案）。
- 不做月度化（JST 是年度源，转月需插值引噪，对 30–60 年 FIRE 边际价值低）。
- ~~不采用 ACO 的"跨国 block 接续"~~ —— **此项从非目标移出，改列为开放问题（见升级 D / §3.D），交 Codex 裁决**。原论据（同国 circular wrap 语义更干净）仍是当前倾向，但需对抗"2025→1872 跨代 artifact"顾虑后再定。
- 不改产品默认国家权重（当前=等权 1/N）；observation-weighted 与 sqrt-GDP 一样，仅作 research 对照。

## 3. 升级项

### 升级 A：几何分布块长（核心，feature-flagged）

设计：新增采样参数（建议 `block_dist: "uniform" | "geometric" = "uniform"` 与 `mean_block: int | None = None`）。
- `uniform`（默认）：保持现有 `randint[min_block, max_block]`，零行为变化。
- `geometric`：块长 `L ~ Geometric(p)`，`p = 1/mean_block`，用 `rng.geometric(p)` 抽取（返回 ≥1，均值 1/p，无 off-by-one — Codex Finding 8），再 `block_size = min(L, retirement_years - pos)` 截断。
- circular wrap 不变；当 `L > n`（单国数据长度）时 `% n` 自动多圈环绕（需在测试中覆盖）。

**Codex review 落实**：
- **Finding 6（RNG 调用顺序，关键）**：单国路径抽样顺序 = 先块长后起点；池化 = 先国家后块长后起点。重构**必须逐位保持 uniform 路径的 RNG 调用顺序**，否则同 seed 数值漂移。新增 **bitwise-exact 回归测试覆盖全部路径**（单国 / 池化等权 / 串行 / 并行）作为合并前置条件。
- **Finding 8（support 语义变化）**：geometric 只保留**均值**，不保留 `[min_block,max_block]` 区间——会有大量块短于 min、长于 max。文档/UI 明示；几何模式下 UI 的 min/max 输入应置灰/失效。
- **Finding 9（mean_block > n 守卫）**：若 `mean_block` 超过某国过滤后的 obs 数 n，单块会在一条路径内重复同国数据。`_validate_bootstrap_args` 增加告警/上限。
- **Finding 10（默认值定性）**：`mean_block` 缺省 = `(min_block+max_block)/2`（=10）仅为**兼容初值**（保均值），非统计最优；真正的辩护来自升级 B 的 VR/PPW，不靠"保均值"。

实现位置：仅 `_block_bootstrap_core` 与 `_block_bootstrap_pooled_core` 的块长抽样一处；`_validate_bootstrap_args` 增加 `block_dist`/`mean_block` 校验。

参数流（向后兼容，全部带默认值，旧调用不受影响）：
- `simulator/bootstrap.py` 各公共函数签名追加可选参数。
- `simulator/{monte_carlo,sweep,buy_vs_rent,accumulation}.py` 透传。
- `backend/schemas.py` 3 处 + validator；`backend/routes/*` 透传。
- `frontend`（`src/lib/types.ts`、`api.ts`、`sidebar-form.tsx`）：作为高级选项暴露，**默认 uniform**，避免改变现有用户的持久化参数语义。

### 升级 B：variance ratio 块长校准（研究脚本）

- 新增 `analysis/block_length_vr_calibration.py`：计算历史 **VR(k)（k=1,5,10,15,20,30）**，再对若干 `mean_block` 跑 bootstrap、计算合成序列 VR、对比历史 VR。
- **Codex Finding 4**：block 是**联合**抽取 stock/global/bond/inflation 的——VR 校准目标必须用**组合收益 + 通胀的联合过程**（例如代表性 60/40 组合的实际收益），单看 `Domestic_Stock` VR 会牺牲组合协方差/通胀行为。per-asset VR 仅作 diagnostics 输出。
- **Codex Finding 5**：年度序列每国仅 ~126–155 obs，VR(10/20/30) 点估计噪声大 → 不可用单一点估计反解唯一 `mean_block`（会过拟合噪声）。改为：① VR 带 **bootstrap 不确定性带**输出；② 用 **Patton-Politis-White (2009) 自动块长 plug-in** 交叉验证；③ VR **不作为唯一**校准目标，只作为"现 [5,15] 是否落在合理区间"的辩护证据。
- 产出：VR + PPW 自动块长 + 不确定性带，写入 `docs/`，**不改产品默认**。default `mean_block` 仍取兼容初值（见升级 A Finding 10）。

### 升级 C：observation-weighted 国家权重（研究对照）

- 在 `_prepare_pooled_arrays` 的 `country_weights` 体系内增加一种权重构造：`w_i ∝ n_i`（各国可用年数），作为研究对照维度。
- 仅 analysis/research 使用；**产品默认是等权 1/N**（不是 sqrt-GDP）。
- 用途：把稳健性声明做成"等权 1/N（产品默认）、sqrt-GDP、observation-weighted 三种合理权重方案下结论一致"的对照，而非"在产品默认旁加第三种选项"。

### 升级 D（#1）：block 边界处理 —— 开放问题，交 Codex 裁决

**背景**：当 block 长度超出某国数据末尾时，当前 `_block_bootstrap_core` / `_block_bootstrap_pooled_core` 用 `indices = np.arange(start, start+block_size) % n` 做**同国 circular wrap**（如 USA 2025 → 1872）。

**三种候选方案**：

| 方案 | seam 类型 | 理论依据 / 顾虑 |
|---|---|---|
| (a) 现状：同国 circular wrap | 同国跨代（2025→1872） | ✅ 这正是 **Circular Block Bootstrap (Politis-Romano 1992)**：故意首尾相接以**消除块边界处的边界偏差(edge bias)**。对近似平稳的*收益*序列（非价格），wrap seam 与任意块边界等价，理论上良性。 |
| (b) 截断 + 起新块 | 国界处块变短，下一块换国/换起点 | ⚠️ 去掉 wrap → **重新引入 edge bias**（首尾行被采样不足）；CBB 设计初衷正是为避免这点。优点是无跨代 artifact。 |
| (c) ACO 跨国接续 | 同时跨国+跨代（双 seam，且续接固定从新国开头 Rj,1） | ⚠️ 双 seam + 强制从新国第一行起 → 对新国早期数据有偏；池化下每个块边界本就跨国，额外接续价值存疑。 |

**裁决（Codex review 2026-06-21，Finding 2/3/7）：保留 (a)，不改代码。**
- (a) 是有文献支撑的 Circular Block Bootstrap (Politis-Romano 1992) 标准做法，2025→1872 seam 是 CBB 既定的人造接缝，非 bug。
- (b) 截断会**重新引入 edge bias**（CBB 设计初衷正是消除它）—— Codex 确认 plan 拒绝截断是对的（Finding 7）。
- (c) ACO 跨国接续=双 seam + 强制从新国第一行起→对早期数据有偏，产品路径拒绝，仅 research（Finding 3）。
- **唯一需改的是文档**（Finding 2/13）：现 docstring 的"stationary→benign"论证太宽——`Inflation`（通胀率，近似平稳，OK）尚可，但 `Long_Rate`（长债收益率**水平**）和 housing 列是**水平量、非平稳**，wrap seam 对它们不良性。需在 `bootstrap.py` docstring 收窄声明：CBB 的良性仅对 return-like 列成立，对 rate/housing 水平列加 caveat；"stationary" 措辞改为"几何块长赋予 bootstrap 过程 stationary Markov renewal 性质"，不与底层序列平稳性混为一谈。

## 4. 验证方案

1. **回归等价性**：`tests/test_vectorization_equivalence.py`、`tests/test_bootstrap_parallelization.py` 必须全绿（几何默认关闭 ⇒ 现有数值不变）。
2. **新增单测**：
   - 几何块长样本的均值/方差符合理论（`E[L]=1/p`，容差内）。
   - `block_dist="uniform"` 与改造前逐位等价（同 seed）。
   - circular wrap 在 `L > n` 时索引正确、无越界。
3. **walk-forward 复跑**（复用 `scripts/analysis/walk_forward_validation.py`）：对照 `uniform[5,15]` vs `geometric(mean=10)` vs `geometric(mean=20)`，看 −3~−8pp 保守偏差是否收窄；这是本升级唯一可证伪的主假设。
4. **数值纪律**：seed ∈ {42, 60042, 120042} 三 seed 复核，间隔 > N，规避 bootstrap seed 重叠陷阱。

## 5. 风险与 caveat

- 几何分布长尾会抽到 `L > n` 的超长块 → 同国多圈 wrap，**跨代 seam 增多**；需在 walk-forward/VR 校准中确认未引入伪人造依赖。
- 单位陷阱：ACO 120 **月**，本仓库 `mean_block` 是**年**，校准与文档需显式标注单位。
- 性能：`rng.geometric` 在循环中调用；若热点退化，改为按 block 数批量预抽。需保证 sweep/guardrail 大批量路径不显著变慢。
- 前端持久化：新参数若默认值与历史 localStorage 缺省不一致会改变老用户结果——必须确保缺省=uniform 等价。

## 6. 工件

- 本 plan：`docs/plan-2026-06-21-block-bootstrap-sampling-upgrade.md`
- 已有：`analysis/jst_vs_gfd_returns.py`、`analysis/output/jst_vs_gfd_returns.csv`
- 新增：`analysis/block_length_vr_calibration.py`、几何块长改动（`bootstrap.py` 等）、新单测
- 结论文档：`docs/jst-vs-gfd-sampling-2026-06-21.md`（对比 + VR 校准 + walk-forward 结果）

## 7. 实施顺序

1. 升级 B（VR 校准脚本，纯分析，零产品风险）→ 得到推荐 `mean_block`；顺带产出 wrap-seam 占比与 (a) 合成 VR 对照（喂给升级 D 决策）。
2. 升级 A（几何块长，feature-flag，默认关）+ 单测 + 回归。
3. walk-forward 复跑量化保守偏差变化（验证主假设）。
4. 升级 D（#1 边界）裁决：基于 B/A/walk-forward 的实测指标 + Codex 意见定夺 (a)/(b)/(c)；默认改动需用户确认。
5. 升级 C（obs-weighted 对照）+ 汇总结论文档。
6. 仅当 walk-forward 显示几何块长**明确改善校准且不破坏方向性结论**时，才讨论是否调整产品默认；否则保留为可选研究开关。

## 8. 版本记录 / 工作流

- 分支：`feat/block-bootstrap-sampling`（核心引擎 + RNG 语义改动，走 feature branch，`--no-ff` 合并）。
- 每阶段（B → A → D 裁决 → C → 结论）独立 commit；commit message 前缀 `feat:`/`test:`/`docs:`/`analysis:`。
- 关键节点跑 Codex：plan review（本计划）→ 升级 A 实现完成后 review（RNG 语义）→ 合并前 branch review。
- 严格 `git add <显式路径>`，避免扫入并发 worktree 的改动；commit 前 `git diff --cached --stat` 核对。

## 9. Codex plan review 收敛（2026-06-21）

14 findings 全部消化。**无方向性分歧**——Codex 确认计划的所有 lean 正确，仅补充细化。逐条处理：

| # | 级别 | 处理 |
|---|---|---|
| 1 | HIGH | 现状权重描述写错（产品=等权 1/N，非 sqrt-GDP）→ §1/§2/§3.C **已修正** |
| 2 | HIGH | circular wrap 确是 CBB，保留 (a)；docstring "benign" 声明收窄到 return-like 列，rate/housing 水平列加 caveat → §3.D |
| 3 | HIGH | (c) ACO 接续拒绝，仅 research → §3.D |
| 4 | HIGH | VR 校准用组合+通胀联合过程，非单一 stock → §3.B |
| 5 | HIGH | 年度 VR 噪声大，不可点估计反解单一 mean_block；加不确定性带 + PPW 自动块长交叉验证 → §3.B |
| 6 | HIGH | 保 uniform 路径 RNG 调用顺序，bitwise 回归测试覆盖全路径 → §3.A、§4 |
| 7 | MED | 截断 (b) 拒绝正确，无需改动 → §3.D |
| 8 | MED | geometric 只保均值不保 support，文档/UI 明示，min/max 置灰 → §3.A |
| 9 | MED | mean_block>n 守卫 → §3.A |
| 10 | MED | midpoint 默认仅兼容初值，非统计最优 → §3.A |
| 11 | MED | localStorage 浅合并能给新顶层字段默认值，但需审计每个 request builder + 页面级持久化控件 → §4 新增前端审计项 |
| 12 | MED | geometric 不解决 seed-overlap；验证脚本保持分隔 seed 集（间隔 > N）→ §4 |
| 13 | LOW | "stationary" 措辞改为 "stationary Markov renewal property" → §3.D docstring |

**收敛后实施范围**：#1=零代码（仅 docstring 收窄）；#2=geometric feature-flag（默认关，重 RNG 纪律）；B=VR+PPW 诊断脚本；#3=obs-weighted research-only。**产品默认行为零变化**。

**新增前端审计项（Finding 11）**：实现 #2 前端时，逐一核对所有 request builder（simulate/guardrail/sensitivity/buy-vs-rent/accumulation）与页面级 persisted 控件，确保新 `block_dist`/`mean_block` 字段缺省 = uniform 等价、不污染老用户 localStorage。
