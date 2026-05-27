# Guardrail × Allocation 扩展分析计划（2026-05-27）

> 在 `docs/optimal-allocation-plan-2026-05-27.md` 的基础上，把 `withdrawal_strategy=fixed/declining/smile` 替换成 risk-based guardrail，固定参数：**target=0.85 / up=0.99 / lo=0.70 / adj=0.10 / mode=amount / min_remaining_years=5**。目标：看护栏下最优配置是否相对 v1 fixed 结论发生 shift。

## 1. 算法差异

`sweep_allocations` 不支持 guardrail，因此自己写一个等价的 alloc 循环：

```
for alloc in 66 grid:
    nominal = alloc · raw_per_asset
    real_returns = nominal_to_real(nominal, inflation, leverage)
    rate_grid, table = build_success_rate_table(real_returns)
    init_p, init_wd, traj, wds = run_guardrail_simulation(
        scenarios=real_returns, target_success=0.85,
        upper_guardrail=0.99, lower_guardrail=0.70,
        adjustment_pct=0.10, adjustment_mode="amount",
        min_remaining_years=5, retirement_years=Y,
        table=table, rate_grid=rate_grid,
        initial_portfolio=1_000_000,    # 反推 init_wd
    )
    metrics = (init_wd/init_p,            # 起始 SWR @ target=0.85
               compute_effective_funded_ratio(...),  # eff FR/SR
               cvar_10(traj[:,-1]),
               p10_min_wd, median_total_consumption, ...)
```

要点：
- **`input_mode = "portfolio"`**（给 1M，反推 init_wd），让每个 alloc 都对齐到 target=0.85。这是 guardrail 分析的标准做法，比固定 WR 更公平：rank 直接反映各 alloc 在同样安全度下能承受的最高消费。
- 用 `compute_effective_funded_ratio` 而非传统 funded_ratio——guardrail 会通过削减消费"假活"，传统 FR 偏乐观（[Memory: guardrail-allocation-leverage-sweep] 的 effFR 局限）。
- `build_success_rate_table` 必须在 alloc 循环内重建（依赖 alloc-specific real_returns）。

## 2. 维度（剪枝后）

| 维度 | 取值 | 说明 |
|---|---|---|
| `data_source` | jst, fire_dataset | FIRE_dataset 只 USA |
| `country` | USA, ALL(gdp_sqrt), 跨国: CHE/AUS/JPN/DEU | |
| `data_start_year` | 1900, 1970 | |
| `retirement_years` | 30, 45, 60 | |
| `allocation_step` | 0.1 | 66 alloc |
| `leverage` | 1.0, 1.2 | 子集 |
| **Guardrail 参数** | 单一组合 | target=0.85/up=0.99/lo=0.70/adj=0.10/amount/mr=5 |
| **WR 维度** | 不需要 | guardrail 从 target 反推 init_wd |
| **strategy 维度** | 不需要 | 固定 guardrail |

剪枝同 v1：
- FIRE_dataset 只 USA，仅 1900 + 1970 + 45y。
- 杠杆 1.2 仅 USA/ALL × 1900 × 45y。
- 跨国稳健性仅 1900 × 45y。

### 规模
- 主线：`{jst} × {USA, ALL} × {1900, 1970} × {30, 45, 60}` = 12 scenarios。
- FIRE 补充：2 scenarios。
- 杠杆 1.2 补充：2 scenarios。
- 跨国：4 scenarios。
- **总计 20 scenarios × 66 alloc = 1320 个 guardrail 模拟**。
- 单次 `run_guardrail_simulation` (scalar Python loop, num_sims=2000, 45y) ≈ 0.3–0.8s → 总耗时预估 **8–18 分钟**。
- 如果太慢，砍 `retirement_years=60` 维度（只保留 30/45），或砍 `start_year=1970`。

## 3. 输出指标（每行）

| 指标 | 含义 |
|---|---|
| `initial_swr` | `init_wd / 1,000,000`（guardrail 在 target=0.85 下反推的起始提取率） |
| `success_rate` | `compute_success_rate(traj, retirement_years)` — `depletion_year >= retirement_years` 视为成功（与 v1 / 现有 `compute_success_rate` 对齐，last-year 破产仍算成功），避免与 v1 `funded_ratio`/`success_rate` 不可比 |
| `eff_success_rate` | 加入消费地板 = max(50% initial_wd) 的等效成功率 |
| `eff_funded_ratio` | 等效 FR |
| `median_final` | trajectory[:,-1] 中位数 |
| `cvar_10_final` | 最差 10% 的 final value 均值 |
| `p10_min_wd` | 全模拟最低年消费的 P10（衡量"最差年的消费下限"） |
| `median_total_wd` | 中位数总消费 |
| `mean_years_below_floor` | 平均每路径有多少年消费 < 50% 初始 wd |
| `is_pareto` / `is_near_optimal` | 按 eff_funded_ratio × median_final 帕累托；near-opt 阈值=1pp eff_FR |

## 4. CSV 列
```
data_source, country, pooling, start_year, retirement_years, leverage,
domestic_stock, global_stock, domestic_bond,
initial_swr, success_rate, eff_success_rate, eff_funded_ratio,
median_final, cvar_10_final, p10_min_wd, median_total_wd,
mean_years_below_floor, is_pareto, is_near_optimal
```
落到 `analysis/output/optimal_allocation/guardrail_results.csv`。

## 5. 分析

1. **跨场景稳健排名（核心）** — 按 `eff_funded_ratio` rank（同 v1）；同时按 `initial_swr` rank（看哪个 alloc 在 target=0.85 下能撑最高 wd）。
2. **vs v1 fixed 对比** — 把 v1 的 fixed 最优 vs 本次 guardrail 最优做配对（同 country/start/years），看 top-1 alloc 是否变。
3. **消费稳定性** — `p10_min_wd` 和 `mean_years_below_floor`，看哪些 alloc 的消费序列更稳。
4. **杠杆/数据源/跨国** — 同 v1。

> **注**：本次 `initial_swr` 完全等价于在同 alloc 下 fixed 表对 target=0.85 反推的 SWR（因为 `run_guardrail_simulation` 当传 `initial_portfolio` 时用 `find_rate_for_target(table, target=0.85, years)` 反推 init_wd，正是 fixed-WR 表）。所以**不要把 `initial_swr` 解释为 "guardrail 相对 fixed 的 SWR 提升"**。Guardrail 的真正价值体现在 `eff_funded_ratio` / `p10_min_wd` / `cvar_10` 等"路径中后期 dynamic adjustment 改变结局"的指标上。如果想测真正的 SWR uplift，需要对 effective-success 做 root finding，那是另一个研究（不在本次范围）。

## 6. 实现步骤

1. `analysis/optimal_allocation_guardrail.py`
   - 同 v1 的 Scenario + Run 结构，移除 strategy/WR 维度。
   - 复用 `pregenerate_raw_scenarios`（每个 country/start/years 重建）+ `raw_to_combined`（每个 alloc 算 real_returns）+ `build_success_rate_table`（每 alloc 一张表）+ `run_guardrail_simulation`。
   - 用 `compute_effective_funded_ratio(consumption_floor=0.5)` 计算 eff_FR/SR；额外计算 cvar_10/p10_min_wd 等。
   - Pareto tie-break 用 `(-eff_FR, -median_final)`（v1 反馈）。
2. 跑：`python analysis/optimal_allocation_guardrail.py`，预期 < 20 min。
3. 写报告：`docs/optimal-allocation-guardrail-2026-05-27.md`。

## 7. 验证清单

- [ ] `raw_to_combined` 调用时**显式传 `borrowing_spread=0.02`**（默认 0.0，会少算 2pp 借贷成本，导致与 v1/API 不可比）。`leverage=1.0` 时该参数被忽略，无影响；`leverage=1.2` 时必传。
- [ ] `build_success_rate_table` 每个 alloc 重建（不能跨 alloc 共享）。
- [ ] guardrail 用 `input_mode="portfolio"`，固定 `initial_portfolio=1_000_000`，反推 init_wd。
- [ ] eff_FR 使用 `consumption_floor=0.5`、`trajectories=traj`（防 trajectories 归零情形被掩盖）。
- [ ] `min_remaining_years=5` 限制 guardrail 后期触发，与 [Memory: guardrail-optimal-params-v2] 习惯一致。
- [ ] Pareto tie-break 用 v1 已修复的方式（`-eff_FR, -median_final`）。

## 8. 已知限制

- **target=0.85 比 [Memory: guardrail-optimal-params-v2] 保守档（0.95）激进 10pp** — 这是用户指定。结论不能直接套用到 0.95 保守档。
- 仍未含 cash flow。
- num_sims=2000；guardrail 比 fixed 更依赖路径细节，尾部噪声可能放大；如需稳，跑 5000+。
- 不与 fixed 的 `funded_ratio` 直接比（量纲不同：fixed FR 包含完整 wd 路径，guardrail FR 包含被削后的"消费下限假活"）→ 对比时用 `initial_swr × eff_funded_ratio` 而非 FR。
- 杠杆 1.2 仍可能因借贷成本拉低 SWR；预期与 v1 一致，但仍验证。
