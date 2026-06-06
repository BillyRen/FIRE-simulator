# FIRE Simulator 竞品对标升级路线图

**日期**: 2026-06-06
**状态**: 已批准，执行中
**作者**: Claude (Opus 4.8) + Billy

## 背景

基于对 9+ 成熟竞品（cFIREsim、FIRECalc、FI Calc、Portfolio Visualizer、Boldin、
ProjectionLab、Empower、Income Lab、Rich-Broke-or-Dead）的功能调研，结合本项目
现状（Block Bootstrap 多国池化 + 风险护栏方法论已领先简化 MC 竞品，杠杆/护栏为独有卖点），
制定本轮升级路线图。

### 现状优势（护城河）
- Block Bootstrap 多国池化采样（16 国 sqrt(GDP) 加权）—— 比 cFIREsim/FIRECalc 的
  "均值/标准差套整组合" 简化 MC 更先进
- 风险护栏（Risk-Based Guardrail）—— 唯一免费开源的 probability-of-success 护栏工具
- 杠杆 + IBKR 借贷利差建模 —— 竞品几乎都没有

### 数据现状约束（影响可行性的硬事实）
- ❌ 无 CAPE/Shiller 估值数据：`FIRE_dataset.csv` 仅 US Stock/Intl/Bond/Inflation，
  JST 无估值列 → CAPE 策略需额外引入 Shiller 数据（公开，需正规 import 脚本）
- ❌ 无死亡率/生命表 → Rich-Broke-Dead 需嵌入静态 SSA 精算表
- ⚠️ JST 仅 16 个发达经济体，**不含中国（CHN）** → 多币种 CNY 购买力错配
  在当前数据下无历史中国通胀/汇率支撑，**本轮搁置**

## 路线图（4 波次，按风险/ROI 排序）

### Wave 1 — 纯前端增量（零引擎风险，直接 commit 到 main）
1. **URL 分享/保存计算** — 参数编码进 URL，一键分享/复现。来源：FI Calc。
   传播 ROI 最高。复用 `params-context` 状态，加 URL 序列化/反序列化。
2. **CSV 导出** — 轨迹 + 期末值折回首年美元。来源：FI Calc。量化用户刚需。
3. **命名支出预设** — 把已有 declining/smile 引擎包装成 Bernicke / Retirement-Stages
   等命名下拉。来源：FIRECalc/Bogleheads。纯前端。

### Wave 2 — 可视化（需嵌入小静态表）
4. **Rich-Broke-Dead 死亡率可视化** — 内置 SSA 生命表，三态叠加
   （钱花不完 / 花光 / 人没了）。来源：engaging-data。同栈 Plotly，社群传播性强。

### Wave 3 — 引擎改动（feature branch + Codex review + 数值等价测试）
5. **护栏不对称调整 + 历史压力叙事** — 上护栏 100% 回目标 / 下护栏只回 X%
   （Income Lab 招牌）+ "2008 只需减收 X%、1970s 减收 Y%" 具体历史数字。
   对标付费竞品 Income Lab 的免费替代定位。
6. **更多取款策略 + 意图分类** — 新增 VPW、Endowment/95%-rule，按"恒定 / 最大化长寿"
   意图归类。来源：FI Calc。
7. **NRA 股息预提税参数** — `global_stock` 实际收益按预提税率打折。国际/IBKR 定位
   低成本赢点。

### Wave 4 — B 级（依赖外部数据引入）
8. **CAPE 估值驱动取款** — 先写 Shiller CAPE import 脚本 → 再加引擎策略。
   最大、最后做。来源：FI Calc。

### 本轮搁置
- **多币种 CNY 购买力错配** — 数据不足（中国不在 JST 面板）。等未来引入中国通胀/汇率
  序列再说。

## 执行机制
- Wave 1-2 低风险 → 直接 commit 到 main
- Wave 3-4 引擎改动 → feature branch，每特性 implement → Codex review
  （`~/.local/bin/codex-review`）→ 数值等价测试（`test_perf_equivalence.py` /
  `test_vectorization_equivalence.py` 模式）→ 确认无回归再 `--no-ff` merge
- 每个 Wave 完成后向用户汇报里程碑
- 回滚策略：每特性独立 commit/分支，可单独 revert

## 验证标准
- 前端改动：`(cd frontend && npx next build)` + `(cd frontend && npx eslint src/)`
- 后端改动：`pytest tests/`
- 引擎改动：新增数值等价测试，断言向量化/新路径与既有标量实现一致

## 不做（YAGNI）
- 美国税务引擎 / Roth/RMD/IRMAA（美国本土化深坑，对目标用户无用）
- 因子回归 / Black-Litterman / CVaR 优化（对散户过重）
- 账户聚合（合规 + 工程成本极高，与无登录架构冲突）
