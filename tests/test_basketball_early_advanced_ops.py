"""NBA advance pregame score evidence must be truly paired and immutable."""
from datetime import datetime, timezone
import json

from basketball.research_data import write_games
from basketball.research_opening_score import capture as original_capture
from basketball.research_early_advanced import paired_uncertainty
from basketball.research_early_advanced_ops import (
    audit, capture, settle, cycle
)
from basketball.research_cli import build_parser
from tests.test_basketball_early_advanced import fixture_data

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
DONE = datetime(2026, 10, 26, 23, tzinfo=timezone.utc)


def setup(tmp_path):
    games, team = fixture_data()
    write_games(games, tmp_path / "nba_games.jsonl")
    box = tmp_path / "advanced"
    box.mkdir()
    for year in (2024, 2025, 2026, 2027):
        entries = [x for x in team if (
            2024 <= int(x["game_id"]) // 1000 <= 2026 and
            int(x["game_id"]) // 1000 == year) or
            (year == 2027 and 27000 <= int(x["game_id"]) < 28000)]
        (box / f"team_{year}.json").write_text(json.dumps(entries))
    return games


def test_requires_immutable_original_early_score_forecast(tmp_path):
    setup(tmp_path)
    result = capture(tmp_path, now=NOW)
    assert result["created"] == 0
    assert not (tmp_path / "early_advanced_forecasts.jsonl").exists()


def test_pregame_capture_matched_original_and_verified_settlement(tmp_path):
    fixtures = setup(tmp_path)
    assert original_capture(tmp_path, now=NOW)["created"] == 1
    original = (tmp_path / "opening_score_forecasts.jsonl").read_bytes()
    result = capture(tmp_path, now=NOW)
    assert result["created"] == 1
    assert capture(tmp_path, now=NOW)["created"] == 0
    status = audit(tmp_path, now=NOW)
    assert status["forecast_count"] == 1
    assert status["settled"] == 0
    assert status["operational_states"] == {"not_started": 1}
    advanced = (tmp_path / "early_advanced_forecasts.jsonl").read_bytes()
    data = json.loads(advanced)
    reference = json.loads(original)
    assert data["original_predicted_total"] == reference["predicted_total"]
    assert data["research_only"] is True
    fixtures[-1] = {**fixtures[-1], "status": "final",
                    "home_score": 114, "away_score": 102}
    write_games(fixtures, tmp_path / "nba_games.jsonl")
    assert audit(tmp_path, now=DONE)["operational_states"] == (
        {"final_available_pending_grade": 1})
    assert settle(tmp_path, now=DONE)["new_settlements"] == 1
    assert settle(tmp_path, now=DONE)["new_settlements"] == 0
    final = audit(tmp_path, now=DONE)
    assert final["status"] == "forward_observations"
    assert final["settled"] == 1
    assert final["paired_forward_metrics"]["games"] == 1
    assert final["paired_forward_metrics"]["targets"]["total"][
        "advanced_mae"] is not None
    assert advanced == (tmp_path / "early_advanced_forecasts.jsonl").read_bytes()
    assert original == (tmp_path / "opening_score_forecasts.jsonl").read_bytes()


def test_tamper_advanced_sha_fails_closed_and_no_extra_score(tmp_path):
    setup(tmp_path)
    original_capture(tmp_path, now=NOW)
    assert capture(tmp_path, now=NOW)["created"] == 1
    file = tmp_path / "early_advanced_forecasts.jsonl"
    file.write_text(file.read_text().replace('"estimated_possessions":',
                                             '"estimated_possessions":999,"extra":'))
    assert audit(tmp_path, now=NOW)["status"] == "integrity_failed"
    assert cycle(tmp_path, now=NOW)["status"] == "integrity_failed"


def test_both_methods_require_actual_pregame(tmp_path):
    setup(tmp_path)
    original_capture(tmp_path, now=NOW)
    late = datetime(2026, 10, 26, 21, tzinfo=timezone.utc)
    assert capture(tmp_path, now=late)["created"] == 0
    assert not (tmp_path / "early_advanced_forecasts.jsonl").exists()


def test_historical_small_sample_uncertainty_is_not_invented():
    results = paired_uncertainty([])
    assert results["status"] == "insufficient_independent_days"
    assert results["targets"] == {}
    assert results["not_a_promotion_gate"] is True
    rows = [{
        "date": f"2026-10-{d:02}", "predicted_total":200,
        "reference_predicted_total":205, "actual_total":204,
        "predicted_home_margin":5, "reference_predicted_home_margin":6,
        "actual_home_margin":5,
        "predicted_home_points":102.5,"reference_predicted_home_points":105.5,
        "actual_home_points":104.5,
        "predicted_away_points":97.5,"reference_predicted_away_points":99.5,
        "actual_away_points":99.5
    } for d in range(1,11)]
    result=paired_uncertainty(rows,draws=100)
    assert result["targets"]["total"]["improvement_demonstrated"] is True
    assert result["days"]==10


def test_cli_isolation():
    assert (build_parser().parse_args(["early-advanced-cycle"]).command
            == "early-advanced-cycle")
    assert (build_parser().parse_args(["early-advanced-report"]).command
            == "early-advanced-report")
