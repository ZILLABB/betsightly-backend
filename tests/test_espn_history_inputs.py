import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from leagues import base_rates, team_history
from leagues.espn_history_fetch import finished_events


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


def test_base_rates_and_team_history_share_supported_fetch():
    event = _event("match", "2026-09-20T12:00Z")
    with patch("leagues.espn_history_fetch.finished_events", return_value=[event]) as fetch:
        assert base_rates._fetch_finished_range("bra.2", "20260901", "20260922") == [(2, 1)]
        assert team_history._fetch_finished("bra.2", "20260901", "20260922")[0]["hs"] == 2
    assert fetch.call_count == 2


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
