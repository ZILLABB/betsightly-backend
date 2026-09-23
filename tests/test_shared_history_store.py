"""Two independent engine objects simulate separate app instances."""

import time

import pytest
from sqlalchemy import create_engine, text

from leagues import shared_history_store as store


def _create_schema(engine):
    # Production uses the Alembic migration; isolated SQLite tests create its
    # equivalent explicitly so no application request performs DDL.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE history_artifacts ("
                          "cache_key VARCHAR(120) PRIMARY KEY, "
                          "schema_version INTEGER NOT NULL, payload TEXT, "
                          "payload_sha256 VARCHAR(64), built_at FLOAT, "
                          "lease_owner VARCHAR(36), lease_until FLOAT)"))


def test_two_instances_share_only_promoted_complete_artifact(tmp_path):
    url = f"sqlite:///{(tmp_path / 'shared.db').as_posix()}"
    first = create_engine(url)
    second = create_engine(url)
    _create_schema(first)
    payload = {"_cache_schema": 2, "_priors": {"global": {"matches": 42}}}
    with store.claim("base_rates", 2, engine=first) as owner:
        assert owner
        with store.claim("base_rates", 2, engine=second) as contender:
            assert contender is None
        assert store.read("base_rates", 2, required="_priors", engine=second) is None
        with pytest.raises(ValueError):
            store.promote("base_rates", 2, {**payload, "_failed_leagues": ["x"]},
                          owner, required="_priors", engine=first)
        assert store.promote("base_rates", 2, payload, owner,
                             required="_priors", engine=first)
    assert store.read("base_rates", 2, required="_priors", engine=second) == payload

    # A failed or crashed refresh does not erase the old complete payload.
    with store.claim("base_rates", 2, engine=second) as owner:
        assert owner
        assert store.read("base_rates", 2, required="_priors", engine=first) == payload
    assert store.read("base_rates", 2, required="_priors", engine=first) == payload
    first.dispose()
    second.dispose()


def test_expired_claim_recovers_and_old_owner_cannot_promote(tmp_path):
    url = f"sqlite:///{(tmp_path / 'shared.db').as_posix()}"
    first = create_engine(url)
    second = create_engine(url)
    _create_schema(first)
    with store.claim("team_history", 2, engine=first) as old_owner:
        assert old_owner
        with first.begin() as conn:
            conn.execute(text(
                "UPDATE history_artifacts SET lease_until = :past "
                "WHERE cache_key = 'team_history'"), {"past": time.time() - 1})
        with store.claim("team_history", 2, engine=second) as new_owner:
            assert new_owner and new_owner != old_owner
            assert not store.promote("team_history", 2,
                                     {"_cache_schema": 2, "matches": []},
                                     old_owner, required="matches", engine=first)
            assert store.promote("team_history", 2,
                                 {"_cache_schema": 2, "matches": []},
                                 new_owner, required="matches", engine=second)
    assert store.read("team_history", 2, required="matches", engine=first) == {
        "_cache_schema": 2, "matches": []}
    first.dispose()
    second.dispose()
