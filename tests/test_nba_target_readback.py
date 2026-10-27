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
