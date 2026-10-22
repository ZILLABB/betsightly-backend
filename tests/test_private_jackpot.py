"""Unit tests for the authenticated private jackpot service (no network calls)."""
import sys
import types

import pytest

from growth.private_jackpot import booking_request, candidate_board, filters_for


def _rows():
    return [
        dict(selection_id="event-a:over_1_5", match_id="a", home_team="A",
             away_team="B", market="over_1_5", odds=2.0, bookable=True,
             trust_grade="B", selection_probability=.69),
        dict(selection_id="event-b:home_win", match_id="b", home_team="C",
             away_team="D", market="home_win", odds=2.1, bookable=True,
             trust_grade="A", selection_probability=.75),
        dict(selection_id="event-a:under_2_5", match_id="a", home_team="A",
             away_team="B", market="under_2_5", odds=3.0, bookable=True),
    ]


@pytest.fixture
def stub_builder(monkeypatch):
    calls = []
    module = types.ModuleType("leagues.builder_v2")
    def list_candidates(opts):
        calls.append(("candidates", opts))
        return {"status": "success", "candidates": _rows(), "board": {"ready": True}}
    def manual_build(opts):
        calls.append(("book", opts))
        return {
            "status": "success", "estimated_all_leg_probability": .52,
            "booking": {
                "status": "active", "booking_status": "FULL",
                "booked_leg_count": 2, "readback_validation": "PASSED",
                "actual_sportybet_odds": 4.2, "share_code": "EXAMPLE",
                "share_url": "https://example.test", "expires_at": "2026-10-22T19:00:00Z",
            },
        }
    module.list_candidates = list_candidates
    module.manual_build = manual_build
    monkeypatch.setitem(sys.modules, "leagues.builder_v2", module)
    return calls


def test_under_goals_are_excluded_and_never_booked(stub_builder):
    candidates = candidate_board({"horizon": "today"})
    assert candidates["status"] == "success"
    assert len(candidates["candidates"]) == 2
    assert all(not x["market"].startswith("under_") for x in candidates["candidates"])
    rejected = booking_request({"selection_ids": ["event-a:under_2_5"]})
    assert rejected["status"] == "SELECTIONS_CHANGED"
    assert not any(name == "book" for name, _ in stub_builder)


def test_requires_current_exact_bookable_selections(stub_builder):
    result = booking_request({"target_odds": 4.0, "selection_ids": [
        "event-a:over_1_5", "event-b:home_win"]})
    assert result["status"] == "success"
    assert result["share_code"] == "EXAMPLE"
    assert result["verified_odds"] == 4.2
    assert result["legs"] == 2
    assert result["publication_status"] == "PRIVATE_NOT_PUBLISHED"
    assert stub_builder[-1][1]["selection_ids"] == [
        "event-a:over_1_5", "event-b:home_win"]
    assert stub_builder[-1][1]["require_bookable"] is True


def test_no_booking_if_approved_board_below_requested_odds(stub_builder):
    result = booking_request({"target_odds": 100_000, "selection_ids": [
        "event-a:over_1_5", "event-b:home_win"]})
    assert result["status"] == "BELOW_TARGET"
    assert result["share_code"] is None
    assert not any(name == "book" for name, _ in stub_builder)


def test_no_code_if_bookmaker_readback_fails(monkeypatch, stub_builder):
    module = sys.modules["leagues.builder_v2"]
    module.manual_build = lambda opts: {"status": "BOOKING_UNAVAILABLE", "booking": {
        "status": "invalid", "share_code": None, "readback_validation": "FAILED"}}
    result = booking_request({"target_odds": 2.0, "selection_ids": [
        "event-a:over_1_5", "event-b:home_win"]})
    assert result["share_code"] is None
    assert result["status"] == "BOOKING_UNAVAILABLE"


def test_fails_closed_when_actual_odds_drift_down(monkeypatch, stub_builder):
    module = sys.modules["leagues.builder_v2"]
    def low_quote(opts):
        return {"status": "success", "booking": {
            "status": "active", "booking_status": "FULL",
            "booked_leg_count": 2, "readback_validation": "PASSED",
            "actual_sportybet_odds": 3.4, "share_code": "UNSAFE"}}
    module.manual_build = low_quote
    result = booking_request({"target_odds": 4.0, "selection_ids": [
        "event-a:over_1_5", "event-b:home_win"]})
    assert result["status"] == "BELOW_TARGET"
    assert result["share_code"] is None


def test_bad_filters_and_duplicate_selection_rejected():
    with pytest.raises(ValueError, match="under"):
        filters_for({"markets": ["under_2_5"]})
    with pytest.raises(ValueError, match="distinct"):
        booking_request({"selection_ids": ["same", "same"]})
    with pytest.raises(ValueError, match="100,000"):
        booking_request({"selection_ids": ["a"], "target_odds": 150_000})
