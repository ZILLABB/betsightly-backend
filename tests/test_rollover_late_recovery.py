"""Settlement must unblock a new rollover only with safe, available legs."""
from datetime import datetime, timezone
from leagues import rollover_late_recovery as late
from leagues import daily_feed as feed
from leagues import rollover_db
from leagues import engine
from leagues import booking
from leagues import fixture_ranker

NOW = datetime(2026, 10, 17, 8, 0, tzinfo=timezone.utc)


def _pick(mid, home, away, kickoff="2026-10-17T15:00:00Z"):
    return {
        "match_id": mid, "bookable": True, "safe_tier_eligible": True,
        "_fixture": {
            "home": {"name": home}, "away": {"name": away},
            "commence_time": kickoff,
        },
    }


def setup(monkeypatch, status="lost"):
    monkeypatch.setattr(feed, "_publish_date", lambda: "2026-10-17")
    monkeypatch.setattr(feed, "_load_locked", lambda _: {
        "banker": {"selected": True, "games": [{
            "match_id": "reserved", "home_team": "Gamma", "away_team": "Delta",
        }]},
    })
    monkeypatch.setattr(rollover_db, "load_chain", lambda day: {
        "start_date": "2026-10-15",
        "days": [
            {"date": "2026-10-15", "day_number": 1, "status": "won"},
            {"date": "2026-10-16", "day_number": 2, "status": status},
        ],
    })
    monkeypatch.setattr(engine, "prepared_board_status", lambda days_ahead: {
        "ready": True, "age_seconds": 50,
    })
    monkeypatch.setattr(engine, "prepared_pipeline", lambda days_ahead: ([
        _pick("reserved", "Gamma", "Delta"),
        _pick("some-other-id", "Gamma", "Different"),
        _pick("good", "Epsilon", "Zeta"),
    ], []))
    monkeypatch.setattr(booking, "bookings_for", lambda date: {})
    monkeypatch.setattr(
        fixture_ranker, "canonical_fixture_recommendations",
        lambda picks, include_all_eligible: picks,
    )
    monkeypatch.setattr(
        feed, "filter_official_candidates", lambda picks, tier: (picks, []),
    )


def test_unresolved_previous_day_never_attempts_model_selection(monkeypatch):
    setup(monkeypatch, "pending")
    monkeypatch.setattr(feed, "_build_rollover",
                        lambda *a: (_ for _ in ()).throw(AssertionError("no writes")))
    assert late.recover_once(at=NOW)["status"] == "CHAIN_BLOCKED"


def test_lost_prior_day_automatically_considers_new_day_one_only(monkeypatch):
    setup(monkeypatch)
    called = []
    monkeypatch.setattr(feed, "_build_rollover", lambda picks, day: (
        called.append((picks, day)) or {
            "selected": True, "games": [{"match_id": "good"}],
            "chain": [{"day_number": 1}], "total_odds": 2.2,
        }))
    monkeypatch.setattr(booking, "book_card",
                        lambda day, cats: {"booked": ["rollover"], "failed": []})
    result = late.recover_once(at=NOW)
    assert result["status"] == "PUBLISHED" and result["booking_created"]
    assert [p["match_id"] for p in called[0][0]] == ["good"]
    assert called[0][1] == "2026-10-17"


def test_without_qualified_remaining_match_no_booking_or_new_stage(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(engine, "prepared_pipeline", lambda days_ahead: (
        [_pick("reserved", "Gamma", "Delta")], []))
    monkeypatch.setattr(feed, "_build_rollover",
                        lambda *a: (_ for _ in ()).throw(AssertionError("no stage")))
    assert late.recover_once(at=NOW)["status"] == "NO_SAFE_BOOKABLE_PICKS"


def test_premature_recovery_before_8am_wat_is_blocked(monkeypatch):
    setup(monkeypatch)
    assert late.recover_once(
        at=datetime(2026, 10, 17, 6, 59, tzinfo=timezone.utc)
    )["status"] == "BEFORE_PUBLICATION"


def test_old_prepared_snapshot_cannot_publish_new_stage(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(engine, "prepared_board_status", lambda days_ahead: {
        "ready": True, "age_seconds": 22000,
    })
    assert late.recover_once(at=NOW)["status"] == "PREPARED_BOARD_UNAVAILABLE"
