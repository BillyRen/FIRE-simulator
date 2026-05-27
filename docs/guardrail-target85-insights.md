# `target=0.85` 时其他 5 个参数的最优洞察

**日期**: 2026-05-27
**Baseline**: JST Pool 1900+, 15/75/10, 50yr, $1M, no CFs, floor=0.50, 5-seed mean
**数据源**: `analysis/output/guardrail_v2/baseline_agg.csv` (600 configs at target=0.85)
**分析脚本**: `/tmp/target85_analysis.py`（探索性，未持久化）

---

## 0. TL;DR — 5 个关键洞察

1. **SWR 完全 fixed at 3.31%**：所有 600 configs 反算 SWR 都是 3.31%（这是 target=0.85 在 baseline scenarios 下的 SWR 表）。**所有 target=0.85 candidates 起点消费相同**，区别全在 path 调整与终值
2. **`mode × adj` 决定 effFR↔CEW trade-off**：amount + small adj → 高 effFR；success_rate + large adj → 高 CEW + 高 P10。两个极端互斥
3. **`lower` 呈"V 形"非单调**：lower=0.5-0.7 是 sweet spot；lower=0.1 太宽护栏不触发（effFR 低），lower=0.8 太窄触发过频繁削减消费过狠（CEW 低）
4. **`min_remaining_years` 是 noise**：mr ∈ {1, 3, 5, 10} 之间 effFR 差异 median 0.0005，max 0.0015。**保留 v1 的 mr=5 无害**，但选 mr=1 是数据最优
5. **`upper` 决定 CEW 收益**：upper=0.90 → 更频繁的 upper 触发 → 更多上调 wd → CEW $51K（最高）；upper=0.99 → 更少 upper 触发 → CEW $47K（最低）。但 effFR 反向（upper=0.99 → 0.950, upper=0.90 → 0.946）

---

## 1. SWR 在 target=0.85 全网格下固定为 3.31%

```
mean SWR across 600 target=0.85 configs: 3.311%
std deviation: 0.00 (literally zero)
```

**机理**: `find_rate_for_target(table, rate_grid, 0.85, 50yr) = 0.03311`，反算 SWR 只依赖 (target, scenarios, retirement_years)，不依赖 guardrail 参数。**所有 target=0.85 推荐起点 wd 完全相同**（$33,111 / $1M）。

→ 选 target=0.85 candidates 时**不需要看 SWR**——SWR 全相同，只看 effFR / CEW / P10 / 跨源 robust 的 trade-off。

---

## 2. mode × adj 的清晰 trade-off

5 seed 平均（gating 内 433 configs）：

| mode | adj | mean effFR | mean CEW |
|---|---:|---:|---:|
| amount | 0.05 | **0.966** ★ | $45,830 |
| amount | 0.10 | 0.960 | $47,838 |
| amount | 0.15 | 0.955 | $48,600 |
| amount | 0.20 | 0.950 | $49,156 |
| amount | 0.25 | 0.946 | $49,575 |
| success_rate | 0.05 | 0.949 | $49,069 |
| success_rate | 0.10 | 0.945 | $49,992 |
| success_rate | 0.15 | 0.940 | $50,536 |
| success_rate | 0.20 | 0.936 | $50,717 |
| success_rate | 0.25 | 0.932 | $50,770 ★ |

**模式**：
- 在每个 mode 内，**adj 越大 → effFR 越低、CEW 越高**（单调清晰）
- 跨 mode 比较：**同 adj 下，success_rate 的 CEW > amount + $1-3K，但 effFR < amount 0.015**
- 极值：
  - effFR-max → `amount + adj=0.05` (0.966)
  - CEW-max → `success_rate + adj=0.25` (但 baseline 不显示的 stress 崩塌已在 §JPN 验证暴露)

**Why amount/success_rate 区别**:
- `amount` mode 削减按 fixed dollar 步长 → 大幅 stress 时削减节奏可控 → effFR 高
- `success_rate` mode 削减按 success 距离比例 → stress 时削减过激 → wd 持续下滑 → 短期 CEW 看起来高但 stress 下崩塌

---

## 3. `lower` 呈非单调"V 形"

5 lower × 单独看（pool gating 内）：

| lower | n configs | mean effFR | mean CEW |
|:---:|---:|---:|---:|
| 0.10 | 30 | 0.947 | $47,543 |
| 0.20 | 48 | 0.949 | $48,068 |
| **0.50** | 116 | **0.950** ★ | **$49,736** ★ |
| 0.70 | 120 | 0.947 | $49,540 |
| 0.80 | 119 | 0.946 | $49,306 |

**模式**：lower=0.5 是 effFR 和 CEW 的双峰。

**Why**:
- `lower 太低` (0.1, 0.2)：护栏 lower 几乎从不触发 → 实际等同 fixed wd 策略 → 缺少下行保护 → effFR 略低
- `lower 中位` (0.5)：lower 触发频率适中 → 在真正 stress 时削减、其它时间维持 → 最佳 trade-off
- `lower 太高` (0.8)：lower 频繁触发 → 削减过频导致 wd 持续下滑 → CEW 略低

**注意**：5 candidate doc 中 B (lo=0.7) 和 D (lo=0.5) 看起来矛盾——但当我们 zoom out 到 robustness 维度（跨 4-source + 54-env）时，**B 的 lo=0.7 在 stress 下更稳健**（提前触发护栏避免 deep drawdown），D 的 lo=0.5 baseline CEW 高但 stress 下崩塌。

**结论**：baseline 数据 lo=0.5 略优，但稳健性维度 lo=0.7 优。

---

## 4. `upper` 决定 CEW 来自"上调"还是"不下调"

3 upper × 单独看：

| upper | n configs | mean effFR | mean CEW | mean effSR |
|:---:|---:|---:|---:|---:|
| **0.90** | 115 | 0.946 | **$51,290** ★ | 0.866 |
| 0.95 | 128 | 0.947 | $50,548 | 0.874 |
| **0.99** | 190 | **0.950** ★ | $47,088 | **0.882** ★ |

**模式**：upper 与 CEW 反向，与 effFR 正向。

**Why**:
- `upper=0.90`: 当 path 走得好时 success_rate 容易突破 0.90 → 触发 upper → 上调 wd → 中位路径 wd 拔高 → CEW 高
- `upper=0.99`: 几乎不触发 upper → 路径稳态 wd → CEW 低
- 但 upper 上调多了，路径未来 drawdown 风险升高 → effFR 略降

**结论**：
- 想要 CEW 高 → `upper=0.90`
- 想要 effFR 高（保本） → `upper=0.99`
- 平衡 → `upper=0.95`

---

## 5. `min_remaining_years` 是 noise（每个 fixed config 跨 mr 的差异）

固定 (upper, lower, adj, mode) 不变，看 mr ∈ {1, 3, 5, 10} 之间 effFR 的 range：

```
median range: 0.00046
P90 range:    0.00124
max range:    0.00150
```

**结论**：mr 在 target=0.85 baseline 下**实际影响 < 0.001 effFR**。

v1 的"保守取 mr=5"出于历史回测路径短的考虑，没问题；v2 数据最优是 mr=1，差异在显示精度内。**任何 mr 值都可以**。

---

## 6. lower × adj 二维 heatmap（mode=amount only）

`mean CEW` by (lower, adj):

| lower\adj | 0.05 | 0.10 | 0.15 | 0.20 | 0.25 |
|:---:|---:|---:|---:|---:|---:|
| 0.1 | $44,096 | $45,851 | $46,565 | $47,011 | $47,332 |
| 0.2 | $44,286 | $46,020 | $46,637 | $47,074 | $47,372 |
| **0.5** | $46,208 | **$48,311** | $49,322 | **$49,999** | **$50,415** ★ |
| 0.7 | $46,046 | $48,092 | $49,048 | $49,574 | $50,020 |
| 0.8 | $45,898 | $47,882 | $48,763 | $49,306 | $49,771 |

`mean effFR` by (lower, adj):

| lower\adj | 0.05 | 0.10 | 0.15 | 0.20 | 0.25 |
|:---:|---:|---:|---:|---:|---:|
| 0.1 | 0.956 | 0.956 | 0.955 | 0.954 | 0.953 |
| 0.2 | 0.960 | 0.959 | 0.957 | 0.957 | 0.955 |
| 0.5 | 0.964 | 0.960 | 0.957 | 0.952 | 0.949 |
| 0.7 | 0.967 | 0.961 | 0.954 | 0.947 | 0.944 |
| **0.8** | **0.968** ★ | 0.960 | 0.953 | 0.945 | 0.939 |

**两个 heatmap 的 ridge**：
- **CEW ridge**：`lower=0.5, adj=0.20-0.25` → CEW $50K+
- **effFR ridge**：`lower=0.7-0.8, adj=0.05` → effFR 0.967+
- **不存在 simultaneous optimum**——这印证 v2 主报告 §3.1 的 "effFR-robust ⊥ CEW-robust" 结论

---

## 7. 五个"哲学"参数集（target=0.85 内的代表性选择）

每个适配不同 user preference：

| 哲学 | 参数 | SWR | effFR | CEW | P10 wd | 评价 |
|---|---|---:|---:|---:|---:|---|
| 极致 funded ratio | `up=0.99 lo=0.80 adj=0.05 amount mr=1` | 3.31% | **0.970** | $43,985 | $27,913 | 高安全，低消费 |
| Legacy v1（B 候选） | `up=0.99 lo=0.70 adj=0.10 amount mr=5` | 3.31% | 0.962 | $45,590 | $28,686 | 平衡（推荐 SWR 3.31% 档） |
| 高 CEW amount（D 候选） | `up=0.90 lo=0.50 adj=0.15 amount mr=10` | 3.31% | 0.954 | $51,293 | $? | 高 CEW，4-src 边际 |
| 极致 CEW（dropped） | `up=0.90 lo=0.50 adj=0.25 success_rate mr=1` | 3.31% | 0.931 | **$53,979** | $33,105 | JPN 跌出 gating |
| 极致 P10（下行保护） | `up=0.99 lo=0.80 adj=0.25 success_rate mr=1` | 3.31% | 0.931 | $48,115 | **$36,280** | 最高下行保护，未验证 robustness |

---

## 8. 总结 & 应用建议

**在 target=0.85 这一类**（SWR 全部 3.31%）：

1. **不要看 SWR**——全相同
2. **看 mode**: success_rate CEW 高 ~5%，但 stress 下崩塌。**生产用 amount，CEW 极限场景才考虑 success_rate**
3. **看 adj**: 0.05-0.10 → effFR；0.20-0.25 → CEW。**没有同时最优**
4. **看 lower**: 0.5-0.7 是 sweet spot；0.1 和 0.8 极端都次优。**Legacy v1 的 lo=0.7 在 robustness 下胜过 baseline-optimal 的 lo=0.5**
5. **看 upper**: 0.90 → CEW 优先；0.99 → effFR 优先。0.95 是中庸
6. **不用看 mr**: 在 noise 内
7. **要看跨 4-source + 54-env 稳健性**: baseline-optimal ≠ robust-optimal。Legacy v1 (B) 是 robust 维度的隐藏赢家
