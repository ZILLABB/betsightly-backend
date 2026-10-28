"""Private opening-week NBA experiment: synthetic only, no public picks."""
from datetime import datetime, timezone

from basketball.research_coldstart import (
    audit, benchmark, candidates, capture, cycle, settle,
)
from basketball.research_advanced_gaps import report as gap_report
from basketball.research_data import write_games
from basketball.research_cli import build_parser

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
SOURCE = "sportsdataverse:espn_nba_schedules:v1"


def game(gid, *, season=2027, date="2026-10-24",
         status="final", home="1", away="2", stamp=None):
    return {
        "game_id": str(gid), "season": season, "date": date,
        "status": status, "home_id": home, "away_id": away,
        "home_name": f"Team {home}", "away_name": f"Team {away}",
        "home_score": (110 if status == "final" else None),
        "away_score": (100 if status == "final" else None),
        "start_utc": stamp or date + "T20:00:00+00:00",
        "postseason": False, "source": SOURCE,
        "retrieved_at": NOW.isoformat(),
    }


def sample():
    # Last season is fully observed; two historical clubs have >=20 games.
    history = [game(5000+i, season=2026, date="2026-04-01",
               home="1" if i % 2 else "2",
               away="2" if i % 2 else "1") for i in range(240)]
    current = [game(7000+i, date=f"2026-10-{20+i:02}")
               for i in range(3)]
    upcoming = game(9000, date="2026-10-26", status="scheduled",
                    stamp="2026-10-26T20:00:00+00:00")
    return history + current + [upcoming]


def test_coldstart_captures_actual_future_and_settles_separately(tmp_path):
    games = sample()
    write_games(games, tmp_path / "nba_games.jsonl")
    available = candidates(games, now=NOW)
    assert len(available) == 1
    assert available[0]["current_home_games"] == 3
    assert available[0]["current_away_games"] == 3
    assert available[0]["prior_home_games"] >= 20
    assert available[0]["probability_home_win"] > 0.25
    assert capture(tmp_path, now=NOW)["created"] == 1
    assert capture(tmp_path, now=NOW)["created"] == 0
    before = (tmp_path / "coldstart_forecasts.jsonl").read_bytes()
    first = audit(tmp_path, now=NOW)
    assert first["status"] == "awaiting_first_final"
    assert first["forecast_count"] == 1
    assert first["verified_settlements"] == 0
    games[-1] = {**games[-1], "status": "final",
                 "home_score": 105, "away_score": 111}
    write_games(games, tmp_path / "nba_games.jsonl")
    after_tipoff = datetime(2026, 10, 26, 23, tzinfo=timezone.utc)
    assert settle(tmp_path, now=after_tipoff)["new_settlements"] == 1
    assert settle(tmp_path, now=after_tipoff)["new_settlements"] == 0
    audit_result = audit(tmp_path, now=after_tipoff)
    assert audit_result["status"] == "forward_observations"
    assert audit_result["verified_settlements"] == 1
    assert audit_result["prospective_brier"] is not None
    assert before == (tmp_path / "coldstart_forecasts.jsonl").read_bytes()


def test_coldstart_tamper_fails_closed(tmp_path):
    write_games(sample(), tmp_path / "nba_games.jsonl")
    assert capture(tmp_path, now=NOW)["created"] == 1
    ledger = tmp_path / "coldstart_forecasts.jsonl"
    ledger.write_text(ledger.read_text().replace(
        '"probability_home_win":0.', '"probability_home_win":0.9'))
    assert audit(tmp_path, now=NOW)["status"] == "integrity_failed"
    assert cycle(tmp_path, now=NOW)["status"] == "integrity_failed"


def test_no_backfill_when_game_already_started(tmp_path):
    fixtures = sample()
    write_games(fixtures, tmp_path / "nba_games.jsonl")
    late = datetime(2026, 10, 26, 21, tzinfo=timezone.utc)
    assert capture(tmp_path, now=late)["created"] == 0
    assert not (tmp_path / "coldstart_forecasts.jsonl").exists()


def test_same_day_finals_cannot_become_same_day_pregame_features():
    games = sample()
    # Date-only batching applies even if an earlier final has occurred.
    other = game(8000, date="2026-10-26", status="final")
    games.append(other)
    row = candidates(games, now=NOW)[0]
    assert row["current_home_games"] == 3
    assert row["current_away_games"] == 3


def test_no_previous_season_club_baseline_prevents_invented_strength():
    games = sample()
    games[-1] = {**games[-1], "away_id": "999", "away_name": "New club"}
    assert candidates(games, now=NOW) == []


def test_historical_benchmark_does_not_use_2027_finals():
    b = benchmark(sample())
    assert b["walkforward_folds"]["2025"]["games"] == 0
    assert b["walkforward_folds"]["2026"]["games"] == 0
    assert b["model_retrained"] is False
    assert b["no_writes"] is True


def test_exact_side_coverage_gap_audit(tmp_path):
    games = sample()
    write_games(games, tmp_path/"nba_games.jsonl")
    folder = tmp_path/"advanced"
    folder.mkdir()
    import json
    team = [
        {"game_id": "7000", "team_id": "1"},
        {"game_id": "7000", "team_id": "2"},
    ]
    (folder/"team_2027.json").write_text(json.dumps(team))
    (folder/"team_2027.manifest.json").write_text(json.dumps({
        "season": 2027, "kind": "team", "covered_final_games": 1,
        "provenance_checked_at": NOW.isoformat()}))
    result = gap_report(tmp_path)
    assert result["verified_final_games"] == 3
    assert result["assets"]["team"]["complete_games"] == 1
    assert result["assets"]["team"]["missing_games"] == 2
    assert result["assets"]["team"]["status"] == "source_lag"
    assert result["assets"]["player"]["status"] == "missing"


def test_coldstart_cli_keeps_public_v1_unchanged(tmp_path):
    choices = ("coldstart-backtest", "coldstart-report",
               "coldstart-cycle", "advanced-gaps")
    for name in choices:
        assert build_parser().parse_args([name]).command == name
    assert audit(tmp_path, now=NOW)["status"] == "awaiting_first_forecast"
    assert not list(tmp_path.iterdir())

def test_readiness_reports_actual_shadow_eligible_and_stays_readonly(tmp_path):
    from basketball.research_coldstart import readiness
    write_games(sample(), tmp_path/"nba_games.jsonl")
    before = (tmp_path/"nba_games.jsonl").read_bytes()
    report = readiness(tmp_path, now=NOW)
    assert report["status"] == "ready_for_shadow_capture"
    assert report["eligible_next_48h"] == 1
    assert report["eligible_samples"][0]["game_id"] == "9000"
    assert report["capture_is_a_separate_write"] is True
    assert report["no_writes"] is True
    assert before == (tmp_path/"nba_games.jsonl").read_bytes()
    assert not (tmp_path/"coldstart_forecasts.jsonl").exists()


def test_readiness_missing_data_explicit(tmp_path):
    from basketball.research_coldstart import readiness
    report = readiness(tmp_path, now=NOW)
    assert report["status"] == "source_missing"
    assert report["eligible_next_48h"] == 0
    assert list(tmp_path.iterdir()) == []


def test_historical_paired_calibration_and_metric_disclosure():
    from basketball.research_coldstart import _paired_metrics
    rows = [{
        "actual_home_win": 1, "probability_home_win": .6,
        "previous_season_home_baseline": .5,
    }, {
        "actual_home_win": 0, "probability_home_win": .4,
        "previous_season_home_baseline": .5,
    }]
    result = _paired_metrics(rows)
    assert result["games"] == 2
    assert result["candidate_brier"] == .16
    assert result["prior_home_baseline_brier"] == .25
    assert result["paired_brier_improvement"] == .09
    assert result["candidate_accuracy"] == 1.0
    assert sum(b["games"] for b in result["candidate_calibration"]) == 2
    assert result["candidate_log_loss"] is not None


def test_forward_paired_metrics_use_only_actual_verification(tmp_path):
    write_games(sample(), tmp_path/"nba_games.jsonl")
    assert capture(tmp_path, now=NOW)["created"] == 1
    initial = audit(tmp_path, now=NOW)
    assert initial["prospective_baseline_brier"] is None
    games = sample()
    games[-1] = {**games[-1], "status": "final",
                 "home_score": 105, "away_score": 111}
    write_games(games, tmp_path/"nba_games.jsonl")
    assert settle(tmp_path, now=datetime(2026, 10, 26, 23,
                                        tzinfo=timezone.utc))["new_settlements"] == 1
    result = audit(tmp_path)
    assert result["prospective_paired_metrics"]["games"] == 1
    assert result["prospective_baseline_brier"] is not None
    assert result["last_30_verified"]["games"] == 1
