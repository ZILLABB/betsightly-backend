"""Free provider adapters must not corrupt official 90-minute settlement."""
from datetime import datetime

from leagues import results_checker
from services import free_football_score_sources as source


def _sample_fdo(duration="REGULAR", regular=None, full=None):
    return {"id": 99, "status": "FINISHED",
            "utcDate": "2026-10-09T19:00:00Z",
            "homeTeam": {"name": "Arsenal FC"},
            "awayTeam": {"name": "Chelsea FC"},
            "score": {"duration": duration, "regularTime": regular,
                      "fullTime": full or {"home": 3, "away": 2}}}


def test_fdo_regular_time_does_not_grade_extra_time_goals():
    regular = {"home": 1, "away": 1}
    match = source._fd_match(_sample_fdo(
        duration="EXTRA_TIME", regular=regular))
    assert match["score_90"] == {"home": 1, "away": 1}
    assert match["home_score"] == 1
    assert source._fd_match(_sample_fdo(duration="EXTRA_TIME")) is None
    assert source._fd_match(_sample_fdo(duration="PENALTY_SHOOTOUT")) is None


def test_fdo_unfinished_and_broken_scores_do_not_settle():
    match = _sample_fdo()
    match["status"] = "IN_PLAY"
    assert source._fd_match(match) is None
    match["status"] = "FINISHED"
    match["score"]["fullTime"] = {"home": None, "away": 1}
    assert source._fd_match(match) is None
    match["score"]["fullTime"] = {"home": -1, "away": 1}
    assert source._fd_match(match) is None


def test_sportsdb_requires_explicit_finished_status():
    event = {"strSport": "Soccer", "strStatus": "Match Finished",
             "dateEvent": "2026-10-09", "strHomeTeam": "Arsenal",
             "strAwayTeam": "Chelsea", "intHomeScore": "2",
             "intAwayScore": "0", "idEvent": "e1"}
    assert source._sportsdb_match(event)["score_90"] == {"home": 2, "away": 0}
    assert source._sportsdb_match({**event, "strStatus": None}) is None
    assert source._sportsdb_match({**event, "strStatus": "After Extra Time"}) is None
    assert source._sportsdb_match({**event, "intAwayScore": None}) is None


def test_fdo_uses_token_header_and_honors_remaining_quota(monkeypatch):
    source._CACHE.clear()
    source._COOLDOWN.clear()
    source._MIN_INTERVAL.clear()
    monkeypatch.setenv("FOOTBALL_DATA_ORG_TOKEN", "fake-test-token")
    calls = []
    class Response:
        status_code = 200
        headers = {"X-Requests-Available-Minute": "0",
                   "X-RequestCounter-Reset": "43"}
        def json(self):
            return {"matches": [_sample_fdo()]}
    def request(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(source.requests, "get", request)
    result = source.football_data_finals("2026-10-09", "2026-10-09")
    assert len(result) == 1
    assert calls[0][1]["headers"] == {"X-Auth-Token": "fake-test-token"}
    assert calls[0][1]["params"]["status"] == "FINISHED"
    assert source._COOLDOWN["football-data.org"] > source.time.monotonic()
    assert source.football_data_finals("2026-10-09", "2026-10-09") == result
    assert len(calls) == 1
    source._CACHE.clear()
    source._COOLDOWN.clear()
    source._MIN_INTERVAL.clear()


def test_429_defers_calls_without_sleeping_or_leaking_token(monkeypatch):
    source._CACHE.clear()
    source._COOLDOWN.clear()
    source._MIN_INTERVAL.clear()
    monkeypatch.setenv("FOOTBALL_DATA_ORG_TOKEN", "fake-test-token")
    class Response:
        status_code = 429
        headers = {"Retry-After": "40"}
    calls = []
    monkeypatch.setattr(source.requests, "get",
                        lambda *a, **kw: calls.append(1) or Response())
    assert source.football_data_finals("2026-10-09", "2026-10-09") == []
    assert source.football_data_finals("2026-10-09", "2026-10-10") == []
    assert len(calls) == 1
    source._COOLDOWN.clear()
    source._MIN_INTERVAL.clear()


def test_dated_score_index_rejects_collisions_and_no_fuzzy_lookups():
    one = source._fd_match(_sample_fdo())
    indexed = results_checker._index_free_finals([one])
    assert results_checker._lookup_score(indexed, "Arsenal",
                                          "Chelsea", "2026-10-09")
    assert not results_checker._lookup_score(indexed, "Arsenal",
                                             "Chelsea", "2026-10-08")
    assert not results_checker._lookup_score(indexed, "Liverpool",
                                             "Chelsea", "2026-10-09")
    twice = {**one, "provider_event_id": 101, "home_score": 4}
    mixed = results_checker._index_free_finals([one, twice])
    assert results_checker._lookup_score(mixed, "Arsenal",
                                         "Chelsea", "2026-10-09") is None


def test_espn_first_then_free_fdo_without_contacting_api_football(monkeypatch):
    # Stub all providers: the real source must never be queried by tests.
    monkeypatch.setattr(results_checker, "_collect_espn_scores_ranged",
                        lambda *a, **kw: {})
    monkeypatch.setattr(results_checker, "_collect_apifootball_scores",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("suspended API-Football contacted")))
    monkeypatch.setattr(source, "football_data_finals",
                        lambda start, end: [source._fd_match(_sample_fdo())])
    monkeypatch.setattr(source, "sportsdb_finals", lambda dates: [])
    monkeypatch.setattr(results_checker, "_get_odds_api_key", lambda: "")
    picks = [{"home_team": "Arsenal", "away_team": "Chelsea",
              "kickoff": "2026-10-09T19:00:00Z"}]
    scored, providers = results_checker._collect_scores_for_picks(picks)
    assert results_checker._lookup_score(
        scored, "Arsenal", "Chelsea", "2026-10-09")["home_score"] == 3
    assert "football-data.org" in providers
    assert "api-football" not in providers


def test_sportsdb_only_with_opt_in(monkeypatch):
    monkeypatch.delenv("THESPORTSDB_FALLBACK_ENABLED", raising=False)
    assert source.sportsdb_finals(["2026-10-09"]) == []


def test_api_football_disabled_in_production(monkeypatch):
    from services import api_football_gateway as gateway
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_FOOTBALL_ENABLED", raising=False)
    monkeypatch.setenv("API_FOOTBALL_API_KEY", "dummy")
    monkeypatch.setattr(gateway, "reserve_request",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("no legacy quota should be spent")))
    assert gateway.api_football_get("fixtures") is None
