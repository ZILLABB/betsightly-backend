"""Stage 3A: immutable-v1 comparison, audited missing identity and as-of features.

All test NBA games are synthetic and stay out of the user's private ledger.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date,timedelta,datetime,timezone

import pytest

from basketball.research_features import make_rows
from basketball.research_features_v2 import (
    FEATURE_COLUMNS, BASE_FEATURES, EXTRA_FEATURES, make_rows_v2,
)
from basketball.research_quality_v2 import audit_games
from basketball.research_public_data import read_release_csv, REQUIRED


def g(i, *, season=2026, date_override=None, status="final", home="1",
      away="2", score_home=None, score_away=None):
    day=date_override or (date(2026,1,1)+timedelta(days=i)).isoformat()
    hs=score_home if score_home is not None else 101+(i*17)%31
    vs=score_away if score_away is not None else 95+(i*11)%39
    if hs==vs:hs+=1
    return {
        "game_id":str(710000+i),"date":day,"season":season,
        "home_id":home,"away_id":away,"home_name":"A","away_name":"B",
        "home_score":hs if status=="final" else None,
        "away_score":vs if status=="final" else None,
        "status":status,"postseason":False,
        "start_utc":day+"T22:00:00+00:00",
        "source":"sportsdataverse:espn_nba_schedules:v1",
        "retrieved_at":"2026-10-24T10:00:00+00:00",
    }


def test_same_cohort_shape_and_only_prior_results():
    games=[g(i) for i in range(15)]
    future=g(999,date_override="2026-02-01",status="scheduled")
    games.append(future)
    before=make_rows(games)
    after=make_rows_v2(games)
    assert [(r["game_id"],r["status"]) for r in before]==[
        (r["game_id"],r["status"]) for r in after]
    assert len(FEATURE_COLUMNS)==len(BASE_FEATURES)+len(EXTRA_FEATURES)
    assert all(len(r["features"])==len(FEATURE_COLUMNS) for r in after)
    assert after[-1]["status"]=="scheduled"
    assert after[-1]["feature_schema"]=="nba-score-derived-pregame-v2"


def test_same_day_final_cannot_leak_into_scheduled_predictions():
    five=[g(i) for i in range(5)]
    day="2026-01-07"
    scheduled=g(15,date_override=day,status="scheduled")
    final=g(16,date_override=day,score_home=150,score_away=70)
    base=make_rows_v2(five+[scheduled])
    extended=make_rows_v2(five+[scheduled,final])
    left=next(r for r in base if r["game_id"]==scheduled["game_id"])
    right=next(r for r in extended if r["game_id"]==scheduled["game_id"])
    assert left["features"]==right["features"]


def test_cannot_import_other_season_form_into_early_fixture():
    games=[g(i,season=2025) for i in range(20)]
    future=g(900,season=2026,date_override="2026-10-25",status="scheduled")
    assert all(r["game_id"]!=future["game_id"] for r in make_rows_v2(games+[future]))


def test_fatigue_and_volatility_are_scores_derived_not_fake_possessions():
    games=[g(i) for i in range(8)]
    out=make_rows_v2(games)
    last=out[-1]
    f=dict(zip(FEATURE_COLUMNS,last["features"]))
    assert f["home_games_last4days"]==3
    assert f["away_games_last6days"]==5
    assert f["home_back_to_back_fraction_last10"]==1.0
    assert f["home_scored_std_last10"]>=0
    assert "pace" not in f and "injuries" not in f and "travel_miles" not in f


def test_enhanced_features_change_if_prior_games_change():
    games=[g(i) for i in range(10)]
    old=make_rows_v2(games)[-1]["features"]
    updated=[*games]
    updated[1]={**games[1],"home_score":games[1]["home_score"]+18}
    new=make_rows_v2(updated)[-1]["features"]
    assert old!=new


def test_real_holdout_candidate_baseline_match_and_no_live_promotion():
    pytest.importorskip("sklearn")
    from basketball.research_candidate_v2 import compare_on_real_finals
    games=[g(i,season=2025) for i in range(390)]
    result=compare_on_real_finals(games)
    assert result["status"]=="completed"
    assert result["promoted_to_live"] is False
    assert result["prospective_predictions_created"]==0
    assert result["v1_feature_count"]==14
    assert result["candidate_feature_count"]==30
    assert result["untouched_test_games"]>=20
    assert result["incumbent_moneyline"]["test"]["games"]==result[
        "candidate_moneyline"]["test"]["games"]
    assert set(result["score_targets"]["candidate"])=={
        "home_margin","total_points"}
    assert result["review_gate"]["live_model_promotion_allowed"] is False
    assert result["not_measured"]["possessions_pace"] is True


def test_quality_audit_never_invents_missing_travel_injuries_or_pace():
    games=[g(i) for i in range(7)]
    report=audit_games(games,[{
        "season":2026,"quality":{
            "rejected_regular_rows":6,
            "rejection_reasons":{"invalid_away_id":6},
            "excluded_examples":[{"game_id":"777","away_id":""}],
        },
    }])
    assert report["source_rejected_regular_rows"]==6
    assert report["seasons"]["2026"]["distinct_team_ids"]==2
    assert report["seasons"]["2026"]["final"]==7
    assert report["unavailable_inputs"]["injuries_and_lineups"]
    assert report["no_writes"] is True


def test_csv_exclusion_details_are_preserved_in_audit_not_accepted_as_picks():
    out=io.StringIO()
    cols=sorted(REQUIRED|{"game_date_time"})
    writer=csv.DictWriter(out,fieldnames=cols)
    writer.writeheader()
    for i in range(650):
        writer.writerow({
            "game_id":str(100000+i),
            "game_date":(date(2026,10,20)+timedelta(days=i//10)).isoformat(),
            "game_date_time":"2026-10-24T19:00:00Z",
            "season":"2027","season_type":"2",
            "home_id":"1","away_id":"2",
            "home_display_name":"Home","away_display_name":"Away",
            "home_score":"","away_score":"",
            "status_type_name":"STATUS_SCHEDULED",
            "status_type_completed":"FALSE",
        })
    for i in range(6):
        writer.writerow({
            "game_id":str(900000+i),
            "game_date":"2026-11-01",
            "game_date_time":"2026-11-01T20:00:00Z",
            "season":"2027","season_type":"2",
            "home_id":"1","away_id":"",
            "home_display_name":"Home","away_display_name":"",
            "status_type_name":"STATUS_PRE",
            "status_type_completed":"FALSE",
        })
    stats={}
    games=read_release_csv(out.getvalue().encode(),2027,
                           retrieved_at="2026-10-24T10:00:00+00:00",
                           audit=stats)
    assert len(games)==650
    assert stats["rejected_regular_rows"]==6
    assert stats["rejection_reasons"]=={"invalid_away_id":6}
    assert len(stats["excluded_examples"])==6
    assert all(i["away_id"]=="" for i in stats["excluded_examples"])
