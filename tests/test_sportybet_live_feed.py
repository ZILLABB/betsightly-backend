"""SportyBet live data must be cost-bounded and display-only."""
from datetime import datetime, timezone
from leagues import sportybet_live_feed as feed

FIXTURE = {
    "event_id": "sr:match:73220854",
    "home_team": "Dominica", "away_team": "Guyana",
    "home_score": 0, "away_score": 2, "start_time_ms": 1790888400000,
    "match_status": "HT", "match_minute": 45, "is_live": True,
}

def test_parser_provisional_and_90_minute_is_never_final():
    result = feed._parse_match(FIXTURE)
    assert result and result["live"] and result["provisional"]
    assert result["finished"] is False
    assert result["event_id"] == FIXTURE["event_id"]

def test_parser_rejects_fake_live_finished_and_missing_scores():
    assert feed._parse_match({**FIXTURE,"match_status":"FT"}) is None
    assert feed._parse_match({**FIXTURE,"is_live":False}) is None
    assert feed._parse_match({**FIXTURE,"home_score":None}) is None
    assert feed._parse_match({**FIXTURE,"event_id":"invalid"}) is None
    assert feed._parse_match({**FIXTURE,"home_team":""}) is None

def test_parser_removes_ambiguous_duplicate_event_ids():
    response = {"status":"success","data":{"matches":[FIXTURE,{**FIXTURE,"away_score":3}]}}
    assert feed._parse_payload(response) == []

def test_parser_accepts_documented_nested_response():
    result=feed._parse_payload({"status":"success","data":{"matches":[FIXTURE]}})
    assert len(result)==1
    assert result[0]["date"]=="2026-10-01"

def test_disabled_does_not_make_external_calls(monkeypatch):
    monkeypatch.delenv("SPORTYBET_PARSE_LIVE_ENABLED",raising=False)
    monkeypatch.setattr(feed.requests,"get",lambda *a,**kw: (_ for _ in ()).throw(AssertionError()))
    assert feed.snapshot()["status"]=="disabled"

def test_enabled_requires_key(monkeypatch):
    monkeypatch.setenv("SPORTYBET_PARSE_LIVE_ENABLED","true")
    monkeypatch.delenv("SPORTYBET_PARSE_API_KEY",raising=False)
    assert feed.snapshot()["status"]=="missing_api_key"

def test_cache_prevents_repeated_provider_calls(monkeypatch):
    monkeypatch.setenv("SPORTYBET_PARSE_LIVE_ENABLED","true")
    monkeypatch.setenv("SPORTYBET_PARSE_API_KEY","not-a-real-key")
    monkeypatch.setattr(feed,"_LAST_FETCH",0.)
    monkeypatch.setattr(feed,"_BUDGET_DAY","")
    monkeypatch.setattr(feed,"_BUDGET_MONTH","")
    calls=[]
    class Response:
        status_code=200
        def json(self): return {"status":"success","data":{"matches":[FIXTURE]}}
    monkeypatch.setattr(feed.requests,"get",lambda url,**kw:calls.append((url,kw)) or Response())
    assert len(feed.snapshot()["matches"])==1
    assert len(feed.snapshot()["matches"])==1
    assert len(calls)==1
    assert "X-API-Key" in calls[0][1]["headers"]

def test_monthly_budget_not_bypassed(monkeypatch):
    monkeypatch.setenv("SPORTYBET_PARSE_LIVE_ENABLED","true")
    monkeypatch.setenv("SPORTYBET_PARSE_API_KEY","test")
    monkeypatch.setenv("SPORTYBET_PARSE_DAILY_BUDGET","1")
    monkeypatch.setattr(feed,"_LAST_FETCH",0)
    monkeypatch.setattr(feed,"_BUDGET_DAY","")
    monkeypatch.setattr(feed,"_BUDGET_MONTH","")
    class Response:
        status_code=200
        def json(self): return {"status":"success","data":{"matches":[]}}
    calls=[]
    monkeypatch.setattr(feed.requests,"get",lambda *a,**kw:calls.append(1) or Response())
    assert feed.snapshot()["status"]=="no_live_games"
    monkeypatch.setattr(feed,"_LAST_FETCH",0)
    assert feed.snapshot()["status"]=="budget_exhausted"
    assert len(calls)==1
