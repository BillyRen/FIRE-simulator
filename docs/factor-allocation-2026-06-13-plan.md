# 因子倾斜最优配置分析 — Plan (2026-06-13)

> 状态：待 Codex 评审。评审通过后实现 `analysis/factor_allocation_cew.py`，结论写入 `docs/factor-allocation-2026-06-13.md`。

## 用户问题

1. 在 `FIRE_dataset_intl` 的三个金融资产之外，加入**美国小盘价值**（及可选**动量**），最优长周期配置是什么？
2. 加入资产 4-5 对 FIRE 计划**成功率/安全提款率的净贡献**有多大？
3. 资产 4-5 的成本应高于 1-3——用差异化费率公平评估，看溢价被成本吞掉多少。

## 资产与数据

| # | 资产 | 列来源 | 费率 |
|---|---|---|---|
| 1 | US Stock | `FIRE_dataset_intl` `US Stock` | 0.5% |
| 2 | Intl Stock | `FIRE_dataset_intl` `International Stock` | 0.5% |
| 3 | US Bond | `FIRE_dataset_intl` `US Bond` | 0.5% |
| 4 | US Small Value | `data/factors/monthly/us_size_value_2x3.csv` → `SMALL HiBM`（2×3，NYSE 中位数以下宽基小盘×深价值，≈AVUV/DFSV/IWN，**非** Lo10 微盘）| **0.8%**（+0.3%）|
| 5 | US Momentum | `data/factors/monthly/us_size_momentum_2x3.csv` → `BIG HiPRIOR`（大盘赢家，≈MTUM，最可投资的长多动量代理）| **1.0%**（+0.5%）|

- 因子数据用 `annual_nominal/`（月度复合年度，名义，含股息），与 `FIRE_dataset_intl` 名义口径一致。
- 合并：按 `Year` 内连接 + `dropna` + 断言无年份缺口（镜像 `optimal_allocation_cew_us_multi.py:load_panel`）。
- **窗口 = 1927–2025（99 年）**，受因子数据起点限制（无法用既往 US 研究的 1900 起点）。
- 去通胀统一用 `FIRE_dataset_intl` `US Inflation`（Shiller CPI），产品口径 `(1+nom)/(1+infl)-1`。
- 纯 add，不替换 1-3。SV 与 US Stock 概念重叠（同为美股子风格），由优化器决定倾斜程度。

## 引擎（复用产品 + 镜像现有 CEW 脚本）

- `simulator.bootstrap.block_bootstrap_np` 单国 moving-block（block 5–15）在合并的 `[5 assets + Inflation]` 矩阵上**共享 block 索引** → 保留同年跨资产相关性。
- 情景构造（比房产简单，**无 idiosyncratic 噪声**）：
  `nom_port = nominal_assets @ w − (w @ EXPENSE_VEC)`；`real = (1+nom_port)/(1+infl) − 1`。
- 复用 `optimal_allocation_cew.py` 常量与 helper：`INITIAL_PORTFOLIO / NUM_SIMS / RETIREMENT_YEARS / MIN_BLOCK / MAX_BLOCK / SEED / CONSUMPTION_FLOOR / GR_UPPER / GR_ADJ / GR_MODE / GR_MIN_REMAIN / SR_FLOOR / SEVERE_FAIL_MAX / CEW_NEAR_OPTIMAL`、`compute_cew / per_path_funded_ratio / consumption_ulcer`，及 `multi_asset_allocation.compositions`。
- **横盘期限**：导入基础 CEW 脚本的 `RETIREMENT_YEARS`（实现时确认 50y/65y），并补跑 65y（你的目标期限）。

## 两条策略（你选的"双管齐下"）

### A. 护栏（主目标 = 选最优配置）
- target=0.85 / lower=0.75 / upper=`GR_UPPER` / adj=`GR_ADJ` / amount floor / mr=`GR_MIN_REMAIN`（与现有 CEW_US_multi 完全一致）。
- 目标函数：**max median CEW**（CRRA γ=2，δ=0.02）s.t. `success_rate ≥ 0.90` 且 `P(path FR<0.5) ≤ 0.01`；tie-break = 消费路径 Ulcer Index；plateau 用 `CEW_NEAR_OPTIMAL`。
- 同时记录 `init_swr / realized success / severe_fail / p10_cew / eff_FR / p10_min_wd`。

### B. 固定取款（直接回答"成功率贡献"）
- 复用 `guardrail.run_fixed_baseline`（向量化定额取款）在同一 real_returns 矩阵上：
  - ① **SWR@90%**：扫提款率求各 universe 最优配置下满足 90% success 的最大实际提款率（`compute_success_rate` 口径：末年耗尽=成功）。
  - ② **固定 WR 下成功率**：在 3.5% / 4.0% / 4.5% 三档固定提款率，报告各 universe 最优配置的 success_rate。
- composite(eff_FR + init_SWR + P10_min_wd) 排名作交叉验证（你既有 fixed 口径）。

## Universe 对照（回答 Q2/Q3 的核心）

四个 universe 是同一张网格的精确切片（共享 bootstrap，配对比较）：
- `base`：SV=Mom=0（仅 US/Intl/Bond）
- `+SV`：Mom=0
- `+Mom`：SV=0
- `+SV+Mom`：全 5 资产

对每个 universe 取最优配置，逐级报告 **ΔCEW / ΔSWR@90% / Δsuccess@4% / Δsevere_fail**。

### 成本影响隔离（Q3）
每个 universe 同时跑两版：
- **净成本版**：上表差异化费率（0.5/0.5/0.5/0.8/1.0%）
- **gross 版**：全部 0.5%（即 4-5 不加增量成本）

→ `gross 溢价 − 净溢价 = 成本吞掉的部分`，直接量化"溢价是否扛得住成本"。

## 网格与稳健性

- 5 资产 simplex step 10%（C(14,4)=1001 点），最优点附近 5% 细化。
- Phase 1：1001×{1927, 1970}，N=NUM_SIMS，seed=SEED，每窗口共享一次 bootstrap。
- Phase 2：1927 多 seed 确认，seeds=[SEED, SEED+5000, +10000, +15000, +20000]（间隔 ≥ NUM_SIMS，避开 [[seed 重叠陷阱]]）；robust = 全 seed 满足约束。
- Phase 3：高 N（10000，seed 远离）在 1927（主）+ 1970（regime 对照）确认 robust 决赛配置。
- 1970 起点为 regime 情景（非基线），呼应既往"1970 起点会翻转结论"的发现。

## 输出
- `analysis/factor_allocation_cew.py`
- `analysis/output/factor_allocation/{results,multiseed,confirm10k,fixed_swr}.csv`
- `docs/factor-allocation-2026-06-13.md`（主结论：最优配置 + Q2/Q3 答案 + 成本敏感性）

## 已知风险/检查点
1. **SV 与 US Stock 共线性**：优化器可能把 US Stock 权重全转给 SV（同为美股、SV CAGR 更高）→ 结论可能是"用 SV 替代 US 大盘"。如实呈现，定性为"长多/无杠杆菜单下获得 SV/Mom sleeve 的价值"，非纯增量叠加。
2. **窗口 1927 vs 既往 1900**：起点变化对 US 最优配置敏感（既往发现），结论须标注"仅 1927+ 窗口"，不能外推到 1900。
3. **动量长多腿的真实价值**：`BIG HiPRIOR` 长多动量扣 1.0% 后大概率贡献甚微（动量溢价多在多空/短腿）——这正是要量化的，预期它是"鸡肋"。
4. **成本基准 0.5% 对所有资产**：会在 universe 间大部分抵消（仅因子权重差异处不抵消），net 比较实质是增量 0.3/0.5%——须说明。
5. **gross-vs-net 配对**：必须共享同一 bootstrap draw，否则差异混入 MC 噪声。
6. **固定取款 depletion 口径**：复用 `run_fixed_baseline` 确保与 `compute_success_rate`（末年耗尽=成功）一致，避免 off-by-one。

## Codex 评审 round 1（2026-06-13）— 全部采纳

Codex 6 条核心 SOUND（bootstrap 相关性、成本模型、共线性表述、动量代理、固定取款一致性、seed 间隔）。3 条 caveat + 1 个实现 gotcha 已采纳，落实为：

- **[实现] 日历年对齐诊断**：脚本启动打印 `corr(FF 重构市场, FIRE US Stock)`（早先验证=0.9988@1927-2025）并断言 ≥0.99 —— 因子序列同源 FF 月度框架（Jan-Dec 复合），FF 市场与 FIRE 对齐 ⇒ 因子传递性对齐。错位一年相关性会崩，故此诊断即对齐证明。
- **[实现] SWR 扫描耗尽口径**：用 `compute_success_rate`（末年耗尽=成功）判定，**不**用 `build_success_rate_table` 的 `values>0`（更严格）。核对 `run_fixed_baseline` 实际口径。
- **[实现] 因子 sleeve 上限**：除无约束最优外，增报**现实约束版**（SV≤40% / Mom≤20% / 因子合计≤50%）；无约束最优若落在 sleeve 角点须显式标注。
- **[报告] 小样本框架**：~99 个年度观测 → 多 seed/高 N 只降 MC 噪声不降样本不确定性；最优配置须配宽 CI 警示 + 1927/1970 窗口敏感性对照。
- **[报告] 动量摩擦**：`BIG HiPRIOR` ≠ 经典多空动量；税务低效 + 年内换手成本超出建模的年度费率，须额外提示。
- **[报告] FF 数据**：CRSP 基础含退市收益，无生存者偏差（正面注明）。
