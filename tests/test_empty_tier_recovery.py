import json
import threading

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from leagues import empty_tier_recovery as recovery
from leagues import daily_feed
from leagues.picks_db import Base, DailyCard, PublishedSlip
from leagues import picks_db


def _game(name="A"):
    return {"match_id": name, "home_team": f"Home {name}", "away_team": f"Away {name}",
            "market": "over_1_5", "prediction": "Over 1.5", "odds": 1.5,
            "confidence": .75, "selection_probability": .75,
            "safe_tier_eligible": True, "market_floor_eligible": True,
            "market_trust_state": "TRUSTED", "bookable": True,
            "odds_are_real": True, "risk_adjusted_return": 1.02,
            "kickoff": "2099-01-01T12:00:00Z", "started": False}


def _candidate():
    # A genuine seven-leg 10 Odds candidate. A 1.5x single is NOT 10 Odds.
    games = [_game(f"fixture-{i}") for i in range(7)]
    return {"selected": True, "games": games, "total_odds": round(1.5 ** 7, 2),
            "hit_probability": .75 ** 7, "presentation": "accumulator"}


def _booking():
    return {"status": "active", "booking_status": "FULL", "readback_validation": "PASSED",
            "share_code": "ABC123", "share_url": "https://example.test", "legs": 7,
            "original_leg_count": 7, "booked_leg_count": 7, "excluded_leg_count": 0,
            "replacement_count": 0, "predicted_tier_odds": round(1.5 ** 7, 2),
            "actual_sportybet_odds": round(1.5 ** 7, 2),
            "final_booked_legs": _candidate()["games"]}


def _db(monkeypatch):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[DailyCard.__table__, PublishedSlip.__table__])
    # Runtime recovery self-heals this additive provenance table.
    monkeypatch.setattr(recovery, "engine", eng)
    return eng


def _card(eng, payload):
    with sessionmaker(bind=eng)() as session:
        session.add(DailyCard(publish_date="2099-01-01", payload=json.dumps(payload)))
        session.commit()


def test_atomic_empty_tier_recovery_persists_card_slip_booking_and_provenance(monkeypatch):
    eng = _db(monkeypatch)
    banker = {"selected": True, "games": [_game("bank")], "total_odds": 1.5}
    _card(eng, {"banker": banker, "10_odds": {"selected": False, "games": []}})
    result = recovery.recover_empty_tier(publish_date="2099-01-01", tier="10_odds",
                                         candidate=_candidate(), booking=_booking(),
                                         decision_snapshot_id="snap")
    assert result["status"] == "RECOVERED"
    with eng.begin() as conn:
        card = json.loads(conn.execute(text("SELECT payload FROM daily_cards")).scalar_one())
        assert card["banker"] == banker
        assert card["10_odds"]["selected"] is True
        assert conn.execute(text("SELECT count(*) FROM published_slips")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM tier_bookings")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM tier_recovery_provenance")).scalar_one() == 1


def test_recovery_is_idempotent_and_rejects_failed_booking(monkeypatch):
    eng = _db(monkeypatch)
    _card(eng, {"10_odds": {"selected": False, "games": []}})
    bad = {**_booking(), "readback_validation": "FAILED"}
    assert recovery.recover_empty_tier(
        publish_date="2099-01-01", tier="10_odds", candidate=_candidate(),
        booking=bad)["status"] == "BLOCKED"
    with eng.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM published_slips")).scalar_one() == 0
    good = recovery.recover_empty_tier(publish_date="2099-01-01", tier="10_odds",
                                       candidate=_candidate(), booking=_booking())
    assert good["status"] == "RECOVERED"
    assert recovery.recover_empty_tier(publish_date="2099-01-01", tier="10_odds",
                                       candidate=_candidate(), booking=_booking())["status"] == "ALREADY_FILLED"


def test_prepared_only_recovery_never_runs_full_pipeline(monkeypatch):
    monkeypatch.setattr(daily_feed, "_load_locked", lambda _date: {
        "10_odds": {"selected": False, "games": []},
    })
    monkeypatch.setattr(daily_feed, "_publish_date", lambda: "2099-01-01")
    monkeypatch.setattr("leagues.engine.prepared_board_status", lambda **_: {"ready": True})
    monkeypatch.setattr("leagues.engine.prepared_pipeline", lambda **_: ([], []))
    monkeypatch.setattr("leagues.engine.run_pipeline", lambda **_: (_ for _ in ()).throw(AssertionError("no rebuild")))
    result = daily_feed.recover_today_empty_tiers()
    assert result["status"] == "COMPLETE"
    assert result["tiers"]["10_odds"]["status"] == "UNREACHABLE"


def test_failure_after_slip_insert_rolls_back_everything(monkeypatch):
    eng = _db(monkeypatch)
    _card(eng, {"10_odds": {"selected": False, "games": []}})
    monkeypatch.setattr(recovery, "_store_booking", lambda *_: (_ for _ in ()).throw(RuntimeError("db fail")))
    assert recovery.recover_empty_tier(
        publish_date="2099-01-01", tier="10_odds", candidate=_candidate(),
        booking=_booking())["status"] == "FAILED"
    with eng.begin() as conn:
        payload = json.loads(conn.execute(text("SELECT payload FROM daily_cards")).scalar_one())
        assert payload["10_odds"]["selected"] is False
        assert conn.execute(text("SELECT count(*) FROM published_slips")).scalar_one() == 0


def test_recovered_slip_uses_normal_settlement_path(monkeypatch):
    eng = _db(monkeypatch)
    _card(eng, {"10_odds": {"selected": False, "games": []}})
    assert recovery.recover_empty_tier(
        publish_date="2099-01-01", tier="10_odds", candidate=_candidate(),
        booking=_booking())["status"] == "RECOVERED"
    monkeypatch.setattr(picks_db, "SessionLocal", sessionmaker(bind=eng))
    with eng.begin() as conn:
        slip_id = conn.execute(text("SELECT id FROM published_slips")).scalar_one()
    assert picks_db.settle_slip(slip_id, ["won"], [{"settlement_evidence": {"score": "2-0"}}]) == "won"


def test_two_independent_threads_publish_empty_tier_once(monkeypatch, tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'recovery.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng, tables=[DailyCard.__table__, PublishedSlip.__table__])
    monkeypatch.setattr(recovery, "engine", eng)
    _card(eng, {"10_odds": {"selected": False, "games": []}})
    gate = threading.Barrier(2)
    results = []
    def attempt():
        gate.wait()
        results.append(recovery.recover_empty_tier(publish_date="2099-01-01", tier="10_odds", candidate=_candidate(), booking=_booking())["status"])
    workers = [threading.Thread(target=attempt) for _ in range(2)]
    [worker.start() for worker in workers]
    [worker.join() for worker in workers]
    assert sorted(results) == ["ALREADY_FILLED", "RECOVERED"]
    with eng.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM published_slips")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM tier_bookings")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM tier_recovery_provenance")).scalar_one() == 1


def test_ten_odds_recovery_rejects_repriced_nine_odds(monkeypatch):
    eng = _db(monkeypatch)
    _card(eng, {"10_odds": {"selected": False, "games": []}})
    booking = {**_booking(), "actual_sportybet_odds": 9.8}
    result = recovery.recover_empty_tier(
        publish_date="2099-01-01", tier="10_odds",
        candidate=_candidate(), booking=booking)
    assert result["status"] == "BLOCKED"
    with eng.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM published_slips")).scalar_one() == 0


def test_recovery_never_reuses_an_over_one_five_fixture(monkeypatch):
    eng = _db(monkeypatch)
    _card(eng, {
        "over_1_5": {"selected": True, "games": [_game("fixture-0")]},
        "10_odds": {"selected": False, "games": []},
    })
    result = recovery.recover_empty_tier(
        publish_date="2099-01-01", tier="10_odds",
        candidate=_candidate(), booking=_booking())
    assert result["status"] == "FIXTURE_CONFLICT"
    with eng.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM published_slips")).scalar_one() == 0


def test_recovery_rejects_stale_or_unverified_selection(monkeypatch):
    eng = _db(monkeypatch)
    _card(eng, {"10_odds": {"selected": False, "games": []}})
    selected = _candidate()
    selected["games"][0]["kickoff"] = "2000-01-01T12:00:00Z"
    assert recovery.recover_empty_tier(
        publish_date="2099-01-01", tier="10_odds",
        candidate=selected, booking=_booking())["status"] == "BLOCKED"
    untrusted = _candidate()
    untrusted["games"][0]["safe_tier_eligible"] = False
    assert recovery.recover_empty_tier(
        publish_date="2099-01-01", tier="10_odds",
        candidate=untrusted, booking=_booking())["status"] == "BLOCKED"
