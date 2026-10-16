"""SportyBet live snapshots extend UI coverage, never official settlement."""
from copy import deepcopy
from leagues.live_scores import overlay_sportybet_live

GAME = {"match_id":"abc123", "sportybet_event_id":"sr:match:1234",
        "home_team":"Alpha FC", "away_team":"Beta",
        "kickoff":"2026-10-16T18:00:00Z"}
OBS = {"event_id":"sr:match:1234", "home_team":"Alpha FC",
       "away_team":"Beta", "date":"2026-10-16",
       "home_score":2, "away_score":1, "live":True, "finished":False,
       "provisional":True, "match_status":"H2", "match_minute":72}

def test_live_overlay_makes_provisional_score_visible_for_published_match():
    input_scores={}
    result,n=overlay_sportybet_live(input_scores,[GAME],[OBS])
    assert n==1 and input_scores=={}
    assert result["abc123"]["home_score"]==2
    assert result["abc123"]["state"]=="in"
    assert result["abc123"]["finished"] is False

def test_live_overlay_keeps_existing_espn_finished():
    scores={"abc123":{"finished":True,"home_score":1,"away_score":0,"live":False}}
    before=deepcopy(scores)
    result,n=overlay_sportybet_live(scores,[GAME],[OBS])
    assert n==0 and result==before and scores==before

def test_live_overlay_keeps_existing_espn_inplay():
    scores={"abc123":{"finished":False,"home_score":0,"away_score":1,"live":True}}
    result,n=overlay_sportybet_live(scores,[GAME],[OBS])
    assert n==0 and result==scores

def test_live_overlay_rejects_wrong_fixture_identity():
    for changed in (
        {"event_id":"sr:match:1235"},
        {"home_team":"Gamma"},
        {"away_team":"Delta"},
        {"date":"2026-10-17"},
        {"finished":True},
        {"provisional":False},
    ):
        result,n=overlay_sportybet_live({},[GAME],[{**OBS,**changed}])
        assert n==0 and result=={}

def test_duplicate_event_id_never_overlays_score():
    result,n=overlay_sportybet_live({},[GAME],[OBS,OBS])
    assert n==0 and result=={}
