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


def test_quoted_under_allowed_in_private_mode_but_started_fixture_rejected():
    board = _board(_fixture("Ajax", "Atalanta", "evt1", price=2.3,
                            market="under_2_5"),
                   _fixture("Hoffenheim", "Lyon", "evt2", hour=14))
    under = bookmaker_paste_preview(
        _args("Ajax vs Atalanta | Under 2.5"), board=board, now=NOW)
    assert under["status"] == "PROPOSED_NOT_BOOKED"
    assert under["matched"][0]["market"] == "under_2_5"
    assert under["matched"][0]["odds"] == pytest.approx(2.3)
    assert under["share_code"] is None
    started = bookmaker_paste_preview(
        _args("Hoffenheim vs Lyon | Home win"), board=board, now=NOW)
    assert started["unmatched"][0]["reason"] == "STARTED_OR_TOO_CLOSE_TO_KICKOFF"


@pytest.mark.parametrize("home,away,market,price", [
    ("Torino", "Monza", "under_3_5", 1.37),
    ("Alaves", "Malaga CF", "under_3_5", 1.32),
    ("Vitoria SC Guimaraes", "Maritimo Madeira", "under_3_5", 1.32),
    ("Granada", "Valladolid", "under_2_5", 1.73),
    ("Alanyaspor", "Kocaelispor", "under_2_5", 1.62),
])
def test_requested_under_markets_remain_exact_and_quoted(home, away, market, price):
    real = _fixture(home, away, "senior-event", price=price, market=market)
    real["competition"] = "Domestic Senior League"
    real["kickoff_ms"] = int((NOW + timedelta(hours=26)).timestamp() * 1000)
    result = bookmaker_paste_preview({
        **_args(f"{home} vs {away} | {market.replace('_', ' ')}"),
        "horizon": "3_days",
    }, board=_board(real), now=NOW)
    # A single quoted 1.37x-1.73x leg must pass exact-market validation,
    # but cannot satisfy the existing 2.00x minimum accumulator target.
    assert result["status"] == "BELOW_TARGET"
    assert result["full_ticket_complete"] is True
    assert result["matched_fixture_count"] == 1
    assert result["matched"][0]["market"] == market
    assert result["matched"][0]["event_id"] == "senior-event"
    assert result["indicative_odds"] == pytest.approx(price)
    assert result["share_code"] is None


def test_under_market_suspended_outcome_remains_unavailable():
    event = _fixture("Torino", "Monza", "senior", market="under_3_5")
    ref = next(iter(event["market_refs"].values()))
    next(iter(ref["outcomes"].values()))["active"] = False
    result = bookmaker_paste_preview(
        _args("Torino vs Monza | Under 3.5"), board=_board(event), now=NOW)
    assert result["matched_fixture_count"] == 0
    assert result["unmatched"][0]["reason"] == "OUTCOME_SUSPENDED"
    assert result["share_code"] is None


def test_senior_fixture_ignores_youth_competition_without_squad_markers():
    senior = _fixture("Alanyaspor", "Kocaelispor", "real-senior",
                      price=1.62, market="under_2_5")
    senior["competition"] = "Super Lig"
    youth = _fixture("Alanyaspor", "Kocaelispor", "youth-event",
                     price=2.05, market="under_2_5")
    # SportyBet records sometimes lack U19 markers in both team names
    # and home_squad/away_squad, so competition must be checked too.
    youth["competition"] = "U19 PAF Ligi"
    youth["kickoff_ms"] = senior["kickoff_ms"]
    payload = _args("Alanyaspor vs Kocaelispor | Under 2.5")
    result = bookmaker_paste_preview(payload, board=_board(senior, youth), now=NOW)
    assert result["status"] == "BELOW_TARGET"
    assert result["full_ticket_complete"] is True
    assert result["matched"][0]["event_id"] == "real-senior"
    assert result["matched"][0]["odds"] == pytest.approx(1.62)
    assert result["share_code"] is None

    youth_only = bookmaker_paste_preview(payload, board=_board(youth), now=NOW)
    assert youth_only["matched_fixture_count"] == 0
    assert youth_only["unmatched"][0]["reason"] == "FIXTURE_NOT_ON_SPORTYBET_BOARD"


def test_duplicate_senior_fixtures_remain_ambiguous():
    first = _fixture("Alanyaspor", "Kocaelispor", "first",
                     market="under_2_5")
    second = _fixture("Alanyaspor", "Kocaelispor", "second",
                      market="under_2_5")
    result = bookmaker_paste_preview(
        _args("Alanyaspor vs Kocaelispor | Under 2.5"),
        board=_board(first, second), now=NOW)
    assert result["matched_fixture_count"] == 0
    assert result["unmatched"][0]["reason"] == "AMBIGUOUS_BOOKMAKER_FIXTURE"
    assert result["share_code"] is None


def test_too_low_actual_bookmaker_price_cannot_release_code(monkeypatch):
    from growth import jackpot_bookmaker_only as module
    from leagues import sportybet
    board = _board(_fixture("Hoffenheim", "Lyon", "evt1", price=3.2))
    monkeypatch.setattr(sportybet, "cached_board_for_admin", lambda: board)
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


def test_preview_never_fetches_live_bookmaker_board_on_request(monkeypatch):
    from leagues import sportybet
    monkeypatch.setattr(sportybet, "cached_board_for_admin", lambda: None)
    monkeypatch.setattr(sportybet, "fetch_board",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("no synchronous bookmaker crawl")))
    result = bookmaker_paste_preview(_args("Hoffenheim vs Lyon | Home win"))
    assert result["status"] == "BOARD_REFRESH_REQUIRED"
    assert result["share_code"] is None
    assert result["matched_fixture_count"] == 0
    assert result["maximum_reference_odds"] is None
    assert result["exact_market_mode"] is True
    assert result["requested_market_count"] == 1
    assert result["full_ticket_complete"] is False
    assert result["booking_code_created"] is False


def test_book_reuses_one_snapshot_and_never_attempts_missing_ticket(monkeypatch):
    from leagues import sportybet
    import leagues.booking as booking
    calls = []
    board = _board(_fixture("Hoffenheim", "Lyon", "evt1", price=2.7))
    monkeypatch.setattr(sportybet, "cached_board_for_admin",
                        lambda: (calls.append("cached") or board))
    monkeypatch.setattr(sportybet, "fetch_board",
                        lambda *a,**kw: (_ for _ in ()).throw(
                            AssertionError("live network crawl forbidden")))
    monkeypatch.setattr(booking, "create_booking",
                        lambda *a,**kw: (_ for _ in ()).throw(
                            AssertionError("incomplete booking must be refused")))
    from growth import jackpot_bookmaker_only as module
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(module, "datetime", Clock)
    result = bookmaker_paste_book(_args(
        "Hoffenheim vs Lyon | Home win\nAjax vs Atalanta | BTTS Yes", 100000
    ))
    assert result["status"] == "UNMATCHED_FIXTURES"
    assert result["matched_fixture_count"] == 1
    assert calls == ["cached"]


def test_admin_cached_board_respects_freshness_and_completeness(monkeypatch):
    from leagues import sportybet
    board = _board(_fixture("Hoffenheim", "Lyon", "evt1"))
    meta = {**board["__meta__"],
            "cache_schema_version": sportybet._CACHE_SCHEMA_VERSION}
    monkeypatch.setattr(sportybet, "_db_get", lambda _: {
        "metadata": meta, "fetched_at": NOW.timestamp(),
        "fixtures": {k:v for k,v in board.items() if k!="__meta__"}
    })
    monkeypatch.setattr(sportybet.time, "time", lambda: NOW.timestamp()+600)
    assert sportybet.cached_board_for_admin() is not None
    # Producer refreshes on the existing three-hour cadence, so a cache
    # that is 2,000 seconds old must remain readable.
    monkeypatch.setattr(sportybet.time, "time", lambda: NOW.timestamp()+2000)
    assert sportybet.cached_board_for_admin() is not None
    monkeypatch.setattr(sportybet.time, "time", lambda: NOW.timestamp()+11000)
    assert sportybet.cached_board_for_admin() is None
    meta["is_complete"] = False
    monkeypatch.setattr(sportybet.time, "time", lambda: NOW.timestamp()+600)
    assert sportybet.cached_board_for_admin() is None


def test_bookmaker_unique_match_ignores_verified_club_prefixes_and_transliteration():
    from growth.jackpot_bookmaker_only import _same_club
    pairs = [
        ("Jagiellonia Bialystok", "Jagiellonia Bialystok"),
        ("RSC Anderlecht", "Anderlecht"),
        ("FC Thun", "Thun"),
        ("HNK Hajduk Split", "Hajduk Split"),
        ("Lillestroem SK", "Lillestrøm"),
        ("St. Truidense VV", "Sint-Truidense"),
        ("AGF Aarhus", "Aarhus"),
        ("Kuopion Palloseura", "KuPS"),
    ]
    assert all(_same_club(left,right) for left,right in pairs)
    assert not _same_club("Celtic", "Celta Vigo")
    assert not _same_club("Hoffenheim U19", "Hoffenheim")


def test_alias_matching_requires_same_day_and_one_unique_event():
    board = _board(
        _fixture("AGF Aarhus", "Egnatia", "evt1"),
        _fixture("AGF Aarhus", "Egnatia", "evt2"),
    )
    result = bookmaker_paste_preview(
        _args("Aarhus vs KF Egnatia Rrogozhine | Home win"),
        board=board, now=NOW,
    )
    assert result["status"] == "UNMATCHED_FIXTURES"
    assert result["matched_fixture_count"] == 0
    assert result["unmatched"][0]["reason"] == "AMBIGUOUS_BOOKMAKER_FIXTURE"
    assert result["share_code"] is None


def _fixture_at(local_time, home="Flamengo", away="Estudiantes", event="evtfuture"):
    fixture = _fixture(home, away, event, price=2.2)
    fixture["kickoff_ms"] = int(local_time.astimezone(timezone.utc).timestamp()*1000)
    return fixture


def test_next_day_match_accepted_only_in_three_day_mode():
    from zoneinfo import ZoneInfo
    nigeria = ZoneInfo("Africa/Lagos")
    event = _fixture_at(datetime(2026, 10, 23, 1, tzinfo=nigeria))
    board = _board(event)
    today_args = _args("Flamengo vs Estudiantes | Home win")
    denied = bookmaker_paste_preview(today_args, board=board, now=NOW)
    assert denied["unmatched"][0]["reason"] == "NOT_SCHEDULED_TODAY"
    allowed = bookmaker_paste_preview(
        {**today_args, "horizon": "3_days"}, board=board, now=NOW
    )
    assert allowed["status"] == "PROPOSED_NOT_BOOKED"
    assert allowed["matched_fixture_count"] == 1
    assert allowed["horizon"] == "3_days"
    assert allowed["window_end"]
    assert allowed["indicative_odds"] == pytest.approx(2.2)
    assert allowed["share_code"] is None


def test_three_day_window_rejects_event_after_72_hours():
    board = _board(_fixture_at(NOW+timedelta(hours=73)))
    result = bookmaker_paste_preview(
        {**_args("Flamengo vs Estudiantes | Home win"), "horizon": "3_days"},
        board=board, now=NOW,
    )
    assert result["status"] == "UNMATCHED_FIXTURES"
    assert result["unmatched"][0]["reason"] == "OUTSIDE_THREE_DAY_WINDOW"
    assert result["selection_ids"] == []


def test_three_day_window_rejects_game_within_20_minutes():
    board = _board(_fixture_at(NOW+timedelta(minutes=10)))
    result = bookmaker_paste_preview(
        {**_args("Flamengo vs Estudiantes | Home win"), "horizon": "3_days"},
        board=board, now=NOW,
    )
    assert result["unmatched"][0]["reason"] == "STARTED_OR_TOO_CLOSE_TO_KICKOFF"
    assert result["share_code"] is None


def test_three_day_window_rejects_started_fixture():
    board = _board(_fixture_at(NOW-timedelta(hours=1)))
    result = bookmaker_paste_preview(
        {**_args("Flamengo vs Estudiantes | Home win"), "horizon": "3_days"},
        board=board, now=NOW,
    )
    assert result["unmatched"][0]["reason"] == "STARTED_OR_TOO_CLOSE_TO_KICKOFF"
    assert result["share_code"] is None


def test_three_day_window_does_not_guess_between_duplicate_club_events():
    matches = _board(
        _fixture_at(NOW+timedelta(hours=2), event="evt1"),
        _fixture_at(NOW+timedelta(hours=45), event="evt2"),
    )
    result = bookmaker_paste_preview(
        {**_args("Flamengo vs Estudiantes | Home win"), "horizon": "3_days"},
        board=matches, now=NOW,
    )
    assert result["unmatched"][0]["reason"] == "AMBIGUOUS_BOOKMAKER_FIXTURE"
    assert result["share_code"] is None


def test_bookmaker_mode_rejects_seven_day_window():
    with pytest.raises(ValueError, match="Today or Next 3 days"):
        bookmaker_paste_preview({
            **_args("Flamengo vs Estudiantes | Home win"), "horizon": "7_days"
        })


def test_srl_and_borussia_club_matching_regression():
    from growth.jackpot_bookmaker_only import _same_club
    assert not _same_club("Torino", "Torino SRL")
    assert not _same_club("Monza", "AC Monza SRL")
    assert not _same_club("Brest", "Brest SRL")
    assert not _same_club("Nice", "Nice SRL")
    assert not _same_club("Alaves", "Alaves SRL")
    assert not _same_club("Malaga CF", "Malaga CF SRL")
    assert _same_club("Borussia Monchengladbach", "Borussia M´gladbach")
    assert not _same_club("Borussia Dortmund", "Borussia M´gladbach")


@pytest.mark.parametrize("home,away,price", [
    ("Torino", "Monza", 1.29),
    ("Brest", "Nice", 1.22),
    ("Alaves", "Malaga CF", 1.33),
])
def test_real_fixture_selected_over_srl_when_both_exist(home,away,price):
    real = _fixture(home, away, "real-event", price=price, market="over_1_5")
    virtual = _fixture(home+" SRL", away+" SRL", "virtual-event",
                       price=1.8, market="over_1_5")
    future = int((NOW+timedelta(hours=25)).timestamp()*1000)
    real["kickoff_ms"] = future
    virtual["kickoff_ms"] = future-3600000
    result = bookmaker_paste_preview({
        **_args(f"{home} vs {away} | Over 1.5"), "horizon":"3_days"
    }, board=_board(real, virtual), now=NOW)
    assert result["matched_fixture_count"] == 1
    assert result["unmatched_fixture_count"] == 0
    assert result["matched"][0]["event_id"] == "real-event"
    assert result["matched"][0]["odds"] == pytest.approx(price)
    assert result["share_code"] is None
