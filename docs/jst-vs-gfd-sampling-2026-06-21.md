# JST vs GFD 数据 + Block Bootstrap 采样升级 — 结论 (2026-06-21)

起因：把本仓库 JST 多国面板与 **Anarkulova-Cederburg-O'Doherty (ACO) "Beyond the
Status Quo"（数据源 GFD）** 做逐国回报对比时，顺带复核了 ACO 的 block bootstrap 采样
方法，提出三项候选改动（#1 边界 / #2 几何块长 / #3 观测加权），加一项 VR 校准（B）。

**一句话结论：四项调查全部指向"保留现有默认"——现有 `uniform[5,15]` 块长 + 同国
circular wrap + 等权 1/N 池化，原本是"经验未辩护"，现在有 VR / wrap / walk-forward /
三权重 四重实证支撑。产品默认行为零变化；新增的几何块长是 opt-in 研究开关。**

计划与 Codex 收敛见 `docs/plan-2026-06-21-block-bootstrap-sampling-upgrade.md`（14 findings
全部消化，无方向性分歧）。

---

## 0. JST vs GFD 逐国实际回报（`analysis/jst_vs_gfd_returns.py`）

16 个 JST 国家 domestic-stock 年化实际(本币)回报 vs ACO Table II：**13/16 ≤1.0pp、
9/16 ≤0.5pp**（美国对照 +0.22pp）。仅 FRA/JPN/PRT 差 1.4–2.7pp，定位为战争/革命停市期的
**指数重构口径差**（ACO 用黑市价/金马克/占领期成交价显式逐事件重构；JST 是年度官方学术
序列），非数据错误。与已有 JST-vs-MSCI、JST-vs-DMS 验证同一模式（战区股市方法论差异）。

ACO 极端值处理哲学：**重建而非剔除**——停市(35 例,如 1914 NYSE)跨期重建投资者经历、
恶性通胀(德国 1923)按本地 CPI 平减后保留、主权违约(希腊 2012)反映真实结果、平衡面板
(缺失只在序列开头)。德国债券 JST −16.4%/yr vs GFD −1.43%/yr 的巨大差异即源于此：JST
年度口径把 1923 压成单个 ≈−100% 全损步，ACO 月度重建软化成非全损路径。

---

## 1. ACO 采样 vs 本仓库

| 维度 | ACO (GFD) | 本仓库 |
|---|---|---|
| 抽国家概率 | 隐式 ∝ 各国数据月数（country-month 上均匀抽起点） | **等权 1/N**（`resolve_country_weights` 恒 None） |
| 块长分布 | 几何（stationary bootstrap），均值 ≈120 月(10y) | 均匀 `[5,15]`，均值 10y |
| 块内边界 | 跨国从新国开头接续 | 同国 circular wrap（`% n`） |
| 数据频率 | 月度 | 年度 |

注意：均值块长其实**一样**（都 ≈10y）；真正差异在分布形状、边界处理、国家权重。

---

## 2. #1 / 升级 D：block 边界 → 保留同国 circular wrap

**裁决：保留现状 (a)。** Codex Finding 2/3/7 一致确认：

- (a) 同国 circular wrap = 标准 **Circular Block Bootstrap (Politis-Romano 1992)**，
  故意首尾相接以消除块边界 edge bias；2025→1872 接缝是 CBB 既定代价，非 bug。
- (b) 截断会**重新引入** edge bias（CBB 正是为避免它）→ 拒绝。
- (c) ACO 跨国接续 = 双 seam + 强制从新国第一行起（早期数据偏）→ 拒绝（仅 research）。
- **实证支撑**（B2）：默认配置下 wrap-seam 仅占采样行 **3.4%** → 接缝罕见、无法实质
  扭曲结果。
- 唯一改动：`bootstrap.py` docstring 收窄声明——CBB 良性仅对 *return-like* 列成立，
  对 `Long_Rate`/housing **水平**列加 caveat（Finding 2/13）。

---

## 3. #2 / 升级 A：几何块长（opt-in，默认关）

新增 `block_dist={"uniform"|"geometric"}` + `mean_block`，透传 `bootstrap.py` →
`monte_carlo.run_simulation(_vectorized_fixed)`。**默认 uniform 逐位 no-op**（RNG 调用
顺序严格保持，Finding 6；14 个新测试 + 全套 260 通过）。

**主假设（几何块长收窄记录的 −3~−8pp MC 保守偏差）被证伪：**

| 数据源/区间 | uniform[5,15] | geometric(10) | geometric(20) |
|---|---|---|---|
| JST_pool [all] MC 偏差 | −5.4pp | −5.5pp | −5.2pp |
| JST_pool [3-6%] | −3.3pp | −3.5pp | −2.9pp |
| US [all] | −6.0pp | −6.3pp | −5.4pp |
| US [3-6%] | −3.3pp | −3.6pp | −2.5pp |

移动幅度 ≤0.8pp，远在 ±19pp CI 内，Brier 几乎不变。**保守偏差不是块长分布的
artifact**（另有来源：MC vs realized 本质 + 池化 regime 库偏保守）。

合成 VR 对照（B2）进一步显示：三种配置都低估历史长期持续性（hist VR(30)=1.46），
但 **uniform[5,15] 在 k=30 最接近（1.35 vs geom10=1.30/geom20=1.28）**——几何长尾
→ 更多 wrap → seam 打断持续性 → VR(30) 反而更低。

→ **几何块长保留为 opt-in 研究开关，产品默认 uniform[5,15] 不变。**

---

## 4. 升级 B：块长校准（VR + PPW）

`analysis/block_length_vr_calibration.py`（`--with-synthetic` 跑 B2）：

- **VR(k)**：USA 单国实际股票 VR(10)=0.73/VR(20)=0.51（经典均值回归，对标
  Poterba-Summers，验证公式正确）；**池化 60/40 VR(10)=1.47 = 长期持续性**，由
  FRA(2.66)/JPN(2.11)/ESP/PRT 战争+通胀 regime 驱动。
- **PPW(2009) 最优块长 ≈2.1y**（90% 带 [1.7,2.6]）——但它优化的是**样本均值估计的
  MSE**，与我们"复现 ruin 相关长期方差"是不同目标。2y 块会洗掉驱动尾部破产的 10-30y
  持续性 → **不采用 PPW 块长**。
- Codex Finding 4/5 落实：VR 用 60/40 联合过程 + 国家 resample 不确定性带；不靠单一
  点估计反解块长。

---

## 5. #3 / 升级 C：观测加权（research-only）

`config.get_observation_weights`（w_i ∝ 历史长度）+ `analysis/pooling_weight_sensitivity.py`。
三种权重 SWR@90%：等权 3.26% / sqrt-GDP 3.35% / obs 3.28%，**spread 0.09pp = 噪声**。
稳健性声明升级为"**等权 1/N（默认）、sqrt-GDP、obs-weighted 三种方案下结论一致**"。
（obs ≈ 等权，因 JST 16 国大多满长 126-155y，不像 ACO 38 国长度悬殊。）

---

## 6. 工件与版本

- 分支 `feat/block-bootstrap-sampling`；commits：plan → plan收敛 → B1 → A → walk-forward
  参数化 → B2 → C → 本结论。
- 代码：`simulator/bootstrap.py`（几何块长 + docstring）、`simulator/monte_carlo.py`
  （透传）、`simulator/config.py`（obs 权重）、`scripts/analysis/walk_forward_validation.py`
  （`--block-dist` CLI）、`tests/test_block_dist.py`（14 测试）。
- 分析：`analysis/jst_vs_gfd_returns.py`、`analysis/block_length_vr_calibration.py`、
  `analysis/pooling_weight_sensitivity.py`。
- 产品默认行为：**零变化**（260 测试全过，uniform 路径逐位等价）。
