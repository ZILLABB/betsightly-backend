"""Admin import review: never lose legs or silently guess special market outcomes."""
from unittest.mock import patch
from leagues import editorial_manual as manual


def share(*selections):
    return {
        "bizCode": 10000,
        "data": {"ticket": {
            "displayTotalOdds": "2.52",
            "selections": list(selections),
        }},
    }


def test_unknown_promotional_market_is_retained_for_explicit_admin_review():
    result = share(
        {"eventId": "sr:match:74165922", "marketId": "promo:unknown",
         "outcomeId": "bonus:weird", "marketName": "EarlyGoals: 1 goal by 10 min",
         "outcomeName": "Over 1.5"},
        {"eventId": "sr:match:74165923", "marketId": "18",
         "specifier": "total=1.5", "outcomeId": "12"},
        {"eventId": "sr:match:74165924", "marketId": "1",
         "specifier": "", "outcomeId": "3"},
    )
    with patch("leagues.booking._read_share", return_value=result):
        report = manual.import_share_code(
            "TESTPROMO", "2_odds",
            convert_special=True, allow_review=True,
        )
    assert report["status"] == "NEEDS_MANUAL_REVIEW"
    assert report["publish_ready"] is False
    assert report["booking_code_created"] is False
    assert report["live_prices_verified"] is False
    assert report["original_leg_count"] == 3
    assert len(report["games"]) == 3
    assert report["unresolved_count"] == 1
    assert report["unresolved_selections"][0]["sportybet_event_id"] == "sr:match:74165922"
    assert report["unresolved_selections"][0]["market"] is None
    assert report["unresolved_selections"][0]["requires_review"] is True
    assert report["games"][1]["market"] == "over_1_5"
    assert report["games"][2]["market"] == "away_win"
    assert report["lines"] == (
        "sr:match:74165923,over_1_5\n"
        "sr:match:74165924,away_win"
    )
    assert any("No selection has been dropped" in w for w in report["warnings"])


def test_no_explicit_consent_still_rejects_unknown_promotional_markets():
    with patch("leagues.booking._read_share", return_value=share({
        "eventId": "sr:match:74165922", "marketId": "unmapped",
        "outcomeId": "unmapped",
    })):
        import pytest
        with pytest.raises(ValueError, match="Unsupported market"):
            manual.import_share_code("TESTPROMO", "2_odds",
                                     convert_special=True, allow_review=False)


def test_known_special_converts_and_unknown_one_requires_review():
    data = share(
        {"eventId": "sr:match:1", "marketId": "999",
         "marketName": "1X2 - 1UP", "outcomeId": "3"},
        {"eventId": "sr:match:2", "marketId": "299",
         "marketName": "EarlyGoals: 1 goal by 10 min", "outcomeId": "special"},
    )
    with patch("leagues.booking._read_share", return_value=data):
        report = manual.import_share_code("TESTPROMO", "2_odds",
                                          convert_special=True, allow_review=True)
    assert report["games"][0]["market"] == "away_win"
    assert report["converted_features"][0]["from"] == "1UP"
    assert report["games"][1]["requires_review"] is True
    assert report["original_leg_count"] == 2
    assert report["unresolved_count"] == 1


def test_ambiguity_is_never_silently_switched_to_winning_outcome():
    data = share({
        "eventId": "sr:match:74165922", "marketId": "101",
        "marketName": "1X2 - 1UP", "outcomeId": "1", "outcomeName": "Away",
    })
    with patch("leagues.booking._read_share", return_value=data):
        report = manual.import_share_code(
            "TESTPROMO", "banker", convert_special=True,
            allow_review=True,
        )
    assert report["status"] == "NEEDS_MANUAL_REVIEW"
    assert report["unresolved_count"] == 1
    assert report["games"][0]["market"] is None
    assert report["games"][0]["bookable"] is False


def test_user_interface_preserves_editor_and_blocks_partial_publication():
    from growth.admin_ui import HTML
    assert "manualImportReview=d" in HTML
    assert "manualApplyImportReview" in HTML
    assert "manualCancelImportReview" in HTML
    assert "if(manualImportReview)" in HTML
    assert "Original early payouts are NOT preserved" in HTML
    assert "Your previous manual selections are unchanged" in HTML
    assert "manualImportReview=null;" in HTML
