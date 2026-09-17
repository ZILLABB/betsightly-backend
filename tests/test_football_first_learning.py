from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import numpy as np

from leagues.challenger_registry import (
    ChallengerRegistry, PromotionPolicy, promotion_assessment,
)
from leagues.football_feature_contract import (
    FEATURE_COLUMNS, FootballHistoryState, team_identity, validate_contract,
)
from leagues.football_first_model import artifact_compatible, coherent_probabilities
from leagues import weekly_training
from scripts.train_football_first import _split


def test_football_first_contract_contains_no_bookmaker_features():
    assert validate_contract() == (True, "COMPATIBLE")
    joined = " ".join(FEATURE_COLUMNS).lower()
    for forbidden in ("odds", "price", "implied", "market", "bookmaker", "sportybet"):
        assert forbidden not in joined


def test_training_and_inference_use_one_feature_builder_and_strict_cutoff():
    state = FootballHistoryState()
    before = state.features(league_id=1, home_team="Alpha", away_team="Beta",
                            as_of="2026-01-02")
    state.observe(league_id=1, home_team="Alpha", away_team="Beta",
                  played_at="2026-01-02", home_goals=2, away_goals=0)
    after = state.features(league_id=1, home_team="Alpha", away_team="Beta",
                           as_of="2026-01-09")
    assert len(before.values) == len(FEATURE_COLUMNS)
    assert before.as_dict()["home_history_coverage"] == 0
    assert after.as_dict()["home_history_coverage"] == pytest.approx(.1)
    assert after.as_dict()["home_rest_days"] == 7
    assert "home_history_lt_5" in after.missing


def test_non_chronological_history_is_rejected():
    state = FootballHistoryState()
    state.observe(league_id=1, home_team="Alpha", away_team="Beta",
                  played_at="2026-01-10", home_goals=1, away_goals=1)
    with pytest.raises(ValueError, match="NON_CHRONOLOGICAL_HISTORY"):
        state.features(league_id=1, home_team="Alpha", away_team="Beta",
                       as_of="2026-01-09")


def test_chronological_partitions_never_share_a_match_date():
    dates = np.asarray(
        [np.datetime64("2024-01-01") + np.timedelta64(day, "D")
         for day in range(1100) for _ in range(2)]
    )
    train, calibration, test = _split(dates)
    assert dates[train][-1] < dates[calibration][0]
    assert dates[calibration][-1] < dates[test][0]


def test_identity_is_league_and_team_type_scoped():
    assert team_identity(1, "São Paulo", "CLUB") == ("CLUB", "1", "sao paulo")
    assert team_identity(2, "São Paulo", "CLUB") != team_identity(1, "São Paulo", "CLUB")
    assert team_identity(1, "France", "NATIONAL") != team_identity(1, "France", "CLUB")


def test_football_probabilities_are_coherent():
    p = coherent_probabilities(1.8, .9)
    assert p["home_win"] + p["draw"] + p["away_win"] == pytest.approx(1, abs=3e-6)
    assert p["over_1_5"] >= p["over_2_5"] >= p["over_3_5"]
    assert p["over_2_5"] + p["under_2_5"] == pytest.approx(1, abs=2e-6)
    assert p["btts_yes"] + p["btts_no"] == pytest.approx(1, abs=2e-6)
    assert p["home_or_draw"] == pytest.approx(p["home_win"] + p["draw"], abs=2e-6)


def test_artifact_requires_bookmaker_independence_and_schema():
    metadata = {
        "artifact_format_version": "football-first-artifact-v1",
        "feature_schema_version": "football-first-v1",
        "feature_columns": list(FEATURE_COLUMNS),
        "uses_bookmaker_features": False,
        "promotion_status": "CHALLENGER",
    }
    assert artifact_compatible(metadata) == (True, "COMPATIBLE")
    metadata["uses_bookmaker_features"] = True
    assert artifact_compatible(metadata)[1] == "BOOKMAKER_INDEPENDENCE_NOT_DECLARED"


def test_registry_is_immutable_and_never_auto_promotes(tmp_path):
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"challenger")
    record = {"model_version": "v1", "artifact_path": str(artifact),
              "artifact_sha256": hashlib.sha256(b"challenger").hexdigest()}
    registry = ChallengerRegistry(tmp_path / "registry.json")
    assert registry.register_challenger(record) == record
    assert registry.register_challenger(record) == record
    with pytest.raises(PermissionError, match="AUTOMATIC_PROMOTION_DISABLED"):
        registry.promote("v1")


def test_promotion_requires_shadow_and_human_review():
    candidate = {
        "compatibility": "COMPATIBLE", "data_quality": "PASSED",
        "leakage_checks": "PASSED", "calibration_status": "PASSED",
        "common_test_n": 3000, "shadow_n": 300,
        "latency_status": "PASSED", "startup_status": "PASSED",
        "rollback_artifact": "champion-v0", "log_loss": .5, "brier": .2,
    }
    result = promotion_assessment(candidate, {"log_loss": .501, "brier": .201})
    assert result["recommendation"] == "ELIGIBLE_FOR_HUMAN_REVIEW"
    assert result["automatic_promotion"] is False
    candidate["shadow_n"] = 0
    assert promotion_assessment(candidate, None)["recommendation"] == "DO_NOT_PROMOTE"


def _settled_matches(n=100):
    return [{
        "fixture_id": str(i), "status": "FINISHED", "league_id": "eng.1",
        "home_team": f"H{i}", "away_team": f"A{i}",
        "kickoff": f"2026-01-{1 + i // 24:02d}T{i % 24:02d}:00:00Z",
        "home_score": i % 4, "away_score": (i + 1) % 3,
    } for i in range(n)]


def test_weekly_training_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(weekly_training.ENV_ENABLE, raising=False)
    with pytest.raises(PermissionError, match="DISABLED"):
        weekly_training.run_weekly(
            run_date="2026-01-11", matches=_settled_matches(),
            registry_path=tmp_path / "registry.json",
            train_challenger=lambda *_: {}, evaluate_challenger=lambda *_: {},
        )


def test_weekly_training_is_idempotent_and_does_not_promote(tmp_path, monkeypatch):
    monkeypatch.setenv(weekly_training.ENV_ENABLE, "true")
    calls = []

    def train(matches, key):
        calls.append(key)
        return {"model_version": "challenger-v1", "samples": len(matches)}

    kwargs = dict(
        run_date="2026-01-11", matches=_settled_matches(),
        registry_path=tmp_path / "registry.json", train_challenger=train,
        evaluate_challenger=lambda model: {"recommendation": "SHADOW"},
    )
    first = weekly_training.run_weekly(**kwargs)
    second = weekly_training.run_weekly(**kwargs)
    assert first == second
    assert len(calls) == 1
    assert first["production_changed"] is False
    assert first["promotion"] == "HUMAN_REVIEW_REQUIRED"


def test_weekly_failure_preserves_production(tmp_path, monkeypatch):
    monkeypatch.setenv(weekly_training.ENV_ENABLE, "true")
    result = weekly_training.run_weekly(
        run_date="2026-01-18", matches=_settled_matches(),
        registry_path=tmp_path / "registry.json",
        train_challenger=lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
        evaluate_challenger=lambda *_: {},
    )
    assert result["status"] == "FAILED"
    assert result["production_changed"] is False
    assert result["failure_reason"] == "RuntimeError"
