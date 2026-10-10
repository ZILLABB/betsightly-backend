"""OpenLigaDB: free, keyless, final-only German score source."""
from datetime import date

from leagues import results_checker
from services import openligadb_score_source as source


def _match(*, is_finished=True, shortcut="bl1", season=2026,
           results=None, home="FC Bayern München", away="Borussia Dortmund",
           kickoff="2026-10-10T13:30:00Z", match_id=9901):
    if results is None:
        results = [
            {"resultTypeID": 1, "pointsTeam1": 1, "pointsTeam2": 0},
            {"resultTypeID": 2, "pointsTeam1": 2, "pointsTeam2": 1},
        ]
    return {
        "leagueShortcut": shortcut,
        "leagueSeason": season,
        "matchID": match_id,
        "matchDateTimeUTC": kickoff,
        "team1": {"teamName": home},
        "team2": {"teamName": away},
        "matchIsFinished": is_finished,
        "matchResults": results,
    }


def test_openligadb_strict_final_result_and_explicit_safe_alias():
    parsed = source._normalize_fixture(_match(), "bl1", 2026)
    assert parsed["home"] == "Bayern Munich"
    assert parsed["away"] == "Borussia Dortmund"
    assert parsed["score_90"] == {"home": 2, "away": 1}
    assert parsed["provider"] == "openligadb"
    assert parsed["match_status"] == "FT"
    assert parsed["date"] == "2026-10-10"


def test_unfinished_missing_or_ambiguous_score_is_never_settled():
    assert source._normalize_fixture(_match(is_finished=False), "bl1", 2026) is None
    assert source._normalize_fixture(_match(results=[]), "bl1", 2026) is None
    assert source._normalize_fixture(_match(results=[
        {"resultTypeID": 1, "pointsTeam1": 1, "pointsTeam2": 0}]), "bl1", 2026) is None
    assert source._normalize_fixture(_match(results=[
        {"resultTypeID": 2, "pointsTeam1": None, "pointsTeam2": 2}]),
        "bl1", 2026) is None
    assert source._normalize_fixture(_match(results=[
        {"resultTypeID": 2, "pointsTeam1": 1, "pointsTeam2": 1},
        {"resultTypeID": 2, "pointsTeam1": 2, "pointsTeam2": 1}]),
        "bl1", 2026) is None


def test_extra_time_and_penalty_result_types_are_rejected():
    for kind in (3, 4):
        assert source._normalize_fixture(_match(results=[
            {"resultTypeID": 2, "pointsTeam1": 1, "pointsTeam2": 1},
            {"resultTypeID": kind, "pointsTeam1": 2, "pointsTeam2": 1},
        ]), "bl1", 2026) is None


def test_wrong_league_year_and_missing_kickoff_are_rejected():
    assert source._normalize_fixture(_match(shortcut="bl2"), "bl1", 2026) is None
    assert source._normalize_fixture(_match(season=2025), "bl1", 2026) is None
    assert source._normalize_fixture(_match(kickoff=None), "bl1", 2026) is None
    assert source._season_for(date(2026, 6, 9)) == 2025
    assert source._season_for(date(2026, 7, 9)) == 2026


def test_only_explicit_german_domestic_league_targets_are_fetched(monkeypatch):
    requests = []
    def season_finals(shortcut, year):
        requests.append((shortcut, year))
        return [source._normalize_fixture(_match(), "bl1", 2026)]
    monkeypatch.setattr(source, "_season_finals", season_finals)
    monkeypatch.setenv("OPENLIGADB_ENABLED", "true")
    tickets = [
        {"league_slug": "ger.1", "home_team": "Bayern Munich",
         "away_team": "Borussia Dortmund",
         "kickoff": "2026-10-10T13:30:00Z"},
        {"league_slug": "ger.dfb_pokal", "home_team": "X",
         "away_team": "Y", "kickoff": "2026-10-10T13:30:00Z"},
        {"league_slug": "eng.1", "home_team": "X",
         "away_team": "Y", "kickoff": "2026-10-10T13:30:00Z"},
    ]
    scores = source.openligadb_finals(tickets)
    assert requests == [("bl1", 2026)]
    assert len(scores) == 1
    assert scores[0]["provider_event_id"] == 9901


def test_openligadb_opt_out_and_unknown_leagues_are_no_ops(monkeypatch):
    monkeypatch.setenv("OPENLIGADB_ENABLED", "false")
    assert source.openligadb_finals([{"league_slug": "ger.1",
        "kickoff": "2026-10-10T13:30:00Z"}]) == []
    monkeypatch.setenv("OPENLIGADB_ENABLED", "true")
    monkeypatch.setattr(source, "_season_finals",
                        lambda *args: (_ for _ in ()).throw(
                            AssertionError("must not query non-German matches")))
    assert source.openligadb_finals([{"league_slug": "eng.1",
        "kickoff": "2026-10-10T13:30:00Z"}]) == []


def test_request_is_cached_and_429_is_bounded(monkeypatch):
    source._CACHE.clear()
    calls = []
    class Response:
        status_code = 200
        headers = {}
        def json(self):
            return [_match()]
    def get(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()
    monkeypatch.setattr(source.requests, "get", get)
    assert len(source._season_finals("bl1", 2026)) == 1
    assert len(source._season_finals("bl1", 2026)) == 1
    assert len(calls) == 1
    assert calls[0][0][0].endswith("/getmatchdata/bl1/2026")

    source._CACHE.clear()
    class RateLimited:
        status_code = 429
        headers = {"Retry-After": "180"}
    monkeypatch.setattr(source.requests, "get",
                        lambda *a, **k: calls.append(1) or RateLimited())
    assert source._season_finals("bl1", 2026) == []
    assert source._season_finals("bl1", 2026) == []
    assert len(calls) == 2
    source._CACHE.clear()


def test_settlement_resolves_german_with_openligadb_not_api_football(monkeypatch):
    from services import free_football_score_sources as free
    monkeypatch.setenv("OPENLIGADB_ENABLED", "true")
    monkeypatch.setattr(results_checker, "_collect_espn_scores_ranged",
                        lambda *a, **kw: {})
    monkeypatch.setattr(source, "_season_finals",
                        lambda shortcut, year: [
                            source._normalize_fixture(_match(), shortcut, year)])
    monkeypatch.setattr(free, "football_data_finals", lambda *a: [])
    monkeypatch.setattr(free, "sportsdb_finals", lambda *a: [])
    monkeypatch.setattr(results_checker, "_get_odds_api_key", lambda: "")
    monkeypatch.setattr(results_checker, "_collect_apifootball_scores",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("suspended API-Football contacted")))
    picks = [{"league_slug": "ger.1", "home_team": "Bayern Munich",
              "away_team": "Borussia Dortmund",
              "kickoff": "2026-10-10T13:30:00Z"}]
    scores, providers = results_checker._collect_scores_for_picks(picks)
    assert results_checker._lookup_score(
        scores, "Bayern Munich", "Borussia Dortmund",
        "2026-10-10")["home_score"] == 2
    assert "openligadb" in providers
    assert "api-football" not in providers


def test_espn_already_verified_german_result_does_not_call_openligadb(
        monkeypatch):
    monkeypatch.setattr(results_checker, "_collect_espn_scores_ranged",
                        lambda *a, **kw: {
                            "bayern munich|borussia dortmund|2026-10-10": {
                                "home_score": 3, "away_score": 0}})
    monkeypatch.setattr(source, "openligadb_finals",
                        lambda *a: (_ for _ in ()).throw(
                            AssertionError("do not fetch when ESPN already final")))
    picks = [{"league_slug": "ger.1", "home_team": "Bayern Munich",
              "away_team": "Borussia Dortmund",
              "kickoff": "2026-10-10T13:30:00Z"}]
    scores, provider = results_checker._collect_scores_for_picks(picks)
    assert provider == "espn"
    assert len(scores) == 1
