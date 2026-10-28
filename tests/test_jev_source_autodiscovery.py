from datetime import datetime, timezone
import pytest

from leagues import external_openligadb as source
from leagues import jev_shadow_worker as worker

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
ON = {"BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED": "true"}


def test_no_flag_stops_current_group_network(monkeypatch):
    monkeypatch.setattr(source, "_read_json", lambda url: pytest.fail("no network"))
    result = source.fetch_current_matchday("bl1", environ={}, now=NOW)
    assert result["status"] == "disabled"
    assert result["network_called"] is False


def test_current_group_uses_pinned_https_endpoint_and_correct_season(monkeypatch):
    source._CACHE.clear()
    urls = []
    row = {
        "matchID": 888, "leagueShortcut": "bl1",
        "leagueSeason": 2026, "matchDateTimeUTC": "2026-10-30T17:00:00Z",
        "team1": {"teamName": "Team A"},
        "team2": {"teamName": "Team B"},
        "matchIsFinished": False, "matchResults": [],
    }
    def read(url):
        urls.append(url)
        if url.endswith("/getcurrentgroup/bl1"):
            return {"groupOrderID": 8, "groupName": "8. Spieltag"}
        return [row]
    monkeypatch.setattr(source, "_read_json", read)
    response = source.fetch_current_matchday("bl1", environ=ON, now=NOW)
    assert response["status"] == "ok"
    assert response["auto_discovered_group"] == 8
    assert response["auto_discovered_season"] == 2026
    assert len(response["evidence"]) == 1
    assert urls == [
        "https://api.openligadb.de/getcurrentgroup/bl1",
        "https://api.openligadb.de/getmatchdata/bl1/2026/8",
    ]


def test_in_january_season_is_previous_starting_year():
    jan = datetime(2027, 1, 3, tzinfo=timezone.utc)
    assert source._season_start(jan) == 2026


@pytest.mark.parametrize("bad_group", [
    {}, [], None, {"groupOrderID": "8"}, {"groupOrderID": -1},
    {"groupOrderID": True}, {"groupOrderID": 999},
])
def test_bad_current_group_never_makes_second_request(monkeypatch, bad_group):
    called = []
    def read(url):
        called.append(url)
        return bad_group
    monkeypatch.setattr(source, "_read_json", read)
    response = source.fetch_current_matchday("bl2", environ=ON, now=NOW)
    assert response["status"] == "unavailable"
    assert len(called) == 1
    assert "fixtures" not in response


def test_unapproved_group_url_cannot_expand_to_untrusted_hosts():
    with pytest.raises(ValueError):
        source._read_json("https://attacker.test/getcurrentgroup/bl1")
    with pytest.raises(ValueError):
        source._read_json("https://api.openligadb.de/getcurrentgroup/untrusted")


def test_worker_autodiscover_does_not_run_without_jev_key(monkeypatch):
    monkeypatch.setattr(worker, "configured_sources",
                        lambda raw: pytest.fail("should not read sources"))
    report = worker.run_staging_once(environ={
        "ENVIRONMENT": "staging",
        "BETSIGHTLY_JEV_SOURCE_AUTODISCOVER": "true",
    }, now=NOW)
    assert report["source_calls"] == 0
    assert report["jev_calls"] == 0
