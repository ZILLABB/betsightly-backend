"""A readable SportyBet share code must import even when publication is blocked."""
import pytest
from leagues import editorial_manual as editor
from leagues import booking


def payload(*choices, odds="2.52", unavailable=None):
    selections = [
        {"eventId": e, "marketId": m, "specifier": spec, "outcomeId": outcome}
        for e, m, spec, outcome in choices
    ]
    return {"bizCode": 10000, "data": {
        "ticket": {"selections": selections, "displayTotalOdds": odds},
        "unavailableOutcomes": unavailable or [],
    }}


def _four_leg_code():
    # Two Over 1.5 goals and two Away wins, exactly as in screenshot.
    return payload(
        ("sr:match:1", "18", "total=1.5", "12"),
        ("sr:match:2", "18", "total=1.5", "12"),
        ("sr:match:3", "1", "", "3"),
        ("sr:match:4", "1", "", "3"),
    )


def test_valid_252x_booking_imports_for_2_odds_without_fetching_large_live_board(monkeypatch):
    monkeypatch.setattr(booking, "_read_share", lambda code: _four_leg_code())
    # Publication validation and board calls must not run at import time.
    monkeypatch.setattr(editor, "preview", lambda *a, **kw:
                        (_ for _ in ()).throw(AssertionError("preview should not run")))
    result = editor.import_share_code("DEMO252", "2_odds")
    assert result["status"] == "IMPORTED_NOT_PUBLISHED"
    assert result["total_odds"] == 2.52
    assert result["lines"] == (
        "sr:match:1,over_1_5\n"
        "sr:match:2,over_1_5\n"
        "sr:match:3,away_win\n"
        "sr:match:4,away_win"
    )
    assert result["publish_ready"] is False
    assert result["live_prices_verified"] is False
    assert result["warnings"] == []


def test_valid_code_imports_even_when_selected_tier_does_not_meet_minimum(monkeypatch):
    monkeypatch.setattr(booking, "_read_share", lambda code: _four_leg_code())
    result = editor.import_share_code("DEMO252", "5_odds")
    assert result["lines"]
    assert any("below" in w for w in result["warnings"])
    assert result["publish_ready"] is False


def test_mixed_ticket_imports_with_clear_warning_for_over15_only_tier(monkeypatch):
    monkeypatch.setattr(booking, "_read_share", lambda code: _four_leg_code())
    result = editor.import_share_code("DEMO252", "over_1_5")
    assert len(result["games"]) == 4
    assert any("only Over 1.5" in w for w in result["warnings"])


def test_unavailable_market_can_be_decoded_but_never_silently_booked(monkeypatch):
    monkeypatch.setattr(booking, "_read_share", lambda code:
        payload(("sr:match:1", "18", "total=1.5", "12"),
                unavailable=[{"eventId": "sr:match:1"}]))
    result = editor.import_share_code("DEMO123", "banker")
    assert result["publish_ready"] is False
    assert any("unavailable" in w for w in result["warnings"])


def test_unsupported_earlygoals_addon_rejected_without_dropping_a_leg(monkeypatch):
    monkeypatch.setattr(booking, "_read_share", lambda code: payload(
        ("sr:match:1", "18", "total=1.5", "12"),
        ("sr:match:2", "9999", "earlygoal=10", "999"),
    ))
    with pytest.raises(ValueError, match="unsupported SportyBet market or add-on"):
        editor.import_share_code("DEMO123", "2_odds")


def test_duplicate_fixture_and_nonexistent_code_are_rejected(monkeypatch):
    monkeypatch.setattr(booking, "_read_share", lambda code: payload(
        ("sr:match:1", "18", "total=1.5", "12"),
        ("sr:match:1", "1", "", "3"),
    ))
    with pytest.raises(ValueError, match="repeats"):
        editor.import_share_code("DEMO123", "2_odds")
    monkeypatch.setattr(booking, "_read_share",
                        lambda code: {"bizCode": 9999, "data": {}})
    with pytest.raises(ValueError, match="did not recognize"):
        editor.import_share_code("DEMO123", "2_odds")


def test_share_code_readback_error_does_not_mint_fake_import(monkeypatch):
    def fail(code):
        raise TimeoutError()
    monkeypatch.setattr(booking, "_read_share", fail)
    with pytest.raises(ValueError, match="timed out or failed"):
        editor.import_share_code("DEMO123", "2_odds")
