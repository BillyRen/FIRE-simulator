# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FIRE (Financial Independence, Retire Early) retirement simulator. Monte Carlo simulation tool using historical market data (1871-2025) with Block Bootstrap sampling. Chinese/English bilingual.

**Live**: Frontend at https://fire.rens.ai (Vercel), Backend API on Render.

## Commands

### Backend (FastAPI + Python)
```bash
cd backend && pip install -r requirements.txt
uvicorn main:app --port 8000              # run API server
```

### Frontend (Next.js 16 + React 19)
```bash
cd frontend && npm install
npm run dev                                # http://localhost:3000
npm run build                              # production build
npm run lint                               # eslint
```

### Tests
```bash
pytest tests/                              # all tests
pytest tests/test_core.py                  # core engine tests
pytest tests/test_api.py                   # API integration tests
pytest tests/test_statistics.py            # statistics module tests
pytest tests/test_core.py::TestBlockBootstrap::test_output_shape  # single test
```

### CI/CD
- `.github/workflows/ci.yml` — pytest + eslint + next build on push/PR

## Architecture

### Two-tier: FastAPI backend + Next.js frontend

**Backend** (`backend/`):
- `main.py` — All REST API endpoints. Imports and orchestrates the simulator engine.
- `schemas.py` — Pydantic request/response models. `BaseSimulationParams` is the shared base class for most endpoints.

**Simulator engine** (`simulator/`): Pure Python computation library at repo root, no web dependencies.
- `bootstrap.py` — Block Bootstrap sampling (single-country and pooled multi-country)
- `monte_carlo.py` — Core MC simulation loop (`run_simulation`)
- `portfolio.py` — Portfolio return calculation (asset allocation, expense ratios, leverage)
- `cashflow.py` — Custom cash flow scheduling (probabilistic groups, inflation adjustment)
- `guardrail.py` — Risk-based guardrail withdrawal strategy with success-rate lookup tables
- `sweep.py` — Sensitivity analysis (withdrawal rate sweep, asset allocation sweep)
- `statistics.py` — Batch percentile calculation, funded ratio metrics
- `backtest_batch.py` — Historical backtesting across all country/start-year combinations
- `buy_vs_rent.py` — Buy vs rent comparison (simple deterministic + MC)
- `accumulation.py` — FIRE accumulation phase calculator
- `data_loader.py` — Loads `data/jst_returns.csv` (JST multi-country) and `data/FIRE_dataset.csv` (US-only)
- `config.py` — Global constants (guardrail grid steps, GDP weights, default parameters)

**Frontend** (`frontend/`):
- Next.js App Router with 7 pages: main simulator (`/`), sensitivity (`/sensitivity`), guardrail (`/guardrail`), allocation (`/allocation`), buy-vs-rent (`/buy-vs-rent`), accumulation (`/accumulation`), dashboard (`/dashboard`)
- `src/lib/api.ts` — API client, all backend calls
- `src/lib/types.ts` — TypeScript type definitions mirroring `schemas.py`
- `src/lib/params-context.tsx` — React context for shared simulation parameters across pages
- `src/lib/use-persisted-state.ts` — localStorage persistence hook (60+ instances across pages)
- `src/lib/use-api-call.ts` — Generic API call hook with loading/error state
- `src/lib/pdf-export.ts` — PDF report generation
- `src/components/` — Shared UI components (fan charts via Plotly, sidebar forms, stats tables, scenario manager)
- `messages/en.json`, `messages/zh.json` — i18n translations via `next-intl`
- UI: Tailwind CSS + Radix UI primitives (`src/components/ui/`)

**Tests** (`tests/`):
- `test_core.py` — Core engine: bootstrap, MC simulation, portfolio, cashflow, sweep, guardrail
- `test_statistics.py` — Statistics module: funded ratio, percentiles, metrics
- `test_api.py` — API integration tests against FastAPI endpoints
- `test_vectorization_equivalence.py` — Validates vectorized code matches scalar implementations
- `test_bootstrap_parallelization.py` — Bootstrap parallel execution tests

### Data flow
1. Frontend sends typed request to FastAPI endpoint
2. Backend validates via Pydantic schema, calls simulator functions
3. Simulator uses Block Bootstrap to sample from historical returns, runs MC paths
4. Results returned as percentile trajectories, success rates, funded ratios

### Key patterns
- Multi-country pooling: when `country="ALL"`, bootstrap draws from 16 countries weighted by sqrt(GDP)
- Cash flows support probabilistic groups (mutually exclusive events with probability weights)
- Guardrail strategy uses precomputed success-rate lookup tables for real-time adjustments
- All monetary values in responses are real (inflation-adjusted) dollars
- All pages use `"use client"` — no SSR concerns for component state

### JST data extension (2021-2025)
- JST R6 official data ends at 2020; years 2021-2025 are an unofficial extension using IMF/OECD/yfinance
- Extension scripts: `scripts/extend_jst_2021_2025.py` -> `scripts/build_dataset_from_jst.py` -> `scripts/validate_jst_extension.py`
- **Critical methodology**: see `scripts/DATA_UPDATE_GUIDE.md` for annual-average equity pricing, Eurozone legacy currency conversion, and other pitfalls

## Conventions
- Commit messages: concise, prefixed with type (`feat:`, `fix:`, `perf:`, `refactor:`, `test:`, `docs:`)
- Language: code and comments in English; UI text via i18n (zh/en)
- Backend: Python 3.x, numpy for vectorized computation, avoid Python loops on large arrays
- Frontend: TypeScript strict, functional components, React hooks

## Environment Variables
- Backend: `ALLOWED_ORIGINS` (CORS), `PYTHON_VERSION`
- Frontend: `NEXT_PUBLIC_API_URL` (backend URL)
