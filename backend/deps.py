"""Shared dependencies: data loading/caching, parameter conversion helpers."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from simulator.cashflow import CashFlowItem
from simulator.config import get_gdp_weights
from simulator.data_loader import (
    filter_by_country,
    filter_housing_data,
    get_country_dfs,
    get_housing_available_countries,
    get_housing_country_dfs,
    load_country_list_by_source,
    load_returns_by_source,
)

logger = logging.getLogger(__name__)

# Project root (repo root, one level above backend/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Custom exception classes
# ---------------------------------------------------------------------------

class DataNotFoundError(HTTPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=404,
            detail={"error": "DATA_NOT_FOUND", "message": message}
        )


class ValidationError(HTTPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=400,
            detail={"error": "VALIDATION_ERROR", "message": message}
        )


class ComputationError(HTTPException):
    def __init__(self, message: str):
        super().__init__(
            status_code=500,
            detail={"error": "COMPUTATION_ERROR", "message": message}
        )


# ---------------------------------------------------------------------------
# NDJSON streaming response
# ---------------------------------------------------------------------------

def _json_default(obj):
    """JSON serialization callback for numpy types."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def streaming(gen):
    """Wrap a generator as an NDJSON StreamingResponse.

    Generator yields progress events {"type":"progress","stage":"...","pct":N}
    and final result {"type":"result","data":{...}}.
    """
    def _iter():
        try:
            for item in gen:
                yield json.dumps(item, default=_json_default) + "\n"
        except HTTPException as exc:
            yield json.dumps({"type": "error", "message": exc.detail if isinstance(exc.detail, str) else str(exc.detail)}) + "\n"
        except Exception as exc:
            logger.exception("Streaming endpoint error")
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(
        _iter(),
        media_type="application/x-ndjson",
        headers={
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


# ---------------------------------------------------------------------------
# Data loading & caching
# ---------------------------------------------------------------------------

_returns_cache: dict[str, object] = {}
_country_list_cache: dict[str, list] = {}
_country_dfs_cache: dict[tuple[int, str], dict] = {}
_combined_df_cache: dict[tuple[int, str], object] = {}


def get_returns_df(data_source: str = "jst"):
    if data_source not in _returns_cache:
        _returns_cache[data_source] = load_returns_by_source(data_source)
    return _returns_cache[data_source]


def get_country_list(data_source: str = "jst"):
    if data_source not in _country_list_cache:
        _country_list_cache[data_source] = load_country_list_by_source(data_source)
    return _country_list_cache[data_source]


def filter_df(country: str, data_start_year: int, data_source: str = "jst"):
    """Filter data by country and start year (single-country mode)."""
    df = get_returns_df(data_source)
    return filter_by_country(df, country, data_start_year)


def get_country_dfs_cached(data_start_year: int, data_source: str = "jst") -> dict[str, "pd.DataFrame"]:
    """Get per-country DataFrames (for pooled bootstrap), cached."""
    cache_key = (data_start_year, data_source)
    if cache_key not in _country_dfs_cache:
        df = get_returns_df(data_source)
        _country_dfs_cache[cache_key] = get_country_dfs(df, data_start_year)
    return _country_dfs_cache[cache_key]


def get_combined_df(data_start_year: int, data_source: str = "jst"):
    """Get merged multi-country DataFrame (ALL mode), cached."""
    cache_key = (data_start_year, data_source)
    if cache_key not in _combined_df_cache:
        country_dfs = get_country_dfs_cached(data_start_year, data_source)
        if not country_dfs:
            _combined_df_cache[cache_key] = pd.DataFrame()
        else:
            _combined_df_cache[cache_key] = pd.concat(country_dfs.values(), ignore_index=True)
    return _combined_df_cache[cache_key]


# ---------------------------------------------------------------------------
# Parameter conversion helpers
# ---------------------------------------------------------------------------

def to_cash_flows(items) -> list[CashFlowItem] | None:
    if not items:
        return None
    enabled = [cf for cf in items if getattr(cf, "enabled", True)]
    if not enabled:
        return None
    return [
        CashFlowItem(
            name=cf.name,
            amount=cf.amount,
            start_year=cf.start_year,
            duration=cf.duration,
            inflation_adjusted=cf.inflation_adjusted,
            growth_rate=getattr(cf, "growth_rate", 0.0),
            probability=getattr(cf, "probability", 1.0),
            group=getattr(cf, "group", None),
        )
        for cf in enabled
    ]


def alloc_dict(a) -> dict[str, float]:
    return {"domestic_stock": a.domestic_stock, "global_stock": a.global_stock, "domestic_bond": a.domestic_bond}


def expense_dict(e) -> dict[str, float]:
    return {"domestic_stock": e.domestic_stock, "global_stock": e.global_stock, "domestic_bond": e.domestic_bond}


def validate_data_sufficient(filtered, country_dfs) -> None:
    """Raise 400 if data is insufficient."""
    if len(filtered) < 2 and country_dfs is None:
        raise HTTPException(400, "可用数据不足")


def unpack_cf_table(cf_table_result) -> tuple:
    """Unpack the 5-tuple from build_cf_aware_table, None-safe."""
    if cf_table_result is None:
        return None, None, None, 0.0, -1
    return (
        cf_table_result[0],
        cf_table_result[1],
        cf_table_result[2],
        cf_table_result[3],
        cf_table_result[4],
    )


def resolve_data(req):
    """Resolve filtered_df and country_dfs based on country field.

    Returns
    -------
    tuple[pd.DataFrame, dict | None]
        (filtered_df, country_dfs)
    """
    ds = getattr(req, "data_source", "jst")
    country = req.country
    if ds == "fire_dataset" and country == "ALL":
        country = "USA"

    if country == "ALL":
        country_dfs = get_country_dfs_cached(req.data_start_year, ds)
        if not country_dfs:
            return pd.DataFrame(), None
        combined = get_combined_df(req.data_start_year, ds)
        return combined, country_dfs
    else:
        filtered = filter_df(country, req.data_start_year, ds)
        return filtered, None


def resolve_country_weights(req, country_dfs: dict | None) -> dict[str, float] | None:
    """Compute sampling weights based on pooling_method.

    Only effective when country=ALL and country_dfs is not None.
    """
    if country_dfs is None:
        return None
    if req.pooling_method == "gdp_sqrt":
        return get_gdp_weights(list(country_dfs.keys()))
    return None


def resolve_country_weights_for_housing(req, country_dfs: dict) -> dict[str, float] | None:
    """Compute pooling weights for countries with housing data."""
    if req.pooling_method == "gdp_sqrt":
        all_weights = get_gdp_weights(list(country_dfs.keys()))
        weights = {iso: all_weights.get(iso, 1.0) for iso in country_dfs}
        total = sum(weights.values())
        if total > 0:
            return {iso: w / total for iso, w in weights.items()}
    return None


def prepare_housing_data(req, df):
    """Resolve country_dfs / filtered_df for housing endpoints."""
    if req.country == "ALL":
        country_dfs = get_housing_country_dfs(df, req.data_start_year)
        if not country_dfs:
            raise HTTPException(400, "No countries with housing data available")
        country_weights = resolve_country_weights_for_housing(req, country_dfs)
        return None, country_dfs, country_weights
    else:
        filtered_df = filter_housing_data(df, req.country, req.data_start_year)
        if len(filtered_df) < 10:
            raise HTTPException(
                400,
                f"Insufficient housing data for country {req.country} "
                f"(need 10+ years, got {len(filtered_df)})"
            )
        return filtered_df, None, None
