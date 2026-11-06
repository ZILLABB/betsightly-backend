"""Wave 2 source paths are explicit and never silently replaced.

Synthetic isolated files only: no archived game results or jobs are modified.
"""
import hashlib
from pathlib import Path

from basketball.research_wave2_report import wave2_report


def test_missing_shadow_files_are_reported_explicitly(tmp_path):
    r = wave2_report(tmp_path)
    assert r["status"] == "awaiting_first_forecast"
    assert r["forecast_count"] == 0
    assert r["settled_count"] == 0
    assert r["source_status"] == "shadow_forecast_file_missing"
    assert r["research_home"] == str(tmp_path.resolve())
    assert r["source_inputs"]["shadow_forecasts"]["exists"] is False
    assert r["source_inputs"]["shadow_settlements"]["exists"] is False
    assert r["source_inputs"]["verified_fixtures"]["exists"] is False
    assert r["no_writes"] is True
    assert not (tmp_path / "advanced").exists()


def test_existing_empty_ledger_distinguished_from_absent_file(tmp_path):
    root = tmp_path / "advanced"
    root.mkdir()
    f = root / "shadow_2027.jsonl"
    f.write_text("", encoding="utf-8")
    r = wave2_report(tmp_path)
    assert r["source_status"] == "shadow_forecast_file_empty"
    assert r["source_inputs"]["shadow_forecasts"]["exists"] is True
    assert r["source_inputs"]["shadow_forecasts"]["size_bytes"] == 0
    assert r["source_inputs"]["shadow_forecasts"]["sha256"] == (
        hashlib.sha256(b"").hexdigest())
    assert r["forecast_count"] == 0


def test_orphan_settlement_integrity_failure_exposes_exact_sources(tmp_path):
    root = tmp_path / "advanced"
    root.mkdir()
    f = root / "shadow_settlements_2027.json"
    f.write_text('{"made_up_id": {"scores": [109, 100]}}', encoding="utf-8")
    r = wave2_report(tmp_path)
    assert r["status"] == "integrity_failed"
    assert r["reason"] == "orphan_settlement_identity"
    assert r["metrics_withheld"] is True
    assert r["source_inputs"]["shadow_forecasts"]["exists"] is False
    assert r["source_inputs"]["shadow_settlements"]["exists"] is True
    assert r["source_inputs"]["shadow_settlements"]["sha256"] is not None
    assert r["source_inputs"]["shadow_settlements"]["path"] == str(f.resolve())
    assert r["no_writes"] is True


def test_shadow_missing_no_confusion_with_other_forecast_ledgers(tmp_path):
    # Existing v1 main ledger must not be read as shadow evidence.
    (tmp_path / "nba_paper.sqlite").write_bytes(b"not a database")
    r = wave2_report(tmp_path)
    assert r["status"] == "awaiting_first_forecast"
    assert r["source_status"] == "shadow_forecast_file_missing"
    assert r["forecast_count"] == 0
    assert r["settled_count"] == 0
    assert (tmp_path / "nba_paper.sqlite").read_bytes() == b"not a database"
