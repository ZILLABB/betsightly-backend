"""Capture one read-only, pre-kickoff fixture/price board for offline shadow work.

This does not run the publication pipeline or create booking codes. The output
path must be outside the repository and is never a published-card table.
"""

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


def model_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1] / "models" / "api_football"
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.joblib")) + sorted(root.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def capture(output: Path, days: int = 4) -> dict:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from leagues import espn_source, sportybet

    started = datetime.now(timezone.utc)
    calibration_response = requests.get(
        "https://betsightly-api.onrender.com/api/leagues/calibration-fit",
        timeout=25,
    )
    calibration_response.raise_for_status()
    calibration = calibration_response.json()
    if calibration.get("status") != "success" or not isinstance(
            calibration.get("groups"), dict):
        raise ValueError("production calibration snapshot unavailable")
    calibration_observed_at = datetime.now(timezone.utc).isoformat()
    fixtures = espn_source.get_fixtures(days_ahead=days, force=False,
                                         now=started)
    provider = espn_source.cache_metadata()
    # Prevent SportyBet's normal database-backed cache from reading or writing
    # any database. Only its public upcoming-board GET is used.
    sportybet._db_get = lambda *_args, **_kwargs: None
    sportybet._db_set = lambda *_args, **_kwargs: None
    board = sportybet.fetch_board(force=True)
    fixtures = copy.deepcopy(fixtures)
    matched = sportybet.apply_to_fixtures(fixtures, board=board)
    cutoff = started + timedelta(minutes=30)
    fixtures = [fixture for fixture in fixtures if datetime.fromisoformat(
        fixture["commence_time"].replace("Z", "+00:00")) > cutoff]
    fixtures.sort(key=lambda f: (f["commence_time"], f["match_id"]))
    payload = {
        "schema": 1, "captured_at": started.isoformat(),
        "minimum_kickoff": cutoff.isoformat(),
        "provider": provider,
        "calibration": calibration,
        "calibration_observed_at": calibration_observed_at,
        "model_fingerprint": model_fingerprint(),
        "sportybet": sportybet.board_metadata(board),
        "sportybet_matched_before_kickoff_filter": matched,
        "fixtures": fixtures,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    payload["snapshot_id"] = hashlib.sha256(raw).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return {
        "snapshot_id": payload["snapshot_id"],
        "captured_at": payload["captured_at"],
        "fixtures": len(fixtures),
        "priced": sum(bool((f.get("odds") or {}).get("implied")) for f in fixtures),
        "sportybet_matched": sum(bool((f.get("odds") or {}).get("sportybet_event_id"))
                                 for f in fixtures),
        "provider_success": provider.get("successful_league_count"),
        "provider_failed": provider.get("failed_league_count"),
        "output": str(output),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--days", type=int, default=4)
    arguments = parser.parse_args()
    print(json.dumps(capture(arguments.output, arguments.days), sort_keys=True))
