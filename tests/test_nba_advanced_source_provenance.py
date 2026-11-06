"""Regression coverage for NBA advanced settlement source provenance."""
from datetime import datetime, timezone

import pytest

from basketball import research_early_advanced_ops as advanced
from basketball.research_coldstart import _json, _signed
from basketball.research_data import write_games


def save_signed(path, rows):
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(_json({**row, "sha256": _signed(row)}) + "\n")


@pytest.mark.parametrize(
    "settlement_source,home_score,should_pass",
    [
        ("espn:nba:scoreboard:v1", 112, True),
        ("sportsdataverse:espn_nba_schedules:v1", 112, True),
        ("espn:nba:scoreboard:v1", 111, False),
        ("nba:official_live_cdn:scoreboard:v1", 112, False),
    ],
)
def test_advanced_settlement_source_provenance(
    tmp_path, settlement_source, home_score, should_pass
):
    home = tmp_path / "research"
    home.mkdir()

    start = "2026-10-26T01:00:00+00:00"
    identity = {
        "game_id": "9900001",
        "date": "2026-10-26",
        "season": 2027,
        "home_id": "1",
        "away_id": "2",
    }

    game = {
        **identity,
        "status": "final",
        "home_name": "Synthetic Home",
        "away_name": "Synthetic Away",
        "home_score": 112,
        "away_score": 123,
        "start_utc": start,
        "postseason": False,
        "source": "sportsdataverse:espn_nba_schedules:v1",
        "retrieved_at": "2026-11-06T10:00:00+00:00",
    }
    write_games([game], home / "nba_games.jsonl")

    original_predictions = {
        "predicted_total": 236.0,
        "predicted_home_margin": -10.0,
        "predicted_home_points": 113.0,
        "predicted_away_points": 123.0,
    }

    reference = {
        **identity,
        "start_utc": start,
        "captured_at": "2026-10-25T23:00:00+00:00",
        **original_predictions,
    }

    forecast = {
        **identity,
        "start_utc": start,
        "captured_at": "2026-10-25T23:30:00+00:00",
        "model_version": advanced.VERSION,
        "reference_model": advanced.REFERENCE_VERSION,
        "source": "sportsdataverse:espn_nba_schedules:v1",
        "research_only": True,
        "not_bookable": True,
        "bookmaker_prices_verified": False,
        "estimated_possessions": 98.0,
        "predicted_total": 240.0,
        "predicted_home_margin": -10.0,
        "predicted_home_points": 115.0,
        "predicted_away_points": 125.0,
        **{
            "original_" + key: value
            for key, value in original_predictions.items()
        },
    }

    settlement = {
        "game_id": identity["game_id"],
        "home_score": home_score,
        "away_score": 123,
        "source": settlement_source,
        "settled_at": "2026-10-26T07:04:19+00:00",
        "research_only": True,
    }

    save_signed(home / advanced.REFERENCE, [reference])
    save_signed(home / advanced.FORECASTS, [forecast])
    save_signed(home / advanced.FINALS, [settlement])

    result = advanced.audit(
        home, now=datetime(2026, 11, 6, tzinfo=timezone.utc)
    )

    if should_pass:
        assert result["status"] == "forward_observations"
        assert result["settled"] == 1
    else:
        assert result["status"] == "integrity_failed"
        assert "invalid_verified_advanced_settlement" in result["integrity_errors"]
