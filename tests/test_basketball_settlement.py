"""NBA paper settlement tests: verified IDs, final-only, bounded free feed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from basketball.research_data import read_games, write_games
from basketball.research_scoreboard import (
    download_scoreboard, parse_scoreboard, parse_final_event,
    preserve_older_verified_finals,
    refresh_recent_finals, selected_dates, verify_finals,
)
from basketball.research_score_only import settle_once
from basketball.research_store import open_ledger, save_forecasts

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
SOURCE = "sportsdataverse:espn_nba_schedules:v1"


def start(day="2026-10-24"):
    return day + "T08:00:00+00:00"


def scheduled(ident="401910001", day="2026-10-24"):
    return {
        "game_id": ident, "date": day, "season": 2027,
        "status": "scheduled", "home_id": "11", "away_id": "22",
        "home_name": "Home", "away_name": "Away",
        "home_score": None, "away_score": None,
        "start_utc": start(day), "postseason": False,
        "source": SOURCE, "retrieved_at": NOW.isoformat(),
    }


def espn_event(ident="401910001", day="2026-10-24", *,
               home_id="11", away_id="22", home_score="114",
               away_score="108", complete=True):
    return {
        "id": ident, "date": start(day),
        "season": {"type": 2},
        "status": {"type": {
            "completed": complete,
            "state": "post" if complete else "in",
            "name": "STATUS_FINAL" if complete else "STATUS_IN_PROGRESS",
        }},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": home_id}, "score": home_score},
            {"homeAway": "away", "team": {"id": away_id}, "score": away_score},
        ]}],
    }


def test_only_real_final_status_with_valid_competitors_is_accepted():
    event = espn_event()
    final = parse_final_event(event, retrieved_at=NOW.isoformat())
    assert final["home_score"] == 114 and final["away_score"] == 108
    assert final["home_id"] == "11"
    assert parse_final_event(espn_event(complete=False),
                             retrieved_at=NOW.isoformat()) is None
    postseason = espn_event()
    postseason["season"]["type"] = 3
    assert parse_final_event(postseason, retrieved_at=NOW.isoformat()) is None
    tie = espn_event(home_score="101", away_score="101")
    with pytest.raises(ValueError, match="tied"):
        parse_final_event(tie, retrieved_at=NOW.isoformat())
    ambiguous = espn_event()
    ambiguous["competitions"][0]["competitors"][1]["homeAway"] = "home"
    with pytest.raises(ValueError, match="Ambiguous"):
        parse_final_event(ambiguous, retrieved_at=NOW.isoformat())


def test_fixture_identity_and_existing_finals_fail_closed():
    source = scheduled()
    final = parse_final_event(espn_event(), retrieved_at=NOW.isoformat())
    updated, stats = verify_finals([source], {source["game_id"]: final})
    assert updated[0]["status"] == "final"
    assert updated[0]["source"] == "espn:nba:scoreboard:v1"
    assert stats["verified_new_finals"] == 1
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_finals([source], {source["game_id"]: {
            **final, "away_id": "999"}})
    with pytest.raises(ValueError, match="Conflicting verified"):
        verify_finals(updated, {source["game_id"]: {
            **final, "away_score": 110}})
    wrong_start = {**final, "start_utc": "2026-10-20T08:00:00+00:00"}
    with pytest.raises(ValueError, match="kickoff identity mismatch"):
        verify_finals([source], {source["game_id"]: wrong_start})


def test_persist_prior_verified_final_if_github_is_behind():
    old = scheduled()
    final = {**old, "status": "final", "home_score": 114,
             "away_score": 108, "source": "espn:nba:scoreboard:v1"}
    merged, retained = preserve_older_verified_finals([old], [final])
    assert retained == 1
    assert merged[0]["home_score"] == 114
    with pytest.raises(ValueError, match="score conflict"):
        preserve_older_verified_finals([
            {**final, "away_score": 107}], [final])


def test_bounded_recent_dates_and_partial_provider_errors():
    source = [scheduled()]
    assert selected_dates(source, NOW) == ["2026-10-24"]

    def unavailable(day):
        raise RuntimeError("simulated network outage")

    untouched, health = refresh_recent_finals(
        source, as_of=NOW, loader=unavailable)
    assert untouched == source
    assert health["status"] == "partial"
    assert health["verified_new_finals"] == 0
    assert health["failed_dates"] == [
        {"date": "2026-10-24", "error": "RuntimeError",
         "detail": "simulated network outage"}]

    def complete(day):
        return {"events": [espn_event()]}

    updated, health = refresh_recent_finals(
        source, as_of=NOW, loader=complete)
    assert updated[0]["status"] == "final"
    assert health["status"] == "ok"
    assert health["verified_new_finals"] == 1
    assert health["dates_requested"] == 1


def test_score_only_updates_snapshot_and_settles_immutable_forecast(tmp_path):
    # Choose actual past times to satisfy immutable forecast validation.
    now = datetime.now(timezone.utc)
    tipoff = now + timedelta(minutes=30)
    created = now - timedelta(minutes=1)
    day = tipoff.date().isoformat()
    source = {**scheduled(day=day), "start_utc": tipoff.isoformat(),
              "retrieved_at": now.isoformat()}
    write_games([source], tmp_path / "nba_games.jsonl")
    prediction = {
        "game_id": source["game_id"], "date": day,
        "start_utc": tipoff.isoformat(), "generated_at": created.isoformat(),
        "home_team_id": "11", "away_team_id": "22",
        "home_team": "Home", "away_team": "Away",
        "home_win_probability": .62, "away_win_probability": .38,
        "model_version": "nba-moneyline-offline-v1",
        "feature_schema": "nba-pregame-v1",
        "research_only": True, "not_for_betting": True,
        "bookmaker_odds_verified": False, "booking_code": None,
    }
    with open_ledger(tmp_path / "nba_paper.sqlite") as ledger:
        assert save_forecasts(ledger, [prediction])["inserted"] == 1

    def loader(requested_date):
        assert requested_date == day
        event = espn_event(day=day)
        event["date"] = tipoff.isoformat()
        return {"events": [event]}

    evaluation_time = now + timedelta(hours=4)
    result = settle_once(home=tmp_path, now=evaluation_time,
                         loader=loader)
    assert result["scoreboard"]["verified_new_finals"] == 1
    assert result["settlement"]["newly_settled"] == 1
    assert result["performance"]["settled"] == 1
    assert result["models_retrained"] is False
    assert read_games(tmp_path / "nba_games.jsonl")[0]["status"] == "final"
    again = settle_once(home=tmp_path, now=evaluation_time, offline=True)
    assert again["settlement"]["newly_settled"] == 0
    assert again["performance"]["settled"] == 1
    assert (tmp_path / "scoreboard_health.json").is_file()


def test_scoreboard_rejects_no_events_and_identical_final_conflicts():
    with pytest.raises(ValueError, match="events collection"):
        parse_scoreboard({}, retrieved_at=NOW.isoformat())
    invalid = {"events": [espn_event(), espn_event(home_score="116")]}
    with pytest.raises(ValueError, match="Conflicting"):
        parse_scoreboard(invalid, retrieved_at=NOW.isoformat())


def test_scoreboard_falls_back_to_validated_cdn_without_guessing(monkeypatch):
    from basketball import research_scoreboard as module
    attempted = []

    def probe(url, *, expected_host, timeout):
        attempted.append(expected_host)
        if expected_host == "site.api.espn.com":
            raise RuntimeError("HTTP_403")
        assert "xhr=1" in url and "date=20261024" in url
        return {"sbData": {"events": [espn_event()]}}

    monkeypatch.setattr(module, "_fetch_json", probe)
    response = download_scoreboard("2026-10-24")
    assert len(response["events"]) == 1
    assert attempted == ["site.api.espn.com", "cdn.espn.com"]
    assert len(parse_scoreboard(response, retrieved_at=NOW.isoformat())) == 1


def test_failed_both_espn_hosts_show_safe_http_codes(monkeypatch):
    from basketball import research_scoreboard as module

    def blocked(url, *, expected_host, timeout):
        raise RuntimeError("HTTP_403")

    monkeypatch.setattr(module, "_fetch_json", blocked)
    with pytest.raises(RuntimeError, match="site:HTTP_403; cdn:HTTP_403"):
        download_scoreboard("2026-10-24")


def test_malformed_cdn_does_not_fake_a_final(monkeypatch):
    from basketball import research_scoreboard as module

    def probe(url, *, expected_host, timeout):
        if expected_host == "site.api.espn.com":
            raise RuntimeError("HTTP_403")
        return {"sbData": "<html>403 Access Denied</html>"}

    monkeypatch.setattr(module, "_fetch_json", probe)
    with pytest.raises(RuntimeError, match="CDN_INVALID_SBDATA"):
        download_scoreboard("2026-10-24")


def test_historical_source_omission_keeps_previously_verified_final_only():
    """A truncated replacement must not discard old independently verified scores."""
    prior = scheduled("401910002", "2026-10-23")
    verified = {**prior,"status":"final","home_score":114,"away_score":108,
                "source":"espn:nba:scoreboard:v1"}
    future = scheduled("401910003", "2026-10-25")
    old_future = scheduled("401910004", "2026-10-26")
    merged, kept = preserve_older_verified_finals(
        [future],[verified,old_future])
    assert kept == 1
    assert {item["game_id"] for item in merged} == {
        "401910002","401910003"}
    assert next(row for row in merged if row["game_id"]=="401910002") == verified
    assert "401910004" not in {item["game_id"] for item in merged}


def test_score_check_prioritizes_older_unsettled_over_newer_unpredicted():
    dates=[f"2026-10-{day:02d}" for day in range(11,25)]
    games=[scheduled(str(600000+i),day) for i,day in enumerate(dates)]
    chosen=selected_dates(games,NOW,pending_dates=["2026-10-11"])
    assert len(chosen)==12
    assert chosen[0]=="2026-10-11"
    assert "2026-10-24" in chosen
