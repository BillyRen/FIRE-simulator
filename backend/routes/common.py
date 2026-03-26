"""Common endpoints: /api/defaults, /api/countries, /api/historical-events, /api/returns."""

from __future__ import annotations

from fastapi import APIRouter

from deps import (
    PROJECT_ROOT,
    get_country_list,
    get_returns_df,
)
from schemas import (
    CountriesResponse,
    CountryInfo,
    HousingCountriesResponse,
    HousingCountryInfo,
    ReturnsResponse,
)
from simulator.data_loader import (
    filter_by_country,
    get_housing_available_countries,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/defaults
# ---------------------------------------------------------------------------

def _detect_server_tier() -> dict:
    """Detect server resources and recommend simulation defaults.

    Uses cgroup limits (container-aware) when available, falling back to
    host-level values.  This matters on shared-host platforms like Render
    where cpu_count() returns the *host* cores, not the allocated share.
    """
    import multiprocessing

    # -- CPU: prefer cgroup quota (works in Docker / Render / K8s) ----------
    cores = multiprocessing.cpu_count()  # host fallback
    try:
        # cgroup v2
        with open("/sys/fs/cgroup/cpu.max") as f:
            parts = f.read().strip().split()
            if parts[0] != "max":
                quota, period = int(parts[0]), int(parts[1])
                cores = max(1, quota / period)
    except (OSError, ValueError, IndexError):
        try:
            # cgroup v1
            with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as fq, \
                 open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as fp:
                quota = int(fq.read().strip())
                period = int(fp.read().strip())
                if quota > 0:
                    cores = max(1, quota / period)
        except (OSError, ValueError):
            pass  # keep host cpu_count

    # -- Memory: prefer cgroup limit ------------------------------------
    mem_gb = 2.0  # conservative default
    try:
        import psutil
        mem_gb = psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem_gb = int(line.split()[1]) / (1024 ** 2)
                        break
        except OSError:
            pass
    # Override with cgroup memory limit if it's lower than host total
    try:
        # cgroup v2
        with open("/sys/fs/cgroup/memory.max") as f:
            val = f.read().strip()
            if val != "max":
                cg_mem = int(val) / (1024 ** 3)
                mem_gb = min(mem_gb, cg_mem)
    except (OSError, ValueError):
        try:
            # cgroup v1
            with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
                val = int(f.read().strip())
                # Kernel uses a huge sentinel (~2^63) for "unlimited"
                if val < 2 ** 62:
                    cg_mem = val / (1024 ** 3)
                    mem_gb = min(mem_gb, cg_mem)
        except (OSError, ValueError):
            pass

    if cores <= 2 or mem_gb <= 1:
        tier = "low"
    elif cores <= 4 or mem_gb <= 4:
        tier = "mid"
    else:
        tier = "high"

    sim_counts = {
        "low":  {"default": 1_000, "heavy": 500,  "guardrail": 500,  "allocation": 500},
        "mid":  {"default": 2_000, "heavy": 1_000, "guardrail": 1_000, "allocation": 1_000},
        "high": {"default": 5_000, "heavy": 2_000, "guardrail": 2_000, "allocation": 2_000},
    }

    return {
        "tier": tier,
        "cores": cores,
        "memory_gb": round(mem_gb, 1),
        "recommended_sim_counts": sim_counts[tier],
    }


_server_defaults: dict | None = None


@router.get("/api/defaults")
def get_defaults():
    """Return recommended simulation defaults based on server resources."""
    global _server_defaults
    if _server_defaults is None:
        _server_defaults = _detect_server_tier()
    return _server_defaults


# ---------------------------------------------------------------------------
# GET /api/countries
# ---------------------------------------------------------------------------

@router.get("/api/countries", response_model=CountriesResponse)
def api_countries(data_source: str = "jst"):
    """Return available countries with metadata."""
    raw = get_country_list(data_source)
    items = [CountryInfo(**c) for c in raw]
    return CountriesResponse(countries=items)


# ---------------------------------------------------------------------------
# GET /api/historical-events
# ---------------------------------------------------------------------------

_historical_events: list[dict] | None = None


def _load_historical_events() -> list[dict]:
    global _historical_events
    if _historical_events is None:
        import json
        events_path = PROJECT_ROOT / "data" / "historical_events.json"
        with open(events_path, encoding="utf-8") as f:
            _historical_events = json.load(f)
    return _historical_events


@router.get("/api/historical-events")
def api_historical_events(country: str | None = None):
    events = _load_historical_events()
    if country:
        events = [
            e for e in events
            if "ALL" in e["countries"] or country in e["countries"]
        ]
    return events


# ---------------------------------------------------------------------------
# GET /api/returns
# ---------------------------------------------------------------------------

@router.get("/api/returns", response_model=ReturnsResponse)
def api_returns(country: str = "USA", data_start_year: int = 1900, data_source: str = "jst"):
    df = get_returns_df(data_source)
    filtered = filter_by_country(df, country, data_start_year)
    return ReturnsResponse(
        years=filtered["Year"].tolist(),
        domestic_stock=filtered["Domestic_Stock"].tolist(),
        global_stock=filtered["Global_Stock"].tolist(),
        domestic_bond=filtered["Domestic_Bond"].tolist(),
        inflation=filtered["Inflation"].tolist(),
    )


# ---------------------------------------------------------------------------
# GET /api/buy-vs-rent/countries
# ---------------------------------------------------------------------------

@router.get("/api/buy-vs-rent/countries", response_model=HousingCountriesResponse)
def api_housing_countries():
    countries = get_housing_available_countries("jst")
    return HousingCountriesResponse(
        countries=[HousingCountryInfo(**c) for c in countries]
    )
