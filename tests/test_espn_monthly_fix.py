"""Regression tests to copy to tests/test_espn_monthly_fix.py in the backend repo."""
from datetime import datetime, timezone

from leagues import espn_source


class FakeResponse:
    def __init__(self, code=200, events=None):
        self.status_code = code
        self._events = events or []

    def json(self):
        return {"leagues": [{"name": "Premier League"}], "events": self._events}


def event(fixture_id, kickoff):
    return {
        "id": fixture_id,
        "date": kickoff,
        "competitions": [{
            "status": {"type": {"name": "STATUS_SCHEDULED"}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": f"Home {fixture_id}"}},
                {"homeAway": "away", "team": {"displayName": f"Away {fixture_id}"}},
            ],
        }],
    }


def setup(monkeypatch, tmp_path, http):
    monkeypatch.setattr(espn_source, "CACHE_PATH", tmp_path / "espn.json")
    monkeypatch.setattr(espn_source, "ESPN_CLUB_LEAGUES", {"eng.1": "Premier League"})
    monkeypatch.setattr(espn_source, "tournament_context", lambda *args: {})
    monkeypatch.setattr(espn_source, "_parse_odds", lambda comp: {})
    monkeypatch.setattr(espn_source.requests, "get", http)
    espn_source._FETCH_HEALTH.clear()


def test_same_month_uses_one_monthly_request(monkeypatch, tmp_path):
    calls = []
    def get(url, params, timeout):
        calls.append(params["dates"])
        assert params["limit"] == 500
        return FakeResponse(events=[event("sep", "2026-09-19T14:00:00Z")])
    setup(monkeypatch, tmp_path, get)
    fixtures = espn_source.get_fixtures(
        days_ahead=7, now=datetime(2026, 9, 17, 12, tzinfo=timezone.utc))
    assert calls == ["202609"]
    assert [f["event_id"] for f in fixtures] == ["sep"]
    assert espn_source.cache_metadata()["complete"] is True


def test_cross_month_filters_deduplicates_and_marks_complete(monkeypatch, tmp_path):
    calls = []
    def get(url, params, timeout):
        month = params["dates"]
        calls.append(month)
        assert month in {"202609", "202610"}, "Never send YYYYMMDD-YYYYMMDD to ESPN"
        overlap = event("overlap", "2026-10-02T14:00:00Z")
        if month == "202609":
            return FakeResponse(events=[event("sep", "2026-09-30T14:00:00Z"), overlap,
                                        event("old", "2026-09-01T14:00:00Z")])
        return FakeResponse(events=[overlap, event("late", "2026-10-20T14:00:00Z")])
    setup(monkeypatch, tmp_path, get)
    fixtures = espn_source.get_fixtures(
        days_ahead=7, now=datetime(2026, 9, 29, 12, tzinfo=timezone.utc))
    assert calls == ["202609", "202610"]
    assert {f["event_id"] for f in fixtures} == {"sep", "overlap"}
    assert len(fixtures) == 2
    assert espn_source.cache_metadata()["complete"] is True
    assert espn_source.fetch_health()["eng.1"]["failed_months"] == []


def test_one_failed_month_is_not_reported_complete(monkeypatch, tmp_path):
    calls = []
    def get(url, params, timeout):
        month = params["dates"]
        calls.append(month)
        if month == "202610":
            return FakeResponse(code=503)
        return FakeResponse(events=[event("sep", "2026-09-30T14:00:00Z")])
    setup(monkeypatch, tmp_path, get)
    fixtures = espn_source.get_fixtures(
        days_ahead=7, now=datetime(2026, 9, 29, 12, tzinfo=timezone.utc))
    assert [f["event_id"] for f in fixtures] == ["sep"]
    assert calls == ["202609", "202610"] * 3
    assert espn_source.cache_metadata()["complete"] is False
    assert espn_source.cache_metadata()["failed_leagues"] == ["eng.1"]
    assert espn_source.fetch_health()["eng.1"]["failed_months"] == ["202610"]


def test_valid_empty_month_is_success(monkeypatch, tmp_path):
    calls = []
    def get(url, params, timeout):
        calls.append(params["dates"])
        return FakeResponse(events=[])
    setup(monkeypatch, tmp_path, get)
    fixtures = espn_source.get_fixtures(
        days_ahead=7, now=datetime(2026, 9, 17, 12, tzinfo=timezone.utc))
    assert fixtures == []
    assert calls == ["202609"]
    assert espn_source.cache_metadata()["complete"] is True
