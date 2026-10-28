"""Non-destructive NBA migration acceptance tests, no cloud SQL connections."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from basketball import research_safe_migrate as migration


@pytest.mark.parametrize("destination", [
    "", "sqlite:///nba.db", "mysql://someone@test/private",
    "postgresql:///nohost", "https://public.example/db",
])
def test_rejects_non_dedicated_postgres_urls(destination):
    with pytest.raises(ValueError):
        migration.isolated_target_is_safe(destination)


def test_never_migrates_back_to_source_db():
    source="postgresql://source:secret@staging.example/nba_stage"
    with pytest.raises(ValueError,match="REFUSES_SOURCE"):
        migration.isolated_target_is_safe(source,source)


def test_requires_verified_export_before_opening_any_database(monkeypatch):
    invoked=[]
    def fake_engine(*args,**kwargs):
        invoked.append(True)
        pytest.fail("Never connect to a database if export signature is invalid")
    with pytest.raises(ValueError):
        migration.restore_into_empty_target(
            {"version":"bad"}, "postgresql://nba@new.example/new_empty_nba",
            engine_factory=fake_engine,
        )
    assert invoked == []


def test_malformed_export_cannot_trigger_any_restore(tmp_path):
    path=tmp_path/"unverified.json"
    path.write_text('{"version":"unknown"}',encoding="utf-8")
    with pytest.raises(ValueError):
        migration.load_checked_backup(path)
    path.write_text("not valid json",encoding="utf-8")
    with pytest.raises(ValueError,match="JSON_INVALID"):
        migration.load_checked_backup(path)


def test_unbounded_export_file_rejected(tmp_path):
    path=tmp_path/"too_big.json"
    path.write_bytes(b" " * (migration.MAX_BACKUP_FILE+1))
    with pytest.raises(ValueError,match="UNBOUNDED"):
        migration.load_checked_backup(path)


def test_timestamp_must_be_aware():
    checked=migration.__parse_utc("2026-10-27T14:00:00Z")
    assert isinstance(checked,datetime)
    assert checked.tzinfo is None
    with pytest.raises(ValueError,match="TIMESTAMP"):
        migration.__parse_utc("2026-10-27T14:00:00")


def test_private_supabase_target_never_uses_source_or_public_schema():
    from basketball.research_safe_migrate import probe_empty_target
    target="postgresql://nba_research:example@supabase.example/postgres"
    source="postgresql://source:example@render.example/staging"
    class FakeResult:
        def scalar(self): return "public"
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self,*args): return None
        def exec_driver_sql(self, sql):
            assert sql == "SET LOCAL search_path TO nba_research"
        def execute(self,*args,**kwargs): return FakeResult()
    class FakeEngine:
        def begin(self): return FakeConn()
        def dispose(self): pass
    with pytest.raises(ValueError,match="PRIVATE_SCHEMA_REQUIRED"):
        probe_empty_target(target,source_url=source,
                           engine_factory=lambda *args,**kwargs: FakeEngine())
    with pytest.raises(ValueError,match="SOURCE_DATABASE"):
        probe_empty_target(source,source_url=source,
                           engine_factory=lambda *args,**kwargs: pytest.fail("no SQL"))


def test_signed_migration_identity_is_separate_from_forecast_and_settle():
    from basketball.research_oidc import WORKFLOWS
    assert "migration" in WORKFLOWS
    assert WORKFLOWS["migration"].endswith(
      "/.github/workflows/nba-private-stage-migration.yml@refs/heads/dev"
    )
    assert WORKFLOWS["migration"] not in (
      WORKFLOWS["settlement"],WORKFLOWS["forecast"],WORKFLOWS["market"]
    )


def test_private_schema_probe_does_not_modify_global_search_path(monkeypatch):
    calls=[]
    class FakeResult:
        def scalar(self): return "nba_research"
    class Conn:
        dialect=type("Dialect", (), {"name":"postgresql"})()
        def __enter__(self): return self
        def __exit__(self,*args): return None
        def exec_driver_sql(self, sql): calls.append(sql)
        def execute(self, sql): calls.append(str(sql)); return FakeResult()
    class Engine:
        def begin(self): return Conn()
        def dispose(self): calls.append("disposed")
    class Inspection:
        def get_table_names(self, *, schema):
            assert schema=="nba_research"
            return []
    monkeypatch.setattr(migration, "inspect", lambda conn: Inspection())
    result=migration.probe_empty_target(
        "postgresql://private@new.example/postgres",
        source_url="postgresql://previous@render.example/old",
        engine_factory=lambda *args,**kwargs: Engine(),
    )
    assert result["status"]=="target_empty"
    assert result["source_unchanged"] is True
    assert calls[0]=="SET LOCAL search_path TO nba_research"
    assert "disposed" in calls
