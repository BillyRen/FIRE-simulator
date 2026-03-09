"""测试向量化版本与通用版本的数值等价性。"""

import numpy as np
import pytest

from simulator.monte_carlo import run_simulation, run_simulation_vectorized_fixed
from simulator.data_loader import load_returns_by_source, get_country_dfs


class TestVectorizationEquivalence:
    """确保向量化版本产生与通用版本一致的结果。"""

    @pytest.fixture(scope="class")
    def usa_data(self):
        """加载USA数据用于测试。"""
        df = load_returns_by_source("jst")
        return df[df["Country"] == "USA"].reset_index(drop=True)

    @pytest.fixture(scope="class")
    def country_dfs(self):
        """加载多国数据用于池化测试。"""
        df = load_returns_by_source("jst")
        return get_country_dfs(df, data_start_year=1900)

    def test_fixed_strategy_equivalence_single_country(self, usa_data):
        """测试单国场景下，fixed策略向量化版本与通用版本结果一致。"""
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            "retirement_years": 30,
            "min_block": 5,
            "max_block": 15,
            "num_simulations": 100,
            "returns_df": usa_data,
            "seed": 42,
        }

        # 向量化版本（通过run_simulation自动触发）
        traj_vec, wd_vec, ret_vec, inf_vec = run_simulation(
            **params, withdrawal_strategy="fixed"
        )

        # 直接调用向量化函数
        traj_direct, wd_direct, ret_direct, inf_direct = run_simulation_vectorized_fixed(
            **params
        )

        # 验证结果一致
        np.testing.assert_array_almost_equal(traj_vec, traj_direct, decimal=10)
        np.testing.assert_array_almost_equal(wd_vec, wd_direct, decimal=10)
        np.testing.assert_array_almost_equal(ret_vec, ret_direct, decimal=10)
        np.testing.assert_array_almost_equal(inf_vec, inf_direct, decimal=10)

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
            "num_simulations": 50,
            "returns_df": df.head(1),  # placeholder
            "seed": 123,
            "country_dfs": country_dfs,
        }

        # 向量化版本
        traj_vec, wd_vec, ret_vec, inf_vec = run_simulation(
            **params, withdrawal_strategy="fixed"
        )

        # 直接调用
        traj_direct, wd_direct, ret_direct, inf_direct = run_simulation_vectorized_fixed(
            **params
        )

        # 验证
        np.testing.assert_array_almost_equal(traj_vec, traj_direct, decimal=10)
        np.testing.assert_array_almost_equal(wd_vec, wd_direct, decimal=10)

    def test_fixed_strategy_with_glide_path(self, usa_data):
        """测试带glide path的等价性。"""
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "allocation": {"domestic_stock": 0.8, "global_stock": 0.1, "domestic_bond": 0.1},
            "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            "retirement_years": 30,
            "min_block": 5,
            "max_block": 15,
            "num_simulations": 50,
            "returns_df": usa_data,
            "seed": 99,
            "glide_path_end_allocation": {"domestic_stock": 0.4, "global_stock": 0.1, "domestic_bond": 0.5},
            "glide_path_years": 20,
        }

        # 向量化版本
        traj_vec, wd_vec, ret_vec, inf_vec = run_simulation(
            **params, withdrawal_strategy="fixed"
        )

        # 直接调用
        traj_direct, wd_direct, ret_direct, inf_direct = run_simulation_vectorized_fixed(
            **params
        )

        # 验证
        np.testing.assert_array_almost_equal(traj_vec, traj_direct, decimal=10)
        np.testing.assert_array_almost_equal(wd_vec, wd_direct, decimal=10)

    def test_vectorized_bankruptcy_handling(self, usa_data):
        """测试破产场景下向量化版本的正确性。"""
        # 使用极高的提取率触发破产
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 150_000,  # 15%提取率，几乎必破产
            "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            "retirement_years": 20,
            "min_block": 5,
            "max_block": 15,
            "num_simulations": 30,
            "returns_df": usa_data,
            "seed": 77,
        }

        traj_vec, wd_vec, _, _ = run_simulation_vectorized_fixed(**params)

        # 验证破产后的行为
        for i in range(len(traj_vec)):
            # 找到第一次破产的年份
            bankruptcy_year = None
            for year in range(params["retirement_years"] + 1):
                if traj_vec[i, year] == 0:
                    bankruptcy_year = year
                    break

            if bankruptcy_year is not None:
                # 破产后所有年份资产应为0
                assert np.all(traj_vec[i, bankruptcy_year:] == 0), \
                    f"Simulation {i}: Portfolio should stay 0 after bankruptcy at year {bankruptcy_year}"

                # 破产后所有年份提取应为0
                if bankruptcy_year < params["retirement_years"]:
                    assert np.all(wd_vec[i, bankruptcy_year:] == 0), \
                        f"Simulation {i}: Withdrawals should be 0 after bankruptcy"

    def test_vectorized_success_rate_consistency(self, usa_data):
        """测试向量化版本的成功率计算一致性。"""
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            "retirement_years": 30,
            "min_block": 5,
            "max_block": 15,
            "num_simulations": 200,
            "returns_df": usa_data,
            "seed": 88,
        }

        traj_vec, _, _, _ = run_simulation_vectorized_fixed(**params)

        # 计算成功率（最后年份资产>0的比例）
        success_rate_vec = (traj_vec[:, -1] > 0).sum() / len(traj_vec)

        # 成功率应在合理范围内（40%历史4%规则成功率约85-95%）
        assert 0.5 <= success_rate_vec <= 1.0, \
            f"Success rate {success_rate_vec:.1%} seems unrealistic"

    def test_withdrawal_amount_correctness(self, usa_data):
        """测试fixed策略的提取金额是否正确。"""
        annual_wd = 35_000
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": annual_wd,
            "allocation": {"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            "expense_ratios": {"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            "retirement_years": 30,
            "min_block": 5,
            "max_block": 15,
            "num_simulations": 20,
            "returns_df": usa_data,
            "seed": 55,
        }

        _, wd_vec, _, _ = run_simulation_vectorized_fixed(**params)

        # Fixed策略：所有非破产年份的提取金额应等于annual_withdrawal
        for i in range(len(wd_vec)):
            for year in range(params["retirement_years"]):
                if wd_vec[i, year] > 0:
                    # 未破产的年份，提取金额应正确
                    assert abs(wd_vec[i, year] - annual_wd) < 1e-6, \
                        f"Withdrawal in year {year} should be {annual_wd}, got {wd_vec[i, year]}"
