from sqlalchemy import create_engine
import pytest

from leagues import football_first_shadow_observations as obs


def _db():
    db = create_engine("sqlite:///:memory:")
    obs.ensure_table(db)
    return db


def _patch_empty_model(monkeypatch):
    monkeypatch.setattr(
        obs.shadow,
        "status",
        lambda: {"model_version": "shadow-v1", "shadow_only": True},
    )
    monkeypatch.setattr(
        obs,
        "collection_allowed",
        lambda: (True, "enabled"),
    )


def test_review_packet_tracks_progress_without_promoting(monkeypatch):
    db = _db()
    _patch_empty_model(monkeypatch)
    packet = obs.review_packet(db_engine=db)
    assert packet["review_gate"]["eligible"] is False
    assert packet["review_gate"]["current_settled"] == 0
    assert packet["review_gate"]["remaining_to_minimum"] == 300
    assert packet["promotion_effective"] is False
    assert packet["automatic_promotion"] is False


def test_approval_fails_closed_before_evidence_gate(monkeypatch):
    db = _db()
    _patch_empty_model(monkeypatch)
    with pytest.raises(ValueError, match="promotion_review_gate_not_met"):
        obs.record_review(
            "APPROVE_FOR_PROMOTION_IMPLEMENTATION",
            reviewer="tester",
            db_engine=db,
        )


def test_keep_champion_review_never_changes_live_model(monkeypatch):
    db = _db()
    _patch_empty_model(monkeypatch)
    result = obs.record_review(
        "KEEP_CHAMPION",
        reviewer="tester",
        note="continue collecting",
        db_engine=db,
    )
    assert result["status"] == "RECORDED"
    assert result["review"]["decision"] == "KEEP_CHAMPION"
    assert result["promotion_effective"] is False
    assert result["live_adjustment_allowed"] is False
    assert obs.latest_review(db_engine=db)["decision"] == "KEEP_CHAMPION"


def test_eligible_approval_only_allows_future_implementation(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        obs,
        "review_packet",
        lambda db_engine=db: {
            "model": {"model_version": "shadow-v1"},
            "evidence": {
                "comparison": {
                    "n": 325,
                    "status": "ELIGIBLE_FOR_HUMAN_REVIEW",
                }
            },
            "review_gate": {"eligible": True},
        },
    )
    result = obs.record_review(
        "APPROVE_FOR_PROMOTION_IMPLEMENTATION",
        reviewer="tester",
        note="evidence gate passed",
        db_engine=db,
    )
    assert result["status"] == "RECORDED"
    assert result["promotion_effective"] is False
    assert result["next_action"] == "separate_code_review_and_deployment_required"


def test_async_settlement_throttles_duplicate_triggers(monkeypatch):
    db = _db()
    calls = []

    def fake_settle(**kwargs):
        calls.append(1)
        return {"status": "SUCCESS", "checked": 0, "settled": 0, "pending": 0}

    class ImmediateThread:
        def __init__(self, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(obs, "settle_pending_observations", fake_settle)
    monkeypatch.setattr(obs.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(obs, "_SETTLEMENT_LAST_STARTED", 0.0)

    first = obs.start_settlement_async(db_engine=db)
    second = obs.start_settlement_async(db_engine=db)
    assert first["status"] == "STARTED"
    assert second["status"] == "SKIPPED"
    assert second["reason"] == "cooldown"
    assert len(calls) == 1


def test_shadow_report_exposes_300_match_progress(monkeypatch):
    db = _db()
    _patch_empty_model(monkeypatch)
    report = obs.shadow_report(db_engine=db)
    assert report["evidence_progress"]["minimum_for_human_review"] == 300
    assert report["evidence_progress"]["settled"] == 0
    assert report["evidence_progress"]["remaining"] == 300
    assert report["evidence_progress"]["percent_complete"] == 0.0
    assert report["automatic_promotion"] is False
