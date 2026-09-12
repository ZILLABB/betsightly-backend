from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.pool import QueuePool
import pytest

from leagues import builder_editor, builder_revisions


def _result(*ids, odds=10.2, active=True):
    games = [
        {
            "selection_id": selection,
            "match_id": f"match-{selection}",
            "fixture_id": index,
            "home_team": f"Home {index}",
            "away_team": f"Away {index}",
            "market": "over_1_5",
            "odds": 1.5,
        }
        for index, selection in enumerate(ids, 1)
    ]
    return {
        "status": "success", "target": 10, "odds": odds,
        "legs": len(games), "games": games,
        "booking": ({"status": "active", "share_code": "CODE1",
                     "booking_status": "FULL", "readback_validation": "PASSED"}
                    if active else {"status": "unavailable", "share_code": None}),
    }


@pytest.fixture
def revision_db(monkeypatch):
    db = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(builder_revisions, "engine", db)
    builder_revisions.metadata.create_all(db)
    return db


def test_revision_history_is_immutable_and_supersedes_old_code(revision_db):
    initial = builder_revisions.create_initial_run(10, "week", _result("a", "b"))
    revised = _result("a", "c")
    stored = builder_revisions.persist_revision(
        run_id=initial["builder_run_id"], edit_token=initial["edit_token"],
        expected_revision=1, request_id="request-0001",
        action="replace_selection", action_target={"selection_id": "b"},
        result=revised, locked_selection_ids={"a"},
        excluded_fixture_ids=set(), excluded_selection_ids={"b"},
    )

    assert stored["revision"] == 2
    assert stored["locked_selection_ids"] == ["a"]
    with revision_db.begin() as conn:
        revisions = conn.execute(select(builder_revisions.builder_revisions))
        revisions = revisions.mappings().all()
        bookings = conn.execute(select(builder_revisions.builder_revision_bookings))
        bookings = bookings.mappings().all()
    assert len(revisions) == 2
    assert "\"selection_id\":\"b\"" in revisions[0]["result_payload"]
    assert [row["status"] for row in bookings] == ["superseded", "active"]


def test_stale_revision_is_rejected(revision_db):
    initial = builder_revisions.create_initial_run(10, "week", _result("a"))
    builder_revisions.persist_revision(
        run_id=initial["builder_run_id"], edit_token=initial["edit_token"],
        expected_revision=1, request_id="request-0002", action="lock_selection",
        action_target={}, result=_result("a"), locked_selection_ids={"a"},
        excluded_fixture_ids=set(), excluded_selection_ids=set(),
    )
    with pytest.raises(builder_revisions.StaleBuilderRevision):
        builder_revisions.persist_revision(
            run_id=initial["builder_run_id"], edit_token=initial["edit_token"],
            expected_revision=1, request_id="request-0003",
            action="remove_selection", action_target={}, result=_result("b"),
            locked_selection_ids=set(), excluded_fixture_ids=set(),
            excluded_selection_ids={"a"},
        )


def test_repeated_request_id_returns_same_revision(revision_db):
    initial = builder_revisions.create_initial_run(10, "week", _result("a"))
    builder_revisions.persist_revision(
        run_id=initial["builder_run_id"], edit_token=initial["edit_token"],
        expected_revision=1, request_id="request-0004", action="lock_selection",
        action_target={}, result=_result("a"), locked_selection_ids={"a"},
        excluded_fixture_ids=set(), excluded_selection_ids=set(),
    )
    replay = builder_revisions.idempotent_result(
        initial["builder_run_id"], initial["edit_token"], "request-0004"
    )
    assert replay["revision"] == 2
    assert replay["idempotent_replay"] is True


def test_invalid_edit_token_is_rejected(revision_db):
    initial = builder_revisions.create_initial_run(10, "week", _result("a"))
    with pytest.raises(builder_revisions.BuilderRunForbidden):
        builder_revisions.load_state(initial["builder_run_id"], "x" * 32)


def test_repeated_revision_operations_return_connections_to_pool(monkeypatch):
    db = create_engine("sqlite:///:memory:", poolclass=QueuePool, pool_size=2)
    monkeypatch.setattr(builder_revisions, "engine", db)
    builder_revisions.metadata.create_all(db)
    baseline = db.pool.checkedout()
    for _ in range(12):
        initial = builder_revisions.create_initial_run(10, "week", _result("a"))
        builder_revisions.load_state(
            initial["builder_run_id"], initial["edit_token"]
        )
    assert db.pool.checkedout() == baseline


def test_builder_constraints_preserve_lock_and_exclude_fixture(monkeypatch):
    def _pick(match_id, odds, confidence, market="over_1_5",
              market_group="goals"):
        return {
            "match_id": match_id, "market": market,
            "market_group": market_group, "odds": odds,
            "confidence": confidence, "bookable": True,
            "odds_are_real": True,
            "market_implied_probability": min(confidence, 1 / odds),
            "expected_value": min(.1, confidence * odds - 1),
            "safe_tier_eligible": True, "calibration_sample": 25,
            "sportybet_availability": {
                "status": "BOOKABLE", "sportybet_available": True,
                "board_snapshot_id": "test",
            },
            "_fixture": {"commence_time": "2099-01-01T12:00:00Z"},
            "_model": {"expected_goals": {
                "home": 1.5, "away": 1.5, "total": 3.0,
            }},
        }

    def _accept_trust(pick):
        return {
            "accepted": True,
            "evidence_adjusted_probability": pick["confidence"],
            "lower_reliability_bound": pick["confidence"] - .04,
            "evidence_strength": .9, "evidence_state": "SUPPORTED",
            "trust_score": 90, "trust_grade": "A", "rejection_reasons": [],
        }

    monkeypatch.setattr("leagues.leg_trust.evaluate_leg_trust", _accept_trust)
    locked = _pick("locked", 2, .82, market_group="goals_over_1_5")
    excluded = _pick("excluded", 3, .90, market="under_4_5",
                     market_group="goals_under_4_5")
    replacement = _pick("replacement", 2, .80, market="home_or_draw",
                        market_group="double_chance")
    for pick in (locked, excluded, replacement):
        pick["selection_id"] = pick["match_id"]
        pick["_fixture"].update(
            home={"name": f"{pick['match_id']} home"},
            away={"name": f"{pick['match_id']} away"},
        )

    built = builder_editor.build_slip(
        4, pool=[locked, excluded, replacement], market_cap=3,
        locked_selection_ids={"locked"},
        excluded_fixture_ids={"excluded"},
    )
    assert built["ok"]
    assert {pick["match_id"] for pick in built["picks"]} == {
        "locked", "replacement",
    }


def test_custom_target_is_bounded_at_200():
    from leagues.slip_builder import MAX_TARGET
    assert MAX_TARGET == 200


def test_exclusion_and_lock_constraints_persist_across_editor_revisions(
        revision_db, monkeypatch):
    first = builder_revisions.create_initial_run(
        10, "week", _result("a", "b")
    )
    calls = []
    pool = [
        {"selection_id": value, "match_id": f"match-{value}"}
        for value in ("a", "b", "c", "d")
    ]
    monkeypatch.setattr(
        builder_editor, "prepared_bookable_pool",
        lambda *args, **kwargs: ({"__meta__": {}}, pool, {"board_lookup": 1}),
    )
    monkeypatch.setattr(
        "leagues.engine.prepared_board_status",
        lambda **kwargs: {"ready": True, "degraded": False, "complete": True},
    )
    monkeypatch.setattr(
        builder_editor, "approved_builder_candidates",
        lambda candidates: (candidates, {}),
    )

    def fake_build(target, **kwargs):
        calls.append(kwargs)
        return {"ok": True, "picks": ["a", "d"], "odds": 10.1}

    monkeypatch.setattr(builder_editor, "build_slip", fake_build)
    monkeypatch.setattr(
        builder_editor, "_public_result_from_build",
        lambda target, horizon, built, board, timings: _result(
            *built["picks"], odds=built["odds"]
        ),
    )

    locked = builder_editor.revise(
        run_id=first["builder_run_id"], edit_token=first["edit_token"],
        revision=1, request_id="editor-request-1", action="lock_selection",
        selection_id="a", fixture_id="match-a",
    )
    excluded = builder_editor.revise(
        run_id=first["builder_run_id"], edit_token=first["edit_token"],
        revision=2, request_id="editor-request-2", action="exclude_fixture",
        selection_id="b", fixture_id="match-b",
    )

    assert locked["locked_selection_ids"] == ["a"]
    assert excluded["locked_selection_ids"] == ["a"]
    assert excluded["excluded_fixture_ids"] == ["match-b"]
    assert calls[0]["locked_selection_ids"] == {"a"}
    assert calls[0]["excluded_fixture_ids"] == {"match-b"}


def test_lock_and_unlock_are_local_and_do_not_wait_for_live_board(
        revision_db, monkeypatch):
    initial = builder_revisions.create_initial_run(10, "week", _result("a"))
    monkeypatch.setattr(
        builder_editor, "prepared_bookable_pool",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("lock operations must not rebuild the board")
        ),
    )

    locked = builder_editor.revise(
        run_id=initial["builder_run_id"], edit_token=initial["edit_token"],
        revision=1, request_id="local-lock-0001", action="lock_selection",
        selection_id="a", fixture_id="match-a",
    )
    unlocked = builder_editor.revise(
        run_id=initial["builder_run_id"], edit_token=initial["edit_token"],
        revision=2, request_id="local-lock-0002", action="unlock_selection",
        selection_id="a", fixture_id="match-a",
    )

    assert locked["locked_selection_ids"] == ["a"]
    assert unlocked["locked_selection_ids"] == []
    assert unlocked["booking"]["share_code"] == "CODE1"


def test_safer_market_must_remain_on_fixture_and_improve_survival(monkeypatch):
    current = {
        "selection_id": "current", "match_id": "fixture-1",
        "market": "home_win", "odds": 1.8, "confidence": .66,
        "evidence_adjusted_probability": .66,
        "trust": {"lower_reliability_bound": .62},
    }
    same_safer = {
        "selection_id": "safer", "match_id": "fixture-1",
        "market": "home_or_draw", "odds": 1.3, "confidence": .76,
        "evidence_adjusted_probability": .76,
        "quality_score": 80,
    }
    other = {
        "selection_id": "other", "match_id": "fixture-2",
        "market": "under_4_5", "odds": 1.2, "confidence": .90,
        "evidence_adjusted_probability": .90,
        "quality_score": 90,
    }
    assert builder_editor._safer_candidate(
        current, [current, same_safer, other]
    ) is same_safer


def test_no_marginal_same_fixture_market_is_presented_as_safer():
    current = {
        "selection_id": "current", "match_id": "fixture-1",
        "market": "home_win", "odds": 1.8, "confidence": .70,
        "evidence_adjusted_probability": .70,
        "trust": {"lower_reliability_bound": .70},
    }
    marginal = {
        "selection_id": "marginal", "match_id": "fixture-1",
        "market": "home_or_draw", "odds": 1.5, "confidence": .715,
        "evidence_adjusted_probability": .715, "quality_score": 90,
    }
    assert builder_editor._safer_candidate(current, [current, marginal]) is None


def test_failed_replace_is_persisted_idempotently_without_excluding_fixture(
        revision_db, monkeypatch):
    initial = builder_revisions.create_initial_run(10, "week", _result("a"))
    monkeypatch.setattr(
        builder_editor, "prepared_bookable_pool",
        lambda *args, **kwargs: ({}, [], {"board_lookup": 1}),
    )
    monkeypatch.setattr(
        "leagues.engine.prepared_board_status",
        lambda **kwargs: {"ready": True, "degraded": False, "complete": True},
    )
    monkeypatch.setattr(
        builder_editor, "approved_builder_candidates",
        lambda candidates: (candidates, {}),
    )
    monkeypatch.setattr(
        builder_editor, "_replace_fixture_locally",
        lambda **kwargs: (None, None),
    )
    kwargs = dict(
        run_id=initial["builder_run_id"], edit_token=initial["edit_token"],
        revision=1, request_id="replace-no-change",
        action="replace_selection", selection_id="a", fixture_id="match-a",
    )
    first = builder_editor.revise(**kwargs)
    replay = builder_editor.revise(**kwargs)
    assert first["revision"] == replay["revision"] == 2
    assert replay["idempotent_replay"] is True
    assert first["revision_status"] == "no_change"
    assert first["excluded_fixture_ids"] == []
