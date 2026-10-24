"""Rapid settlement uses only corroborated, completed 90-minute ESPN scores."""
from datetime import datetime, timezone

from leagues import fast_settlement
from leagues.editorial_settlement import grade_manual_slip
from leagues.results_checker import _lookup_settlement_score


NOW = datetime(2026, 10, 20, 21, 15, tzinfo=timezone.utc)


def _pick(home="Roma", away="Slovan Bratislava", league="UEFA Champions League",
          kickoff="2026-10-20T19:00:00+00:00"):
    return {
        "home_team": home, "away_team": away,
        "league": league, "kickoff": kickoff,
        "market": "home_win", "prediction": "Roma Win",
    }


def _espn_event(*, finished=True, home="AS Roma", away="Slovan Bratislava",
                game_day="2026-10-20T19:00:00Z", score_home="4", score_away="0"):
    return {
        "id": "espn-verified-roma",
        "date": game_day,
        "competitions": [{
            "status": {"type": {"completed": finished,
                                "name": ("STATUS_FULL_TIME" if finished
                                         else "STATUS_IN_PROGRESS")}},
            "competitors": [
                {"homeAway": "home", "score": score_home,
                 "team": {"id": "home-1", "displayName": home}},
                {"homeAway": "away", "score": score_away,
                 "team": {"id": "away-1", "displayName": away}},
            ],
        }],
    }


def test_rapid_espn_verified_full_time_settles_manual(monkeypatch):
    fast_settlement._CACHE.clear()
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {"events": [_espn_event()]}
    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]["dates"]))
        return Response()
    monkeypatch.setattr(fast_settlement.requests, "get", fake_get)
    scores, source = fast_settlement.collect_recent_verified_finals(
        [_pick()], now=NOW,
    )
    assert source == "espn-rapid"
    assert calls == [(
        "https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard",
        "20261020",
    )]
    confirmed = _lookup_settlement_score(
        scores, "Roma", "Slovan Bratislava", "2026-10-20",
    )
    assert confirmed["home_score"] == 4
    assert confirmed["score_90"] == {"home": 4, "away": 0}
    record = {"date": "2026-10-20", "tier": "5_odds",
              "games": [_pick()]}
    graded = grade_manual_slip(record, scores, now=NOW)
    assert graded["result_status"] == "won"
    assert graded["games"][0]["settlement_evidence"]["provider"] == "espn"
    # The 45-second cache prevents duplicate HTTP requests across product types.
    fast_settlement.collect_recent_verified_finals([_pick()], now=NOW)
    assert len(calls) == 1


def test_in_play_cannot_settle_and_wrong_fixture_date_never_matches(monkeypatch):
    fast_settlement._CACHE.clear()
    class Response:
        status_code = 200
        def json(self):
            return {"events": [_espn_event(finished=False)]}
    monkeypatch.setattr(fast_settlement.requests, "get",
                        lambda *a, **kw: Response())
    scores, _ = fast_settlement.collect_recent_verified_finals([_pick()], now=NOW)
    assert not scores

    fast_settlement._CACHE.clear()
    class FinishedResponse:
        status_code = 200
        def json(self):
            return {"events": [_espn_event()]}
    monkeypatch.setattr(fast_settlement.requests, "get",
                        lambda *a, **kw: FinishedResponse())
    scores, _ = fast_settlement.collect_recent_verified_finals([_pick()], now=NOW)
    assert _lookup_settlement_score(
        scores, "Roma", "Slovan Bratislava", "2026-10-21",
    ) is None
    assert _lookup_settlement_score(
        scores, "AS Roma Women", "Slovan Bratislava", "2026-10-20",
    ) is None


def test_only_recent_finished_or_finishing_fixtures_are_polled(monkeypatch):
    fast_settlement._CACHE.clear()
    calls = []
    monkeypatch.setattr(fast_settlement.requests, "get",
                        lambda *a, **kw: calls.append(a))
    scores, _ = fast_settlement.collect_recent_verified_finals(
        [_pick(kickoff="2026-10-20T21:00:00+00:00"),
         _pick(kickoff="2026-10-19T02:00:00+00:00")],
        now=NOW,
    )
    assert scores == {}
    assert calls == []


def test_unknown_competitions_remain_pending_no_fuzzy_resolution(monkeypatch):
    fast_settlement._CACHE.clear()
    calls = []
    monkeypatch.setattr(fast_settlement.requests, "get",
                        lambda *a, **kw: calls.append(a))
    scores, _ = fast_settlement.collect_recent_verified_finals(
        [_pick(league="Unmapped Fictional League")],
        now=NOW,
    )
    assert not scores
    assert calls == []


def test_saudi_results_use_live_espn_ksa_slug_not_rejected_registry_slug(monkeypatch):
    fast_settlement._CACHE.clear()
    queried = []
    class Response:
        status_code = 200
        def json(self):
            return {"events": [_espn_event(
                home="Al Nassr", away="Neom SC",
                game_day="2026-10-20T18:00:00Z",
                score_home="1", score_away="0",
            )]}
    def request(url, **kw):
        queried.append(url)
        return Response()
    monkeypatch.setattr(fast_settlement.requests, "get", request)
    pick = _pick(
        home="Al Nassr Club", away="Neom SC",
        league="Saudi Pro League", kickoff="2026-10-20T18:00:00+00:00",
    )
    scores, _ = fast_settlement.collect_recent_verified_finals(
        [pick], now=NOW,
    )
    assert queried == [
        "https://site.api.espn.com/apis/site/v2/sports/soccer/ksa.1/scoreboard",
    ]
    confirmed = _lookup_settlement_score(
        scores, "Al Nassr Club", "Neom SC", "2026-10-20",
    )
    assert confirmed and confirmed["score_90"] == {"home": 1, "away": 0}



def test_early_utc_kickoff_checks_previous_espn_board_without_misdating(monkeypatch):
    """ESPN local scoreboard date can precede the UTC fixture date."""
    fast_settlement._CACHE.clear()
    requested = []

    class Response:
        status_code = 200

        def __init__(self, events):
            self.events = events

        def json(self):
            return {"events": self.events}

    def fake_get(url, **kwargs):
        day = kwargs["params"]["dates"]
        requested.append(day)
        return Response([
            _espn_event(game_day="2026-10-20T00:30:00Z")
        ] if day == "20261019" else [])

    monkeypatch.setattr(fast_settlement.requests, "get", fake_get)
    now = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
    pick = _pick(kickoff="2026-10-20T00:30:00Z")
    scores, source = fast_settlement.collect_recent_verified_finals(
        [pick], now=now,
    )
    assert source == "espn-rapid"
    assert sorted(requested) == ["20261019", "20261020"]
    assert _lookup_settlement_score(
        scores, "Roma", "Slovan Bratislava", "2026-10-20",
    )["score_90"] == {"home": 4, "away": 0}
    assert _lookup_settlement_score(
        scores, "Roma", "Slovan Bratislava", "2026-10-19",
    ) is None


def test_rapid_openligadb_settles_missing_espn_german_final_without_key(monkeypatch):
    """Exact Bundesliga manual league labels can settle through a free FT feed."""
    from services import openligadb_score_source as free

    fast_settlement._CACHE.clear()
    monkeypatch.setenv("OPENLIGADB_ENABLED", "true")
    monkeypatch.setattr(fast_settlement.requests, "get",
                        lambda *args, **kwargs: type("R", (), {
                            "status_code": 200,
                            "json": lambda self: {"events": []},
                        })())
    fetched = []

    def season_finals(league, season):
        fetched.append((league, season))
        return [{
            "home": "Bayern Munich", "away": "Borussia Dortmund",
            "date": "2026-10-20", "home_score": 2, "away_score": 1,
            "score_90": {"home": 2, "away": 1},
            "completed": True, "provider": "openligadb",
            "provider_event_id": 11991, "match_status": "FT",
        }]

    monkeypatch.setattr(free, "_season_finals", season_finals)
    pick = _pick(
        home="Bayern Munich", away="Borussia Dortmund",
        league="Bundesliga", kickoff="2026-10-20T19:00:00Z",
    )
    scores, source = fast_settlement.collect_rapid_verified_finals(
        [pick], now=NOW,
    )
    assert fetched == [("bl1", 2026)]
    assert source == "espn-rapid+openligadb-rapid"
    result = _lookup_settlement_score(
        scores, "Bayern Munich", "Borussia Dortmund", "2026-10-20",
    )
    assert result and result["score_90"] == {"home": 2, "away": 1}
    assert result["provider"] == "openligadb"


def test_rapid_german_fallback_does_not_guess_unmapped_league(monkeypatch):
    from services import openligadb_score_source as free

    fast_settlement._CACHE.clear()
    monkeypatch.setenv("OPENLIGADB_ENABLED", "true")
    monkeypatch.setattr(fast_settlement.requests, "get",
                        lambda *args, **kwargs: type("R", (), {
                            "status_code": 200,
                            "json": lambda self: {"events": []},
                        })())
    monkeypatch.setattr(free, "_season_finals", lambda *args: (
        _ for _ in ()).throw(AssertionError("must not fetch a guessed league")))
    scores, source = fast_settlement.collect_rapid_verified_finals([
        _pick(league="Bundesliga U21"),
    ], now=NOW)
    assert scores == {}
    assert source == "espn-rapid"
