"""Special SportyBet code import is opt-in and preserves bookmaker truth."""
import pytest

from leagues import editorial_manual as manual


@pytest.mark.parametrize(("market", "outcome", "expected", "feature"), [
    ("1X2 - 1UP", "3", "away_win", "1UP"),
    ("1X2 - 2UP", "1", "home_win", "2UP"),
    ("Double Chance - 1UP", "11", "away_or_draw", "1UP"),
    ("Over/Under - Early Goals", "12", "over_1_5", "EarlyGoals"),
])
def test_special_markets_require_explicit_conversion(market, outcome, expected, feature):
    choice = {"eventId": "sr:match:123", "marketId": "999",
              "marketName": market, "outcomeId": outcome,
              "specifier": "total=1.5" if feature == "EarlyGoals" else ""}
    with pytest.raises(ValueError, match="early-settlement variant"):
        manual._resolve_import_market(choice, convert_special=False)
    result, converted = manual._resolve_import_market(
        choice, convert_special=True
    )
    assert (result, converted) == (expected, feature)


def test_same_underlying_market_id_still_warns_when_1up_flagged():
    choice = {"eventId": "123", "marketId": "1", "outcomeId": "3",
              "specifier": "", "earlyPayoutType": "1UP"}
    with pytest.raises(ValueError, match="1UP"):
        manual._resolve_import_market(choice, convert_special=False)
    # Exact standard market IDs are independently verifiable.
    assert manual._resolve_import_market(
        choice, convert_special=True) == ("away_win", "1UP")


def test_plain_supported_markets_import_without_loss():
    assert manual._resolve_import_market({
        "eventId": "12", "marketId": "18", "specifier": "total=1.5",
        "outcomeId": "12",
    }, convert_special=False) == ("over_1_5", None)
    assert manual._resolve_import_market({
        "eventId": "13", "marketId": "1", "specifier": "",
        "outcomeId": "3",
    }, convert_special=False) == ("away_win", None)


def test_unknown_market_rejected_even_with_special_conversion_consent():
    with pytest.raises(ValueError, match="Unsupported market"):
        manual._resolve_import_market({
            "marketId": "unknown", "outcomeId": "123", "specifier": "",
        }, convert_special=True)


def test_early_goals_mismatched_total_line_fails_closed():
    with pytest.raises(ValueError, match="cannot be converted safely"):
        manual._resolve_import_market({
            "marketName": "Over/Under - Early Goals",
            "marketId": "999", "outcomeId": "12",
            "outcomeName": "Over 2.5", "specifier": "total=1.5",
        }, convert_special=True)


def test_import_share_code_requires_all_legs_and_discloses_changed_terms(monkeypatch):
    from leagues import booking, sportybet
    code_response = {
        "bizCode": 10000,
        "data": {"ticket": {"selections": [
            {"eventId": "123", "marketId": "999", "marketName": "1X2 - 1UP",
             "outcomeId": "3", "specifier": ""},
            {"eventId": "124", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"},
        ]}},
    }
    monkeypatch.setattr(booking, "_read_share", lambda code: code_response)
    monkeypatch.setattr(sportybet, "_board_entries", lambda board: [
        ("a", {"event_id": "123"}),
        ("b", {"event_id": "124"}),
    ])
    def fake_preview(tier, lines, *, board=None, **kwargs):
        assert tier == "2_odds"
        assert lines == "123,away_win\n124,over_1_5"
        return {
            "games": [{"market": "away_win"}, {"market": "over_1_5"}],
            "total_odds": 2.2,
        }
    monkeypatch.setattr(manual, "preview", fake_preview)

    with pytest.raises(ValueError, match="Event 123: 1UP"):
        manual.import_share_code("ABCDE", "2_odds", board={})
    report = manual.import_share_code(
        "ABCDE", "2_odds", board={}, convert_special=True
    )
    assert report["original_leg_count"] == 2
    assert report["lines"] == "123,away_win\n124,over_1_5"
    assert report["converted_features"] == [
        {"event_id": "123", "from": "1UP", "to": "away_win"}
    ]
    assert "NOT preserved" in report["note"]
    assert report["imported_share_code"] == "ABCDE"


def test_mixed_specials_do_not_silently_drop_unsupported_legs(monkeypatch):
    from leagues import booking, sportybet
    monkeypatch.setattr(booking, "_read_share", lambda code: {
        "bizCode": 10000,
        "data": {"ticket": {"selections": [
            {"eventId": "123", "marketId": "1", "outcomeId": "3"},
            {"eventId": "124", "marketId": "997", "outcomeId": "123",
             "marketName": "Unfamiliar Special"},
        ]}},
    })
    monkeypatch.setattr(sportybet, "_board_entries", lambda board: [
        ("x", {"event_id": "123"}), ("y", {"event_id": "124"}),
    ])
    monkeypatch.setattr(manual, "preview", lambda *a, **kw:
                        pytest.fail("Never preview or publish incomplete code"))
    with pytest.raises(ValueError, match="Event 124"):
        manual.import_share_code("ABC123", "2_odds", board={},
                                 convert_special=True)


def test_1up_bookmaker_outcome_label_cannot_contradict_outcome_id():
    with pytest.raises(ValueError, match="cannot be converted safely"):
        manual._resolve_import_market({
            "marketId": "999", "marketName": "1X2 - 1UP",
            "outcomeId": "1", "outcomeName": "Away",
        }, convert_special=True)


def test_early_goals_under_cannot_be_incorrectly_imported_as_over():
    with pytest.raises(ValueError, match="cannot be converted safely"):
        manual._resolve_import_market({
            "marketId": "999", "marketName": "Over/Under - Early Goals",
            "outcomeId": "12", "outcomeName": "Under 1.5",
            "specifier": "total=1.5",
        }, convert_special=True)


def test_bookmaker_text_conflict_rejected_even_if_standard_id_matches():
    with pytest.raises(ValueError, match="conflicts"):
        manual._resolve_import_market({
            "marketId": "1", "marketName": "1X2 - 1UP",
            "outcomeId": "1", "outcomeName": "Away",
        }, convert_special=True)
