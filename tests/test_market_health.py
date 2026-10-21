"""Read-only readiness telemetry never invents market training or odds."""
from datetime import datetime, timezone
import json

from leagues.market_health import market_health_report


def _record():
    return {
        "n": 55, "fitted_at": datetime(2026, 10, 21, tzinfo=timezone.utc).timestamp(),
        "groups": {"goals_over_1_5": {"n": 25},
                   "goals_over_0_5": {"n": 0}},
        "policy": {"version": "selection-policy-v1.2",
                   "settled_unique_forecasts": 10,
                   "historical_unique_forecasts": 45},
    }


def test_missing_over05_replay_and_live_observations_show_explicit_blockers(tmp_path):
    (tmp_path / "market_summary.json").write_text(json.dumps({
        "over_1_5": {"n": 200, "ece": 0.01, "bookmaker_n": 0},
    }))
    (tmp_path / "replay_metadata.json").write_text(json.dumps({}))
    result = market_health_report(
        date="2026-10-21", directory=tmp_path, fit=_record(),
        card={
            "banker": {"selected": True, "games": [{"match_id": "A"}]},
            "5_odds": {"selected": False, "games": [],
                       "reason": "No safe combination"},
            "_portfolio": {
                "max_official_fixture_exposure": 1,
                "tier_supply_diagnostics": {
                    "qualified_fixtures": 6,
                    "reserved_fixtures": 5,
                    "remaining_qualified_fixtures": 1,
                },
                "publication_policy": {"rejections": {"official": {
                    "NEGATIVE_MODEL_VALUE": 88,
                }}},
            },
        },
    )
    assert result["production_mutated"] is False
    assert result["publication"]["qualified_fixtures"] == 6
    assert result["publication"]["policy_rejections"]["NEGATIVE_MODEL_VALUE"] == 88
    assert result["live_calibration"]["unique_settled_forecasts"] == 55
    assert result["markets"]["over_0_5"]["historical_replay_n"] == 0
    assert "HISTORICAL_REPLAY_MISSING_OR_THIN" in result["markets"]["over_0_5"]["blockers"]
    assert result["legacy_training_tables_are_not_current_model_telemetry"]


def test_developing_market_never_silently_claims_safe_tier(tmp_path):
    (tmp_path / "market_summary.json").write_text(json.dumps({
        "home_over_0_5": {"n": 250, "ece": 0.01, "bookmaker_n": 0},
    }))
    (tmp_path / "replay_metadata.json").write_text(json.dumps({}))
    result = market_health_report(
        date="2026-10-21", directory=tmp_path, fit=_record(), card={})
    market = result["markets"]["home_over_0_5"]
    assert market["activation"] == "ACTIVE"
    assert market["safe_tier_enabled"] is False
    assert "SAFE_TIER_NOT_APPROVED" in market["blockers"]
    assert "HISTORICAL_BOOKMAKER_BENCHMARK_MISSING" in market["blockers"]
    assert market["publication_requires_current_bookmaker_check"] is True
