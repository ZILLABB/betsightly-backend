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
    record = _verified_record([_leg(1, -1), _leg(2, .2), _leg(3, 2)])
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
