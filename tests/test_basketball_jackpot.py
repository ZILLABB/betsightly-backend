"""Fail-closed basketball code creation and independent bookmaker caching."""
import time

from growth import basketball_jackpot as bj
from growth import basketball_history as bh
import pytest


@pytest.fixture(autouse=True)
def isolated_booking_ledger(monkeypatch):
    """Existing code tests isolate DB while exercising booking/readback."""
    monkeypatch.setattr(bh, "claim", lambda selections, legs, target, snapshot: (
        True, {"fingerprint": "unit-test-claim", "status": "creating"}))
    monkeypatch.setattr(bh, "mark", lambda fingerprint, **kwargs: None)



def _event(when=None, eid="sr:match:9876"):
    return {
        "eventId": eid,
        "homeTeamName": "Boston Celtics",
        "awayTeamName": "New York Knicks",
        "estimateStartTime": when or int((time.time() + 7200) * 1000),
        "markets": [
            {"id": "219", "specifier": "", "outcomes": [
                {"id": "4", "desc": "Boston Celtics", "odds": "1.70", "isActive": True},
                {"id": "5", "desc": "New York Knicks", "odds": "2.20", "isActive": True},
            ]},
            {"id": "225", "specifier": "total=221.5", "outcomes": [
                {"id": "12", "desc": "Over", "odds": "1.95", "isActive": True},
                {"id": "13", "desc": "Under", "odds": "1.85", "isActive": False},
            ]},
        ],
    }


def _board():
    return {"fetched_at": time.time(), "metadata": {
        "is_complete": True, "schema": bj.SCHEMA, "snapshot_id": "test-1",
    }, "fixtures": [bj._parse_event(_event(), "NBA")]}


def _request():
    return {"target_odds": 2, "selections": [
        {"event_id": "sr:match:9876", "market_id": "219",
         "specifier": "", "outcome_id": "5"}]}


def test_exact_basketball_market_mapping_and_suspensions():
    event = bj._parse_event(_event(), "NBA")
    assert event["home_team"] == "Boston Celtics"
    assert len(event["markets"]) == 2
    assert [o["outcome_id"] for o in event["markets"][0]["outcomes"]] == ["4", "5"]
    assert [o["label"] for o in event["markets"][1]["outcomes"]] == ["Over 221.5"]
    assert bj._parse_event({**_event(), "markets": [{
        "id": "225", "specifier": "total=two hundred",
        "outcomes": [{"id": "12", "odds": "1.9"}],
    }]}, "NBA")["markets"] == []


def test_partial_basketball_refresh_preserves_previous_complete_board(monkeypatch):
    stored = _board()
    changes = []
    monkeypatch.setattr(bj.sportybet, "_db_get",
                        lambda key: stored if key == bj.CACHE_KEY else None)
    monkeypatch.setattr(bj.sportybet, "_db_set",
                        lambda key, value: changes.append((key, value)))
    monkeypatch.setattr(bj.sportybet, "_get_json", lambda url, timeout=20: {
        "bizCode": 10000, "data": {"totalNum": 3, "tournaments": [
            {"name": "NBA", "events": [_event()]}] if "pageNum=1" in url else []},
    })
    res = bj.refresh_board()
    assert res["status"] == "REFRESH_INCOMPLETE"
    assert res["board_preserved"] is True
    assert all(key != bj.CACHE_KEY for key, _ in changes)
    assert bj.cached_board() is stored


def test_basketball_refresh_retries_one_event_count_drift(monkeypatch):
    """A near-complete response is not promoted; only the second full pass is."""
    attempts, writes = [], []

    def unstable_provider(url, timeout=20):
        if "pageNum=1" in url:
            attempts.append(1)
            declared = 2 if len(attempts) == 1 else 1
            return {"bizCode": 10000, "data": {"totalNum": declared,
                "tournaments": [{"name": "NBA", "events": [_event()]}]}}
        return {"bizCode": 10000, "data": {"totalNum": 2, "tournaments": []}}

    monkeypatch.setattr(bj.sportybet, "_get_json", unstable_provider)
    monkeypatch.setattr(bj.sportybet, "_db_set",
                        lambda key, data: writes.append((key, data)))
    report = bj.refresh_board()
    assert report["status"] == "success"
    assert len(attempts) == 2
    assert len(writes) == 1
    assert writes[0][0] == bj.CACHE_KEY
    assert writes[0][1]["metadata"]["is_complete"] is True


def test_full_basketball_refresh_is_promoted(monkeypatch):
    changes = []
    monkeypatch.setattr(bj.sportybet, "_db_set",
                        lambda key, value: changes.append((key, value)))
    monkeypatch.setattr(bj.sportybet, "_get_json", lambda url, timeout=20: {
        "bizCode": 10000, "data": {"totalNum": 1, "tournaments": [
            {"name": "NBA", "events": [_event()]}]},
    })
    result = bj.refresh_board()
    assert result["status"] == "success"
    assert len(changes) == 1 and changes[0][0] == bj.CACHE_KEY
    assert changes[0][1]["metadata"]["sport"] == "basketball"


def test_preview_keeps_exact_market_and_never_substitutes(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", _board)
    ok = bj.preview(_request())
    assert ok["status"] == "PROPOSED_NOT_BOOKED"
    assert ok["matched_fixture_count"] == 1
    assert ok["matched"][0]["outcome_id"] == "5"
    assert ok["indicative_odds"] == 2.2
    bad = _request()
    bad["selections"][0]["outcome_id"] = "13"
    bad["selections"][0]["market_id"] = "225"
    bad["selections"][0]["specifier"] = "total=221.5"
    result = bj.preview(bad)
    assert result["status"] == "EXACT_MARKETS_UNAVAILABLE"
    assert result["share_code"] is None


def test_booking_never_exposes_failed_readback_code(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", _board)
    monkeypatch.setattr(bj.booking, "_post_share", lambda selections: {
        "bizCode": 10000, "data": {"shareCode": "ABC123"}})
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, expected: (False, "wrong selection", None))
    result = bj.book(_request())
    assert result["status"] == "BOOKING_UNAVAILABLE"
    assert result["share_code"] is None
    assert result["readback_status"] == "FAILED"


def test_booking_verified_readback_can_release_code(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", _board)
    expected = []
    def post(selections):
        expected.extend(selections)
        return {"bizCode": 10000, "data": {"shareCode": "NBA123",
                "deadline": int((time.time() + 3600) * 1000)}}
    monkeypatch.setattr(bj.booking, "_post_share", post)
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, selections: (selections == expected, "ok", 2.2))
    result = bj.book(_request())
    assert result["status"] == "success"
    assert result["readback_status"] == "PASSED"
    assert result["share_code"] == "NBA123"


def test_incomplete_readback_odds_must_not_release_code(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", _board)
    monkeypatch.setattr(bj, "refresh_board",
                        lambda: {"status": "REFRESH_INCOMPLETE"})
    monkeypatch.setattr(bj.booking, "_post_share", lambda selections: {
        "bizCode": 10000, "data": {"shareCode": "ABC123"}})
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, expected: (True, "ok", None))
    report = bj.book(_request())
    assert report["share_code"] is None
    assert report["readback_status"] == "ODDS_UNAVAILABLE"


def test_basketball_cache_freshness_limit():
    cached = _board()
    cached["fetched_at"] = time.time() - bj.CACHE_AGE - 10
    assert bj._valid_cached(cached) is False


def test_basketball_code_requires_future_expiry(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", _board)
    monkeypatch.setattr(bj.booking, "_post_share", lambda selections: {
        "bizCode": 10000, "data": {"shareCode": "GOOD12", "deadline": 0}})
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, expected: (True, "ok", 2.3))
    result = bj.book(_request())
    assert result["share_code"] is None
    assert result["readback_status"] == "FAILED"



def test_basketball_readback_without_total_uses_fresh_exact_board(monkeypatch):
    from time import time
    monkeypatch.setattr(bj, "cached_board", _board)
    refreshed = []
    monkeypatch.setattr(bj, "refresh_board",
                        lambda: refreshed.append(True) or {"status": "success"})
    posts = []
    def share(selected):
        posts.append(selected)
        return {"bizCode": 10000, "data": {"shareCode": "YES123",
                "deadline": int((time() + 3600) * 1000)}}
    monkeypatch.setattr(bj.booking, "_post_share", share)
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, selected: (True, "ok", None))
    result = bj.book(_request())
    assert len(posts) == 1  # No duplicate create on fallback.
    assert len(refreshed) == 1
    assert result["status"] == "success"
    assert result["share_code"] == "YES123"
    assert result["verified_odds"] == 2.2
    assert result["verified_odds_source"] == "fresh_complete_sportybet_board"


def test_basketball_fresh_total_below_target_never_releases_code(monkeypatch):
    from time import time
    initial = _board()
    newer = _board()
    newer["fixtures"][0]["markets"][0]["outcomes"][1]["odds"] = 1.7
    attempts = []
    def refresh():
        attempts.append(True)
        return {"status": "success"}
    monkeypatch.setattr(bj, "cached_board",
                        lambda: newer if attempts else initial)
    monkeypatch.setattr(bj, "refresh_board", refresh)
    monkeypatch.setattr(bj.booking, "_post_share", lambda selected: {
        "bizCode": 10000, "data": {"shareCode": "PRICED",
                "deadline": int((time() + 3600) * 1000)}})
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, selected: (True, "ok", None))
    result = bj.book(_request())
    assert result["status"] == "BOOKING_UNAVAILABLE"
    assert result["readback_status"] == "BELOW_TARGET"
    assert result["share_code"] is None
    assert result["verified_odds"] == 1.7
    assert "below" in result["reason"].lower()


def test_basketball_refreshed_missing_exact_market_stays_unavailable(monkeypatch):
    from time import time
    initial = _board()
    newer = _board()
    newer["fixtures"][0]["markets"] = []
    attempted = []
    monkeypatch.setattr(bj, "cached_board",
                        lambda: newer if attempted else initial)
    monkeypatch.setattr(bj, "refresh_board",
                        lambda: attempted.append(True) or {"status": "success"})
    monkeypatch.setattr(bj.booking, "_post_share", lambda selected: {
        "bizCode": 10000, "data": {"shareCode": "NOMKT",
                "deadline": int((time() + 3600) * 1000)}})
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, selected: (True, "ok", None))
    result = bj.book(_request())
    assert result["share_code"] is None
    assert result["unmatched"][0]["reason"] == "EXACT_MARKET_NOT_ACTIVE"


def test_basketball_authoritative_readback_price_below_target_is_respected(monkeypatch):
    from time import time
    monkeypatch.setattr(bj, "cached_board", _board)
    monkeypatch.setattr(bj, "refresh_board",
                        lambda: (_ for _ in ()).throw(AssertionError(
                            "Must not override actual code readback with board")))
    monkeypatch.setattr(bj.booking, "_post_share", lambda selected: {
        "bizCode": 10000, "data": {"shareCode": "NOTENOUGH",
                "deadline": int((time() + 3600) * 1000)}})
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, selected: (True, "ok", 1.9))
    result = bj.book(_request())
    assert result["share_code"] is None
    assert result["readback_status"] == "BELOW_TARGET"
    assert result["verified_odds_source"] == "sportybet_code_readback"


def test_duplicate_basketball_request_never_calls_sportybet(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", _board)
    monkeypatch.setattr(bh, "claim", lambda *args: (
        False, {"fingerprint": "previous-claim", "status": "needs_review",
                "expires_at": None, "share_code": None}))
    called = []
    monkeypatch.setattr(bj.booking, "_post_share",
                        lambda picks: called.append(picks))
    report = bj.book(_request())
    assert report["status"] == "BOOKING_PREVIOUS_ATTEMPT"
    assert report["share_code"] is None
    assert called == []


def test_basketball_db_failure_never_requests_sportybet_code(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", _board)
    def raise_unavailable(*args):
        raise RuntimeError("database down")
    monkeypatch.setattr(bh, "claim", raise_unavailable)
    called = []
    monkeypatch.setattr(bj.booking, "_post_share",
                        lambda picks: called.append(picks))
    report = bj.book(_request())
    assert report["status"] == "BOOKING_HISTORY_UNAVAILABLE"
    assert called == []


def test_basketball_verified_ticket_is_archived(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", _board)
    steps = []
    monkeypatch.setattr(bh, "mark",
                        lambda fingerprint, **kwargs: steps.append(kwargs))
    monkeypatch.setattr(bj.booking, "_post_share", lambda selections: {
        "bizCode": 10000, "data": {"shareCode": "PAID22",
        "deadline": int((time.time() + 3600) * 1000)}})
    monkeypatch.setattr(bj.booking, "validate_code_details",
                        lambda code, expected: (True, "ok", 2.2))
    result = bj.book(_request())
    assert result["history_saved"] is True
    assert result["share_code"] == "PAID22"
    assert [item["status"] for item in steps] == ["verifying", "active"]
