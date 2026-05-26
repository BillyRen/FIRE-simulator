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
