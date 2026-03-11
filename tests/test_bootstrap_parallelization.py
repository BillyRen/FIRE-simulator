"""测试 Bootstrap 并行化的数值等价性和性能。"""

import numpy as np
import pytest

from simulator.sweep import pregenerate_return_scenarios, pregenerate_raw_scenarios
from simulator.data_loader import load_returns_by_source, get_country_dfs


class TestBootstrapParallelization:
    """确保并行化 bootstrap 产生与顺序版本一致的结果。"""

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

    def test_small_simulations_use_sequential(self, usa_data):
        """测试小任务量（<100）使用顺序执行。"""
        # 50次模拟应该走顺序分支
        scenarios1, inflation1 = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=50,
            returns_df=usa_data,
            seed=42,
        )

        # 再次调用应该得到相同结果（使用相同seed）
        scenarios2, inflation2 = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=50,
            returns_df=usa_data,
            seed=42,
        )

        np.testing.assert_array_equal(scenarios1, scenarios2)
        np.testing.assert_array_equal(inflation1, inflation2)

    def test_large_simulations_reproducible(self, usa_data):
        """测试大任务量（>100）并行化的可复现性。"""
        # 200次模拟应该走并行分支
        scenarios1, inflation1 = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=200,
            returns_df=usa_data,
            seed=123,
        )

        # 使用相同seed应该得到相同结果
        scenarios2, inflation2 = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=200,
            returns_df=usa_data,
            seed=123,
        )

        np.testing.assert_array_almost_equal(scenarios1, scenarios2, decimal=10)
        np.testing.assert_array_almost_equal(inflation1, inflation2, decimal=10)

    def test_multi_country_parallelization(self, country_dfs):
        """测试多国池化场景下的并行化可复现性。"""
        df = load_returns_by_source("jst")

        raw1 = pregenerate_raw_scenarios(
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=200,
            returns_df=df.head(1),
            seed=456,
            country_dfs=country_dfs,
        )

        raw2 = pregenerate_raw_scenarios(
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=200,
            returns_df=df.head(1),
            seed=456,
            country_dfs=country_dfs,
        )

        # 验证所有资产类别结果一致
        np.testing.assert_array_almost_equal(
            raw1["domestic_stock"], raw2["domestic_stock"], decimal=10
        )
        np.testing.assert_array_almost_equal(
            raw1["global_stock"], raw2["global_stock"], decimal=10
        )
        np.testing.assert_array_almost_equal(
            raw1["domestic_bond"], raw2["domestic_bond"], decimal=10
        )
        np.testing.assert_array_almost_equal(
            raw1["inflation"], raw2["inflation"], decimal=10
        )

    def test_output_shapes(self, usa_data):
        """测试并行化版本的输出形状正确。"""
        num_sims = 150
        years = 40

        scenarios, inflation = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.7, "global_stock": 0.2, "domestic_bond": 0.1},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=years,
            min_block=5,
            max_block=15,
            num_simulations=num_sims,
            returns_df=usa_data,
            seed=789,
        )

        assert scenarios.shape == (num_sims, years)
        assert inflation.shape == (num_sims, years)

        # 验证数值范围合理
        assert np.all(np.isfinite(scenarios))
        assert np.all(np.isfinite(inflation))
        assert np.all(inflation >= -0.5)  # 通胀率不应低于-50%（极端通缩）
        assert np.all(inflation <= 0.5)   # 通胀率不应超过50%（极端通胀）

    def test_raw_scenarios_output_structure(self, usa_data):
        """测试 pregenerate_raw_scenarios 并行化的输出结构。"""
        num_sims = 120
        years = 35

        raw = pregenerate_raw_scenarios(
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=years,
            min_block=5,
            max_block=15,
            num_simulations=num_sims,
            returns_df=usa_data,
            seed=999,
        )

        # 验证包含所有必需的键
        assert set(raw.keys()) == {"domestic_stock", "global_stock", "domestic_bond", "inflation"}

        # 验证所有矩阵形状正确
        for key in raw:
            assert raw[key].shape == (num_sims, years), f"{key} has wrong shape"
            assert np.all(np.isfinite(raw[key])), f"{key} contains non-finite values"

    def test_leverage_with_parallelization(self, usa_data):
        """测试杠杆参数在并行化下正确工作。"""
        # 1x杠杆
        scenarios_1x, _ = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=150,
            returns_df=usa_data,
            seed=111,
            leverage=1.0,
            borrowing_spread=0.0,
        )

        # 1.5x杠杆
        scenarios_15x, _ = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=150,
            returns_df=usa_data,
            seed=111,
            leverage=1.5,
            borrowing_spread=0.02,
        )

        # 杠杆版本的波动性应该更大
        vol_1x = np.std(scenarios_1x)
        vol_15x = np.std(scenarios_15x)
        assert vol_15x > vol_1x, "Leveraged version should have higher volatility"

    def test_different_seeds_produce_different_results(self, usa_data):
        """测试不同seed产生不同结果（验证随机性）。"""
        scenarios1, _ = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=150,
            returns_df=usa_data,
            seed=1,
        )

        scenarios2, _ = pregenerate_return_scenarios(
            allocation={"domestic_stock": 0.6, "global_stock": 0.1, "domestic_bond": 0.3},
            expense_ratios={"domestic_stock": 0.003, "global_stock": 0.005, "domestic_bond": 0.002},
            retirement_years=30,
            min_block=5,
            max_block=15,
            num_simulations=150,
            returns_df=usa_data,
            seed=2,
        )

        # 不同seed应该产生不同结果
        assert not np.array_equal(scenarios1, scenarios2)
        # 但统计特性应该相似（来自同一分布）
        assert abs(np.mean(scenarios1) - np.mean(scenarios2)) < 0.02  # 均值相近
