"""Never leak a withheld or stale SportyBet share code via public API."""
import asyncio

from leagues import api as league_api
from leagues import booking as booking_module
from leagues import daily_feed


def _game():
    return {
        "match_id": "fixture-one",
        "home_team": "Home",
        "away_team": "Away",
        "market": "over_1_5",
        "odds": 1.45,
        "kickoff": "2099-12-01T16:00:00Z",
    }


def _stored(game, code="DO_NOT_EXPOSE"):
    return {
        "status": "active",
        "booking_status": "FULL",
        "share_code": code,
        "share_url": f"https://example.test/code/{code}",
        "detail": {"raw_code": code, "private_payload": "sensitive"},
        "readback_validation": "PASSED",
        "original_leg_count": 1,
        "booked_leg_count": 1,
        "excluded_leg_count": 0,
        "leg_fingerprint": booking_module.leg_fingerprint([game]),
        "expires_at": "2099-12-01T15:00:00Z",
    }


def _stub(monkeypatch, *, category, stored, card_day="2099-12-01"):
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: "2099-12-01")
    monkeypatch.setattr(
        daily_feed, "build_daily_accumulators",
        lambda **_: {
            "date": card_day,
            "accumulators": {"rollover": category},
        },
    )
    monkeypatch.setattr(
        booking_module, "bookings_for",
        lambda *_: {"rollover": stored},
    )


def test_public_endpoint_never_exposes_withheld_rollover_code(monkeypatch):
    game = _game()
    _stub(
        monkeypatch,
        category={
            "selected": False,
            "games": [],
            "result_status": "PUBLICATION_POLICY_BLOCKED",
        },
        stored=_stored(game),
    )
    output = asyncio.run(league_api.get_bookings())
    row = output["bookings"]["rollover"]
    assert output["count"] == 0
    assert row["actionable"] is False
    assert row["share_code"] is None
    assert row["share_url"] is None
    assert "DO_NOT_EXPOSE" not in repr(output)
    assert "private_payload" not in repr(output)


def test_public_endpoint_exposes_only_current_valid_code(monkeypatch):
    game = _game()
    _stub(
        monkeypatch,
        category={"selected": True, "games": [game]},
        stored=_stored(game, code="CURRENT123"),
    )
    result = asyncio.run(league_api.get_bookings())
    assert result["count"] == 1
    assert result["bookings"]["rollover"]["actionable"] is True
    assert result["bookings"]["rollover"]["share_code"] == "CURRENT123"
    assert "private_payload" not in repr(result)


def test_old_dates_cannot_resurface_expired_or_archived_codes(monkeypatch):
    game = _game()
    _stub(
        monkeypatch,
        category={"selected": True, "games": [game]},
        stored=_stored(game),
    )
    result = asyncio.run(league_api.get_bookings(date="2099-11-30"))
    assert result["count"] == 0
    assert result["bookings"]["rollover"]["share_code"] is None


def test_attachment_clears_stale_code_even_when_stored_rows_disappear(monkeypatch):
    monkeypatch.setattr(booking_module, "bookings_for", lambda *_: {})
    category = {
        "rollover": {
            "selected": False,
            "games": [],
            "booking": {"actionable": True, "share_code": "STALE"},
        }
    }
    booking_module.attach_bookings("2099-12-01", category)
    assert "booking" not in category["rollover"]
