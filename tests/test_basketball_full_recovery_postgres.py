"""Prove no source writes or accidental target connections before full V2 acceptance."""
from datetime import datetime, timezone
import pytest
from basketball import research_full_recovery_postgres as restore


def test_invalid_or_unauthenticated_bundle_does_not_connect():
    def blocked(*args, **kwargs):
        pytest.fail("Unsafe backup must be rejected BEFORE target connection")
    with pytest.raises(ValueError):
        restore.restore_full_v2_empty_postgres(
            {"version":"bad"},
            "postgresql://restore:secret@disposable.example/postgres",
            active_primary_url="postgresql://active:secret@supabase.example/postgres",
            original_render_url="postgresql://old:secret@render.example/nba",
            engine_factory=blocked)


def test_disposable_target_rejects_active_or_original_postgres_hosts(monkeypatch):
    monkeypatch.setattr(restore, "verify_full_recovery", lambda *a: {})
    def blocked(*args, **kwargs):
        pytest.fail("Never connect to source or target on shared production host")
    for target in (
        "postgresql://restore:secret@supabase.example/disposable",
        "postgresql://restore:secret@render.example/disposable",
    ):
        with pytest.raises(ValueError, match="HOST_NOT_DISPOSABLE"):
            restore.restore_full_v2_empty_postgres(
                {"portable_backup_v1":{},"job_receipts":[]},
                target,
                active_primary_url="postgresql://active:secret@supabase.example/postgres",
                original_render_url="postgresql://old:secret@render.example/nba",
                engine_factory=blocked)


def test_only_aware_recovery_timestamps():
    assert restore._timestamp("2026-10-28T07:40:00Z") == datetime(
        2026,10,28,7,40)
    with pytest.raises(ValueError, match="TIMESTAMP"):
        restore._timestamp("2026-10-28T07:40:00")


def test_original_database_url_never_optional(monkeypatch):
    monkeypatch.setattr(restore, "verify_full_recovery", lambda *a: {})
    with pytest.raises(ValueError):
        restore.restore_full_v2_empty_postgres(
            {"portable_backup_v1": {}, "job_receipts": []},
            "postgresql://restore:secret@disposable.example/postgres",
            active_primary_url="postgresql://active:secret@supabase.example/postgres",
            original_render_url="",
            engine_factory=lambda *a, **kw: pytest.fail("No SQL"))
