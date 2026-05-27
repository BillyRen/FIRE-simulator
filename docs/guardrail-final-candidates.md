# Guardrail 最终 4 备选参数（v2 全 robustness 验证）

**日期**: 2026-05-27
**Baseline**: JST Pool 1900+, 15/75/10, 50yr, $1M, no CFs, floor=0.50, seed=42
**完整方法论**: [docs/guardrail-optimal-params-v2.md](guardrail-optimal-params-v2.md)
**数据**: `analysis/output/guardrail_v2/final_candidates_summary.csv`

---

## TL;DR — 4 备选对比表

| ID | Tier | 参数 | SWR | POOL effSR | 4-src min effSR | 54-env fail count | 54-env min CEW | 推荐场景 |
|---|---|---|---:|---:|---:|---:|---:|---|
| **A** | 保守 ★ | `tgt=0.95 up=0.99 lo=0.80 adj=0.05 amount mr=1` | 2.37% | 0.964 | **0.957** ✓ | **18/54** | **$34,925** ✓ | Default / 4-src 全过 + 54-env fails 最少且 CEW 不崩塌 |
| **B** | 旧推荐 (v1) | `tgt=0.85 up=0.99 lo=0.70 adj=0.10 amount mr=5` | 3.31% | 0.901 | 0.883 ✓ | 27/54 | ≈ 0 ⚠️ | 平衡水平 / 想要 SWR 3.31% / floor=0.50 标准 |
| **C** | ~~激进 (deprecated)~~ | ~~`tgt=0.80 up=0.99 lo=0.50 adj=0.10 amount mr=1`~~ | ~~3.70%~~ | ~~0.859~~ | ~~0.844 ⚠~~ | ~~36/54~~ | ~~≈ 0 ⚠️~~ | **替代为 F**（旧 E 改名 + lower 调到 0.70 满足 user 约束） |
| **D** | 综合-高 CEW | `tgt=0.85 up=0.90 lo=0.50 adj=0.15 amount mr=10` | 3.31% | 0.864 | 0.843 ⚠ | 35/54 | ≈ 0 ⚠️ | CEW > $51K / 接受 4-src 边际 |
| **E** | ~~激进-稳健 (deprecated, gap=0)~~ | ~~`tgt=0.80 up=0.99 lo=0.80 adj=0.05 amount mr=1`~~ | ~~3.70%~~ | ~~0.861~~ | ~~0.860 ✓~~ | ~~31/54~~ | ~~$45,540 ✓~~ | **违反 user 哲学约束**（lower=target=0.80, gap=0）；替代为 F |
| **F** | 激进-gap10 ★ | `tgt=0.80 up=0.99 lo=0.70 adj=0.05 amount mr=1` | 3.70% | 0.857 | 0.853 ✓ | 33/54 | **$45,500** ✓ | 想要 SWR 3.70% + CEW 不崩塌 + lower 比 target 低 10pp |

\* `min effSR` 加粗 = 通过 0.85 gating；⚠ = 边际（0.83-0.85）；❌ = 跌出（< 0.83）
\* `54-env min CEW ≈ 0` 出现在 `with_cfs=True AND retirement_years ∈ {45, 60}` 子集
\* 平衡档 `target=0.85, lo=0.50, adj=0.25, success_rate, mr=1` 已被剔除（4-src min effSR=0.733 跌出 gating，详见 §选择理由）
\* C → E → F 演化：
- 原激进档 C (lo=0.50, adj=0.10) 被 E (lo=0.80, adj=0.05) robustness 全面优于
- E 被 user 约束（lower 必须比 target 低 ≥ 10pp）拒绝（E 的 lo=0.80 = target=0.80, gap=0）
- 最终用 F (lo=0.70, adj=0.05, gap=10pp)，性能与 E 几乎相同（4-src min effSR -0.7pp 在 noise 内，CEW 同 $45.5K 不崩塌）

保留 C/E 在 summary CSV 中 `status=deprecated` 仅作历史参考。

---

### ★ 结构性发现：`adj` 是 CEW 崩塌的主导因子

跨 sensitivity.csv 153 个完整 (54-env) 参数集，按 `(lower, adj)` 分组的 CEW 崩塌率（min median_CEW < $100 视为崩塌）：

| adj | lower=0.2 | lower=0.5 | lower=0.7 | lower=0.8 |
|:---:|:---:|:---:|:---:|:---:|
| **0.05** | 0/2 (0%) | 0/12 (0%) | 3/19 (**16%**) | 0/13 (0%) |
| 0.10 | — | 8/12 (67%) | 8/16 (50%) | — |
| 0.15 | 2/2 (100%) | 11/11 (100%) | 10/10 (100%) | 3/3 (100%) |
| 0.20 | 1/1 (100%) | 11/11 (100%) | 11/11 (100%) | 3/3 (100%) |
| 0.25 | 1/1 (100%) | 13/13 (100%) | 10/10 (100%) | 3/3 (100%) |

**真实规律**:
1. **`adj=0.05` 是 CEW non-collapse 的主要 driver**——55 个不崩塌参数中 43 个是 adj=0.05；其余 12 个全部是 adj=0.10 + target=0.95 组合。同时 46 个 adj=0.05 参数中有 3 个崩塌（都是 target=0.80 + lower=0.7 组合），说明 adj=0.05 是强 indicator 但非严格 sufficient
2. **`adj ≥ 0.15` 几乎 100% 崩塌**，与 lower 无关
3. **`adj=0.10` 是 borderline**：lower=0.5/0.7 各 50-67% 崩塌；与 target 强 interact（target=0.95 时不崩，target=0.80 时崩）
4. **`lower` 影响 secondary**：在 adj=0.05 下，lower ∈ {0.2, 0.5, 0.8} 都不崩塌；lower=0.7 有 3/19 (16%) 崩塌

**机理**：在 `with_cfs=True + long horizon + high floor` 极端 env 下，guardrail 触发后 wd 削减按 `(1 - adj)` 倍数缩放。`adj=0.05` 表示每次只削 5% → wd 缓慢下降可被市场回升追回；`adj ≥ 0.15` 表示每次削 ≥15% → 触发频繁时 wd 一路向下跌进 0 附近不再回升。

**应用建议**：如果你重视 long-horizon worst-case 消费水平（不只是 effSR 不破产），**首选 `adj=0.05` 参数**——即 A (tgt=0.95, lo=0.80) 或 F (tgt=0.80, lo=0.70)。两者主要差 SWR 起点（2.37% vs 3.70%），但 robustness 也有差：A 跨 4-src min effSR 0.957 + 54-env 仅 18/54 fails；F 跨 4-src min effSR 0.853 + 54-env 33/54 fails（仍通过 gating + CEW 不崩塌）。**避开 `adj ≥ 0.15`**（包括 v2 综合 ranking Top-1 即 D 候选）。

---

## 详细 robustness 矩阵

### 4-source baseline effSR（15/75/10, 50yr, no CFs, floor=0.50）

| ID | POOL | USA | DEU | JPN | min |
|---|---:|---:|---:|---:|---:|
| **A** 保守 | 0.964 | 0.971 | 0.975 | **0.957** | 0.957 ✓ |
| **B** 旧推荐 | 0.901 | 0.908 | 0.913 | **0.883** | 0.883 ✓ |
| ~~**C** 激进 (dep)~~ | ~~0.859~~ | ~~0.879~~ | ~~0.874~~ | ~~**0.844**~~ | ~~0.844 ⚠~~ |
| **D** 综合 | 0.864 | 0.870 | 0.870 | **0.843** | 0.843 ⚠ |
| ~~**E** 激进-稳健 (dep)~~ | ~~0.861~~ | ~~0.873~~ | ~~0.876~~ | ~~**0.860**~~ | ~~0.860 ✓~~ |
| **F** 激进-gap10 | 0.857 | 0.870 | 0.873 | **0.853** | 0.853 ✓ |

→ **A、B、F 在所有 source 都过 0.85**（最弱 JPN 0.957/0.883/0.853）；D 在 JPN 跌到 0.843（边际）；deprecated C 是 0.844 边际、deprecated E 0.860 通过但 lower=target=0.80 违反 user 约束。

### 54-env stress（3 alloc × 3 years × 2 CFs × 3 floor, POOL only）

| ID | min effSR | n_envs effSR<0.85 | min median_CEW |
|---|---:|---:|---:|
| **A** 保守 | 0.727 | 18/54 | **$34,925** ✓ |
| **B** 旧推荐 | 0.436 | 27/54 | ≈ 0 ❌ |
| ~~**C** 激进 (dep)~~ | ~~0.408~~ | ~~36/54~~ | ~~≈ 0~~ ❌ |
| **D** 综合 | 0.332 | 35/54 | ≈ 0 ❌ |
| ~~**E** 激进-稳健 (dep)~~ | ~~0.518~~ | ~~31/54~~ | ~~$45,540 ✓~~ |
| **F** 激进-gap10 | 0.518 | 33/54 | **$45,500** ✓ |

→ **A 和 F 是唯一两个 final tier 在 54-env 下 CEW 不崩塌**（都使用 adj=0.05；详见 §结构性发现）；B/D/deprecated-C 在 `with_cfs=True AND years ∈ {45, 60}` 极端 env 下 CEW → 0。
→ F 与 A 同为 adj=0.05 family，只在 target 上差异（0.80 vs 0.95），让 user 在 SWR 维度有 3.70% vs 2.37% 的选择。
→ F vs deprecated E：F lower 从 0.80 降到 0.70 满足 user 哲学约束，性能数字几乎无差（54-env min effSR 同 0.518，min CEW 同 $45,500）。

### POOL baseline 主要指标

| ID | SWR | init annual wd | effFR | CEW |
|---|---:|---:|---:|---:|
| **A** 保守 | 2.37% | $23,692 | 0.990 | $36,229 |
| **B** 旧推荐 | 3.31% | $33,111 | 0.962 | $45,590 |
| ~~**C** 激进 (dep)~~ | ~~3.70%~~ | ~~$37,036~~ | ~~0.946~~ | ~~$48,322~~ |
| **D** 综合 | 3.31% | $33,111 | 0.954 | $51,293 |
| ~~**E** 激进-稳健 (dep)~~ | ~~3.70%~~ | ~~$37,036~~ | ~~0.955~~ | ~~$46,655~~ |
| **F** 激进-gap10 | 3.70% | $37,036 | 0.954 | $46,753 |

→ B 与 D 同 SWR ($33K)，D CEW 高 +12%（$51K vs $46K），但 D 的 4-src min effSR 比 B 低 0.04（0.843 vs 0.883）。**这是真实 trade-off：D 多 12% CEW 换 4pp robustness 损失**。
→ F vs deprecated C 同 SWR ($37K)，**robustness 维度 F 全面更优**（4-src min effSR +0.9pp 通过 gating、54-env fails -3、min effSR +11pp、CEW 54-env 不崩塌），但**baseline POOL CEW F 略低** $46.8K vs $48.3K（-3.3%）。这不是严格 Pareto-dominance，是真实 trade-off。
→ F vs deprecated E：lower 从 0.80 → 0.70 满足 user 哲学（lower 应明显低于 target），其它指标几乎不变（CEW +$98、effFR -0.001、4-src min -0.007）。

---

## 选择决策树

```
你的优先级是？
├── "想要最稳健、可承受较低消费" → A 保守 ★ DEFAULT
│       SWR 2.37%，4-src 全过 (min 0.957) + 54-env 18/54 fails（最少）
│       CEW 不崩塌（54-env min $34.9K）
│
├── "想要 SWR ~3.3% + robust" → B 旧推荐（重新发现）
│       SWR 3.31%，4-src 全过 (min 0.883)，54-env 27 个 fail
│       注意：54-env 极端 env 下 CEW 会崩（adj=0.10 边际）
│
├── "想要 SWR ~3.7% + CEW 不崩塌" → F 激进-gap10 ★
│       SWR 3.70%，4-src 全过 (min 0.853) + 54-env 33 fails + CEW $45.5K 不崩塌
│       lower=0.70 (target=0.80, gap=10pp) 满足 user 哲学约束
│       与已弃用 E (lo=0.80) 性能几乎相同，只是 lower 比 target 低 10pp
│
└── "CEW 最大化、能容忍 robustness 略低" → D 综合-高 CEW
        SWR 3.31% + CEW $51K（比 B 高 12%）
        4-src min effSR 0.843（vs B 0.883 / F 0.853），CEW 在 long-
        horizon CFs 下崩塌（adj=0.15 → 100% 崩塌率）
```

---

## 各候选的选择理由 / 警告

### A. 保守（推荐 default）
- **★ 选择理由**: 在所有 4 个 source baseline 下都过 gating（min effSR 0.957），且 54-env stress 测试中 fails 数最少（18/54）。CEW 在 54-env 仍 ≥ $34.9K（与 E 共享 adj=0.05 不崩塌特性，详见 §结构性发现）。`target=0.95` 让反算 SWR 极低（2.37%），护栏从不被深度触发，路径稳定。
- **警告**: A 在 54-env stress 中仍有 18/54 个 env 跌出 effSR ≥ 0.85。这 18 个全部是 `with_cfs=True AND retirement_years ∈ {45, 60}` 组合，跨 3 个 alloc（10/80/10、15/75/10、25/65/10）平均分布，floor (0.4/0.5/0.6) 也不 binding——即 **CFs + 中长 horizon 是真正的 stress driver**。完美 robust 不存在；A 的优势是相对其它 tier 跌幅最小（min effSR 0.727 vs B 0.436 / D 0.332）。
- **额外警告**: SWR 低，初始消费 $23,692 / $1M（用户实际 IB 持仓换算后可能感觉偏紧）。但路径中位 CEW $36K 高于初始 wd 53%，反映 guardrail upper 上调消费。
- **mr=1 vs 1/3/5/10**: 在所有数据中差异 < 0.001 effFR。选 mr=1 是数据最优；mr=5/10 是 v1 "保守取"，没有实质差异。

### B. 旧推荐 (v1，2026-03-17)
- **★ 选择理由（重新发现）**: 综合排序 + 全 robustness 验证后，B 在 SWR 3.31% 这档是**最稳健**的选项——比综合 Top-1 (D) 在 4-src min effSR 高 4pp，54-env failures 少 8 个。
- **机理**: `lower=0.70`（vs D 的 0.50）让护栏更早触发 → 提前削减 wd → 减少 deep stress 下的 wd 大幅下滑。
- **警告**: 54-env CEW 仍崩塌（all `target=0.85` candidates 一样）。在 long-horizon + CFs + high-floor 极端环境下不可靠。
- **mr=5 vs 1**: 数据中差异 < 0.001 effFR。保留 v1 取 mr=5 不影响。

### ~~C. 激进~~ (deprecated 2026-05-27, 演化路径 C → E → F)
- 原参数 `tgt=0.80 up=0.99 lo=0.50 adj=0.10 amount mr=1`
- 被 E (同 SWR 3.70%) robustness 全面优于：4-src min effSR +1.6pp、54-env fails -5、min effSR +11pp、CEW 不崩塌
- E 又被 user 约束（lower 必须比 target 低 ≥ 10pp）拒绝（E lo=0.80 = target=0.80, gap=0），最终用 F (lo=0.70, gap=10pp)
- 保留在 `final_candidates_summary.csv` 中 `status=deprecated` 仅作历史参考

### ~~E. 激进-稳健 (deprecated 2026-05-27, gap=0 违反 user 约束)~~
- 原参数 `tgt=0.80 up=0.99 lo=0.80 adj=0.05 amount mr=1`
- robustness 全面优于 deprecated C，但 lower=target=0.80（gap=0）违反 user 哲学（lower 应明显低于 target）
- 替代为 F：lower 调到 0.70（gap=10pp），其它参数不变；性能差异在 noise 内

### F. 激进-gap10（推荐用于 SWR 3.70% 需求 + lower < target）
- **★ 选择理由**: target=0.80 内部 baseline-optimal by effFR 当 lower ≤ 0.70 约束下 (0.954)，4-src min effSR 0.853 通过 gating（C 0.844 边际跌出）。CEW 在 54-env 不崩塌（min $45,500）——与 A 共享 adj=0.05 family。
- **机理**: `lower=0.70 + adj=0.05` 让护栏在 success_rate < 70% 时触发，每次只削 5%——micro-adjustments 累积保 wd 不深跌。adj=0.05 是 CEW non-collapse 的主导 driver（详见 §结构性发现）。
- **vs A**: 同 family (lo=0.7-0.8, adj=0.05, amount)，只差 target (0.80 vs 0.95) → SWR (3.70% vs 2.37%)。如果 user 需要 $33K+ 起点消费，F > A；否则 A > F。
- **vs B**: 同 user profile 下 F 起点高 0.4pp SWR、4-src 略低 -3pp、但 CEW 不崩塌（B 崩塌）。**F 是"想要更高 SWR 又不放弃 CEW robustness 且 lower 明显低于 target"的精确解**。
- **vs deprecated E**: lower 从 0.80 → 0.70 满足 user 哲学；性能差异：CEW +$98（无意义提升），effFR -0.001（noise），4-src min effSR -0.007（仍过 gating），54-env fails +2（边际增加）。**为 user 约束付的代价极小**。

### D. 综合-高 CEW
- **★ 选择理由**: 综合排序（rank-sum 和 geomean）的 Top-1。在 3 个指标上都不极端但都强：
  - effFR rank #1223（不是最高但很高）
  - CEW rank #128（top 7.5%）
  - SWR rank #85（top 5%）
- **vs B 旧推荐**: D 与 B 都是 `target=0.85, amount mode, SWR 3.31%`。**唯一差异**: D `lower=0.50, adj=0.15, mr=10` vs B `lower=0.70, adj=0.10, mr=5`。
  - D 优势: CEW $51K vs $46K（+12%）
  - B 优势: 4-src min effSR 0.883 vs 0.843（+4pp）、54-env fails 27 vs 35（-8）、54-env min effSR 0.436 vs 0.332（+10pp）
- **真实 trade-off**: D 给"中位日子"多 12% 消费，B 给"最坏日子"多 4pp 安全边际。**user 实际选哪个取决于风险偏好**。
- **CEW collapse 警告**: D 的 `adj=0.15` 在 54-env CEW collapse 测试中 **100% 崩塌率**（参见 §结构性发现表）。若 user 担心 long-horizon CFs scenarios，应避开 D。

### 为何剔除平衡档（`tgt=0.85, lo=0.50, adj=0.25, success_rate, mr=1`）
- POOL CEW $53,976（4 候选中最高）但 4-src min effSR = **0.733 (JPN)** — **跌出 gating 0.85 阈值整 12pp**
- 54-env effSR 38/54 fails，min 0.208
- `mode=success_rate` 在 JPN-like extreme drawdown 下削减过激 → 路径中位 wd 持续下滑 → CEW 崩塌
- 不推荐作为生产参数 — 仅作为"最大 CEW 上界"参考

---

## 与之前推荐对比

| 来源 | 推荐 | 在新数据下评估 |
|---|---|---|
| v1 (2026-03-17) 单一推荐 | `target=85, up=99, lo=70, adj=10, amount, mr=5` | 现 = **候选 B**，仍合理 |
| v2 §6.4 单一最终推荐 | `target=95, up=99, lo=80, adj=0.05, amount, mr=1` | 现 = **候选 A**，仍合理 |
| Composite ranking Top-1 | `target=85, up=90, lo=50, adj=15, amount, mr=10` | 现 = **候选 D**，但 robustness 不如 B |
| Composite Min-max Top-1 | `target=80, up=99, lo=80, adj=05, amount, mr=1` | 原为候选 E（SWR=3.70% sweet spot），后被 user 约束 `lower ≤ target-0.10`（即 gap ≥ 10pp）拒绝；改为候选 F (lo=0.70) |

**v2 报告的"保守档"和"激进档"未变**。**新增**：**候选 B 重新发现**——综合 robustness 验证后，旧推荐在 SWR 3.31% 档是最稳健选择。候选 D 是 explicit CEW-max trade-off。

---

## 复现性

- 候选 B、D、E、F 的 4-src + 54-env 数据由 `analysis/guardrail_v2_validate_candidates.py` 添加到原 `cross_source.csv` 和 `sensitivity.csv`
- 汇总表 `analysis/output/guardrail_v2/final_candidates_summary.csv` 包含 7 行：
  - 4 final（A / B / D / F，`status=final`）
  - 2 deprecated（C Aggressive 被 robustness 全面优于；E Aggressive-robust 因 lower=target 违反 user gap≥10pp 约束）
  - 1 dropped（X Max-CEW，`status=dropped`，作"上界参考"）
- **`status` 列必读以区分推荐与已淘汰候选**
- 生成脚本：`analysis/guardrail_v2_summarize_final.py`
- 所有候选可在 v2 baseline_grid.csv 中查到原始 5-seed 平均
