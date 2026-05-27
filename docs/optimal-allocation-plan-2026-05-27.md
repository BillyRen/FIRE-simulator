# 最优资产配置分析计划（v1，2026-05-27）

## 1. 目标
基于 `sweep_allocations` 算法，跨"数据源 × 起始年份 × 国家 × 提取策略 × 初始提取率 × 提取时长（× 杠杆）"的多维网格，找出在多数情境下都接近最优、且对参数变化稳健的资产配置组合，并提炼跨维度洞察。

## 2. 复用与扩展

### 复用
- `simulator.sweep.pregenerate_raw_scenarios` —— 一次 bootstrap，多次扫描，避免重复抽样。
- `simulator.sweep.sweep_allocations(allocation_step)` —— 已向量化的 fixed/declining/smile 路径。
- `simulator.statistics.compute_funded_ratio` / `compute_success_rate` / CVaR 计算（向量化）。
- Pareto frontier 逻辑：`success_rate / funded_ratio` 与 `median_final` 双目标。

### 不复用 / 新增
- guardrail 策略不走 `sweep_allocations`（它只支持 fixed/dynamic/declining/smile）。Guardrail 在敏感性附录里用 `simulator.guardrail.run_guardrail_simulation` 单独跑一个小网格（基线参数 = [Memory] `guardrail-optimal-params-v2` 保守档：target=0.95/up=0.99/lo=0.80/adj=0.05/amount/mr=1）。
- 计算 effective funded ratio（带消费下限）与名义 funded ratio 两套指标，便于复核 [Memory] 中"effFR 局限"提示。

## 3. 维度（笛卡尔积版本，先列后剪枝）

| 维度 | 取值 | 说明 |
|---|---|---|
| `data_source` | `jst`, `fire_dataset` | FIRE_dataset 仅 USA，长序列；JST 多国 1871-2025 |
| `country` | `USA`, `ALL`(gdp_sqrt) | 主线两值；附录加 `CHE`/`AUS`/`JPN`/`DEU` 做稳健性 |
| `data_start_year` | `1900`, `1950`, `1970` | 1900 = 全样本；1970 = 现代金融体系；1950 = 战后 |
| `withdrawal_strategy` | `fixed`, `declining`, `smile` | dynamic 不向量化，太慢；guardrail 单独走 |
| `initial_wr` | `0.030`, `0.035`, `0.040`, `0.045` | 4% rule 上下覆盖 FIRE/传统区间 |
| `retirement_years` | `30`, `45`, `60` | 传统退休 30y / FIRE 基线 45y / 早退保守 60y |
| `allocation_step` | `0.1` | 66 个 (US, Intl, Bond) 组合 |
| `leverage` | `1.0`, `1.2` | 基线无杠杆 + 一档轻度杠杆做参考 |
| `pooling_method` | `gdp_sqrt` | country=ALL 时固定，避免组合爆炸 |
| `min_block / max_block` | `5 / 15` | 与默认一致 |
| `num_simulations` | `2_000` | 与现有 allocation page 默认对齐，平衡精度/耗时 |
| `seed` | `42` | 单 seed；附录用 5 个 seed 验稳定性 |
| `expense_ratios` | 0.005 全资产 | 默认 |

### 剪枝（主网格）
丢弃以下组合以控总量：
- `fire_dataset` 只跑 `country=USA`（数据源限制）。
- `start_year=1950` 仅跑 `country=USA` × `strategy=fixed` × `wr=0.04` × `years=45`（作为补充时间窗）。
- `leverage=1.2` 仅跑 `country in {USA, ALL}` × `strategy=fixed` × `years=45` × 全部 wr（验杠杆效应）。

### 主网格规模估算
- 主线：`{jst} × {USA, ALL} × {1900, 1970} × {fixed, declining, smile} × {0.030, 0.035, 0.040, 0.045} × {30, 45, 60}` = 1×2×2×3×4×3 = **144 个 sweep**。
- 每个 sweep = 66 alloc × 2000 sims × N 年，向量化约 0.5–1.5s。总耗时预估 **2–4 分钟**（向量化 fast path）。
- FIRE_dataset 补充：`{USA} × {1900, 1970} × {fixed} × {0.030, 0.035, 0.040, 0.045} × {45}` = 8 个 sweep。
- 杠杆补充：`{1.2} × {USA, ALL} × {fixed} × {0.030, 0.035, 0.040, 0.045} × {45}` = 8 个 sweep。
- 跨国稳健性：`{jst} × {CHE, AUS, JPN, DEU} × {1900} × {fixed} × {0.040} × {45}` = 4 个 sweep。
- Guardrail 附录：4 个 sweep（country × start_year，固定保守参数）。
- **总计 ≈ 168 sweeps，约 5–10 分钟可跑完**。

## 4. 输出指标（每行）

| 指标 | 含义 | 来源 |
|---|---|---|
| `success_rate` | 完整退休期不破产比例（last-year 破产仍算成功） | `compute_success_rate` |
| `funded_ratio` | 平均资金充足度 | `compute_funded_ratio` |
| `cvar_10` | 最差 10% 路径的平均最终值 | 现有 `AllocationResult.cvar_10` |
| `median_final`, `p10_final`, `p90_final` | 最终价值分位 | 现有 |
| `p10_depletion_year` | 第 10 分位破产年份 | 现有 |
| `is_pareto` | 在 funded_ratio × median_final 上是否帕累托最优 | 现有 |

## 5. CSV 数据模型（长表）
```
data_source, country, pooling, start_year, retirement_years, strategy,
initial_wr, leverage, us_stock, intl_stock, us_bond,
success_rate, funded_ratio, cvar_10, median_final, p10_final, p90_final,
p10_depletion_year, is_pareto, is_near_optimal
```
落到 `analysis/output/optimal_allocation/results.csv`。

## 6. 分析（脚本会生成）

1. **跨场景稳健性排名（核心产出）**
   - 对每个 (source, country, start_year, strategy, wr, years) 场景按 `funded_ratio` 排序，给每个 alloc 一个 rank。
   - 跨所有场景求 `mean_rank` 和 `rank_std`，找出 "rank 持续靠前 + 波动小" 的组合 → 稳健推荐。
   - 同样跨场景统计 "进入 Pareto" 次数（`pareto_count`）和 "进入 near-optimal" 次数。

2. **场景化最优**
   - 每个场景 top-3 配置 + 与稳健推荐的差距。

3. **维度敏感性**
   - 固定其他变量，单独变化每个维度，画 `funded_ratio` 对 alloc 的 heatmap，看最优区域的位移幅度。

4. **杠杆/数据源/国家对比**
   - 1.0 vs 1.2 杠杆下最优区域漂移。
   - JST-USA vs FIRE_dataset-USA 最优区域差异（侧面验证数据源一致性）。
   - USA vs ALL pool 最优 stock 比例差异。

5. **与现有 Memory 推荐对齐**
   - 检查"中国居民 Dom ≤ 25%"建议是否与跨场景稳健最优一致（Memory：`feedback-dom-global-perspective`）。
   - 与 `guardrail-allocation-leverage-sweep` 中"杠杆=1.0 最优"的结论交叉验证。

## 7. 实现步骤

1. `analysis/optimal_allocation_v1.py`
   - 顶部统一参数表 + 维度组合生成。
   - 用 `pregenerate_raw_scenarios` 一次 bootstrap，再循环 strategy/wr/years/leverage 调 `sweep_allocations`。
     - 注意：start_year/country/data_source 变化时必须重新 bootstrap。
   - 输出 `results.csv` + `summary.md`（含 top-10 稳健配置、各维度敏感性）。
2. 运行：`python analysis/optimal_allocation_v1.py`，预期 < 10 min。
3. 写报告：`docs/optimal-allocation-analysis-2026-05-27.md`。

## 8. 验证清单（跑之前自检）

- [ ] `sweep_allocations` 对 `withdrawal_strategy="declining"/"smile"` 也透传了正确参数（confirmed in code review of `_sweep_single_allocation`）。
- [ ] `pregenerate_raw_scenarios` 在 country/start_year 变化时被重建。
- [ ] FIRE_dataset 路径不会被错误传给 `country=ALL`。
- [ ] 输出 CSV 列与 `AllocationResult` schema 对齐。
- [ ] 单跑一个组合用例做 sanity check（与 `/api/allocation-sweep` 输出比对）。

## 9. 已知限制（在报告里说明）
- `sweep_allocations` 把"年提取金额"作为 fixed/declining/smile 的基线，没有 guardrail 的动态上下限调整 → 不能完全替代消费下限保护的偏好分析。
- num_sims=2000 在尾部分位有 ~1pp success_rate 噪声；如果稳健排名结果两个组合 funded_ratio 差距 <1pp，需要补跑 10k。
- 现金流（pension / 育儿 / 房产）一律不开，避免与配置选择互相干扰。后续可专门跑一份"含现金流"的版本。
- Glide path 关闭：本次只看静态配置；动态滑路径单独研究。
- pooling_method 固定 `gdp_sqrt`，未对比 equal pooling 对配置最优的影响。

## 10. 交付
- `analysis/optimal_allocation_v1.py` 脚本。
- `analysis/output/optimal_allocation/results.csv` 全量长表。
- `docs/optimal-allocation-analysis-2026-05-27.md` 报告，含：
  1. 稳健推荐 1–3 个组合及理由。
  2. 跨数据源/国家/起始年/策略/提取率/年限的最优区域。
  3. 与已有 Memory 推荐（[user-investment-profile]、[guardrail-optimal-params-v2]、[guardrail-allocation-leverage-sweep]、[feedback-dom-global-perspective]）的差异与一致。
  4. 局限与下一步研究方向。
