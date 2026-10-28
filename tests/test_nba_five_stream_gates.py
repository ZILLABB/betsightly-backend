"""Five-stream contract: forward metrics, market grade, leagues, V2 recovery."""
from datetime import datetime, timezone
import copy
import pytest

from basketball import research_forward_scorecard as s
from basketball import research_market_settlement_contract as m
from basketball import research_multileague_release_gates as l
from basketball import research_full_recovery_ack as b


def demo_archive():
    fixture = {"game_id":"42","status":"final","start_utc":"2026-10-27T20:00:00+00:00",
               "home_score":107,"away_score":99}
    common = {"game_id":"42","captured_at":"2026-10-27T18:00:00+00:00"}
    return {"fixtures":[fixture], "records":{
        "moneyline":[{**common,"probability_home_win":0.75}],
        "opening_score":[{**common,"predicted_home_points":105.0,
                           "predicted_away_points":98.0}],
        "moneyline_finals":[{"game_id":"42","home_score":107,"away_score":99}],
        "opening_score_finals":[{"game_id":"42","home_score":107,"away_score":99}],
    }}


def test_forward_scorecard_prospectively_grades_originals(monkeypatch):
    monkeypatch.setattr(s,"inspect_bundle",lambda bundle: {})
    archive=demo_archive()
    report=s.scorecard(archive)
    assert report["models"]["moneyline"]["verified_forward_games"]==1
    assert report["models"]["moneyline"]["brier"]==0.0625
    assert report["models"]["moneyline"]["accuracy"]==1
    assert report["models"]["opening_score"]["home_mae"]==2.0
    assert report["models"]["opening_score"]["total_mae"]==3.0
    assert report["eligible_for_public_prediction"] is False
    assert report["betting_roi"] is None
    late=copy.deepcopy(archive)
    late["records"]["moneyline"][0]["captured_at"]="2026-10-27T20:01:00+00:00"
    with pytest.raises(ValueError,match="LEAKAGE"):
        s.scorecard(late)
    mismatch=copy.deepcopy(archive)
    mismatch["records"]["opening_score_finals"][0]["home_score"]=108
    with pytest.raises(ValueError,match="MISMATCH"):
        s.scorecard(mismatch)


def test_full_game_market_push_over_and_spread_with_exact_event():
    game={"event_id":"evt1","home_id":"h","away_id":"a",
          "home_score":110,"away_score":105,"status":"final"}
    base={"event_id":"evt1","home_id":"h","away_id":"a",
          "league":"nba","overtime_included":True}
    score=m.grade_full_game({**base,"kind":"full_game_total",
                             "side":"over","line":215.0},game)
    assert score["outcome"]=="push" and score["not_bookable"]
    score=m.grade_full_game({**base,"kind":"full_game_home_spread",
                             "side":"home","line":-4.5},game)
    assert score["outcome"]=="won"
    score=m.grade_full_game({**base,"kind":"full_game_away_team_total",
                             "side":"under","line":104.5},game)
    assert score["outcome"]=="lost"


@pytest.mark.parametrize("changed",[
    {"kind":"first_quarter_total","line":52.5,"side":"over"},
    {"kind":"player_points","line":24.5,"side":"over"},
    {"kind":"full_game_total","overtime_included":False,"line":220.5,"side":"over"},
    {"kind":"full_game_total","event_id":"wrong","line":220.5,"side":"over"},
    {"kind":"full_game_total","line":float("nan"),"side":"over"},
])
def test_never_guess_period_player_or_ambiguous_market(changed):
    game={"event_id":"evt1","home_id":"h","away_id":"a",
          "home_score":110,"away_score":105,"status":"final"}
    market={"event_id":"evt1","home_id":"h","away_id":"a",
            "league":"nba","overtime_included":True,
            "kind":"full_game_total","line":210.5,"side":"over"}
    with pytest.raises(ValueError):
        m.grade_full_game({**market,**changed},game)


def test_leagues_are_candidates_not_automatic_public_picks():
    sample={"independent_verified_finals":50,"complete_seasons":1}
    for league in l.CANDIDATE_LEAGUES:
        x=l.assess_league(league,sample)
        assert not x["model_eligible"]
        assert not x["public_publishing_enabled"]
        assert "insufficient_independent_finals" in x["blockers"]
    full={"independent_verified_finals":500,"complete_seasons":3,
          "licensed_for_this_use":True,"stable_team_ids":True,
          "cross_source_final_agreement":True,"date_complete":True,
          "league_period_rules_verified":True,
          "pre_tipoff_features_original":True,"independent_calibration_passed":True}
    accepted=l.assess_league("wnba",full)
    assert accepted["model_eligible"]
    assert accepted["public_publishing_enabled"] is False
    with pytest.raises(ValueError):
        l.assess_league("unknown",full)


def test_v2_ack_requires_current_archive_markets_and_complete_job_prefix():
    good={"verified":True,"store":"private_vercel_blob_v2",
          "archive_digest":"a"*64,"blob_sha256":"b"*64,
          "market_receipt_count":5,"job_receipt_count":15,"last_job_id":15}
    fake={"portable_backup_v1":{"archive_digest":"a"*64,
                                "market_receipt_count":5},
          "job_receipts":[{"id":i} for i in range(1,16)]}
    ok=b.verify_v2_backup_ack(good,recovery_loader=lambda:fake)
    assert ok["status"]=="verified_full_private_blob_readback"
    for bad in ({"job_receipt_count":14},{"market_receipt_count":6},
                {"last_job_id":14},{"archive_digest":"0"*64},
                {"store":"public_blob"},{"blob_sha256":"bad"}):
        with pytest.raises(ValueError):
            b.verify_v2_backup_ack({**good,**bad},recovery_loader=lambda:fake)
