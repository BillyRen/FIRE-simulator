# FIRE Simulator - Performance Optimization Summary

## Performance Results

| Page | Before | After | Speedup |
|------|--------|-------|---------|
| Withdrawal Rate Sweep (`/api/sweep`) | 2.25s | 1.20s | 1.87x |
| Guardrail (`/api/guardrail`) | 2.23s | 1.20s | 1.86x |
| Asset Allocation Sweep (`/api/allocation-sweep`) | 2.22s | 1.20s | 1.86x |
| **Total** | **6.70s** | **3.59s** | **1.86x** |

Tested on: macOS, Python 3.12.9, Apple Silicon M-series (8 cores)

## What Was Optimized

### Phase 1: Quick Wins
- **GZIP compression** (`backend/main.py`): 60-80% response size reduction
- **Custom exceptions** + division-by-zero guards (`guardrail.py`, `statistics.py`)
- **Data caching** with composite keys (`main.py`): 20-40% speedup on repeated requests
- **Mobile UX** improvements (navbar, sidebar-form)

### Phase 2: Core Performance
- **Bootstrap array pre-allocation** (`bootstrap.py`): Eliminated list.append + concatenate overhead
- **Glide path vectorization** (`monte_carlo.py`): Pre-computed weight matrices, vectorized returns
- **Fixed strategy vectorization** (`monte_carlo.py`): `run_simulation_vectorized_fixed()` eliminates inner Python loop
- **Sweep parallelization** (`sweep.py`): `ProcessPoolExecutor` for withdrawal rate and allocation sweeps
- **Bootstrap parallelization** (`sweep.py`): Per-simulation parallel bootstrap sampling with `initializer` for shared data

### Key Design Decisions
- **Conditional parallelization**: Only enabled when `num_simulations > 100` and `MAX_WORKERS > 1`
- **Per-index seeding**: `rng = default_rng(seed + sim_index)` ensures reproducibility across parallel/sequential paths
- **ProcessPoolExecutor initializer**: Shared read-only data (returns_df, country_dfs) passed once per worker, not per task
- **chunksize tuning**: `max(1, n_tasks // (MAX_WORKERS * 4))` reduces IPC overhead
- **Environment variable**: `MAX_SWEEP_WORKERS` (default 8) controls max parallelism

## Running Benchmarks

```bash
# Comprehensive MC benchmark (4 scenarios)
PYTHONPATH=. python scripts/benchmark_summary.py

# Sequential vs parallel comparison
PYTHONPATH=. python scripts/benchmark_parallelization.py
```

## Running Tests

```bash
PYTHONPATH=. pytest tests/ -v
```

Test coverage includes:
- 28 core tests (Bootstrap, Monte Carlo, Portfolio, CashFlow)
- Vectorization equivalence tests (generic path vs vectorized path)
- Bootstrap parallelization reproducibility tests
