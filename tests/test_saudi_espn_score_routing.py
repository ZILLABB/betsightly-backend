"""Saudi league ESPN endpoints are ksa.1, not the older sau.1 slug."""
from leagues import fast_settlement, results_checker


class _OK:
    status_code = 200
    def json(self):
        return {"events": []}


def test_rapid_score_fetch_uses_real_saudi_espn_slug(monkeypatch):
    calls = []
    monkeypatch.setattr(fast_settlement.requests, "get",
                        lambda url, **kw: (calls.append(url), _OK())[1])
    fast_settlement._CACHE.clear()
    assert fast_settlement._fetch_confirmed_events("sau.1", "2026-10-20") == []
    assert calls == [
        "https://site.api.espn.com/apis/site/v2/sports/soccer/ksa.1/scoreboard",
    ]


def test_historical_score_fetch_uses_real_saudi_espn_slug(monkeypatch):
    calls = []
    monkeypatch.setattr(results_checker.requests, "get",
                        lambda url, **kw: (calls.append(url), _OK())[1])
    rows = results_checker._collect_espn_scores_ranged(
        "2026-10-20", "2026-10-20", league_slugs={"sau.1"},
    )
    assert rows == {}
    assert calls == [
        "https://site.api.espn.com/apis/site/v2/sports/soccer/ksa.1/scoreboard",
    ]
