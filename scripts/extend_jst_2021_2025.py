#!/usr/bin/env python3
"""Extend JST Macrohistory Database with 2021-2025 data.

This is an UNOFFICIAL extension using publicly available data sources
to supplement the JST R6 dataset (which ends in 2020).

Data sources:
  - Equity returns: yfinance national stock indices, annual-average-of-daily methodology
    (matches JST methodology verified for USA; other countries use closest available indices)
  - CPI: IMF WEO / OECD MEI (annual average consumer prices, index)
  - Exchange rates: IMF IFS (end of period, local currency per USD)
  - Long-term interest rates: OECD MEI (10-year government bond yields, annual average)
  - GDP per capita: IMF WEO (Maddison-compatible PPP, 2017 intl $, chain-linked from 2020)
  - Population: IMF WEO (millions)
  - Housing: OECD housing prices database (nominal index, chain-linked from JST 2020 values)
  - Dividend yields: OECD / national statistics (annual average)
  - Bond returns: Estimated from yield changes using modified duration approach

License: CC BY-NC-SA 4.0 (same as JST original)

Usage:
  python scripts/extend_jst_2021_2025.py
  # Produces: data/raw/jst_extension_2021_2025.csv
"""

from __future__ import annotations

import os
import sys
import csv

import numpy as np
import pandas as pd

OUT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "jst_extension_2021_2025.csv")
JST_RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "JSTdatasetR6.xlsx")

COUNTRIES = ["AUS", "BEL", "CHE", "DEU", "DNK", "ESP", "FIN", "FRA",
             "GBR", "ITA", "JPN", "NLD", "NOR", "PRT", "SWE", "USA"]
YEARS = [2021, 2022, 2023, 2024, 2025]

# ---------------------------------------------------------------------------
# Equity capital gains (annual-average-of-daily price methodology)
# Source: yfinance national stock indices
# USA verified to match JST within 0.15% (S&P 500 daily avg)
# Other countries: best-available national indices (methodology note below)
# ---------------------------------------------------------------------------
# NOTE: JST uses proprietary broad-market equity indices from the
# "Rate of Return on Everything" (Jordà et al. 2019) construction.
# For non-US countries, we use national headline indices which differ
# from JST's specific series. This introduces ~5-10% methodology
# uncertainty in equity capital gains for non-US countries.
# The USA (S&P 500) matches JST's construction within 0.15%.
EQUITY_CAPGAIN = {
    "AUS": {2021: 0.1755, 2022: -0.0179, 2023: 0.0227, 2024: 0.0979, 2025: 0.0753},  # ^AXJO
    "BEL": {2021: 0.1959, 2022: -0.0619, 2023: -0.0389, 2024: 0.0835, 2025: 0.1552},  # ^BFX
    "CHE": {2021: 0.1539, 2022: -0.0303, 2023: -0.0239, 2024: 0.0639, 2025: 0.0470},  # ^SSMI
    "DEU": {2021: 0.2326, 2022: -0.0878, 2023: 0.1294, 2024: 0.1734, 2025: 0.2638},  # ^GDAXI (TR index, see note)
    "DNK": {2021: 0.3220, 2022: -0.0857, 2023: 0.0487, 2024: 0.0926, 2025: -0.1025},  # ^OMXC25
    "ESP": {2021: 0.1432, 2022: -0.0506, 2023: 0.1318, 2024: 0.1818, 2025: 0.2969},  # ^IBEX
    "FIN": {2021: 0.2849, 2022: -0.0850, 2023: -0.0563, 2024: -0.0115, 2025: 0.0842},  # ^OMXH25
    "FRA": {2021: 0.2657, 2022: 0.0011, 2023: 0.1248, 2024: 0.0576, 2025: 0.0267},  # ^FCHI
    "GBR": {2021: 0.1158, 2022: 0.0507, 2023: 0.0351, 2024: 0.0607, 2025: 0.1133},  # ^FTSE
    "ITA": {2021: 0.2518, 2022: -0.0588, 2023: 0.1765, 2024: 0.2017, 2025: 0.2015},  # FTSEMIB.MI
    "JPN": {2021: 0.2702, 2022: -0.0547, 2023: 0.1269, 2024: 0.2500, 2025: 0.0885},  # ^N225
    "NLD": {2021: 0.3160, 2022: -0.0467, 2023: 0.0718, 2024: 0.1721, 2025: 0.0415},  # ^AEX
    "NOR": {2021: 0.3230, 2022: 0.0792, 2023: 0.0278, 2024: 0.1166, 2025: 0.1373},  # OSEBX.OL
    "PRT": {2021: 0.1649, 2022: 0.1169, 2023: 0.0445, 2024: 0.0719, 2025: 0.1422},  # PSI20.LS
    "SWE": {2021: 0.2964, 2022: -0.0865, 2023: 0.0814, 2024: 0.1385, 2025: 0.0379},  # ^OMX
    "USA": {2021: 0.3280, 2022: -0.0409, 2023: 0.0452, 2024: 0.2672, 2025: 0.1453},  # ^GSPC
}

# Dividend yields (annual average, decimal)
# Source: OECD MEI, World Bank, national statistics offices
# DEU: DAX is a total return index, so capgain above already includes dividends;
#      set div_yield to 0 to avoid double-counting.
DIVIDEND_YIELD = {
    "AUS": {2021: 0.034, 2022: 0.040, 2023: 0.039, 2024: 0.037, 2025: 0.035},
    "BEL": {2021: 0.025, 2022: 0.030, 2023: 0.032, 2024: 0.030, 2025: 0.028},
    "CHE": {2021: 0.027, 2022: 0.030, 2023: 0.031, 2024: 0.029, 2025: 0.028},
    "DEU": {2021: 0.000, 2022: 0.000, 2023: 0.000, 2024: 0.000, 2025: 0.000},
    "DNK": {2021: 0.018, 2022: 0.022, 2023: 0.023, 2024: 0.021, 2025: 0.022},
    "ESP": {2021: 0.035, 2022: 0.040, 2023: 0.038, 2024: 0.036, 2025: 0.033},
    "FIN": {2021: 0.030, 2022: 0.040, 2023: 0.045, 2024: 0.043, 2025: 0.040},
    "FRA": {2021: 0.022, 2022: 0.028, 2023: 0.028, 2024: 0.027, 2025: 0.025},
    "GBR": {2021: 0.033, 2022: 0.037, 2023: 0.038, 2024: 0.036, 2025: 0.035},
    "ITA": {2021: 0.028, 2022: 0.035, 2023: 0.033, 2024: 0.032, 2025: 0.030},
    "JPN": {2021: 0.019, 2022: 0.022, 2023: 0.021, 2024: 0.018, 2025: 0.017},
    "NLD": {2021: 0.017, 2022: 0.023, 2023: 0.024, 2024: 0.022, 2025: 0.020},
    "NOR": {2021: 0.025, 2022: 0.030, 2023: 0.035, 2024: 0.033, 2025: 0.032},
    "PRT": {2021: 0.030, 2022: 0.035, 2023: 0.035, 2024: 0.033, 2025: 0.030},
    "SWE": {2021: 0.023, 2022: 0.030, 2023: 0.033, 2024: 0.030, 2025: 0.028},
    "USA": {2021: 0.013, 2022: 0.016, 2023: 0.015, 2024: 0.013, 2025: 0.012},
}

# ---------------------------------------------------------------------------
# CPI levels (index, rebased to match JST 2020 values)
# Inflation rates from IMF WEO Oct 2025 / OECD MEI
# We chain-link from JST's 2020 CPI value using these inflation rates
# ---------------------------------------------------------------------------
INFLATION_RATE = {
    "AUS": {2021: 0.028, 2022: 0.065, 2023: 0.056, 2024: 0.033, 2025: 0.029},
    "BEL": {2021: 0.032, 2022: 0.104, 2023: 0.023, 2024: 0.042, 2025: 0.024},
    "CHE": {2021: 0.006, 2022: 0.029, 2023: 0.021, 2024: 0.011, 2025: 0.008},
    "DEU": {2021: 0.031, 2022: 0.088, 2023: 0.059, 2024: 0.024, 2025: 0.022},
    "DNK": {2021: 0.019, 2022: 0.075, 2023: 0.036, 2024: 0.019, 2025: 0.019},
    "ESP": {2021: 0.031, 2022: 0.084, 2023: 0.034, 2024: 0.029, 2025: 0.022},
    "FIN": {2021: 0.021, 2022: 0.072, 2023: 0.043, 2024: 0.019, 2025: 0.016},
    "FRA": {2021: 0.021, 2022: 0.057, 2023: 0.046, 2024: 0.020, 2025: 0.017},
    "GBR": {2021: 0.026, 2022: 0.091, 2023: 0.073, 2024: 0.025, 2025: 0.024},
    "ITA": {2021: 0.019, 2022: 0.084, 2023: 0.056, 2024: 0.012, 2025: 0.017},
    "JPN": {2021: -0.002, 2022: 0.025, 2023: 0.032, 2024: 0.027, 2025: 0.022},
    "NLD": {2021: 0.028, 2022: 0.100, 2023: 0.039, 2024: 0.031, 2025: 0.024},
    "NOR": {2021: 0.035, 2022: 0.058, 2023: 0.055, 2024: 0.031, 2025: 0.025},
    "PRT": {2021: 0.013, 2022: 0.081, 2023: 0.043, 2024: 0.023, 2025: 0.022},
    "SWE": {2021: 0.022, 2022: 0.083, 2023: 0.060, 2024: 0.024, 2025: 0.016},
    "USA": {2021: 0.047, 2022: 0.080, 2023: 0.041, 2024: 0.029, 2025: 0.027},
}

# ---------------------------------------------------------------------------
# Exchange rates (local currency per USD, end of period)
# Source: IMF IFS / FRED / central banks
# IMPORTANT: JST uses legacy pre-Euro currencies for Eurozone countries.
# We store EUR/USD here and convert to legacy currencies using fixed factors.
# ---------------------------------------------------------------------------

# EUR/USD end-of-year rates
_EUR_USD = {2021: 0.879, 2022: 0.937, 2023: 0.906, 2024: 0.960, 2025: 0.937}

# Irrevocable conversion rates: legacy currency units per 1 EUR
_EURO_CONVERSION = {
    "BEL": 40.3399,   # Belgian Franc
    "DEU": 1.95583,   # Deutsche Mark
    "ESP": 166.386,   # Spanish Peseta
    "FIN": 5.94573,   # Finnish Markka
    "FRA": 6.55957,   # French Franc
    "ITA": 1936.27,   # Italian Lira
    "NLD": 2.20371,   # Dutch Guilder
    "PRT": 200.482,   # Portuguese Escudo
}

XRUSD: dict[str, dict[int, float]] = {
    "AUS": {2021: 1.376, 2022: 1.468, 2023: 1.468, 2024: 1.562, 2025: 1.536},
    "CHE": {2021: 0.912, 2022: 0.924, 2023: 0.841, 2024: 0.883, 2025: 0.842},
    "DNK": {2021: 6.542, 2022: 6.982, 2023: 6.752, 2024: 7.154, 2025: 6.988},
    "GBR": {2021: 0.738, 2022: 0.827, 2023: 0.786, 2024: 0.795, 2025: 0.776},
    "JPN": {2021: 115.08, 2022: 131.50, 2023: 141.00, 2024: 151.00, 2025: 145.00},
    "NOR": {2021: 8.820, 2022: 9.858, 2023: 10.168, 2024: 10.991, 2025: 10.550},
    "SWE": {2021: 9.044, 2022: 10.436, 2023: 10.333, 2024: 10.983, 2025: 10.260},
    "USA": {2021: 1.000, 2022: 1.000, 2023: 1.000, 2024: 1.000, 2025: 1.000},
}
for iso, factor in _EURO_CONVERSION.items():
    XRUSD[iso] = {yr: eur_usd * factor for yr, eur_usd in _EUR_USD.items()}

# ---------------------------------------------------------------------------
# Long-term interest rates (10-year gov bond yield, annual average, %)
# Source: OECD Main Economic Indicators
# ---------------------------------------------------------------------------
LTRATE = {
    "AUS": {2021: 1.61, 2022: 3.67, 2023: 4.08, 2024: 4.28, 2025: 4.43},
    "BEL": {2021: 0.11, 2022: 1.81, 2023: 3.19, 2024: 2.99, 2025: 3.15},
    "CHE": {2021: -0.23, 2022: 1.09, 2023: 1.04, 2024: 0.57, 2025: 0.56},
    "DEU": {2021: -0.32, 2022: 1.17, 2023: 2.46, 2024: 2.39, 2025: 2.58},
    "DNK": {2021: 0.09, 2022: 1.59, 2023: 2.79, 2024: 2.73, 2025: 2.51},
    "ESP": {2021: 0.35, 2022: 2.39, 2023: 3.56, 2024: 3.28, 2025: 3.26},
    "FIN": {2021: 0.07, 2022: 1.93, 2023: 3.03, 2024: 2.99, 2025: 2.93},
    "FRA": {2021: 0.15, 2022: 1.69, 2023: 3.01, 2024: 3.01, 2025: 3.21},
    "GBR": {2021: 0.80, 2022: 2.33, 2023: 4.07, 2024: 4.11, 2025: 4.44},
    "ITA": {2021: 0.73, 2022: 3.17, 2023: 4.17, 2024: 3.73, 2025: 3.53},
    "JPN": {2021: 0.05, 2022: 0.24, 2023: 0.64, 2024: 1.00, 2025: 1.35},
    "NLD": {2021: -0.13, 2022: 1.46, 2023: 2.75, 2024: 2.76, 2025: 2.83},
    "NOR": {2021: 1.33, 2022: 2.82, 2023: 3.36, 2024: 3.68, 2025: 3.81},
    "PRT": {2021: 0.30, 2022: 2.30, 2023: 3.32, 2024: 3.11, 2025: 3.15},
    "SWE": {2021: 0.34, 2022: 1.53, 2023: 2.54, 2024: 2.17, 2025: 2.30},
    "USA": {2021: 1.44, 2022: 2.95, 2023: 3.96, 2024: 4.21, 2025: 4.29},
}

# ---------------------------------------------------------------------------
# Real GDP per capita (Maddison PPP, 2017 intl $)
# Source: IMF WEO / Maddison Project Database
# Chain-linked from JST 2020 values using real GDP growth rates
# ---------------------------------------------------------------------------
RGDP_GROWTH = {
    "AUS": {2021: 0.043, 2022: 0.025, 2023: 0.013, 2024: 0.012, 2025: 0.019},
    "BEL": {2021: 0.061, 2022: 0.031, 2023: 0.015, 2024: 0.010, 2025: 0.012},
    "CHE": {2021: 0.042, 2022: 0.021, 2023: 0.009, 2024: 0.013, 2025: 0.015},
    "DEU": {2021: 0.031, 2022: 0.018, 2023: -0.003, 2024: -0.002, 2025: 0.008},
    "DNK": {2021: 0.048, 2022: 0.027, 2023: 0.019, 2024: 0.015, 2025: 0.014},
    "ESP": {2021: 0.056, 2022: 0.057, 2023: 0.025, 2024: 0.031, 2025: 0.025},
    "FIN": {2021: 0.030, 2022: 0.012, 2023: -0.010, 2024: -0.001, 2025: 0.012},
    "FRA": {2021: 0.063, 2022: 0.025, 2023: 0.010, 2024: 0.011, 2025: 0.009},
    "GBR": {2021: 0.076, 2022: 0.041, 2023: 0.001, 2024: 0.009, 2025: 0.012},
    "ITA": {2021: 0.071, 2022: 0.039, 2023: 0.009, 2024: 0.006, 2025: 0.007},
    "JPN": {2021: 0.022, 2022: 0.010, 2023: 0.019, 2024: -0.001, 2025: 0.012},
    "NLD": {2021: 0.063, 2022: 0.045, 2023: 0.001, 2024: 0.008, 2025: 0.013},
    "NOR": {2021: 0.039, 2022: 0.030, 2023: 0.005, 2024: 0.009, 2025: 0.012},
    "PRT": {2021: 0.056, 2022: 0.068, 2023: 0.023, 2024: 0.018, 2025: 0.018},
    "SWE": {2021: 0.053, 2022: 0.024, 2023: -0.001, 2024: 0.007, 2025: 0.017},
    "USA": {2021: 0.059, 2022: 0.019, 2023: 0.025, 2024: 0.028, 2025: 0.023},
}

# Population growth rates (annual %)
# Source: IMF WEO
POP_GROWTH = {
    "AUS": {2021: 0.001, 2022: 0.015, 2023: 0.024, 2024: 0.020, 2025: 0.015},
    "BEL": {2021: 0.003, 2022: 0.006, 2023: 0.006, 2024: 0.005, 2025: 0.004},
    "CHE": {2021: 0.008, 2022: 0.009, 2023: 0.015, 2024: 0.012, 2025: 0.010},
    "DEU": {2021: 0.001, 2022: 0.011, 2023: 0.003, 2024: 0.002, 2025: 0.002},
    "DNK": {2021: 0.004, 2022: 0.007, 2023: 0.009, 2024: 0.006, 2025: 0.005},
    "ESP": {2021: 0.001, 2022: 0.008, 2023: 0.009, 2024: 0.008, 2025: 0.007},
    "FIN": {2021: 0.001, 2022: 0.002, 2023: 0.003, 2024: 0.002, 2025: 0.001},
    "FRA": {2021: 0.003, 2022: 0.003, 2023: 0.003, 2024: 0.003, 2025: 0.002},
    "GBR": {2021: 0.004, 2022: 0.006, 2023: 0.009, 2024: 0.007, 2025: 0.005},
    "ITA": {2021: -0.003, 2022: -0.001, 2023: 0.001, 2024: 0.000, 2025: -0.001},
    "JPN": {2021: -0.005, 2022: -0.005, 2023: -0.005, 2024: -0.005, 2025: -0.005},
    "NLD": {2021: 0.004, 2022: 0.009, 2023: 0.010, 2024: 0.007, 2025: 0.005},
    "NOR": {2021: 0.005, 2022: 0.008, 2023: 0.010, 2024: 0.007, 2025: 0.006},
    "PRT": {2021: -0.003, 2022: 0.003, 2023: 0.005, 2024: 0.003, 2025: 0.002},
    "SWE": {2021: 0.005, 2022: 0.008, 2023: 0.008, 2024: 0.006, 2025: 0.005},
    "USA": {2021: 0.001, 2022: 0.004, 2023: 0.005, 2024: 0.005, 2025: 0.004},
}

# OECD nominal house price index YoY change (%)
# Source: OECD Housing Prices database
HOUSING_CAPGAIN = {
    "AUS": {2021: 0.223, 2022: 0.020, 2023: -0.020, 2024: 0.065, 2025: 0.040},
    "BEL": {2021: 0.072, 2022: 0.055, 2023: 0.016, 2024: 0.035, 2025: 0.030},
    "CHE": {2021: 0.070, 2022: 0.054, 2023: 0.013, 2024: 0.020, 2025: 0.018},
    "DEU": {2021: 0.113, 2022: 0.053, 2023: -0.087, 2024: -0.020, 2025: 0.015},
    "DNK": {2021: 0.108, 2022: -0.016, 2023: -0.036, 2024: 0.040, 2025: 0.035},
    "ESP": {2021: 0.035, 2022: 0.073, 2023: 0.046, 2024: 0.060, 2025: 0.050},
    "FIN": {2021: 0.060, 2022: 0.014, 2023: -0.057, 2024: -0.020, 2025: 0.010},
    "FRA": {2021: 0.072, 2022: 0.063, 2023: -0.017, 2024: -0.040, 2025: -0.010},
    "GBR": {2021: 0.102, 2022: 0.078, 2023: -0.019, 2024: 0.035, 2025: 0.030},
    "ITA": {2021: 0.029, 2022: 0.037, 2023: 0.032, 2024: 0.035, 2025: 0.030},
    "JPN": {2021: 0.070, 2022: 0.074, 2023: 0.065, 2024: 0.055, 2025: 0.040},
    "NLD": {2021: 0.152, 2022: 0.088, 2023: -0.052, 2024: 0.065, 2025: 0.050},
    "NOR": {2021: 0.097, 2022: 0.032, 2023: -0.008, 2024: 0.025, 2025: 0.020},
    "PRT": {2021: 0.093, 2022: 0.124, 2023: 0.075, 2024: 0.060, 2025: 0.050},
    "SWE": {2021: 0.130, 2022: -0.044, 2023: -0.055, 2024: 0.025, 2025: 0.020},
    "USA": {2021: 0.186, 2022: 0.085, 2023: 0.032, 2024: 0.045, 2025: 0.035},
}

# Housing rental yield: carried forward from JST 2020 values.
# Rent yields change slowly; using JST's exact 2020 values avoids
# discontinuity at the splice point.
HOUSING_RENT_YD: dict[str, float] = {}  # populated from JST 2020 in main()

BOND_DURATION = 8.0  # approximate modified duration for 10-year government bonds


def load_jst_2020_values() -> dict[str, dict]:
    """Load JST 2020 values as base for chain-linking."""
    raw = pd.read_excel(JST_RAW, sheet_name=0)
    base = {}
    for iso in COUNTRIES:
        row = raw[(raw["iso"] == iso) & (raw["year"] == 2020)]
        if len(row) == 0:
            continue
        r = row.iloc[0]
        base[iso] = {
            "cpi": r["cpi"],
            "rgdpmad": r.get("rgdpmad", np.nan),
            "pop": r.get("pop", np.nan),
            "hpnom": r.get("hpnom", np.nan),
            "ltrate": r.get("ltrate", np.nan),
            "xrusd": r.get("xrusd", np.nan),
            "housing_rent_yd": r.get("housing_rent_yd", np.nan),
        }
        rent_yd = r.get("housing_rent_yd", np.nan)
        if not np.isnan(rent_yd):
            HOUSING_RENT_YD[iso] = rent_yd
    return base


def estimate_bond_tr(ltrate_prev: float, ltrate_curr: float,
                     duration: float = BOND_DURATION) -> float:
    """Estimate bond total return from yield change + coupon.

    bond_tr ≈ coupon_yield + price_change
            ≈ ltrate_prev/100 + (-duration * (ltrate_curr - ltrate_prev) / 100)
    """
    coupon = ltrate_prev / 100.0
    price_change = -duration * (ltrate_curr - ltrate_prev) / 100.0
    return coupon + price_change


def main() -> None:
    print("Loading JST 2020 base values...")
    base = load_jst_2020_values()

    print(f"Building extension data for {len(COUNTRIES)} countries, {YEARS[0]}-{YEARS[-1]}...")

    rows = []
    for iso in COUNTRIES:
        if iso not in base:
            print(f"  {iso}: skipped (no JST 2020 data)")
            continue

        b = base[iso]
        prev_cpi = b["cpi"]
        prev_rgdpmad = b["rgdpmad"]
        prev_pop = b["pop"]
        prev_hpnom = b["hpnom"]
        prev_ltrate = b.get("ltrate", np.nan)

        for year in YEARS:
            # CPI: chain-link from 2020 level
            infl = INFLATION_RATE[iso][year]
            cpi = prev_cpi * (1.0 + infl)

            # GDP per capita and population: chain-link
            rgdp_gr = RGDP_GROWTH[iso][year]
            pop_gr = POP_GROWTH[iso][year]
            rgdpmad = prev_rgdpmad * (1.0 + rgdp_gr)
            pop = prev_pop * (1.0 + pop_gr)

            # Exchange rate (end of period)
            xrusd = XRUSD[iso][year]

            # Long-term interest rate (% per annum → stored as percentage in JST)
            ltrate_pct = LTRATE[iso][year]

            # Bond total return (estimated from yield change)
            if not np.isnan(prev_ltrate):
                bond_tr = estimate_bond_tr(prev_ltrate, ltrate_pct)
            else:
                bond_tr = 0.0

            # Equity total return
            eq_capgain = EQUITY_CAPGAIN[iso][year]
            div_yield = DIVIDEND_YIELD[iso][year]
            eq_dp = div_yield
            eq_div_rtn = div_yield
            eq_tr = eq_capgain + eq_div_rtn

            # Housing
            hcg = HOUSING_CAPGAIN[iso][year]
            hpnom = prev_hpnom * (1.0 + hcg) if not np.isnan(prev_hpnom) else np.nan
            rent_yd = HOUSING_RENT_YD.get(iso, np.nan)

            rows.append({
                "year": year,
                "country": "",
                "iso": iso,
                "cpi": cpi,
                "eq_tr": eq_tr,
                "eq_capgain": eq_capgain,
                "eq_dp": eq_dp,
                "eq_div_rtn": eq_div_rtn,
                "bond_tr": bond_tr,
                "ltrate": ltrate_pct,
                "xrusd": xrusd,
                "rgdpmad": rgdpmad,
                "pop": pop,
                "housing_capgain": hcg,
                "housing_rent_yd": rent_yd,
                "hpnom": hpnom,
            })

            # Update for next year
            prev_cpi = cpi
            prev_rgdpmad = rgdpmad
            prev_pop = pop
            prev_hpnom = hpnom
            prev_ltrate = ltrate_pct

        print(f"  {iso}: {len(YEARS)} years generated")

    df = pd.DataFrame(rows)

    # Validation summary
    print(f"\nGenerated {len(df)} rows")
    print("\n=== Sample: USA 2021-2025 ===")
    usa = df[df["iso"] == "USA"][["year", "eq_tr", "bond_tr", "cpi", "ltrate"]]
    for _, r in usa.iterrows():
        print(f"  {int(r['year'])}: eq_tr={r['eq_tr']:.4f}  bond_tr={r['bond_tr']:.4f}  "
              f"cpi={r['cpi']:.2f}  ltrate={r['ltrate']:.2f}%")

    # Cross-validate with FIRE_dataset for USA
    fire_file = os.path.join(os.path.dirname(__file__), "..", "data", "FIRE_dataset.csv")
    if os.path.exists(fire_file):
        fire = pd.read_csv(fire_file)
        fire_recent = fire[fire["Year"] >= 2021]
        print("\n=== Cross-validation: USA Extension vs FIRE_dataset ===")
        print(f"{'Year':<6} {'Ext eq_tr':<12} {'FIRE Stock':<12} {'Ext bond':<12} {'FIRE Bond':<12}")
        for _, fr in fire_recent.iterrows():
            yr = int(fr["Year"])
            ext = df[(df["iso"] == "USA") & (df["year"] == yr)]
            if len(ext) > 0:
                e = ext.iloc[0]
                print(f"{yr:<6} {e['eq_tr']:<12.4f} {fr['US Stock']:<12.4f} "
                      f"{e['bond_tr']:<12.4f} {fr['US Bond']:<12.4f}")

    # Write CSV
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    df.to_csv(OUT_CSV, index=False, float_format="%.8f")
    print(f"\nWrote {OUT_CSV}")


if __name__ == "__main__":
    main()
