# Codex Code Review — PR-0 (commit 0ff78df)

Date: 2026-05-26
Invocation: `codex exec review --commit 0ff78df --title "PR-0: atomic CMA import + equivalence fixtures"`
Model: gpt-5.5, reasoning effort xhigh, multi_agent enabled

## Findings

### [P2] Atomic write helper can leave inconsistent state between the two os.replace calls

- Path: `scripts/import_horizon_cma.py:346-347` (in commit 0ff78df, before fix)
- Severity: P2 (Medium-High)
- Category: Correctness / Atomicity

**Issue**: If `os.replace(tmp_assets, assets_csv)` succeeds but
`os.replace(tmp_corr, corr_csv)` then raises (IO error, permission, or
crash between the two renames), the assets file has already been
overwritten while the correlation file remains old. That leaves
`data/cme/` with a mixed-version CSV pair — the partial-update state the
helper is meant to prevent.

**Codex reproducer** (executed live during review):

```python
# Patched os.replace to fail on the 2nd promote call after both temps written.
# Result: assets.csv contains v2 marker (0.099) while corr.csv stays v1.
# Confirms the original (committed) helper does NOT roll back the first replace.
```

## Resolution

Fix landed as follow-up commit on the same branch (`feat/cme-yield-conditioning`):

- `_atomic_write_csvs` now stages temps, moves originals to `.bak` sidecars,
  promotes temps in sequence, and on any exception rolls back partial state
  (restores from `.bak` or deletes a freshly-promoted file when no original
  existed).
- New `_safe_replace` / `_safe_unlink` helpers for best-effort rollback ops.
- 2 new tests:
  - `test_atomic_write_rolls_back_when_second_replace_fails` — Codex's
    exact reproducer, asserts both files at original (v1) state after the
    second replace raises.
  - `test_atomic_write_first_run_failure_leaves_clean_directory` —
    no-prior-file case: partially-promoted file must be deleted, not orphaned.

Limitation documented in the helper docstring: cannot protect against
`kill -9` between the two renames; would need filesystem-level journaling.
This helper protects against exceptions raised by `os.replace` or earlier
steps in the write sequence.

## Other observations from review run

Codex's review terminal output also surfaced (read-only) the existing plan
content (`docs/plan-2026-05-26-cme-yield-conditioning.md`) and inspected
the simulator engine surfaces while assessing context. No additional
findings were raised against PR-0 beyond the P2 above.
