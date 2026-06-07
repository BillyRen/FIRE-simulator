#!/usr/bin/env python3
"""Capture equivalence fixtures from current HEAD for backward-compat protection.

Subsequent PRs in the CME + yield-conditioning effort (see
`docs/plan-2026-05-26-cme-yield-conditioning.md`) will refactor the
bootstrap/sampling layer. This script captures the *current* observable
behavior for fixed-seed scenarios, so those refactors can be proven
byte-identical for unchanged inputs.

Idempotent: re-running produces fixtures whose `metadata.created_at` differs
but all other arrays are byte-identical (assuming pinned numpy/pandas).

Outputs (all under `tests/fixtures/`):
  - equiv_default.npz      JST single-country (USA)
  - equiv_pooled.npz       JST pooled (ALL, gdp_sqrt)
  - equiv_fire.npz         FIRE_dataset (USA only)
  - equiv_buy_vs_rent.npz  buy_vs_rent bootstrap (7-col with housing data)

Each .npz contains:
  - bootstrap_returns : (num_sims, retirement_years, n_cols) raw bootstrap output
  - sim_trajectories  : (num_sims, retirement_years + 1) portfolio path
  - sim_withdrawals   : (num_sims, retirement_years) withdrawal amounts
  - sim_real_returns  : (num_sims, retirement_years) real portfolio returns
  - sim_inflation     : (num_sims, retirement_years) inflation per year
  - metadata          : 0-d object array; JSON string with env + params info

Usage:
  python scripts/capture_equivalence_fixtures.py            # capture all 4
  python scripts/capture_equivalence_fixtures.py --scenario default
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulator.bootstrap import (  # noqa: E402
    HOUSING_COLS,
    RETURN_COLS,
    _prepare_pooled_arrays,
    block_bootstrap_np,
    block_bootstrap_pooled_np,
)
from simulator.config import get_gdp_weights  # noqa: E402
from simulator.data_loader import (  # noqa: E402
    filter_by_country,
    filter_housing_data,
    get_country_dfs,
    get_housing_country_dfs,
    load_fire_dataset,
    load_returns_data,
)
from simulator.monte_carlo import run_simulation  # noqa: E402

FIXTURES_DIR = ROOT / "tests" / "fixtures"

# Default parameters shared across scenarios (small enough for compact fixtures)
SEED = 42
NUM_SIMS = 200
RETIREMENT_YEARS = 65
MIN_BLOCK = 5
MAX_BLOCK = 15
DATA_START_YEAR = 1900
INITIAL_PORTFOLIO = 1_000_000.0
ANNUAL_WITHDRAWAL = 40_000.0
ALLOCATION = {"domestic_stock": 0.4, "global_stock": 0.4, "domestic_bond": 0.2}
EXPENSE_RATIOS = {"domestic_stock": 0.005, "global_stock": 0.005, "domestic_bond": 0.005}


SCENARIO_NAMES = ("default", "pooled", "fire", "buy_vs_rent")


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _metadata(scenario: str, params: dict) -> dict:
    return {
        "scenario": scenario,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "python_version": platform.python_version(),
        "git_sha": _git_sha(),
        "seed": SEED,
        "params": params,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _capture_bootstrap_returns(
    *,
    returns_df: pd.DataFrame | None,
    country_dfs: dict | None,
    country_weights: dict | None,
    columns: list[str],
    seed: int,
    num_sims: int,
    retirement_years: int,
    min_block: int,
    max_block: int,
) -> np.ndarray:
    """Replicate the per-sim bootstrap loop with a fresh RNG.

    Important: this uses an independent RNG from run_simulation's RNG. The
    purpose is to capture the raw bootstrap stream at the same seed, which
    serves as a low-level invariant. The high-level invariant is captured
    via the full run_simulation pipeline separately.
    """
    rng = np.random.default_rng(seed)
    out = np.empty((num_sims, retirement_years, len(columns)), dtype=np.float64)

    if country_dfs is not None:
        _, c_arrays, c_lens, c_probs = _prepare_pooled_arrays(
            country_dfs, country_weights, columns
        )
        for i in range(num_sims):
            out[i] = block_bootstrap_pooled_np(
                c_arrays, c_lens, c_probs,
                retirement_years, min_block, max_block, rng=rng,
            )
    else:
        assert returns_df is not None
        src_data = returns_df[columns].values
        src_n = len(src_data)
        for i in range(num_sims):
            out[i] = block_bootstrap_np(
                src_data, src_n, retirement_years, min_block, max_block, rng=rng,
            )
    return out


def _capture_sim_pipeline(
    *,
    returns_df: pd.DataFrame,
    country_dfs: dict | None,
    country_weights: dict | None,
) -> dict[str, np.ndarray]:
    """Run the full run_simulation pipeline and return key outputs."""
    traj, wd, real_ret, infl = run_simulation(
        initial_portfolio=INITIAL_PORTFOLIO,
        annual_withdrawal=ANNUAL_WITHDRAWAL,
        allocation=ALLOCATION,
        expense_ratios=EXPENSE_RATIOS,
        retirement_years=RETIREMENT_YEARS,
        min_block=MIN_BLOCK,
        max_block=MAX_BLOCK,
        num_simulations=NUM_SIMS,
        returns_df=returns_df,
        seed=SEED,
        country_dfs=country_dfs,
        country_weights=country_weights,
    )
    return {
        "sim_trajectories": traj,
        "sim_withdrawals": wd,
        "sim_real_returns": real_ret,
        "sim_inflation": infl,
    }


def _save_npz(path: Path, *, bootstrap_returns: np.ndarray, sim: dict, metadata: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        bootstrap_returns=bootstrap_returns,
        metadata=np.array(json.dumps(metadata, sort_keys=True)),
        **sim,
    )


def capture_default() -> Path:
    df = load_returns_data()
    filtered = filter_by_country(df, "USA", DATA_START_YEAR)
    boot = _capture_bootstrap_returns(
        returns_df=filtered, country_dfs=None, country_weights=None,
        columns=RETURN_COLS, seed=SEED, num_sims=NUM_SIMS,
        retirement_years=RETIREMENT_YEARS, min_block=MIN_BLOCK, max_block=MAX_BLOCK,
    )
    sim = _capture_sim_pipeline(returns_df=filtered, country_dfs=None, country_weights=None)
    meta = _metadata("default", {
        "data_source": "jst", "country": "USA", "data_start_year": DATA_START_YEAR,
        "retirement_years": RETIREMENT_YEARS, "num_simulations": NUM_SIMS,
        "min_block": MIN_BLOCK, "max_block": MAX_BLOCK,
        "initial_portfolio": INITIAL_PORTFOLIO,
        "annual_withdrawal": ANNUAL_WITHDRAWAL,
        "allocation": ALLOCATION, "expense_ratios": EXPENSE_RATIOS,
    })
    path = FIXTURES_DIR / "equiv_default.npz"
    _save_npz(path, bootstrap_returns=boot, sim=sim, metadata=meta)
    return path


def capture_pooled() -> Path:
    df = load_returns_data()
    country_dfs = get_country_dfs(df, DATA_START_YEAR)
    country_weights = get_gdp_weights(list(country_dfs.keys()))
    combined = pd.concat(country_dfs.values(), ignore_index=True)
    boot = _capture_bootstrap_returns(
        returns_df=None, country_dfs=country_dfs, country_weights=country_weights,
        columns=RETURN_COLS, seed=SEED, num_sims=NUM_SIMS,
        retirement_years=RETIREMENT_YEARS, min_block=MIN_BLOCK, max_block=MAX_BLOCK,
    )
    sim = _capture_sim_pipeline(
        returns_df=combined, country_dfs=country_dfs, country_weights=country_weights,
    )
    meta = _metadata("pooled", {
        "data_source": "jst", "country": "ALL", "pooling_method": "gdp_sqrt",
        "data_start_year": DATA_START_YEAR,
        "retirement_years": RETIREMENT_YEARS, "num_simulations": NUM_SIMS,
        "min_block": MIN_BLOCK, "max_block": MAX_BLOCK,
        "initial_portfolio": INITIAL_PORTFOLIO,
        "annual_withdrawal": ANNUAL_WITHDRAWAL,
        "allocation": ALLOCATION, "expense_ratios": EXPENSE_RATIOS,
    })
    path = FIXTURES_DIR / "equiv_pooled.npz"
    _save_npz(path, bootstrap_returns=boot, sim=sim, metadata=meta)
    return path


def capture_fire() -> Path:
    df = load_fire_dataset()
    filtered = filter_by_country(df, "USA", DATA_START_YEAR)
    boot = _capture_bootstrap_returns(
        returns_df=filtered, country_dfs=None, country_weights=None,
        columns=RETURN_COLS, seed=SEED, num_sims=NUM_SIMS,
        retirement_years=RETIREMENT_YEARS, min_block=MIN_BLOCK, max_block=MAX_BLOCK,
    )
    sim = _capture_sim_pipeline(returns_df=filtered, country_dfs=None, country_weights=None)
    meta = _metadata("fire", {
        "data_source": "fire_dataset", "country": "USA",
        "data_start_year": DATA_START_YEAR,
        "retirement_years": RETIREMENT_YEARS, "num_simulations": NUM_SIMS,
        "min_block": MIN_BLOCK, "max_block": MAX_BLOCK,
        "initial_portfolio": INITIAL_PORTFOLIO,
        "annual_withdrawal": ANNUAL_WITHDRAWAL,
        "allocation": ALLOCATION, "expense_ratios": EXPENSE_RATIOS,
    })
    path = FIXTURES_DIR / "equiv_fire.npz"
    _save_npz(path, bootstrap_returns=boot, sim=sim, metadata=meta)
    return path


def capture_buy_vs_rent() -> Path:
    """For buy_vs_rent we only capture the bootstrap stream — full run_buy_vs_rent_mc
    needs many additional housing/financing parameters; the bootstrap layer is what
    subsequent PRs touch, so that's the invariant we anchor."""
    df = load_returns_data()
    filtered = filter_housing_data(df, "USA", DATA_START_YEAR)
    columns = RETURN_COLS + HOUSING_COLS  # 7 columns
    bvr_years = 30  # Typical buy-vs-rent horizon
    boot = _capture_bootstrap_returns(
        returns_df=filtered, country_dfs=None, country_weights=None,
        columns=columns, seed=SEED, num_sims=NUM_SIMS,
        retirement_years=bvr_years, min_block=MIN_BLOCK, max_block=MAX_BLOCK,
    )
    # No full sim pipeline for BvR — only the bootstrap matters for our refactor scope
    meta = _metadata("buy_vs_rent", {
        "data_source": "jst", "country": "USA",
        "data_start_year": DATA_START_YEAR,
        "analysis_years": bvr_years, "num_simulations": NUM_SIMS,
        "min_block": MIN_BLOCK, "max_block": MAX_BLOCK,
        "columns": columns,
    })
    path = FIXTURES_DIR / "equiv_buy_vs_rent.npz"
    # Save without sim_* arrays — BvR fixture only contains bootstrap_returns
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        bootstrap_returns=boot,
        metadata=np.array(json.dumps(meta, sort_keys=True)),
    )
    return path


CAPTURE_FUNCS = {
    "default": capture_default,
    "pooled": capture_pooled,
    "fire": capture_fire,
    "buy_vs_rent": capture_buy_vs_rent,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--scenario",
        choices=("all", *SCENARIO_NAMES),
        default="all",
        help="Which scenario to (re)capture. Default: all four.",
    )
    args = parser.parse_args(argv)

    targets = SCENARIO_NAMES if args.scenario == "all" else (args.scenario,)
    for name in targets:
        print(f"Capturing {name}...")
        path = CAPTURE_FUNCS[name]()
        size_kb = path.stat().st_size / 1024
        print(f"  -> {path.relative_to(ROOT)} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
