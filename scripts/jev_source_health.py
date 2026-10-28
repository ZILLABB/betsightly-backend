"""Keyless OpenLigaDB health probe for scheduled GitHub Actions research.

This is read-only, requests only two explicit Bundesliga current matchdays,
does not score fixtures, touch databases, perform Jev calls or publish picks.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

LEAGUES = ("bl1", "bl2")


def probe_sources(*, now=None, fetcher=None):
    from leagues.external_openligadb import fetch_current_matchday
    current = now or datetime.now(timezone.utc)
    get = fetcher or fetch_current_matchday
    checks = []
    for league in LEAGUES:
        try:
            result = get(
                league,
                environ={"BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED": "true"},
                now=current,
            )
            checks.append({
                "league": league,
                "status": ("empty" if result.get("status") == "ok" and not result.get("fixtures") else str(result.get("status") or "unavailable")),
                "reported_matches": len(result.get("fixtures") or []),
                "reported_pregame_evidence": len(result.get("evidence") or []),
                "reported_group": result.get("auto_discovered_group"),
                "attribution": result.get("attribution"),
            })
        except Exception as exc:
            checks.append({"league": league, "status": "unavailable",
                           "reason": type(exc).__name__})
    return {
        "status": "ok" if checks and all(
            item["status"] == "ok" for item in checks
        ) else "degraded",
        "checked_at": current.astimezone(timezone.utc).isoformat(),
        "source": "OpenLigaDB",
        "source_health_only": True,
        "independent_settlement_verified": False,
        "cross_provider_fixture_identity_verified": False,
        "jev_calls_made": 0,
        "official_predictions_changed": False,
        "checks": checks,
    }


def main():
    report = probe_sources()
    print(json.dumps(report, sort_keys=True, default=str))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
