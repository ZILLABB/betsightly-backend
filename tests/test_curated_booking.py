"""The curated admin route refuses inaccurate or unsafe booking codes."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from leagues import curated_booking as cb
from leagues import booking, sportybet


def _leg(home="Sparta Prague", away="Lillestrøm",
         market="over_1_5", hours=12):
    return cb.CuratedBookingLeg(
        home_team=home, away_team=away, league="UEFA Europa League",
        kickoff=datetime.now(timezone.utc) + timedelta(hours=hours),
        market=market,
    )


def _board(complete=True):
    return {"__meta__": {"is_complete": complete, "snapshot_id": "audit-snap"}}


def _patch_board(monkeypatch, complete=True):
    monkeypatch.setattr(sportybet, "fetch_board",
                        lambda force=False: _board(complete))
    monkeypatch.setattr(sportybet, "board_metadata",
                        lambda board: board["__meta__"])


def test_key_is_mandatory_even_when_environment_is_development(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        cb.require_curated_booking_key(None)
    assert exc.value.status_code == 503


def test_unsupported_under_is_rejected_before_any_network(monkeypatch):
    monkeypatch.setattr(sportybet, "fetch_board",
                        lambda **kwargs: pytest.fail("must not fetch board"))
    result = cb.generate_curated_booking(
        cb.CuratedBookingRequest(legs=[_leg(market="under_3_5")]))
    assert result["share_code"] is None
    assert result["failures"][0]["reason"] == "unsupported_market"


def test_duplicate_fixture_is_rejected_even_for_different_market(monkeypatch):
    monkeypatch.setattr(sportybet, "fetch_board",
                        lambda **kwargs: pytest.fail("must not fetch board"))
    result = cb.generate_curated_booking(cb.CuratedBookingRequest(
        legs=[_leg(), _leg(market="over_2_5")]))
    assert result["share_code"] is None
    assert result["failures"][0]["reason"] == "duplicate_fixture"


def test_no_code_on_incomplete_bookmaker_board(monkeypatch):
    _patch_board(monkeypatch, complete=False)
    result = cb.generate_curated_booking(cb.CuratedBookingRequest(
        legs=[_leg()]))
    assert result["status"] == "unavailable"
    assert result["reason"] == "sportybet_board_incomplete"
    assert result["share_code"] is None


def test_all_or_nothing_on_single_missing_selection(monkeypatch):
    _patch_board(monkeypatch)
    def fake_availability(board, home, away, kickoff, league, market):
        if home == "Sparta Prague":
            return {"sportybet_available": True, "event_id": "event-one",
                    "market_id": "18", "specifier": "total=1.5",
                    "outcome_id": "12", "sportybet_odds": 1.2}
        return {"sportybet_available": False, "status": "MARKET_NOT_FOUND"}
    monkeypatch.setattr(sportybet, "availability_for", fake_availability)
    monkeypatch.setattr(booking, "create_or_reuse_generated_booking",
                        lambda *args, **kwargs: pytest.fail("must not post"))
    result = cb.generate_curated_booking(cb.CuratedBookingRequest(
        legs=[_leg(), _leg(home="Gent", away="Aarhus")]))
    assert result["share_code"] is None
    assert result["failures"][0]["leg"] == 2


def test_exact_validated_full_slip_returned(monkeypatch):
    _patch_board(monkeypatch)
    def fake_availability(board, home, away, kickoff, league, market):
        return {"sportybet_available": True,
                "event_id": "event-" + home,
                "market_id": "18", "specifier": "total=1.5",
                "outcome_id": "12", "sportybet_odds": 1.25}
    monkeypatch.setattr(sportybet, "availability_for", fake_availability)
    def fake_booking(games, board):
        assert len(games) == 2
        assert all(g["sportybet_availability"]["sportybet_available"]
                   for g in games)
        return {"status": "active", "share_code": "SAMPLE12",
                "share_url": "https://www.sportybet.com/ng/?shareCode=SAMPLE12",
                "readback_validation": "PASSED", "booking_status": "FULL",
                "booked_leg_count": 2, "partial": False,
                "actual_sportybet_odds": 1.5625,
                "expires_at": (datetime.now(timezone.utc)
                               + timedelta(hours=6)).isoformat()}
    monkeypatch.setattr(booking, "create_or_reuse_generated_booking", fake_booking)
    result = cb.generate_curated_booking(cb.CuratedBookingRequest(
        legs=[_leg(), _leg(home="Gent", away="Aarhus")]))
    assert result["status"] == "success"
    assert result["readback_validation"] == "PASSED"
    assert result["legs"] == 2
    assert result["share_code"] == "SAMPLE12"


def test_readback_failure_never_exposes_code(monkeypatch):
    _patch_board(monkeypatch)
    monkeypatch.setattr(sportybet, "availability_for", lambda *args: {
        "sportybet_available": True, "event_id": "e1",
        "market_id": "18", "specifier": "total=1.5", "outcome_id": "12",
        "sportybet_odds": 1.25,
    })
    monkeypatch.setattr(booking, "create_or_reuse_generated_booking",
                        lambda games, board: {
                            "status": "invalid", "share_code": "BADCODE",
                            "readback_validation": "FAILED",
                            "failure_category": "READBACK_MISMATCH",
                        })
    result = cb.generate_curated_booking(cb.CuratedBookingRequest(
        legs=[_leg()]))
    assert result["status"] == "unavailable"
    assert result["share_code"] is None
