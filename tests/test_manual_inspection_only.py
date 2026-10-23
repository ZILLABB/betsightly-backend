"""Regression tests for price inspection of occupied manual tiers.

Inspection must never become a shortcut around publication guards.
"""
from datetime import datetime, timezone

import pytest

from leagues import editorial_manual as editor


def test_occupied_tier_can_be_inspected_but_never_published(monkeypatch):
    from leagues import booking, picks_db, sportybet

    at = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)
    upcoming = int(datetime(2026, 10, 21, 16, tzinfo=timezone.utc).timestamp() * 1000)
    board = {
        "sports": [
            {"event_id": eid, "home_team": "Alpha " + eid,
             "away_team": "Beta " + eid, "competition": "Inspection Tests",
             "kickoff_ms": upcoming, "prices": {"home_win": 2.4}}
            for eid in ("52587", "52588")
        ]
    }
    monkeypatch.setattr(picks_db, "load_card",
                        lambda day: {"2_odds": {"selected": True}})
    monkeypatch.setattr(editor, "list_published",
                        lambda day: {"2_odds": {"games": [], "booking": {"share_code": "EXIST"}}})
    monkeypatch.setattr(booking, "bookings_for", lambda day: {})
    monkeypatch.setattr(sportybet, "fetch_board", lambda **kw: board)
    monkeypatch.setattr(sportybet, "availability_for",
                        lambda board, home, away, kickoff, league, market, event_id=None:
                        {"sportybet_available": True, "sportybet_odds": 2.4,
                         "event_id": event_id})
    monkeypatch.setattr(booking, "create_booking",
                        lambda *a, **kw: pytest.fail("inspection created booking"))

    lines = "52587,home_win\\n52588,home_win".replace("\\n", "\n")
    inspected = editor.preview("2_odds", lines, board=board, now=at,
                               inspection_only=True)
    assert inspected["status"] == "INSPECTION_ONLY"
    assert inspected["publish_ready"] is False
    assert inspected["booking_code_created"] is False
    assert inspected["research_only"] is True
    assert len(inspected["games"]) == 2
    assert inspected["total_odds"] == 5.76

    with pytest.raises(ValueError, match="immutable official"):
        editor.preview("2_odds", lines, board=board, now=at)
    with pytest.raises(ValueError, match="published manual slip"):
        editor.preview("2_odds", lines, board=board, now=at,
                       replace_official_display=True)
    with pytest.raises(ValueError, match="published manual slip"):
        editor.publish("2_odds", lines, replace_official_display=True)
