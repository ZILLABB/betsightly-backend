"""Strict NBA official live-score CDN crosswalk and ESPN outage fallback tests."""
from datetime import datetime, timezone, timedelta

import pytest

from basketball.research_nba_cdn import (
    NBA_CDN_SOURCE, match_nba_cdn_finals,
)
from basketball.research_scoreboard import (
    refresh_recent_finals, verify_finals,
)

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def fixture(day="2026-10-23"):
    return {
        "game_id": "401909847", "date": day, "season": 2027,
        "status": "scheduled", "home_id": "14", "away_id": "8",
        "home_name": "Miami Heat", "away_name": "Detroit Pistons",
        "home_score": None, "away_score": None,
        "start_utc": "2026-10-24T00:00:00+00:00",
        "postseason": False,
        "source": "sportsdataverse:espn_nba_schedules:v1",
        "retrieved_at": NOW.isoformat(),
    }


def official(day="2026-10-23", home="MIA", away="DET",
             when="2026-10-24T00:00:00Z",
             code=3, state="Final"):
    return {
        "scoreboard": {
            "gameDate": day, "leagueId": "00",
            "games": [{
                "gameId": "0022600042",
                "gameStatus": code, "gameStatusText": state,
                "gameTimeUTC": when,
                "homeTeam": {"teamTricode": home, "score": 111},
                "awayTeam": {"teamTricode": away, "score": 105},
            }],
        },
    }


def match(payload, games=None):
    return match_nba_cdn_finals(
        payload, "2026-10-23", games or [fixture()],
        retrieved_at=NOW.isoformat(),
    )


def test_exact_nba_id_crosswalk_and_final_score_verification():
    final = match(official())
    assert list(final) == ["401909847"]
    assert final["401909847"]["provider_game_id"] == "0022600042"
    assert final["401909847"]["source"] == NBA_CDN_SOURCE
    verified, stats = verify_finals([fixture()], final)
    assert stats["verified_new_finals"] == 1
    assert verified[0]["status"] == "final"
    assert verified[0]["home_score"] == 111
    assert verified[0]["source"] == NBA_CDN_SOURCE
    assert verified[0]["verification_provider_game_id"] == "0022600042"


def test_no_crosswalk_on_wrong_team_or_fuzzy_team_names():
    assert match(official(away="LAL")) == {}
    altered = {**fixture(), "home_name": "Miami"}
    assert match(official(), games=[altered]) == {}
    assert match(official(when="2026-10-24T02:00:00Z")) == {}


def test_only_actual_nba_final_and_exact_current_date_is_accepted():
    assert match(official(code=2, state="Q4")) == {}
    assert match(official(code=3, state="Suspended")) == {}
    with pytest.raises(RuntimeError, match="DATE_MISMATCH"):
        match(official(day="2026-10-24"))
    with pytest.raises(ValueError, match="cannot be tied"):
        tied = official()
        tied["scoreboard"]["games"][0]["awayTeam"]["score"] = 111
        match(tied)


def test_ambiguity_in_cross_provider_mapping_fails_closed():
    duplicate = {**fixture(), "game_id": "401909999"}
    with pytest.raises(ValueError, match="Ambiguous"):
        match(official(), games=[fixture(), duplicate])


def test_official_nba_fallback_to_failed_espm_scoreboard(monkeypatch):
    from basketball import research_scoreboard as espn
    from basketball import research_nba_cdn as nba

    def error(day):
        raise RuntimeError("SCOREBOARD_UNAVAILABLE site:HTTP_403; cdn:HTTP_403")

    monkeypatch.setattr(espn, "download_scoreboard", error)
    monkeypatch.setattr(nba, "download_nba_cdn", lambda day: official(day))
    merged, health = refresh_recent_finals([fixture()], as_of=NOW)
    assert health["status"] == "ok"
    assert health["official_nba_fallback_dates"] == ["2026-10-23"]
    assert health["verified_new_finals"] == 1
    assert merged[0]["source"] == NBA_CDN_SOURCE


def test_three_unavailable_sources_report_partial_without_any_scores(monkeypatch):
    from basketball import research_scoreboard as espn
    from basketball import research_nba_cdn as nba

    monkeypatch.setattr(espn, "download_scoreboard",
                        lambda day: (_ for _ in ()).throw(RuntimeError("HTTP_403")))
    monkeypatch.setattr(nba, "download_nba_cdn",
                        lambda day: (_ for _ in ()).throw(RuntimeError("HTTP_403")))
    merged, health = refresh_recent_finals([fixture()], as_of=NOW)
    assert merged[0]["status"] == "scheduled"
    assert health["status"] == "partial"
    assert "nba_cdn:HTTP_403" in health["failed_dates"][0]["detail"]
    assert health["dates_checked"] == 0


def test_valid_but_empty_espn_board_probes_official_final_when_overdue():
    """A 200/events=[] response must not strand a finished paper fixture."""
    calls=[]
    merged,health=refresh_recent_finals(
        [fixture()],as_of=NOW,
        loader=lambda day:{"events":[]},
        official_loader=lambda day:(calls.append(day) or official(day)),
    )
    assert calls == ["2026-10-23"]
    assert health["verified_new_finals"]==1
    assert health["official_nba_fallback_dates"]==["2026-10-23"]
    assert health["overdue_espn_probe_dates"]==["2026-10-23"]
    assert health["overdue_unverified_count"]==0
    assert health["status"]=="ok"
    assert merged[0]["source"]==NBA_CDN_SOURCE


def test_not_yet_overdue_empty_espn_board_does_not_trigger_extra_probe():
    current={**fixture(day="2026-10-24"),
             "start_utc":(NOW-timedelta(hours=1)).isoformat()}
    probed=[]
    merged,health=refresh_recent_finals(
        [current],as_of=NOW,
        loader=lambda day:{"events":[]},
        official_loader=lambda day:probed.append(day),
    )
    assert not probed
    assert health["status"]=="ok"
    assert health["verified_new_finals"]==0
    assert health["overdue_espn_probe_dates"]==[]
    assert merged[0]["status"]=="scheduled"


def test_failed_official_probe_is_reported_not_silently_successful():
    def unavailable(day):
        raise RuntimeError("HTTP_503")
    merged,health=refresh_recent_finals(
        [fixture()],as_of=NOW,
        loader=lambda day:{"events":[]},official_loader=unavailable,
    )
    assert merged[0]["status"]=="scheduled"
    assert health["status"]=="partial"
    assert health["overdue_unverified_count"]==1
    assert health["failed_dates"][0]["detail"]=="official_nba_probe:HTTP_503"
