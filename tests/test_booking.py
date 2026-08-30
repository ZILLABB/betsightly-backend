"""
Tier booking codes.

The properties worth protecting are all refusals. A code that stakes something
other than the published tier is worse than no code at all, because the reader
cannot see the difference once it loads into their slip — so a tier is booked
only when every leg maps, the created code is read back and compared before it
is stored, and anything short of that publishes a reason instead.

No network: the bookmaker calls are stubbed.
"""

import json

import pytest
from sqlalchemy import text

from database import engine
from leagues import booking as B


DAY = "1999-02-02"


@pytest.fixture(autouse=True)
def clean_bookings():
    def _clear():
        with engine.begin() as conn:
            B._ensure_table(conn)
            conn.execute(text("DELETE FROM tier_bookings WHERE publish_date = :d"),
                         {"d": DAY})
    _clear()
    yield
    _clear()


def _board():
    return {
        "fulham|chelsea": {
            "event_id": "sr:match:1", "home_team": "Fulham", "away_team": "Chelsea",
            "home_squad": "", "away_squad": "", "kickoff_ms": 1787598000000,
            "prices": {"over_1_5": 1.22}, "margins": {"over_1_5": 0.04},
        },
        "arsenal|spurs": {
            "event_id": "sr:match:2", "home_team": "Arsenal", "away_team": "Spurs",
            "home_squad": "", "away_squad": "", "kickoff_ms": 1787598000000,
            "prices": {"home_win": 1.80}, "margins": {"home_win": 0.05},
        },
    }


def _game(home, away, market, kickoff="2026-08-24T19:00:00Z"):
    return {"home_team": home, "away_team": away, "market": market,
            "kickoff": kickoff, "prediction": f"{market} on {home}"}


# ── Mapping ────────────────────────────────────────────────

def test_maps_a_tier_onto_selections():
    games = [_game("Fulham", "Chelsea", "over_1_5"),
             _game("Arsenal", "Spurs", "home_win")]
    sels, unmapped = B.selections_for(games, _board())
    assert unmapped == []
    assert sels == [
        {"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
         "specifier": "total=1.5"},
        {"eventId": "sr:match:2", "marketId": "1", "outcomeId": "1",
         "specifier": None},
    ]


def test_the_three_way_market_maps_to_the_right_side():
    """1X2 outcome ids are Home=1, Draw=2, Away=3 — an easy place to slip."""
    board = _board()
    board["arsenal|spurs"]["market_refs"] = {"1|": {"outcomes": {
        "1": {"active": True, "odds": 1.8},
        "2": {"active": True, "odds": 3.4},
        "3": {"active": True, "odds": 4.2},
    }}}
    for market, outcome in [("home_win", "1"), ("draw", "2"), ("away_win", "3")]:
        sels, _ = B.selections_for([_game("Arsenal", "Spurs", market)], board)
        assert sels[0]["outcomeId"] == outcome, market


def test_market_group_is_not_bookable():
    """The rollover bug: a group does not say which side the pick was on."""
    sels, unmapped = B.selections_for(
        [_game("Fulham", "Chelsea", "match_result")], _board())
    assert sels == []
    assert "no SportyBet mapping" in unmapped[0]["reason"]


def test_missing_market_key_is_not_bookable():
    sels, unmapped = B.selections_for(
        [_game("Fulham", "Chelsea", None)], _board())
    assert sels == [] and unmapped


def test_fixture_absent_from_the_board_is_reported():
    sels, unmapped = B.selections_for(
        [_game("Someone", "Nobody", "over_1_5")], _board())
    assert sels == []
    assert "not present" in unmapped[0]["reason"]


def test_every_bookable_market_has_a_distinct_selection():
    """Guards against a copy-paste collision in the market table."""
    seen = set()
    for market, triple in B.MARKET_TO_SPORTYBET.items():
        assert triple not in seen, f"{market} duplicates another market"
        seen.add(triple)


def test_team_totals_are_not_crossed():
    """Markets 19 and 20 mirror each other, so the ids alone say whose goals.

    Getting these the wrong way round books the opposite team, and nothing
    downstream would catch it — the slip would be internally consistent and
    validate cleanly against exactly the wrong selection.
    """
    team_totals = {m: t for m, t in B.MARKET_TO_SPORTYBET.items()
                   if "_over_" in m or "_under_" in m}
    assert team_totals, "expected per-team goal lines in the table"
    for market, (mid, _, _) in team_totals.items():
        if market.startswith("home_"):
            assert mid == "19", f"{market} must use the home market"
        elif market.startswith("away_"):
            assert mid == "20", f"{market} must use the away market"


def test_over_and_under_take_opposite_outcomes():
    for market, (mid, spec, outcome) in B.MARKET_TO_SPORTYBET.items():
        if "_over_" in market or market.startswith("over_"):
            assert outcome == "12", market
        elif "_under_" in market or market.startswith("under_"):
            assert outcome == "13", market


def test_every_published_market_can_be_booked():
    """A pick we publish but cannot book costs its whole tier a code.

    Partial slips are refused, so one unbookable market in a tier means no
    code at all — which makes this table's completeness a publishing concern,
    not just a booking one.
    """
    from leagues.picks import MARKET_LABELS
    missing = sorted(set(MARKET_LABELS) - set(B.MARKET_TO_SPORTYBET))
    assert not missing, f"published but not bookable: {missing}"


# ── Refusals ───────────────────────────────────────────────

def test_a_partial_tier_is_refused(monkeypatch):
    """Four legs booked under a five-leg tier is a different bet.

    The reader has no way to notice once the code is in their slip, so this
    publishes a reason rather than a code.
    """
    called = []
    monkeypatch.setattr(B, "_post_share", lambda s: called.append(s))
    games = [_game("Fulham", "Chelsea", "over_1_5"),
             _game("Someone", "Nobody", "over_1_5")]
    record = B.create_booking(games, _board())
    assert record["status"] == "unavailable"
    assert record["share_code"] is None
    assert called == [], "must not contact the bookmaker for a partial slip"


def test_nothing_mappable_yields_a_reason_not_a_crash():
    record = B.create_booking([_game("Someone", "Nobody", "over_1_5")], _board())
    assert record["status"] == "unavailable" and record["legs"] == 0


def test_bookmaker_refusal_is_recorded(monkeypatch):
    monkeypatch.setattr(B, "_post_share",
                        lambda s: {"bizCode": 19000, "message": "Invalid"})
    record = B.create_booking([_game("Fulham", "Chelsea", "over_1_5")], _board())
    assert record["status"] == "failed"
    assert "Invalid" in record["reason"]


def test_transport_failure_is_recorded(monkeypatch):
    def _boom(_):
        raise OSError("connection reset")
    monkeypatch.setattr(B, "_post_share", _boom)
    record = B.create_booking([_game("Fulham", "Chelsea", "over_1_5")], _board())
    assert record["status"] == "failed"
    assert record["share_code"] is None


def test_a_response_without_a_code_is_a_failure(monkeypatch):
    monkeypatch.setattr(B, "_post_share", lambda s: {"bizCode": 10000, "data": {}})
    record = B.create_booking([_game("Fulham", "Chelsea", "over_1_5")], _board())
    assert record["status"] == "failed"


# ── Validation ─────────────────────────────────────────────

def _share_response(selections, deadline=1788867000000, unavailable=None):
    return {"bizCode": 10000, "data": {
        "shareCode": "ABC123",
        "shareURL": "http://www.sportybet.com/ng/?shareCode=ABC123",
        "deadline": deadline,
        "unavailableOutcomes": unavailable or [],
        "ticket": {"orderType": 2, "selections": selections},
    }}


def test_a_validated_code_is_active(monkeypatch):
    sels = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"}]
    monkeypatch.setattr(B, "_post_share", lambda s: _share_response(sels))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(sels))
    record = B.create_booking([_game("Fulham", "Chelsea", "over_1_5")], _board())
    assert record["status"] == "active"
    assert record["share_code"] == "ABC123"
    assert record["expires_at"].startswith("2026-")
    assert record["priced_at"]


def test_a_dropped_leg_fails_validation(monkeypatch):
    """HTTP 200 does not mean the right slip exists."""
    asked = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
              "specifier": "total=1.5"},
             {"eventId": "sr:match:2", "marketId": "1", "outcomeId": "3",
              "specifier": None}]
    monkeypatch.setattr(B, "_post_share", lambda s: _share_response(asked))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(asked[:1]))
    record = B.create_booking(
        [_game("Fulham", "Chelsea", "over_1_5"), _game("Arsenal", "Spurs", "home_win")],
        _board())
    assert record["status"] == "invalid"
    assert record["share_code"] is None


def test_a_substituted_selection_fails_validation(monkeypatch):
    asked = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
              "specifier": "total=1.5"}]
    swapped = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "13",
                "specifier": "total=1.5"}]  # Under, not Over
    monkeypatch.setattr(B, "_post_share", lambda s: _share_response(asked))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(swapped))
    record = B.create_booking([_game("Fulham", "Chelsea", "over_1_5")], _board())
    assert record["status"] == "invalid"


def test_an_already_unavailable_selection_fails_validation(monkeypatch):
    sels = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"}]
    monkeypatch.setattr(B, "_post_share", lambda s: _share_response(sels))
    monkeypatch.setattr(
        B, "_read_share",
        lambda c: _share_response(sels, unavailable=[{"eventId": "sr:match:1"}]))
    record = B.create_booking([_game("Fulham", "Chelsea", "over_1_5")], _board())
    assert record["status"] == "invalid"


def test_validation_survives_an_unreadable_code(monkeypatch):
    def _boom(_):
        raise OSError("timeout")
    monkeypatch.setattr(B, "_read_share", _boom)
    ok, why = B.validate_code("ABC123", [])
    assert not ok and "could not read back" in why


# ── Storage and idempotency ────────────────────────────────

def test_booking_the_card_is_idempotent(monkeypatch):
    """The daily job may retry, and the in-process loop calls the same path."""
    sels = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"}]
    posts = []
    monkeypatch.setattr(B, "_post_share",
                        lambda s: posts.append(s) or _share_response(sels))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(sels))
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda: _board())

    card = {"banker": {"games": [_game("Fulham", "Chelsea", "over_1_5")]}}
    first = B.book_card(DAY, card)
    assert len(first["booked"]) == 1 and len(posts) == 1

    second = B.book_card(DAY, card)
    assert second["booked"] == [] and len(second["skipped"]) == 1
    assert len(posts) == 1, "a held code must not be re-minted"


def test_force_rebooks(monkeypatch):
    sels = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"}]
    posts = []
    monkeypatch.setattr(B, "_post_share",
                        lambda s: posts.append(s) or _share_response(sels))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(sels))
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda: _board())
    card = {"banker": {"games": [_game("Fulham", "Chelsea", "over_1_5")]}}
    B.book_card(DAY, card)
    B.book_card(DAY, card, force=True)
    assert len(posts) == 2


def test_no_board_means_no_bookings_attempted(monkeypatch):
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda: {})
    report = B.book_card(DAY, {"banker": {"games": [
        _game("Fulham", "Chelsea", "over_1_5")]}})
    assert report["booked"] == []
    assert "no bookmaker board" in report["failed"][0]


def test_empty_tiers_are_skipped_entirely(monkeypatch):
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda: _board())
    report = B.book_card(DAY, {"banker": {"games": []}, "junk": "not a dict"})
    assert report["booked"] == [] and report["failed"] == []


# ── Attaching to the card ──────────────────────────────────

def test_attach_is_read_only(monkeypatch):
    """Serving the card must never contact a bookmaker.

    If it did, a page load would create bookings and two readers could hold
    different codes for the same tier.
    """
    def _boom(*a, **k):
        raise AssertionError("attach must not book")
    monkeypatch.setattr(B, "_post_share", _boom)

    B._store(DAY, "banker", {"status": "active", "share_code": "ZZZ999",
                             "legs": 1, "share_url": "http://x"})
    card = {"banker": {"games": [1]}, "2_odds": {"games": [1, 2]}}
    out = B.attach_bookings(DAY, card)
    assert out["banker"]["booking"]["share_code"] == "ZZZ999"
    assert "booking" not in out["2_odds"], "unbooked tiers carry no record"


def test_attach_with_nothing_stored_is_a_no_op():
    card = {"banker": {"games": [1]}}
    assert B.attach_bookings("1999-12-31", card) == card


def test_store_survives_an_oversized_record():
    B._store(DAY, "banker", {"status": "active", "share_code": "X",
                             "junk": "y" * 20000})
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT detail FROM tier_bookings WHERE publish_date=:d"
                 " AND tier='banker'"), {"d": DAY}).fetchone()
    assert len(row[0]) > 20000, "booking JSON must never be silently truncated"


def test_bookings_for_tolerates_corrupt_rows():
    with engine.begin() as conn:
        B._ensure_table(conn)
        conn.execute(text(
            "INSERT INTO tier_bookings (publish_date, tier, status, detail)"
            " VALUES (:d, 'banker', 'active', '{bad json')"), {"d": DAY})
    assert B.bookings_for(DAY) == {}


# ── Staleness ──────────────────────────────────────────────

def test_a_code_does_not_outlive_the_tier_it_describes(monkeypatch):
    """The bug this catches, found while testing: a tier rebuilt after booking.

    The stored code was still attached beside legs it had never covered, so
    the card showed one slip and the code loaded another.
    """
    B._store(DAY, "banker", {
        "status": "active", "share_code": "OLD123", "legs": 1,
        "leg_fingerprint": B.leg_fingerprint(
            [_game("Fulham", "Chelsea", "over_1_5")]),
    })
    changed = {"banker": {"games": [_game("Arsenal", "Spurs", "home_win")]}}
    out = B.attach_bookings(DAY, changed)
    assert out["banker"]["booking"]["status"] == "stale"
    assert out["banker"]["booking"]["share_code"] is None


def test_an_unchanged_tier_keeps_its_code():
    games = [_game("Fulham", "Chelsea", "over_1_5")]
    B._store(DAY, "banker", {
        "status": "active", "share_code": "KEEP99", "legs": 1,
        "leg_fingerprint": B.leg_fingerprint(games),
    })
    out = B.attach_bookings(DAY, {"banker": {"games": games}})
    assert out["banker"]["booking"]["share_code"] == "KEEP99"


def test_fingerprint_ignores_leg_order():
    a = [_game("Fulham", "Chelsea", "over_1_5"), _game("Arsenal", "Spurs", "home_win")]
    assert B.leg_fingerprint(a) == B.leg_fingerprint(list(reversed(a)))


def test_fingerprint_tracks_the_market_not_just_the_fixture():
    """Same match, opposite side, must not reuse the code."""
    over = [_game("Fulham", "Chelsea", "over_1_5")]
    under = [_game("Fulham", "Chelsea", "under_1_5")]
    assert B.leg_fingerprint(over) != B.leg_fingerprint(under)


def test_selection_fingerprint_uses_exact_sportybet_tuple_and_ignores_order():
    first = [
        {"eventId": "e1", "marketId": "18", "outcomeId": "12",
         "specifier": "total=1.5"},
        {"eventId": "e2", "marketId": "1", "outcomeId": "1", "specifier": ""},
    ]
    changed = [dict(first[0], outcomeId="13"), first[1]]

    assert B.selection_fingerprint(first) == B.selection_fingerprint(list(reversed(first)))
    assert B.selection_fingerprint(first) != B.selection_fingerprint(changed)


def test_a_changed_tier_is_rebooked_not_skipped(monkeypatch):
    sels = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"}]
    posts = []
    monkeypatch.setattr(B, "_post_share",
                        lambda s: posts.append(s) or _share_response(sels))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(sels))
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda: _board())

    B.book_card(DAY, {"banker": {"games": [_game("Fulham", "Chelsea", "over_1_5")]}})
    assert len(posts) == 1
    # Same tier, different legs — the held code no longer applies.
    B.book_card(DAY, {"banker": {"games": [_game("Arsenal", "Spurs", "home_win")]}})
    assert len(posts) == 2


def test_booking_drops_the_served_card_cache(monkeypatch):
    """Codes must appear on the card now, not whenever the cache lapses.

    The daily job builds and caches the card, then books against it. Without
    invalidation the site serves that cached, code-free card for up to fifteen
    minutes while the codes sit in the database — which is exactly what the
    site showed the morning after booking went live.

    Runs the real job so the assertion guards the shipped step, not a copy of
    it; every outward call is stubbed.
    """
    from leagues import daily_feed, scheduler

    monkeypatch.setattr(daily_feed, "_publish_date", lambda: "1999-04-04")
    monkeypatch.setattr(daily_feed, "build_daily_accumulators",
                        lambda *a, **k: {"date": "1999-04-04",
                                         "accumulators": {}, "revision": 1})
    monkeypatch.setattr("leagues.booking.book_card",
                        lambda *a, **k: {"booked": ["banker: X"], "skipped": [],
                                         "failed": []})
    monkeypatch.setattr("leagues.results_checker.check_all_pending", lambda: {})
    monkeypatch.setattr("leagues.results_checker.settle_published_slips", lambda: {})
    monkeypatch.setattr("leagues.calibrator.fit_calibration", lambda **k: {"n": 0})
    monkeypatch.setattr("services.push_notification_service.notify_predictions_ready",
                        lambda **k: None)

    daily_feed._accum_cache.update({"result": {"stale": True}, "ts": 9e9})
    report = scheduler.run_daily_job(force=True, publish=False)

    assert report["steps"]["book"]["ok"], report["steps"]["book"]
    assert daily_feed._accum_cache["result"] is None,         "the cached card must be dropped so codes are served immediately"

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_runs WHERE run_date = '1999-04-04'"))


# ── Partial booking for singles ────────────────────────────

def test_a_singles_tier_books_whatever_is_available(monkeypatch):
    """Available Over 1.5 legs may be shared, but the ticket is labelled."""
    sels = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"}]
    monkeypatch.setattr(B, "_post_share", lambda s: _share_response(sels))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(sels))
    games = [_game("Fulham", "Chelsea", "over_1_5"),
             _game("Someone", "Nobody", "over_1_5")]
    record = B.create_booking(games, _board(), allow_partial=True)
    assert record["status"] == "active"
    assert record["partial"] is True
    assert record["unbooked"] == ["Someone v Nobody"]
    assert record["ticket_type"] == "accumulator"


def test_an_accumulator_still_refuses_a_partial_slip(monkeypatch):
    """A missing leg changes the bet, and the reader cannot see that it did."""
    monkeypatch.setattr(B, "_post_share",
                        lambda s: pytest.fail("must not book a partial acca"))
    games = [_game("Fulham", "Chelsea", "over_1_5"),
             _game("Someone", "Nobody", "over_1_5")]
    record = B.create_booking(games, _board(), allow_partial=False)
    assert record["status"] == "unavailable"


def test_a_complete_singles_tier_is_not_flagged_partial(monkeypatch):
    sels = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"}]
    monkeypatch.setattr(B, "_post_share", lambda s: _share_response(sels))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(sels))
    record = B.create_booking([_game("Fulham", "Chelsea", "over_1_5")],
                              _board(), allow_partial=True)
    assert record["status"] == "active" and record["partial"] is False


def test_book_card_does_not_misrepresent_an_invalid_one_leg_acca(monkeypatch):
    """One surviving leg is insufficient for a multi-leg accumulator tier."""
    sels = [{"eventId": "sr:match:1", "marketId": "18", "outcomeId": "12",
             "specifier": "total=1.5"}]
    monkeypatch.setattr(B, "_post_share", lambda s: _share_response(sels))
    monkeypatch.setattr(B, "_read_share", lambda c: _share_response(sels))
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda: _board())
    games = [_game("Fulham", "Chelsea", "over_1_5"),
             _game("Someone", "Nobody", "over_1_5")]
    report = B.book_card(DAY, {
        "over_1_5": {"games": games, "presentation": "singles"},
        "5_odds": {"games": games, "presentation": "accumulator"},
    })
    assert any(r.startswith("over_1_5") for r in report["booked"])
    assert any(r.startswith("5_odds") for r in report["failed"])


# ── Replacement and accumulator partial variants ──────────

def _exact_board():
    board = _board()
    board["__meta__"] = {"is_complete": True, "snapshot_id": "booking-snap"}
    board["fulham|chelsea"]["market_refs"] = {
        "18|total=1.5": {"outcomes": {
            "12": {"active": True, "odds": 1.40},
            "13": {"active": True, "odds": 4.6},
        }}}
    board["arsenal|spurs"]["market_refs"] = {"1|": {"outcomes": {
        "1": {"active": True, "odds": 1.45},
        "2": {"active": True, "odds": 3.4},
        "3": {"active": True, "odds": 4.2},
    }}}
    return board


def _qualified_game(home, away, market, confidence=.68, group="goals"):
    return {**_game(home, away, market), "match_id": f"{home}-{away}",
            "prediction_type": group, "confidence": confidence,
            "odds": 1.3, "odds_are_real": True, "expected_value": .05,
            "market_margin": .04, "safe_tier_eligible": True}


def test_book_card_rebuilds_with_a_qualified_exactly_bookable_replacement(monkeypatch):
    board = _exact_board()
    last = {"selections": []}
    def post(selections):
        last["selections"] = selections
        return _share_response(selections)
    def read(_):
        payload = _share_response(last["selections"])
        payload["data"]["ticket"]["displayTotalOdds"] = "2.20"
        return payload
    monkeypatch.setattr(B, "_post_share", post)
    monkeypatch.setattr(B, "_read_share", read)
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda **k: board)
    original = [_qualified_game("Fulham", "Chelsea", "over_1_5"),
                _qualified_game("Missing", "Club", "home_win",
                                group="match_result")]
    candidates = [_qualified_game("Fulham", "Chelsea", "over_1_5"),
                  _qualified_game("Arsenal", "Spurs", "home_win",
                                  group="match_result")]
    card = {"2_odds": {"games": original, "total_odds": 2.1,
                        "booking_rule": {"selector": "accumulator", "target": 2,
                                         "max_picks": 4, "min_confidence": .65,
                                         "min_ev": .82, "band_low": .92,
                                         "safe_only": True}},
            "_booking_candidates": {"games": candidates}}
    before = json.loads(json.dumps(original))
    report = B.book_card(DAY, card)
    record = B.bookings_for(DAY)["2_odds"]
    assert report["booked"]
    assert record["booking_status"] == "REBUILT_FULL"
    assert record["replacement_count"] == 1
    assert record["actual_sportybet_odds"] == 2.2
    assert any(g["home_team"] == "Fulham" for g in record["final_booked_legs"])
    assert original == before, "booking variants must not rewrite the prediction"


def test_accumulator_falls_back_to_a_clearly_partial_ticket(monkeypatch):
    board = _exact_board()
    last = {"selections": []}
    monkeypatch.setattr(B, "_post_share",
                        lambda selections: last.update(selections=selections)
                        or _share_response(selections))
    monkeypatch.setattr(B, "_read_share",
                        lambda code: _share_response(last["selections"]))
    monkeypatch.setattr("leagues.sportybet.fetch_board", lambda **k: board)
    original = [_qualified_game("Fulham", "Chelsea", "over_1_5"),
                _qualified_game("Arsenal", "Spurs", "home_win",
                                group="match_result"),
                _qualified_game("Missing", "Club", "over_1_5")]
    card = {"5_odds": {"games": original, "total_odds": 5.1,
                        "booking_rule": {"selector": "accumulator", "target": 5,
                                         "max_picks": 6, "min_confidence": .65,
                                         "min_ev": .72}},
            "_booking_candidates": {"games": []}}
    B.book_card(DAY, card)
    record = B.bookings_for(DAY)["5_odds"]
    assert record["booking_status"] == "PARTIAL"
    assert record["original_leg_count"] == 3
    assert record["booked_leg_count"] == 2
    assert record["excluded_leg_count"] == 1
    assert record["ticket_type"] == "accumulator"


def test_generated_booking_reuses_same_valid_fingerprint(monkeypatch):
    games = [_game("Fulham", "Chelsea", "over_1_5")]
    monkeypatch.setattr(B, "generated_booking_for", lambda _: {
        "status": "active", "share_code": "HELD42",
        "actual_sportybet_odds": 1.4,
    })
    monkeypatch.setattr(B, "validate_code_details",
                        lambda code, selections: (True, "ok", 1.42))
    monkeypatch.setattr(B, "create_booking",
                        lambda *args, **kwargs: pytest.fail("minted a duplicate code"))

    record = B.create_or_reuse_generated_booking(games, _board())

    assert record["share_code"] == "HELD42"
    assert record["code_reused"] is True
    assert record["actual_sportybet_odds"] == 1.42


def test_generated_booking_force_creates_and_persists_new_code(monkeypatch):
    games = [_game("Fulham", "Chelsea", "over_1_5")]
    stored = {}
    monkeypatch.setattr(B, "generated_booking_for",
                        lambda _: pytest.fail("force must bypass reuse"))
    monkeypatch.setattr(B, "create_booking", lambda *args, **kwargs: {
        "status": "active", "share_code": "NEW123",
    })
    monkeypatch.setattr(B, "_store_generated_booking",
                        lambda fingerprint, record: stored.update({
                            "fingerprint": fingerprint, "record": record,
                        }))

    record = B.create_or_reuse_generated_booking(
        games, _board(), predicted_odds=1.4, force=True)

    assert record["share_code"] == "NEW123"
    assert record["code_reused"] is False
    assert stored["record"]["share_code"] == "NEW123"
