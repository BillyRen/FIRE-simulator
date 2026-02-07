"""自定义现金流数据结构与辅助函数。

用户可添加多个收入/支出现金流，指定起始年、持续年数和是否通胀调整。
在模拟中，现金流会按年应用到资产组合中。
"""

from dataclasses import dataclass

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
    """

    name: str
    amount: float
    start_year: int
    duration: int
    inflation_adjusted: bool = True


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
            assert cumulative_inflation is not None
            for t in range(start_idx, end_idx):
                schedule[t] += cf.amount / cumulative_inflation[t]

    return schedule
