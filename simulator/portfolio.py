"""资产组合回报计算模块。"""

import numpy as np
import pandas as pd


def compute_real_portfolio_returns(
    sampled_returns: pd.DataFrame,
    allocation: dict[str, float],
    expense_ratios: dict[str, float],
) -> np.ndarray:
    """根据资产配置和费用率计算组合的实际回报率序列。

    计算公式：
    - 名义组合回报 = Σ allocation[asset] * (return[asset] - expense[asset])
    - 实际组合回报 = (1 + 名义组合回报) / (1 + 通胀) - 1

    Parameters
    ----------
    sampled_returns : pd.DataFrame
        由 block_bootstrap 生成的回报序列，
        包含 US Stock, International Stock, US Bond, US Inflation 列。
    allocation : dict
        资产配置比例，键为 "us_stock", "intl_stock", "us_bond"，值之和应为 1.0。
    expense_ratios : dict
        各资产对应的费用率，键同 allocation。

    Returns
    -------
    np.ndarray
        长度为 len(sampled_returns) 的实际（扣通胀）组合回报率数组。
    """
    # 将 dict 键映射到 DataFrame 列名
    asset_map = {
        "us_stock": "US Stock",
        "intl_stock": "International Stock",
        "us_bond": "US Bond",
    }

    # 计算名义加权回报（扣除各资产费用）
    nominal_return = np.zeros(len(sampled_returns))
    for asset_key, col_name in asset_map.items():
        weight = allocation.get(asset_key, 0.0)
        expense = expense_ratios.get(asset_key, 0.0)
        nominal_return += weight * (sampled_returns[col_name].values - expense)

    # 扣除通胀，得到实际回报
    inflation = sampled_returns["US Inflation"].values
    real_return = (1.0 + nominal_return) / (1.0 + inflation) - 1.0

    return real_return
