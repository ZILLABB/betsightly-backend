import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, select

from leagues import decision_archive


def _pick(odds=1.5):
    fixture = {
        "match_id": "fx-1", "league": "Test League", "league_slug": "test",
        "commence_time": "2026-09-11T12:00:00Z",
        "home": {"name": "Home"}, "away": {"name": "Away"},
    }
    return {
        "match_id": "fx-1", "market": "over_1_5", "market_group": "goals",
        "prediction": "Over 1.5 Goals", "raw_confidence": .78,
        "confidence": .75, "selection_probability": .72,
        "lower_reliability_bound": .69, "odds": odds,
        "odds_are_real": True, "odds_provider": "SportyBet",
        "market_implied_probability": .70, "bookable": True,
        "sportybet_availability": {"status": "EXACT"},
        "market_floor_eligible": True, "safe_tier_eligible": True,
        "public_rank": 1, "model_rank": 2, "quality_score": 80,
        "market_trust_state": "TRUSTED", "quality_classification": "STRONG",
        "selection_reason_codes": ["PUBLIC_RANK_1"],
        "trust": {"trust_grade": "A", "trust_score": 82,
                  "rejection_reasons": []},
        "_fixture": fixture,
        "_model": {"expected_goals": {"home": 1.4, "away": 1.0, "total": 2.4}},
    }


def _db(monkeypatch):
    db = create_engine("sqlite://")
    monkeypatch.setattr(decision_archive, "engine", db)
    decision_archive.metadata.create_all(db)
    return db


def test_snapshot_is_idempotent_immutable_and_retains_decision_facts(monkeypatch):
    db = _db(monkeypatch)
    monkeypatch.setattr(
        "leagues.fixture_ranker.canonical_fixture_recommendations",
        lambda picks, **kwargs: picks,
    )
    pick = _pick()
    first = decision_archive.archive_board(
        [pick], [pick["_fixture"]], horizon=7,
        provider={"complete": False}, calibration={"version": "cal-v1"},
        generated_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    second = decision_archive.archive_board(
        [pick], [pick["_fixture"]], horizon=7,
        provider={"complete": False}, calibration={"version": "cal-v1"},
        generated_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    assert first == second == pick["_board_snapshot_id"]
    with db.begin() as conn:
        rows = conn.execute(select(decision_archive.board_snapshots)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["provider_state"] == "degraded"
    board = decision_archive.load_board(first)
    candidate = board["candidates"][0]
    assert candidate["public_rank"] == 1
    assert candidate["model_rank"] == 2
    assert candidate["bookable"] is True
    assert candidate["lower_reliability_bound"] == .69

    pick["odds"] = 9.99
    assert decision_archive.load_board(first)["candidates"][0]["odds"] == 1.5


def test_replay_is_archived_only_deterministic_and_never_publishable(monkeypatch):
    _db(monkeypatch)
    monkeypatch.setattr(
        "leagues.fixture_ranker.canonical_fixture_recommendations",
        lambda picks, **kwargs: picks,
    )
    pick = _pick()
    snapshot = decision_archive.archive_board(
        [pick], [pick["_fixture"]], horizon=7,
        generated_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    first = decision_archive.replay(snapshot, "SHADOW_POLICY")
    second = decision_archive.replay(snapshot, "SHADOW_POLICY")
    assert first == second
    assert first["publishable"] is False
    assert first["bookable"] is False
    assert first["settle_officially"] is False
    assert first["recommendations"][0]["fixture_id"] == "fx-1"


def test_daily_counterfactual_and_builder_edits_are_idempotent(monkeypatch):
    db = _db(monkeypatch)
    # Foreign keys are intentionally not required: operational writes remain
    # non-blocking even if an archive write failed before publication.
    snapshot = "a" * 64
    decision_archive.record_daily(
        snapshot, "2026-09-10",
        {"5_odds": ([_pick()], 4.8, .31)},
        {"5_odds": {"result_status": "QUALITY_CAPPED", "games": [],
                    "booking_rule": {"target": 5.0}}},
        {"products": {"5_odds": {"decision": "INDEPENDENT_BEST"}}},
    )
    decision_archive.record_daily(
        snapshot, "2026-09-10",
        {"5_odds": ([_pick()], 4.8, .31)},
        {"5_odds": {"result_status": "QUALITY_CAPPED", "games": [],
                    "booking_rule": {"target": 5.0}}},
        {"products": {}},
    )
    for _ in range(2):
        decision_archive.record_builder_event(
            run_id="run", snapshot_id=snapshot, request_id="request-1",
            revision_before=1, revision_after=2, action="replace",
            action_target={"fixture_id": "fx-1", "selection_id": "old",
                           "replacement_selection_id": "new"},
            requested_target=10, achieved_before=9.1, achieved_after=8.8,
        )
    with db.begin() as conn:
        products = conn.execute(select(decision_archive.product_decisions)).mappings().all()
        edits = conn.execute(select(decision_archive.builder_edit_events)).mappings().all()
    assert len(products) == 1
    assert json.loads(products[0]["independent_payload"])["odds"] == 4.8
    assert len(edits) == 1
    assert edits[0]["replacement_selection_id"] == "new"


def test_quality_report_uses_readiness_guardrails(monkeypatch):
    _db(monkeypatch)
    report = decision_archive.quality_report()
    assert report["readiness"] == "thin"
    assert report["minimum_policy_comparison_snapshots"] == 30
    assert report["policies"]["adaptive_trust_enabled"] is False


def test_settled_metrics_count_legs_once_and_keep_ranks_separate(monkeypatch):
    history = [{
        "category": "2_odds",
        "picks": [{"match_id": "fx-1", "market": "over_1_5",
                   "status": "won", "confidence": .75, "public_rank": 1,
                   "quality_classification": "STRONG", "league": "League"}],
    }, {
        # Same official identity repeated by a readback/history join.
        "category": "2_odds",
        "picks": [{"match_id": "fx-1", "market": "over_1_5",
                   "status": "won", "confidence": .75, "public_rank": 1,
                   "quality_classification": "STRONG", "league": "League"}],
    }]
    monkeypatch.setattr("leagues.picks_db.get_history", lambda limit_days: history)
    metrics = decision_archive._settled_quality_metrics()
    assert metrics["legs"] == 1
    assert metrics["ranks"]["1"]["hit_rate"] == 1.0
    assert metrics["markets"]["over_1_5"]["brier"] == .0625
    assert metrics["markets"]["over_1_5"]["readiness"] == "thin"
