"""NBA idle-status and read-only provider diagnosis regression tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from basketball.research_data import write_games
from basketball.research_scoreboard import refresh_recent_finals
from basketball.research_score_diagnostics import (
    inspect_recent, probe_source,
)
from basketball.research_score_only import write_scoreboard_health

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def game(status="final"):
    return {
        "game_id": "401909847", "date": "2026-10-23",
        "season": 2027, "status": status,
        "home_id": "14", "away_id": "8",
        "home_name": "Miami Heat", "away_name": "Detroit Pistons",
        "home_score": 111 if status == "final" else None,
        "away_score": 105 if status == "final" else None,
        "start_utc": "2026-10-24T00:00:00+00:00",
        "postseason": False,
        "source": "sportsdataverse:espn_nba_schedules:v1",
        "retrieved_at": NOW.isoformat(),
    }


def final_event():
    return {"id": "401909847", "date": "2026-10-24T00:00:00Z",
            "season": {"type": 2},
            "status": {"type": {"completed": True, "state": "post",
                                "name": "STATUS_FINAL"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"id": "14"}, "score": "111"},
                {"homeAway": "away", "team": {"id": "8"}, "score": "105"},
            ]}]}


def test_when_prior_run_settled_game_no_request_is_explicitly_idle():
    calls = []
    def forbidden(day):
        calls.append(day)
        raise AssertionError("No request is required")
    snapshot = [game()]
    _, report = refresh_recent_finals(snapshot, as_of=NOW, loader=forbidden)
    assert report["status"] == "idle"
    assert report["verification_performed"] is False
    assert report["dates_requested"] == 0
    assert report["dates_checked"] == 0
    assert not calls
    local = inspect_recent(snapshot, now=NOW)
    assert local["completed_finals"] == 1
    assert local["started_without_final"] == 0
    assert local["dates_awaiting_result"] == []


def test_missing_final_keeps_the_date_eligible_for_a_real_provider_request():
    calls = []
    def simulated_outage(day):
        calls.append(day)
        raise RuntimeError("HTTP_403")
    data = [game(status="scheduled")]
    _, report = refresh_recent_finals(data, as_of=NOW, loader=simulated_outage)
    assert calls == ["2026-10-23"]
    assert report["status"] == "partial"
    assert report["verification_performed"] is False
    assert report["dates_requested"] == 1
    assert inspect_recent(data, now=NOW)["started_without_final"] == 1


def test_readonly_provider_probe_confirms_existing_exact_final(tmp_path):
    path = tmp_path / "nba_games.jsonl"
    write_games([game()], path)
    before = path.read_bytes()
    response = probe_source(
        tmp_path, day="2026-10-23", now=NOW,
        espn_loader=lambda day: {"events": [final_event()]},
        nba_loader=lambda day: (_ for _ in ()).throw(
            RuntimeError("NBA_CDN_DATE_MISMATCH")),
    )
    assert response["status"] == "verified"
    assert response["results"]["espn"]["status"] == "verified_match"
    assert response["results"]["espn"]["exact_final_matches"] == 1
    assert response["results"]["nba_official"]["status"] == "unavailable_for_date"
    assert before == path.read_bytes()
    assert not (tmp_path / "nba_paper.sqlite").exists()
    assert response["no_writes"] is True


def test_probe_reachable_with_no_matching_final_is_not_verified(tmp_path):
    write_games([game()], tmp_path / "nba_games.jsonl")
    payload = {"events": []}
    result = probe_source(
        tmp_path, day="2026-10-23", now=NOW,
        espn_loader=lambda day: payload,
        nba_loader=lambda day: (_ for _ in ()).throw(
            RuntimeError("NBA_CDN_DATE_MISMATCH")),
    )
    assert result["status"] == "unverified"
    assert result["results"]["espn"]["status"] == "no_exact_final_match"


def test_health_remembers_last_real_check_after_idle(tmp_path):
    worked = {"status": "ok", "dates_checked": 1,
              "dates_requested": 1, "verified_new_finals": 1}
    write_scoreboard_health(tmp_path, worked, NOW)
    then = NOW + timedelta(hours=1)
    write_scoreboard_health(tmp_path, {
        "status": "idle", "dates_checked": 0,
        "dates_requested": 0, "verified_new_finals": 0,
    }, then)
    saved = json.loads((tmp_path / "scoreboard_health.json").read_text())
    assert saved["status"] == "idle"
    assert saved["last_actual_check_at"] == NOW.isoformat()
    assert saved["last_actual_check_status"] == "ok"
    assert saved["checked_at"] == then.isoformat()


def test_probe_disallows_old_or_future_dates(tmp_path):
    write_games([game()], tmp_path / "nba_games.jsonl")
    for bad in ("2026-10-05", "2026-10-25"):
        with pytest.raises(ValueError, match="last 14 days"):
            probe_source(tmp_path, day=bad, now=NOW,
                         espn_loader=lambda day: {"events": []})
