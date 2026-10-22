"""Offline fixture paste validation: bookmaker network is never contacted."""
import sys
import types

import pytest

from growth.jackpot_paste import (
    match_fixture_lines, parse_fixture_lines, pasted_auto_book, pasted_preview,
)


def test_parses_uefa_copy_paste_and_keeps_home_away_order():
    data = parse_fixture_lines(
        "1. GNK Dinamo vs NEC Nijmegen\n"
        "2. FC Nordsjaelland vs CSKA Sofia | over 1.5\n"
        "- Kauno Žalgiris v Brann"
    )
    assert len(data) == 3
    assert data[1]["home_team"] == "FC Nordsjaelland"
    assert data[2]["away_team"] == "Brann"


@pytest.mark.parametrize("text", [
    "Arsenal to win",
    "Chelsea vs Chelsea",
    "Arsenal vs Chelsea\n1. Arsenal vs Chelsea",
    ("Real Madrid vs Barcelona\n" * 81),
])
def test_rejects_malformed_duplicate_or_oversized_input(text):
    with pytest.raises(ValueError):
        parse_fixture_lines(text)


def test_safe_matching_does_not_invent_nonexistent_fixtures():
    pasted = parse_fixture_lines(
        "Dinamo Zagreb vs NEC Nijmegen\n"
        "Ararat Armenia vs AZ Alkmaar"
    )
    choices = [
        {"match_id": "d", "selection_id": "d:over_1_5",
         "home_team": "GNK Dinamo Zagreb", "away_team": "NEC Nijmegen",
         "market": "over_1_5", "odds": 1.35},
    ]
    matched = match_fixture_lines(pasted, choices)
    assert len(matched["matched"]) == 1
    assert len(matched["unmatched"]) == 1
    assert matched["unmatched"][0]["reason"] == "NOT_APPROVED_ON_CURRENT_BOARD"


def test_paste_preview_auto_optimizes_only_from_matched_model_board(monkeypatch):
    import growth.private_jackpot as jackpot
    monkeypatch.setattr(jackpot, "candidate_board", lambda _:{
        "status": "success", "candidates": [
            {"match_id": "a", "selection_id": "a:away_win",
             "home_team": "Dinamo Zagreb", "away_team": "NEC Nijmegen",
             "market": "away_win", "odds": 2.1, "selection_probability": .70},
            {"match_id": "b", "selection_id": "b:over_1_5",
             "home_team": "Braga", "away_team": "Gent",
             "market": "over_1_5", "odds": 1.5, "selection_probability": .80},
        ]})
    result = pasted_preview({"fixtures_text":
        "Dinamo Zagreb vs NEC Nijmegen\nBraga vs Gent",
        "target_odds": 2.0, "max_legs": 2})
    assert result["matched_fixture_count"] == 2
    assert result["unmatched_fixture_count"] == 0
    assert result["status"] == "PROPOSED_NOT_BOOKED"
    assert result["bookmaker_code_created"] is False
    assert result["share_code"] is None
    assert all(x["match_id"] in ("a","b") for x in result["selected_games"])


def test_no_silent_dropping_of_pasted_fixtures_before_booking(monkeypatch):
    import growth.jackpot_paste as module
    monkeypatch.setattr(module, "pasted_preview", lambda _:{
        "status": "PROPOSED_NOT_BOOKED",
        "selection_ids": ["x:home_win"],
        "unmatched_fixture_count": 1,
        "unmatched": [{"home_team": "Missing", "away_team": "Unknown"}],
    })
    monkeypatch.setattr(sys.modules["growth.private_jackpot"], "booking_request",
                        lambda _: (_ for _ in ()).throw(AssertionError("must not book")))
    result = pasted_auto_book({"fixtures_text": "Missing vs Unknown"})
    assert result["status"] == "UNMATCHED_FIXTURES"
    assert result["share_code"] is None


def test_explicit_markets_and_reference_prices_are_parsed_without_trusting_price():
    lines = parse_fixture_lines(
        "1. Besiktas vs Crystal Palace | BTTS Yes @1.53\\n"
        "2. Braga vs Gent | Home win @1.81\\n"
        "3. Sturm Graz vs Marseille | 2 @2.14"
    )
    assert [x["requested_market"] for x in lines] == [
        "btts_yes", "home_win", "away_win"
    ]
    assert "odds" not in lines[0]


def test_unrecognized_market_is_rejected_not_silently_ignored():
    with pytest.raises(ValueError, match="unknown pick"):
        parse_fixture_lines("Ajax vs Atalanta | BTTS No @2.1")


def test_exact_picks_preserved_when_bookable(monkeypatch):
    import growth.private_jackpot as jackpot
    monkeypatch.setattr(jackpot, "candidate_board", lambda _:{
        "status": "success", "candidates": [
            {"match_id": "a", "selection_id": "a:btts_yes",
             "home_team": "Besiktas", "away_team": "Crystal Palace",
             "market": "btts_yes", "odds": 1.53,
             "selection_probability": .70},
            {"match_id": "a", "selection_id": "a:home_win",
             "home_team": "Besiktas", "away_team": "Crystal Palace",
             "market": "home_win", "odds": 2.20,
             "selection_probability": .70},
            {"match_id": "b", "selection_id": "b:home_win",
             "home_team": "Braga", "away_team": "Gent",
             "market": "home_win", "odds": 1.81,
             "selection_probability": .70},
        ]})
    result = pasted_preview({
        "fixtures_text": ("Besiktas vs Crystal Palace | BTTS Yes @1.53\\n"
                          "Braga vs Gent | Home win @1.81"),
        "target_odds": 2.0, "max_legs": 2,
    })
    assert result["status"] == "PROPOSED_NOT_BOOKED"
    assert result["selection_ids"] == ["a:btts_yes", "b:home_win"]
    assert result["portfolio_type"] == "USER_SUPPLIED_EXACT_MARKETS"
    assert result["exact_market_mode"] is True
    assert result["indicative_odds"] == pytest.approx(2.769, abs=1e-3)


def test_exact_market_unavailable_returns_diagnostic_and_never_substitutes(monkeypatch):
    import growth.private_jackpot as jackpot
    monkeypatch.setattr(jackpot, "candidate_board", lambda _:{
        "status": "success", "candidates": [
            {"match_id": "a", "selection_id": "a:home_win",
             "home_team": "Besiktas", "away_team": "Crystal Palace",
             "market": "home_win", "odds": 2.20,
             "selection_probability": .70},
        ]})
    result = pasted_preview({
        "fixtures_text": "Besiktas vs Crystal Palace | BTTS Yes @1.53",
        "target_odds": 2.0, "max_legs": 2,
    })
    assert result["status"] == "UNMATCHED_FIXTURES"
    assert not result["selection_ids"]
    assert result["unmatched"][0]["reason"] == "REQUESTED_MARKET_NOT_APPROVED"
    assert result["share_code"] is None


def test_mixed_exact_and_automatic_matches_are_rejected(monkeypatch):
    import growth.private_jackpot as jackpot
    monkeypatch.setattr(jackpot, "candidate_board", lambda _:{
        "status": "success", "candidates": []})
    with pytest.raises(ValueError, match="Every pasted line"):
        pasted_preview({
            "fixtures_text": ("Besiktas vs Crystal Palace | BTTS Yes @1.53\\n"
                              "Braga vs Gent"),
            "target_odds": 2.0, "max_legs": 2,
        })
