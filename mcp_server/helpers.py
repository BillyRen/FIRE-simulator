"""Shared helpers for FIRE Simulator MCP tools.

- _resolve_data: country/data_source -> (filtered_df, country_dfs, weights)
- _alloc_from_stock_pct: 0.8 -> {ds:0.4, gs:0.4, db:0.2}
- safe_call: decorator converting FastAPI HTTPException into ValueError
"""

from __future__ import annotations

import functools
from typing import Any, Callable

import pandas as pd
from fastapi import HTTPException

# These imports require sys.path to include repo root + backend/.
# server.py sets that up before importing this module.
from deps import (
    get_country_dfs_cached,
    get_country_list,
    get_combined_df,
    filter_df,
)
from simulator.config import get_gdp_weights


def safe_call(func: Callable) -> Callable:
    """Convert FastAPI HTTPException raised inside tool code into ValueError.

    MCP transport serializes exceptions as text; ValueError surfaces a clean
    error message rather than a stringified HTTPException.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPException as e:
            msg = e.detail if isinstance(e.detail, str) else str(e.detail)
            raise ValueError(f"{msg}") from e

    return wrapper


def _alloc_from_stock_pct(stock_pct: float) -> dict[str, float]:
    """Convenience: split stock_pct equally into domestic_stock / global_stock.

    stock_pct=0.8 -> {ds: 0.4, gs: 0.4, db: 0.2}. Useful when the caller does
    not want to specify the full 3-asset breakdown.
    """
    if not 0.0 <= stock_pct <= 1.0:
        raise ValueError(f"stock_pct must be in [0,1], got {stock_pct}")
    half = stock_pct / 2.0
    return {
        "domestic_stock": half,
        "global_stock": half,
        "domestic_bond": round(1.0 - stock_pct, 6),
    }


def _validate_country(country: str, data_source: str) -> str:
    """Validate ISO code against available countries.

    Returns the normalized country code ('ALL' or valid ISO).
    Raises ValueError with suggestions if not found.
    """
    if country == "ALL":
        return "ALL"

    countries = get_country_list(data_source)
    valid_isos = {c["iso"] for c in countries}
    if country in valid_isos:
        return country

    # Suggest close matches by simple prefix / substring
    upper = country.upper()
    if upper in valid_isos:
        return upper

    suggestions = [c["iso"] for c in countries
                   if upper in c["iso"] or upper in c["name_en"].upper()][:5]
    msg = f"Unknown country '{country}' for data_source='{data_source}'."
    if suggestions:
        msg += f" Did you mean: {', '.join(suggestions)}?"
    msg += " Use fire_list_countries to see all valid ISO codes (3-letter)."
    raise ValueError(msg)


def _resolve_data(
    country: str,
    data_source: str,
    data_start_year: int = 1900,
    pooling_method: str = "gdp_sqrt",
) -> tuple[Any, dict | None, dict | None]:
    """Resolve (filtered_df, country_dfs, country_weights) without Pydantic req.

    Mirrors backend.deps.resolve_data + resolve_country_weights but takes
    plain args. ISO codes are validated up-front with helpful suggestions.
    """
    country = _validate_country(country, data_source)
    if data_source == "fire_dataset" and country == "ALL":
        country = "USA"  # silent coerce, same as backend

    if country == "ALL":
        country_dfs = get_country_dfs_cached(data_start_year, data_source)
        if not country_dfs:
            raise ValueError(
                f"No country data available for data_source={data_source}, "
                f"data_start_year={data_start_year}"
            )
        combined = get_combined_df(data_start_year, data_source)
        weights = (
            get_gdp_weights(list(country_dfs.keys()))
            if pooling_method == "gdp_sqrt" else None
        )
        return combined, country_dfs, weights
    else:
        filtered = filter_df(country, data_start_year, data_source)
        if len(filtered) < 2:
            raise ValueError(
                f"Insufficient data for country={country}, "
                f"data_start_year={data_start_year} ({len(filtered)} rows)"
            )
        return filtered, None, None


def _build_notes(country: str, data_source: str, **kwargs) -> str:
    """Compact one-line context string for tool responses."""
    parts = [f"country={country}", f"data_source={data_source}"]
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    return ", ".join(parts)
