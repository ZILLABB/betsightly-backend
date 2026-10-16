"""Licensed LiveScore adapter mock tests: zero real external network calls."""
from datetime import datetime, timezone
from leagues import authorized_livescore as feed


def event(event_id="7733", esid=2, epr=1, phase="71'", tr1="2", tr2="1"):
    return {"Eid": event_id, "Esd": "20261016190000",
            "T1": [{"Nm": "Arsenal FC"}], "T2": [{"Nm": "Chelsea"}],
            "Tr1": tr1, "Tr2": tr2, "Tr1OR": "2", "Tr2OR": "1",
            "Trh1": "1", "Trh2": "0", "Esid": esid, "Epr": epr,
            "Eps": phase}

def payload(rows):
    return {"Stages":[{"Snm":"Premier League", "Events":rows}]}


def game(mid="publisher-1", kickoff="2026-10-16T19:00:00Z"):
    return {"match_id":mid,"home_team":"Arsenal","away_team":"Chelsea",
            "kickoff":kickoff}


def test_parses_live_minute_and_scores_from_real_schema():
    result=feed.parse_payload(payload([event()]))[0]
    assert result["home_score"]==2 and result["away_score"]==1
    assert result["clock"]=="71'" and result["live"] and result["provisional"]
    assert not result["score_verified"] and not result["finished"]
    assert result["half_home_score"]==1


def test_finish_is_reported_not_verified():
    result=feed.parse_payload(payload([event(esid=6,epr=2,phase="FT")]))[0]
    assert result["finished"] and not result["live"]
    assert not result["score_verified"] and result["provisional"]


def test_unknown_status_and_after_penalties_never_become_ft():
    assert feed.parse_payload(payload([event(esid=13,epr=2,phase="AP")]))==[]
    assert feed.parse_payload(payload([event(esid=7,epr=2,phase="FT")]))==[]
    assert feed.parse_payload(payload([event(esid=6,epr=1,phase="FT")]))==[]


def test_incomplete_scores_and_malformed_id_rejected():
    assert feed.parse_payload(payload([event(tr1=None)]))==[]
    assert feed.parse_payload(payload([event(event_id="garbage")]))==[]


def test_duplicate_conflicting_provider_ids_fail_closed():
    assert feed.parse_payload(payload([event(tr1="1"),event(tr1="2")]))==[]


def test_unique_team_date_mapping_only_adds_provisional_ui():
    rows=feed.parse_payload(payload([event()]))
    original={}
    result,n=feed.overlay(original,[game()],rows)
    assert n==1 and original=={}
    assert result["publisher-1"]["source"]=="livescore-cdn"
    assert result["publisher-1"]["provisional"]


def test_wrong_teams_dates_and_reversed_fixtures_dont_join():
    rows=feed.parse_payload(payload([event()]))
    for invalid in [
        {**game(),"home_team":"Chelsea","away_team":"Arsenal FC"},
        {**game(),"kickoff":"2026-10-17T19:00:00Z"},
        {**game(),"home_team":"Arsenal U21"},
    ]:
        result,n=feed.overlay({},[invalid],rows)
        assert n==0 and result=={}


def test_existing_live_or_final_espn_not_overwritten():
    existing={"publisher-1":{"live":True,"finished":False,"home_score":0}}
    out,n=feed.overlay(existing,[game()],feed.parse_payload(payload([event()])))
    assert not n and out==existing


def test_duplicate_published_fixture_claims_fail_closed():
    result,n=feed.overlay({},[game("a"),game("b")],feed.parse_payload(payload([event()])))
    assert n==0 and result=={}


def test_authorization_gate_blocks_all_network_calls(monkeypatch):
    monkeypatch.setenv("LIVESCORE_CDN_ENABLED","true")
    monkeypatch.delenv("LIVESCORE_CDN_USAGE_AUTHORIZED",raising=False)
    monkeypatch.setattr(feed.requests,"get",lambda *a,**k: (_ for _ in ()).throw(AssertionError()))
    result=feed.snapshot(["2026-10-16"])
    assert result["status"]=="disabled"


def test_enabled_mock_reads_date_and_live_once(monkeypatch):
    monkeypatch.setenv("LIVESCORE_CDN_ENABLED","true")
    monkeypatch.setenv("LIVESCORE_CDN_USAGE_AUTHORIZED","true")
    monkeypatch.setattr(feed,"_LAST_FETCH",0.)
    class Resp:
        status_code=200
        def json(self): return payload([event()])
    calls=[]
    monkeypatch.setattr(feed.requests,"get",lambda url,**kw:calls.append(url) or Resp())
    one=feed.snapshot(["2026-10-16"])
    two=feed.snapshot(["2026-10-16"])
    assert one["status"]=="ok" and len(one["matches"])==1
    assert two==one and len(calls)==2


def test_max_date_window_and_invalid_dates_rejected_before_network(monkeypatch):
    monkeypatch.setenv("LIVESCORE_CDN_ENABLED","true")
    monkeypatch.setenv("LIVESCORE_CDN_USAGE_AUTHORIZED","true")
    monkeypatch.setattr(feed.requests,"get",lambda *a,**kw: (_ for _ in ()).throw(AssertionError()))
    assert feed.snapshot(["2026-10-16","2026-10-17","2026-10-18","2026-10-19"])["status"]=="invalid_date_window"
    assert feed.snapshot(["invalid"])["status"]=="invalid_date_window"
