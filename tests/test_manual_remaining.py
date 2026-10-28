"""No started manual legs may appear in a new bookmaker code."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from leagues import manual_remaining as M
from leagues import booking as B

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _leg(i: int, offset_hours: float) -> dict:
    kickoff = (NOW + timedelta(hours=offset_hours)).isoformat()
    return {
        "match_id": f"fixture-{i}",
        "home_team": f"Home {i}",
        "away_team": f"Away {i}",
        "kickoff": kickoff,
        "market": "over_1_5",
        "odds": 1.52,
        "editorial_manual": True,
    }


def _verified_record(legs: list[dict], *, edition=False) -> dict:
    return {
        "code" if edition else "share_code": "ORIGINAL",
        "readback_validation": "PASSED",
        "status": "active" if not edition else None,
        "original_legs": legs,
    }


def _mock_live_booking(monkeypatch):
    seen = []
    def checked(games, board):
        return ([{**g, "bookable": True, "odds": 1.48} for g in games], [])
    def book(games, board, **kwargs):
        seen.append([g["match_id"] for g in games])
        return {"status": "active", "share_code": "NEWCODE",
                "booking_status": "FULL", "readback_validation": "PASSED",
                "booked_leg_count": len(games),
                "actual_sportybet_odds": 2.2,
                "partial": False}
    monkeypatch.setattr(B, "_revalidate_games", checked)
    monkeypatch.setattr(B, "create_or_reuse_generated_booking", book)
    return seen


def test_started_manual_leg_is_pruned_and_new_code_matches_only_survivors(monkeypatch):
    seen = _mock_live_booking(monkeypatch)
    original = [_leg(1, -2), _leg(2, 3), _leg(3, 4)]
    record = _verified_record(original)
    output = M.eligible_manual_remainder(record, "5_odds", {}, now=NOW)
    assert output["selected"] is True
    assert output["editorial_manual"] is True
    assert output["official_publication"] is False
    assert output["result_scored"] is False
    assert output["removed_leg_count"] == 1
    assert output["remaining_leg_count"] == 2
    assert output["booking"]["share_code"] == "NEWCODE"
    assert seen == [["fixture-2", "fixture-3"]]
    assert original[0]["match_id"] == "fixture-1"
    assert record["share_code"] == "ORIGINAL"


def test_near_kickoff_is_also_removed_and_too_few_survivors_never_book(monkeypatch):
    seen = _mock_live_booking(monkeypatch)
    record = _verified_record([_leg(1, -1), _leg(2, .15), _leg(3, 2)])
    output = M.eligible_manual_remainder(record, "10_odds", {}, now=NOW)
    assert output["selected"] is False
    assert output["remaining_leg_count"] == 1
    assert seen == []


def test_unverified_old_manual_source_is_not_treated_as_an_admin_ticket(monkeypatch):
    seen = _mock_live_booking(monkeypatch)
    record = _verified_record([_leg(1, 2), _leg(2, 3)])
    record["readback_validation"] = "FAILED"
    assert M.eligible_manual_remainder(record, "5_odds", {}, now=NOW)["selected"] is False
    assert seen == []
    record["readback_validation"] = "PASSED"
    record["original_legs"][1]["editorial_manual"] = False
    assert M.eligible_manual_remainder(record, "5_odds", {}, now=NOW)["selected"] is False
    assert seen == []


def test_rebooking_rejects_readback_failure_and_partial_codes(monkeypatch):
    monkeypatch.setattr(B, "_revalidate_games",
                        lambda games, board: (games, []))
    for booking in (
        {"status":"active","share_code":"BAD","booking_status":"FULL",
         "readback_validation":"FAILED","actual_sportybet_odds":2.2},
        {"status":"active","share_code":"PARTIAL","booking_status":"PARTIAL",
         "readback_validation":"PASSED","actual_sportybet_odds":2.2},
        {"status":"active","share_code":"NOODDS","booking_status":"FULL",
         "readback_validation":"PASSED","booked_leg_count":2,"actual_sportybet_odds":None},
    ):
        monkeypatch.setattr(B, "create_or_reuse_generated_booking",
                            lambda games, board, **kwargs: dict(booking))
        result = M.eligible_manual_remainder(
            _verified_record([_leg(1, 2), _leg(2, 3)]),
            "5_odds", {}, now=NOW)
        assert result["selected"] is False
        assert "booking" not in result


def test_verified_append_only_edition_is_valid_source_and_never_mutated(monkeypatch):
    seen = _mock_live_booking(monkeypatch)
    record = _verified_record([_leg(1, -2), _leg(2, 3), _leg(3, 4)], edition=True)
    output = M.build_manual_remainders(now=NOW, records={"5_odds": record}, board={})
    assert output["available"] is True
    assert output["official_publication_unchanged"] is True
    assert output["tiers"]["5_odds"]["booking"]["share_code"] == "NEWCODE"
    assert record["code"] == "ORIGINAL"
    assert seen == [["fixture-2", "fixture-3"]]


def test_empty_store_never_fetches_bookmaker_board(monkeypatch):
    from leagues import sportybet
    monkeypatch.setattr(sportybet, "fetch_board",
                        lambda: (_ for _ in ()).throw(AssertionError("must not fetch")))
    output = M.build_manual_remainders(now=NOW, records={}, board=None)
    assert output["tiers"] == {}
    assert output["available"] is False


def test_latest_unavailable_booking_falls_back_to_verified_edition(monkeypatch):
    from leagues import sportybet
    seen = _mock_live_booking(monkeypatch)
    monkeypatch.setattr(B, "bookings_for", lambda day: {
        "5_odds": {"status": "unavailable", "share_code": None, "original_legs": []},
    })
    monkeypatch.setattr(B, "booking_editions_for", lambda day, tier:
        [_verified_record([_leg(1, -2), _leg(2, 3), _leg(3, 4)], edition=True)]
        if tier == "5_odds" else [])
    monkeypatch.setattr(sportybet, "fetch_board", lambda: {})
    output = M.build_manual_remainders(now=NOW)
    assert output["available"]
    assert output["tiers"]["5_odds"]["removed_leg_count"] == 1
    assert seen == [["fixture-2", "fixture-3"]]


def test_ten_minute_rule_keeps_fifteen_minute_manual_match_and_excludes_nine(monkeypatch):
    """Between 10 and 20 minutes is eligible for MANUAL rebooking only."""
    from leagues.availability import game_kickoff_lifecycle
    seen = []
    monkeypatch.setattr(B, "_revalidate_games", lambda games, board: (games, []))

    def booked(games, board, **kwargs):
        seen.append((list(g["match_id"] for g in games), kwargs["kickoff_buffer"]))
        return {
            "status": "active", "share_code": "NEW10MIN",
            "booking_status": "FULL", "readback_validation": "PASSED",
            "booked_leg_count": len(games), "partial": False,
            "actual_sportybet_odds": 2.06,
        }

    monkeypatch.setattr(B, "create_or_reuse_generated_booking", booked)
    manual = _verified_record([
        _leg(1, .15),       # 9 minutes: remove
        _leg(2, .25),       # 15 minutes: retain
        _leg(3, 2),         # 120 minutes: retain
    ])
    result = M.eligible_manual_remainder(manual, "5_odds", {}, now=NOW)
    assert result["selected"] is True
    assert result["remaining_leg_count"] == 2
    assert result["removed_leg_count"] == 1
    assert seen == [(["fixture-2", "fixture-3"], timedelta(minutes=10))]
    assert result["booking"]["share_code"] == "NEW10MIN"
    assert game_kickoff_lifecycle(_leg(2, .25), NOW) == "kickoff_buffer"
    assert game_kickoff_lifecycle(
        _leg(2, .25), NOW, booking_buffer=M.MANUAL_BOOKING_BUFFER,
    ) == "actionable"


def test_manual_cutoff_exactly_ten_minutes_still_removes_fixture(monkeypatch):
    seen = _mock_live_booking(monkeypatch)
    result = M.eligible_manual_remainder(
        _verified_record([_leg(1, 10 / 60), _leg(2, 2), _leg(3, 3)]),
        "10_odds", {}, now=NOW,
    )
    assert result["selected"] is True
    assert result["removed_leg_count"] == 1
    assert seen == [["fixture-2", "fixture-3"]]


def test_global_booking_still_has_twenty_minute_cutoff():
    from leagues.availability import BOOKING_BUFFER, game_kickoff_lifecycle
    assert BOOKING_BUFFER == timedelta(minutes=20)
    fifteen = _leg(1, .25)
    assert game_kickoff_lifecycle(fifteen, NOW) == "kickoff_buffer"
    assert game_kickoff_lifecycle(
        fifteen, NOW, booking_buffer=timedelta(minutes=10),
    ) == "actionable"
    # The shared create_booking path defaults to 20 minutes.
    standard = B.create_booking([fifteen], {}, now=NOW)
    assert standard["status"] == "kickoff_buffer"
    assert "20 minutes" in standard["reason"]


def test_create_booking_accepts_explicit_ten_minute_override(monkeypatch):
    """Allow reaching live mapping at 15m; never loosen the default buffer."""
    monkeypatch.setattr(B, "selections_for", lambda games, board: ([], []))
    fifteen = [_leg(1, .25)]
    result = B.create_booking(
        fifteen, {}, now=NOW,
        kickoff_buffer=timedelta(minutes=10),
    )
    assert result["status"] == "unavailable"
    assert result["booking_status"] == "UNAVAILABLE"
    # At exactly ten minutes, even the manually overridden path must stop.
    ten = B.create_booking(
        [_leg(1, 10 / 60)], {}, now=NOW,
        kickoff_buffer=timedelta(minutes=10),
    )
    assert ten["status"] == "kickoff_buffer"
    assert "10 minutes" in ten["reason"]


def _editorial_publication(legs: list[dict], *, code: str = "MANUAL10") -> dict:
    """The real editorial_tier_slips shape, not a tier_bookings row."""
    from leagues.booking import leg_fingerprint
    fingerprint = leg_fingerprint(legs)
    return {
        "editorial_manual": True,
        "source": "admin_curated",
        "games": [dict(g) for g in legs],
        "booking": {
            "status": "active",
            "booking_status": "FULL",
            "share_code": code,
            "readback_validation": "PASSED",
            "partial": False,
            "original_leg_count": len(legs),
            "booked_leg_count": len(legs),
            "leg_fingerprint": fingerprint,
            "booking_variant_fingerprint": fingerprint,
            "original_legs": [dict(g) for g in legs],
            "final_booked_legs": [dict(g) for g in legs],
        },
    }


def test_real_editorial_publication_is_primary_manual_rebooking_source(monkeypatch):
    from leagues import editorial_manual, sportybet
    seen = _mock_live_booking(monkeypatch)
    original = [_leg(1, -2), _leg(2, 3), _leg(3, 4)]
    published = _editorial_publication(original)
    monkeypatch.setattr(editorial_manual, "list_published",
                        lambda date: {"10_odds": published})
    # The legacy tier store has an unrelated automated ticket under same key.
    monkeypatch.setattr(B, "bookings_for", lambda day: {
        "10_odds": _verified_record([_leg(8, 2), _leg(9, 3)])})
    def legacy_editions(day, tier):
        if tier == "10_odds":
            raise AssertionError("Must not use legacy edition for the published tier")
        return []
    monkeypatch.setattr(B, "booking_editions_for", legacy_editions)
    monkeypatch.setattr(sportybet, "fetch_board", lambda: {})
    result = M.build_manual_remainders(now=NOW)
    assert result["available"] is True
    assert result["tiers"]["10_odds"]["remaining_leg_count"] == 2
    assert result["tiers"]["10_odds"]["removed_leg_count"] == 1
    assert result["tiers"]["10_odds"]["booking"]["share_code"] == "NEWCODE"
    assert seen == [["fixture-2", "fixture-3"]]
    assert published["booking"]["share_code"] == "MANUAL10"
    assert len(published["games"]) == 3


def test_bad_editorial_fingerprint_never_falls_back_to_unrelated_booking(monkeypatch):
    from leagues import editorial_manual, sportybet
    seen = _mock_live_booking(monkeypatch)
    published = _editorial_publication([_leg(1, 2), _leg(2, 3)])
    published["games"][0]["market"] = "over_2_5"
    monkeypatch.setattr(editorial_manual, "list_published",
                        lambda day: {"5_odds": published})
    monkeypatch.setattr(B, "bookings_for", lambda date: {
        "5_odds": _verified_record([_leg(3, 4), _leg(4, 5)])})
    monkeypatch.setattr(sportybet, "fetch_board",
                        lambda: (_ for _ in ()).throw(AssertionError("No bookmaker call")))
    result = M.build_manual_remainders(now=NOW)
    assert result["available"] is False
    assert result["tiers"] == {}
    assert "exact booking verification" in result["tier_reasons"]["5_odds"]
    assert seen == []


def test_editorial_source_rejects_partial_or_missing_readback():
    from copy import deepcopy
    original = _editorial_publication([_leg(1, 2), _leg(2, 3)])
    for field, value in (
        ("readback_validation", "FAILED"),
        ("booked_leg_count", 1),
        ("booking_status", "PARTIAL"),
        ("share_code", None),
    ):
        altered = deepcopy(original)
        altered["booking"][field] = value
        assert M._verified_editorial_source(altered) is None


def test_reduced_ticket_failure_describes_why_without_overwriting_original(monkeypatch):
    from leagues import editorial_manual, sportybet
    original = [_leg(1, -2), _leg(2, .15)]
    published = _editorial_publication(original)
    monkeypatch.setattr(editorial_manual, "list_published",
                        lambda date: {"5_odds": published})
    monkeypatch.setattr(B, "bookings_for", lambda day: {})
    monkeypatch.setattr(sportybet, "fetch_board", lambda: {})
    result = M.build_manual_remainders(now=NOW)
    assert result["available"] is False
    assert "Too few" in result["tier_reasons"]["5_odds"]
    assert result["official_publication_unchanged"] is True
    assert published["booking"]["share_code"] == "MANUAL10"
