import hashlib
import json
from datetime import datetime, timezone

from scripts.capture_forward_board import model_fingerprint
from scripts.compare_forward_history import compare


def test_complete_shadow_does_not_fetch_live_inputs(tmp_path, monkeypatch):
    import requests

    def forbidden(*args, **kwargs):
        raise AssertionError("frozen replay attempted a live provider call")

    monkeypatch.setattr(requests, "get", forbidden)
    board = {
        "schema": 2,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "fixtures": [], "model_fingerprint": model_fingerprint(),
        "calibration": {"status": "success", "n_legs": 0,
                        "groups": {}, "policy": {}},
        "calibration_observed_at": datetime.now(timezone.utc).isoformat(),
        "target_wat_date": "2099-01-01",
        "historical_inputs": {
            "base_rates": {"_priors": {}, "_cache_schema": 2},
            "team_history": {"matches": [], "_cache_schema": 2},
            "elo_ratings": {},
        },
        "provider": {}, "sportybet": {},
    }
    raw = json.dumps(board, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    board["snapshot_id"] = hashlib.sha256(raw).hexdigest()
    input_path = tmp_path / "board.json"
    output_path = tmp_path / "comparison.json"
    input_path.write_text(json.dumps(board), encoding="utf-8")
    result = compare(input_path, output_path)
    assert result["base_requests"] == 0
    assert result["history_requests"] == 0
    assert output_path.exists()
