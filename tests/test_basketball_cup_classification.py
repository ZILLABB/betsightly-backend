"""Exact 2025 Cup classification, no retroactive NBA forecast changes."""
from datetime import datetime, timezone

from basketball.research_cli import build_parser
from basketball.research_cup_classification import (
    CUP_HOME, CUP_AWAY, identify_cup_final, review, from_home,
)
from basketball.research_data import write_games
from tests.test_basketball_coldstart import game as _game

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def _cup():
    return {
        **_game(899101, season=2026, date="2025-12-16",
                home="18", away="24",
                stamp="2025-12-17T01:30:00+00:00"),
        "home_name": CUP_HOME, "away_name": CUP_AWAY,
        "home_score": 124, "away_score": 113,
    }


def _sample():
    rows = []
    for i in range(82):
        rows.append({
            **_game(30000+i, season=2026, date="2026-02-01",
                    home="18", away="99"),
            "home_name": CUP_HOME,
            "away_name": "Other club",
        })
        rows.append({
            **_game(40000+i, season=2026, date="2026-02-01",
                    home="98", away="24"),
            "home_name": "Other opponent",
            "away_name": CUP_AWAY,
        })
    for i in range(50):
        rows.append(_game(50000+i, season=2026, date="2026-02-01",
                          home="12", away="13"))
    rows.append(_cup())
    rows.append({
        **_game(999001, season=2027, date="2026-10-26", status="scheduled",
                home="18", away="24",
                stamp="2026-10-26T20:00:00+00:00"),
        "home_name": CUP_HOME, "away_name": CUP_AWAY
    })
    return rows


def test_exact_real_competition_identified_without_guessing_id():
    rows = _sample()
    label, cup = identify_cup_final(rows)
    assert label == "matched_verified_event"
    assert [g["game_id"] for g in cup] == ["899101"]
    assert identify_cup_final(rows[:-2])[0] == "not_identified_in_local_source"


def test_counterfactual_preserves_provider_data_and_reports_83_to_82(tmp_path):
    rows = _sample()
    write_games(rows, tmp_path/"nba_games.jsonl")
    before = (tmp_path/"nba_games.jsonl").read_bytes()
    report = from_home(tmp_path, now=NOW)
    assert report["status"] == "review_only"
    assert report["cup_final_source_game_id"] == "899101"
    assert report["raw_season_calendar"]["teams_over_standard_count"] == 2
    assert report["counterfactual_calendar_after_excluding_nonstandings"][
        "teams_over_standard_count"] == 0
    assert report["active_future_shadow_sensitivity"]["comparisons"] == 1
    assert report["already_recorded_predictions_left_untouched"] is True
    assert report["no_writes"] is True
    assert before == (tmp_path/"nba_games.jsonl").read_bytes()


def test_no_inferred_fix_without_exact_match(tmp_path):
    data = [g for g in _sample() if g["game_id"] != "899101"]
    result = review(data, now=NOW)
    assert result["cup_fixture_identification"] == (
        "not_identified_in_local_source")
    assert result["counterfactual_calendar_after_excluding_nonstandings"] is None
    assert result["active_future_shadow_sensitivity"]["comparisons"] == 0
    assert result["retrospective_metrics_replaced"] is False


def test_wrong_score_does_not_match_official_cup_final():
    item = {**_cup(), "home_score": 125}
    assert identify_cup_final([item])[0] == "not_identified_in_local_source"


def test_cli_and_missing_snapshot_are_readonly(tmp_path):
    assert build_parser().parse_args(
        ["cup-source-audit"]).command == "cup-source-audit"
    assert from_home(tmp_path)["status"] == "source_missing"
    assert not list(tmp_path.iterdir())
