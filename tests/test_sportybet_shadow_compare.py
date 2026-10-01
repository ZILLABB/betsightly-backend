from datetime import datetime, timezone

from leagues import canonical_identity
from leagues import sportybet_shadow_compare as shadow


NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def inventory():
    return {
        "status": "success",
        "snapshot_id": "sb-1",
        "complete": True,
        "fixtures": [
            {
                "sportybet_event_id": "sb-ars-che",
                "home_team": "Arsenal",
                "away_team": "Chelsea",
                "competition": "Premier League",
                "kickoff": NOW.isoformat(),
            },
            {
                "sportybet_event_id": "sb-liv-eve",
                "home_team": "Liverpool",
                "away_team": "Everton",
                "competition": "Premier League",
                "kickoff": NOW.isoformat(),
            },
        ],
    }


def prepared():
    return [
        {
            "match_id": "espn-1",
            "event_id": "espn-1",
            "league": "Premier League",
            "commence_time": NOW.isoformat(),
            "home": {"name": "Arsenal"},
            "away": {"name": "Chelsea"},
        }
    ]


def api_fixtures():
    return [
        {
            "fixture_id": 101,
            "date": NOW.isoformat(),
            "league_name": "Premier League",
            "country_name": "England",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
        }
    ]


def test_full_when_prepared_and_api_football_agree():
    result = shadow.compare(
        inventory(),
        prepared(),
        prepared_status={
            "ready": True,
            "stale": False,
            "board_snapshot_id": "prod-1",
        },
        api_fixtures=api_fixtures(),
    )

    first = result["fixtures"][0]
    assert first["enrichment_state"] == shadow.FULL
    assert first["data_support"] == shadow.STRONG
    assert first["identity_state"] == canonical_identity.TEAM_KICKOFF
    assert result["prepared_match_count"] == 1
    assert result["api_football_support_count"] == 1


def test_prepared_only_is_partial_and_adequate():
    result = shadow.compare(
        inventory(),
        prepared(),
        prepared_status={"ready": True, "stale": False},
        api_fixtures=[],
    )

    first = result["fixtures"][0]
    assert first["enrichment_state"] == shadow.PARTIAL
    assert first["data_support"] == shadow.ADEQUATE


def test_stale_prepared_match_is_explicit_fallback():
    result = shadow.compare(
        inventory(),
        prepared(),
        prepared_status={"ready": True, "stale": True},
        api_fixtures=api_fixtures(),
    )

    first = result["fixtures"][0]
    assert first["enrichment_state"] == shadow.STALE_FALLBACK
    assert first["data_support"] == shadow.THIN


def test_unmatched_sportybet_fixture_is_not_promoted():
    result = shadow.compare(
        inventory(),
        prepared(),
        prepared_status={"ready": True, "stale": False},
        api_fixtures=api_fixtures(),
    )

    second = result["fixtures"][1]
    assert second["enrichment_state"] == shadow.SPORTYBET_ONLY
    assert second["data_support"] == shadow.VERY_THIN
    assert second["prepared_fixture_id"] is None


def test_ambiguous_prepared_identity_fails_closed():
    dup = prepared() + [{
        "match_id": "espn-2",
        "event_id": "espn-2",
        "league": "Premier League",
        "commence_time": NOW.isoformat(),
        "home": {"name": "Arsenal"},
        "away": {"name": "Chelsea"},
    }]
    result = shadow.compare(
        inventory(),
        dup,
        prepared_status={"ready": True, "stale": False},
        api_fixtures=[],
    )

    first = result["fixtures"][0]
    assert first["identity_state"] == canonical_identity.AMBIGUOUS
    assert first["enrichment_state"] == shadow.AMBIGUOUS
    assert first["data_support"] == shadow.NO_SUPPORT


def test_status_omits_fixture_payload(monkeypatch):
    monkeypatch.setattr(
        shadow,
        "current_shadow_comparison",
        lambda: {
            "status": "success",
            "sportybet_fixture_count": 100,
            "fixtures": [{"sportybet_event_id": "private-detail"}],
        },
    )

    result = shadow.status()

    assert result["sportybet_fixture_count"] == 100
    assert "fixtures" not in result


def test_current_comparison_uses_prepared_and_cached_sources_only(monkeypatch):
    calls = {"prepared": 0, "api_cache": 0}
    monkeypatch.setattr(
        shadow.sportybet_inventory,
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
        return [], prepared()

    monkeypatch.setattr(engine, "prepared_pipeline", prepared_pipeline)

    def cached(dates):
        calls["api_cache"] += 1
        return api_fixtures()

    monkeypatch.setattr(shadow, "cached_apifootball_fixtures", cached)

    result = shadow.current_shadow_comparison()

    assert result["status"] == "success"
    assert calls == {"prepared": 1, "api_cache": 1}
