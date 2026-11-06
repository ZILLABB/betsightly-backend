"""NBA Stage 2E: bounded retries, process locks, score/pregame/daily reliability.

Fixture inputs are entirely synthetic; they never enter a real user's
prospective ledger, public betting routes, or GitHub Actions artifacts.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from basketball.research_automation import (
    exclusive_local_run, refresh_current_season, reliability_from_home,
    run_automation, _retried,
)
from basketball.research_data import read_games, write_games
from basketball.research_dashboard import render_dashboard

NOW = datetime(2026, 10, 24, 13, tzinfo=timezone.utc)
SOURCE = "sportsdataverse:espn_nba_schedules:v1"


def game(ident, season, *, status="scheduled", date="2026-10-25",
         home="1", away="2", score=115):
    return {
        "game_id": ident, "date": date, "season": season,
        "home_id": home, "away_id": away,
        "home_name": "Private Home", "away_name": "Private Away",
        "home_score": score if status == "final" else None,
        "away_score": score - 5 if status == "final" else None,
        "status": status, "postseason": False,
        "start_utc": date + "T20:00:00+00:00",
        "source": SOURCE, "retrieved_at": NOW.isoformat(),
    }


def fetched(games):
    return (games, [{"season": 2027, "source_url": "local fixture only",
                     "sha256": "test", "bytes": 1234}])


def fake_score(*, home, now):
    return {
        "status": "research_only",
        "scoreboard": {"status": "idle", "dates_checked": 0},
        "settlement": {"newly_settled": 0}, "performance": {},
    }


def fake_cycle(*, home, now, offline=False, days_ahead=2):
    assert days_ahead == 2
    return {
        "scoreboard": {"status": "idle"},
        "new_forecasts": 0, "eligible_forecasts": 0,
        "settlement": {"newly_settled": 0},
        "readiness": {"snapshot_health": "fresh"},
        "model_retrained": False, "score_models_retrained": False,
    }


def test_local_lock_blocks_overlapping_research_jobs(tmp_path):
    with exclusive_local_run(tmp_path):
        with pytest.raises(BlockingIOError, match="task is active"):
            with exclusive_local_run(tmp_path):
                pass
    with exclusive_local_run(tmp_path):
        assert (tmp_path / "automation.lock").is_file()


def test_retry_has_exactly_two_network_attempts_not_invalid_schema():
    attempted = []
    def flaky():
        attempted.append(1)
        if len(attempted) == 1:
            raise RuntimeError("HTTP_503")
        return "data"
    result, attempts = _retried(flaky, sleeper=lambda delay: None)
    assert result == "data" and attempts == 2
    assert len(attempted) == 2

    calls = []
    def malformed():
        calls.append(1)
        raise ValueError("fixture identity changed")
    with pytest.raises(ValueError, match="identity changed"):
        _retried(malformed, sleeper=lambda delay: None)
    assert len(calls) == 1


def test_lightweight_refresh_preserves_old_seasons_and_verified_finals(tmp_path):
    earlier = game("old-1", 2026, status="final", date="2025-10-20")
    prior_final = game("2027f", 2027, status="final", date="2026-10-23")
    future = game("2027s", 2027)
    write_games([earlier, prior_final, future], tmp_path/"nba_games.jsonl")
    stale_final = {**prior_final, "status": "scheduled",
                   "home_score": None, "away_score": None}
    new_future = game("2027new", 2027, date="2026-10-26")
    seen = []
    def fetch(years):
        seen.append(years)
        return fetched([stale_final, future, new_future])
    report = refresh_current_season(
        tmp_path, now=NOW, fetcher=fetch, sleeper=lambda delay: None)
    assert seen == [[2027]]  # Never fetch 11 seasons each hour.
    assert report["preserved_verified_finals"] == 1
    all_games = read_games(tmp_path/"nba_games.jsonl")
    assert len(all_games) == 4
    saved_final = next(g for g in all_games if g["game_id"] == "2027f")
    assert saved_final["status"] == "final"
    assert saved_final["home_score"] == prior_final["home_score"]
    assert (tmp_path/"current_season_refresh.json").is_file()


def test_current_season_missing_fixture_rejected_without_snapshot_changes(tmp_path):
    initial = [game("s1", 2027), game("s2", 2027)]
    snapshot = tmp_path/"nba_games.jsonl"
    write_games(initial, snapshot)
    before = snapshot.read_bytes()
    with pytest.raises(ValueError, match="lost local fixtures"):
        refresh_current_season(
            tmp_path, now=NOW, fetcher=lambda years: fetched([initial[0]]),
            sleeper=lambda delay: None,
        )
    assert snapshot.read_bytes() == before


def test_conflicting_verified_final_never_silently_overwritten(tmp_path):
    previously_verified = game("f1", 2027, status="final",
                               date="2026-10-23")
    write_games([previously_verified], tmp_path/"nba_games.jsonl")
    different_final = {**previously_verified, "home_score": 135}
    with pytest.raises(ValueError, match="score conflict"):
        refresh_current_season(
            tmp_path, now=NOW,
            fetcher=lambda years: fetched([different_final]),
            sleeper=lambda delay: None,
        )
    assert read_games(tmp_path/"nba_games.jsonl")[0]["home_score"] == 115


def test_hourly_pregame_serialized_and_does_not_retrain(tmp_path):
    write_games([game("one", 2027)], tmp_path/"nba_games.jsonl")
    called = []
    def source(years):
        called.append(("source", years))
        return fetched([game("one", 2027)])
    def score(*, home, now):
        called.append(("score", now))
        return fake_score(home=home, now=now)
    def cycle(*, home, now, offline=False, days_ahead=2):
        called.append(("cycle", offline))
        return fake_cycle(home=home, now=now, offline=offline,
                          days_ahead=days_ahead)
    first = run_automation(
        home=tmp_path, mode="pregame", now=NOW,
        season_fetcher=source, score_runner=score, cycle_runner=cycle,
        sleeper=lambda delay: None,
    )
    assert first["status"] == "succeeded"
    assert called[0] == ("source", [2027])
    assert called[1][0] == "score"
    assert called[2] == ("cycle", True)
    assert first["run"]["models_retrained"] is False
    assert first["run"]["new_forecasts"] == 0
    assert reliability_from_home(tmp_path, now=NOW)["tasks"]["pregame"]["status"] == "succeeded"
    assert not (tmp_path/"nba_paper.sqlite").exists()


def test_provider_partial_never_claims_scheduled_task_success(tmp_path):
    def down(*, home, now):
        return {**fake_score(home=home, now=now),
                "scoreboard": {"status": "partial", "dates_checked": 0}}
    report = run_automation(
        home=tmp_path, mode="score", now=NOW, score_runner=down)
    assert report["status"] == "degraded"
    assert report["health"]["details"]["scoreboard_status"] == "partial"
    assert reliability_from_home(tmp_path, now=NOW)["issues"] == ["score:degraded"]


def test_network_refresh_failure_does_not_write_fabricated_predictions(tmp_path):
    original = game("s1", 2027)
    snapshot = tmp_path/"nba_games.jsonl"
    write_games([original], snapshot)
    before = snapshot.read_bytes()
    attempts = []
    def unreachable(years):
        attempts.append(years)
        raise RuntimeError("HTTP_503")
    result = run_automation(
        home=tmp_path, mode="pregame", now=NOW,
        season_fetcher=unreachable,
        cycle_runner=lambda **kw: pytest.fail("Never forecast on failed refresh"),
        sleeper=lambda delay: None,
    )
    assert len(attempts) == 2
    assert result["status"] == "failed"
    assert result["health"]["details"]["error"] == "NBA_SOURCE_UNAVAILABLE_AFTER_RETRY"
    assert snapshot.read_bytes() == before
    assert not (tmp_path/"nba_paper.sqlite").exists()


def test_full_daily_cycle_retry_success_and_receipt(tmp_path):
    attempts = []
    def cycle(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("transient ESPN outage")
        return fake_cycle(**kwargs)
    outcome = run_automation(
        home=tmp_path, mode="full", now=NOW, cycle_runner=cycle,
        sleeper=lambda delay: None,
    )
    assert len(attempts) == 2
    assert attempts[0]["days_ahead"] == 2
    assert outcome["status"] == "succeeded"
    assert outcome["run"]["source_attempts"] == 2


def test_busy_task_cannot_modify_current_task_receipt(tmp_path):
    with exclusive_local_run(tmp_path):
        pending = run_automation(
            home=tmp_path, mode="score", now=NOW,
            score_runner=lambda **kw: pytest.fail("Must not run concurrently"),
        )
    assert pending["status"] == "busy"
    assert not (tmp_path/"automation_score.json").exists()


def test_reliability_marks_late_tasks_and_no_receipt_separately(tmp_path):
    run_automation(home=tmp_path, mode="score", now=NOW, score_runner=fake_score)
    report = reliability_from_home(tmp_path, now=NOW+timedelta(hours=4))
    assert report["tasks"]["score"]["status"] == "stale"
    assert report["tasks"]["pregame"]["status"] == "not_observed"
    assert report["issues"] == ["score:stale"]
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    again = reliability_from_home(tmp_path, now=NOW+timedelta(hours=4))
    assert report == again
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_dashboard_renders_sanitized_stage2e_job_health():
    health = {
        "tasks": {
            "score": {"status": "failed", "last_seen_at": "<script>x</script>"},
            "pregame": {"status": "not_observed"},
            "full": {"status": "succeeded"},
        },
        "issues": ["score:failed"],
    }
    html = render_dashboard(
        {"forecast_count": 0, "settled": 0, "pending": 0},
        [], [], reliability=health,
    )
    assert "Stage 2E · automation reliability" in html
    assert "score:failed" in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<script>x</script>" not in html


def test_scheduled_failure_does_not_hide_behind_later_manual_success(tmp_path):
    import json
    (tmp_path / "automation_pregame.json").write_text(
        json.dumps({
            "mode": "pregame", "research_only": True,
            "status": "succeeded", "checked_at": NOW.isoformat(),
            "details": {"source_attempts": 1},
        }), encoding="utf-8"
    )
    # The manual success receipt is not proof that Task Scheduler worked.
    (tmp_path / "scheduled_pregame_attempt.json").write_text(
        json.dumps({
            "mode": "pregame", "scheduling": "windows_task_runner",
            "started_at": (NOW-timedelta(minutes=10)).isoformat(),
            "finished_at": (NOW-timedelta(minutes=9)).isoformat(),
            "process_exit_code": 1, "status": "failed",
            "local_only": True,
        }), encoding="utf-8"
    )
    report=reliability_from_home(tmp_path,now=NOW)
    assert report["tasks"]["pregame"]["status"]=="succeeded"
    assert "pregame:scheduled_failed" in report["issues"]
    assert report["tasks"]["pregame"]["scheduled_attempt"]["exit_code"]==1


def test_scheduled_score_busy_is_not_falsely_counted_as_settlement(tmp_path):
    import json
    (tmp_path / "scheduled_score_attempt.json").write_text(
        json.dumps({
            "mode": "score", "scheduling": "windows_task_runner",
            "started_at": (NOW-timedelta(minutes=1)).isoformat(),
            "finished_at": NOW.isoformat(),
            "process_exit_code": 0, "status": "busy",
            "local_only": True,
        }), encoding="utf-8"
    )
    report=reliability_from_home(tmp_path,now=NOW)
    assert report["tasks"]["score"]["status"]=="not_observed"
    assert report["tasks"]["score"]["scheduled_attempt"]["status"]=="busy"
    assert report["tasks"]["score"]["scheduled_attempt"]["performed_research"] is False
    assert report["issues"]==[]


def test_corrupted_scheduled_attempt_reports_issue_without_changing_main_receipt(
    tmp_path
):
    (tmp_path / "scheduled_score_attempt.json").write_text("{broken")
    report=reliability_from_home(tmp_path,now=NOW)
    assert "score:scheduled_invalid" in report["issues"]
    assert report["tasks"]["score"]["status"]=="not_observed"


def test_optional_advanced_source_lag_is_visible_without_failing_baseline(tmp_path):
    import json
    (tmp_path/"automation_pregame.json").write_text(json.dumps({
        "mode":"pregame","research_only":True,"status":"succeeded",
        "checked_at":NOW.isoformat(),"details":{
            "advanced_sidecar":{"advanced_refresh":{
                "status":"partial",
                "assets":{"team":{"status":"unavailable",
                                  "reason":"insufficient_current_fixture_coverage"},
                          "player":{"status":"verified",
                                    "fixture_coverage":0.7778}}
            }}
        }
    }),encoding="utf-8")
    report=reliability_from_home(tmp_path,now=NOW)
    assert report["tasks"]["pregame"]["status"]=="succeeded"
    assert report["issues"]==[]
    assert report["advisories"]==["pregame:advanced_source_partial"]


def test_all_three_score_graders_visible_and_verified_idle_is_not_failure(tmp_path):
    result = run_automation(
        home=tmp_path, mode="score", now=NOW, score_runner=fake_score)
    assert result["status"] == "idle"
    assert result["run"]["independent_settlement_statuses"] == {
        "moneyline": "research_only",
        "opening_score": "research_only",
        "early_advanced": "research_only",
    }
    assert result["health"]["details"][
        "independent_settlement_statuses"] == (
            result["run"]["independent_settlement_statuses"])


def test_corrupt_advanced_ledger_never_reports_successful_hourly_check(
    tmp_path, monkeypatch
):
    from basketball import research_early_advanced_ops
    monkeypatch.setattr(
        research_early_advanced_ops, "settle",
        lambda home, now: {"status": "integrity_failed",
                           "new_settlements": 0})
    result = run_automation(
        home=tmp_path, mode="score", now=NOW, score_runner=fake_score)
    assert result["status"] == "failed"
    assert result["run"]["independent_settlement_statuses"][
        "early_advanced"] == "integrity_failed"
    assert reliability_from_home(tmp_path, now=NOW)["issues"] == [
        "score:failed"]


def test_unavailable_original_scoring_grader_is_degraded_not_succeeded(
    tmp_path, monkeypatch
):
    from basketball import research_opening_score
    def unavailable(home, now):
        raise RuntimeError("Independent score audit temporarily unavailable")
    monkeypatch.setattr(research_opening_score, "settle", unavailable)
    report = run_automation(
        home=tmp_path, mode="score", now=NOW, score_runner=fake_score)
    assert report["status"] == "degraded"
    assert report["run"]["independent_settlement_statuses"][
        "opening_score"] == "unavailable"
    assert reliability_from_home(tmp_path, now=NOW)["issues"] == [
        "score:degraded"]


def test_pregame_optional_advanced_unavailable_is_explicit_advisory(tmp_path):
    import json
    (tmp_path / "automation_pregame.json").write_text(json.dumps({
        "mode": "pregame", "research_only": True, "status": "succeeded",
        "checked_at": NOW.isoformat(),
        "details": {"advanced_sidecar": {
            "early_advanced": {"status": "unavailable", "created": 0},
        }},
    }), encoding="utf-8")
    report = reliability_from_home(tmp_path, now=NOW)
    assert report["tasks"]["pregame"]["status"] == "succeeded"
    assert report["issues"] == []
    assert report["advisories"] == ["pregame:early_advanced_unavailable"]
