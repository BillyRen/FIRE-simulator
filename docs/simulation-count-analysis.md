# Optimal Default Simulation Counts by Page and Server Tier

## Summary

Analysis of endpoint computational complexity and benchmarking across different `num_simulations` values to determine optimal defaults per page and server tier.

## Benchmark Results (Local High-Performance Machine, ~10 cores)

All times are wall-clock seconds for a single API call, retirement_years=40, country=USA.

| Endpoint | n=500 | n=1000 | n=2000 | n=5000 | n=10000 | Scaling |
|---|---|---|---|---|---|---|
| simulate (fixed) | 0.010 | 0.021 | 0.040 | 0.099 | 0.206 | Linear |
| sweep (vectorized) | 0.003 | 0.006 | 0.006 | 0.011 | 0.023 | Sub-linear |
| alloc-sweep (step=0.1, 66 combos) | 0.038 | 0.055 | 0.123 | 0.310 | 0.386 | Linear |
| alloc-sweep (step=0.05, 231 combos) | 0.124 | 0.169 | 0.265 | 0.651 | 1.232 | Linear |
| guardrail (no CF, 2D table) | 0.098 | 0.197 | 0.401 | 0.860 | ~1.7 | Linear |
| guardrail (with CF, 3D table) | ~0.5 | ~1.2 | ~3.1 | ~7.3 | ~9.7 | Linear |
| accumulation | 0.055 | 0.070 | ~0.10 | ~0.23 | ~0.45 | Sub-linear |
| buy-vs-rent MC | 0.038 | 0.071 | 0.136 | 0.334 | ~0.67 | Linear |

### Render Starter Estimated Times (1 CPU, 512MB, ~5-10x slower)

| Endpoint | n=500 | n=1000 | n=2000 |
|---|---|---|---|
| simulate | 0.05-0.1 | 0.1-0.2 | 0.2-0.4 |
| sweep | 0.02 | 0.03 | 0.05 |
| alloc-sweep (0.1) | 0.2-0.4 | 0.3-0.6 | 0.6-1.2 |
| alloc-sweep (0.05) | 0.6-1.2 | 0.8-1.7 | 1.3-2.7 |
| guardrail (no CF) | 0.5-1.0 | 1.0-2.0 | 2.0-4.0 |
| guardrail (+CF) | 2.5-5 | 6-12 | 15-30 |
| accumulation | 0.3-0.6 | 0.4-0.7 | 0.5-1.0 |

## Key Findings

### 1. Computation costs vary 100x+ across pages
- **Lightest**: sweep (vectorized, nearly free after bootstrap)
- **Heaviest**: guardrail+CF (3D lookup table dominates, ~50-100x vs simulate)

### 2. All costs scale linearly with num_simulations
- Exception: sweep and accumulation have sub-linear scaling due to fixed-cost portions (vectorized sweep, fixed SWR binary search at 500 sims)

### 3. Two distinct cost tiers
- **Standard** (simulate, sweep, sensitivity, accumulation, buy-vs-rent): Single bootstrap + single MC pass. Comfortable at n=2000-5000 even on weak hardware.
- **Heavy** (guardrail, allocation sweep): Multiple table builds or sweep iterations multiplied by n. Need lower n on constrained servers.

### 4. Guardrail 3D table is the bottleneck
- At n=2000, guardrail+CF takes ~3s locally, ~15-30s on Render Starter
- The 3D table computation is O(170 rates x 15 cf_scales x n x retirement_years)
- This is the only endpoint where n=2000 risks timeout on free-tier hosting

## Recommended Defaults

### Server Tier Classification
| Tier | Cores | Memory | Examples |
|---|---|---|---|
| low | <= 2 | <= 1 GB | Render Starter, Railway free |
| mid | <= 4 | <= 4 GB | Render Standard, small VPS |
| high | > 4 | > 4 GB | Dedicated server, local dev |

### Recommended sim counts by page type and tier

| Category | Pages | Low | Mid | High |
|---|---|---|---|---|
| default | simulate, sweep, sensitivity, accumulation, buy-vs-rent | 1,000 | 2,000 | 5,000 |
| guardrail | guardrail (all sub-endpoints) | 500 | 1,000 | 2,000 |
| allocation | allocation sweep | 500 | 1,000 | 2,000 |

### UX Target Response Times
- Quick response (main simulate, sweep): < 1s
- Normal response (sensitivity, accumulation): < 3s
- Heavy response (guardrail, allocation): < 8s
- Maximum acceptable: < 15s

## Implementation

### Backend: `/api/defaults` endpoint
Returns per-category recommendations:
```json
{
  "tier": "low",
  "cores": 1,
  "memory_gb": 0.5,
  "recommended_sim_counts": {
    "default": 1000,
    "heavy": 500,
    "guardrail": 500,
    "allocation": 500
  }
}
```

### Frontend: `getSimCount(category)` in params-context
- `getSimCount("default")` → returns `params.num_simulations` as-is
- `getSimCount("guardrail")` → returns `Math.min(params.num_simulations, serverCap)`
- `getSimCount("allocation")` → returns `Math.min(params.num_simulations, serverCap)`
- If server defaults haven't loaded yet, falls back to `params.num_simulations`

### Behavior
- **New user**: first visit auto-applies `default` recommendation from server
- **Returning user**: persisted `num_simulations` is respected; heavy pages silently cap to server recommendation
- **User manually sets high value**: heavy pages cap protects from timeout; user's explicit choice on standard pages is honored
