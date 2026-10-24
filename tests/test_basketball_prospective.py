"""Prospective evaluation: real immutable ledger only, never historical backtest."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from basketball.research_prospective import prospective_report
from basketball.research_dashboard import render_dashboard
from basketball.research_store import open_ledger

CREATE_TIME = datetime(2026, 10, 24, 17, tzinfo=timezone.utc)
TIPOFF = CREATE_TIME + timedelta(hours=7)
FINAL_TIME = TIPOFF + timedelta(hours=3)


def insert(db, index: int, prob: float = .6, *, settled=True,
           version="nba-moneyline-offline-v1", score_projection=True):
    ident = f"4018{index:06d}"
    day = "2026-10-25"
    raw = json.dumps({"game_id": ident, "probability": prob},
                     sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    db.execute("""
        INSERT INTO forecasts(
            game_id,fixture_date,start_utc,created_at,home_team,away_team,
            home_team_id,away_team_id,model_version,home_win_probability,
            expected_total_points,expected_home_margin,raw_json,sha256,inserted_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ident, day, TIPOFF.isoformat(), CREATE_TIME.isoformat(),
        f"Home {index}", f"Away {index}", "1", "2", version, prob,
        215. if score_projection else None,
        6. if score_projection else None, raw, digest,
        (CREATE_TIME+timedelta(minutes=1)).isoformat(),
    ))
    if settled:
        # Half win/half loss by construction; no mock market odds anywhere.
        home, away = (112, 107) if index % 2 else (105, 112)
        db.execute("""
            INSERT INTO settlements(game_id,home_score,away_score,home_won,
                                    recorded_at,source) VALUES(?,?,?,?,?,?)
        """, (
            ident, home, away, int(home > away),
            FINAL_TIME.isoformat(), "espn:nba:scoreboard:v1",
        ))
    db.commit()
    return ident


def test_empty_missing_ledger_does_not_create_sqlite(tmp_path):
    target = tmp_path / "nba_paper.sqlite"
    report = prospective_report(target)
    assert report["status"] == "awaiting_first_forecast"
    assert report["forecast_count"] == 0
    assert report["no_writes"] is True
    assert not target.exists()


def test_settled_and_pending_are_separate_and_no_roi_is_claimed(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    with open_ledger(path) as db:
        insert(db, 1, prob=.8)
        insert(db, 2, prob=.4, settled=False)
    before = path.read_bytes()
    report = prospective_report(path)
    assert report["status"] == "descriptive_only"
    assert report["forecast_count"] == 2
    assert report["settled_count"] == 1
    assert report["pending_count"] == 1
    assert report["overall"]["correct"] == 1
    assert report["overall"]["brier"] == .04
    assert report["overall"]["baseline_brier"] == .25
    assert report["overall"]["brier_skill_vs_50_50"] == .84
    assert report["sample_size_gate_met"] is False
    assert report["calibration"]["ece"] is None
    assert report["score_projection_errors"]["count"] == 1
    assert report["pending_fixtures"][0]["game_id"] == "4018000002"
    assert report["bookmaker_odds_verified"] is False
    assert report["betting_roi"] is None
    assert before == path.read_bytes()


def test_all_pending_is_not_mistaken_for_zero_performance(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    with open_ledger(path) as db:
        insert(db, 1, settled=False)
    report = prospective_report(path)
    assert report["status"] == "awaiting_verified_final"
    assert report["overall"]["brier"] is None
    assert report["settled_count"] == 0
    assert report["forecast_count"] == 1


def test_100_real_ledger_rows_unlock_descriptive_review_and_fixed_bins(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    with open_ledger(path) as db:
        for i in range(1, 101):
            insert(db, i, prob=(.1,.3,.5,.7,.9)[(i-1) % 5])
    report = prospective_report(path)
    assert report["status"] == "review_ready"
    assert report["sample_size_gate_met"] is True
    assert report["overall"]["count"] == 100
    assert report["calibration"]["ece"] is not None
    assert sum(row["count"] for row in report["calibration"]["bins"]) == 100
    assert len(report["by_model_version"]) == 1
    assert report["rolling_settled"]["last_30"]["count"] == 30
    assert report["rolling_settled"]["last_100"]["count"] == 100
    assert report["overall"]["accuracy_95pct_ci"]["lower"] < .5
    assert report["overall"]["accuracy_95pct_ci"]["upper"] > .5
    assert report["integrity"]["sha256_records_verified"] == 100


def test_model_versions_and_missing_score_projections_are_separate(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    with open_ledger(path) as db:
        insert(db, 1, version="v1")
        insert(db, 2, version="v2", score_projection=False)
    report = prospective_report(path)
    assert set(report["by_model_version"]) == {"v1", "v2"}
    assert report["score_projection_errors"]["count"] == 1
    assert report["by_model_version"]["v1"]["count"] == 1


def test_changed_predictions_in_sqlite_withhold_all_model_statistics(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    with open_ledger(path) as db:
        ident = insert(db, 1)
        db.execute("UPDATE forecasts SET raw_json=? WHERE game_id=?",
                   ('{"fabricated":true}', ident))
        db.commit()
    report = prospective_report(path)
    assert report["status"] == "integrity_failed"
    assert report["metrics_withheld"] is True
    assert report["issue_count"] == 1
    assert "brier" not in report


def test_post_tipoff_insertion_and_bad_settlement_block_prospective_report(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    with open_ledger(path) as db:
        ident = insert(db, 1)
        db.execute("UPDATE forecasts SET inserted_at=? WHERE game_id=?",
                   ((TIPOFF+timedelta(seconds=2)).isoformat(), ident))
        db.commit()
    bad = prospective_report(path)
    assert bad["status"] == "integrity_failed"
    assert "after tipoff" in bad["issues"][0]


def test_dashboard_shows_sample_warning_and_escapes_prospective_data(tmp_path):
    path = tmp_path / "nba_paper.sqlite"
    with open_ledger(path) as db:
        insert(db, 1)
    result = prospective_report(path)
    html = render_dashboard(
        {"forecast_count": 1, "settled": 1, "pending": 0},
        [], [], prospective=result
    )
    assert "Prospective research evaluation" in html
    assert "Early results are unstable" in html
    assert "0.2500" in html
    assert "No verified bookmaker odds or betting ROI" in html
