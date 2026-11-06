"""Verify first-final queue, actual grades and source >82 quality alerts."""
import json
from datetime import datetime, timezone

from basketball.research_cli import build_parser
from basketball.research_coldstart_ops import calendar_anomalies, closeout
from basketball.research_coldstart import capture, settle
from basketball.research_data import write_games
from tests.test_basketball_coldstart import sample

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def test_first_16_pregame_would_appear_in_separate_experiment(tmp_path):
    games=sample()
    write_games(games, tmp_path/"nba_games.jsonl")
    assert capture(tmp_path, now=NOW)["created"]==1
    before={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result=closeout(tmp_path,now=NOW)
    assert result["forecast_count"]==1
    assert result["verified_settlements"]==0
    assert result["operational_pending_states"]=={"not_started":1}
    assert result["upcoming_samples"][0]["verified_final_available"] is False
    assert result["verified_directional_correct"]==0
    assert result["no_writes"] is True
    assert before=={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}


def test_verified_final_pending_then_real_score_grading(tmp_path):
    games=sample()
    write_games(games,tmp_path/"nba_games.jsonl")
    assert capture(tmp_path,now=NOW)["created"]==1
    games[-1]={**games[-1],"status":"final","home_score":112,"away_score":104}
    write_games(games,tmp_path/"nba_games.jsonl")
    after=datetime(2026,10,26,23,tzinfo=timezone.utc)
    missing=closeout(tmp_path,now=after)
    assert missing["operational_pending_states"]=={
        "final_available_pending_grade":1}
    assert missing["verified_directional_correct"]==0
    assert settle(tmp_path,now=after)["new_settlements"]==1
    result=closeout(tmp_path,now=after)
    assert result["operational_pending_states"]=={"verified_settled":1}
    assert result["verified_directional_correct"] + result[
        "verified_directional_incorrect"] == 1
    assert result["settled_samples"][0]["result_status"]=="verified_final"
    assert result["prospective_paired_metrics"]["games"]==1


def test_no_false_loss_when_no_verified_final(tmp_path):
    games=sample()
    write_games(games,tmp_path/"nba_games.jsonl")
    assert capture(tmp_path,now=NOW)["created"]==1
    after=datetime(2026,10,27,3,tzinfo=timezone.utc)
    result=closeout(tmp_path,now=after)
    assert result["operational_pending_states"]=={"overdue_unverified_final":1}
    assert result["verified_directional_incorrect"]==0
    assert result["overdue_unverified_final_count"]==1


def test_excess_regular_season_count_is_only_an_audit():
    first=sample()[0]
    games=[{**first,"game_id":str(700+i)}
           for i in range(83)]
    report=calendar_anomalies(games,season=2026)
    assert report["teams_over_standard_count"]==2
    assert report["anomalies"][0]["completed_season_games"]==83
    assert report["not_proof_of_corruption"] is True
    assert report["automatic_source_mutation"] is False


def test_missing_source_is_not_success_or_mutation(tmp_path):
    assert build_parser().parse_args(
        ["coldstart-closeout"]).command=="coldstart-closeout"
    assert closeout(tmp_path,now=NOW)["status"]=="source_missing"
    assert list(tmp_path.iterdir())==[]


def test_corrupt_ledger_metrics_withheld(tmp_path):
    games=sample()
    write_games(games,tmp_path/"nba_games.jsonl")
    assert capture(tmp_path,now=NOW)["created"]==1
    p=tmp_path/"coldstart_forecasts.jsonl"
    p.write_text(p.read_text().replace(
        '"probability_home_win":0.', '"probability_home_win":0.9'))
    result=closeout(tmp_path,now=NOW)
    assert result["status"]=="integrity_failed"
    assert result["prospective_paired_metrics"] is None
    assert result["operational_pending_states"] is None


def test_wave1_preserves_distinction_from_trusted_v1(tmp_path):
    from basketball import research_wave1_report
    # Existing Wave 1 cold-start behavior must not mutate an empty directory.
    result=research_wave1_report.wave1_report(tmp_path,now=NOW)
    assert result["settlement"]["total_paper_forecasts"]==0
    early=result["separate_early_season_experiment"]
    assert early["status"]=="source_missing"
    assert early["not_official_v1_calibration"] is True
    assert not list(tmp_path.iterdir())
