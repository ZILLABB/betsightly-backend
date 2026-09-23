import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.compare_forward_history import _verified_board


def _write_board(path, kickoff):
    captured = datetime.now(timezone.utc)
    payload = {
        "captured_at": captured.isoformat(),
        "fixtures": [{"match_id": "fixture-1", "commence_time": kickoff.isoformat()}],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    payload["snapshot_id"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_shadow_board_refuses_started_fixture(tmp_path):
    path = tmp_path / "board.json"
    _write_board(path, datetime.now(timezone.utc) - timedelta(minutes=1))
    with pytest.raises(ValueError, match="started fixture"):
        _verified_board(path)


def test_shadow_board_refuses_modified_snapshot(tmp_path):
    path = tmp_path / "board.json"
    payload = _write_board(path, datetime.now(timezone.utc) + timedelta(days=1))
    payload["fixtures"][0]["match_id"] = "altered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        _verified_board(path)


def test_shadow_board_accepts_untouched_future_fixture(tmp_path):
    path = tmp_path / "board.json"
    payload = _write_board(path, datetime.now(timezone.utc) + timedelta(days=1))
    assert _verified_board(path)["snapshot_id"] == payload["snapshot_id"]
