"""资产组合回报计算模块。"""

import numpy as np
import pandas as pd

from .bootstrap import IDX_DS, IDX_GS, IDX_DB, IDX_INF


def compute_real_portfolio_returns_np(
    data: np.ndarray,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
) -> np.ndarray:
    """Fast portfolio return calculation from numpy array (no DataFrame overhead).

    Parameters
    ----------
    data : np.ndarray
        shape (n, 4+) array with columns in RETURN_COLS order:
        [Domestic_Stock, Global_Stock, Domestic_Bond, Inflation, ...].
    allocation, expense_ratios, leverage, borrowing_spread :
        Same as compute_real_portfolio_returns().

    Returns
    -------
    np.ndarray
        Real portfolio returns, length n.
    """
    w_ds = allocation.get("domestic_stock", 0.0)
    w_gs = allocation.get("global_stock", 0.0)
    w_db = allocation.get("domestic_bond", 0.0)
    e_ds = expense_ratios.get("domestic_stock", 0.0)
    e_gs = expense_ratios.get("global_stock", 0.0)
    e_db = expense_ratios.get("domestic_bond", 0.0)

    nominal_return = (
        w_ds * (data[:, IDX_DS] - e_ds)
        + w_gs * (data[:, IDX_GS] - e_gs)
        + w_db * (data[:, IDX_DB] - e_db)
    )

    inflation = data[:, IDX_INF]
    if leverage != 1.0:
        nominal_return = leverage * nominal_return - (leverage - 1.0) * (inflation + borrowing_spread)

    return (1.0 + nominal_return) / (1.0 + inflation) - 1.0


def compute_real_portfolio_returns(
    sampled_returns: pd.DataFrame,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
    leverage: float = 1.0,
    borrowing_spread: float = 0.0,
) -> np.ndarray:
    """根据资产配置和费用率计算组合的实际回报率序列。

    计算公式：
    - 名义组合回报 = Σ allocation[asset] * (return[asset] - expense[asset])
    - 若有杠杆：名义回报 = L * 名义回报 - (L-1) * (通胀 + 借贷利差)
    - 实际组合回报 = (1 + 名义组合回报) / (1 + 通胀) - 1

    Parameters
    ----------
    sampled_returns : pd.DataFrame
        由 block_bootstrap 生成的回报序列，
        包含 Domestic_Stock, Global_Stock, Domestic_Bond, Inflation 列。
    allocation : dict
        资产配置比例，键为 "domestic_stock", "global_stock", "domestic_bond"，值之和应为 1.0。
    expense_ratios : dict
        各资产对应的费用率，键同 allocation。
    leverage : float
        杠杆倍数，1.0 表示无杠杆。
    borrowing_spread : float
        借贷利差（实际利率），借贷成本 = 通胀 + 利差。

    Returns
    -------
    np.ndarray
        长度为 len(sampled_returns) 的实际（扣通胀）组合回报率数组。
    """
    # 将 dict 键映射到 DataFrame 列名
    asset_map = {
        "domestic_stock": "Domestic_Stock",
        "global_stock": "Global_Stock",
        "domestic_bond": "Domestic_Bond",
    }

    # 计算名义加权回报（扣除各资产费用）
    nominal_return = np.zeros(len(sampled_returns))
    for asset_key, col_name in asset_map.items():
        weight = allocation.get(asset_key, 0.0)
        expense = expense_ratios.get(asset_key, 0.0)
        nominal_return += weight * (sampled_returns[col_name].values - expense)

    # 杠杆计算
    inflation = sampled_returns["Inflation"].values
    if leverage != 1.0:
        borrowing_cost = inflation + borrowing_spread
        nominal_return = leverage * nominal_return - (leverage - 1.0) * borrowing_cost

    # 扣除通胀，得到实际回报
    real_return = (1.0 + nominal_return) / (1.0 + inflation) - 1.0

    return real_return
