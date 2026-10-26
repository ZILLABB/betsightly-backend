"""Exact pasted basketball picks must never become different bookmaker selections."""
import time

import pytest

from growth import basketball_jackpot as bj
from growth import basketball_paste as bp


def board(extra=None):
    event = {
        "event_id": "sr:match:1001", "home_team": "Boston Celtics",
        "away_team": "New York Knicks",
        "competition": "NBA", "kickoff_ms": int((time.time() + 3600) * 1000),
        "markets": [
            {"market_id": "219", "specifier": "", "outcomes": [
                {"outcome_id": "4", "odds": 1.6, "label": "Boston Celtics"},
                {"outcome_id": "5", "odds": 2.6, "label": "New York Knicks"}]},
            {"market_id": "225", "specifier": "total=221.5", "outcomes": [
                {"outcome_id": "12", "odds": 2.2, "label": "Over 221.5"},
                {"outcome_id": "13", "odds": 1.72, "label": "Under 221.5"}]},
        ],
    }
    return {"fetched_at": time.time(), "metadata": {
        "schema": bj.SCHEMA, "snapshot_id": "fixture-board", "is_complete": True,
    }, "fixtures": [event] + (extra or [])}


def request(text, target=2):
    return {"fixtures_text": text, "target_odds": target}


@pytest.mark.parametrize("line,mid,oid,spec", [
    ("Boston Celtics vs New York Knicks | Home win", "219", "4", ""),
    ("Boston Celtics vs New York Knicks | Away win", "219", "5", ""),
    ("Boston Celtics vs New York Knicks | Over 221.5", "225", "12", "total=221.5"),
    ("Boston Celtics vs New York Knicks | Under 221.5 @1.72", "225", "13", "total=221.5"),
])
def test_exact_markets_and_ignored_pasted_prices(line, mid, oid, spec):
    report, resolved = bp.resolve(request(line), board())
    assert report["status"] in {"PROPOSED_NOT_BOOKED", "BELOW_TARGET"}
    assert resolved["selections"][0] == {
        "event_id": "sr:match:1001", "market_id": mid,
        "outcome_id": oid, "specifier": spec,
    }


def test_rejects_nonexistent_line_without_substituting_or_booking(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", board)
    posted = []
    monkeypatch.setattr(bj.booking, "_post_share", lambda legs: posted.append(legs))
    p = bp.preview(request("Boston Celtics vs New York Knicks | Over 225.5"))
    assert p["status"] == "EXACT_MARKETS_UNAVAILABLE"
    assert p["unmatched"][0]["reason"] == "EXACT_MARKET_UNAVAILABLE"
    assert bp.book(request("Boston Celtics vs New York Knicks | Over 225.5"))["share_code"] is None
    assert posted == []


def test_rejects_duplicates_and_ambiguous_fixtures():
    text = "Boston Celtics vs New York Knicks | Home win\nBoston Celtics vs New York Knicks | Over 221.5"
    report, _ = bp.resolve(request(text), board())
    assert report["status"] == "EXACT_MARKETS_UNAVAILABLE"
    assert report["unmatched"][0]["reason"] == "DUPLICATE_FIXTURE"
    extra = dict(board()["fixtures"][0], event_id="sr:match:other")
    report, _ = bp.resolve(request("Boston Celtics vs New York Knicks | Home win"), board([extra]))
    assert report["unmatched"][0]["reason"] == "FIXTURE_AMBIGUOUS"


def test_mixed_valid_and_invalid_ticket_fails_closed():
    report, resolved = bp.resolve(request(
        "Boston Celtics vs New York Knicks | Home win\nFake Club vs Other Team | Away win"), board())
    assert resolved is None
    assert report["status"] == "EXACT_MARKETS_UNAVAILABLE"
    assert report["matched_fixture_count"] == 1
    assert report["pasted_fixture_count"] == 2
    assert report["full_ticket_complete"] is False


def test_no_cached_board_disables_paste_booking(monkeypatch):
    monkeypatch.setattr(bj, "cached_board", lambda: None)
    assert bp.preview(request("Boston Celtics vs New York Knicks | Home win"))["status"] == "BOARD_REFRESH_REQUIRED"
    assert bp.book(request("Boston Celtics vs New York Knicks | Home win"))["share_code"] is None


def test_paste_limit_and_invalid_selection():
    with pytest.raises(ValueError):
        bp._parse("X vs Y | Home win\n" * 51)
    report, resolved = bp.resolve(request("Boston Celtics vs New York Knicks | First quarter handicap +3.5"), board())
    assert resolved is None
    assert report["unmatched"][0]["reason"] == "UNSUPPORTED_MARKET"


def test_missing_pasted_fixture_identifies_actual_board_names_without_substitution():
    report, resolved = bp.resolve(request(
        "Boston Celtics vs Philadelphia 76ers | Home win"), board())
    assert resolved is None
    error = report["unmatched"][0]
    assert error["reason"] == "FIXTURE_NOT_ON_BOARD"
    assert "Boston Celtics vs New York Knicks" in error["detail"]
    assert report["matched_fixture_count"] == 0
    assert report["share_code"] is None


def test_reversed_home_away_does_not_flip_moneyline():
    report, resolved = bp.resolve(request(
        "New York Knicks vs Boston Celtics | Home win"), board())
    assert resolved is None
    assert report["unmatched"][0]["reason"] == "FIXTURE_NOT_ON_BOARD"
    assert "reverse" in report["unmatched"][0]["detail"]
    assert report["full_ticket_complete"] is False


def test_matching_fixture_that_already_started_is_not_called_not_found():
    fixture = dict(board()["fixtures"][0],
                   kickoff_ms=int((time.time() - 60) * 1000))
    report, _ = bp.resolve(request(
        "Boston Celtics vs New York Knicks | Away win"), board([fixture]) | {
            "fixtures": [fixture],
        })
    assert report["unmatched"][0]["reason"] == "FIXTURE_NOT_ELIGIBLE"
    assert "ten minutes" in report["unmatched"][0]["detail"]


def test_unsupported_basketball_market_explains_available_market_types():
    report, _ = bp.resolve(request(
        "Boston Celtics vs New York Knicks | First half Over 110.5"), board())
    error = report["unmatched"][0]
    assert error["reason"] == "UNSUPPORTED_MARKET"
    assert "moneyline" in error["detail"]
    assert "full-game" in error["detail"]


def test_exact_points_line_missing_provides_no_substitution():
    report, resolved = bp.resolve(request(
        "Boston Celtics vs New York Knicks | Over 235.5"), board())
    assert resolved is None
    assert report["unmatched"][0]["reason"] == "EXACT_MARKET_UNAVAILABLE"
    assert "not active" in report["unmatched"][0]["detail"]
    assert report["share_code"] is None
