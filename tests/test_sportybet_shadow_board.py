from datetime import datetime, timezone

from leagues import sportybet_shadow_board as board
from leagues import sportybet_shadow_compare as compare


NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def inventory():
    return {
        "status": "success",
        "snapshot_id": "sb-1",
        "complete": True,
        "fixtures": [{
            "sportybet_event_id": "sb-1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "competition": "Premier League",
            "kickoff": NOW.isoformat(),
        }],
    }


def prepared_fixture():
    return {
        "match_id": "m1",
        "event_id": "m1",
        "league": "Premier League",
        "commence_time": NOW.isoformat(),
        "home": {"name": "Arsenal"},
        "away": {"name": "Chelsea"},
    }


def pick():
    fixture = prepared_fixture()
    return {
        "match_id": "m1",
        "market": "over_1_5",
        "prediction": "Over 1.5",
        "odds": 1.40,
        "confidence": 0.75,
        "selection_probability": 0.73,
        "lower_reliability_bound": 0.69,
        "quality_score": 0.8,
        "risk_adjusted_return": 1.02,
        "trust": {
            "accepted": True,
            "trust_grade": "A",
            "trust_score": 91,
            "lower_reliability_bound": 0.69,
            "evidence_adjusted_probability": 0.73,
            "rejection_reasons": [],
        },
        "_fixture": fixture,
    }


def api_fixture():
    return {
        "fixture_id": 101,
        "date": NOW.isoformat(),
        "league_name": "Premier League",
        "country_name": "England",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
    }


def test_supported_current_candidate_is_prediction_ready(monkeypatch):
    monkeypatch.setattr(
        board,
        "_approved_prepared_candidates",
        lambda picks: (picks, {}),
    )

    result = board.build_shadow_prediction_board(
        inventory(),
        [pick()],
        [prepared_fixture()],
        prepared_status={"ready": True, "stale": False},
        api_fixtures=[api_fixture()],
    )

    assert result["shadow_only"] is True
    assert result["can_publish"] is False
    assert result["can_book"] is False
    assert result["can_settle"] is False
    assert result["authoritative_for_user_output"] is False
    assert result["prediction_ready_count"] == 1

    fixture = result["fixtures"][0]
    assert fixture["prediction_ready"] is True
    assert fixture["data_support"] == compare.STRONG
    assert fixture["candidate_count"] == 1


def test_thin_stale_support_is_not_prediction_ready(monkeypatch):
    monkeypatch.setattr(
        board,
        "_approved_prepared_candidates",
        lambda picks: (picks, {}),
    )

    result = board.build_shadow_prediction_board(
        inventory(),
        [pick()],
        [prepared_fixture()],
        prepared_status={"ready": True, "stale": True},
        api_fixtures=[api_fixture()],
    )

    fixture = result["fixtures"][0]
    assert fixture["data_support"] == compare.THIN
    assert fixture["prediction_ready"] is False


def test_no_approved_candidate_is_not_prediction_ready(monkeypatch):
    monkeypatch.setattr(
        board,
        "_approved_prepared_candidates",
        lambda picks: ([], {"trust_grade_below_b": 1}),
    )

    result = board.build_shadow_prediction_board(
        inventory(),
        [pick()],
        [prepared_fixture()],
        prepared_status={"ready": True, "stale": False},
        api_fixtures=[api_fixture()],
    )

    fixture = result["fixtures"][0]
    assert fixture["prediction_ready"] is False
    assert fixture["candidate_count"] == 0
    assert result["policy_rejections"] == {"trust_grade_below_b": 1}


def test_status_never_returns_fixture_or_candidate_payload(monkeypatch):
    monkeypatch.setattr(
        board,
        "current_shadow_prediction_board",
        lambda: {
            "status": "success",
            "prediction_ready_count": 20,
            "fixtures": [{"candidates": [{"market": "over_1_5"}]}],
        },
    )

    result = board.status()

    assert result["prediction_ready_count"] == 20
    assert "fixtures" not in result


def test_current_shadow_board_uses_prepared_memory_and_cache_only(monkeypatch):
    calls = {"prepared": 0, "api_cache": 0}

    monkeypatch.setattr(
        board.sportybet_inventory,
        "cached_shadow_inventory",
        lambda: inventory(),
    )

    from leagues import engine

    monkeypatch.setattr(
        engine,
        "prepared_board_status",
        lambda days_ahead=7: {
            "ready": True,
            "stale": False,
            "board_snapshot_id": "prod-1",
        },
    )

    def prepared_pipeline(days_ahead=7):
        calls["prepared"] += 1
        return [pick()], [prepared_fixture()]

    monkeypatch.setattr(engine, "prepared_pipeline", prepared_pipeline)

    def cached(dates):
        calls["api_cache"] += 1
        return [api_fixture()]

    monkeypatch.setattr(
        board.shadow_compare,
        "cached_apifootball_fixtures",
        cached,
    )
    monkeypatch.setattr(
        board,
        "_approved_prepared_candidates",
        lambda picks: (picks, {}),
    )

    result = board.current_shadow_prediction_board()

    assert result["status"] == "success"
    assert calls == {"prepared": 1, "api_cache": 1}
