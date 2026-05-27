# Guardrail × Allocation 分析报告（2026-05-27）

> 配套 `docs/optimal-allocation-analysis-2026-05-27.md`（v1 fixed/declining/smile）；脚本：`analysis/optimal_allocation_guardrail.py`；原始数据：`analysis/output/optimal_allocation/guardrail_results.csv` (1,320 行)。
> Guardrail 参数：**target=0.85 / up=0.99 / lo=0.70 / adj=0.10 / mode=amount / mr=5**。

## 1. 一句话结论

**Guardrail 不改变跨场景最优 alloc 结论**：综合 (eff_FR + init_SWR + P10_min_wd) 三指标后，**top-1 仍是 30/60/10**，top-10 与 v1 fixed 几乎相同（10 个里有 8 个重叠）。但 **如果只看单一 eff_FR 指标，会被 bond-heavy alloc 误导**——这是 guardrail 分析的关键 pitfall。

## 2. 方法学

`sweep_allocations` 不支持 guardrail，所以本次自己写循环：
1. `pregenerate_raw_scenarios` 抽样（与 v1 相同）。
2. 对 66 个 alloc，逐个 `raw_to_combined` 算 real_returns（`borrowing_spread=0.02` 显式传，与 v1 对齐）。
3. 每 alloc 单独 `build_success_rate_table`（表是 alloc-specific）。
4. `run_guardrail_simulation(initial_portfolio=1M, target=0.85, ...)` 反推 `initial_wd`，模拟动态调整路径。
5. 指标：传统 `success_rate`、`compute_effective_funded_ratio`（消费地板=50% 初始 wd）、`p10_min_wd`、`mean_years_below_floor` 等。

20 个 scenario × 66 alloc = 1,320 行，7.4 分钟跑完。

### 重要 caveat（Codex review 提醒）
- `initial_swr` 不能解释为 "guardrail 相比 fixed 的 SWR 提升"。在 `input_mode=portfolio` 下，guardrail 用 `find_rate_for_target(table, target=0.85)` 反推 init_wd——这正是 fixed-WR 表的反推。所以同 alloc / 同 target，**guardrail init_swr ≡ fixed @ target=0.85 的 SWR**。Guardrail 的真实价值出现在路径中后期的动态调整（被 `eff_funded_ratio` / `p10_min_wd` 等指标体现）。
- `success_rate` 用 `compute_success_rate(traj, years)`，last-year 破产仍算成功，与 v1 对齐。

## 3. 三视角排名对比（核心发现）

### 3.1 单一 `eff_funded_ratio` 排名（**误导版本**）
| Alloc | eff_FR_rank | mean_eff_FR | mean_SWR | mean_P10_wd |
|---|---|---|---|---|
| 10/50/40 | 19.00 | 0.977 | **3.29%** | $21,795 |
| 20/40/40 | 20.00 | 0.976 | **3.33%** | $22,102 |
| 10/40/50 | 20.00 | 0.975 | **3.05%** | $20,314 |
| 00/40/60 | 20.05 | 0.975 | **2.71%** | $18,445 |
| 00/30/70 | 20.25 | 0.974 | **2.44%** | $16,620 |
| ... | | | | |

**为什么 bond-heavy 赢了 eff_FR**：bond 路径波动小，触发 `lower_guardrail` 的次数少，消费很少跌破 50% 地板 → eff_FR 接近上限。**但代价是初始 SWR 只有 2-3.3%**——投资者实际可消费水平比 stock-heavy 低一截。

### 3.2 **综合排名（推荐）**：composite = avg(eff_FR_rank, P10_wd_rank, SWR_rank)
| Alloc | composite | eff_FR_r | P10_r | SWR_r | mean_eff_FR | mean_SWR | mean_P10_wd | yrs<floor |
|---|---|---|---|---|---|---|---|---|
| **30/60/10** | **13.92** | 27.9 | 7.1 | 6.8 | 0.976 | 3.83% | $24,818 | 1.1 |
| 30/50/20 | 14.82 | 22.8 | 8.7 | 12.9 | 0.976 | 3.72% | $24,433 | 1.1 |
| 40/50/10 | 14.88 | 30.5 | 6.9 | 7.2 | 0.974 | 3.83% | $24,717 | 1.1 |
| 20/60/20 | 15.13 | 20.8 | 10.3 | 14.3 | 0.977 | 3.69% | $24,412 | 1.0 |
| 20/70/10 | 15.88 | 27.2 | 10.6 | 9.8 | 0.975 | 3.78% | $24,534 | 1.1 |
| 40/40/20 | 17.53 | 28.2 | 9.8 | 14.6 | 0.974 | 3.69% | $24,204 | 1.1 |
| 40/60/00 | 17.88 | 37.0 | 11.6 | 5.1 | 0.973 | 3.89% | $24,571 | 1.2 |
| 30/70/00 | 18.37 | 35.0 | 13.9 | 6.2 | 0.974 | 3.87% | $24,408 | 1.1 |
| 50/40/10 | 19.25 | 36.1 | 10.8 | 10.8 | 0.972 | 3.77% | $24,313 | 1.2 |
| 20/50/30 | 19.25 | 19.2 | 16.1 | 22.4 | 0.977 | 3.55% | $23,570 | 1.0 |

**注意**：composite 视角下 top-1 是 **30/60/10**，与 v1 fixed 的 top-1 完全一致；前 10 名中 8 个与 v1 相同（仅 20/50/30 替换 v1 的 50/50/00）。

### 3.3 v1 fixed vs guardrail composite top-10 重叠

| Rank | v1 fixed (mean_rank_fr) | guardrail (composite) | 重叠? |
|---|---|---|---|
| 1 | 30/60/10 | 30/60/10 | ✅ |
| 2 | 40/50/10 | 30/50/20 | — |
| 3 | 20/70/10 | 40/50/10 | ✅(序变) |
| 4 | 30/50/20 | 20/60/20 | ✅(序变) |
| 5 | 40/60/00 | 20/70/10 | ✅(序变) |
| 6 | 30/70/00 | 40/40/20 | ✅(序变) |
| 7 | 20/60/20 | 40/60/00 | ✅(序变) |
| 8 | 40/40/20 | 30/70/00 | ✅(序变) |
| 9 | 50/40/10 | 50/40/10 | ✅ |
| 10 | 50/50/00 | 20/50/30 | — |

→ **保留了 v1 fixed 的核心结论**：Stock ≥ 70% / Bond 0-20% / Dom-Intl 比例 20-50:40-70。

## 4. Per-scenario 最优配置（按 eff_FR）的 trap

由于 eff_FR 单一视角下 bond-heavy 占优，per-scenario best (按 eff_FR) 报告的最优往往不实用：

| Country (1900, 45y, leverage=1.0) | guardrail "best" by eff_FR | init_SWR | v1 fixed best | v1 SWR (@ 4%) |
|---|---|---|---|---|
| USA | **00/00/100** | **1.66%** | 50/50/00 | 4.0% |
| ALL | 20/70/10 | 3.45% | 30/70/00 | 4.0% |
| AUS | **00/10/90** | **1.87%** | 60/40/00 | 4.0% |
| CHE | **00/00/100** | **2.00%** | 10/70/20 | 4.0% |
| DEU | 20/50/30 | 2.71% | 40/60/00 | 4.0% |
| JPN | 30/70/00 | 3.26% | 30/70/00 | 4.0% |

USA、AUS、CHE 在 eff_FR 视角下都是"100% bond / 90% bond"获胜，init_SWR 跌到 1.2-2%。**这不是真正的"最优"，只是 guardrail 评估指标本身的 trade-off：bond 路径波动小 → 消费很少跌破 50% 起始线（因为起始线本身就低）**。

如果改按 composite 排序 per-scenario，USA 1900 45y 最优变回 **50/40/10**（init_SWR=4.12%, eff_FR=0.976, P10_wd=$26,665），与 v1 fixed 的 50/50/00 高度近邻。

## 5. 杠杆 1.0 vs 1.2

| Country | leverage | best alloc (by eff_FR) | init_SWR | eff_FR | P10_min_wd | yrs<floor |
|---|---|---|---|---|---|---|
| ALL | 1.0 | 20/70/10 | 3.45% | 0.968 | $20,802 | 1.4 |
| ALL | 1.2 | 30/70/00 | 2.94% | 0.954 | $18,914 | 2.0 |
| USA | 1.0 | 00/00/100 | 1.66% | 0.996 | $11,546 | 0.2 |
| USA | 1.2 | 00/00/100 | 1.37% | 0.992 | $9,063 | 0.4 |

1.2x 杠杆全面拉低 SWR / eff_FR / P10_wd，且 `yrs<floor` 增加（消费被削减的年数变多）。**与 v1 fixed 一致：杠杆 1.0 最优**。

## 6. 数据源 / 跨国比较（按 composite 视角应主要看 v1，本次仅看 trend）

- JST-USA vs FIRE_dataset-USA：在 guardrail 下两者 eff_FR 都接近 1.0，差异不大；但 JST 推荐 70% Intl + 30% Bond，FIRE 推荐 40% Intl + 60% Bond——这反映两数据源里 stock 序列波动差异。
- 跨国（CHE/AUS/JPN/DEU）：与 v1 fixed 的国家偏好一致——历史强国（AUS/USA）偏 Dom，弱国（CHE/JPN/DEU）偏 Intl 分散。

## 7. 关键洞察

### 7.1 Guardrail 不改变最优配置（综合视角下）
- 综合 eff_FR + SWR + P10_min_wd 后，top 10 alloc 与 v1 fixed 几乎重叠。
- **`guardrail-allocation-leverage-sweep` Memory 里 "effFR 局限" 提醒在这里再次得到验证**：单一 eff_FR 在 guardrail 下系统性偏向 bond-heavy。

### 7.2 Guardrail 的真实价值不在改变 alloc，而在改善路径稳定性
- 同 alloc 下，guardrail 的 init_SWR = fixed @ target=0.85 的 SWR（数学等价）。
- 真正改善的是：当模拟路径走差时，动态削减消费 → 避免完全归零 → eff_FR 比同 alloc fixed 的 FR 高几个 pp。
- 代价：P10 路径有 ~1 年消费 < 50% 起始 wd。
- **对中国居民含义**：30/60/10 alloc + target=0.85 guardrail 在 JST ALL pool 45y 下，init_SWR=3.45%（比 v1 fixed @ 4% rule 保守），但 eff_FR=0.968、yrs<floor=1.4 年——可以承担 4 年最差消费仍然不破产。

### 7.3 `target=0.85` 比 [Memory: guardrail-optimal-params-v2] 保守档（0.95）激进
- target=0.85 让 init_SWR 提升（更多消费），但 path 中触发 lower_guardrail 概率更高、削减更频繁。
- 与 v2 保守档 (target=0.95) 比，本次的 P10_min_wd 和 yrs<floor 都更差（v2 的 amount/mr=1 配 0.95 target，几乎不削减消费）。
- 选 target=0.85 还是 0.95 取决于偏好：高目标 success（0.95）→ 起始消费低但路径稳；低目标（0.85）→ 起始消费高但路径波动大。
- **本次结论不替换 v2 保守档建议**——v2 仍是 [user-investment-profile] 的首选。

### 7.4 不要盲信单一指标
- 单按 `eff_FR` 选 alloc → 推荐 100% bond → init_SWR 1.5-2% → 实际消费水平远低于 stock-heavy 的可承受范围。
- 单按 `init_SWR` 选 alloc → 推荐 40-50/50-60/0 → 路径波动大，P10 路径年消费可能跌到 50% 以下数年。
- 综合 (eff_FR + P10 + SWR) 才能给出有意义的 trade-off。**这是 guardrail 分析方法学层面的关键启示**。

## 8. 推荐组合（按需求场景）

### 8.1 综合稳健（target=0.85）
**30/60/10** — composite 排名第一；mean init_SWR 3.83%, mean P10_wd $24.8k, mean eff_FR 0.976, mean yrs<floor 1.1。

### 8.2 中国居民 IB 投资版（参考 [user-investment-profile] + 本次 ALL pool 视角）
- **A 股+港股 25% + VT 60% + 短债+TIPS 15%**（基本 = 25/60/15，与 30/60/10 接近）。
- 用 guardrail target=0.85：1M USD 时年初 wd ~ $34,500（3.45% SWR for ALL pool 45y），路径中可能被削减到 ~$17,000 (50% floor) 1-2 年。
- 用 guardrail target=0.95（v2 保守档）：年初 wd ~ $25,000（2.5% SWR）但削减极少。
- 二者权衡：**高消费但波动 vs 低消费但稳定**。

### 8.3 切不要在 guardrail 下推 100% Bond
- USA 100% bond 在 target=0.85 下 init_SWR 仅 1.66%（年 wd $16,600 on $1M），P10_wd $11,546——退休生活质量远低于 stock-heavy alloc 的可承受下限。
- 单一 eff_FR 视角下"100% bond 最优"是评估指标人为造成的假象。

## 9. 与 Memory 的关系

| Memory | 本次验证 |
|---|---|
| `guardrail-optimal-params-v2` 保守档 target=0.95 | ✅ target=0.85 比保守档激进；本次不替换 v2 建议 |
| `guardrail-allocation-leverage-sweep` effFR 局限 | ✅ 单一 eff_FR 在 guardrail 下严重偏向 bond，必须综合 SWR + P10 看 |
| `feedback-dom-global-perspective` 中国居民 Dom ≤ 25% | ✅ JST ALL pool composite top alloc Dom 20-40%，可控 |
| `user-investment-profile` IB 投资 | ✅ 30/60/10 与该 profile 推荐基本对齐 |

## 10. 局限

- 单一 guardrail 参数组（target=0.85）；不同 target/adj 会换排名（详见 [Memory: guardrail-optimal-params-v2] 的 3000-grid 研究）。
- num_sims=2000，guardrail 路径细节噪声 ~1-2pp eff_FR；如做 PR 级决策应跑 5000+。
- 仍未含 cash flow / housing。
- composite ranking 用 equal-weight 三个指标；不同 utility function 会给不同排名（如对消费下限极度厌恶的投资者应给 P10 更高权重）。
- `eff_FR` 用 `consumption_floor=0.5`（50% 初始 wd），floor 设置影响排名；试 0.3 / 0.7 会换结果。
- target=0.85 下 USA 1900 60y 100% bond init_SWR 才 1.23%——已经接近"养老金水平"，不应作为合理推荐。
