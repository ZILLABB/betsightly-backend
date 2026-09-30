"""Read-only ESPN cold/warm history-cost diagnostic; writes only temp cache."""

import json
import os
import tempfile
import time
from pathlib import Path
from threading import Lock
from unittest.mock import patch


def measure():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["ENVIRONMENT"] = "research"
    with tempfile.TemporaryDirectory(prefix="betsightly-history-measure-") as root:
        os.environ["BETSIGHTLY_CACHE_ROOT"] = root
        from leagues import base_rates, team_history, espn_history_fetch
        from leagues.espn_source import ESPN_CLUB_LEAGUES

        original = espn_history_fetch.requests.get
        counts = {"requests": 0}
        lock = Lock()

        def counted(*args, **kwargs):
            with lock:
                counts["requests"] += 1
            return original(*args, **kwargs)

        with patch("leagues.espn_history_fetch.requests.get", side_effect=counted):
            t0 = time.monotonic()
            base = base_rates.compute_base_rates(ESPN_CLUB_LEAGUES)
            base_seconds = time.monotonic() - t0
            base_requests = counts["requests"]
            base_months = len(list(Path(root, "history_months").glob("*.json")))
            t0 = time.monotonic()
            history = team_history.build(ESPN_CLUB_LEAGUES)
            history_seconds = time.monotonic() - t0
            cold_requests = counts["requests"]
            t0 = time.monotonic()
            base_rates.compute_base_rates(ESPN_CLUB_LEAGUES)
            team_history.build(ESPN_CLUB_LEAGUES)
            warm_seconds = time.monotonic() - t0
            warm_requests = counts["requests"] - cold_requests

        files = list(Path(root, "history_months").glob("*.json"))
        return {
            "base_requests": base_requests,
            "team_additional_requests": cold_requests - base_requests,
            "cold_requests": cold_requests,
            "warm_requests": warm_requests,
            "base_seconds": round(base_seconds, 2),
            "team_seconds": round(history_seconds, 2),
            "warm_seconds": round(warm_seconds, 2),
            "monthly_artifacts": len(files),
            "shared_months_reused_by_team": base_months,
            "monthly_artifact_bytes": sum(path.stat().st_size for path in files),
            "failed_base_leagues": len(base.get("_failed_leagues") or []),
            "failed_team_leagues": len(history.get("failed_leagues") or []),
        }


if __name__ == "__main__":
    print(json.dumps(measure(), sort_keys=True))
