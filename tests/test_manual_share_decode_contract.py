"""Manual share-code import should be fast, complete, and strictly read-only."""
import pytest
from leagues import editorial_manual as M


def _code(*selections, total="2.52", unavailable=None):
    return {"bizCode": 10000, "data": {
        "ticket": {
            "selections": list(selections),
            "displayTotalOdds": total,
        },
        "unavailableOutcomes": unavailable or [],
    }}


def _selection(event, market_id, specifier, outcome_id):
    return {"eventId": event, "marketId": market_id,
            "specifier": specifier, "outcomeId": outcome_id}


def _example():
    return _code(
        _selection("sr:match:1", "18", "total=1.5", "12"),
        _selection("sr:match:2", "18", "total=1.5", "12"),
        _selection("sr:match:3", "1", "", "3"),
        _selection("sr:match:4", "1", "", "3"),
    )


def test_mixed_252_sportybet_code_imports_into_two_odds_without_board_or_preview(monkeypatch):
    from leagues import booking, sportybet
    monkeypatch.setattr(booking, "_read_share", lambda code: _example())
    monkeypatch.setattr(sportybet, "fetch_board", lambda **kw:
                        pytest.fail("Import cannot start a full bookmaker board scan"))
    monkeypatch.setattr(M, "preview", lambda *a, **kw:
                        pytest.fail("Import must not enforce publishing requirements"))
    report = M.import_share_code("EXAMPLE", "2_odds")
    assert report["status"] == "IMPORTED_NOT_PUBLISHED"
    assert report["lines"] == ("sr:match:1,over_1_5\n"
                               "sr:match:2,over_1_5\n"
                               "sr:match:3,away_win\n"
                               "sr:match:4,away_win")
    assert report["total_odds"] == 2.52
    assert report["publish_ready"] is False
    assert report["live_prices_verified"] is False
    assert report["warnings"] == []


def test_import_can_report_tier_mismatch_without_rejecting_valid_code(monkeypatch):
    from leagues import booking
    monkeypatch.setattr(booking, "_read_share", lambda code: _example())
    report = M.import_share_code("EXAMPLE", "5_odds")
    assert len(report["games"]) == 4
    assert any("below" in w for w in report["warnings"])
    report = M.import_share_code("EXAMPLE", "over_1_5")
    assert any("accepts only" in w for w in report["warnings"])


def test_early_goals_remains_explicit_consent_only(monkeypatch):
    from leagues import booking
    fixture = _selection("sr:match:7", "999", "total=1.5", "12")
    fixture["marketName"] = "Over/Under - Early Goals"
    monkeypatch.setattr(booking, "_read_share", lambda code:
                        _code(fixture, total="1.30"))
    with pytest.raises(ValueError, match="early-settlement variant"):
        M.import_share_code("EXAMPLE", "banker")
    report = M.import_share_code("EXAMPLE", "banker",
                                 convert_special=True)
    assert report["lines"] == "sr:match:7,over_1_5"
    assert report["converted_features"][0]["from"] == "EarlyGoals"
    assert report["publish_ready"] is False
    assert "NOT preserved" in report["note"]


def test_duplicate_and_unknown_markets_fail_closed_and_never_drop_leg(monkeypatch):
    from leagues import booking
    monkeypatch.setattr(booking, "_read_share", lambda code: _code(
        _selection("sr:match:1", "18", "total=1.5", "12"),
        _selection("sr:match:1", "1", "", "3"),
    ))
    with pytest.raises(ValueError, match="more than once"):
        M.import_share_code("EXAMPLE", "2_odds")
    monkeypatch.setattr(booking, "_read_share", lambda code: _code(
        _selection("sr:match:1", "18", "total=1.5", "12"),
        _selection("sr:match:2", "999", "", "999"),
    ))
    with pytest.raises(ValueError, match="Event sr:match:2"):
        M.import_share_code("EXAMPLE", "2_odds")


def test_markets_marked_unavailable_import_for_inspection_but_not_publication(monkeypatch):
    from leagues import booking
    monkeypatch.setattr(booking, "_read_share", lambda code: _code(
        _selection("sr:match:1", "18", "total=1.5", "12"),
        unavailable=[{"eventId": "sr:match:1"}]
    ))
    result = M.import_share_code("EXAMPLE", "banker")
    assert len(result["games"]) == 1
    assert result["publish_ready"] is False
    assert any("unavailable" in warning for warning in result["warnings"])
