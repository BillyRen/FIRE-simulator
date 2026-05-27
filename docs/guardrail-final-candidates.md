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
| **C** | ~~激进 (deprecated)~~ | ~~`tgt=0.80 up=0.99 lo=0.50 adj=0.10 amount mr=1`~~ | ~~3.70%~~ | ~~0.859~~ | ~~0.844 ⚠~~ | ~~36/54~~ | ~~≈ 0 ⚠️~~ | **替代为 E**（同 SWR，E 全面更优） |
| **D** | 综合-高 CEW | `tgt=0.85 up=0.90 lo=0.50 adj=0.15 amount mr=10` | 3.31% | 0.864 | 0.843 ⚠ | 35/54 | ≈ 0 ⚠️ | CEW > $51K / 接受 4-src 边际 |
| **E** | 激进-稳健 ★ | `tgt=0.80 up=0.99 lo=0.80 adj=0.05 amount mr=1` | 3.70% | 0.861 | **0.860** ✓ | 31/54 | **$45,540** ✓ | 想要 SWR 3.70% + CEW 不崩塌（dominates 旧 C） |

\* `min effSR` 加粗 = 通过 0.85 gating；⚠ = 边际（0.83-0.85）；❌ = 跌出（< 0.83）
\* `54-env min CEW ≈ 0` 出现在 `with_cfs=True AND retirement_years ∈ {45, 60}` 子集
\* 平衡档 `target=0.85, lo=0.50, adj=0.25, success_rate, mr=1` 已被剔除（4-src min effSR=0.733 跌出 gating，详见 §选择理由）
\* C → E：原激进档 C 在 2026-05-27 后续分析中被 E 严格 dominate（同 SWR 3.70%，4-src min effSR +1.6pp，54-env fails -5，且 CEW 不崩塌）。保留 C 在 summary CSV 中 status=deprecated 仅作历史参考。

---

### ★ 结构性发现：CEW 崩塌的 root cause

跨所有候选，**CEW 在 54-env 是否崩塌完全由 `(lower, adj)` 组合决定，与 target 无关**：

| (lower, adj) 组合 | 候选 | 54-env min CEW | CEW 崩塌? |
|---|---|---:|---|
| `lo=0.80, adj=0.05` | A (tgt=0.95), **E (tgt=0.80)** | $34,925 / $45,540 | **✗ 不崩塌** |
| `lo=0.70, adj=0.10` | B | ≈ 0 | ✓ 崩塌 |
| `lo=0.50, adj=0.10` | C (deprecated) | ≈ 0 | ✓ 崩塌 |
| `lo=0.50, adj=0.15` | D | ≈ 0 | ✓ 崩塌 |
| `lo=0.50, adj=0.25` | dropped Max-CEW | ≈ 0 | ✓ 崩塌 |

**机理**：在 `with_cfs=True + long horizon + high floor` 极端 env 下，wd 持续向下削减。`lo=0.80 + adj=0.05` 表示"频繁触发 lower + 每次只削 5%"——即使触发也是 micro-adjustments，wd 不会断崖式下跌。其它 (lo, adj) 组合让单次削减更激进 → 跌进 0 附近不再回升。

**应用建议**：如果你重视 long-horizon worst-case 消费水平（不只是 effSR 不破产），**选择 (lo=0.80, adj=0.05) 系列**——即 A (tgt=0.95) 或 E (tgt=0.80)。两者只在 SWR 起点不同（2.37% vs 3.70%）。

---

## 详细 robustness 矩阵

### 4-source baseline effSR（15/75/10, 50yr, no CFs, floor=0.50）

| ID | POOL | USA | DEU | JPN | min |
|---|---:|---:|---:|---:|---:|
| **A** 保守 | 0.964 | 0.971 | 0.975 | **0.957** | 0.957 ✓ |
| **B** 旧推荐 | 0.901 | 0.908 | 0.913 | **0.883** | 0.883 ✓ |
| **C** 激进 | 0.859 | 0.879 | 0.874 | **0.844** | 0.844 ⚠ |
| **D** 综合 | 0.864 | 0.870 | 0.870 | **0.843** | 0.843 ⚠ |

→ **A 在所有 source 都过 0.85；B 也都过（最弱 JPN 0.883）；C/D 在 JPN 跌到 0.843-0.844（边际）**。

### 54-env stress（3 alloc × 3 years × 2 CFs × 3 floor, POOL only）

| ID | min effSR | n_envs effSR<0.85 | min median_CEW |
|---|---:|---:|---:|
| **A** 保守 | 0.727 | 18/54 | **$34,925** |
| **B** 旧推荐 | 0.436 | 27/54 | ≈ 0 |
| **C** 激进 | 0.408 | 36/54 | ≈ 0 |
| **D** 综合 | 0.332 | 35/54 | ≈ 0 |

→ **A 是唯一 54-env 下 CEW 不崩塌的**；B/C/D 在 `with_cfs=True AND years ∈ {45, 60}` 极端 env 下 CEW → 0。
→ B 在 stress 维度紧次于 A（fail 27 vs 18，min effSR 0.436 vs 0.727）。

### POOL baseline 主要指标

| ID | SWR | init annual wd | effFR | CEW |
|---|---:|---:|---:|---:|
| **A** 保守 | 2.37% | $23,692 | 0.990 | $36,229 |
| **B** 旧推荐 | 3.31% | $33,111 | 0.962 | $45,590 |
| **C** 激进 | 3.70% | $37,036 | 0.946 | $48,322 |
| **D** 综合 | 3.31% | $33,111 | 0.954 | $51,293 |

→ B 与 D 同 SWR ($33K)，D CEW 高 +12%（$51K vs $46K），但 D 的 4-src min effSR 比 B 低 0.04（0.843 vs 0.883）。**这是真实 trade-off：D 多 12% CEW 换 4pp robustness 损失**。

---

## 选择决策树

```
你的优先级是？
├── "想要最稳健、可承受较低消费" → A 保守 ★ DEFAULT
│       SWR 2.37%，4-src 全过 (min 0.957) + 54-env 18/54 fails（最少）
│       唯一一档 54-env min CEW 保持正值（$34.9K），其它 tier CEW 在
│       long-horizon + CFs 极端 env 下崩塌至 ≈ 0
│
├── "想要 3-4% 消费水平，仍要 robust" → B 旧推荐（重新发现）
│       SWR 3.31%，4-src 全过 (min 0.883)，54-env 27 个 fail
│       注意：JPN-like extreme stress 下 CEW 会崩
│
├── "起步消费 > 3.7%" → C 激进
│       SWR 3.70%，JPN 下 effSR 0.844 边际
│       注意：你需要能接受 JPN 风格 stress 下 effSR 跌出 0.85
│
└── "CEW 最大化、能容忍 robustness 略低" → D 综合-高 CEW
        SWR 3.31% + CEW $51K（比 B 高 12%）
        4-src min effSR 0.843（vs B 的 0.883），相差 4pp
        注意：这是 user 主动选择 CEW > robustness 的 trade-off
```

---

## 各候选的选择理由 / 警告

### A. 保守（推荐 default）
- **★ 选择理由**: 在所有 4 个 source baseline 下都过 gating（min effSR 0.957），且 54-env stress 测试中 fails 数最少（18/54）、**唯一 54-env min CEW 保持正值**（$34.9K，其它 tier 都崩到 ≈ 0）。`target=0.95` 让反算 SWR 极低（2.37%），护栏从不被深度触发，路径稳定。
- **警告**: A 在 54-env stress 中仍有 18/54 个 env 跌出 effSR ≥ 0.85。这 18 个全部是 `with_cfs=True AND retirement_years ∈ {45, 60}` 组合，跨 3 个 alloc（10/80/10、15/75/10、25/65/10）平均分布，floor (0.4/0.5/0.6) 也不 binding——即 **CFs + 中长 horizon 是真正的 stress driver**。完美 robust 不存在；A 的优势是相对其它 tier 跌幅最小（min effSR 0.727 vs B 0.436 / D 0.332）。
- **额外警告**: SWR 低，初始消费 $23,692 / $1M（用户实际 IB 持仓换算后可能感觉偏紧）。但路径中位 CEW $36K 高于初始 wd 53%，反映 guardrail upper 上调消费。
- **mr=1 vs 1/3/5/10**: 在所有数据中差异 < 0.001 effFR。选 mr=1 是数据最优；mr=5/10 是 v1 "保守取"，没有实质差异。

### B. 旧推荐 (v1，2026-03-17)
- **★ 选择理由（重新发现）**: 综合排序 + 全 robustness 验证后，B 在 SWR 3.31% 这档是**最稳健**的选项——比综合 Top-1 (D) 在 4-src min effSR 高 4pp，54-env failures 少 8 个。
- **机理**: `lower=0.70`（vs D 的 0.50）让护栏更早触发 → 提前削减 wd → 减少 deep stress 下的 wd 大幅下滑。
- **警告**: 54-env CEW 仍崩塌（all `target=0.85` candidates 一样）。在 long-horizon + CFs + high-floor 极端环境下不可靠。
- **mr=5 vs 1**: 数据中差异 < 0.001 effFR。保留 v1 取 mr=5 不影响。

### C. 激进
- **★ 选择理由**: 想要最高初始消费（3.70%）+ 能接受较大 path 调整。
- **警告**: JPN data 下 effSR 0.844，跌到 0.85 gating 边际。若担心 JPN-style sequence risk（Lost Decades + WWII），改 A 或 B。
- **激进档不是综合 winner**: 在 min-max normalized sum 下排第 #8（被 SWR 极值推高），但在 rank-sum / Borda 下只排 #441/1701。综合排序时偏向 SWR 是评价方法选择的产物。

### D. 综合-高 CEW
- **★ 选择理由**: 综合排序（rank-sum 和 geomean）的 Top-1。在 3 个指标上都不极端但都强：
  - effFR rank #1223（不是最高但很高）
  - CEW rank #128（top 7.5%）
  - SWR rank #85（top 5%）
- **vs B 旧推荐**: D 与 B 都是 `target=0.85, amount mode, SWR 3.31%`。**唯一差异**: D `lower=0.50, adj=0.15, mr=10` vs B `lower=0.70, adj=0.10, mr=5`。
  - D 优势: CEW $51K vs $46K（+12%）
  - B 优势: 4-src min effSR 0.883 vs 0.843（+4pp）、54-env fails 27 vs 35（-8）、54-env min effSR 0.436 vs 0.332（+10pp）
- **真实 trade-off**: D 给"中位日子"多 12% 消费，B 给"最坏日子"多 4pp 安全边际。**user 实际选哪个取决于风险偏好**。

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
| Composite Min-max Top-1 | `target=80, up=99, lo=80, adj=05, amount, mr=1` | 接近候选 C（lower 不同） |

**v2 报告的"保守档"和"激进档"未变**。**新增**：**候选 B 重新发现**——综合 robustness 验证后，旧推荐在 SWR 3.31% 档是最稳健选择。候选 D 是 explicit CEW-max trade-off。

---

## 复现性

- 候选 B 和 D 的 4-src + 54-env 数据由 `analysis/guardrail_v2_validate_candidates.py` 添加到原 `cross_source.csv` (124 rows) 和 `sensitivity.csv` (8208 rows)
- 汇总表 `analysis/output/guardrail_v2/final_candidates_summary.csv` 包含 5 行：4 个 final（A/B/C/D, `status=final`）+ 1 个 dropped（X Max-CEW, `status=dropped`，保留用于"上界参考"）。`status` 列必读以区分推荐与已淘汰候选。
- 生成脚本：`analysis/guardrail_v2_summarize_final.py`
- 所有 4 候选可在 v2 baseline_grid.csv 中查到原始 5-seed 平均
