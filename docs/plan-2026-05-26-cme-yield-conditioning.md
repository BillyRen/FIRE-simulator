# Implementation Plan — CME Forward CMA + Starting-Yield Conditional Bootstrap

**Date**: 2026-05-26
**Author**: Claude Code (FIRE_simulator project)
**Status**: Draft v1.3 — Codex plan critique fully integrated
**Round 2 dependency**: this plan must be approved before any code is written.

**Codex review status (2026-05-26)**:

Three Codex passes total. The third (direct `codex exec` invocation, bypassing review-loop's code-review template) finally reviewed the plan content. Critique saved to `reviews/codex-plan-critique-2026-05-26.md`. v1.3 integrates all High-severity findings and most Medium findings:

| Finding | Severity | Integrated in v1.3 |
|---|---|---|
| §4.2 asset mapping breaks for non-US investors (user's allocation weights still apply downstream) | **High** | §4.2 rewritten to introduce `cme_mapping_profile` enum |
| §5.3 real yield formula uses ex-post realized inflation (information leakage) | **High** | §5.3 changed to trailing 3-yr inflation; framing softened (BFP used yield + CAPE, not "real yield" explicitly) |
| §4.6.3 missed `simulator/buy_vs_rent.py:349,354` bootstrap call sites | **High** | §4.6.3 touch list expanded; verified via grep |
| Schema propagation: `BuyVsRentMCRequest` inherits `BuyVsRentBaseParams`, NOT `BaseSimulationParams` | **High** | New §4.7.1.1 covers schema inheritance map and explicit propagation strategy |
| §9 hardcoded mapping = §4.2 issue (same root) | **High** | Resolved via mapping profiles in §4.2 |
| Inflation priors fixed but not versioned/sensitivity-tested | Medium | §4.1 adds `INFLATION_PRIOR_VERSION` constant + sensitivity diagnostic test |
| `arith_20yr` should not auto-switch on `retirement_years` | Medium | §4.3 keeps `arith_20yr` as fixed default |
| Per-country yield diagnostics needed in response | Medium | §6.4 model_diagnostics extended with per-country match counts |
| Arithmetic MVN sampling — add geometric consistency test | Medium | §7.1 adds `test_compounded_geometric_consistency` |
| Snapshot equivalence: version pinning + no-filter RNG-consumption test | Medium | §7.3 strengthened; PR-0 captures fixture before any functional change |
| First-block-only methodology framing | Medium | §5.1 + i18n text clarified — it conditions opening block, not full BFP-style |
| PSD repair: report magnitude + repair correlation then re-scale | Medium | §4.1 expanded; uses Higham for non-trivial repair |
| Statistical test tolerance 1σ/√N → 3-5σ/√N | Medium | §7.1 tolerance widened |
| Property-based tests for yield mask | Medium | §7.2 adds Hypothesis-based mask tests |
| Performance: `np.flatnonzero` per simulation | Medium | §5.5.2 algorithm changed to precompute `valid_starts` once per request |
| MCP parity insufficient; need separate schema | Medium | §4.6.5 expanded — MCP shared Pydantic adapter |
| Error code 400 vs 422 inconsistency between §6.6 and §7.4 | Low | §6.6 standardized on 422 (matches FastAPI validation default); §7.4 confirmed |
| PR-0 should include equivalence fixture harness | Low | §8 reordered |
| i18n precision around "real yield" (Chinese) | Low | §5.8 i18n strings updated with explicit nominal/inflation breakdown |
| `arith_20yr` vs `arith_10yr` no auto-switch | Low | §4.3 confirmed as fixed default |
| Guardrail hard-reject contradictory text (was "guardrail simulation yes" elsewhere) | Low | §5.7.2 corrected to clarify yield filter (B) applies; CME mode (A) is rejected |

**§9** is renamed from "Open Questions" → "Resolved Design Decisions" and now contains the resolved verdicts with rationale.

---

## 1. Motivation & Methodology Context

### 1.1 Why we are doing this

The simulator's current return engine is an **unconditional historical Block Bootstrap** over JST 1871-2025 (single country) or 16-country GDP-weighted pool. This is robust against survivor bias and includes wartime tail events, but it suffers a known **methodological gap** identified by Blanchett, Finke & Pfau (2014), *"Asset Valuations and Safe Portfolio Withdrawal Rates,"* *Retirement Management Journal* 4(1):21-34:

> *The starting market valuation at retirement (bond yield + equity CAPE) is conditional information that should not be marginalized out of the simulation. Sampling uniformly from history implicitly assumes the retiree faces the historical average yield/valuation regime — which can be far from the truth.*

The B-F-P paper estimated that under 2013 conditions (10y T-Note 2.0%, CAPE 22), a 4% / 30y rule's MC success rate dropped from ~90% (unconditional) to **48%** (conditional). The actionable insight: **the user's tool should expose forward-looking and yield-conditional views as first-class alternatives**, not as ad-hoc analyses.

Two improvements implement this in the cheapest way possible without rewriting the simulator's stochastic engine:

### 1.2 The two interventions

**(A) CME Horizon 2025 parametric MC** — activate the already-imported but unused 41-firm consensus CMA as an *alternative* data source. Use multivariate normal sampling on the published mean vector + covariance matrix to generate return paths. This delivers a **forward-looking baseline** that B-F-P's GMM machinery would otherwise require us to estimate.

**(B) Starting-yield conditional filter** — restrict the first sampled historical block to years whose `Long_Rate` falls within a user-specified percentile band of the country's (or pool's) yield distribution. This is a lightweight conditional bootstrap that preserves the rest of the engine but anchors the *opening* macro regime to today's environment.

Together, A + B give the user three coherent views (historical unconditional / historical conditional on yield / forward consensus) that should converge in their SWR recommendation when the inputs are well-calibrated.

### 1.3 Connection to the user's existing recommendation

Per `memory/cme-horizon-2025-validates-jst-pool.md`, the JST 16-country pool's 60/40 real return (3.23%) is within 0.8 pp of CME Horizon 2025's 4.04% — i.e., the pool is **already** approximately valuation-humble. The goal of this work is not to *change* the recommendation but to **let the user verify** it from two independent vantage points, which is the same epistemic discipline B-F-P (2014) advocated.

---

## 2. Scope

### 2.1 In-scope

| # | Item | Module |
|---|------|--------|
| A1 | Load CME Horizon 2025 CMA into memory, expose mean vec + cov mat | `simulator/cma_loader.py` (NEW) |
| A2 | Parametric sampler that produces a `(retirement_years, 4)` array shape-compatible with bootstrap output | `simulator/cma_loader.py` |
| A3 | Wire `data_source="cme_horizon_2025"` through `BaseSimulationParams` and all derived request schemas | `backend/schemas.py` |
| A4 | Route sampler selection in `monte_carlo.py` / `sweep.py` so CME mode bypasses bootstrap | `simulator/monte_carlo.py`, `simulator/sweep.py` |
| A5 | Frontend data-source toggle: add "CME Horizon 2025" option, conditionally hide country/pooling/data_start_year fields when selected | `frontend/src/components/sidebar-form.tsx`, `frontend/src/lib/types.ts` |
| A6 | Add `/api/countries` and `/api/defaults` to return appropriate fallback metadata for CME source | `backend/deps.py`, `routes/common.py` |
| A7 | i18n strings for the new data source | `frontend/messages/{en,zh}.json` |
| A8 | MCP tool schemas updated to surface new params (data_source, yield filter) with parity validation | `mcp_server/tools.py`, `mcp_server/helpers.py` |
| A9 | Side-task: fix `scripts/import_horizon_cma.py` to validate-before-write (per Codex finding #5; small atomic-rename fix, parallel commit) | `scripts/import_horizon_cma.py` |
| B1 | Add `starting_yield_percentile_range: tuple[float, float] \| None` to `BaseSimulationParams` | `backend/schemas.py` |
| B2 | Compute per-country `Long_Rate` percentile thresholds; cache | `backend/deps.py` |
| B3 | Implement `block_bootstrap_np` / `block_bootstrap_pooled_np` first-block filter | `simulator/bootstrap.py` |
| B4 | Frontend UI: optional control with 3 presets + custom range | `frontend/src/components/sidebar-form.tsx` |
| B5 | i18n strings | `frontend/messages/{en,zh}.json` |
| C1 | Unit tests for both features | `tests/test_cma_sampler.py` (NEW), `tests/test_core.py` (extend) |
| C2 | Integration test: end-to-end API call with each new param | `tests/test_api.py` (extend) |
| C3 | Equivalence tests: backward compatibility — existing requests produce identical results | `tests/test_perf_equivalence.py` (extend) |

### 2.2 Explicitly out-of-scope (deferred to future rounds)

| # | Item | Reason for deferral |
|---|------|---------------------|
| OOS-1 | Shiller CAPE-conditional starting state | Requires new dataset; multi-country applicability is unclear |
| OOS-2 | Black-Litterman style historical + CMA blend (`forward_view_weight` param) | Worth doing after we observe how often users pick which mode |
| OOS-3 | Mean-reversion of yield/CAPE over the simulation horizon (full B-F-P VAR) | Materially more complex; the parametric CMA + yield filter already cover ~80% of B-F-P's signal |
| OOS-4 | Conditional filter on **all** sampled blocks (not just first) | Statistically harder to justify; first-block conditioning is the canonical interpretation |
| OOS-5 | CME source for guardrail lookup table construction | Guardrail tables are precomputed and not regenerated per-request; adding a CME variant requires a separate offline cache strategy. Phase 2. |
| OOS-6 | CME source for the historical *backtest* page | Backtest is inherently single-historical-path; CMA has no temporal axis |
| OOS-7 | CME source for buy-vs-rent (requires housing return; CMA only has Real Estate as a class, not the housing-rent series the simulator uses) | Requires modeling assumptions out of scope |
| OOS-8 | Importing Horizon **2026** edition when published | Trivial follow-up; same `import_horizon_cma.py` script handles it |
| OOS-9 | Generalizing the conditional filter to filter on the **average** Long_Rate across the entire sampled path | Statistically harder, not what B-F-P proposed |

---

## 3. Architecture Overview

### 3.1 Current control flow (for context)

```
HTTP request
  → Pydantic validation (backend/schemas.py)
  → resolve_data() in deps.py  → returns (filtered_df, country_dfs|None)
  → simulator.monte_carlo.run_simulation_engine()
      → loop over num_simulations:
          sampled_np = block_bootstrap_np(...)         ← shape (T, 4)
          real_returns = compute_real_portfolio_returns_np(sampled_np, ...)
```

### 3.2 Proposed control flow (additions in **bold**)

```
HTTP request
  → Pydantic validation (data_source ∈ {jst, fire_dataset, cme_horizon_2025},
                          starting_yield_percentile_range optional)
  → **dispatch on data_source**:
        if data_source in {jst, fire_dataset}:
             resolve_data()  → (filtered_df, country_dfs|None)
             **resolve_yield_filter()  → indexer ∩ year mask (B)**
        else  (cme_horizon_2025):
             **load_cma_sampler()  → CmaSampler object**
  → simulator.monte_carlo.run_simulation_engine(sampler_or_dfs)
      → loop over num_simulations:
          if sampler is CmaSampler:
               sampled_np = sampler.draw(T, rng)         ← shape (T, 4)
          else:
               sampled_np = block_bootstrap_np(
                   ..., starting_year_mask=...           ← B
               )
          real_returns = compute_real_portfolio_returns_np(sampled_np, ...)
```

### 3.3 Key design principle: **shape-compatible at the boundary**

The CmaSampler's `.draw(T, rng)` returns the **same numpy shape `(T, 4)` with the same column semantics** as `block_bootstrap_np`: `[Domestic_Stock, Global_Stock, Domestic_Bond, Inflation]`, **all nominal**. This means **downstream code in `compute_real_portfolio_returns_np`, glide-path logic, withdrawal strategies, etc. is unmodified**. This is the central invariant of the design.

---

## 4. Part A — CME Horizon 2025 Forward-Looking CMA

### 4.1 Data model

**Source files** (already exist):
- `data/cme/horizon_2025_assets.csv` — 18 rows (17 assets + Inflation). Columns: `index, asset, arith_10yr, geom_10yr, arith_20yr, geom_20yr, std_dev`. All values are decimals (not percent).
- `data/cme/horizon_2025_corr.csv` — 17×17 symmetric correlation matrix (assets only; **Inflation excluded by Horizon convention**).

**Critical issue**: Inflation has no correlation row in the source matrix. We must impute Inflation correlations.

**Resolution**: Build a 4×4 sub-matrix for the 4 columns we sample (Dom_Stock, Global_Stock, Dom_Bond, Inflation):
- The 3×3 sub-block for `(Dom_Stock, Global_Stock, Dom_Bond)` comes directly from CME correlations after asset mapping.
- Inflation row/column: hard-code **empirically-defensible priors**, **versioned** (per Codex Medium finding) as `INFLATION_PRIOR_VERSION = "v1-2026-05"`:
  - corr(Inflation, US Equity) = **−0.10** (Fama 1981; updated by Wachter 2002 — modest negative)
  - corr(Inflation, Non-US Equity) = **−0.05** (less pronounced due to currency)
  - corr(Inflation, US Bonds) = **−0.30** (canonical bond/inflation hedge breakdown; Bekaert & Wang 2010)
- Constants and citations live in `simulator/cma_loader.py`; the version string is emitted in `model_diagnostics` (§6.4) so any change is traceable.

**Sensitivity test** (`test_inflation_prior_sensitivity` in §7.1): perturbing each prior by ±0.10 and rerunning a fixed-seed simulation should produce SR drift within a tabulated tolerance (~±0.5 pp). If a future revision breaches the tolerance, the test forces the maintainer to bump `INFLATION_PRIOR_VERSION` consciously.

**v1.3 PSD repair strategy (per Codex Medium finding):** v1.1 said "clip negative eigenvalues to 0, reconstruct". That's only safe for trivial repairs. Refined approach:

1. Compute `eigvals, eigvecs = np.linalg.eigh(corr)`.
2. If `eigvals.min() >= -1e-10`: no repair, return as-is.
3. If `eigvals.min() >= -1e-4`: clip negatives to `0`, reconstruct, **rescale diagonal to 1** (since clipping breaks unit diagonal), then re-derive cov from corr × std outer-product.
4. If `eigvals.min() < -1e-4`: use **Higham's nearest-correlation-matrix algorithm** (`scipy.linalg` doesn't ship it; implement the 30-line iteration or vendor `statsmodels.stats.correlation_tools.cov_nearest`).
5. Always emit `cme_psd_repair_norm = np.linalg.norm(corr_repaired - corr_original, ord='fro')` in `model_diagnostics`. If `> 0.01`, log at WARNING level — repair magnitude is non-negligible and the asset mapping should be reviewed.

### 4.2 Asset mapping — CME 17 assets → 4 simulator columns

**v1.3 redesign (per Codex critique High-severity finding):** the v1.1 mapping was unsound for non-US investors. The simulator applies the user's `allocation = {domestic_stock, global_stock, domestic_bond}` weights *downstream* of the sampler. If a China resident enters `{10%, 80%, 10%}` (matching their IWDA/VWRA holdings as ACWI-ex-CN), CME mode under the old mapping would produce **10% US Large Cap + 80% Non-US** — NOT a cap-weighted ACWI exposure. The "60% US ≈ ACWI" rationalization conflated the *user's portfolio* with the *simulator's column semantics*.

**v1.3 solution: named mapping profiles.** Add `cme_mapping_profile: str` parameter, defaulting to `"us_investor"`, with at minimum the following profiles:

#### Profile `us_investor` (default; the v1.1 mapping)

| Simulator column | CME asset(s) | Weights |
|---|---|---|
| Domestic_Stock | `US Equity - Large Cap` | 100% |
| Global_Stock | `Non-US Equity - Developed`, `Non-US Equity - Emerging` | 80% / 20% |
| Domestic_Bond | `US Corporate Bonds - Core`, `US Treasuries (Cash Equivalents)` | 60% / 40% |
| Inflation | `Inflation` | 100% |

**Use case:** US-based investor with home-country bias (US Large Cap = home).

#### Profile `acwi_proxy` (recommended for non-US ACWI ETF holders like the project user)

Both `Domestic_Stock` and `Global_Stock` map to a **synthetic ACWI cap-weighted equity**:
- Mean: `0.60 × US_Large + 0.10 × US_SmallMid + 0.24 × Non_US_Developed + 0.06 × Non_US_Emerging` (approximates MSCI ACWI cap weights as of 2026)
- Variance: `w' Σ w` over the 4-asset sub-matrix
- `Domestic_Stock` and `Global_Stock` get **identical** returns each year (perfectly correlated by construction)
- `Domestic_Bond`: same as `us_investor` profile (US Agg proxy)
- `Inflation`: same

**Use case:** non-US investor holding IWDA / VWRA / SPGM / similar single-product ACWI ETFs. Whatever `allocation` weights the user enters for `domestic_stock` + `global_stock` are summed into total equity exposure with cap-weighted ACWI return characteristics. This **decouples** the user's allocation-mix UI from the simulator's column semantics.

#### Profile `developed_world_60_40` (alternative for hedged DM-only investors)

Use `MSCI World` proxy = 70% US Large + 30% Non-US Developed (no EM). Domestic = Global = this composite.

**Composite-column variance:** for composite columns (multi-CME-asset weighted averages), **mean = w · μ**; **cov = w · Σ_sub · wᵀ** using the published correlation sub-matrix scaled to covariance via the diagonal of std_devs. Standard portfolio-of-portfolios calculation.

**Frontend implication:** when `data_source == "cme_horizon_2025"`, the sidebar shows the `cme_mapping_profile` dropdown (with help text explaining when to pick which). For the project user (China resident, IWDA), the frontend can pre-select `acwi_proxy` if `data_source` switches to CME for the first time (a one-time heuristic; respects later user choice). The previous v1.1 default of `us_investor` for non-US users is **wrong** and is corrected here.

**Performance & cache:** `CmaSampler` instances are keyed by `(edition, mapping_profile)` in the LRU cache. With 3 profiles × 1 edition, max 3 entries.

### 4.3 Arithmetic vs geometric — which to sample

**Decision: use `arith_20yr`**, not geometric.

Rationale:
1. Multivariate normal sampling produces arithmetic returns; mean of MVN is arithmetic by construction.
2. Horizon publishes both because geometric is what compounds over time, but if you draw arithmetic returns and then compound them, you naturally get the geometric mean — this is a known identity (Jensen's gap = ½ σ² for log-normal). **Using geometric mean as the MVN mean would systematically under-estimate compounded return**.
3. 20-year horizon matches the typical FIRE planning horizon (30-65 years) better than 10-year. Document this trade-off in the loader.

### 4.4 Sanity check vs JST pool

`simulator/cma_loader.py` should print a one-time summary on first load (DEBUG level) showing the 4-column mean / std / correlation, so during dev / smoke we can confirm:

| Column | CMA 20-yr arith | JST Pool 1900+ historical arith |
|---|---|---|
| Dom_Stock | ~8.3% | ~6.7% |
| Global_Stock | ~9.0% (weighted) | ~9.8% |
| Dom_Bond | ~5.3% | ~1.2% |
| Inflation | ~2.4% | varies, ~3% |

(These are illustrative; exact numbers verified at impl time.) Note that **CME means are nominal**, matching JST. The existing `compute_real_portfolio_returns_np` will deflate by Inflation downstream.

### 4.5 New module: `simulator/cma_loader.py`

**File-level API**:

```python
# Constants (with academic citations as comments)
INFLATION_PRIORS: dict[str, float]   # cor(Inflation, *)

@dataclass(frozen=True)
class CmaSampler:
    mean: np.ndarray         # shape (4,), nominal arithmetic
    cov: np.ndarray          # shape (4, 4), PSD
    cholesky: np.ndarray     # shape (4, 4), pre-decomposed
    source_label: str        # e.g. "horizon_2025"
    asset_mapping: dict      # for introspection / debugging

    def draw(self, T: int, rng: np.random.Generator) -> np.ndarray:
        """Draw T years of returns. Returns shape (T, 4)."""

def load_cma_sampler(edition: str = "horizon_2025") -> CmaSampler:
    """Load and cache CMA from data/cme/horizon_<edition>_*.csv."""
```

**Implementation notes**:
- Cache the `CmaSampler` instance globally (`functools.lru_cache` on `edition`).
- `.draw()` uses `rng.standard_normal((T, 4)) @ cholesky.T + mean` — vectorized, ~50× faster than `rng.multivariate_normal((T,))`.
- **Load-time validation is mandatory and serves as last-line-of-defense**: `cov` PSD (with nearest-PSD repair fallback), mean values in plausible range (|mean|<0.5), std in (0, 0.5), at least 4 non-Inflation assets matchable by name. Rationale: per Codex review of `scripts/import_horizon_cma.py:288`, the upstream import script writes generated CSVs **before** running its own validation, meaning malformed CSVs can land in `data/cme/`. Loader must not trust the file unconditionally. If validation fails, raise with a clear remediation hint pointing back to `scripts/import_horizon_cma.py` and the offending field.
- Raise `FileNotFoundError` with clear message if `data/cme/horizon_<edition>_assets.csv` missing.
- **Round 2 side-task** (small): fix the import script to write to a temp file and atomically rename only after validation passes (separate commit, would close Codex finding #5 directly).

### 4.6 Backend integration

#### 4.6.1 `backend/schemas.py`

Modify `BaseSimulationParams.data_source`:

```python
data_source: str = Field(
    "jst",
    pattern="^(jst|fire_dataset|cme_horizon_2025)$",
    description="...|cme_horizon_2025=Horizon Actuarial 2025 forward CMA",
)
```

Cross-field validator addition (`@model_validator(mode='after')`):

- If `data_source == "cme_horizon_2025"`:
  - `country` must equal `"USA"` or be `"ALL"` (we'll normalize internally; surfaced for the frontend's existing logic). **Decision: silently coerce to `"USA"` in backend**, since CMA is country-agnostic.
  - `pooling_method` is ignored (irrelevant for parametric MC).
  - `data_start_year` is ignored.
  - `starting_yield_percentile_range` MUST be `None` (raise 400 if set — yield filter only applies to historical bootstrap).
  - `min_block` / `max_block` ignored.

#### 4.6.2 `backend/deps.py`

Add a `resolve_sampler(req)` function:

```python
def resolve_sampler(req) -> CmaSampler | None:
    """If data_source is CMA-based, return a CmaSampler. Else None."""
    ds = getattr(req, "data_source", "jst")
    if ds == "cme_horizon_2025":
        return load_cma_sampler("horizon_2025")
    return None
```

Modify `resolve_data(req)`:

- When `data_source == "cme_horizon_2025"`: return `(pd.DataFrame(), None)` (empty df, no country_dfs). The downstream simulator code paths must handle the empty-df case via the new sampler argument.
- Otherwise: unchanged.

#### 4.6.3 Simulator-side touchpoints (engine bootstrap call sites)

**Touchpoints** (per current code as of 2026-05-26, verified by grep at v1.3 review):

- `simulator/monte_carlo.py:329-336` and `:548-555` — the two `if c_arrays is not None: block_bootstrap_pooled_np else block_bootstrap_np` dispatch blocks
- `simulator/sweep.py:55-65` — `_do_bootstrap_np`
- **`simulator/buy_vs_rent.py:349, 354`** — direct calls to `block_bootstrap_pooled_np` and `block_bootstrap_np` (**added in v1.3 per Codex finding**; missed in v1.1's touch list)

Per OOS-7, buy_vs_rent **rejects** `data_source="cme_horizon_2025"`. **However**, the **yield filter (B) still applies** to buy_vs_rent's bootstrap calls — so the new signature (with `starting_year_mask`) must reach these call sites. Add `buy_vs_rent.py` to PR-2's touch list. Equivalence test (§7.3) must include a buy_vs_rent baseline path to prove behavior is preserved when no filter is set.

**Refactoring recommendation (per Codex finding):** rather than hand-patching 3 modules with the same dispatch pattern, extract a shared adapter in a new module `simulator/sampling.py` that wraps the bootstrap/CMA dispatch and is imported by all three. This keeps `monte_carlo.py`, `sweep.py`, and `buy_vs_rent.py` clean and ensures any future call site automatically inherits the behavior. The adapter signature:

```python
def sample_returns(
    *, sampler: CmaSampler | None,
    src_data: np.ndarray | None, src_n: int,
    c_arrays, c_lens, c_probs,
    retirement_years: int, min_block: int, max_block: int,
    rng: np.random.Generator,
    starting_year_mask: np.ndarray | None = None,
    starting_year_mask_per_country: list[np.ndarray] | None = None,
) -> np.ndarray:
    """Returns (T, 4) array. Dispatches to CMA parametric or historical bootstrap."""
```

PR-3 introduces this adapter and refactors all three call sites to use it (one-line dispatch each).

**New dispatch pattern** (all three sites refactored identically):

```python
# Pseudocode
if sampler is not None:           # CMA mode
    sampled_np = sampler.draw(retirement_years, rng)
elif c_arrays is not None:        # JST pooled mode
    sampled_np = block_bootstrap_pooled_np(
        c_arrays, c_lens, c_probs, retirement_years, min_block, max_block,
        rng=rng, starting_year_mask=starting_year_mask_pooled,  # B
    )
else:                              # JST single-country / FIRE_dataset mode
    sampled_np = block_bootstrap_np(
        src_data, src_n, retirement_years, min_block, max_block,
        rng=rng, starting_year_mask=starting_year_mask,         # B
    )
```

Both `run_simulation_engine` (`monte_carlo.py`) and the corresponding sweep entry point gain a new optional kwarg `sampler: CmaSampler | None = None`. Pure refactor at call sites; existing callers continue to pass nothing.

#### 4.6.4 `backend/routes/*.py`

Each route's request handler that already calls `resolve_data(req)` should also call `resolve_sampler(req)` and pass the result down. Touch list (verify at implementation):

- `routes/simulate.py` (main `/api/simulate`)
- `routes/sensitivity.py`
- `routes/guardrail.py` — **CME mode disabled here** (see OOS-5); raise 400 `"Guardrail strategy not yet supported with CME data source. Use historical bootstrap."`
- `routes/buy_vs_rent.py` — **CME mode disabled** (OOS-7), same 400
- `routes/accumulation.py` — applicable, wire it
- Batch backtest: **CME mode N/A** by construction (backtest is historical-path); validator should reject.

#### 4.6.5 `mcp_server/` (MCP tools)

The MCP server exposes 5 tools (`fire_simulate`, `fire_guardrail`, `fire_sweep_withdrawal`, `fire_swr_for_target`, `fire_list_countries`) that wrap simulator entrypoints directly.

**v1.3 strengthening (per Codex Medium finding):** "parity validation" (v1.1's phrasing) is insufficient — the current MCP server **completely bypasses** Pydantic validation, so the new params need *real* schema enforcement on the MCP side, not just "mirror the values".

**Round 2 approach**: extract a shared Pydantic adapter usable from both FastAPI handlers and MCP tools:

```python
# new: backend/schemas_shared.py (or backend/api_core.py)
# Re-exports BaseSimulationParams and provides MCP-flavored variants

class McpSimulationParams(BaseSimulationParams):
    """Same validation as BaseSimulationParams but with MCP-friendly defaults."""
    pass

# In mcp_server/tools.py: replace ad-hoc dict input with
#   params = McpSimulationParams(**raw_input)
# which raises pydantic.ValidationError → caught and surfaced as MCP error
```

Specific requirements:
- Add `data_source` literal to accept `"cme_horizon_2025"`.
- Add optional `starting_yield_percentile_range` (Part B).
- Add `cme_mapping_profile` (Part A, per §4.2 v1.3 redesign).
- Apply the same cross-field validation as `BaseSimulationParams` (CME ↔ yield-filter mutual exclusion; CME mode forces certain ignored-field semantics).
- `fire_list_countries` returns a sensible placeholder (`[{iso: "USA", name_en: "(N/A — forward-looking CMA)"}]`) when `data_source="cme_horizon_2025"`.

**Note on broader MCP input-bounds gap (Codex finding #3 from round 1, Codex finding #1+#2 from round 2)**: the existing MCP tools have NO validation of `retirement_years <= 100`, `leverage <= 5`, `num_simulations > 0`, `rate_step > 0`, etc. Closing that gap is **out of scope for this plan** (orthogonal to CME / yield filter), but the shared-adapter approach above naturally fixes it as a side effect — PR-5 should commit this strengthening explicitly, then file a follow-up issue tracking remaining MCP-only validation work.

### 4.7 Frontend integration

#### 4.7.0 Schema inheritance map (v1.3 addition per Codex critique)

**High-severity finding**: not every request schema inherits from `BaseSimulationParams`. v1.1 implicitly assumed inheritance; v1.3 makes this explicit.

Current backend schemas (verified by grep on `backend/schemas.py:49,131,160,190,244,294,320,542,556,583,693`):

| Schema | Inherits from | Receives new params automatically? |
|---|---|---|
| `BaseSimulationParams` | `BaseModel` | — (source of truth) |
| `SimulationRequest` | `BaseSimulationParams` | ✅ Yes |
| `SweepRequest` | `BaseSimulationParams` | ✅ Yes |
| `GuardrailRequest` | `BaseSimulationParams` | ✅ Yes |
| `BacktestRequest` | `BaseSimulationParams` | ✅ Yes — but yield filter is meaningless here (historical single-path); add per-route validator to reject |
| `SimBacktestRequest` | `BaseSimulationParams` | ✅ Yes — same caveat |
| `SimBatchBacktestRequest` | `BaseSimulationParams` | ✅ Yes — same caveat |
| `AccumulationRequest` | `BaseSimulationParams` | ✅ Yes |
| `AllocationSweepRequest` | `BaseSimulationParams` | ✅ Yes |
| **`BuyVsRentBaseParams`** | **`BaseModel`** | ❌ **No — inherits from BaseModel directly** |
| **`BuyVsRentSimpleRequest`** | **`BuyVsRentBaseParams`** | ❌ **No** |
| **`BuyVsRentMCRequest`** | **`BuyVsRentBaseParams`** | ❌ **No** |

**Action items (PR-4):**
1. Decision needed: should buy-vs-rent get `data_source` and `starting_yield_percentile_range`?
   - For **CME mode**: NO (per OOS-7, rejected anyway)
   - For **yield filter (B)**: YES — buy-vs-rent's bootstrap should respect the same starting conditions
2. Add `starting_yield_percentile_range: tuple[float, float] | None` directly to `BuyVsRentBaseParams` (NOT to `BaseSimulationParams` propagation — explicit duplication, since the two hierarchies are independent by design).
3. For backtest schemas (historical single-path): add per-route validator that **rejects** `starting_yield_percentile_range != None` with 400 "yield filter not applicable to historical backtest (filter is for bootstrap-based simulation only)".

**Frontend implication (corrected from v1.1):** the previous "all 8 union types" framing in §4.7.1 was a shortcut. The TypeScript side should use a **shared type alias** rather than copy-paste:

```ts
// frontend/src/lib/types.ts (new at top)
export type DataSource = "jst" | "fire_dataset" | "cme_horizon_2025";

// Then every interface uses:
data_source: DataSource;
```

PR-6 replaces the 8 duplicated string-union literals with this single alias — one-line refactor, eliminates drift risk.

#### 4.7.1 `frontend/src/lib/types.ts`

Apply the shared `DataSource` type alias above. Add to `BaseSimulationParams` (and to `BuyVsRentBaseParams` separately):
```ts
starting_yield_percentile_range?: [number, number] | null
```

#### 4.7.2 `frontend/src/components/sidebar-form.tsx`

Add third option to data-source `<Select>`:

```tsx
<SelectItem value="cme_horizon_2025">{t("dataSourceCme")}</SelectItem>
```

When `p.data_source === "cme_horizon_2025"`:
- Hide: country selector, pooling_method selector, data_start_year input, min_block/max_block, **yield filter section (B)**.
- Show: a static info card with the CMA edition, asset mapping summary, and a link to "What is this?" methodology blurb (one paragraph; lives in `methodology` i18n namespace).

Wire `onChange` to coerce `country="USA"` and clear yield-filter when switching to CME.

#### 4.7.3 `frontend/src/lib/api.ts`

`fetchCountries(data_source)` — when `data_source === "cme_horizon_2025"`, the backend should return a 1-row placeholder `[{iso: "USA", name_en: "(N/A — forward-looking CMA)", ...}]` so the existing dropdown logic doesn't crash; the frontend hides the dropdown anyway.

### 4.8 i18n keys

`messages/{en,zh}.json` additions:

```json
{
  "dataSourceCme": "Forward CMA (Horizon 2025)",
  "dataSourceCmeDesc": "Horizon Actuarial 2025 Survey of Capital Market Assumptions — 41-firm consensus 20-year forward returns. Parametric Monte Carlo (multivariate normal). Use as forward-looking sanity check vs historical bootstrap.",
  "cmeAssetMapping": "Asset mapping: Domestic Stock=US Large Cap; Global Stock=80% Developed + 20% Emerging; Domestic Bond=60% Corp Core + 40% Treasuries",
  "cmeMethodNote": "This view samples returns from a multivariate normal calibrated to the CMA mean vector and 4×4 covariance. Inflation correlations use empirical priors (Bekaert & Wang 2010, Wachter 2002)."
}
```

Chinese translations mirror the structure.

---

## 5. Part B — Starting Bond-Yield Conditional Filter

### 5.1 Concept

The first sampled block's starting year is restricted to years whose `Long_Rate` lies within a user-specified percentile band of the *available* `Long_Rate` distribution.

- **Default**: `None` (no restriction; current behavior).
- **Typical use**: user sets `[0.30, 0.60]` to anchor to "moderate yield" historical regimes.
- **Preset for 2026 retiree** (current US 10y real ≈ 1.5%): percentile band approx **[0.30, 0.55]** on real yield (or [0.35, 0.50] on nominal — see §5.4).

**Why only the first block?** This matches the B-F-P (2014) methodology spirit: *initial* condition matters, then mean-reversion takes over. After the first block, the standard random-walk wrap-around continues unchanged.

### 5.2 Schema additions

`backend/schemas.py` — `BaseSimulationParams`:

```python
starting_yield_percentile_range: tuple[float, float] | None = Field(
    None,
    description="Restrict the first sampled block's starting year to years "
                "whose Long_Rate falls within this percentile band of the "
                "available distribution. None = no restriction (default).",
)

@model_validator(mode="after")
def check_yield_pct_range(self) -> "BaseSimulationParams":
    r = self.starting_yield_percentile_range
    if r is not None:
        if len(r) != 2 or not (0.0 <= r[0] < r[1] <= 1.0):
            raise ValueError(
                f"starting_yield_percentile_range must be (low, high) with "
                f"0 <= low < high <= 1, got {r}"
            )
        # Combined-validity: only allowed with historical data sources
        if self.data_source not in ("jst", "fire_dataset"):
            raise ValueError(
                "starting_yield_percentile_range only valid with historical "
                "bootstrap data sources (jst, fire_dataset)"
            )
    return self
```

### 5.3 Nominal vs real yield — which axis?

`Long_Rate` in JST is **nominal**. Conditioning on nominal mixes regimes (1981 had nominal 14% but real ~3%; 2021 had nominal 1.5% but real -1%).

**Decision: condition on a real-yield proxy**, computed as **`Long_Rate[t] - trailing_inflation[t]`** where `trailing_inflation[t] = mean(Inflation[t-3 : t])` (3-year backward window, year-t exclusive).

**v1.3 correction (per Codex critique High-severity finding):** v1.1 specified `real_yield[t] = Long_Rate[t] - Inflation[t]`, which is **ex-post** — it uses *realized* same-year inflation. That information was not available to a retiree at the start of year t and creates a subtle information leak: years with unexpected inflation shocks get bucketed in a way that wouldn't be possible in practice. The trailing-3y average is a standard ex-ante proxy for inflation expectations (Cleveland Fed methodology; cited in Faust & Wright 2013, *Handbook of Economic Forecasting* ch. 1).

**Rationale for real yield (refined):**
1. Real yield is a defensible macro regime proxy. *Note*: B-F-P (2014) themselves used **initial bond yield + CAPE** (both nominal-style state variables) — the v1.1 framing "BFP implicitly used real yield" was overstated. The plan now claims only that real-yield conditioning is a *defensible simplification* of BFP's bivariate state.
2. The user-facing UI presets explicitly say "match current real yield ~1.5%" — UI semantics should match data semantics.
3. Nominal-only conditioning would silently bias toward post-1980 disinflation regimes when set to a "moderate" band.

**Implementation note**: Compute `real_yield_proxy[t]` once on data load (cache per `(country, data_start_year)` tuple). For the first 3 years of each country's data (where the trailing window is incomplete), fall back to: years 1-2 use the available trailing mean (1 or 2 years); year 0 uses the year-0 inflation (the only ex-post case, but it's the data boundary; document explicitly). Total trailing-window-edge rows affected: < 50 across all JST countries.

**Edge case — pre-1900 inflation noise**: Some early JST years have inflation values that are very volatile (deflationary spikes). The real_yield_proxy distribution is still well-defined; we document but do not artificially trim. If users complain, a `data_start_year >= 1900` constraint is already the default.

**Documentation requirement (per Codex Low-finding):** UI tooltips and methodology blurb must explicitly say "real-yield proxy = nominal long-rate minus trailing 3-year average inflation" — not just "real yield". This avoids the implicit claim that we use ex-ante expected inflation (which would require modeling).

### 5.4 Computing the percentile mask

Per-country mode (single country selected):
- Compute the real_yield distribution **over the filtered df** (i.e., respecting `data_start_year`).
- `low, high = np.quantile(real_yield, percentile_range)`.
- Build a boolean mask `mask[i] = (real_yield[i] >= low) & (real_yield[i] <= high)`.
- Convert to **valid starting indices** for the first block.

Pooled mode (ALL countries):
- The percentile is computed **per country** independently (each country has its own yield regime).
- A starting-block draw first picks a country (per existing weighted logic), then restricts within that country's yield-filtered years.
- This is the cleanest interpretation: "match the yield environment within each historical country".

**Why per-country and not pool-wide?** Pool-wide quantile would mix Germany 1923 (negative real yield from hyperinflation) with US 2021 (also negative real yield from QE). The semantic meaning of "30th percentile" differs across countries; per-country preserves the conditional meaning.

### 5.5 Modifying `simulator/bootstrap.py`

#### 5.5.1 `block_bootstrap_np` signature

Add `starting_year_mask: np.ndarray | None = None` parameter:

- `starting_year_mask`: 1-D boolean array of shape `(n,)`. `None` = unrestricted (current behavior).
- When provided, the **first** iteration of the while loop picks `start` only from indices where `mask[start] == True`.
- Subsequent iterations are unchanged (full random over `[0, n)`).

#### 5.5.2 Implementation

**v1.3 performance correction (per Codex Medium finding):** `np.flatnonzero(starting_year_mask)` runs **once per simulation path** under the v1.1 sketch — for sweep/guardrail bulk paths this becomes a hot loop. Fix: callers must **precompute** `valid_starts` once per request and pass it (or pass the mask and let the core do it once-with-cache). The cleanest signature accepts `valid_starts` directly:

```python
def _block_bootstrap_core(
    data, n, retirement_years, min_block, max_block, rng, n_cols,
    valid_starts: np.ndarray | None = None,
):
    """
    valid_starts : np.ndarray | None
        1-D int array of allowed first-block start indices (precomputed by caller).
        None = unrestricted (current behavior).
    """
    output = np.empty((retirement_years, n_cols), dtype=np.float64)
    pos = 0
    first_block = True

    while pos < retirement_years:
        block_size = min(rng.integers(min_block, max_block + 1), retirement_years - pos)
        if first_block and valid_starts is not None:
            start = int(valid_starts[rng.integers(0, len(valid_starts))])
        else:
            start = rng.integers(0, n)
        first_block = False
        indices = np.arange(start, start + block_size) % n
        output[pos:pos + block_size] = data[indices]
        pos += block_size

    return output
```

**Public-API convenience:** the top-level `block_bootstrap_np(..., starting_year_mask=...)` still accepts a boolean mask for ergonomics — it converts to `valid_starts` **once** and threads through to the core. The core's signature uses `valid_starts` to make the per-path performance cost O(1).

**Caller responsibility** (in `deps.py`'s `resolve_yield_filter`): compute and validate `valid_starts` once per request, attach to the resolved data object, pass into `monte_carlo.run_simulation_engine` or `sweep` entry points.

#### 5.5.3 `block_bootstrap_pooled_np` signature

Add `starting_year_mask_per_country: list[np.ndarray | None] | None = None`:

- A list, one entry per country, parallel to `country_arrays`.
- `None` element → no restriction for that country.
- The whole arg `None` → no restriction for any country (current behavior).

For the first iteration: after picking `country_idx`, if the per-country mask is set, use it to constrain `start`. Subsequent iterations unchanged.

Edge case: if a country has **zero** valid starting years (e.g., the percentile band yields no matches due to data sparsity), **fall back to unrestricted for that country** with a one-time logger.warning. Rationale: dropping the country mid-simulation would distort the pool's weight; warn but proceed. This matches the simulator's general fail-loud-but-continue style.

### 5.6 Wiring through `monte_carlo.py` / `sweep.py`

`run_simulation_engine` and equivalent in sweep gain a new kwarg:

```python
starting_year_mask: np.ndarray | None = None,                          # single-country mode
starting_year_mask_per_country: list[np.ndarray] | None = None,        # pooled mode
```

In `deps.py`, add a helper `resolve_yield_filter(req, filtered_df, country_dfs)`:

```python
def resolve_yield_filter(req, filtered_df, country_dfs):
    """Returns (mask, mask_per_country) — at most one is non-None."""
    pct = getattr(req, "starting_yield_percentile_range", None)
    if pct is None:
        return None, None
    low_q, high_q = pct
    if country_dfs is not None:  # pooled
        masks = []
        for iso in country_dfs:  # preserve dict order
            df = country_dfs[iso]
            ry = (df["Long_Rate"] - df["Inflation"]).values
            lo, hi = np.quantile(ry, [low_q, high_q])
            m = (ry >= lo) & (ry <= hi)
            if not m.any():
                logger.warning(f"Yield filter yielded 0 years for {iso}, falling back to unrestricted")
                m = np.ones_like(m, dtype=bool)
            masks.append(m)
        return None, masks
    else:
        ry = (filtered_df["Long_Rate"] - filtered_df["Inflation"]).values
        lo, hi = np.quantile(ry, [low_q, high_q])
        m = (ry >= lo) & (ry <= hi)
        if not m.any():
            raise ValidationError(
                f"Yield filter [{low_q}, {high_q}] matched 0 years in selected data. "
                "Try widening the band or different data_start_year."
            )
        return m, None
```

### 5.7 Frontend integration

#### 5.7.1 `frontend/src/components/sidebar-form.tsx`

Add an optional collapsible section **"Starting Yield Filter (advanced)"**, visible only when `data_source !== "cme_horizon_2025"`:

- Toggle: enabled / disabled (default disabled).
- Preset radio group (when enabled):
  - **Match current real yield (~1.5%)** → `[0.30, 0.55]`
  - **Match low real yield (~0%)** → `[0.10, 0.35]`
  - **Match high real yield (~3%)** → `[0.65, 0.90]`
  - **Custom** → reveal two number inputs (0.0–1.0, step 0.05)
- Help text linking to a methodology one-pager explaining what conditional bootstrap means and citing B-F-P (2014).

Wire `onChange` to set `starting_yield_percentile_range` to the tuple or `null`.

#### 5.7.2 Where it applies

- Main simulator page: yes
- Sensitivity page: yes (SWR sweep should respect filter)
- Guardrail page: **yes**, with caveat — the precomputed lookup table is *not* yield-conditional (OOS-5); only the path simulation portion uses it. Document this in the UI tooltip.
- Buy-vs-rent / accumulation: not applicable (these don't use the same engine layer for portfolio returns). Verify at implementation time and either wire or explicitly skip.
- Batch backtest: **not applicable** (backtest is single-historical-path, no bootstrap).

### 5.8 i18n keys

**v1.3 i18n precision update (per Codex Low finding):** Chinese translation needs to disambiguate "real yield" — naively "实际收益率" is ambiguous (could mean "actual return"). Use full phrase **"实际长期债券收益率（名义长期利率减通胀率）"** to make the construction explicit.

English (en.json):
```json
{
  "yieldFilter": "Starting Yield Filter (advanced)",
  "yieldFilterEnable": "Anchor to historical years matching today's yield regime",
  "yieldFilterPresetCurrent": "Current real yield (~1.5% → percentile 30–55)",
  "yieldFilterPresetLow": "Low real yield (~0% → percentile 10–35)",
  "yieldFilterPresetHigh": "High real yield (~3% → percentile 65–90)",
  "yieldFilterCustom": "Custom percentile band",
  "yieldFilterHelp": "Restricts the *first* sampled block to historical years with similar real-yield proxy (nominal long-rate minus trailing 3-year average inflation). Inspired by Blanchett-Finke-Pfau (2014) conditional methodology; first-block-only is a simplification of their full state-space approach.",
  "yieldFilterTooltipGuardrail": "Note: the guardrail lookup table is precomputed and not yield-conditional; this filter only affects path simulation, not the static target-rate table."
}
```

Chinese (zh.json):
```json
{
  "yieldFilter": "起始收益率过滤（高级）",
  "yieldFilterEnable": "锚定到与当下利率环境相似的历史年份",
  "yieldFilterPresetCurrent": "当前实际长期债券收益率（约 1.5% → 分位 30–55）",
  "yieldFilterPresetLow": "低实际长期债券收益率（约 0% → 分位 10–35）",
  "yieldFilterPresetHigh": "高实际长期债券收益率（约 3% → 分位 65–90）",
  "yieldFilterCustom": "自定义分位区间",
  "yieldFilterHelp": "限制*第一个*采样区块的起始年份，使其落在实际长期债券收益率代理（名义长期利率减过去 3 年平均通胀率）相近的历史年份。简化自 Blanchett-Finke-Pfau (2014) 的条件化方法——仅条件化首块，非完整状态空间模型。",
  "yieldFilterTooltipGuardrail": "注：护栏查找表是预计算的，不随收益率条件变化；本过滤器仅影响路径模拟，不影响静态目标率表。"
}
```

---

## 6. Common Considerations

### 6.1 Backward compatibility matrix

| Existing request | After A+B merge | Identical output? |
|---|---|---|
| `data_source=jst, country=USA, no yield filter` | Same params | **Must be byte-identical** (with same `seed`) |
| `data_source=jst, country=ALL, pooling=gdp_sqrt` | Same params | **Must be byte-identical** |
| `data_source=fire_dataset` | Same params | **Must be byte-identical** |
| `data_source=jst, starting_yield_percentile_range=None` | Same params (explicit None) | **Must be byte-identical** to omitting |

Equivalence test (§7.2 below) enforces this.

### 6.2 Performance

- **CME parametric mode**: ~50× faster than bootstrap (no DataFrame indexing). Expected sub-second for 10K sims × 50 years.
- **Yield filter**: adds O(n) mask computation once per request (cached if possible by `(data_source, data_start_year, country, percentile_range)` tuple in `deps.py`). Per-iteration cost: O(1) lookup. **Negligible** perf impact.

### 6.3 Rollout / feature flag

**Approach**: no feature flag — both are additive and gated by explicit parameter values. Risk profile:
- A user without the new params sees zero behavior change.
- A user opting in to `data_source="cme_horizon_2025"` or setting `starting_yield_percentile_range` gets the new behavior.

If risk averse, alternative: an env var `FIRE_ENABLE_CME=1` and `FIRE_ENABLE_YIELD_FILTER=1` checked at API boundary (returning 400 if attempted while disabled). **Recommendation: don't add the flag**; the feature is too well-isolated to warrant operational complexity. Roll back via git revert if needed.

### 6.4 Observability

- `simulator/cma_loader.py` logs at INFO level on first cache miss: which edition loaded, mapping profile, the 4×4 mean/std/corr summary, PSD eigenvalue range, Higham repair magnitude (Frobenius norm; 0 if no repair).
- `deps.resolve_yield_filter` logs at INFO level: percentile band, resulting year counts per country (or for single country, the year range of matched years).
- **v1.3 expanded model_diagnostics** (per Codex Medium finding) — response field returned by all simulation endpoints:

```python
model_diagnostics: {
    data_source: str,                     # "jst" | "fire_dataset" | "cme_horizon_2025"
    cme_mapping_profile: str | null,      # only when data_source=cme_horizon_2025
    cme_psd_repair_norm: float | null,    # Frobenius norm of PSD repair, 0 if no repair needed
    inflation_prior_version: str | null,  # e.g. "v1-2026-05"; for traceability of forward-MC results
    yield_filter_active: bool,
    yield_filter_percentile_range: [float, float] | null,
    yield_filter_per_country_match_counts: dict[str, int] | int | null,
       # Per-country: dict like {"USA": 44, "JPN": 12, ...}
       # Single-country: int like 44
       # Disabled: null
    yield_filter_fallback_countries: list[str],  # countries where filter yielded 0 matches and fell back to unrestricted
}
```

The frontend displays a "Diagnostics" expand panel under the main results, showing matched-year counts so users see *which* historical regimes the simulation was anchored to. This addresses Codex's note that "GDP-weighted countries with sparse data may silently dominate or vanish".

### 6.5 Caching

- `_returns_cache`, `_country_dfs_cache`, etc. are unchanged.
- New cache: `_cma_sampler_cache: dict[str, CmaSampler]` keyed by edition string.
- Yield filter masks are **not cached at module scope** (they depend on per-request `data_start_year`); compute on each request. If profiling shows hot path, add an LRU cache on `(data_source, data_start_year, country, percentile_range)`.

### 6.6 Error messages — user-visible texts

Pattern: surface a clear remediation, never a raw exception.

**v1.3 standardization (per Codex Low finding):** v1.1 mixed 400 and 422 between §6.6 and §7.4. **Decision: use 422 for all schema/validation errors** (matches FastAPI/Pydantic's default and is what `pydantic.ValidationError` naturally raises), and **400 only for cross-request semantic errors** (e.g., "guardrail strategy is not supported with CME data source").

| Condition | HTTP code | Message |
|---|---|---|
| `data_source=cme_horizon_2025` + `starting_yield_percentile_range` set | **422** | "Yield filter not applicable to CME data source. Either remove the filter or switch to JST/FIRE dataset." |
| `starting_yield_percentile_range` set on a historical-backtest endpoint | **422** | "Yield filter only applies to bootstrap-based simulation, not historical-path backtest." |
| Yield filter band yields 0 years (single country) | 400 | "Yield percentile band [{low}, {high}] matched no historical years for {country} from {data_start_year}. Try widening the band or earlier data start year." |
| Yield filter band yields 0 years for some pooled countries | 200 (warn only) | Per §5.5.3: log warning and fall back to unrestricted for those countries; `model_diagnostics.yield_filter_per_country_match_counts` shows the drop |
| Guardrail strategy + `data_source=cme_horizon_2025` | 400 | "Guardrail strategy not yet supported with CME data source. Use historical bootstrap." |
| Buy-vs-rent + `data_source=cme_horizon_2025` | 400 | "Buy-vs-rent not supported with CME data source." |
| CME asset CSV not found | 500 | "CME data not available (file: data/cme/horizon_2025_assets.csv). Re-run `scripts/import_horizon_cma.py`." |
| Computed CME covariance not PSD even after Higham repair | 500 | "Internal: CME covariance assembly failed PSD check. Report this bug with the asset mapping diagnostic." |

---

## 7. Testing Strategy

### 7.1 Unit tests — `tests/test_cma_sampler.py` (NEW)

**v1.3 tolerance correction (per Codex Medium finding):** v1.1 specified "sample mean within 1σ/√N" — this is a one-standard-error bound, expected to fail ~32% of the time even for a correct sampler. v1.3 uses **3σ/√N** (false-failure rate < 0.3%) with **fixed seed** for determinism.

| Test | Purpose |
|---|---|
| `test_load_horizon_2025_us_investor` | Loader succeeds for default profile, PSD, sane numeric bounds, prior version stamped |
| `test_load_horizon_2025_acwi_proxy` | ACWI proxy profile loads, Dom_Stock and Global_Stock have identical returns each draw (perfectly correlated) |
| `test_load_horizon_2025_developed_world` | DM-only profile loads correctly |
| `test_draw_shape` | `draw(50, rng).shape == (50, 4)` |
| `test_draw_mean_consistency` | **Fixed seed**, draw 100K paths, sample mean within **3σ/√N** of CMA mean per column |
| `test_draw_cov_consistency` | Fixed seed, sample covariance within 5% (relative) of constructed cov |
| `test_draw_reproducibility` | Same `seed` → bit-identical output across runs |
| `test_inflation_correlation_priors` | Verify hard-coded priors match `INFLATION_PRIOR_VERSION` documented values |
| `test_inflation_prior_sensitivity` | Vary corr(Inflation, Bonds) by ±0.10 → confirm SR drift is within expected range (sensitivity diagnostic; not a tolerance assertion, more like a regression-bound smoke test) |
| `test_asset_mapping_weighted` | Composite columns computed correctly per §4.2 |
| `test_missing_csv_raises` | Sensible error if `data/cme/horizon_2025_*.csv` absent |
| `test_corrupted_csv_load_time_validation` | If asset CSV is hand-edited to non-PSD, loader raises (mitigates Codex #5 even if PR-0 didn't land first) |
| `test_compounded_geometric_consistency` | **(v1.3 added)** Simulate 20-year paths × 50K, compute annualized geometric return per simulation, verify mean is within 50 bp of Horizon's published `geom_20yr` for each column. Catches Jensen-gap / lognormal-assumption regression. |
| `test_psd_repair_no_op` | Standard Horizon 2025 cov is naturally PSD; repair is a no-op (eigenvalue clip changes nothing) |
| `test_psd_repair_logs_magnitude` | Inject a non-PSD cov manually; loader applies Higham repair AND logs the repair Frobenius norm |

### 7.2 Unit tests — `tests/test_core.py` (extend)

`class TestStartingYieldFilter`:

| Test | Purpose |
|---|---|
| `test_mask_none_equivalent_to_omitted` | Passing `starting_year_mask=None` produces identical output to omitting the kwarg AND **consumes identical RNG state** (validate by `rng.bit_generator.state` snapshot before/after) |
| `test_mask_restricts_first_block` | When mask allows only year-index 5, first sampled year == data[5] |
| `test_mask_allows_subsequent_unrestricted` | Block 2+ can land anywhere |
| `test_mask_empty_raises` | All-False mask → ValueError |
| `test_pooled_per_country_mask` | Pooled bootstrap honors per-country masks |
| `test_pooled_zero_match_falls_back` | Per-country zero matches → warn + fall back, not crash |

**Property-based tests (v1.3 addition per Codex Medium finding) — `tests/test_yield_filter_properties.py` (NEW):**

Using `hypothesis`:

| Property | Hypothesis strategy |
|---|---|
| First sampled row is always from a valid start year | Generate random `(data, n, mask)` with `mask.any()` |
| Empty (all-False) mask raises | Strategy emits `np.zeros(n, dtype=bool)` |
| All-True mask is equivalent to no mask | Compare two RNG-equal runs |
| Single-True mask forces deterministic first block | First `block_size` rows are exact slice from that one index |
| Boundary percentiles `[0.0, 1.0]` admit all years | Equivalent to no mask |

The hypothesis dependency is small (~1 MB) and already available in many Python envs. If we want to keep `requirements.txt` minimal, add it to `requirements-dev.txt` only.

### 7.3 Equivalence tests — `tests/test_perf_equivalence.py` (extend)

**v1.3 strengthening (per Codex Medium finding):** v1.1 specified "snapshot test capturing expected output before any code change". Codex correctly pointed out that **byte-identical snapshots only hold under pinned numpy/pandas versions**, and the snapshot must be captured *before* PR-1 — captured *after* PR-1 silently bakes in any bug from PR-1.

**v1.3 protocol:**
1. **PR-0** (the import-script fix + fixture harness) generates `tests/fixtures/equiv_default.npz`, `equiv_pooled.npz`, `equiv_fire.npz`, **`equiv_buy_vs_rent.npz`** by running the existing engines against a known-good HEAD ref.
2. The fixture file metadata header records: numpy version, pandas version, Python version, git ref of the engine code, seed used.
3. Subsequent PRs (PR-1+) assert byte-identical equality against this fixture, with a **5-sigma allclose fallback** for cross-platform tolerance (`np.allclose(actual, expected, rtol=1e-7, atol=1e-9)`).
4. Test setup verifies the fixture metadata matches the current numpy/pandas version; if mismatched, the test **fails with a clear "regenerate fixture against your env" message** rather than silently passing under loose tolerance.

`class TestBackwardCompat`:

| Test | Purpose |
|---|---|
| `test_default_request_unchanged` | Baseline JST/USA/no-filter request, byte-identical against `equiv_default.npz` |
| `test_pooled_request_unchanged` | Same for pooled ALL request |
| `test_fire_dataset_unchanged` | Same for `fire_dataset` |
| `test_buy_vs_rent_unchanged` | **(v1.3 added per Codex finding)** Baseline buy_vs_rent MC against `equiv_buy_vs_rent.npz` |
| `test_no_filter_no_rng_drift` | **(v1.3 added)** Call `block_bootstrap_np` with `starting_year_mask=None` and without the kwarg — assert `rng.bit_generator.state` snapshots are identical after both calls (proves new code path consumes zero extra RNG when unused) |

### 7.4 Integration tests — `tests/test_api.py` (extend)

| Test | Purpose |
|---|---|
| `test_simulate_cme_source` | POST /api/simulate with `data_source=cme_horizon_2025`, status 200, response has expected shape, model_diagnostics populated |
| `test_simulate_yield_filter` | POST /api/simulate with `starting_yield_percentile_range=[0.3, 0.6]`, status 200, model_diagnostics shows match count > 0 |
| `test_invalid_combination_cme_plus_filter` | Status 422, message mentions yield filter not applicable to CME |
| `test_yield_filter_empty_band` | Edge percentile band [0.99, 1.0] on short data — status 400 with remediation message |
| `test_guardrail_rejects_cme` | POST /api/guardrail with `data_source=cme_horizon_2025` → 400 |

### 7.5 Smoke / manual verification

Document in PR description manual checks for Round 2:
1. Frontend: switch data source to CME, confirm country selector hides, run simulation, check chart renders.
2. Frontend: enable yield filter with current-yield preset, run simulation, check `model_diagnostics` displayed somewhere visible.
3. Compare three views (JST historical, JST + yield filter, CME) for the user's recommended setup (Pool, 10/80/10, 65y) — SWRs should be within ~50 bp of each other (sanity validation of the whole approach).

---

## 8. Implementation Order (for Round 2)

**v1.3 reordering (per Codex Low finding):** v1.1 had PR-1 = cma_loader + fixture, but if the fixture is captured *after* cma_loader changes the engine surface area, the fixture silently bakes in any PR-1 bug. PR-0 in v1.3 captures the fixture from the *current* HEAD before any code change.

0. **PR-0** (must land first): (a) Fix `scripts/import_horizon_cma.py` write-before-validate (Codex #4/#5); (b) capture equivalence fixtures `tests/fixtures/equiv_{default,pooled,fire,buy_vs_rent}.npz` from current HEAD with metadata header (numpy/pandas versions, git SHA, seed). Independent and behavior-preserving.
1. **PR-1**: `block_bootstrap_*` signature additions (mask + valid_starts params, defaults preserve behavior) + `test_core.py` extensions + property-based mask tests (§7.2) + equivalence tests against PR-0 fixtures
2. **PR-2**: Wire yield filter through `buy_vs_rent.py`, `monte_carlo.py`, `sweep.py` via new `simulator/sampling.py` adapter (§4.6.3 v1.3) + buy_vs_rent equivalence test
3. **PR-3**: `simulator/cma_loader.py` + 3 mapping profiles + PSD repair + unit tests (§7.1)
4. **PR-4**: Engine sampler dispatch (extend `simulator/sampling.py` to handle CmaSampler path) + integration with monte_carlo/sweep/buy_vs_rent
5. **PR-5**: Backend `schemas.py` (extend `BaseSimulationParams` + add to `BuyVsRentBaseParams` separately per §4.7.0) + `deps.py` (`resolve_sampler`, `resolve_yield_filter`) + route wiring + `test_api.py` extensions
6. **PR-6**: MCP shared Pydantic adapter (`backend/schemas_shared.py`) + `mcp_server/tools.py` refactor (§4.6.5) + MCP-side validation tests
7. **PR-7**: Frontend types (`DataSource` alias) + sidebar UI (data source toggle + mapping profile dropdown + yield filter section) + i18n + manual smoke

Each PR is independently mergeable and behavior-preserving for existing users.

---

## 9. Resolved Design Decisions

**v1.3:** the original §9 "Open Questions" have been resolved via Codex plan review (see `reviews/codex-plan-critique-2026-05-26.md`). Each decision is now recorded with Codex's verdict + the resolution.

1. **Inflation correlation priors** (§4.1) — **Refined.** Use the cited fixed priors (-0.10 / -0.05 / -0.30) with `INFLATION_PRIOR_VERSION = "v1-2026-05"` traceability stamp, **plus** a sensitivity diagnostic test (§7.1 `test_inflation_prior_sensitivity`). Estimating from JST historical data was rejected — it would mix ex-post historical inflation regimes with a forward CMA and create false precision (Codex verdict).

2. **Arithmetic 20yr vs 10yr** (§4.3) — **Resolved: arith_20yr fixed default**, no auto-switch on `retirement_years`. Discontinuous behavior at a switching threshold would be hard to explain to users. The 20-year horizon matches typical FIRE planning windows. (Codex Low: confirm)

3. **Per-country yield percentile** (§5.4) — **Confirmed.** Per-country quantile is the right pooled-bootstrap interpretation. Conditioning each country on its own rate/inflation history preserves country sampling weights and gives "low-rate regime within each country" the right semantics. Diagnostics (per-country match counts) added to `model_diagnostics` (§6.4). (Codex Medium: agree)

4. **First-block-only conditioning** (§5.1) — **Refined.** Defensible approximation of B-F-P (2014). UI/methodology text now explicit: "conditions the opening sampled block to today's macro regime; subsequent blocks revert to unrestricted random walk." Avoids overclaiming a full BFP-style state-space conditioning. (Codex Medium: refine framing — done)

5. **PSD repair strategy** (§4.1) — **Refined to multi-tier.** Eigenvalue clip for `eigvals.min() >= -1e-4`; **Higham** for larger deviations. Always emit `cme_psd_repair_norm` in diagnostics. (Codex Medium: refine — done)

6. **Asset mapping weights** (§4.2) — **Major refinement.** v1.1's "single hardcoded US-investor mapping" was unsound for non-US users (the simulator applies user's allocation weights downstream — the "ACWI ≈ US 60%" justification doesn't hold). **v1.3 introduces `cme_mapping_profile` enum** with `us_investor`, `acwi_proxy`, `developed_world_60_40`. Pre-selects `acwi_proxy` for non-US users on first CME activation. (Codex High: redesign — done)

7. **Guardrail incompatibility with CME** — **Confirmed: hard-reject (400).** Silently mixing historical guardrail lookup tables with CME path simulation would be epistemically muddled. v1.1's §5.7.2 contained contradictory language ("guardrail path simulation: yes") that's been corrected — yield filter (B) applies to guardrail; CME data source (A) does NOT. (Codex Medium: agree with cleanup — done)

## 9b. Open Questions Remaining (Round 2 implementation may surface)

1. **CME 60/40 mapping vs Pool 60/40 — calibration sanity check**: when Round 2 lands, the manual smoke (§7.5) should compare Pool 60/40 vs CME-`us_investor` 60/40 vs CME-`acwi_proxy` 60/40 — if they diverge by >2pp SR, that's a methodology bug, not user choice.

2. **Trailing inflation window size for §5.3**: 3-year was picked from Cleveland Fed methodology, but if Round 2 sensitivity shows the result is unstable across window sizes (1y / 3y / 5y), this becomes a v1.4 design question. Cap as a TBD.

3. **`acwi_proxy` profile cap-weight values** (§4.2): the 60/10/24/6 split (US Large/SmallMid/Non-US Developed/Emerging) is approximate for 2026. Should this be a constant in `cma_loader.py` or read from CME data itself (some CMA editions publish market-cap shares)? For v1, hardcode and document.

---

## 10. References

- Blanchett, D. M., Finke, M., & Pfau, W. D. (2014). Asset Valuations and Safe Portfolio Withdrawal Rates. *Retirement Management Journal*, 4(1):21-34. SSRN: https://ssrn.com/abstract=4445598
- Finke, M., Pfau, W. D., & Blanchett, D. (2013). The 4 Percent Rule Is Not Safe in a Low-Yield World. *Journal of Financial Planning*, 26(6):46-55.
- Anarkulova, A., Cederburg, S., & O'Doherty, M. (2023). The Safe Withdrawal Rate: Evidence from a Broad Sample of Developed Markets. *Journal of Financial Economics* (forthcoming).
- Horizon Actuarial Services (2025). Survey of Capital Market Assumptions. 27th Annual Edition.
- Bekaert, G., & Wang, X. (2010). Inflation risk and the inflation risk premium. *Economic Policy*, 25(64):755-806.
- Wachter, J. A. (2002). Portfolio and Consumption Decisions Under Mean-Reverting Returns. *JFQA*, 37(1):63-91.
- Higham, N. J. (2002). Computing the nearest correlation matrix — a problem from finance. *IMA Journal of Numerical Analysis*, 22(3):329-343.
- `memory/cme-horizon-2025-validates-jst-pool.md` (project memory, 2026-04-22)
- `memory/user-investment-profile.md` (project memory, 2026-05-20)
