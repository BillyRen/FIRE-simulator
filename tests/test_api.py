"""API endpoint integration tests using FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path

# Ensure backend and simulator are importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


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
        data = r.json()
        assert "success_rate" in data
        assert "funded_ratio" in data
        assert "percentile_trajectories" in data
        assert 0 <= data["success_rate"] <= 1

    def test_simulate_dynamic_strategy(self, client):
        params = {**self.BASE_PARAMS, "withdrawal_strategy": "dynamic",
                  "dynamic_ceiling": 0.1, "dynamic_floor": 0.05}
        r = client.post("/api/simulate", json=params)
        assert r.status_code == 200

    def test_simulate_invalid_allocation(self, client):
        params = {**self.BASE_PARAMS}
        params["allocation"] = {"domestic_stock": 0.5, "global_stock": 0.5, "domestic_bond": 0.5}
        r = client.post("/api/simulate", json=params)
        assert r.status_code == 400 or r.status_code == 422

    def test_simulate_all_countries(self, client):
        params = {**self.BASE_PARAMS, "country": "ALL", "pooling_method": "gdp_sqrt"}
        r = client.post("/api/simulate", json=params)
        assert r.status_code == 200


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
        data = r.json()
        assert "rates" in data
        assert "success_rates" in data
        assert len(data["rates"]) == len(data["success_rates"])


class TestBuyVsRent:
    def test_simple(self, client):
        params = {
            "home_price": 500_000,
            "down_payment_pct": 0.2,
            "mortgage_rate": 0.04,
            "mortgage_years": 30,
            "monthly_rent": 2000,
            "rent_growth": 0.03,
            "home_appreciation": 0.03,
            "maintenance_pct": 0.01,
            "property_tax_pct": 0.01,
            "insurance_pct": 0.005,
            "investment_return": 0.07,
            "years": 30,
            "country": "USA",
        }
        r = client.post("/api/buy-vs-rent/simple", json=params)
        assert r.status_code == 200
        data = r.json()
        assert "buy_net_worth_real" in data
        assert "rent_net_worth_real" in data
        assert "breakeven_year" in data
