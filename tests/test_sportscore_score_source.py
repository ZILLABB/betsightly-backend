"""No-source-settlement contracts for the free SportScore candidate feed."""
from datetime import datetime, timezone

from services import sportscore_score_source as source


def fixture(**overrides):
    base = {
        "home": "Bolivar", "away": "Universitario De Vinto",
        "home_score": "2", "away_score": "1",
        "status": "finished", "status_text": "Finished",
        "time": "2026-10-27T00:00:00+00:00",
        "competition": "Bolivian Primera Division",
        "url": "/football/match/bolivar-vs-universitario-de-vinto/318q66h8o4w2qo9/",
    }
    return {**base, **overrides}


def test_valid_finished_result_is_only_unverified_candidate():
    row = source.parse_fixture(fixture(), "2026-10-27")
    assert row["home_score"] == 2 and row["away_score"] == 1
    assert row["score_90"] is None
    assert row["match_status"] == "FT_CANDIDATE_NOT_VERIFIED_90MIN"
    assert row["provider"] == "sportscore-shadow"


def test_reject_all_ambiguous_finished_and_non_regular_cup_results():
    assert source.parse_fixture(fixture(status="live"), "2026-10-27") is None
    assert source.parse_fixture(fixture(status_text="After Extra Time"), "2026-10-27") is None
    assert source.parse_fixture(fixture(status_text="Penalties"), "2026-10-27") is None
    assert source.parse_fixture(fixture(competition="National Cup"), "2026-10-27") is None
    assert source.parse_fixture(fixture(home_score=None), "2026-10-27") is None
    assert source.parse_fixture(fixture(home_score=True), "2026-10-27") is None
    assert source.parse_fixture(fixture(time="2026-10-28T00:00:00Z"), "2026-10-27") is None
    assert source.parse_fixture(fixture(url="https://evil.example/match/1"), "2026-10-27") is None


def test_reversed_home_away_slug_is_rejected():
    row = fixture(
        home="Instituto de Cordoba", away="Deportivo Riestra",
        url="/football/match/deportivo-riestra-vs-instituto-de-cordoba/4jwq2ghn5pwnm0v/",
    )
    assert source.parse_fixture(row, "2026-10-27") is None


def test_candidate_requires_exact_league_teams_and_utc_kickoff(monkeypatch):
    monkeypatch.setenv("SPORTSCORE_SHADOW_ENABLED", "true")
    monkeypatch.setattr(source, "fetch_day", lambda day: [
        source.parse_fixture(fixture(), "2026-10-27")
    ] if day == "2026-10-27" else [])
    pick = {
        "sportybet_event_id": "sr:match:123",
        "home_team": "Bolivar", "away_team": "Universitario De Vinto",
        "kickoff": "2026-10-27T00:05:00Z",
        "league": "Bolivian Primera Division",
        "status": "pending",
    }
    assert len(source.candidate_matches([pick])) == 1
    assert source.candidate_matches([{**pick, "away_team": "Riestra"}]) == []
    assert source.candidate_matches([{**pick, "league": "UEFA Europa League"}]) == []
    assert source.candidate_matches([{**pick, "kickoff": "2026-10-27T02:30:00Z"}]) == []
    monkeypatch.setenv("SPORTSCORE_SHADOW_ENABLED", "false")
    assert source.candidate_matches([pick]) == []


def test_live_fetch_is_cached_bounded_and_never_relies_on_html(monkeypatch):
    source._CACHE.clear()
    monkeypatch.setattr(source, "_WAIT_UNTIL", 0.0)
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {"date": "2026-10-27", "count": 1, "sport": "football",
                    "matches": [fixture()]}
    monkeypatch.setattr(source.requests, "get",
                        lambda url, **kwargs: calls.append((url, kwargs)) or Response())
    assert len(source.fetch_day("2026-10-27")) == 1
    assert len(source.fetch_day("2026-10-27")) == 1
    assert len(calls) == 1
    assert calls[0][0] == "https://sportscore.com/api/v1/fixtures/"
    assert calls[0][1]["params"]["limit"] == 200
    source._CACHE.clear()
