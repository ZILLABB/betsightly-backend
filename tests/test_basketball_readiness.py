"""Readiness monitoring tests. Synthetic fixtures are test inputs only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from basketball.research_data import write_games
from basketball.research_dashboard import render_dashboard
from basketball.research_readiness import (
    build_readiness, readiness_from_home,
)

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
SOURCE = "sportsdataverse:espn_nba_schedules:v1"


def game(number, day, home="1", away="2", *,
         status="final", start=None, retrieved=None):
    return {
        "game_id": str(number), "date": day, "season": 2027,
        "status": status, "home_id": home, "away_id": away,
        "home_name": f"<b>Home {home}</b>", "away_name": f"Away {away}",
        "home_score": 108 if status == "final" else None,
        "away_score": 102 if status == "final" else None,
        "start_utc": start if start is not None else day + "T20:00:00Z",
        "postseason": False, "source": SOURCE,
        "retrieved_at": (retrieved or NOW.isoformat()),
    }


def sample():
    # Five earlier-day completed games give teams 1 and 2 sufficient form.
    history = [
        game(i + 1, f"2026-10-{19+i:02d}") for i in range(5)
    ]
    history += [
        game(i + 11, f"2026-10-{20+i:02d}", home="3", away="4")
        for i in range(4)
    ]
    history += [
        game(100, "2026-10-25", status="scheduled"),
        game(101, "2026-10-25", home="1", away="3",
             status="scheduled"),
    ]
    return history


def find(report, ident):
    return next(row for row in report["fixtures"] if row["game_id"] == str(ident))


def test_counts_same_season_history_and_explains_each_warmup_gate():
    report = build_readiness(sample(), now=NOW, model_cutoff="2026-10-23")
    assert report["snapshot"]["status"] == "fresh"
    assert report["scheduled_fixtures"] == 2
    assert report["eligible_forecasts"] == 1
    assert report["feature_ready"] == 1
    ready = find(report, 100)
    assert ready["home_prior_games"] == 5
    assert ready["away_prior_games"] == 5
    assert ready["eligible"]
    blocked = find(report, 101)
    assert blocked["home_prior_games"] == 5
    assert blocked["away_prior_games"] == 4
    assert blocked["away_games_remaining"] == 1
    assert blocked["reasons"] == ["away_warmup"]
    assert report["blockers"]["away_warmup"] == 1


def test_same_date_final_cannot_make_another_game_eligible():
    data = sample()
    # Team 3 has four completed games. This final on the fixture date
    # MUST NOT become the fifth game used by that day's scheduled fixture.
    data.append(game(102, "2026-10-25", home="3", away="4",
                     status="final"))
    report = build_readiness(data, now=NOW, model_cutoff="2026-10-23")
    blocked = find(report, 101)
    assert blocked["away_prior_games"] == 4
    assert not blocked["eligible"]


def test_stale_snapshot_blocks_operational_readiness_but_not_team_history():
    outdated = (NOW - timedelta(days=3)).isoformat()
    data = [{**row, "retrieved_at": outdated} for row in sample()]
    report = build_readiness(data, now=NOW, model_cutoff="2026-10-23")
    assert report["snapshot"]["status"] == "stale"
    assert report["feature_ready"] == 1
    assert report["eligible_forecasts"] == 0
    assert "source_stale" in find(report, 100)["reasons"]


def test_missing_and_invalid_kickoff_never_look_ready():
    data = sample()
    for row in data:
        if row["game_id"] == "100":
            row["start_utc"] = None
    report = build_readiness(data, now=NOW, model_cutoff="2026-10-23")
    assert "missing_tipoff" in find(report, 100)["reasons"]
    assert not find(report, 100)["eligible"]


def test_model_artifact_and_training_cutoff_are_explicit_gates():
    report = build_readiness(sample(), now=NOW, model_exists=False)
    assert "model_missing" in find(report, 100)["reasons"]
    report = build_readiness(sample(), now=NOW, model_cutoff=None)
    assert "model_metadata_missing" in find(report, 100)["reasons"]
    report = build_readiness(sample(), now=NOW, model_cutoff="2026-10-25")
    assert "model_cutoff" in find(report, 100)["reasons"]


def test_prior_same_season_games_and_source_clock_skew():
    data = sample()
    data += [game(i + 1000, "2026-10-18") | {"season": 2026}
             for i in range(6)]
    report = build_readiness(data, now=NOW, model_cutoff="2026-10-23")
    assert find(report, 100)["home_prior_games"] == 5
    forward = (NOW + timedelta(minutes=30)).isoformat()
    data = [{**row, "retrieved_at": forward} for row in data]
    report = build_readiness(data, now=NOW, model_cutoff="2026-10-23")
    assert report["snapshot"]["status"] == "clock_skew"
    assert "source_clock_skew" in find(report, 100)["reasons"]


def test_home_readiness_uses_files_without_loading_pickle_or_writing(tmp_path):
    assert readiness_from_home(tmp_path, now=NOW)["snapshot"]["status"] == "missing"
    assert list(tmp_path.iterdir()) == []
    write_games(sample(), tmp_path / "nba_games.jsonl")
    (tmp_path / "nba_moneyline.joblib").write_bytes(b"untrusted bytes - no unpickle")
    metrics = {"prospective_refit": {"through": "2026-10-23"}}
    (tmp_path / "training_metrics.json").write_text(json.dumps(metrics))
    report = readiness_from_home(tmp_path, now=NOW)
    assert report["scheduled_fixtures"] == 2
    assert report["eligible_forecasts"] == 1
    assert report["model"]["training_cutoff"] == "2026-10-23"
    assert not (tmp_path / "nba_paper.sqlite").exists()
    (tmp_path / "nba_games.jsonl").write_text("not-json\n")
    assert readiness_from_home(tmp_path, now=NOW)["snapshot"]["status"] == "invalid"


def test_readiness_html_escapes_fixture_names_and_is_non_bookable():
    readiness = build_readiness(sample(), now=NOW,
                                model_cutoff="2026-10-23")
    page = render_dashboard(
        {"forecast_count": 0, "settled": 0, "pending": 0},
        [], [], readiness
    )
    assert "Upcoming NBA readiness" in page
    assert "<b>Home 1</b>" not in page
    assert "&lt;b&gt;Home 1&lt;/b&gt;" in page
    assert "Away team has fewer than five" in page
    assert "PRIVATE · OFFLINE · NO BETTING" in page
    assert readiness["public_publishing_enabled"] is False


@pytest.mark.parametrize("days", [0, 15])
def test_horizon_rejects_outside_bounds(days):
    with pytest.raises(ValueError, match="horizon"):
        build_readiness(sample(), now=NOW, days_ahead=days)
