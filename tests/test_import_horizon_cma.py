"""Tests for scripts/import_horizon_cma.py — focus on the atomic-write fix.

PR-0 goal: validation now runs *before* file writes, and writes go through
temp files + os.replace so failed runs leave the target paths untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import import_horizon_cma as ihc  # noqa: E402


def _good_assets() -> list[dict]:
    """Minimal 17-asset + Inflation list passing validate()."""
    rows: list[dict] = []
    for i in range(17):
        rows.append({
            "index": str(i + 1),
            "asset": f"Asset_{i + 1}",
            "arith_10yr": 0.06,
            "geom_10yr": 0.05,
            "arith_20yr": 0.06,
            "geom_20yr": 0.05,
            "std_dev": 0.12,
        })
    rows.append({
        "index": "18",
        "asset": "Inflation",
        "arith_10yr": 0.025,
        "geom_10yr": 0.024,
        "arith_20yr": 0.025,
        "geom_20yr": 0.024,
        "std_dev": 0.02,
    })
    return rows


def _good_corr(n: int = 17) -> np.ndarray:
    """Identity matrix → trivially PSD, symmetric, diag=1."""
    return np.eye(n)


def test_atomic_write_succeeds_when_validation_passes(tmp_path: Path) -> None:
    """Happy path: good data → both CSVs land at final paths."""
    assets = _good_assets()
    corr = _good_corr()
    asset_names = [a["asset"] for a in assets if a["asset"] != "Inflation"]
    assets_csv = tmp_path / "horizon_test_assets.csv"
    corr_csv = tmp_path / "horizon_test_corr.csv"

    ihc._atomic_write_csvs(assets_csv, corr_csv, assets, asset_names, corr)

    assert assets_csv.is_file()
    assert corr_csv.is_file()
    # Tempfile siblings cleaned up
    assert not (tmp_path / "horizon_test_assets.csv.tmp").exists()
    assert not (tmp_path / "horizon_test_corr.csv.tmp").exists()


def test_atomic_write_rolls_back_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the second write raises, the first temp file must be cleaned up
    and the final destination must not exist."""
    assets = _good_assets()
    corr = _good_corr()
    asset_names = [a["asset"] for a in assets if a["asset"] != "Inflation"]
    assets_csv = tmp_path / "horizon_test_assets.csv"
    corr_csv = tmp_path / "horizon_test_corr.csv"

    original_write_corr = ihc.write_corr_csv

    def boom(path: Path, names, mat) -> None:
        # Simulate disk error after assets temp was already written
        raise OSError("simulated write failure")

    monkeypatch.setattr(ihc, "write_corr_csv", boom)

    with pytest.raises(OSError, match="simulated write failure"):
        ihc._atomic_write_csvs(assets_csv, corr_csv, assets, asset_names, corr)

    # Neither final path should exist
    assert not assets_csv.exists()
    assert not corr_csv.exists()
    # Both tempfiles should be cleaned up
    assert not (tmp_path / "horizon_test_assets.csv.tmp").exists()
    assert not (tmp_path / "horizon_test_corr.csv.tmp").exists()

    # Sanity: restoring the real function works
    monkeypatch.setattr(ihc, "write_corr_csv", original_write_corr)


def test_atomic_write_preserves_existing_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a previous good run exists and a new run fails mid-write, the old
    file should remain (untouched) since we never wrote directly to it."""
    assets = _good_assets()
    corr = _good_corr()
    asset_names = [a["asset"] for a in assets if a["asset"] != "Inflation"]
    assets_csv = tmp_path / "horizon_test_assets.csv"
    corr_csv = tmp_path / "horizon_test_corr.csv"

    # First, successful write
    ihc._atomic_write_csvs(assets_csv, corr_csv, assets, asset_names, corr)
    original_assets_content = assets_csv.read_text()
    original_corr_content = corr_csv.read_text()

    # Now patch the corr writer to fail mid-second-run
    def boom(path: Path, names, mat) -> None:
        raise OSError("simulated second-run failure")

    monkeypatch.setattr(ihc, "write_corr_csv", boom)

    # Pretend new data wants to be written
    new_assets = _good_assets()
    new_assets[0]["arith_10yr"] = 0.099  # different marker value
    with pytest.raises(OSError):
        ihc._atomic_write_csvs(assets_csv, corr_csv, new_assets, asset_names, corr)

    # Files unchanged
    assert assets_csv.read_text() == original_assets_content
    assert corr_csv.read_text() == original_corr_content


def test_validation_failure_prevents_any_file_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end check via main(): when validate() returns errors, no CSVs
    appear in the output directory."""
    monkeypatch.setattr(ihc, "DEFAULT_RAW_DIR", tmp_path / "raw")
    (tmp_path / "raw").mkdir()
    fake_pdf = tmp_path / "raw" / "horizon_cma_2099.pdf"
    fake_pdf.write_bytes(b"%PDF-fake")

    # Skip pdftotext + parser entirely; feed validate() bad data
    bad_assets = _good_assets()
    bad_corr = -np.eye(17)  # negative-definite → fails PSD check
    monkeypatch.setattr(ihc, "run_pdftotext", lambda p: "")
    monkeypatch.setattr(ihc, "find_exhibit_17_block", lambda t: [])
    monkeypatch.setattr(ihc, "parse_exhibit_17", lambda b: (bad_assets, bad_corr))

    out_dir = tmp_path / "out"
    rc = ihc.main_with_args(["--out-dir", str(out_dir), "--pdf", str(fake_pdf)])
    assert rc == 1
    # Neither final CSV nor any tempfile should exist
    assert not list(out_dir.glob("*.csv*"))
    captured = capsys.readouterr()
    assert "FAIL" in captured.out or "FAIL" in captured.err


def test_atomic_write_rolls_back_when_second_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex P2 finding: if first os.replace succeeds and second fails, the
    paired files must remain at their original state (not mixed-version).

    Reproducer: write a "v1" pair successfully, then attempt to write "v2"
    where the second os.replace raises. After failure, both target files
    must still contain v1 data.
    """
    assets_v1 = _good_assets()
    asset_names = [a["asset"] for a in assets_v1 if a["asset"] != "Inflation"]
    assets_csv = tmp_path / "horizon_test_assets.csv"
    corr_csv = tmp_path / "horizon_test_corr.csv"

    # First pass: clean write of v1
    ihc._atomic_write_csvs(assets_csv, corr_csv, assets_v1, asset_names, _good_corr())
    v1_assets_content = assets_csv.read_text()
    v1_corr_content = corr_csv.read_text()

    # Patch os.replace to fail on the *second* replace call (mimics partial IO failure)
    original_replace = ihc.os.replace
    call_count = {"n": 0}

    def selective_replace(src: Path, dst: Path) -> None:
        # The sequence inside _atomic_write_csvs is:
        #   replace(assets_csv, bak_assets)
        #   replace(corr_csv, bak_corr)
        #   replace(tmp_assets, assets_csv)   ← we count this
        #   replace(tmp_corr, corr_csv)       ← and fail here
        # Only counting promote-temps phase by path destination.
        call_count["n"] += 1
        if call_count["n"] == 4:  # second temp→target replace
            raise OSError("simulated second-replace failure")
        return original_replace(src, dst)

    monkeypatch.setattr(ihc.os, "replace", selective_replace)

    assets_v2 = _good_assets()
    assets_v2[0]["arith_10yr"] = 0.099  # marker value different from v1
    with pytest.raises(OSError, match="simulated second-replace failure"):
        ihc._atomic_write_csvs(assets_csv, corr_csv, assets_v2, asset_names, _good_corr())

    # Both files must be back to v1 state, no mixed-version pair
    assert assets_csv.read_text() == v1_assets_content, (
        "assets.csv should have been rolled back to v1 after second-replace failure"
    )
    assert corr_csv.read_text() == v1_corr_content, (
        "corr.csv should remain v1 (it was the one that failed to promote)"
    )
    # No sidecars left behind
    assert not (tmp_path / "horizon_test_assets.csv.tmp").exists()
    assert not (tmp_path / "horizon_test_corr.csv.tmp").exists()
    assert not (tmp_path / "horizon_test_assets.csv.bak").exists()
    assert not (tmp_path / "horizon_test_corr.csv.bak").exists()


def test_atomic_write_first_run_failure_leaves_clean_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If there's no prior file and the second replace fails, the partially-
    promoted first file must be deleted (no orphan)."""
    assets = _good_assets()
    asset_names = [a["asset"] for a in assets if a["asset"] != "Inflation"]
    assets_csv = tmp_path / "horizon_first_assets.csv"
    corr_csv = tmp_path / "horizon_first_corr.csv"

    original_replace = ihc.os.replace
    call_count = {"n": 0}

    def selective_replace(src: Path, dst: Path) -> None:
        # First run: no backup phase (originals don't exist), so the first
        # two replace calls are the temp→target promotions.
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError("simulated first-run second-replace failure")
        return original_replace(src, dst)

    monkeypatch.setattr(ihc.os, "replace", selective_replace)

    with pytest.raises(OSError):
        ihc._atomic_write_csvs(assets_csv, corr_csv, assets, asset_names, _good_corr())

    assert not assets_csv.exists(), "Partially-promoted assets.csv must be deleted on first-run failure"
    assert not corr_csv.exists()
    # No sidecars
    for suffix in (".tmp", ".bak"):
        assert not (assets_csv.with_name(assets_csv.name + suffix)).exists()
        assert not (corr_csv.with_name(corr_csv.name + suffix)).exists()


def test_display_path_inside_repo() -> None:
    p = ROOT / "data" / "cme" / "horizon_2025_assets.csv"
    s = ihc._display_path(p)
    assert s == str(p.resolve().relative_to(ROOT))
    assert not s.startswith("/")


def test_display_path_outside_repo(tmp_path: Path) -> None:
    p = tmp_path / "elsewhere.csv"
    s = ihc._display_path(p)
    assert s == str(p.resolve())
    assert s.startswith("/")
