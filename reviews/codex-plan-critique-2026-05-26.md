# Codex Plan Critique — CME CMA + Starting-Yield Filter

Scope: reviewed `docs/plan-2026-05-26-cme-yield-conditioning.md` as a design document, with brief context checks against current bootstrap/schema surfaces and CME CSV headers. No implementation files were modified.

## §9 Open Questions — Verdicts

1. **[Medium] Inflation correlation priors — Refine.** Fixed priors are acceptable for v1 only if treated as versioned modeling assumptions with sensitivity diagnostics; estimating them from JST would look more empirical but would mix ex-post historical inflation regimes with a forward CMA and may create false precision (`docs/plan-2026-05-26-cme-yield-conditioning.md:144`).
2. **[Low] `arith_20yr` vs `arith_10yr` — Refine.** Use `arith_20yr` as the default for retirement simulations, but keep horizon selection as an internal constant or request option rather than automatically switching at 15 years, because discontinuous model behavior by `retirement_years` is hard to explain (`docs/plan-2026-05-26-cme-yield-conditioning.md:177`).
3. **[Medium] Per-country yield percentile — Agree.** Per-country percentile is the right pooled-bootstrap interpretation because it conditions each country on its own rate/inflation history while preserving country sampling weights (`docs/plan-2026-05-26-cme-yield-conditioning.md:435`).
4. **[Medium] First-block-only conditioning — Refine.** First-block-only is a defensible approximation, but the UI and methodology text must say it conditions the opening historical block, not the full BFP-style valuation process (`docs/plan-2026-05-26-cme-yield-conditioning.md:380`).
5. **[Medium] PSD repair — Refine.** For a 4x4 matrix eigenvalue clipping is probably fine as a fallback, but repair the correlation matrix, re-scale variances, report repair magnitude, and prefer Higham if the diagonal/correlation structure would otherwise drift (`docs/plan-2026-05-26-cme-yield-conditioning.md:154`).
6. **[High] Hardcoded mapping weights — Refine.** Do not expose a full tactical builder, but do introduce named mapping profiles or at least a `global_acwi_usd` mapping, because the current US/ex-US split is not equivalent to IWDA/VWRA unless the allocation layer is also remapped (`docs/plan-2026-05-26-cme-yield-conditioning.md:160`).
7. **[Medium] Guardrail hard reject for CME — Agree.** A 400 is cleaner than silently combining historical lookup tables with CME paths, but the plan must remove the contradictory “guardrail path simulation yes” language for CME and distinguish it from the yield filter (`docs/plan-2026-05-26-cme-yield-conditioning.md:301`, `docs/plan-2026-05-26-cme-yield-conditioning.md:558`).

## Methodological Soundness

**[High] §4.2 asset mapping is not acceptable as written for a China resident holding IWDA/VWRA.** The plan says `Domestic_Stock = US Large Cap` is “functionally what they actually own” because the US is about 60% of ACWI (`docs/plan-2026-05-26-cme-yield-conditioning.md:173`), but the simulator still applies the user’s `domestic_stock` and `global_stock` weights downstream. If the user’s portfolio is 90% IWDA/VWRA equity but entered as 10% domestic / 80% global / 10% bond, CME mode would become roughly 10% US large cap and 80% non-US equity, not ACWI-like exposure. Recommendation: add a `home_country_overlay`/`cme_mapping_profile` now, or make CME mode collapse total equity into a documented ACWI proxy before splitting simulator columns.

**[High] §5.3 real yield is defensible, but the proposed formula is ex-post and can leak same-year information.** `Long_Rate - Inflation` (`docs/plan-2026-05-26-cme-yield-conditioning.md:416`) uses realized inflation for the sampled year; that was not known at retirement and may condition on the first year’s inflation shock. Prefer `Long_Rate[t] - trailing_inflation[t-1]`, `Long_Rate[t] - expected_inflation_proxy[t]`, or label the current design explicitly as an ex-post real-yield proxy. Also soften the claim that BFP “implicitly used” real yield; the paper’s public abstract frames the state variables as initial bond yield and CAPE.

**[Medium] §5.4 per-country percentile is right, but diagnostics need to show matched years by country.** A pooled “30th percentile” should mean low-rate regime within each country, not globally low by cross-country level, but the response should include per-country match counts so GDP-weighted countries with sparse data do not silently dominate or vanish (`docs/plan-2026-05-26-cme-yield-conditioning.md:436`).

**[Medium] §4.3 arithmetic MVN sampling is directionally correct, but the compounding explanation is overstated.** Using arithmetic mean as the MVN mean is better than using geometric mean (`docs/plan-2026-05-26-cme-yield-conditioning.md:177`), but “draw arithmetic returns and compound them” only maps cleanly to the published geometric mean under distributional assumptions close to lognormal. Add a test that simulated 20-year annualized geometric returns are near Horizon’s `geom_20yr`, and decide how to handle simple-normal returns below -100%, even if rare.

## Backward Compatibility Risks

**[High] The §4.6.3 touch list misses direct bootstrap and route call sites.** The named engine touchpoints cover `monte_carlo.py` and `sweep.py` (`docs/plan-2026-05-26-cme-yield-conditioning.md:270`), but current code also calls the numpy bootstrap directly in `simulator/buy_vs_rent.py:349` and `simulator/buy_vs_rent.py:354`; even if buy-vs-rent rejects CME/yield filter, tests should prove those paths remain unchanged. Route wiring is also broader than the plan implies: `resolve_data()` is used by simulate variants, sensitivity, allocation sweep, accumulation, and five guardrail handlers, so use a centralized request-to-engine adapter rather than hand-patching endpoints.

**[Medium] Snapshot equivalence is useful but not sufficient.** The byte-identical guarantee (`docs/plan-2026-05-26-cme-yield-conditioning.md:585`) only holds in pinned numpy/pandas versions and if new optional arguments do not consume RNG or reorder country dictionaries. Capture the fixture before any functional PR, pin fixture-generation metadata, and add direct no-filter tests showing `block_bootstrap_np(..., starting_year_mask=None)` has the exact same RNG consumption and output as the old signature.

## Testing Strategy Gaps

**[Medium] The 1σ/√N sampler test will be flaky by design.** A one-standard-error bound fails often even for a correct sampler, especially across four assets and covariance checks (`docs/plan-2026-05-26-cme-yield-conditioning.md:638`); use a fixed seed with 3-5 standard errors or a deterministic large-sample tolerance based on `N * T`.

**[Medium] Add property-based tests for the yield mask.** Hypothesis is appropriate for mask shape, all-false, one-true, all-true, boundary percentile, and pooled per-country cases, with invariants that the first row comes from an allowed start and later blocks remain unrestricted.

**[Low] Snapshot tests need tolerance policy.** Keep exact snapshots for same-platform CI if dependencies are pinned, but add `allclose`-style regression assertions for summary outputs so numpy/platform changes do not create noisy failures unrelated to behavior.

## Implementation Order

**[Low] The PR sequence is mostly sensible, but PR-0 should include the equivalence fixture harness.** A fixture captured in PR-1 after adding `cma_loader.py` is easy to accidentally regenerate from a changed tree (`docs/plan-2026-05-26-cme-yield-conditioning.md:692`). Safer order: PR-0 import-script fix plus golden-equivalence harness/fixtures; PR-1 bootstrap mask with default-preserving tests; PR-2 CMA loader; PR-3 engine sampler dispatch; PR-4 schema/deps/routes; PR-5 MCP; PR-6 frontend/i18n.

## Overlooked Items

**[High] Schema propagation needs explicit negative support, not just inheritance.** Adding `starting_yield_percentile_range` to `BaseSimulationParams` reaches many derived schemas, including historical backtest schemas where a bootstrap filter is meaningless, while `BuyVsRentMCRequest` has duplicated simulation fields and does not inherit from `BaseSimulationParams` (`backend/schemas.py:583`). Add per-route validators or split request bases into “bootstrap simulation” vs “historical path” contracts; in TypeScript, replace the repeated data-source unions with a shared alias rather than manually editing “all 8” (`docs/plan-2026-05-26-cme-yield-conditioning.md:321`).

**[Medium] Performance is not automatically negligible.** The sketch computes `np.flatnonzero(starting_year_mask)` inside the bootstrap core (`docs/plan-2026-05-26-cme-yield-conditioning.md:462`), which runs per simulated path; precompute valid-start index arrays once per request, especially for sweep/guardrail bulk paths.

**[Medium] MCP parity validation is not enough.** MCP tools bypass the FastAPI/Pydantic request models today, so add a separate MCP input schema or shared Pydantic adapter for `data_source` and `starting_yield_percentile_range`, including mutual exclusion and bounds (`docs/plan-2026-05-26-cme-yield-conditioning.md:306`).

**[Low] i18n needs precision around “real yield.”** In Chinese, avoid ambiguous “实际收益率”; use wording like “实际长期债券收益率（名义长期利率减通胀率）”, and if the ex-post proxy remains, say so.

**[Low] Error-code policy is inconsistent.** §6.6 says invalid CME + yield filter is 400, while §7.4 expects 422 (`docs/plan-2026-05-26-cme-yield-conditioning.md:623`, `docs/plan-2026-05-26-cme-yield-conditioning.md:674`); pick one API behavior and test it.

Source consulted for BFP context: SSRN abstract for *Asset Valuations and Safe Portfolio Withdrawal Rates* (`https://ssrn.com/abstract=4445598`).
