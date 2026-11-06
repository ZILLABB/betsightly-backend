"""Synthetic, offline-only coverage for prospective NBA Wave 2 diagnostics."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta

from basketball.research_store import open_ledger
from basketball.research_wave2_diagnostics import (
    paired_uncertainty, bias_and_segments, archived_original_v1_comparison,
    evidence_progress,
)
from basketball.research_wave2_report import wave2_report

UTC = timezone.utc
NOW = datetime(2026, 11, 6, 14, tzinfo=UTC)


def _row(i=1, day="2026-11-01", *, candidate=.8, v1=.6):
    return {
        "game_id": str(i), "fixture_date": day,
        "start_utc": day+"T23:00:00+00:00",
        "candidate_home_win_probability": candidate,
        "matched_v1_home_win_probability": v1,
        "candidate_total_points": 215.0,
        "matched_v1_total_points": 225.0,
        "candidate_home_margin": 9.0,
        "matched_v1_home_margin": 5.0,
        "home_id": "1", "away_id": "2",
    }


def _scored():
    return [
        (_row(100+i, day=f"2026-11-{i//10+1:02d}"), 110, 100)
        for i in range(40)
    ]


def test_cluster_bootstrap_reproducible_positive_deltas_and_date_grouping():
    scored = _scored()
    first = paired_uncertainty(scored)
    second = paired_uncertainty(scored)
    assert first == second
    assert first["distinct_game_dates"] == 4
    assert first["draws"] == 2000
    assert first["interval_status"] == "exploratory"
    for name in ("moneyline_brier", "moneyline_log_loss",
                 "total_points_mae", "home_margin_mae"):
        result = first["comparisons"][name]
        assert result["paired_games"] == 40
        assert result["candidate_improvement"] > 0
        assert result["ci95_lower"] > 0
        assert result["ci95_upper"] > 0
    assert first["comparisons"]["moneyline_accuracy"]["candidate_improvement"] == 0
    assert first["not_an_edge_or_significance_test"] is True


def test_small_sample_no_false_interval():
    report = paired_uncertainty([(_row(), 110, 100)])
    assert report["interval_status"] == "insufficient_date_clusters_or_games"
    assert report["comparisons"]["moneyline_brier"]["ci95_lower"] is None
    assert report["draws"] == 0
    assert paired_uncertainty([])["comparisons"]["home_margin_mae"]["paired_games"] == 0


def test_score_bias_segments_do_not_claim_causal_features():
    report = bias_and_segments(_scored())
    assert report["model_bias"]["candidate"]["total_points"]["bias"] == 5
    assert report["model_bias"]["matched_v1"]["total_points"]["bias"] == 15
    assert report["model_bias"]["candidate"]["home_margin"]["mae"] == 1
    assert report["segments"]["forecast_favorite"]["home"]["games"] == 40
    assert report["segments"]["actual_total_band_postgame"]["below_230"]["games"] == 40
    assert report["postgame_segments_not_available_as_pregame_filters"] is True
    assert report["no_feature_causality_inferred"] is True
    assert report["candidate_error_examples"]


def test_review_checkpoint_does_not_promote_candidate():
    r = evidence_progress(45, 64, 19)
    assert r["additional_verified_settlements_for_checkpoint"] == 55
    assert not r["checkpoint_met"]
    assert r["no_publishing_or_model_promotion"] is True
    assert evidence_progress(100, 120, 20)["checkpoint_met"] is True
    assert evidence_progress(100, 120, 20)["threshold_is_not_evidence_of_model_edge"] is True


def _save_valid_synthetic_archive(root, *, model_version="nba-moneyline-offline-v1"):
    day = "2026-11-01"
    start = day+"T23:00:00+00:00"
    created = day+"T12:00:00+00:00"
    verified = "2026-11-02T02:00:00+00:00"
    row = {
        **_row(101, day),
        "season": 2027, "created_at": created,
        "model_version": "nba-advanced-shadow-2026-v1",
        "bookmaker_odds_verified": False,
        "not_for_betting": True, "research_only": True,
    }
    canon = json.dumps(row, sort_keys=True, separators=(",", ":"))
    row["sha256"] = hashlib.sha256(canon.encode()).hexdigest()
    advanced = root / "advanced"
    advanced.mkdir()
    (advanced/"shadow_2027.jsonl").write_text(
        json.dumps(row)+"\n", encoding="utf-8")
    (advanced/"shadow_settlements_2027.json").write_text(
        json.dumps({"101":{"scores":[110,100],
                           "source":"sportsdataverse:espn_nba_schedules:v1",
                           "verified_at":verified}}), encoding="utf-8")
    game = {
        "game_id":"101", "season":2027, "status":"final",
        "date":day, "start_utc":start, "home_id":"1", "away_id":"2",
        "home_score":110, "away_score":100, "postseason":False,
        "source":"sportsdataverse:espn_nba_schedules:v1",
    }
    (root/"nba_games.jsonl").write_text(
        json.dumps(game)+"\n", encoding="utf-8")
    forecast = {
        "game_id":"101", "date":day,
        "model_version":model_version,
        "home_team":"Synthetic Home", "away_team":"Synthetic Away",
        "home_team_id":"1", "away_team_id":"2",
        "start_utc":start, "generated_at":created,
        "home_win_probability":.7, "away_win_probability":.3,
        "expected_total_points":211.0, "expected_home_margin":8.0,
        "research_only":True, "not_for_betting":True,
        "bookmaker_odds_verified":False, "booking_code":None,
    }
    serialized = json.dumps(
        forecast, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    with open_ledger(root/"nba_paper.sqlite") as db:
        db.execute(
            """INSERT INTO forecasts(
                game_id, fixture_date, start_utc, created_at, home_team,
                away_team, home_team_id, away_team_id, model_version,
                home_win_probability, expected_total_points, expected_home_margin,
                raw_json, sha256, inserted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("101",day,start,created,"Synthetic Home","Synthetic Away",
             "1","2",model_version,.7,211.0,8.0,serialized,digest,
             "2026-11-01T12:01:00+00:00")
        )
        db.execute(
            """INSERT INTO settlements(game_id,home_score,away_score,
                home_won,recorded_at,source) VALUES(?,?,?,?,?,?)""",
            ("101",110,100,1,verified,
             "sportsdataverse:espn_nba_schedules:v1")
        )
        db.commit()


def test_integrated_report_matches_original_saved_v1_without_writes(tmp_path):
    _save_valid_synthetic_archive(tmp_path)
    ledger = tmp_path/"advanced"/"shadow_2027.jsonl"
    db = tmp_path/"nba_paper.sqlite"
    ledger_before = ledger.read_bytes()
    from pathlib import Path
    hash_before = hashlib.sha256(db.read_bytes()).hexdigest()
    result = wave2_report(tmp_path, now=NOW)
    assert result["status"] == "descriptive_only"
    assert result["settled_count"] == 1
    assert result["paired_uncertainty"]["comparisons"]["moneyline_brier"]["paired_games"] == 1
    main = result["original_main_v1_comparison"]
    assert main["status"] == "descriptive_only"
    assert main["matched_games"] == 1
    assert main["moneyline"]["original_main_v1_archive"]["brier"] == .09
    assert main["moneyline"]["advanced_candidate"]["brier"] == .04
    assert main["moneyline"]["matched_reduced_feature_v1"]["brier"] == .16
    assert main["score_projections"]["total_points"]["original_main_v1_archive"]["mae"] == 1
    assert result["forward_evidence_progress"]["additional_verified_settlements_for_checkpoint"] == 99
    assert result["no_writes"] is True
    assert ledger.read_bytes() == ledger_before
    assert hashlib.sha256(db.read_bytes()).hexdigest() == hash_before


def test_different_original_version_is_not_misidentified_as_v1(tmp_path):
    _save_valid_synthetic_archive(tmp_path, model_version="experimental-v2")
    report = wave2_report(tmp_path, now=NOW)
    assert report["status"] == "descriptive_only"
    assert report["original_main_v1_comparison"]["status"] == "no_exact_settled_v1_pairs"


def test_original_v1_final_disagreement_blocks_baseline_not_shadow(tmp_path):
    _save_valid_synthetic_archive(tmp_path)
    with open_ledger(tmp_path/"nba_paper.sqlite") as db:
        db.execute(
            "UPDATE settlements SET home_score=112 WHERE game_id='101'")
        db.commit()
    report = wave2_report(tmp_path, now=NOW)
    assert report["status"] == "descriptive_only"
    assert (report["original_main_v1_comparison"]["status"] ==
            "exact_game_identity_or_score_conflict")
    assert report["original_main_v1_comparison"]["metrics_withheld"] is True


def test_original_v1_tamper_blocks_baseline_not_shadow(tmp_path):
    _save_valid_synthetic_archive(tmp_path)
    with open_ledger(tmp_path/"nba_paper.sqlite") as db:
        db.execute("UPDATE forecasts SET sha256='wrong' WHERE game_id='101'")
        db.commit()
    report = wave2_report(tmp_path, now=NOW)
    assert report["status"] == "descriptive_only"
    assert report["original_main_v1_comparison"]["status"] == "main_v1_integrity_failed"
    assert "moneyline" not in report["original_main_v1_comparison"]
