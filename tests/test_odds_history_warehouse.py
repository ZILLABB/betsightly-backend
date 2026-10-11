"""Phase 9 odds history is append-only; opening quotes never fake CLV."""
from sqlalchemy import create_engine

from leagues import odds_history_warehouse as wh


def _record():
    return {
        "status": "active",
        "booking_status": "FULL",
        "readback_validation": "PASSED",
        "priced_at": "2026-10-11T08:00:00Z",
        "board_snapshot_id": "board-verified-abc",
        "final_booked_legs": [{
            "match_id": "m1", "sportybet_event_id": "evt1",
            "market": "over_1_5", "odds": 1.42, "odds_are_real": True,
            "kickoff": "2026-10-11T15:00:00Z",
        }],
    }


def test_exact_full_booking_captures_original_price():
    quotes = wh.prepare_booked_quotes("2026-10-11", "10_odds", _record())
    assert len(quotes) == 1
    assert quotes[0]["phase"] == "BOOKED_PRICE"
    assert quotes[0]["provider"] == "SportyBet"
    assert quotes[0]["price"] == 1.42
    assert quotes[0]["event_id"] == "evt1"


def test_no_partial_accumulator_quotes():
    r = dict(_record(), booking_status="PARTIAL")
    assert wh.prepare_booked_quotes("2026-10-11", "10_odds", r) == []
    assert len(wh.prepare_booked_quotes("2026-10-11", "over_1_5", r)) == 1


def test_unknown_or_estimated_leg_price_is_not_recorded():
    r = _record()
    r["final_booked_legs"][0]["odds_are_real"] = False
    assert wh.prepare_booked_quotes("2026-10-11", "10_odds", r) == []
    r["final_booked_legs"][0]["odds_are_real"] = True
    r["final_booked_legs"][0]["odds"] = float("nan")
    assert wh.prepare_booked_quotes("2026-10-11", "10_odds", r) == []


def test_no_quote_when_fixture_already_started():
    r = _record()
    r["final_booked_legs"][0]["kickoff"] = "2026-10-11T07:50:00Z"
    assert wh.prepare_booked_quotes("2026-10-11", "10_odds", r) == []


def test_repeated_booking_capture_is_idempotent_and_keeps_clv_unavailable(monkeypatch):
    db = create_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(wh, "engine", db)
    try:
        r = _record()
        assert wh.capture_validated_booking("2026-10-11", "10_odds", r) == 1
        assert wh.capture_validated_booking("2026-10-11", "10_odds", r) == 1
        status = wh.warehouse_status()
        assert status["rows_by_phase"] == {"BOOKED_PRICE": 1}
        assert status["clv_ready"] is False
        assert status["closing_capture_implemented"] is False
    finally:
        db.dispose()


def _quote(price, phase="BOOKED_PRICE", at="2026-10-11T08:00:00Z"):
    return {
        "fixture_id": "m1", "event_id": "evt1",
        "market": "over_1_5", "provider": "SportyBet",
        "price": price, "phase": phase,
        "observed_at": at, "kickoff_at": "2026-10-11T15:00:00Z",
    }


def test_clv_unavailable_without_verified_close():
    assert wh.clv_comparison(_quote(1.42), None) == {
        "status": "MISSING_VERIFIED_CLOSING", "clv": None}
    assert wh.clv_comparison(None, _quote(1.36, "VERIFIED_CLOSING")) == {
        "status": "MISSING_BOOKED_PRICE", "clv": None}


def test_verified_clv_uses_same_market_bookmaker_and_true_chronology():
    close = _quote(1.36, "VERIFIED_CLOSING", "2026-10-11T14:40:00Z")
    result = wh.clv_comparison(_quote(1.42), close)
    assert result["status"] == "VERIFIED_CLOSING_AVAILABLE"
    assert result["clv"] == round(1.42 / 1.36 - 1.0, 6)
    mismatch = dict(close, market="over_2_5")
    assert wh.clv_comparison(_quote(1.42), mismatch)["clv"] is None
    after = dict(close, observed_at="2026-10-11T15:01:00Z")
    assert wh.clv_comparison(_quote(1.42), after)["clv"] is None
