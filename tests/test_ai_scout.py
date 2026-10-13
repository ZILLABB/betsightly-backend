"""Fail-closed tests for source-linked OpenAI research and isolation."""
import json
from datetime import datetime, timedelta, timezone

from leagues import ai_scout


def _pick(fid, *, real=True, bookable=True, minutes=120, market="over_1_5"):
    kickoff = (datetime.now(timezone.utc) + timedelta(minutes=minutes))
    return {
        "match_id": fid,
        "market": market,
        "market_group": "goals",
        "odds": 1.45,
        "odds_are_real": real,
        "bookable": bookable,
        "confidence": 0.78,
        "safe_tier_eligible": True,
        "market_floor_eligible": True,
        "trust": {
            "trust_grade": "A",
            "evidence_adjusted_probability": .78,
            "lower_reliability_bound": .72,
        },
        "_fixture": {
            "commence_time": kickoff.isoformat(),
            "home": {"name": "Home"}, "away": {"name": "Away"},
            "league": "Test League", "league_slug": "eng.1",
        },
    }


def test_scout_disabled_never_fetches_board_or_uses_api(monkeypatch):
    monkeypatch.delenv("AI_SCOUT_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai_scout.run_once(day="2026-10-13")["status"] == "DISABLED"


def test_scout_missing_key_fail_closed_without_database(monkeypatch):
    monkeypatch.setenv("AI_SCOUT_ENABLED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai_scout.run_once(day="2026-10-13")["status"] == "NO_API_KEY"


def test_inventory_one_market_per_fixture_and_bounded():
    now = datetime.now(timezone.utc)
    day = now.astimezone(ai_scout.WAT).date().isoformat()
    # Run date needs to agree with kickoff WAT. Construct future date.
    base = (now + timedelta(days=1)).astimezone(ai_scout.WAT).date()
    day = base.isoformat()
    start = datetime.combine(base, datetime.min.time(),
                             tzinfo=ai_scout.WAT).astimezone(timezone.utc)
    picks = []
    for i in range(12):
        p = _pick(str(i))
        p["_fixture"]["commence_time"] = (
            start + timedelta(hours=15)).isoformat()
        picks.append(p)
        second = {**p, "market": "home_or_draw", "odds": 1.6}
        picks.append(second)
    found = ai_scout.candidate_inventory(picks, day, now=now)
    assert len(found) == ai_scout.MAX_FIXTURES
    assert len({x["fixture_id"] for x in found}) == len(found)
    assert all("publication_allowed" in x for x in found)
    assert all("model_probability" in x for x in found)


def _body(cid, *, tool_urls=None, verdict="RESEARCH_PRIORITY"):
    output = []
    if tool_urls is not None:
        output.append({
            "type": "web_search_call", "action": {
                "type": "search",
                "sources": [{"type": "url", "url": u} for u in tool_urls],
            },
        })
    output.append({
        "type": "message", "content": [{"type": "output_text", "text": json.dumps({
            "assessments": [{
                "candidate_id": cid, "verdict": verdict,
                "rationale": "Report suggests a review.",
                "verification_gap": "Lineups not confirmed.",
                "request_price_refresh": True,
                "source_urls": tool_urls or [],
            }],
        })}],
    })
    return {"status": "completed", "output": output, "usage": {"total_tokens": 42}}


def test_missing_search_sources_downgrades_priority():
    cand = [{"candidate_id": "abc", "fixture_id": "f1"}]
    rows = ai_scout.parse_response(_body("abc"), cand)
    assert rows[0]["verdict"] == "NEEDS_VERIFICATION"
    assert rows[0]["source_urls"] == []
    assert rows[0]["research_only"] is True
    assert rows[0]["bookmaker_code_verified"] is False


def test_only_actual_search_call_urls_become_citations():
    cand = [{"candidate_id": "abc", "fixture_id": "f1"}]
    body = _body("abc", tool_urls=[
        "https://www.espn.com/football", "javascript:alert(1)",
        "http://example.com/unverified",
    ])
    rows = ai_scout.parse_response(body, cand)
    assert rows[0]["verdict"] == "RESEARCH_PRIORITY"
    assert rows[0]["source_urls"] == ["https://www.espn.com/football"]


def test_unknown_or_duplicate_ai_fixture_cannot_enter_watchlist():
    cand = [{"candidate_id": "abc", "fixture_id": "f1"}]
    body = _body("unrecognized", tool_urls=["https://example.com/news"])
    assert ai_scout.parse_response(body, cand) == []
    body = _body("abc", tool_urls=["https://example.com/news"])
    obj = json.loads(body["output"][-1]["content"][0]["text"])
    obj["assessments"] *= 2
    body["output"][-1]["content"][0]["text"] = json.dumps(obj)
    assert len(ai_scout.parse_response(body, cand)) == 1


def test_api_request_never_sends_ticket_or_user_data(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-secret")
    monkeypatch.setenv("AI_SCOUT_MODEL", "gpt-5-mini")
    candidate = {"candidate_id": "abc", "fixture_id": "f1",
                 "model_probability": .75, "market": "over_1_5"}
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return _body("abc")
    class FakeClient:
        def post(self, url, *, json, headers):
            assert url == "https://api.openai.com/v1/responses"
            assert json["store"] is False
            assert json["tools"][0]["type"] == "web_search"
            assert json["text"]["format"]["strict"] is True
            assert "booking_code" not in str(json)
            assert "fake-secret" not in str(json)
            assert headers["Authorization"] == "Bearer fake-secret"
            return FakeResponse()
    result = ai_scout._call_openai([candidate], http_client=FakeClient())
    assert result["status"] == "completed"


def test_incomplete_response_reports_safe_reason_without_untrusted_content():
    import pytest
    body = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [],
    }
    with pytest.raises(ValueError, match="reason=max_output_tokens"):
        ai_scout.parse_response(body, [{"candidate_id": "abc"}])


def test_openai_budget_allows_web_research_and_structured_output(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-credential")
    class Fake:
        def post(self, url, *, json, headers):
            assert json["max_output_tokens"] >= 4000
            assert json["store"] is False
            assert json["text"]["format"]["strict"] is True
            class Resp:
                def raise_for_status(self): pass
                def json(self): return {"status":"completed", "output":[
                    {"type":"message", "content":[{"type":"output_text",
                    "text": '{"assessments":[]}'}]}
                ]}
            return Resp()
    response = ai_scout._call_openai(
        [{"candidate_id": "abc", "market": "over_1_5"}],
        http_client=Fake()
    )
    assert response["status"] == "completed"
