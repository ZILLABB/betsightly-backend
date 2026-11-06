"""Synthetic tests for immutable pre-tipoff feature vectors in NEW Wave 2 rows.

No real NBA data, no connected servers, no model retraining or production writes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from basketball.research_advanced_features import FEATURE_COLUMNS, VERSION
from basketball.research_wave2_feature_snapshot import (
    create_feature_snapshot, validate_feature_snapshot,
)
from basketball.research_wave2_report import _forecast_rows, wave2_report

NOW = datetime(2026, 11, 6, 20, tzinfo=timezone.utc)
START = "2026-11-07T12:00:00+00:00"
VALUES = [float(i) for i in range(len(FEATURE_COLUMNS))]


def _record():
    recorded = {
        "game_id": "200", "season": 2027,
        "fixture_date": "2026-11-07",
        "home_id": "1", "away_id": "2",
        "created_at": NOW.isoformat(), "start_utc": START,
        "model_version": "nba-advanced-shadow-2026-v1",
        "candidate_home_win_probability": .7,
        "matched_v1_home_win_probability": .6,
        "candidate_total_points": 230.0,
        "matched_v1_total_points": 225.0,
        "candidate_home_margin": 5.0,
        "matched_v1_home_margin": 4.0,
        "source_feature_schema": VERSION,
        "bookmaker_odds_verified": False,
        "research_only": True, "not_for_betting": True,
    }
    recorded["pregame_feature_snapshot"] = create_feature_snapshot(
        vector=VALUES, captured_at=NOW.isoformat(), tipoff_at=START)
    return recorded


def _write_signed(root, item):
    path = root / "advanced" / "shadow_2027.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    signed = dict(item)
    canonical = json.dumps(
        {k:v for k,v in signed.items() if k not in ("sha256","settlement")},
        sort_keys=True, separators=(",", ":"))
    signed["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    path.write_text(json.dumps(signed)+"\n", encoding="utf-8")
    return path


def test_snapshots_signed_validated_and_conservative_legacy_read(tmp_path):
    item = _record()
    assert validate_feature_snapshot(item) is True
    snapshot = item["pregame_feature_snapshot"]
    assert snapshot["columns"] == list(FEATURE_COLUMNS)
    assert snapshot["matched_v1_prefix_count"] == 14
    path = _write_signed(tmp_path, item)
    assert len(_forecast_rows(path)) == 1
    report = wave2_report(tmp_path, now=NOW)
    assert report["status"] == "awaiting_verified_finals"
    assert report["forecast_count"] == 1
    assert report["integrity"]["original_hashes_checked"] == 1
    original = path.read_bytes()
    legacy = dict(item)
    legacy.pop("pregame_feature_snapshot")
    _write_signed(tmp_path, legacy)
    assert len(_forecast_rows(path)) == 1
    assert path.read_bytes() != original
    assert validate_feature_snapshot(legacy) is False


@pytest.mark.parametrize("corrupt,reason", [
    ("value", "feature_snapshot_fingerprint_mismatch"),
    ("column", "feature_snapshot_invalid_columns_or_length"),
    ("timestamp", "feature_snapshot_time_mismatch"),
    ("nan", "feature_snapshot_invalid_numeric_values"),
    ("null", "feature_snapshot_explicit_null"),
])
def test_signed_but_internally_inconsistent_snapshot_fails_closed(tmp_path, corrupt, reason):
    item = _record()
    snapshot = item["pregame_feature_snapshot"]
    if corrupt == "value":
        snapshot["values"][5] += 7
    elif corrupt == "column":
        snapshot["columns"][0] = "invented_column"
    elif corrupt == "timestamp":
        snapshot["captured_at"] = "2026-11-06T18:00:00+00:00"
    elif corrupt == "nan":
        snapshot["values"][5] = float("nan")
    else:
        item["pregame_feature_snapshot"] = None
    path = _write_signed(tmp_path, item)
    if corrupt == "nan":
        # A JSON encoder may emit nonstandard NaN but our reader rejects it.
        pass
    report = wave2_report(tmp_path, now=NOW)
    assert report["status"] == "integrity_failed"
    assert reason in report["reason"]
    assert report["metrics_withheld"] is True


def test_snapshot_creation_blocks_after_tipoff_or_nonfinite_values():
    with pytest.raises(ValueError, match="feature_snapshot_not_before_tipoff"):
        create_feature_snapshot(vector=VALUES, captured_at=START, tipoff_at=START)
    with pytest.raises(ValueError, match="feature_snapshot_wrong_vector_length"):
        create_feature_snapshot(vector=VALUES[:-1], captured_at=NOW.isoformat(), tipoff_at=START)
    changed = VALUES.copy()
    changed[2] = float("inf")
    with pytest.raises(ValueError, match="feature_snapshot_nonfinite"):
        create_feature_snapshot(vector=changed, captured_at=NOW.isoformat(), tipoff_at=START)


def test_new_shadow_forecast_stores_real_model_input_and_second_run_is_idempotent(
    tmp_path, monkeypatch
):
    import basketball.research_advanced_model as advanced
    import basketball.research_readiness as readiness
    import basketball.research_data as game_data
    import basketball.research_markets_v4 as markets

    class FakePredictor:
        def __init__(self, width, *, probability=None, score=None):
            self.width = width
            self.probability = probability
            self.score = score

        def predict_proba(self, matrix):
            assert matrix.shape == (1, self.width)
            return np.array([[1-self.probability, self.probability]])

        def predict(self, matrix):
            assert matrix.shape == (1, self.width)
            return np.array([self.score])

    n = len(FEATURE_COLUMNS)
    bundle = {
        "schema": VERSION,
        "model_version": advanced.MODEL_VERSION,
        "features": FEATURE_COLUMNS,
        "trained_through_season": 2026,
        "research_only": True,
        "candidate": FakePredictor(n, probability=.7),
        "matched_v1": FakePredictor(14, probability=.6),
        "score_models": {
            "total_points": {
                "advanced_candidate": FakePredictor(n, score=224),
                "matched_v1_features": FakePredictor(14, score=225),
            },
            "home_margin": {
                "advanced_candidate": FakePredictor(n, score=5),
                "matched_v1_features": FakePredictor(14, score=4),
            },
        },
        "market_residuals": [],
    }
    game = {
        "game_id": "200", "season": 2027,
        "date": "2026-11-07", "status": "scheduled",
        "home_id": "1", "away_id": "2",
        "start_utc": START,
    }
    advanced_folder = tmp_path / "advanced"
    advanced_folder.mkdir()
    (advanced_folder / "shadow_model.joblib").write_bytes(b"synthetic_only")
    monkeypatch.setattr(advanced, "_deps", lambda: (
        SimpleNamespace(load=lambda path: bundle), np, None, None, None))
    monkeypatch.setattr(
        advanced, "from_home", lambda root: (
            [{"game_id": "200", "features": tuple(VALUES)}], {"status": "ready"}))
    monkeypatch.setattr(game_data, "read_games", lambda path: [game])
    monkeypatch.setattr(readiness, "_model_cutoff", lambda root: (True, "2026-06-30"))
    monkeypatch.setattr(readiness, "build_readiness", lambda *args, **kwargs: (
        {"fixtures": [{"game_id": "200", "eligible": True}]}))
    monkeypatch.setattr(markets, "market_grid", lambda **kw: {"status": "blocked"})

    first = advanced.run_shadow(tmp_path, now=NOW)
    assert first["created"] == 1
    assert first["settled"] == 0
    ledger = advanced_folder/"shadow_2027.jsonl"
    saved = ledger.read_bytes()
    row = _forecast_rows(ledger)[0]
    assert row["pregame_feature_snapshot"]["values"] == VALUES
    assert row["pregame_feature_snapshot"]["captured_at"] == NOW.isoformat()
    assert row["candidate_total_points"] == 224
    assert row["matched_v1_home_margin"] == 4
    assert row["sha256"] != row["pregame_feature_snapshot"]["vector_sha256"]
    second = advanced.run_shadow(tmp_path, now=NOW)
    assert second["created"] == 0
    assert ledger.read_bytes() == saved
