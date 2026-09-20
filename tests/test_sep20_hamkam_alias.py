"""Name equivalence must not weaken fixture, squad or market guards."""
from datetime import datetime, timezone
from leagues.sportybet import _norm, match_fixture


def _board(home, away, kickoff_ms, *, home_squad="", away_squad=""):
    key = f"{_norm(home)}|{_norm(away)}"
    return {
        "__meta__": {"snapshot_id": "alias-test", "is_complete": True},
        key: [{"event_id": "example-event", "home_team": home, "away_team": away,
               "home_squad": home_squad, "away_squad": away_squad,
               "kickoff_ms": kickoff_ms, "competition": "Eliteserien"}],
    }


def test_hamarkameratene_is_the_same_senior_club_as_hamkam():
    kickoff = "2026-09-20T15:00:00+00:00"
    ms = int(datetime.fromisoformat(kickoff).timestamp() * 1000)
    board = _board("Tromso", "HamKam", ms)
    result = match_fixture(board, "Tromso", "Hamarkameratene",
                           kickoff, "Eliteserien")
    assert result["status"] == "MATCHED"
    assert result["entry"]["event_id"] == "example-event"


def test_alias_never_overrides_kickoff_check():
    kickoff = "2026-09-20T15:00:00+00:00"
    ms = int(datetime.fromisoformat("2026-09-20T18:00:00+00:00").timestamp() * 1000)
    result = match_fixture(_board("Tromso", "HamKam", ms),
                           "Tromso", "Hamarkameratene", kickoff, "Eliteserien")
    assert result["status"] == "KICKOFF_MISMATCH"


def test_youth_listing_cannot_fill_senior_fixture():
    kickoff = "2026-09-20T14:00:00+00:00"
    ms = int(datetime.fromisoformat(kickoff).timestamp() * 1000)
    board = _board("Fenerbahce U19", "Eyupspor U19", ms,
                   home_squad="u19", away_squad="u19")
    result = match_fixture(board, "Fenerbahce", "Eyupspor", kickoff, "Super Lig")
    assert result["status"] == "FIXTURE_NOT_FOUND"
