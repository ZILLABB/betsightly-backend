import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from leagues import base_rates, team_history
import requests

from leagues.espn_history_fetch import HistoryMonthUnavailable, finished_events


def _event(event_id, date, home=2, away=1, completed=True):
    return {
        "id": event_id, "date": date,
        "competitions": [{
            "status": {"type": {"completed": completed}},
            "competitors": [
                {"homeAway": "home", "score": str(home), "team": {"displayName": "Home"}},
                {"homeAway": "away", "score": str(away), "team": {"displayName": "Away"}},
            ],
        }],
    }


def test_historical_fetch_uses_months_and_filters_dates_and_duplicates():
    august = Mock(status_code=200)
    august.json.return_value = {"events": [
        _event("before", "2026-08-08T12:00Z"),
        _event("valid", "2026-08-10T12:00Z"),
    ]}
    september = Mock(status_code=200)
    september.json.return_value = {"events": [
        _event("valid", "2026-08-10T12:00Z"),
        _event("after", "2026-09-23T12:00Z"),
        _event("second", "2026-09-22T12:00Z"),
    ]}
    with patch("leagues.espn_history_fetch.requests.get", side_effect=[august, september]) as get:
        found = finished_events("bra.2", "20260809", "20260922")
    assert [event["id"] for event in found] == ["valid", "second"]
    assert [call.kwargs["params"]["dates"] for call in get.call_args_list] == ["202608", "202609"]


def test_base_rates_and_team_history_share_supported_fetch(tmp_path, monkeypatch):
    from leagues import history_months
    monkeypatch.setattr(history_months, "MONTH_DIR", tmp_path)
    monkeypatch.setattr(history_months.shared_history_store,
                        "production_shared", lambda: False)
    event = _event("match", "2026-09-20T12:00Z")
    with patch("leagues.history_months.finished_events", return_value=[event]) as fetch:
        assert base_rates._fetch_finished_range("bra.2", "20260901", "20260922") == [(2, 1)]
        assert team_history._fetch_finished("bra.2", "20260901", "20260922")[0]["hs"] == 2
    assert fetch.call_count == 1


def test_broken_range_cache_is_not_reused_even_as_failure_fallback(tmp_path, monkeypatch):
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps({"_priors": {"global": {"matches": 100}}}))
    monkeypatch.setattr(base_rates, "CACHE_PATH", base_path)
    with patch.object(base_rates, "compute_base_rates", side_effect=RuntimeError("offline")):
        assert base_rates.get_base_rates(slugs={"bra.2": "Brazil"}) == {}

    history_path = tmp_path / "history.json"
    history_path.write_text(json.dumps({"matches": [{"home": "Old"}]}))
    monkeypatch.setattr(team_history, "CACHE_PATH", history_path)
    with patch.object(team_history, "build", side_effect=RuntimeError("offline")):
        assert team_history.load() == {"matches": []}


def test_monthly_cache_is_reusable(tmp_path, monkeypatch):
    base_path = tmp_path / "base.json"
    base = {"_cache_schema": base_rates.HISTORY_CACHE_SCHEMA,
            "_priors": {"global": {"matches": 100}}}
    base_path.write_text(json.dumps(base))
    monkeypatch.setattr(base_rates, "CACHE_PATH", base_path)
    assert base_rates.get_base_rates(slugs={}) == base

    history_path = tmp_path / "history.json"
    history = {"_cache_schema": team_history.HISTORY_CACHE_SCHEMA, "matches": []}
    history_path.write_text(json.dumps(history))
    monkeypatch.setattr(team_history, "CACHE_PATH", history_path)
    assert team_history.load() == history


def test_asof_history_requires_pre_cutoff_completed_observation():
    cutoff = datetime(2026, 9, 22, 7, tzinfo=timezone.utc)
    earlier = _event("earlier", "2026-09-20T12:00Z")
    earlier["observed_completed_at"] = "2026-09-20T15:00:00Z"
    later = _event("later", "2026-09-22T01:00Z")
    later["observed_completed_at"] = "2026-09-22T08:00:00Z"
    unknown = _event("unknown", "2026-09-21T12:00Z")
    response = Mock(status_code=200)
    response.json.return_value = {"events": [earlier, later, unknown]}
    with patch("leagues.espn_history_fetch.requests.get", return_value=response):
        assert [e["id"] for e in finished_events(
            "bra.2", "20260901", "20260922", as_of=cutoff
        )] == ["earlier"]
        assert base_rates._fetch_finished_range(
            "bra.2", "20260901", "20260922", as_of=cutoff
        ) == [(2, 1)]
        assert [m["date"] for m in team_history._fetch_finished(
            "bra.2", "20260901", "20260922", as_of=cutoff
        )] == ["2026-09-20"]


def test_asof_never_reuses_current_history_cache(tmp_path, monkeypatch):
    cutoff = datetime(2026, 9, 22, 7, tzinfo=timezone.utc)
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps({"_cache_schema": base_rates.HISTORY_CACHE_SCHEMA,
                                     "_priors": {"global": {"matches": 999}}}))
    monkeypatch.setattr(base_rates, "CACHE_PATH", base_path)
    with patch.object(base_rates, "compute_base_rates", return_value={"_priors": {}}) as compute:
        assert base_rates.get_base_rates(slugs={}, as_of=cutoff) == {"_priors": {}}
    compute.assert_called_once_with({}, as_of=cutoff)

    history_path = tmp_path / "history.json"
    history_path.write_text(json.dumps({"_cache_schema": team_history.HISTORY_CACHE_SCHEMA,
                                        "matches": [{"home": "Future"}]}))
    monkeypatch.setattr(team_history, "CACHE_PATH", history_path)
    with patch.object(team_history, "build", return_value={"matches": []}) as build:
        assert team_history.load(as_of=cutoff) == {"matches": []}
    build.assert_called_once_with(as_of=cutoff)


def test_retryable_history_failure_never_returns_partial_months():
    august = Mock(status_code=200)
    august.json.return_value = {"events": [_event("aug", "2026-08-20T12:00Z")]}
    rate_limited = Mock(status_code=429)
    with patch("leagues.espn_history_fetch.requests.get",
               side_effect=[august, rate_limited, rate_limited]) as get, \
            patch("leagues.espn_history_fetch.time.sleep") as sleep:
        try:
            finished_events("bra.2", "20260801", "20260922")
        except HistoryMonthUnavailable:
            pass
        else:
            raise AssertionError("partial league history was accepted")
    assert get.call_count == 3
    sleep.assert_called_once()


def test_timeout_retries_once_then_fails_closed():
    with patch("leagues.espn_history_fetch.requests.get",
               side_effect=requests.Timeout("offline")) as get, \
            patch("leagues.espn_history_fetch.time.sleep"):
        try:
            finished_events("bra.2", "20260901", "20260922")
        except HistoryMonthUnavailable:
            pass
        else:
            raise AssertionError("timeout was treated as empty league")
    assert get.call_count == 2


def test_permanently_unsupported_league_is_distinct_from_retryable_failure():
    unavailable = Mock(status_code=400)
    with patch("leagues.espn_history_fetch.requests.get", return_value=unavailable) as get:
        try:
            finished_events("alg.1", "20260901", "20260922")
        except HistoryMonthUnavailable as exc:
            assert exc.permanent
        else:
            raise AssertionError("unsupported league treated as valid history")
    get.assert_called_once()


def test_permanent_unavailability_can_be_cached_with_valid_league_samples(
        tmp_path, monkeypatch):
    path = tmp_path / "base.json"
    monkeypatch.setattr(base_rates, "CACHE_PATH", path)
    measured = {"_cache_schema": base_rates.HISTORY_CACHE_SCHEMA,
                "_priors": {"global": {"matches": 100}},
                "_failed_leagues": [], "_unavailable_leagues": ["alg.1"]}
    with patch.object(base_rates, "compute_base_rates", return_value=measured):
        assert base_rates.get_base_rates(slugs={}) == measured
    assert json.loads(path.read_text()) == measured

    history_path = tmp_path / "history.json"
    monkeypatch.setattr(team_history, "CACHE_PATH", history_path)
    history = {"_cache_schema": team_history.HISTORY_CACHE_SCHEMA,
               "matches": [{"home": "Measured"}],
               "failed_leagues": [], "unavailable_leagues": ["alg.1"]}
    with patch.object(team_history, "build", return_value=history):
        assert team_history.load(force=True) == history
    assert json.loads(history_path.read_text()) == history


def test_incomplete_new_history_does_not_replace_last_complete_cache(tmp_path, monkeypatch):
    base_path = tmp_path / "base.json"
    complete = {"_cache_schema": base_rates.HISTORY_CACHE_SCHEMA,
                "_priors": {"global": {"matches": 100}}}
    base_path.write_text(json.dumps(complete))
    monkeypatch.setattr(base_rates, "CACHE_PATH", base_path)
    with patch.object(base_rates, "compute_base_rates", return_value={
            "_cache_schema": base_rates.HISTORY_CACHE_SCHEMA,
            "_failed_leagues": ["bra.2"], "_priors": {}}):
        assert base_rates.get_base_rates(slugs={}, force=True) == complete
    assert json.loads(base_path.read_text()) == complete

    history_path = tmp_path / "history.json"
    previous = {"_cache_schema": team_history.HISTORY_CACHE_SCHEMA,
                "matches": [{"home": "Preserved"}]}
    history_path.write_text(json.dumps(previous))
    monkeypatch.setattr(team_history, "CACHE_PATH", history_path)
    with patch.object(team_history, "build", return_value={
            "_cache_schema": team_history.HISTORY_CACHE_SCHEMA,
            "failed_leagues": ["bra.2"], "matches": []}):
        assert team_history.load(force=True) == previous
    assert json.loads(history_path.read_text()) == previous
