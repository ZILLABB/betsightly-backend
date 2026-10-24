"""Stage 4: full-game probability, 2027 source resilience and model safety.

All fixtures and residuals are synthetic and isolated from real NBA results.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime,timezone,timedelta

import pytest

from basketball.research_markets_v4 import (
    conditional_market_probability,market_grid,market_report_from_home,
    RESEARCH_LINES,
)
from basketball.research_current_advanced_v4 import refresh_current_advanced
from basketball.research_injury_identity_v4 import injury_crosswalk
from basketball.research_stage4_operations import stage4_report
from basketball.research_data import write_games

NOW=datetime(2026,10,24,17,tzinfo=timezone.utc)


def _residuals():
    return [
        {"total_points":(-18.5 if i%3==0 else 7.5 if i%3==1 else 21.5),
         "home_margin":(-11.5 if i%2 else 5.5)}
        for i in range(120)
    ]


def _game(ident="50012",status="final",date="2026-10-23"):
    return {
        "game_id":ident,"season":2027,"date":date,"status":status,
        "home_id":"1","away_id":"2","home_name":"Atlanta Hawks",
        "away_name":"Boston Celtics",
        "start_utc":date+"T22:00:00+00:00",
        "home_score":112 if status=="final" else None,
        "away_score":106 if status=="final" else None,
        "postseason":False,
        "source":"sportsdataverse:espn_nba_schedules:v1",
        "retrieved_at":NOW.isoformat(),
    }


def test_market_four_families_with_distinct_samples_and_correct_push():
    residuals=[{"total_points":0.0,"home_margin":0.0}]*110
    p=conditional_market_probability(
        target="total_points",line=225.5,expected_total=225.5,
        expected_margin=5,residuals=residuals)
    assert p["push_probability"]==1.0
    assert p["above_probability"]==0
    p=conditional_market_probability(
        target="home_margin",line=4.5,expected_total=225,
        expected_margin=5,residuals=residuals)
    assert p["above_probability"]==1.0
    grid=market_grid(expected_total=224,expected_margin=4,
                     residuals=_residuals())
    assert grid["status"]=="research_only"
    assert set(grid["markets"])==set(RESEARCH_LINES)
    assert grid["markets_blocked"]["first_half_total_points"]
    assert grid["no_bookmaker_odds"] is True
    assert grid["public_publishing_enabled"] is False
    for entries in grid["markets"].values():
        for item in entries:
            assert abs(sum(item[k] for k in (
                "above_probability","below_probability","push_probability"))-1)<1e-5


def test_empirical_paired_residuals_cannot_claim_unavailable_market_or_odds():
    with pytest.raises(ValueError,match="Unsupported"):
        conditional_market_probability(target="first_half",
             line=100,expected_total=220,expected_margin=0,
             residuals=_residuals())
    assert market_grid(expected_total=220,expected_margin=0,
                       residuals=None)["status"]=="blocked"
    with pytest.raises(ValueError,match="100 paired"):
        market_grid(expected_total=220,expected_margin=0,
                    residuals=_residuals()[:10])
    with pytest.raises(ValueError,match="Out-of-bounds"):
        bad=[*(_residuals()[:119]),{"total_points":900,"home_margin":0}]
        market_grid(expected_total=220,expected_margin=0,residuals=bad)


def test_team_over_and_home_margin_joint_arithmetic():
    errors=[{"total_points":0,"home_margin":0}]*100
    team=conditional_market_probability(
        target="home_team_points",line=111.5,
        expected_total=225,expected_margin=0,residuals=errors)
    away=conditional_market_probability(
        target="away_team_points",line=113.5,
        expected_total=225,expected_margin=0,residuals=errors)
    assert team["above_probability"]==1
    assert away["above_probability"]==0


def test_current_2027_each_source_independently_accepted_or_blocked(tmp_path):
    calls=[]
    def fake(*,home,seasons,kinds):
        kind=kinds[0]
        calls.append(kind)
        if kind=="player":raise RuntimeError("No current season release")
        return {"source_coverage":[{
            "season":2027,"kind":"team","fixture_coverage":1.0,
            "accepted_rows":30,"provenance_checked_at":NOW.isoformat()
        }]}
    report=refresh_current_advanced(tmp_path,season=2027,
                                    now=NOW,fetcher=fake)
    assert calls==["team","player"]
    assert report["status"]=="partial"
    assert report["assets"]["team"]["status"]=="verified"
    assert report["assets"]["player"]["status"]=="unavailable"
    assert report["model_retrained"] is False


def test_current_2027_no_release_is_not_fabricated(tmp_path):
    def down(**kw):raise RuntimeError("Release not found")
    result=refresh_current_advanced(tmp_path,season=2027,
                                    now=NOW,fetcher=down)
    assert result["status"]=="blocked"
    assert result["old_season_substitution"] is False
    assert result["successful_assets"]==0


def test_exact_official_injury_player_identity_diagnostic_never_trains(tmp_path):
    write_games([_game()],tmp_path/"nba_games.jsonl")
    assets=tmp_path/"advanced"
    assets.mkdir()
    (assets/"player_2027.json").write_text(json.dumps([
        {"team_id":"1","athlete_id":"42","name":"John Doe","game_id":"50012"},
        {"team_id":"1","athlete_id":"51","name":"Other Player","game_id":"50012"},
    ]))
    archive=tmp_path/"injuries"
    archive.mkdir()
    (archive/"sample.json").write_text(json.dumps({
        "source":"nba:official_injury_report_pdf:v1",
        "published_at":"2026-10-24T16:00:00+00:00",
        "downloaded_at":"2026-10-24T16:05:00+00:00",
        "parsed_player_rows":[
            {"team":"Atlanta Hawks","player":"Doe, John","status":"Questionable"},
            {"team":"Atlanta Hawks","player":"Unknown, Person","status":"Out"},
        ],
    }))
    result=injury_crosswalk(tmp_path,as_of=NOW)
    assert result["matched_unique_player_rows"]==1
    assert result["unresolved_injury_rows"]==1
    assert result["eligible_for_model_features"] is False
    assert result["report_completeness_verified"] is False
    old=injury_crosswalk(tmp_path,as_of=NOW+timedelta(hours=13))
    assert old["reason"]=="injury_snapshot_stale"
    too_early=injury_crosswalk(tmp_path,as_of=NOW-timedelta(hours=2))
    assert too_early["reason"]=="no_snapshot_actually_collected_by_cutoff"


def test_stage4_report_missing_source_does_not_imply_launch_ready(tmp_path):
    write_games([_game()],tmp_path/"nba_games.jsonl")
    result=stage4_report(tmp_path,now=NOW)
    assert result["deployable_to_public"] is False
    assert result["market_support"]["first_half"] is False
    assert result["market_support"]["full_game_total"] is False
    assert result["current_2027_missing_assets"]==["team","player"]
    assert result["injury_player_identity"]["eligible_for_model_features"] is False
    assert result["probability_markets"]["forecast_count"]==0
    assert result["no_writes"] is True


def test_market_forward_evaluation_only_settled_immutable_forecasts(tmp_path):
    root=tmp_path/"advanced"
    root.mkdir()
    probabilities=market_grid(expected_total=219,
        expected_margin=3,residuals=_residuals())
    item={
        "game_id":"90099","created_at":"2026-10-24T10:00:00+00:00",
        "start_utc":"2026-10-25T10:00:00+00:00",
        "market_probabilities":probabilities,"research_only":True,
    }
    encoded=json.dumps(item,sort_keys=True,separators=(",",":"))
    item["sha256"]=hashlib.sha256(encoded.encode()).hexdigest()
    (root/"shadow_2027.jsonl").write_text(
        json.dumps(item,sort_keys=True,separators=(",",":"))+"\n")
    (root/"shadow_settlements_2027.json").write_text(json.dumps({
        "90099":{"scores":[111,109],"source":"verified_fixture"}
    }))
    result=market_report_from_home(tmp_path)
    assert result["forecast_count"]==1
    assert result["verified_final_count"]==1
    assert result["bookmaker_roi"] is None
    assert result["first_half_market_enabled"] is False
    assert all(m["review_ready"] is False for m in result["market_metrics"])
    item["market_probabilities"]["markets"]["total_points"][0][
        "above_probability"]=0.999
    (root/"shadow_2027.jsonl").write_text(json.dumps(item)+"\n")
    with pytest.raises(ValueError,match="integrity mismatch"):
        market_report_from_home(tmp_path)
