"""Isolated early-season full-game scoring evidence; synthetic NBA games."""
from datetime import datetime, timezone
import json

from basketball.research_opening_score import (
    audit, benchmark, candidates, capture, cycle, settle, _metrics,
    _corrected, VERSION,
)
from basketball.research_data import write_games
from basketball.research_cli import build_parser
from tests.test_basketball_coldstart import sample, game

NOW=datetime(2026,10,25,12,tzinfo=timezone.utc)


def test_earlier_only_future_market_capture_and_exact_score_settlement(tmp_path):
    games=sample()
    write_games(games,tmp_path/"nba_games.jsonl")
    available=candidates(games,now=NOW)
    assert len(available)==1
    assert available[0]["game_id"]=="9000"
    assert available[0]["current_home_games"]==3
    assert available[0]["current_away_games"]==3
    assert available[0]["predicted_total"]>150
    assert available[0]["predicted_home_points"]>70
    assert capture(tmp_path,now=NOW)["created"]==1
    assert capture(tmp_path,now=NOW)["created"]==0
    assert audit(tmp_path,now=NOW)["operational_states"]["not_started"]==1
    saved=(tmp_path/"opening_score_forecasts.jsonl").read_bytes()
    games[-1]={**games[-1],"status":"final","home_score":105,
               "away_score":111}
    write_games(games,tmp_path/"nba_games.jsonl")
    after=datetime(2026,10,26,23,tzinfo=timezone.utc)
    assert audit(tmp_path,now=after)["operational_states"][
        "final_available_pending_settlement"]==1
    assert settle(tmp_path,now=after)["new_settlements"]==1
    assert settle(tmp_path,now=after)["new_settlements"]==0
    result=audit(tmp_path,now=after)
    assert result["status"]=="forward_observations"
    assert result["settled"]==1
    assert result["prospective_metrics"]["games"]==1
    assert result["prospective_metrics"]["targets"]["total"]["candidate_mae"] is not None
    assert result["prospective_metrics"]["targets"]["home_margin"]["candidate_mae"] is not None
    assert result["prospective_metrics"]["targets"]["home_points"]["candidate_mae"] is not None
    assert result["prospective_metrics"]["targets"]["away_points"]["candidate_mae"] is not None
    assert saved==(tmp_path/"opening_score_forecasts.jsonl").read_bytes()


def test_same_day_final_does_not_leak_into_future_predictions():
    games=sample()
    games.append(game(95555,date="2026-10-26",status="final",
                      home="1",away="2"))
    eligible=candidates(games,now=NOW)
    assert eligible[0]["current_home_games"]==3
    assert eligible[0]["current_away_games"]==3


def test_not_after_tipoff(tmp_path):
    write_games(sample(),tmp_path/"nba_games.jsonl")
    late=datetime(2026,10,26,21,tzinfo=timezone.utc)
    assert capture(tmp_path,now=late)["created"]==0
    assert not (tmp_path/"opening_score_forecasts.jsonl").exists()


def test_tampered_forecast_is_rejected_and_never_scored(tmp_path):
    write_games(sample(),tmp_path/"nba_games.jsonl")
    assert capture(tmp_path,now=NOW)["created"]==1
    ledger=tmp_path/"opening_score_forecasts.jsonl"
    original=ledger.read_text()
    ledger.write_text(original.replace('"predicted_total":',
                                   '"predicted_total":999, "new_field":'))
    assert audit(tmp_path,now=NOW)["status"]=="integrity_failed"
    assert cycle(tmp_path,now=NOW)["status"]=="integrity_failed"


def test_mismatch_score_projections_with_recomputed_sha_also_rejected(tmp_path):
    from basketball.research_coldstart import _signed, _json
    write_games(sample(),tmp_path/"nba_games.jsonl")
    capture(tmp_path,now=NOW)
    ledger=tmp_path/"opening_score_forecasts.jsonl"
    row=json.loads(ledger.read_text())
    row["predicted_total"]+=7
    signed={k:v for k,v in row.items() if k!="sha256"}
    row["sha256"]=_signed(signed)
    ledger.write_text(_json(row)+"\n")
    result=audit(tmp_path,now=NOW)
    assert result["status"]=="integrity_failed"
    assert result["prospective_metrics"] is None


def test_historical_benchmark_no_fake_cohort():
    data=sample()
    report=benchmark(data)
    assert report["model_version"]==VERSION
    assert report["pooled"]["games"]==0
    assert report["no_writes"] is True
    assert report["market_lines_or_odds_present"] is False


def test_historical_paired_errors_are_matched():
    example=[{
        "predicted_total":210,"league_baseline_total":215,"actual_total":209,
        "predicted_home_margin":5,"league_baseline_margin":0,"actual_home_margin":4,
        "predicted_home_points":107.5,"league_baseline_home_points":107.5,
        "actual_home_points":106.5,
        "predicted_away_points":102.5,"league_baseline_away_points":107.5,
        "actual_away_points":102.5,
    }]
    result=_metrics(example)
    assert result["games"]==1
    assert result["targets"]["total"]["candidate_mae"]==1
    assert result["targets"]["total"]["paired_mae_improvement"]==5
    assert result["targets"]["home_margin"]["candidate_mae"]==1


def test_no_source_classification_mutation(tmp_path):
    from basketball.research_cup_classification import CUP_HOME, CUP_AWAY
    fixture={**game(14501,season=2026,date="2025-12-16",
            home="18",away="24",
            stamp="2025-12-17T01:30:00+00:00"),
            "home_name":CUP_HOME,"away_name":CUP_AWAY,
            "home_score":124,"away_score":113}
    full=sample()+[fixture]
    write_games(full,tmp_path/"nba_games.jsonl")
    before=(tmp_path/"nba_games.jsonl").read_bytes()
    assert "14501" not in [r["game_id"] for r in _corrected(full)]
    assert before==(tmp_path/"nba_games.jsonl").read_bytes()


def test_cli_commands_and_empty_report(tmp_path):
    for name in ("opening-score-backtest","opening-score-cycle",
                 "opening-score-report"):
        assert build_parser().parse_args([name]).command==name
    result=audit(tmp_path,now=NOW)
    assert result["status"]=="awaiting_first_forecast"
    assert result["forecasts"]==0
    assert list(tmp_path.iterdir())==[]


def test_waves_do_not_conflate_score_and_moneyline(tmp_path):
    from basketball.research_wave1_report import wave1_report
    report=wave1_report(tmp_path,now=NOW)
    assert report["settlement"]["total_paper_forecasts"]==0
    assert report["separate_opening_score_experiment"]["forecast_count"]==0
    assert report["separate_early_season_experiment"]["forecast_count"]==0
    assert not list(tmp_path.iterdir())
