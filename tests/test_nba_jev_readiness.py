"""NBA Jev readiness must never modify the immutable private archive."""
import json
from datetime import datetime, timedelta, timezone

from basketball.research_store import open_ledger
from basketball.research_jev_readiness import jev_research_readiness


NOW = datetime(2026, 10, 28, 14, tzinfo=timezone.utc)


def test_missing_private_ledger_fails_closed(tmp_path):
    report = jev_research_readiness(
        tmp_path / "missing.sqlite", home=tmp_path, at=NOW)
    assert report["status"] == "ledger_missing"
    assert report["jev_calls_made"] == 0
    assert report["public_betting_enabled"] is False


def test_empty_archive_does_not_manufacture_forecasts(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    con = open_ledger(path)
    con.close()
    report = jev_research_readiness(path, home=tmp_path, at=NOW)
    assert report["status"] == "research_readiness_only"
    assert report["total_archived_forecasts"] == 0
    assert report["eligible_current_pretipoff_forecasts"] == 0
    assert report["injury_evidence_automatically_sent_to_jev"] is False


def test_original_pretipoff_row_counts_without_exposing_private_model_inputs(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    start = NOW + timedelta(hours=3)
    created = NOW - timedelta(minutes=10)
    payload = {"game_id": "nba-123", "research_only": True,
               "not_for_betting": True, "bookmaker_odds_verified": False,
               "booking_code": None, "model_version": "paper_v1"}
    with open_ledger(path) as con:
        con.execute(
            """INSERT INTO forecasts
                (game_id, fixture_date, start_utc, created_at,
                 home_team, away_team, home_team_id, away_team_id,
                 model_version, home_win_probability, raw_json,
                 sha256, inserted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("nba-123", "2026-10-28", start.isoformat(), created.isoformat(),
             "Home", "Away", "101", "202", "paper_v1", .63,
             json.dumps(payload), "f" * 64, created.isoformat()))
    result = jev_research_readiness(path, home=tmp_path, at=NOW)
    assert result["total_archived_forecasts"] == 1
    assert result["eligible_current_pretipoff_forecasts"] == 1
    assert result["eligible_game_stubs"][0]["game_id"] == "nba-123"
    assert "model_probability" not in result["eligible_game_stubs"][0]
    assert result["shadow_evidence_eligible"] is False
    with open_ledger(path) as con:
        assert con.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 1


def test_invalid_betting_enabled_forecast_is_ignored(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    start = NOW + timedelta(hours=4)
    with open_ledger(path) as con:
        con.execute(
            """INSERT INTO forecasts
                (game_id, fixture_date, start_utc, created_at,
                 home_team, away_team, home_team_id, away_team_id,
                 model_version, home_win_probability, raw_json,
                 sha256, inserted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("nba-124", "2026-10-28", start.isoformat(), NOW.isoformat(),
             "Home", "Away", "101", "202", "paper_v1", .63,
             json.dumps({"game_id": "nba-124", "booking_code": "INVALID"}),
             "a" * 64, NOW.isoformat()))
    result = jev_research_readiness(path, home=tmp_path, at=NOW)
    assert result["eligible_current_pretipoff_forecasts"] == 0
    assert result["ineligible_archive_rows"] == 1
