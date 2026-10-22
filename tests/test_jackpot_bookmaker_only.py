"""Bookmaker-only private mode must not modify public model policy or bypass exact checks."""
from datetime import datetime, timedelta, timezone

import pytest

from growth.jackpot_bookmaker_only import bookmaker_paste_preview, bookmaker_paste_book

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)


def _fixture(home, away, event, hour=17, price=3.0, market="home_win"):
    from leagues.market_registry import MARKET_TO_SPORTYBET
    from leagues import sportybet
    mid, specifier, outcome = MARKET_TO_SPORTYBET[market]
    return {
        "event_id": event, "home_team": home, "away_team": away,
        "home_squad": sportybet._squad(home),
        "away_squad": sportybet._squad(away),
        "kickoff_ms": int(datetime(2026, 10, 22, hour, tzinfo=timezone.utc).timestamp()*1000),
        "competition": "UEFA Europa League",
        "market_refs": {f"{mid}|{specifier}": {
            "outcomes": {outcome: {"active": True, "odds": price}},
        }},
        "prices": {market: price},
    }


def _board(*entries):
    from leagues import sportybet
    result = {"__meta__": {"is_complete": True, "snapshot_id": "test", "fetched_at": NOW.timestamp()}}
    for item in entries:
        name = f"{sportybet._norm(item['home_team'])}|{sportybet._norm(item['away_team'])}"
        result.setdefault(name, []).append(item)
    return result


def _args(text, target=2):
    return {"fixtures_text": text, "target_odds": target, "max_legs": 50,
            "horizon": "today", "selection_mode": "bookmaker_only"}


def test_model_grades_not_required_for_bookmaker_only():
    board = _board(_fixture("TSG Hoffenheim", "Lyon", "evt1", price=3.2),
                   _fixture("RB Salzburg", "Celje", "evt2", price=4.0))
    result = bookmaker_paste_preview(
        _args("Hoffenheim vs Lyon | Home win @1.02\n"
              "Salzburg vs Celje | Home win @1.04", 10),
        board=board, now=NOW)
    assert result["status"] == "PROPOSED_NOT_BOOKED"
    assert result["prediction_quality_gate_applied"] is False
    assert result["matched_fixture_count"] == 2
    assert result["unmatched_fixture_count"] == 0
    assert result["indicative_odds"] == pytest.approx(12.8)
    assert result["distinct_fixture_count"] == 2
    assert result["selection_ids"] == ["evt1:home_win", "evt2:home_win"]


def test_partial_ticket_is_not_misreported_as_a_full_ceiling():
    board = _board(_fixture("Hoffenheim", "Lyon", "evt1", price=3.2))
    result = bookmaker_paste_preview(
        _args("Hoffenheim vs Lyon | Home win\n"
              "Ajax vs Atalanta | BTTS Yes", 100000),
        board=board, now=NOW)
    assert result["status"] == "UNMATCHED_FIXTURES"
    assert result["matched_fixture_count"] == 1
    assert result["unmatched_fixture_count"] == 1
    assert result["partial_reference_odds"] == pytest.approx(3.2)
    assert result["maximum_reference_odds"] is None
    assert result["full_ticket_complete"] is False
    assert result["selection_ids"] == []
    assert result["distinct_fixture_count"] == 1


def test_wrong_away_side_is_not_matched():
    board = _board(_fixture("Hoffenheim", "Lyon", "evt1"))
    result = bookmaker_paste_preview(
        _args("Hoffenheim vs Dortmund | Home win"),
        board=board, now=NOW)
    assert result["matched_fixture_count"] == 0
    assert result["unmatched"][0]["reason"] == "FIXTURE_NOT_ON_SPORTYBET_BOARD"


def test_undermarket_excluded_and_started_fixture_rejected():
    from leagues.market_registry import MARKET_TO_SPORTYBET
    board = _board(_fixture("Ajax", "Atalanta", "evt1", price=2.3,
                            market="under_2_5"),
                   _fixture("Hoffenheim", "Lyon", "evt2", hour=14))
    under = bookmaker_paste_preview(
        _args("Ajax vs Atalanta | Under 2.5"), board=board, now=NOW)
    assert under["unmatched"][0]["reason"] == "UNDER_MARKET_EXCLUDED"
    started = bookmaker_paste_preview(
        _args("Hoffenheim vs Lyon | Home win"), board=board, now=NOW)
    assert started["unmatched"][0]["reason"] == "STARTED_OR_TOO_CLOSE_TO_KICKOFF"


def test_too_low_actual_bookmaker_price_cannot_release_code(monkeypatch):
    from growth import jackpot_bookmaker_only as module
    from leagues import sportybet
    board = _board(_fixture("Hoffenheim", "Lyon", "evt1", price=3.2))
    monkeypatch.setattr(sportybet, "fetch_board", lambda force=False: board)
    monkeypatch.setattr(module, "datetime", datetime)
    # Override ambient time with a time in the same fixture day:
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(module, "datetime", Clock)
    import leagues.booking as booking
    monkeypatch.setattr(booking, "create_booking", lambda *a,**kw:{
        "share_code": "TESTREF", "booking_status": "FULL",
        "readback_validation": "PASSED", "booked_leg_count": 1,
        "actual_sportybet_odds": 2.1,
    })
    result = bookmaker_paste_book(_args("Hoffenheim vs Lyon | Home win",3))
    assert result["status"] == "BELOW_TARGET"
    assert result["share_code"] is None


def test_paste_route_dispatches_before_model_lookup(monkeypatch):
    from growth import jackpot_paste
    import growth.private_jackpot as model
    monkeypatch.setattr(model, "candidate_board", lambda _: (_ for _ in ()).throw(
        AssertionError("bookmaker-only must not call model candidates")))
    from growth import jackpot_bookmaker_only
    monkeypatch.setattr(jackpot_bookmaker_only, "bookmaker_paste_preview",
                        lambda _: {"status": "UNMATCHED_FIXTURES", "share_code": None})
    result = jackpot_paste.pasted_preview(_args("Hoffenheim vs Lyon | Home win"))
    assert result["status"] == "UNMATCHED_FIXTURES"
