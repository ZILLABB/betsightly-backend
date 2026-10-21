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
