"""No network, credentials or database connections: reconciliation guards."""
import copy
import hashlib
import json
import pytest

from basketball.research_coldstart import _json
from basketball import research_target_readback as rec


def test_pure_reconciliation_matches_verified_backup(monkeypatch):
    payload = {"version": "test", "fixtures": []}
    digest = hashlib.sha256(_json(payload).encode()).hexdigest()
    unsigned = {"game_id": "77", "observed_at": "2026-10-27T13:00:00Z"}
    market = {**unsigned, "digest": hashlib.sha256(_json(unsigned).encode()).hexdigest()}
    source = {"archive": payload, "archive_digest": digest,
              "market_receipts": [market], "market_receipt_count": 1}
    monkeypatch.setattr(rec, "verify_portable_backup",
                        lambda b: {"restore_drill_passed": True})
    result = rec.compare_archive_and_markets(
        source, digest, _json(payload), [(market["digest"], _json(market))]
    )
    assert result["status"] == "source_target_identical"
    assert result["cutover_approved"] is False
    assert result["source_unchanged"] is True

    with pytest.raises(ValueError, match="ARCHIVE_DRIFT"):
        rec.compare_archive_and_markets(source, "0"*64, _json(payload),
                                        [(market["digest"], _json(market))])
    with pytest.raises(ValueError, match="MARKET_COUNT"):
        rec.compare_archive_and_markets(source, digest, _json(payload), [])
    changed = copy.deepcopy(market)
    changed["game_id"] = "untrusted"
    with pytest.raises(ValueError, match="MARKET_HISTORY"):
        rec.compare_archive_and_markets(source, digest, _json(payload),
                                        [(market["digest"], _json(changed))])


def test_reconciliation_rejects_invalid_backup_first(monkeypatch):
    monkeypatch.setattr(rec, "verify_portable_backup",
                        lambda b: {"restore_drill_passed": False})
    with pytest.raises(ValueError, match="SOURCE_DRILL_FAILED"):
        rec.compare_archive_and_markets({}, "", "{}", [])


def test_reconciliation_always_refuses_same_database():
    with pytest.raises(ValueError, match="REFUSES_SOURCE_DATABASE"):
        from basketball.research_safe_migrate import isolated_target_is_safe
        isolated_target_is_safe(
            "postgresql://nba:test@same.example/postgres",
            "postgresql://nba:test@same.example/postgres")


def test_audit_history_is_append_only_exact_prefix():
    assert rec.verified_audit_prefix([], [(1, "forecast"), (2, "settlement")]) == [
        (1, "forecast"), (2, "settlement")]
    assert rec.verified_audit_prefix([(1, "forecast")],
                                     [(1, "forecast"), (2, "settlement")]) == [
        (2, "settlement")]
    assert rec.verified_audit_prefix([(1, "forecast")],
                                     [(1, "forecast")]) == []
    with pytest.raises(ValueError, match="EXISTING_HISTORY_MISMATCH"):
        rec.verified_audit_prefix([(1, "modified")], [(1, "forecast")])
    with pytest.raises(ValueError, match="EXISTING_HISTORY_MISMATCH"):
        rec.verified_audit_prefix([(1, "forecast"), (2, "extra")],
                                  [(1, "forecast")])



def test_original_render_export_is_explicit_read_only_and_rollback_safe(monkeypatch):
    events = []
    class Transaction:
        def rollback(self):
            events.append("rollback")
    class Connection:
        def __enter__(self):
            events.append("connect")
            return self
        def __exit__(self, *args):
            events.append("disconnect")
        def begin(self):
            events.append("begin")
            return Transaction()
        def exec_driver_sql(self, command):
            events.append(command)
    class Engine:
        def connect(self):
            return Connection()
        def dispose(self):
            events.append("dispose")
    class Session:
        def __init__(self, bind):
            assert isinstance(bind, Connection)
        def __enter__(self):
            events.append("session")
            return self
        def __exit__(self, *args):
            events.append("session_closed")

    monkeypatch.setattr(rec, "Session", Session)
    def factory(url, *, pool_pre_ping):
        assert url.host == "original-render.example"
        assert pool_pre_ping is True
        events.append("source_engine")
        return Engine()
    def exporter(*, db=None):
        assert isinstance(db, Session), "Must not use active SessionLocal"
        events.append("backup_export")
        return {"original_source": True}

    result = rec.export_original_render_source(
        "postgresql://readonly:x@original-render.example/nba",
        engine_factory=factory, exporter=exporter,
    )
    assert result == {"original_source": True}
    assert events.index("SET TRANSACTION READ ONLY") < events.index("backup_export")
    assert events.index("rollback") > events.index("backup_export")
    assert events[-1] == "dispose"


def test_original_render_source_required_and_not_inferred_from_active_session():
    for bad in (None, "", "sqlite:///nba", "postgresql://"):
        with pytest.raises((ValueError, TypeError)):
            rec.export_original_render_source(bad, exporter=lambda **kw: None)
