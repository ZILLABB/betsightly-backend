from leagues.evidence_fusion import fused_market_evidence
from leagues.leg_trust import evaluate_leg_trust

def _pick(market="under_4_5",confidence=.86,**changes):
    value={"match_id":"m","market":market,"market_group":"goals","confidence":confidence,
           "raw_confidence":confidence,"calibration_sample":0,"safe_tier_eligible":False,
           "bookable":True,"sportybet_availability":{"status":"BOOKABLE","sportybet_available":True,"board_snapshot_id":"b"},
           "_fixture":{"commence_time":"2099-01-01T00:00:00Z","league":"Premier League"}}
    value.update(changes); return value

def test_large_historical_evidence_can_support_low_live_market():
    decision=evaluate_leg_trust(_pick())
    assert decision["accepted"] and decision["evidence_state"]=="SUPPORTED"

def test_under_3_5_is_supported():
    assert evaluate_leg_trust(_pick("under_3_5",.76))["accepted"]

def test_conflicting_live_evidence_downgrades_match_result():
    evidence=fused_market_evidence("home_win",.67,"Premier League",{"n":20,"actual":.45})
    assert evidence["live_conflict"] and evidence["state"]=="SHADOW"
    assert evidence["evidence_adjusted_probability"]<=.45

def test_btts_remains_restricted():
    decision=evaluate_leg_trust(_pick("btts_yes",.75))
    assert not decision["accepted"] and decision["evidence_state"]=="SHADOW"

def test_exact_bookability_is_still_required():
    decision=evaluate_leg_trust(_pick(bookable=False,sportybet_availability={"status":"SELECTION_NOT_FOUND","sportybet_available":False}))
    assert not decision["accepted"]

def test_sparse_live_sample_cannot_overturn_historical_evidence():
    evidence=fused_market_evidence("under_4_5",.86,"Premier League",{"n":2,"actual":0})
    assert not evidence["live_conflict"]
    assert evidence["evidence_adjusted_probability"]>.7

def test_hierarchy_uses_confidence_bucket_before_global():
    evidence=fused_market_evidence("under_4_5",.86,"unknown",None)
    assert evidence["hierarchy_level"]=="market_confidence_bucket"
