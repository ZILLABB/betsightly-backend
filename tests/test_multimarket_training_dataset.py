"""Rights/provenance and chronological split gates for multi-market training."""
from datetime import datetime, timedelta, timezone

import pytest

from leagues.multimarket_training_dataset import (
    FEATURES, chronological_groups, validate_records,
)
from scripts.train_multimarket_goals_challenger import train


def row(index: int, *, offset_days: int | None = None) -> dict:
    day = (offset_days if offset_days is not None else index // 10)
    kickoff = datetime(2024, 1, 1, 18, tzinfo=timezone.utc) + timedelta(days=day)
    features_at = kickoff - timedelta(days=1)
    goals_h = (index + day) % 4
    goals_a = (index * 3 + day // 3) % 4
    result = {
        "fixture_id": f"licensed-fixture-{index}",
        "kickoff_utc": kickoff.isoformat(),
        "features_as_of_utc": features_at.isoformat(),
        "source_id": "owner-provided-test-data",
        "license_reference": "synthetic-fixtures-only",
        "rights_verified_by": "fixture-test",
        "rights_basis": "OWNED_VERIFIED",
        "home_goals": str(goals_h),
        "away_goals": str(goals_a),
    }
    for n, feature in enumerate(FEATURES):
        result[feature] = str(round(0.2 + ((index+n) % 19) / 19, 4))
    return result


def test_rejects_unauthorized_or_missing_provenance():
    test_row = row(1)
    test_row["rights_basis"] = "UNKNOWN"
    with pytest.raises(ValueError, match="rights"):
        validate_records([test_row])
    test_row["rights_basis"] = "OWNED_VERIFIED"
    test_row["rights_verified_by"] = ""
    with pytest.raises(ValueError, match="rights_verified_by"):
        validate_records([test_row])


def test_rejects_post_kickoff_feature_leakage():
    test_row = row(1)
    test_row["features_as_of_utc"] = test_row["kickoff_utc"]
    with pytest.raises(ValueError, match="timing leakage"):
        validate_records([test_row])


def test_refuses_duplicate_fixtures_and_bad_scores():
    original = row(2)
    with pytest.raises(ValueError, match="identity"):
        validate_records([original, original])
    original["away_goals"] = "not-finished"
    with pytest.raises(ValueError, match="invalid settled"):
        validate_records([original])


def test_no_future_date_leakage_across_three_chronological_splits():
    validated = validate_records([row(i) for i in range(600)])
    training, calibration, test = chronological_groups(validated)
    def days(records):
        return {(r["kickoff_utc"] + timedelta(hours=1)).date() for r in records}
    assert max(days(training)) < min(days(calibration))
    assert max(days(calibration)) < min(days(test))
    assert len(training) + len(calibration) + len(test) == 600


def test_synthetic_challenger_trains_and_reports_no_live_activation():
    validated = validate_records([row(i) for i in range(600)])
    result = train(validated)
    report = result["report"]
    assert report["production_unchanged"] is True
    assert report["market_activation"] is False
    assert report["test_rows"] > 0
    assert report["training_last_kickoff"] < report["calibration_first_kickoff"]
    assert report["calibration_first_kickoff"] < report["test_first_kickoff"]
    for market in ("btts_yes", "over_0_5", "over_1_5", "over_2_5",
                   "home_over_0_5", "away_or_draw"):
        assert 0 <= report["test"][market]["brier"] <= 1
        assert report["test"][market]["n"] == report["test_rows"]
        assert "baseline_brier" in report["test"][market]
    assert set(result["models"]) == {"home", "away"}
