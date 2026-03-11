"""自定义现金流数据结构与辅助函数。

用户可添加多个收入/支出现金流，指定起始年、持续年数和是否通胀调整。
支持概率分组：同一 group 内的现金流互斥，每次 MC 模拟按概率权重随机选一个。
在模拟中，现金流会按年应用到资产组合中。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np


@dataclass
class CashFlowItem:
    """单个自定义现金流条目。

    Attributes
    ----------
    name : str
        描述性名称（如 "社保收入"、"房贷支出"）。
    amount : float
        金额。正数 = 收入，负数 = 支出。
        通胀调整时为 year-0 实际购买力美元；
        非通胀调整时为固定名义美元。
    start_year : int
        从退休第几年开始（1-indexed，1 = 退休第一年）。
    duration : int
        持续年数。
    inflation_adjusted : bool
        是否按通胀调整（默认 True）。
        True: 金额维持实际购买力不变（year-0 美元）。
        False: 金额为固定名义值，实际购买力随通胀递减。
    growth_rate : float
        年度复合增长率（默认 0.0）。
        inflation_adjusted=True 时：实际增长率（超越通胀的额外增长，如医疗 2%）。
        inflation_adjusted=False 时：名义增长率（如租金每年涨 3%）。
    probability : float
        组内概率权重 (0, 1]。仅在 group 非 None 时有意义。
    group : str or None
        互斥组名。同一 group 内的现金流互斥，每次模拟只选一个变体。
        同一 group 内 name 相同的条目构成一个"变体"，被整体选中。
        None 表示确定事件（100% 发生）。
    """

    name: str
    amount: float
    start_year: int
    duration: int
    inflation_adjusted: bool = True
    growth_rate: float = 0.0
    probability: float = 1.0
    group: str | None = None


def has_probabilistic_cf(cash_flows: list[CashFlowItem]) -> bool:
    """检查现金流列表中是否存在概率分组。"""
    return any(cf.group is not None for cf in cash_flows)


def _group_variants(
    cash_flows: list[CashFlowItem],
) -> tuple[list[CashFlowItem], dict[str, dict[str, list[CashFlowItem]]]]:
    """将现金流按 (group, name) 聚合为变体。

    同一 group 内 name 相同的多个条目构成一个"变体"，
    在概率采样时被整体选中或整体不选。

    Returns
    -------
    ungrouped : list[CashFlowItem]
        group=None 的确定性现金流。
    groups : dict[group_name, dict[variant_name, list[CashFlowItem]]]
        按组名 → 变体名 → 条目列表的嵌套字典。
    """
    ungrouped = [cf for cf in cash_flows if cf.group is None]
    groups: dict[str, dict[str, list[CashFlowItem]]] = {}
    for cf in cash_flows:
        if cf.group is not None:
            groups.setdefault(cf.group, {}).setdefault(cf.name, []).append(cf)
    return ungrouped, groups


def sample_cash_flows(
    cash_flows: list[CashFlowItem],
    rng: np.random.Generator,
) -> list[CashFlowItem]:
    """按概率分组采样活跃现金流。

    - group=None 的现金流：直接纳入（确定事件）。
    - 同一 group 内按 name 聚合为变体，按 probability 权重随机选一个变体。
      同一变体的所有条目被整体选中。
      若组内概率总和 < 1，剩余概率表示"什么都不发生"。

    Parameters
    ----------
    cash_flows : list[CashFlowItem]
        完整的现金流列表（含所有组和非组项）。
    rng : np.random.Generator
        随机数生成器。

    Returns
    -------
    list[CashFlowItem]
        本次模拟中活跃的现金流子集。
    """
    ungrouped, groups = _group_variants(cash_flows)

    result = list(ungrouped)
    for variants in groups.values():
        variant_names = list(variants.keys())
        probs = [variants[vn][0].probability for vn in variant_names]
        total = sum(probs)
        n = len(variant_names)
        if total < 1.0:
            weights = probs + [1.0 - total]
            idx = int(rng.choice(n + 1, p=weights))
            if idx < n:
                result.extend(variants[variant_names[idx]])
        else:
            idx = int(rng.choice(n, p=probs))
            result.extend(variants[variant_names[idx]])

    return result


def build_expected_cf_schedule(
    cash_flows: list[CashFlowItem],
    retirement_years: int,
    inflation_series: np.ndarray | None = None,
) -> np.ndarray:
    """构建概率加权的期望现金流时间表，用于单条回测等确定性场景。

    - group=None 的现金流以 100% 权重计入。
    - 同一 group 内按 name 聚合为变体，每个变体以其 probability 权重计入。

    Parameters
    ----------
    cash_flows : list[CashFlowItem]
        完整的现金流列表（含所有组和非组项）。
    retirement_years : int
        退休总年数。
    inflation_series : np.ndarray or None
        年度通胀率数组，用于非通胀调整的现金流折算。

    Returns
    -------
    np.ndarray
        shape (retirement_years,) 的每年期望净现金流数组（实际购买力美元）。
    """
    ungrouped, groups = _group_variants(cash_flows)
    schedule = build_cf_schedule(ungrouped, retirement_years, inflation_series) if ungrouped else np.zeros(retirement_years)

    for variants in groups.values():
        for variant_items in variants.values():
            prob = variant_items[0].probability
            single = build_cf_schedule(variant_items, retirement_years, inflation_series)
            schedule += prob * single

    return schedule


def enumerate_cf_scenarios(
    cash_flows: list[CashFlowItem],
    max_combinations: int = 64,
) -> list[tuple[str, list[CashFlowItem], float]]:
    """枚举概率分组的所有确定性组合。

    每个组合是一种"如果 A 组选了变体 x，B 组选了变体 y …"的确定性场景。
    同一组内 name 相同的条目构成一个变体，被整体选中。
    确定性（group=None）现金流出现在每个场景中。

    Parameters
    ----------
    cash_flows : list[CashFlowItem]
        完整的现金流列表。
    max_combinations : int
        安全阀：组合数超过此值时返回空列表。

    Returns
    -------
    list[tuple[str, list[CashFlowItem], float]]
        每个元素为 (场景描述, 确定性现金流列表, 联合概率)。
        如果不存在概率分组，返回空列表。
    """
    ungrouped, groups = _group_variants(cash_flows)

    if not groups:
        return []

    group_options: list[list[tuple[str, list[CashFlowItem] | None, float]]] = []
    for group_name, variants in groups.items():
        total_prob = sum(items[0].probability for items in variants.values())
        options: list[tuple[str, list[CashFlowItem] | None, float]] = [
            (f"{group_name}: {vname}", vitems, vitems[0].probability)
            for vname, vitems in variants.items()
        ]
        if total_prob < 1.0 - 1e-9:
            options.append((f"{group_name}: (none)", None, 1.0 - total_prob))
        group_options.append(options)

    total_combos = 1
    for opts in group_options:
        total_combos *= len(opts)
        if total_combos > max_combinations:
            return []

    from itertools import product as itertools_product

    scenarios: list[tuple[str, list[CashFlowItem], float]] = []
    for combo in itertools_product(*group_options):
        label_parts = []
        active_cfs = list(ungrouped)
        joint_prob = 1.0
        for desc, cf_items, prob in combo:
            label_parts.append(desc)
            if cf_items is not None:
                active_cfs.extend(replace(cf, group=None) for cf in cf_items)
            joint_prob *= prob
        label = " + ".join(label_parts)
        scenarios.append((label, active_cfs, joint_prob))

    return scenarios


def enumerate_cf_per_group(
    cash_flows: list[CashFlowItem],
) -> list[tuple[str, list[CashFlowItem], float]]:
    """逐组独立枚举变体，其他组保持概率分布。

    用于组合数过多时的回退策略。对每个组 G 的每个变体 V，
    固定 V 为确定性事件，其他组保留概率分布（MC 模拟中正常采样）。
    同一组内 name 相同的条目构成一个变体。

    Parameters
    ----------
    cash_flows : list[CashFlowItem]
        完整的现金流列表。

    Returns
    -------
    list[tuple[str, list[CashFlowItem], float]]
        每个元素为 (场景描述, 现金流列表, 变体概率)。
        返回格式与 enumerate_cf_scenarios 一致。
        如果不存在概率分组，返回空列表。
    """
    ungrouped, groups = _group_variants(cash_flows)

    if not groups:
        return []

    scenarios: list[tuple[str, list[CashFlowItem], float]] = []
    for group_name, variants in groups.items():
        other_group_items = [
            cf for cf in cash_flows
            if cf.group is not None and cf.group != group_name
        ]

        for variant_name, variant_items in variants.items():
            active_cfs = (
                list(ungrouped)
                + [replace(cf, group=None) for cf in variant_items]
                + other_group_items
            )
            label = f"{group_name}: {variant_name}"
            scenarios.append((label, active_cfs, variant_items[0].probability))

        total_prob = sum(items[0].probability for items in variants.values())
        if total_prob < 1.0 - 1e-9:
            active_cfs = list(ungrouped) + other_group_items
            label = f"{group_name}: (none)"
            scenarios.append((label, active_cfs, 1.0 - total_prob))

    return scenarios


def build_representative_cf_schedule(
    cash_flows: list[CashFlowItem],
    retirement_years: int,
    inflation_matrix: np.ndarray | None = None,
) -> np.ndarray:
    """构建代表性现金流时间表，用于 3D 查找表构建。

    - 确定性通胀调整 CF：直接构建 schedule。
    - 名义 CF：使用 inflation_matrix 的中位数通胀率折算。
    - 概率分组 CF：使用概率加权的期望时间表。

    Parameters
    ----------
    cash_flows : list[CashFlowItem]
        完整的现金流列表。
    retirement_years : int
        退休总年数。
    inflation_matrix : np.ndarray or None
        shape (num_sims, retirement_years) 的通胀率矩阵。

    Returns
    -------
    np.ndarray
        shape (retirement_years,) 的代表性现金流时间表。
    """
    median_infl = None
    if inflation_matrix is not None:
        n = min(inflation_matrix.shape[1], retirement_years)
        median_infl = np.median(inflation_matrix, axis=0)[:n]
        if len(median_infl) < retirement_years:
            median_infl = np.pad(median_infl, (0, retirement_years - len(median_infl)))

    if has_probabilistic_cf(cash_flows):
        return build_expected_cf_schedule(cash_flows, retirement_years, median_infl)

    has_nominal = any(not cf.inflation_adjusted for cf in cash_flows)
    if has_nominal and median_infl is not None:
        return build_cf_schedule(cash_flows, retirement_years, median_infl)

    adj_cfs = [cf for cf in cash_flows if cf.inflation_adjusted]
    return build_cf_schedule(adj_cfs, retirement_years) if adj_cfs else np.zeros(retirement_years)


def build_cf_schedule(
    cash_flows: list[CashFlowItem],
    retirement_years: int,
    inflation_series: np.ndarray | None = None,
) -> np.ndarray:
    """构建每年的净现金流时间表（实际购买力）。

    Parameters
    ----------
    cash_flows : list[CashFlowItem]
        用户定义的现金流列表。
    retirement_years : int
        退休总年数。
    inflation_series : np.ndarray or None
        shape (retirement_years,) 的年度通胀率数组。
        仅当存在非通胀调整的现金流时需要提供。
        用于计算累计通胀因子以折算名义金额为实际购买力。

    Returns
    -------
    np.ndarray
        shape (retirement_years,) 的每年净现金流数组（实际购买力美元）。
        正数 = 净收入，负数 = 净支出。
    """
    schedule = np.zeros(retirement_years)

    if not cash_flows:
        return schedule

    # 预计算累计通胀因子（仅在需要时）
    cumulative_inflation: np.ndarray | None = None
    has_nominal = any(not cf.inflation_adjusted for cf in cash_flows)
    if has_nominal:
        if inflation_series is None:
            raise ValueError(
                "存在非通胀调整的现金流，但未提供 inflation_series"
            )
        # cumulative_inflation[t] = product(1 + inf[j] for j in 0..t)
        # 第 0 年的因子 = (1 + inf[0])，第 t 年 = product(1+inf[0..t])
        cumulative_inflation = np.cumprod(1.0 + inflation_series)

    for cf in cash_flows:
        # start_year 是 1-indexed，转换为 0-indexed
        start_idx = cf.start_year - 1
        end_idx = min(start_idx + cf.duration, retirement_years)

        if start_idx < 0 or start_idx >= retirement_years:
            continue

        if cf.inflation_adjusted:
            if cf.growth_rate == 0.0:
                schedule[start_idx:end_idx] += cf.amount
            else:
                for t in range(start_idx, end_idx):
                    schedule[t] += cf.amount * (1.0 + cf.growth_rate) ** (t - start_idx)
        else:
            if cumulative_inflation is None:
                raise ValueError("inflation_series is required for nominal (non-inflation-adjusted) cash flows")
            for t in range(start_idx, end_idx):
                nominal = cf.amount * (1.0 + cf.growth_rate) ** (t - start_idx)
                schedule[t] += nominal / cumulative_inflation[t]

    return schedule
