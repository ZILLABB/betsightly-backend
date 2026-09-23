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
