"""测试向量化版本与通用版本的数值等价性。

关键：run_simulation("fixed") 会自动 delegate 到 run_simulation_vectorized_fixed，
所以我们需要强制走通用路径来做真正的等价性比较。我们通过传入一个空现金流列表
（cash_flows=[]被视为无现金流所以走 vectorized，而传入一个值为0的 dummy CF 则
强制走 generic path）来实现这一点。
"""

import numpy as np
import pytest

from simulator.monte_carlo import run_simulation, run_simulation_vectorized_fixed
from simulator.cashflow import CashFlowItem
from simulator.data_loader import load_returns_by_source, get_country_dfs


def _run_generic_fixed(*, returns_df, seed, **params):
    """强制走 generic（非向量化）路径的 fixed 策略模拟。

    通过传入一个金额为 0、覆盖全时段的 dummy 现金流，
    使 can_use_vectorized 判断为 False，但不影响模拟结果。
    """
    dummy_cf = [CashFlowItem(
        name="dummy", amount=0.0, start_year=0, duration=1,
        inflation_adjusted=True,
    )]
    traj, wd, ret, inf = run_simulation(
        **params,
        returns_df=returns_df,
        seed=seed,
        withdrawal_strategy="fixed",
        cash_flows=dummy_cf,
    )
    return traj, wd, ret, inf


class TestVectorizationEquivalence:
    """确保向量化版本产生与通用版本一致的结果。"""

    @pytest.fixture(scope="class")
    def usa_data(self):
        df = load_returns_by_source("jst")
        return df[df["Country"] == "USA"].reset_index(drop=True)

    @pytest.fixture(scope="class")
    def country_dfs(self):
        df = load_returns_by_source("jst")
        return get_country_dfs(df, data_start_year=1900)

    def test_fixed_strategy_equivalence_single_country(self, usa_data):
        """测试单国场景下，vectorized 与 generic 路径结果一致。"""
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            "retirement_years": 30,
            "min_block": 5,
            "max_block": 15,
            "num_simulations": 50,
        }

        # 向量化版本
        traj_vec, wd_vec, ret_vec, inf_vec = run_simulation_vectorized_fixed(
            **params, returns_df=usa_data, seed=42,
        )

        # 通用版本（强制走 generic path）
        traj_gen, wd_gen, ret_gen, inf_gen = _run_generic_fixed(
            **params, returns_df=usa_data, seed=42,
        )

        # bootstrap 样本相同（相同 seed），回报矩阵应一致
        np.testing.assert_array_almost_equal(ret_vec, ret_gen, decimal=10)
        np.testing.assert_array_almost_equal(inf_vec, inf_gen, decimal=10)

        # 轨迹和提取额应一致
        np.testing.assert_array_almost_equal(traj_vec, traj_gen, decimal=6)
        # generic path 的 wd 包含了 dummy CF 的影响（cf_schedule[year] < 0 时加回），
        # 但 dummy CF 金额为 0 所以不影响
        for i in range(len(wd_vec)):
            for year in range(params["retirement_years"]):
                if wd_vec[i, year] > 0:
                    assert abs(wd_vec[i, year] - wd_gen[i, year]) < 1e-6

    def test_fixed_strategy_equivalence_multi_country(self, country_dfs):
        """测试多国池化场景下的等价性。"""
        df = load_returns_by_source("jst")
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            "retirement_years": 30,
            "min_block": 5,
            "max_block": 15,
            "num_simulations": 30,
            "country_dfs": country_dfs,
        }

        traj_vec, wd_vec, ret_vec, inf_vec = run_simulation_vectorized_fixed(
            **params, returns_df=df.head(1), seed=123,
        )
        traj_gen, wd_gen, ret_gen, inf_gen = _run_generic_fixed(
            **params, returns_df=df.head(1), seed=123,
        )

        np.testing.assert_array_almost_equal(ret_vec, ret_gen, decimal=10)
        np.testing.assert_array_almost_equal(traj_vec, traj_gen, decimal=6)

    def test_vectorized_bankruptcy_handling(self, usa_data):
        """测试破产场景下向量化版本的正确性。"""
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 150_000,
            "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            "retirement_years": 20,
            "min_block": 5,
            "max_block": 15,
            "num_simulations": 50,
            "returns_df": usa_data,
            "seed": 77,
        }

        traj_vec, wd_vec, _, _ = run_simulation_vectorized_fixed(**params)

        # 确保至少有一些破产发生
        has_bankruptcy = False
        for i in range(len(traj_vec)):
            bankruptcy_year = None
            for year in range(params["retirement_years"] + 1):
                if traj_vec[i, year] == 0 and year > 0:
                    bankruptcy_year = year
                    break

            if bankruptcy_year is not None:
                has_bankruptcy = True
                assert np.all(traj_vec[i, bankruptcy_year:] == 0), \
                    f"Sim {i}: Portfolio should stay 0 after bankruptcy at year {bankruptcy_year}"
                if bankruptcy_year < params["retirement_years"]:
                    assert np.all(wd_vec[i, bankruptcy_year:] == 0), \
                        f"Sim {i}: Withdrawals should be 0 after bankruptcy"

        assert has_bankruptcy, "Expected at least some bankruptcies with 15% withdrawal rate"

    def test_vectorized_success_rate_consistency(self, usa_data):
        """测试向量化版本的成功率在合理范围内。"""
        traj_vec, _, _, _ = run_simulation_vectorized_fixed(
            initial_portfolio=1_000_000,
            annual_withdrawal=40_000,
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=200,
            returns_df=usa_data,
            seed=88,
        )

        success_rate = (traj_vec[:, -1] > 0).sum() / len(traj_vec)
        # 4% rule over 30 years should have ~85-98% success rate
        assert 0.80 <= success_rate <= 1.0, \
            f"Success rate {success_rate:.1%} outside expected range [80%, 100%]"

    def test_withdrawal_amount_correctness(self, usa_data):
        """测试fixed策略的提取金额是否正确。"""
        annual_wd = 35_000
        _, wd_vec, _, _ = run_simulation_vectorized_fixed(
            initial_portfolio=1_000_000,
            annual_withdrawal=annual_wd,
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=20,
            returns_df=usa_data,
            seed=55,
        )

        for i in range(len(wd_vec)):
            for year in range(30):
                if wd_vec[i, year] > 0:
                    assert abs(wd_vec[i, year] - annual_wd) < 1e-6, \
                        f"Withdrawal in year {year} should be {annual_wd}, got {wd_vec[i, year]}"
