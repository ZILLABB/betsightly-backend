"""Phase 6 adapters; no network, production database or model changes."""
import asyncio
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from leagues import api, builder_runs, builder_v2, engine


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    db = create_engine("sqlite://", poolclass=StaticPool,
                       connect_args={"check_same_thread": False})
    monkeypatch.setattr(builder_runs, "engine", db)
    monkeypatch.setenv("BUILDER_ENGINE", "v2")
    monkeypatch.setattr(api, "_V2_TARGET_CACHE", {})
    monkeypatch.setattr(api, "_V2_TARGET_LOCKS", {})
    yield db
    db.dispose()


def test_legacy_http_contract_delegates_to_v2(monkeypatch):
    calls = []
    async def canonical(request):
        calls.append(api._builder_v2_payload(request))
        return {"status": "unavailable", "reason": "board_refreshing"}
    monkeypatch.setattr(api, "slip_builder_v2_generate", canonical)
    result = asyncio.run(api.slip_builder_generate(100, "week", True))
    assert result["reason"] == "board_refreshing"
    assert calls[0]["target_odds"] == 100
    assert calls[0]["horizon"] == "7_days"
    assert calls[0]["refresh"] is True


def test_rollback_is_explicit_and_v2_only_modes_fail_closed(monkeypatch):
    calls = []
    async def legacy(*args):
        calls.append(args)
        return {"status": "success"}
    monkeypatch.setenv("BUILDER_ENGINE", "legacy")
    monkeypatch.setattr(api, "_legacy_slip_builder_generate", legacy)
    assert asyncio.run(api.slip_builder_v2_generate(api.BuilderV2Request(
        mode="target_odds", target_odds=10))) == {"status": "success"}
    assert calls == [(10, "week", False)]
    for mode in ("game_count", "strongest"):
        assert asyncio.run(api.slip_builder_v2_generate(api.BuilderV2Request(
            mode=mode)))["reason"] == "builder_mode_disabled"
    assert asyncio.run(api.slip_builder_v2_manual(api.BuilderV2ManualRequest(
        selection_ids=["s1"])))["reason"] == "builder_mode_disabled"
    assert asyncio.run(api.slip_builder_v2_candidates(api.BuilderV2Filters()))["reason"] == "builder_mode_disabled"
    assert len(calls) == 1


def test_invalid_switch_fails_closed(monkeypatch):
    monkeypatch.setenv("BUILDER_ENGINE", "typo")
    result = asyncio.run(api.slip_builder_v2_generate(api.BuilderV2Request(
        mode="target_odds", target_odds=10)))
    assert result["reason"] == "builder_engine_disabled"


@pytest.mark.parametrize("mode", ["game_count", "strongest", "manual", "target_odds"])
def test_modes_archive_and_settle_without_fabricated_targets(monkeypatch, isolated, mode):
    game = {"match_id": "m1", "market": "over_1_5", "odds": 2.1,
            "kickoff": "2099-01-01T12:00:00Z", "selection_id": "s1"}
    response = {"status": "success", "games": [game], "legs": 1, "odds": 2.1,
                "estimated_all_leg_probability": .75, "estimated_expected_return": 1.575,
                "board": {"board_snapshot_id": "fixed"},
                "booking": {"status": "active", "booking_status": "FULL",
                            "readback_validation": "PASSED", "share_code": "PRIVATE"}}
    monkeypatch.setattr(builder_v2, "generate_v2", lambda opts: dict(response))
    monkeypatch.setattr(builder_v2, "manual_build", lambda opts: dict(response))
    monkeypatch.setattr(engine, "prepared_board_status", lambda **kw: {"board_snapshot_id": "fixed"})
    monkeypatch.setattr(api, "_start_builder_revision", lambda t, h, r: r)
    if mode == "manual":
        result = asyncio.run(api.slip_builder_v2_manual(api.BuilderV2ManualRequest(selection_ids=["s1"])))
    else:
        result = asyncio.run(api.slip_builder_v2_generate(api.BuilderV2Request(
            mode=mode, target_odds=2 if mode == "target_odds" else None, game_count=1)))
    with isolated.connect() as conn:
        row = conn.execute(select(builder_runs.builder_predictions)).mappings().one()
        assert conn.execute(select(builder_runs.builder_runs)).mappings().one()["request_id"] == result["request_id"]
    assert row["mode"] == mode
    assert row["target_odds"] == (2 if mode == "target_odds" else None)
    assert json.loads(row["picks"]) == [game]
    assert json.loads(row["board_context"])["board_snapshot_id"] == "fixed"
    assert row["hit_probability"] == .75
    assert "PRIVATE" not in str(dict(row))
    assert builder_runs.settle_prediction(row["selection_fingerprint"], ["won"]) == "won"
    with isolated.connect() as conn:
        settled = conn.execute(select(builder_runs.builder_predictions)).mappings().one()
    assert settled["actual_settled_return"] == 2.1
    assert settled["target_reached"] == (True if mode == "target_odds" else None)
    builder_runs.performance()
    builder_runs.summary("2000-01-01", "2100-01-01")


def test_revision_keeps_selection_snapshot(monkeypatch):
    from leagues import builder_revisions
    monkeypatch.setattr(engine, "prepared_board_status", lambda **kw: {"board_snapshot_id": "new"})
    monkeypatch.setattr(builder_revisions, "create_initial_run", lambda t, h, r: r)
    result = api._start_builder_revision(10, "7_days", {
        "status": "success", "games": [{"match_id": "m"}],
        "board": {"board_snapshot_id": "selected-snapshot"},
    })
    assert result["board"]["board_snapshot_id"] == "selected-snapshot"


def test_v2_prepared_board_path_never_falls_back_to_provider_pipeline(monkeypatch):
    from leagues import slip_builder
    observed = {}
    monkeypatch.setattr(builder_v2, "_require_prepared_board", lambda: {"ready": True})
    monkeypatch.setattr(slip_builder, "prepared_bookable_pool", lambda *args, **kwargs: (
        observed.update(kwargs) or {"__meta__": {}}, [], {}
    ))
    result = builder_v2.generate_v2({"mode": "strongest", "max_games": 1})
    assert observed["allow_pipeline_fallback"] is False
    assert result["status"] == "unavailable"


@pytest.mark.parametrize("existing_predictions", [False, True])
def test_real_migration_preserves_history_and_supports_non_target_rows(
        monkeypatch, tmp_path, existing_predictions):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import MetaData, inspect, text
    import database
    url = "sqlite:///" + str(tmp_path / "migration.db")
    monkeypatch.setattr(database, "DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "add_tier_recovery_provenance")
    db = create_engine(url)
    if existing_predictions:
        historical = builder_runs.builder_predictions.to_metadata(MetaData())
        historical._columns.remove(historical.c.mode)
        historical._columns.remove(historical.c.board_context)
        historical.c.target_odds.nullable = False
        historical.create(db)
        with db.begin() as conn:
            conn.execute(text("INSERT INTO builder_predictions "
                              "(selection_fingerprint,created_at,target_odds,horizon,generated_odds,leg_count,picks,final_status) "
                              "VALUES ('historical','2026-09-16',10,'week',10,1,'[]','lost')"))
    command.upgrade(cfg, "add_builder_v2_context")
    inspector = inspect(db)
    assert {c["name"] for c in inspector.get_columns("builder_predictions")} >= {"mode", "board_context"}
    assert "ix_builder_predictions_created_at" in {
        index["name"] for index in inspector.get_indexes("builder_predictions")
    }
    monkeypatch.setattr(builder_runs, "engine", db)
    builder_runs.record_run(None, "7_days", False, {"status": "unavailable"}, mode="manual")
    if existing_predictions:
        with db.connect() as conn:
            row = conn.execute(select(builder_runs.builder_predictions)).mappings().one()
            assert row["selection_fingerprint"] == "historical"
            assert row["final_status"] == "lost"
            assert row["target_odds"] == 10
            assert row["mode"] == "target_odds"
    command.downgrade(cfg, "add_tier_recovery_provenance")
    # Downgrade must not discard new-mode history or provenance.
    with db.connect() as conn:
        assert conn.execute(select(builder_runs.builder_runs)).mappings().one()["mode"] == "manual"
    command.upgrade(cfg, "add_builder_v2_context")
    db.dispose()
