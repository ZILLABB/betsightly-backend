import json
import os
import time

import pytest

from leagues.history_cache_io import (local_refresh_claim, read_complete,
                                      replace_complete)
from leagues import base_rates, team_history


def test_atomic_complete_cache_survives_rejected_partial_and_restart(tmp_path):
    path = tmp_path / "rates.json"
    complete = {"_cache_schema": 2, "_priors": {"global": {"matches": 42}}}
    replace_complete(path, complete, 2, required="_priors")
    with pytest.raises(ValueError):
        replace_complete(path, {**complete, "_failed_leagues": ["eng.1"]},
                         2, required="_priors")
    assert read_complete(path, 2, required="_priors") == complete
    assert list(tmp_path.glob("*.tmp")) == []
    # A process dying with a half-written temp artifact cannot replace it.
    (tmp_path / "rates.json.dead.tmp").write_text("{", encoding="utf-8")
    assert read_complete(path, 2, required="_priors") == complete


def test_same_filesystem_refresh_claim_is_nonblocking_and_recoverable(tmp_path):
    path = tmp_path / "rates.json"
    with local_refresh_claim(path) as first:
        assert first
        with local_refresh_claim(path) as second:
            assert not second
    lock = tmp_path / "rates.json.refresh.lock"
    lock.write_text("dead process", encoding="utf-8")
    os.utime(lock, (time.time() - 700, time.time() - 700))
    with local_refresh_claim(path) as recovered:
        assert recovered
    assert not lock.exists()


def test_publication_reads_complete_stale_cache_without_refresh(tmp_path, monkeypatch):
    rate_path = tmp_path / "rates.json"
    rate_data = {"_cache_schema": 2, "_priors": {"global": {"matches": 42}}}
    rate_path.write_text(json.dumps(rate_data), encoding="utf-8")
    os.utime(rate_path, (time.time() - 999999, time.time() - 999999))
    monkeypatch.setattr(base_rates, "CACHE_PATH", rate_path)
    monkeypatch.setattr(base_rates, "compute_base_rates",
                        lambda *args, **kwargs: pytest.fail("synchronous history fetch"))
    assert base_rates.get_base_rates(allow_refresh=False) == rate_data

    team_path = tmp_path / "teams.json"
    team_data = {"_cache_schema": 2, "matches": []}
    team_path.write_text(json.dumps(team_data), encoding="utf-8")
    os.utime(team_path, (time.time() - 999999, time.time() - 999999))
    monkeypatch.setattr(team_history, "CACHE_PATH", team_path)
    monkeypatch.setattr(team_history, "build",
                        lambda *args, **kwargs: pytest.fail("synchronous history fetch"))
    assert team_history.load(allow_refresh=False) == team_data


def test_publication_with_no_complete_cache_does_not_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(base_rates, "CACHE_PATH", tmp_path / "missing-rates.json")
    monkeypatch.setattr(team_history, "CACHE_PATH", tmp_path / "missing-teams.json")
    monkeypatch.setattr(base_rates, "compute_base_rates",
                        lambda *args, **kwargs: pytest.fail("request-path fetch"))
    monkeypatch.setattr(team_history, "build",
                        lambda *args, **kwargs: pytest.fail("request-path fetch"))
    assert base_rates.get_base_rates(allow_refresh=False) == {}
    assert team_history.load(allow_refresh=False) == {"matches": []}
