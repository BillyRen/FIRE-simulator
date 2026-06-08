# 规格：Walk-Forward 验证 — 蒙特卡洛 vs 历史回测的预测准确性

**日期**：2026-06-08
**状态**：Codex 评审已纳入（v2）→ 待用户确认 → 实现

## 1. 目标

用滑动窗口（walk-forward / out-of-sample）方法回答：**FIRE 模拟器的两种成功率预测方法（蒙特卡洛 block bootstrap、历史重叠窗口回测）在真实历史中有多准、是否系统性偏乐观或偏保守、谁更可靠。**

核心动作：在每个"决策年" T，**只用 T 之前的数据**算出两种预测成功率，再用 T 之后真实发生的 30 年观察其真实成败，最后用**校准（calibration）框架**对比预测与真实。

## 2. 核心方法论：为什么是校准而非逐窗口对比

单个 30 年退休窗口只产生一个**二元结局**（成功 / 失败 = 1 / 0），不是一个"真实成功率"。而 MC / 历史回测输出的是一个**概率**（如 0.87）。概率无法与单个 0/1 直接比较。

正确做法 = **校准 / 可靠性（reliability）分析**：

1. 跑大量 (数据源 × 决策年 T × 取款率 WR × 国家) 组合，每个产生一对「预测概率, 真实 0/1」。
2. 把样本**按预测概率分箱**。
3. 每箱内：x = 平均预测成功率，y = 真实成功**频率**。
4. 完美预测落在 45° 对角线上。落在**对角线下方** = 该方法**系统性高估**（过度乐观）；上方 = 过度保守。

### 2.1 估计量（estimand）—— 必须先定义清楚（Codex #1, #5）

**主分析估计量 = "从 16 国发达国家面板中等概率随机抽一个国家，其真实 30 年退休结局"。** 为此，三个量必须用**同一套国家权重 = 等权**：

- MC 池化 bootstrap：用**等权**（非产品默认 sqrt-GDP）。
- 历史回测 HB：跨 16 国的完整窗口**等计数**。
- 真实结局：每国一个 0/1，**等权**聚合。

若三者权重不一致（如 MC 用 sqrt-GDP、HB/realized 等权），"MC vs HB 谁更准"会混入"加权方案差异"，结论失真。故统一等权。

> 报告必须在标题/图注明确：这是"面板随机国家"估计量，**不是**"某单一国家投资者视角"的校准。产品默认用 sqrt-GDP 池化（美国权重 ~0.2 偏高）；本研究刻意用等权以让各国（含 DEU/JPN 灾难尾）等量发声。sqrt-GDP 版本列为可选附录。

### 2.2 为什么要扫取款率

若只用单一 4% 取款率，预测成功率会全部挤在高位，校准曲线只剩一个点。**扫一组取款率**让预测成功率铺满 0–100% 全区间。但需注意**结论会依赖 WR 网格**（Codex #7）：故同时报告 (a) 全网格校准、(b) 每个 WR 单独的偏差/Brier、(c) 实用子集 3–6% 的校准。

## 3. 数据源与配置

| # | 数据源 | 配置 | 角色 |
|---|--------|------|------|
| 1 | JST 池化 (`country=ALL`, 16 国, **等权**) | 50% 本国股 + 50% 全球股, 0 债券 | **主分析** |
| 2 | FIRE_dataset (美国, 1871–2025) | **100% 本国股** | 干净单序列旁证（独立报告） |
| 3 | 其他（per-country JST / sqrt-GDP 池化等） | 同上 | **best-effort**，仅运行不慢时附带，慢则跳过 |

- 数据源 2 用 100% 本国股：FIRE_dataset 的 "International Stock" 列 1970 前是占位，100% 本国股回避此问题。
- 数据源 1 用原生 JST `jst_returns.csv`：每国都有真实本国股票序列 1871–2025，无 pre-1970 美股占位污染。

**固定参数（全数据源一致）**：
- 退休年限 `retirement_years = 30`；策略 `fixed`
- **费用率 = 0.005（0.5%，小数制）** —— 直接传 `expense_ratios={asset: 0.005}`，**不要**用 `config.DEFAULT_EXPENSE_RATIOS`（那是 0.50 百分比单位，会被当 50% 扣）（Codex #10）
- block bootstrap `min_block=5, max_block=15`；杠杆 1.0，无现金流
- 初始组合 $1,000,000；年取款额 = `WR × 初始组合`
- 取款率扫描 `WR ∈ {3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 7.0, 8.0}%`（实现后视预测覆盖情况微调）；实用子集 = 3.0–6.0%
- MC 模拟次数 `num_simulations = 8000`，固定 `seed`

## 4. 精确算法

记某数据源年份从 `Y_min` 到 `Y_max`（JST/US 均 1871–2025）。

### 4.1 年份索引约定
"决策年 T 退休、退休 30 年" = 消耗第 T, T+1, …, T+29 年这 30 个年度收益。成功 = 30 年内未在中途破产（末年破产按 Trinity 口径算成功，与 `compute_success_rate` 一致：`statistics.py:83`）。

### 4.2 决策年范围（Codex #3 修正）
- **上界**：需 T 起完整 30 年真实收益 → `T + 29 ≤ Y_max` → `T ≤ 1996`（取 `T ≤ 1995`）。
- **下界**：要求**全部 16 国**在 pre-T 内都有 ≥10 个完整 30 年 in-sample 窗口。最晚起步国 CHE/ESP/NLD 从 1900 起，第 10 个完整窗口（1909–1938）需 `1938 ≤ T-1` → `T ≥ 1939`。
- **主区间 `T ∈ [1939, 1995]`（57 个决策年）**。此区间内 16 国全部同时具备 in-sample 与 realized 数据 → 预测池国家集 == 真实观察国家集（对齐，避免 Codex #3 的集合错配）。
- 可选附录 `T ∈ [1915, 1938]`：明确标注"早期有限历史"，不进主结论。

### 4.3 预测一：蒙特卡洛 `p_MC(source, T, WR)`（Codex #9 提速）
- in-sample = 该源全部 `Year ≤ T-1` 的行（**扩展窗口**）。
- 池化源：`country_dfs` 每国仅留 `Year ≤ T-1`；`country_weights = 等权`（每国 1/N）。
- **每个 (source, T) 只生成一次** bootstrap 实际收益矩阵 `real_returns_matrix`（shape `8000×30`），随后对每个 WR 调 `run_simulation_from_matrix(...)`（或直接向量化 success）复用同一矩阵 → 省时且 WR 间用 common random numbers（成功率随 WR 单调）。
- 每个 WR：`p_MC = compute_success_rate(trajectories, 30)`。
- 仅用 pre-T 数据 → 无 lookahead。

### 4.4 预测二：历史重叠窗口回测 `p_HB(source, T, WR)`（Codex #4 修正 + 国家等权对齐）
- **专门构造**所有起始年 `s` 满足 `s + 29 ≤ T-1` 的**完整 30 年**真实路径，**按国家分组**。
- **不复用** `run_sim_batch_backtest()` 的聚合（它含 ≥10 年的不完整路径，会压低 HB）。直接用 `batch_backtest_fixed_vectorized()` 对各国窗口矩阵打分。
- 每个 WR：`p_HB = 各国窗口成功率的跨国等权均值`（**国家等权**，与 §2.1 估计量一致；口径同 `compute_success_rate`）。同时记录窗口等权版本 `p_hb_windoweq` 作敏感性对照。

### 4.5 真实结局 `realized(source, T, WR, country)`
- 对每个国家 c（主区间内全 16 国均满足），取真实收益 `T..T+29`，跑 `fixed` 单路径 → 0/1。用 `batch_backtest_fixed_vectorized()` 批量。
- 池化源：每个 (T, WR) 产生 16 个真实样本（每国一个），共享同一对 `p_MC, p_HB`。US 源：1 个。
- 真实分布含 DEU 1920s、JPN 1940s 等灾难尾 —— 池也从中采样，对池化前提是公平检验。

### 4.6 样本表（脚本主输出 `docs/data/walk_forward_samples.csv`）
每行一个真实样本：`source, decision_year, withdrawal_rate, country, p_mc, p_hb, realized, n_insample_hb_windows, n_insample_years`
主区间池化样本量 ≈ 57 (T) × 9 (WR) × 16 (country) ≈ 8200 行。

## 5. 输出

### 5.1 View A — 校准图（核心）
- x = 预测成功率，y = 真实频率；两条折线 MC / HB + 45° 对角线。
- **分箱稳健性**（Codex #6）：主图用固定 0.1 等宽箱（可解释）；附等计数分箱（equal-count）作稳健性对照；每箱标注样本数。稀疏箱（n<30）标灰。
- 每方法量化指标：
  - **Brier score** = mean((p − realized)²)
  - **ECE** = Σ (箱样本占比 × |箱平均预测 − 箱真实频率|)
  - **平均偏差** = mean(p) − mean(realized)，pp（正 = 系统性高估）
  - 同时给**全网格**、**每个 WR**、**实用子集 3–6%** 三套（Codex #7）。
- **置信区间（Codex #2）**：
  - 用 **moving-block bootstrap，重抽样单位 = 连续决策年块**（block 长度默认 ~20，作敏感性试 10/30），块内保留该年全部国家/WR 行 → 同时捕获"同 T 共享预测 + 同 T 跨国相关 + 相邻 T 的 29/30 年重叠"。
  - **重点报告 MC−HB 配对差异**（Brier 差、偏差差）的 95% CI —— 两方法见几乎相同真实结局，差异比绝对水平稳健得多，是最可信的头条结论。
  - 明示**有效独立样本极小**（57 年里只有 ~2 个独立 30 年期）→ 绝对水平 CI 会很宽，这是历史数据的根本限制，不是 bug。

### 5.2 View B — 时间序列
- x = 决策年 T；WR = 4% 与 6% 各一图。
- 三条线：真实频率（该 T 跨 16 国 0/1 均值，含噪）、`p_MC(T)`、`p_HB(T)`。
- 展示预测如何随历史窗口扩展漂移、何时偏离真实。

### 5.3 报告 `docs/walk-forward-mc-vs-backtest.md`
含方法、两视图图表、量化指标表（带配对差异 CI）、按数据源对比、明确 caveat、结论（谁更准/是否乐观/幅度，按 §5.1 的措辞限定到本估计量/WR 网格/决策年范围）。

## 6. Caveat（写进报告）
1. **窗口重叠 → 非独立 + 有效样本极小**：57 决策年里仅 ~2 个独立 30 年期；用 moving-block CI 反映，绝对水平 CI 宽，配对差异更可信。
2. **估计量是"面板随机国家"，非"单国投资者"**（§2.1）；等权 ≠ 产品 sqrt-GDP 默认。
3. **幸存者偏差**：JST 16 国都活到今天；预测与真实共享此偏差 → 内部一致，但绝对"真相"仍偏乐观。
4. **扩展窗口早期更噪**：1939 下界下最短 pre-T 历史 = 39 年（CHE/ESP/NLD）；circular block bootstrap 会把短历史绕接成 30 年路径（非 lookahead，但弱估计器，Codex #8）→ 区分早/晚期。
5. **结论依赖 WR 网格**：故同时给全网格 + per-WR + 3–6% 实用子集。
6. **WR 不是连续真实策略**：扫 WR 是为铺满预测区间，非主张某人用 8% 取款率。

## 7. 实现产物
- `scripts/analysis/walk_forward_validation.py`：离线脚本（**不进产品/后端**）。`__main__` 守卫防 multiprocessing spawn 递归。复用 `run_simulation` / `run_simulation_from_matrix`、`batch_backtest_fixed_vectorized`、`compute_success_rate`、`data_loader`、不复用 `run_sim_batch_backtest` 聚合。
- 输出：`docs/data/walk_forward_samples.csv`、校准/时间序列聚合 CSV、图表（matplotlib PNG 或 Plotly HTML）、报告 md。
- 运行预算：池化 MC ≈ 57 (T) × 1 矩阵生成（8000-sim）≈ 数十秒～数分钟；WR 复用矩阵后近乎免费。超时则降 sim 或减 WR。

## 8. 范围外（v1 不做）
- guardrail / 动态策略 walk-forward。
- "全样本 MC"（lookahead 参考线）。
- 把校准结果反向接入产品 UI。
