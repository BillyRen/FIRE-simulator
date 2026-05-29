"""API endpoint integration tests using FastAPI TestClient."""

import json

import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path

# Ensure backend and simulator are importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from main import app


def parse_ndjson(response):
    """Parse NDJSON streaming response and return the result data."""
    for line in response.text.strip().split("\n"):
        if not line.strip():
            continue
        msg = json.loads(line)
        if msg.get("type") == "result":
            return msg["data"]
    raise ValueError("No result in streaming response")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """Disable slowapi rate limiting so tests can hit endpoints freely.

    Each route module owns its own Limiter instance; disable them all.
    """
    import main as main_module
    from routes import accumulation, buy_vs_rent, guardrail, sensitivity, simulate

    limiters = [
        main_module.limiter,
        accumulation.limiter,
        buy_vs_rent.limiter,
        guardrail.limiter,
        sensitivity.limiter,
        simulate.limiter,
    ]
    saved = [lim.enabled for lim in limiters]
    for lim in limiters:
        lim.enabled = False
    try:
        yield
    finally:
        for lim, was in zip(limiters, saved):
            lim.enabled = was


class TestHealthAndMeta:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_countries(self, client):
        r = client.get("/api/countries?data_source=jst")
        assert r.status_code == 200
        data = r.json()
        assert "countries" in data
        assert len(data["countries"]) > 0
        assert "iso" in data["countries"][0]

    def test_countries_fire_dataset(self, client):
        r = client.get("/api/countries?data_source=fire_dataset")
        assert r.status_code == 200
        countries = r.json()["countries"]
        assert any(c["iso"] == "USA" for c in countries)

    def test_historical_events(self, client):
        r = client.get("/api/historical-events")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_housing_countries(self, client):
        r = client.get("/api/buy-vs-rent/countries")
        assert r.status_code == 200
        assert "countries" in r.json()


class TestSimulation:
    BASE_PARAMS = {
        "initial_portfolio": 1_000_000,
        "annual_withdrawal": 40_000,
        "retirement_years": 30,
        "retirement_age": 65,
        "life_expectancy": 95,
        "allocation": {
            "domestic_stock": 0.6,
            "global_stock": 0.2,
            "domestic_bond": 0.2,
        },
        "expense_ratios": {
            "domestic_stock": 0.001,
            "global_stock": 0.002,
            "domestic_bond": 0.001,
        },
        "num_simulations": 100,
        "min_block": 3,
        "max_block": 10,
        "country": "USA",
        "data_source": "jst",
        "data_start_year": 1950,
        "withdrawal_strategy": "fixed",
        "leverage": 1.0,
        "borrowing_spread": 0.015,
        "cash_flows": [],
    }

    def test_simulate(self, client):
        r = client.post("/api/simulate", json=self.BASE_PARAMS)
        assert r.status_code == 200
        data = parse_ndjson(r)
        assert "success_rate" in data
        assert "funded_ratio" in data
        assert "percentile_trajectories" in data
        assert 0 <= data["success_rate"] <= 1

    def test_simulate_dynamic_strategy(self, client):
        params = {**self.BASE_PARAMS, "withdrawal_strategy": "dynamic",
                  "dynamic_ceiling": 0.1, "dynamic_floor": 0.05}
        r = client.post("/api/simulate", json=params)
        assert r.status_code == 200
        parse_ndjson(r)  # should not raise

    def test_simulate_invalid_allocation(self, client):
        params = {**self.BASE_PARAMS}
        params["allocation"] = {"domestic_stock": 0.5, "global_stock": 0.5, "domestic_bond": 0.5}
        r = client.post("/api/simulate", json=params)
        assert r.status_code == 400 or r.status_code == 422

    def test_simulate_all_countries(self, client):
        params = {**self.BASE_PARAMS, "country": "ALL", "pooling_method": "gdp_sqrt"}
        r = client.post("/api/simulate", json=params)
        assert r.status_code == 200
        parse_ndjson(r)  # should not raise


class TestSweep:
    def test_sweep(self, client):
        params = {
            "initial_portfolio": 1_000_000,
            "retirement_years": 30,
            "retirement_age": 65,
            "life_expectancy": 95,
            "allocation": {
                "domestic_stock": 0.6,
                "global_stock": 0.2,
                "domestic_bond": 0.2,
            },
            "expense_ratios": {
                "domestic_stock": 0.001,
                "global_stock": 0.002,
                "domestic_bond": 0.001,
            },
            "num_simulations": 100,
            "min_block": 3,
            "max_block": 10,
            "country": "USA",
            "data_source": "jst",
            "data_start_year": 1950,
            "withdrawal_strategy": "fixed",
            "leverage": 1.0,
            "borrowing_spread": 0.015,
            "cash_flows": [],
            "rate_max": 0.06,
            "rate_step": 0.005,
            "metric": "success_rate",
        }
        r = client.post("/api/sweep", json=params)
        assert r.status_code == 200
        data = parse_ndjson(r)
        assert "rates" in data
        assert "success_rates" in data
        assert len(data["rates"]) == len(data["success_rates"])


class TestSensitivity:
    """Test /api/simulate/sensitivity endpoint (shared bootstrap optimization)."""

    BASE_PARAMS = TestSimulation.BASE_PARAMS

    def test_sensitivity_basic(self, client):
        r = client.post("/api/simulate/sensitivity", json=self.BASE_PARAMS)
        assert r.status_code == 200
        data = parse_ndjson(r)
        assert "base_success_rate" in data
        assert "base_funded_ratio" in data
        assert "deltas" in data
        assert len(data["deltas"]) == 4  # 4 params

    def test_sensitivity_direction_correct(self, client):
        """Higher IP => higher SR; higher AW => lower SR."""
        r = client.post("/api/simulate/sensitivity", json=self.BASE_PARAMS)
        data = parse_ndjson(r)
        for d in data["deltas"]:
            if d["param_key"] == "initial_portfolio":
                # More money => better survival
                assert d["high_success_rate"] >= d["low_success_rate"]
            elif d["param_key"] == "annual_withdrawal":
                # More spending => worse survival
                assert d["low_success_rate"] >= d["high_success_rate"]

    def test_sensitivity_with_cash_flows(self, client):
        params = {**self.BASE_PARAMS, "cash_flows": [
            {"name": "pension", "amount": 15000, "start_year": 10,
             "duration": 20, "inflation_adjusted": True, "enabled": True},
        ]}
        r = client.post("/api/simulate/sensitivity", json=params)
        assert r.status_code == 200
        parse_ndjson(r)

    def test_sensitivity_declining_strategy(self, client):
        params = {**self.BASE_PARAMS, "withdrawal_strategy": "declining"}
        r = client.post("/api/simulate/sensitivity", json=params)
        assert r.status_code == 200
        parse_ndjson(r)


class TestScenarios:
    """Test /api/simulate/scenarios endpoint (shared bootstrap optimization)."""

    BASE_PARAMS = TestSimulation.BASE_PARAMS

    def test_scenarios_basic(self, client):
        params = {**self.BASE_PARAMS, "cash_flows": [
            {"name": "pension_a", "amount": 20000, "start_year": 10,
             "duration": 20, "inflation_adjusted": True, "enabled": True,
             "probability": 0.6, "group": "career"},
            {"name": "pension_b", "amount": 10000, "start_year": 10,
             "duration": 20, "inflation_adjusted": True, "enabled": True,
             "probability": 0.4, "group": "career"},
        ]}
        r = client.post("/api/simulate/scenarios", json=params)
        assert r.status_code == 200
        data = parse_ndjson(r)
        assert "base_case" in data
        assert "scenarios" in data
        assert "mode" in data

    def test_scenarios_result_format(self, client):
        params = {**self.BASE_PARAMS, "cash_flows": [
            {"name": "option_a", "amount": 20000, "start_year": 5,
             "duration": 10, "inflation_adjusted": True, "enabled": True,
             "probability": 0.5, "group": "job"},
            {"name": "option_b", "amount": 30000, "start_year": 5,
             "duration": 10, "inflation_adjusted": True, "enabled": True,
             "probability": 0.5, "group": "job"},
        ]}
        r = client.post("/api/simulate/scenarios", json=params)
        data = parse_ndjson(r)
        base = data["base_case"]
        assert "success_rate" in base
        assert "funded_ratio" in base
        assert "median_final_portfolio" in base
        for s in data["scenarios"]:
            assert "label" in s
            assert "success_rate" in s

    def test_scenarios_no_cash_flows_returns_400(self, client):
        r = client.post("/api/simulate/scenarios", json=self.BASE_PARAMS)
        assert r.status_code == 400

    # ── scenario_mode (cross / per-group selection) ──

    TWO_GROUP_CFS = [
        {"name": "career_a", "amount": 20000, "start_year": 5, "duration": 10,
         "inflation_adjusted": True, "enabled": True, "probability": 0.6, "group": "career"},
        {"name": "career_b", "amount": 30000, "start_year": 5, "duration": 10,
         "inflation_adjusted": True, "enabled": True, "probability": 0.4, "group": "career"},
        {"name": "house_a", "amount": -50000, "start_year": 3, "duration": 1,
         "inflation_adjusted": True, "enabled": True, "probability": 0.5, "group": "house"},
    ]

    def test_scenario_mode_full(self, client):
        # career(2 variants) × house(1 variant + none) = 2 × 2 = 4 cross scenarios
        params = {**self.BASE_PARAMS, "scenario_mode": "full", "cash_flows": self.TWO_GROUP_CFS}
        r = client.post("/api/simulate/scenarios", json=params)
        assert r.status_code == 200
        data = parse_ndjson(r)
        assert data["mode"] == "full"
        assert len(data["scenarios"]) == 4

    def test_scenario_mode_per_group(self, client):
        # career(2 + none? no, prob sums to 1 → 2) + house(1 + none) = 2 + 2 = 4 per-group scenarios
        params = {**self.BASE_PARAMS, "scenario_mode": "per_group", "cash_flows": self.TWO_GROUP_CFS}
        r = client.post("/api/simulate/scenarios", json=params)
        assert r.status_code == 200
        data = parse_ndjson(r)
        assert data["mode"] == "per_group"
        assert len(data["scenarios"]) == 4

    def test_scenario_mode_default_is_auto(self, client):
        # No scenario_mode → defaults to auto → small combo count uses full cross
        params = {**self.BASE_PARAMS, "cash_flows": self.TWO_GROUP_CFS}
        r = client.post("/api/simulate/scenarios", json=params)
        assert r.status_code == 200
        assert parse_ndjson(r)["mode"] == "full"

    def test_scenario_mode_full_over_cap_returns_400(self, client):
        # 8 single-variant groups (each + none) = 2**8 = 256 > 128 cap
        cfs = [
            {"name": f"g{i}", "amount": 1000, "start_year": 2, "duration": 1,
             "inflation_adjusted": True, "enabled": True, "probability": 0.5, "group": f"grp{i}"}
            for i in range(8)
        ]
        params = {**self.BASE_PARAMS, "scenario_mode": "full", "cash_flows": cfs}
        r = client.post("/api/simulate/scenarios", json=params)
        assert r.status_code == 400

    def test_scenario_mode_per_group_handles_over_cap(self, client):
        # Same 8 groups: per_group avoids the explosion → 8 × (variant + none) = 16
        cfs = [
            {"name": f"g{i}", "amount": 1000, "start_year": 2, "duration": 1,
             "inflation_adjusted": True, "enabled": True, "probability": 0.5, "group": f"grp{i}"}
            for i in range(8)
        ]
        params = {**self.BASE_PARAMS, "scenario_mode": "per_group", "cash_flows": cfs}
        r = client.post("/api/simulate/scenarios", json=params)
        assert r.status_code == 200
        data = parse_ndjson(r)
        assert data["mode"] == "per_group"
        assert len(data["scenarios"]) == 16

    def test_scenario_mode_invalid_returns_422(self, client):
        params = {**self.BASE_PARAMS, "scenario_mode": "bogus", "cash_flows": self.TWO_GROUP_CFS}
        r = client.post("/api/simulate/scenarios", json=params)
        assert r.status_code == 422


class TestBuyVsRent:
    def test_simple(self, client):
        params = {
            "home_price": 500_000,
            "down_payment_pct": 0.2,
            "mortgage_rate": 0.04,
            "mortgage_term": 30,
            "annual_rent": 24_000,
            "rent_growth_rate": 0.03,
            "home_appreciation_rate": 0.03,
            "maintenance_pct": 0.01,
            "property_tax_pct": 0.01,
            "insurance_annual": 1500,
            "investment_return_rate": 0.07,
            "inflation_rate": 0.025,
            "analysis_years": 30,
        }
        r = client.post("/api/buy-vs-rent/simple", json=params)
        assert r.status_code == 200
        data = r.json()
        assert "buy_net_worth_real" in data
        assert "rent_net_worth_real" in data
        assert "breakeven_year" in data


# ---------------------------------------------------------------------------
# Schema cross-validation tests
# ---------------------------------------------------------------------------

class TestSchemaValidation:

    def test_min_block_gt_max_block_rejected(self, client):
        """min_block > max_block should return 422."""
        r = client.post("/api/simulate", json={
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "min_block": 20,
            "max_block": 5,
            "num_simulations": 100,
        })
        assert r.status_code == 422

    def test_glide_path_years_gt_retirement_rejected(self, client):
        """glide_path_years > retirement_years should return 422 when enabled."""
        r = client.post("/api/simulate", json={
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "retirement_years": 30,
            "glide_path_enabled": True,
            "glide_path_years": 50,
            "num_simulations": 100,
        })
        assert r.status_code == 422

    def test_lower_guardrail_gte_upper_rejected(self, client):
        """lower_guardrail >= upper_guardrail should return 422."""
        r = client.post("/api/guardrail", json={
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "upper_guardrail": 0.80,
            "lower_guardrail": 0.90,
            "num_simulations": 100,
        })
        assert r.status_code == 422

    def test_seed_reproducibility(self, client):
        """Same seed should produce identical results."""
        params = {
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "num_simulations": 100,
            "seed": 42,
        }
        r1 = client.post("/api/simulate", json=params)
        r2 = client.post("/api/simulate", json=params)
        assert r1.status_code == 200
        assert r2.status_code == 200
        d1 = parse_ndjson(r1)
        d2 = parse_ndjson(r2)
        assert d1["success_rate"] == d2["success_rate"]
        assert d1["final_median"] == d2["final_median"]

    def test_different_seeds_differ(self, client):
        """Different seeds should produce different results."""
        r1 = client.post("/api/simulate", json={
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "num_simulations": 200,
            "seed": 42,
        })
        r2 = client.post("/api/simulate", json={
            "initial_portfolio": 1_000_000,
            "annual_withdrawal": 40_000,
            "num_simulations": 200,
            "seed": 99,
        })
        d1 = parse_ndjson(r1)
        d2 = parse_ndjson(r2)
        assert d1["success_rate"] != d2["success_rate"] or d1["final_median"] != d2["final_median"]
