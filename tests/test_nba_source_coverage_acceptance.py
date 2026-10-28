"""NBA scheduled fixture completeness and independent model calibration."""
from datetime import datetime, timezone, timedelta
import copy
import pytest
from basketball import research_schedule_coverage as cov
from basketball import research_forward_scorecard as scores
from basketball import research_full_recovery as backup

NOW=datetime(2026,10,28,10,tzinfo=timezone.utc)

def game(gid,tip):
    return {"game_id":str(gid),"season":2027,"status":"scheduled",
            "postseason":False,"start_utc":tip.isoformat(),
            "home_id":"12","away_id":"13"}

def manifest():
    return [{"season":2027,"regular_season_games":1230,
             "quality":{"rejected_regular_rows":0,
                        "not_a_complete_provider_schedule":False}}]

def test_source_calendar_exposes_unforecasted_next_two_days(monkeypatch):
    monkeypatch.setattr(cov,"inspect_bundle",lambda _:None)
    one=game(11,NOW+timedelta(hours=13))
    two=game(12,NOW+timedelta(hours=24))
    far=game(14,NOW+timedelta(days=5))
    archive={"fixtures":[one],"records":{
        "moneyline":[{"game_id":"11"}],"opening_score":[{"game_id":"11"}]}}
    result=cov.audit_nba_coverage(archive,[one,two,far],
        now=NOW,season=2027,manifests=manifest())
    assert result["next_48h_source_fixtures"]==2
    assert result["next_48h_missing_archive"]==1
    assert result["next_48h_missing_original_model"]==1
    assert result["next_7d_not_archived"]==2
    assert not result["next_48h_original_coverage_complete"]
    assert not result["independent_schedule_agreement_proven"]

    complete=copy.deepcopy(archive)
    complete["fixtures"].append(two)
    for key in ("moneyline","opening_score"):
        complete["records"][key].append({"game_id":"12"})
    passed=cov.audit_nba_coverage(complete,[one,two,far],
        now=NOW,season=2027,manifests=manifest())
    assert passed["next_48h_missing_original_model"]==0
    assert passed["next_48h_original_coverage_complete"]
    assert not passed["full_season_prediction_coverage_proven"]

def test_identity_drift_refuses_to_claim_calendar_complete(monkeypatch):
    monkeypatch.setattr(cov,"inspect_bundle",lambda _:None)
    item=game(11,NOW+timedelta(hours=12))
    archive={"fixtures":[{**item,"home_id":"wrong"}],"records":{
        "moneyline":[{"game_id":"11"}],"opening_score":[{"game_id":"11"}]}}
    with pytest.raises(ValueError,match="IDENTITY_CONFLICT"):
        cov.audit_nba_coverage(archive,[item],now=NOW,
            season=2027,manifests=manifest())

def test_forecast_scorecard_has_chance_and_home_baselines(monkeypatch):
    monkeypatch.setattr(scores,"inspect_bundle",lambda _:None)
    fixture={"game_id":"12","start_utc":"2026-10-28T20:00:00+00:00",
             "status":"final","home_score":121,"away_score":112}
    pred={"game_id":"12","captured_at":"2026-10-28T18:00:00+00:00",
          "probability_home_win":0.75}
    archive={"fixtures":[fixture],"records":{
        "moneyline":[pred],"moneyline_finals":[{
            "game_id":"12","home_score":121,"away_score":112}],
        "opening_score":[],"opening_score_finals":[]}}
    m=scores.scorecard(archive)["models"]["moneyline"]
    assert m["brier"]==0.0625
    assert m["chance_brier_baseline"]==0.25
    assert m["always_home_accuracy"]==1
    assert m["brier_skill_vs_chance"]==0.75
    assert sum(x["n"] for x in m["calibration_bins"])==1

def test_backup_audit_accepts_only_bounded_coverage_key():
    old={"id":1,"kind":"forecast","status":"archived_before_tipoff",
         "recorded_at":"2026-10-28T09:00:00+00:00",
         "summary_json":'{"outcome":"archived_before_tipoff","coverage":{"next_48h_source_fixtures":12}}'}
    backup._validate_rows([old])
    broken={**old,"summary_json":'{"outcome":"ok","provider_auth_secret":"oops"}'}
    with pytest.raises(ValueError):
        backup._validate_rows([broken])
