"""Regression: EarlyGoals is not an ordinary 90-minute Over market.

SportyBet offers EarlyGoals as a betslip toggle as well as a named special
market. The editor may safely prepare an ordinary-market replacement only
with explicit consent; it must never fake an early-payout code or drop legs.
"""
from unittest.mock import patch

import pytest

from leagues import editorial_manual as editor


def four_leg_ticket(**ticket_options):
    # Mirrors the categories in the customer's screen, not real current fixtures.
    return {
        "bizCode": 10000, "data": {"ticket": {
            "displayTotalOdds": "2.52",
            "selections": [
                {"eventId": "1001", "marketId": "18",
                 "specifier": "total=1.5", "outcomeId": "12",
                 "marketName": "Over/Under", "outcomeName": "Over 1.5"},
                {"eventId": "1002", "marketId": "18",
                 "specifier": "total=1.5", "outcomeId": "12",
                 "marketName": "Over/Under", "outcomeName": "Over 1.5"},
                {"eventId": "1003", "marketId": "1",
                 "specifier": "", "outcomeId": "3",
                 "marketName": "1X2", "outcomeName": "Away"},
                {"eventId": "1004", "marketId": "1",
                 "specifier": "", "outcomeId": "3",
                 "marketName": "1X2", "outcomeName": "Away"},
            ],
            **ticket_options,
        }},
    }


def test_regular_four_leg_ticket_with_unselected_earlygoals_advert_imports():
    payload = four_leg_ticket(earlyGoals={"eligible": True, "selected": False})
    with patch("leagues.booking._read_share", return_value=payload):
        report = editor.import_share_code("TESTCODE", "2_odds")
    assert report["status"] == "IMPORTED_NOT_PUBLISHED"
    assert report["original_leg_count"] == 4
    assert report["lines"].splitlines() == [
        "1001,over_1_5", "1002,over_1_5",
        "1003,away_win", "1004,away_win",
    ]
    assert report["converted_features"] == []
    assert report["booking_code_created"] is False
    assert report["publish_ready"] is False


def test_activated_ticket_level_earlygoals_requires_consent():
    payload = four_leg_ticket(betOptions={"earlyGoals": {"selected": True}})
    with patch("leagues.booking._read_share", return_value=payload):
        with pytest.raises(ValueError, match="activated EarlyGoals"):
            editor.import_share_code("TESTCODE", "2_odds")
        converted = editor.import_share_code(
            "TESTCODE", "2_odds", convert_special=True
        )
    assert converted["original_leg_count"] == 4
    assert len(converted["lines"].splitlines()) == 4
    assert converted["converted_features"] == [{
        "event_id": "TICKET", "from": "EarlyGoals",
        "to": "ordinary 90-minute markets", "scope": "ticket",
    }]
    assert any("NOT preserved" in w for w in converted["warnings"])
    assert converted["booking_code_created"] is False
    assert converted["publish_ready"] is False


def test_boolean_selection_level_earlygoals_requires_explicit_conversion():
    payload = four_leg_ticket()
    payload["data"]["ticket"]["selections"][0]["isEarlyGoals"] = True
    with patch("leagues.booking._read_share", return_value=payload):
        with pytest.raises(ValueError, match="EarlyGoals"):
            editor.import_share_code("TESTCODE", "2_odds")
        changed = editor.import_share_code(
            "TESTCODE", "2_odds", convert_special=True
        )
    assert changed["converted_features"][0]["event_id"] == "1001"
    assert changed["converted_features"][0]["to"] == "over_1_5"
    assert len(changed["lines"].splitlines()) == 4


def test_early_goals_by_ten_minutes_without_regular_line_never_guessed():
    payload = four_leg_ticket()
    payload["data"]["ticket"]["selections"][0] = {
        "eventId": "1001", "marketId": "NON_STANDARD",
        "specifier": "", "outcomeId": "12",
        "marketName": "EarlyGoals: 1 goal by 10 min",
        "outcomeName": "Yes",
    }
    with patch("leagues.booking._read_share", return_value=payload):
        with pytest.raises(ValueError, match="cannot be converted safely"):
            editor.import_share_code(
                "TESTCODE", "2_odds", convert_special=True
            )
        review = editor.import_share_code(
            "TESTCODE", "2_odds", convert_special=True, allow_review=True,
        )
    assert review["status"] == "NEEDS_MANUAL_REVIEW"
    assert review["original_leg_count"] == 4
    assert review["unresolved_count"] == 1
    assert review["games"][0]["requires_review"] is True
    assert len(review["lines"].splitlines()) == 3
    assert review["publish_ready"] is False


def test_advertised_but_not_activated_ticket_option_does_not_trigger():
    payload = four_leg_ticket(promotions={
        "earlyGoals": {"available": True, "eligible": True, "selected": False}
    })
    with patch("leagues.booking._read_share", return_value=payload):
        parsed = editor.import_share_code("TESTCODE", "2_odds")
    assert parsed["converted_features"] == []
