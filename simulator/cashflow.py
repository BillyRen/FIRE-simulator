"""自定义现金流数据结构与辅助函数。

用户可添加多个收入/支出现金流，指定起始年、持续年数和是否通胀调整。
支持概率分组：同一 group 内的现金流互斥，每次 MC 模拟按概率权重随机选一个。
在模拟中，现金流会按年应用到资产组合中。
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    probability : float
        组内概率权重 (0, 1]。仅在 group 非 None 时有意义。
    group : str or None
        互斥组名。同一 group 内的现金流互斥，每次模拟只选一个。
        None 表示确定事件（100% 发生）。
    """

    name: str
    amount: float
    start_year: int
    duration: int
    inflation_adjusted: bool = True
    probability: float = 1.0
    group: str | None = None


def has_probabilistic_cf(cash_flows: list[CashFlowItem]) -> bool:
    """检查现金流列表中是否存在概率分组。"""
    return any(cf.group is not None for cf in cash_flows)


def sample_cash_flows(
    cash_flows: list[CashFlowItem],
    rng: np.random.Generator,
) -> list[CashFlowItem]:
    """按概率分组采样活跃现金流。

    - group=None 的现金流：直接纳入（确定事件）。
    - 同一 group 的现金流：按 probability 权重随机选一个。
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
    ungrouped = [cf for cf in cash_flows if cf.group is None]

    groups: dict[str, list[CashFlowItem]] = {}
    for cf in cash_flows:
        if cf.group is not None:
            groups.setdefault(cf.group, []).append(cf)

    result = list(ungrouped)
    for variants in groups.values():
        probs = [v.probability for v in variants]
        total = sum(probs)
        n = len(variants)
        if total < 1.0:
            weights = probs + [1.0 - total]
            idx = int(rng.choice(n + 1, p=weights))
            if idx < n:
                result.append(variants[idx])
        else:
            idx = int(rng.choice(n, p=probs))
            result.append(variants[idx])

    return result


def build_expected_cf_schedule(
    cash_flows: list[CashFlowItem],
    retirement_years: int,
    inflation_series: np.ndarray | None = None,
) -> np.ndarray:
    """构建概率加权的期望现金流时间表，用于单条回测等确定性场景。

    - group=None 的现金流以 100% 权重计入。
    - 同一 group 内的每个变体以其 probability 权重计入。

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
    ungrouped = [cf for cf in cash_flows if cf.group is None]
    schedule = build_cf_schedule(ungrouped, retirement_years, inflation_series) if ungrouped else np.zeros(retirement_years)

    groups: dict[str, list[CashFlowItem]] = {}
    for cf in cash_flows:
        if cf.group is not None:
            groups.setdefault(cf.group, []).append(cf)

    for variants in groups.values():
        for cf in variants:
            single = build_cf_schedule([cf], retirement_years, inflation_series)
            schedule += cf.probability * single

    return schedule


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
            # 实际购买力恒定，直接累加
            schedule[start_idx:end_idx] += cf.amount
        else:
            # 名义固定值，需折算为实际购买力
            # 实际值 = 名义值 / 累计通胀因子
            if cumulative_inflation is None:
                raise ValueError("inflation_series is required for nominal (non-inflation-adjusted) cash flows")
            for t in range(start_idx, end_idx):
                schedule[t] += cf.amount / cumulative_inflation[t]

    return schedule
