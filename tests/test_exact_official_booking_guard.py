"""Official booking must not advertise misleading partial or sub-target codes."""
from leagues import booking


def _leg(n):
    return {"match_id": f"fixture-{n}", "home_team": f"H{n}",
            "away_team": f"A{n}", "market": "over_1_5",
            "kickoff": "2099-01-01T12:00:00Z"}


def test_historical_7x_booking_is_not_attached_to_10x_card(monkeypatch):
    monkeypatch.setattr(booking, "bookings_for", lambda _: {
        "10_odds": {"status": "active", "booking_status": "PARTIAL",
                    "share_code": "PARTIAL_CODE", "actual_sportybet_odds": 7.107}
    })
    card = {"10_odds": {"selected": True, "games": [_leg(i) for i in range(7)],
                        "total_odds": 10.17}}
    result = booking.attach_bookings("2026-10-11", card)
    assert "booking" not in result["10_odds"]
    assert result["10_odds"]["selected"] is True
    assert result["10_odds"]["total_odds"] == 10.17


def test_under_10x_even_when_bookmaker_says_full_is_hidden(monkeypatch):
    monkeypatch.setattr(booking, "bookings_for", lambda _: {
        "10_odds": {"status": "active", "booking_status": "FULL",
                    "share_code": "FULL_BUT_9X",
                    "actual_sportybet_odds": 9.98}
    })
    card = {"10_odds": {"selected": True, "games": [_leg(i) for i in range(7)]}}
    booking.attach_bookings("2026-10-11", card)
    assert "booking" not in card["10_odds"]


def test_valid_full_10x_booking_reaches_lifecycle(monkeypatch):
    received = []
    monkeypatch.setattr(booking, "bookings_for", lambda _: {
        "10_odds": {"status": "active", "booking_status": "FULL",
                    "share_code": "TEN_EXACT",
                    "actual_sportybet_odds": 10.16}
    })
    monkeypatch.setattr(
        booking, "booking_lifecycle",
        lambda record, games, now=None, **kw: received.append(record["share_code"])
        or dict(record, actionable=True),
    )
    card = {"10_odds": {"selected": True, "games": [_leg(i) for i in range(7)]}}
    booking.attach_bookings("2026-10-11", card)
    assert received == ["TEN_EXACT"]
    assert card["10_odds"]["booking"]["actionable"]
