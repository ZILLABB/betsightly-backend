from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from leagues import jev_shadow_ledger as ledger
from leagues import jev_shadow_worker as worker

NOW = datetime(2026, 10, 28, 10, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=5)
CONFIG = {
    "ENVIRONMENT": "staging",
    "BETSIGHTLY_JEV_SHADOW_ENABLED": "true",
    "BETSIGHTLY_JEV_API_CALLS_ENABLED": "true",
    "BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED": "true",
    "AI_GATEWAY_API_KEY": "test-only",
}


def envelope():
    return {
        "status": "ready_for_shadow_review",
        "publication_authority": False,
        "shadow_only": True,
        "state_fingerprint": "a" * 64,
        "state": {
            "as_of": NOW.isoformat(),
            "sport": "football",
            "selection": {"fixture_id": "espn-1", "market": "over_1_5",
                          "kickoff_utc": KO.isoformat()},
            "evidence": [{"type": "competition_schedule",
                         "source_id": "openligadb:bl1:991",
                         "claim": "Upcoming game"}],
        },
    }


@pytest.fixture
def engine():
    return create_engine("sqlite+pysqlite:///:memory:")


def test_new_ledger_has_zero_entries_and_does_not_create_table_on_get(engine):
    assert not ledger.table_exists(engine)
    assert ledger.summary(db_engine=engine)["total"] == 0
    assert not ledger.table_exists(engine)


def test_first_write_claim_and_idempotent_retries(engine):
    snap = envelope()
    first = ledger.claim(snap, db_engine=engine)
    again = ledger.claim(snap, db_engine=engine)
    assert first["claimed"] is True
    assert again["claimed"] is False
    assert again["status"] == "already_claimed"
    assert ledger.summary(db_engine=engine)["by_status"]["claimed"] == 1
    result = ledger.complete(first["audit_key"],
        {"status": "shadow_evaluated", "shadow_only": True,
         "publication_authority": False,
         "evidence_state": "insufficient",
         "requires_human_review_probability": .9}, db_engine=engine)
    assert result["updated"] is True
    assert ledger.summary(db_engine=engine)["by_status"]["shadow_evaluated"] == 1
    assert ledger.complete(first["audit_key"],
        {"status": "shadow_evaluated", "shadow_only": True,
         "publication_authority": False}, db_engine=engine)["updated"] is False


def test_future_capture_never_creates_a_database_claim(engine):
    snap = envelope()
    snap["state"]["as_of"] = (KO + timedelta(minutes=1)).isoformat()
    assert ledger.claim(snap, db_engine=engine)["claimed"] is False
    assert not ledger.table_exists(engine)


def test_invalid_or_nonshadow_results_cannot_close_a_ledger_row(engine):
    ticket = ledger.claim(envelope(), db_engine=engine)
    assert ledger.complete(ticket["audit_key"],
        {"publication_authority": True, "shadow_only": False},
        db_engine=engine)["updated"] is False


def test_disabled_worker_does_not_read_board_fetch_sources_or_create_tables(monkeypatch, engine):
    monkeypatch.setattr(worker, "matched_evidence_envelope",
        lambda *a, **k: pytest.fail("should not map fixtures"))
    report = worker.run_shadow_batch([], [], as_of=NOW, environ={},
                                     db_engine=engine)
    assert report["jev_calls"] == 0
    assert not ledger.table_exists(engine)
    assert worker.scheduler_shadow_tick(environ={})["status"] == "staging_only"


def test_requires_explicit_staging_and_limited_matchdays():
    assert worker.scheduler_shadow_tick(
        environ={"ENVIRONMENT": "staging"})["status"] == "worker_disabled"
    assert worker.configured_sources("bl1:2026:8;bl2:2026:8") == [
        ("bl1", 2026, 8), ("bl2", 2026, 8)]
    with pytest.raises(ValueError):
        worker.configured_sources("bl1:2026:8;evil:2026:9")
    with pytest.raises(ValueError):
        worker.configured_sources("bl1:2026:8;bl2:2026:8;bl3:2026:8;bl1:2026:9")


def test_run_batch_never_double_bills_same_fingerprint(monkeypatch, engine):
    from leagues import jev_shadow_decision as decision
    decision._COUNTER.update(date=None, attempted=0)
    def map_fixture(pick, snapshot, as_of):
        return envelope()
    monkeypatch.setattr(worker, "matched_evidence_envelope", map_fixture)
    picks = [{"match_id": "espn-1", "market": "over_1_5"}]
    called = []
    def transport(payload, key):
        called.append(payload)
        return {"answers": {
            "evidence_state": {"type": "choice", "choice": "insufficient",
                               "confidence": .96},
            "requires_human_review": {"type": "boolean", "probability": .8}}}
    first = worker.run_shadow_batch(picks, [{}], as_of=NOW,
        environ=CONFIG, db_engine=engine, transport=transport)
    second = worker.run_shadow_batch(picks, [{}], as_of=NOW,
        environ=CONFIG, db_engine=engine, transport=transport)
    assert first["evaluated"] == 1
    assert second["already_claimed"] == 1
    assert first["jev_calls"] == 1
    assert second["jev_calls"] == 0
    assert len(called) == 1
    assert ledger.summary(db_engine=engine)["total"] == 1
