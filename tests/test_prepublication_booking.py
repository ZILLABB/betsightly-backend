from leagues import booking


def _game(match_id, odds=1.4):
    return {
        "match_id": match_id, "market": "over_1_5", "odds": odds,
        "confidence": .75, "selection_probability": .72,
        "home_team": f"Home {match_id}", "away_team": f"Away {match_id}",
    }


def test_full_rebuilt_booking_is_promoted_before_official_lock(monkeypatch):
    original = [_game("old-1"), _game("old-2")]
    final = [_game("old-1"), _game("replacement", 1.5)]
    accumulators = {
        "2_odds": {"selected": True, "games": original,
                   "total_odds": 1.96, "hit_probability": .52},
    }
    record = {
        "status": "active", "booking_status": "REBUILT_FULL",
        "share_code": "NEW123", "final_booked_legs": final,
        "replacements": [{"old": "old-2", "new": "replacement"}],
    }
    stored = []
    monkeypatch.setattr(booking, "book_card", lambda *_: {"booked": ["2_odds"]})
    monkeypatch.setattr(booking, "bookings_for", lambda *_: {"2_odds": record})
    monkeypatch.setattr(booking, "_store", lambda *args: stored.append(args))

    report = booking.finalize_prepublication_card("2026-09-10", accumulators)

    tier = accumulators["2_odds"]
    assert [game["match_id"] for game in tier["games"]] == [
        "old-1", "replacement"
    ]
    assert tier["prepublication_booking_status"] == "REBUILT_FULL"
    assert report["promoted_before_lock"] == ["2_odds"]
    normalized = stored[0][2]
    assert normalized["booking_status"] == "FULL"
    assert normalized["leg_fingerprint"] == normalized[
        "booking_variant_fingerprint"
    ]


def test_partial_booking_never_mutates_official_prediction(monkeypatch):
    original = [_game("old-1"), _game("old-2")]
    accumulators = {
        "5_odds": {"selected": True, "games": list(original),
                   "total_odds": 1.96, "hit_probability": .52},
    }
    monkeypatch.setattr(booking, "book_card", lambda *_: {"failed": ["5_odds"]})
    monkeypatch.setattr(booking, "bookings_for", lambda *_: {
        "5_odds": {"status": "active", "booking_status": "PARTIAL",
                   "final_booked_legs": [_game("old-1")]},
    })

    report = booking.finalize_prepublication_card("2026-09-10", accumulators)

    assert accumulators["5_odds"]["games"] == original
    assert report["promoted_before_lock"] == []
