"""Fail fast on invalid ESPN monthly requests without hiding degraded coverage."""
from datetime import datetime, timezone

from leagues import espn_source


class Response:
    def __init__(self, code):
        self.status_code = code

    def json(self):
        return {}


def _prepare(monkeypatch, tmp_path, status):
    hits = []
    monkeypatch.setattr(espn_source, "CACHE_PATH", tmp_path / "ep.json")
    monkeypatch.setattr(espn_source, "ESPN_CLUB_LEAGUES",
                        {"alg.1": "Algeria"})
    monkeypatch.setattr(espn_source, "_FETCH_HEALTH", {})
    monkeypatch.setattr(espn_source.time, "sleep", lambda seconds: None)

    def get(url, *, params, timeout):
        hits.append((url, params["dates"]))
        return Response(status)

    monkeypatch.setattr(espn_source.requests, "get", get)
    return hits


def test_http_400_failure_is_not_retried_during_board_fetch(monkeypatch, tmp_path):
    hits = _prepare(monkeypatch, tmp_path, 400)
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    rows = espn_source.get_fixtures(days_ahead=1, force=True, now=now)
    assert rows == []
    assert len(hits) == 1
    health = espn_source.fetch_health()["alg.1"]
    assert health["request_succeeded"] is False
    assert health["retryable"] is False
    metadata = espn_source.cache_metadata()
    assert metadata["failed_leagues"] == ["alg.1"]
    assert metadata["failed_league_details"]["alg.1"]["error"] == "202610: HTTP 400"
    assert metadata["complete"] is False


def test_transient_503_keeps_bounded_retry(monkeypatch, tmp_path):
    hits = _prepare(monkeypatch, tmp_path, 503)
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    rows = espn_source.get_fixtures(days_ahead=1, force=True, now=now)
    assert rows == []
    assert len(hits) == 3
    assert espn_source.fetch_health()["alg.1"]["retryable"] is True
    assert espn_source.cache_metadata()["complete"] is False


def test_single_month_400_health_includes_explicit_status(monkeypatch):
    monkeypatch.setattr(espn_source.requests, "get",
                        lambda *args, **kwargs: Response(400))
    assert espn_source._fetch_league("alg.1", "202610") == []
    health = espn_source.fetch_health()["alg.1"]
    assert health["http_status"] == 400
    assert health["retryable"] is False
