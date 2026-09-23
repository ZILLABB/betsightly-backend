"""Read-only public prediction prerequisite state."""

import time
from datetime import datetime

from leagues import shared_history_store
from leagues.history_cache_io import read_complete


class HistoryNotReady(RuntimeError):
    pass


def status() -> dict:
    from leagues import base_rates, team_history
    specs = (
        ("base_rates", base_rates.CACHE_PATH, base_rates.HISTORY_CACHE_SCHEMA,
         "_priors", base_rates.CACHE_TTL, "_built_at"),
        ("team_history", team_history.CACHE_PATH, team_history.HISTORY_CACHE_SCHEMA,
         "matches", team_history.CACHE_TTL, "built_at"),
    )
    parts = {}
    for key, path, schema, required, ttl, timestamp_key in specs:
        complete = read_complete(path, schema, required=required)
        refreshing = path.with_name(path.name + ".refresh.lock").exists()
        if shared_history_store.production_shared():
            try:
                complete = (shared_history_store.read(
                    key, schema, required=required) or complete)
                refreshing = shared_history_store.lease_active(key)
            except Exception:
                # A local last-complete artifact remains usable if DB is down.
                pass
        if complete is None:
            state = "REFRESHING" if refreshing else "ABSENT"
        else:
            try:
                built = complete.get(timestamp_key)
                age = (time.time() - datetime.fromisoformat(built).timestamp()
                       if built else time.time() - path.stat().st_mtime)
            except (OSError, ValueError, TypeError):
                age = float("inf")
            state = "READY" if age < ttl else "STALE_COMPLETE"
        parts[key] = {"state": state, "complete": complete is not None,
                      "refreshing": refreshing}
    usable = all(p["complete"] for p in parts.values())
    if not usable:
        overall = "REFRESHING" if any(p["refreshing"] for p in parts.values()) else "ABSENT"
    elif any(p["state"] == "STALE_COMPLETE" for p in parts.values()):
        overall = "STALE_COMPLETE"
    else:
        overall = "READY"
    return {"state": overall, "usable": usable, "artifacts": parts}
