from unittest.mock import Mock, patch

import pytest

from leagues import history_months
from leagues.espn_history_fetch import HistoryMonthUnavailable


def _event(event_id="one", date="2026-09-20T12:00Z"):
    return {"id": event_id, "date": date, "competitions": [{
        "status": {"type": {"completed": True}},
        "competitors": [
            {"homeAway": "home", "score": "2", "team": {"displayName": "Home"}},
            {"homeAway": "away", "score": "1", "team": {"displayName": "Away"}},
        ],
    }]}


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(history_months, "MONTH_DIR", tmp_path)
    monkeypatch.setattr(history_months.shared_history_store,
                        "production_shared", lambda: False)


def test_normalized_month_is_reused_across_two_windows(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    response = Mock(status_code=200)
    response.json.return_value = {"events": [_event()]}
    with patch("leagues.espn_history_fetch.requests.get", return_value=response) as get:
        a = history_months.finished_matches("bra.2", "20260901", "20260922")
        b = history_months.finished_matches("bra.2", "20260901", "20260923")
    assert a == b and a[0]["hs"] == 2
    assert get.call_count == 1
    artifact = list(tmp_path.glob("*.json"))
    assert len(artifact) == 1


def test_transient_failure_uses_complete_stale_month(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(history_months, "CURRENT_TTL", -1)
    response = Mock(status_code=200)
    response.json.return_value = {"events": [_event()]}
    with patch("leagues.espn_history_fetch.requests.get", return_value=response):
        first = history_months.finished_matches("bra.2", "20260901", "20260922")
    unavailable = Mock(status_code=503)
    with patch("leagues.espn_history_fetch.requests.get", return_value=unavailable), \
            patch("leagues.espn_history_fetch.time.sleep"):
        assert history_months.finished_matches(
            "bra.2", "20260901", "20260922") == first


def test_no_cache_failed_month_never_returns_partial_history(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    good = Mock(status_code=200)
    good.json.return_value = {"events": [_event("aug", "2026-08-20T12:00Z")]}
    bad = Mock(status_code=502)
    with patch("leagues.espn_history_fetch.requests.get",
               side_effect=[good, bad, bad]), \
            patch("leagues.espn_history_fetch.time.sleep"):
        with pytest.raises(HistoryMonthUnavailable):
            history_months.finished_matches("bra.2", "20260801", "20260922")


def test_permanent_unsupported_month_is_negatively_cached(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    bad = Mock(status_code=400)
    with patch("leagues.espn_history_fetch.requests.get", return_value=bad) as get:
        for _ in range(2):
            with pytest.raises(HistoryMonthUnavailable) as caught:
                history_months.finished_matches("unknown.league", "20260901", "20260922")
            assert caught.value.permanent
    assert get.call_count == 1
