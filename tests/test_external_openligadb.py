"""OpenLigaDB pilot tests are fully offline; no network or publishing."""
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from leagues import external_openligadb as source
from leagues.jev_evidence_contract import evidence_envelope

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
ENABLED = {"BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED": "true"}


def match(mid=81001, kickoff=None, finished=True, score=(2, 1)):
    row = {
        "matchID": mid, "leagueShortcut": "bl1", "leagueSeason": 2026,
        "team1": {"teamId": 100, "teamName": "Home United"},
        "team2": {"teamId": 200, "teamName": "Away City"},
        "matchDateTimeUTC": (kickoff or (NOW - timedelta(days=2))).isoformat(),
        "matchIsFinished": finished,
        "matchResults": [],
    }
    if score is not None:
        row["matchResults"] = [
            {"resultTypeID": 1, "pointsTeam1": 1, "pointsTeam2": 0},
            {"resultTypeID": 2, "pointsTeam1": score[0], "pointsTeam2": score[1]},
        ]
    return row


def test_disabled_by_default_never_uses_network(monkeypatch):
    monkeypatch.setattr(source, "_read_json", lambda u: pytest.fail("network called"))
    report = source.fetch_matchday("bl1", 2026, 8, environ={})
    assert report["status"] == "disabled"
    assert report["network_called"] is False


@pytest.mark.parametrize("league,season,matchday", [
    ("other", 2026, 8), ("bl1/../../evil", 2026, 8), ("bl1", 1997, 8),
    ("bl1", True, 8), ("bl1", 2026, 0), ("bl1", 2026, 100),
    ("bl1", 2026, False),
])
def test_rejects_unapproved_url_segments(league, season, matchday):
    with pytest.raises(ValueError):
        source.source_url(league, season, matchday)


def test_fulltime_only_by_explicit_final_result_id():
    row = match()
    assert source._full_time_result(row) == {"home": 2, "away": 1}
    row["matchResults"].reverse()
    assert source._full_time_result(row) == {"home": 2, "away": 1}
    row["matchIsFinished"] = False
    assert source._full_time_result(row) is None


def test_partial_or_conflicting_score_is_not_claimed_as_final():
    row = match(score=None)
    row["matchResults"] = [{"resultTypeID": 1,
                            "pointsTeam1": 2, "pointsTeam2": 0}]
    report = source.normalize_matchday(
        [row], league="bl1", season=2026, matchday=8, captured_at=NOW)
    assert report["fixtures"][0]["reported_full_time"] is None
    assert report["evidence"] == []


def test_finished_community_result_is_attributed_and_not_for_settlement():
    report = source.normalize_matchday(
        [match()], league="bl1", season=2026, matchday=8, captured_at=NOW)
    assert report["status"] == "ok"
    assert report["license"] == "ODbL"
    assert "OpenLigaDB" in report["attribution"]
    assert report["provider_identity_verified_to_espn"] is False
    assert report["eligible_for_automatic_settlement"] is False
    fixture = report["fixtures"][0]
    assert fixture["reported_full_time"] == {"home": 2, "away": 1}
    assert fixture["eligible_for_automatic_settlement"] is False
    assert len(report["evidence"]) == 1
    evidence = report["evidence"][0]
    assert evidence["type"] == "recent_results"
    assert "community-reported" in evidence["claim"]
    assert evidence["source_url"].endswith("/getmatchdata/81001")
    assert evidence["observed_at"] == "2026-10-28T10:00:00Z"


def test_upcoming_fixture_is_schedule_not_an_invented_result():
    row = match(kickoff=NOW + timedelta(days=1), finished=False)
    report = source.normalize_matchday(
        [row], league="bl1", season=2026, matchday=8, captured_at=NOW)
    assert report["fixtures"][0]["reported_full_time"] is None
    assert report["evidence"][0]["type"] == "competition_schedule"


def test_after_kickoff_with_unverified_score_has_no_recent_result_evidence():
    row = match(kickoff=NOW - timedelta(hours=1), finished=False)
    report = source.normalize_matchday(
        [row], league="bl1", season=2026, matchday=8, captured_at=NOW)
    assert report["evidence"] == []


def test_fail_closed_if_replayed_source_snapshot_is_from_future():
    with pytest.raises(ValueError, match="cannot backdate"):
        source.normalize_matchday([match()], league="bl1", season=2026,
                                  matchday=8, captured_at=NOW,
                                  as_of=NOW - timedelta(days=1))


def test_does_not_mix_seasons_or_duplicate_fixture_ids():
    first = match()
    same = match()
    wrong = match(81002)
    wrong["leagueSeason"] = 2025
    report = source.normalize_matchday(
        [first, same, wrong], league="bl1", season=2026,
        matchday=8, captured_at=NOW)
    assert len(report["fixtures"]) == 1
    assert report["rejected"]["duplicate_provider_match_id"] == 1
    assert report["rejected"]["season_mismatch"] == 1


def test_response_size_and_type_are_bounded():
    with pytest.raises(ValueError, match="large"):
        source.normalize_matchday([match(i + 1) for i in range(47)],
                                  league="bl1", season=2026, matchday=8,
                                  captured_at=NOW)
    with pytest.raises(ValueError, match="invalid"):
        source.normalize_matchday({"matches": []}, league="bl1",
                                  season=2026, matchday=8, captured_at=NOW)


def test_cache_prevents_repeated_provider_calls(monkeypatch):
    source._CACHE.clear()
    calls = []
    monkeypatch.setattr(source, "_read_json", lambda url: (
        calls.append(url) or [match()]
    ))
    first = source.fetch_matchday("bl1", 2026, 8, environ=ENABLED, now=NOW)
    again = source.fetch_matchday("bl1", 2026, 8, environ=ENABLED, now=NOW)
    assert first["status"] == again["status"] == "ok"
    assert first["cache_hit"] is False
    assert again["cache_hit"] is True
    assert len(calls) == 1
    assert calls[0] == "https://api.openligadb.de/getmatchdata/bl1/2026/8"


def test_api_failure_leaves_publication_untouched_and_exposes_no_guessed_data(monkeypatch):
    source._CACHE.clear()
    def fail(url):
        raise HTTPError(url, 429, "too many requests", {}, None)
    monkeypatch.setattr(source, "_read_json", fail)
    report = source.fetch_matchday("bl1", 2026, 8, environ=ENABLED, now=NOW)
    assert report["status"] == "rate_limited"
    assert report["publication_changed"] is False
    assert "fixtures" not in report


def test_source_evidence_composes_only_with_a_pre_kickoff_jev_envelope():
    report = source.normalize_matchday(
        [match(kickoff=NOW + timedelta(days=1), finished=False)],
        league="bl1", season=2026, matchday=8, captured_at=NOW)
    prediction = {
        "match_id": "espn-100", "market": "over_1_5",
        "kickoff": (NOW + timedelta(days=1)).isoformat(),
        "home_team": "Home United", "away_team": "Away City",
        "confidence": .68, "odds": 1.7,
    }
    # Deliberately no identity bridge in Batch 2: this is a contract test,
    # not proof that 'espn-100' equals OpenLigaDB 81001.
    envelope = evidence_envelope(prediction, report["evidence"],
                                 sport="football", as_of=NOW)
    assert envelope["evidence_count"] == 1
    assert envelope["publication_authority"] is False
    assert envelope["state"]["evidence"][0]["type"] == "competition_schedule"
