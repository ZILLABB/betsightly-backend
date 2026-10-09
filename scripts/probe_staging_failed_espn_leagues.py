"""Probe only unavailable ESPN league scoreboards from a saved staging board.

This is a narrow, staging-only network diagnostic. It does NOT regenerate an
ESPN cache, refresh the prediction board, publish slips, write booking codes,
settle matches or retrain. Saved snapshots may be stale; the probe result is
the newly observed response for the target month, not new prediction evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json

from scripts.prepare_staging_board_once import preflight


def failed_from_saved_snapshot() -> tuple[list[str], str | None]:
    from leagues import prepared_board_store
    # In contrast to prepared_board_status(), saved entries are not
    # filtered by the short interactive freshness TTL.
    entries = prepared_board_store.load_entries()
    if not entries:
        raise RuntimeError("No saved staging board available to inspect")
    latest = max(
        entries,
        key=lambda row: str(row.get("saved_at") or ""),
    )
    entry = latest.get("entry") or {}
    metadata = entry.get("metadata") or {}
    provider = metadata.get("provider") or {}
    failed = sorted({
        str(slug) for slug in (provider.get("failed_leagues") or [])
        if slug
    })
    return failed, str(metadata.get("decision_snapshot_id") or "") or None


def probe(
    target_wat_date: str, *,
    slugs: list[str] | None = None,
    max_leagues: int = 25, probe_year_fallback: bool = False,
) -> dict:
    database = preflight()
    requested = date.fromisoformat(target_wat_date)
    wat = timezone(timedelta(hours=1))
    today = datetime.now(wat).date()
    if not today <= requested <= today + timedelta(days=6):
        raise ValueError("Target must be within the current seven-day WAT horizon")
    if not 1 <= max_leagues <= 25:
        raise ValueError("max_leagues must be 1..25")

    from leagues import espn_source
    original_snapshot = None
    if slugs is None:
        slugs, original_snapshot = failed_from_saved_snapshot()
    slugs = sorted(set(slugs))
    if len(slugs) > max_leagues:
        raise ValueError("Too many failed leagues for a bounded probe")
    if any(slug not in espn_source.ESPN_CLUB_LEAGUES for slug in slugs):
        raise ValueError("Unregistered ESPN league slug supplied")

    month = requested.strftime("%Y%m")
    def examine(slug: str) -> dict:
        try:
            fixtures = espn_source._fetch_league(slug, month)
            health = espn_source.fetch_health().get(slug) or {}
            succeeded = bool(health.get("request_succeeded"))
            active = bool(health.get("provider_active"))
            state = (
                "REACHABLE_WITH_FIXTURES" if succeeded and fixtures
                else "REACHABLE_NO_SCHEDULED_FIXTURES" if succeeded and active
                else "REACHABLE_EMPTY_RESPONSE" if succeeded
                else "UNAVAILABLE"
            )
            year_check = None
            if probe_year_fallback and not succeeded:
                # ESPN documents a yearly date filter in addition to month
                # queries. Probe its actual response rather than assuming the
                # 17 HTTP 400 competition IDs are permanently unsupported.
                annual = espn_source._fetch_league(slug, str(requested.year))
                year_health = espn_source.fetch_health().get(slug) or {}
                year_check = {
                    "query_shape": "YYYY",
                    "success": bool(year_health.get("request_succeeded")),
                    "provider_active": bool(year_health.get("provider_active")),
                    "scheduled_in_year": len(annual),
                    "error": year_health.get("error"),
                }
            return {
                "slug": slug,
                "state": state,
                "http_or_transport_error": health.get("error"),
                "provider_active": active,
                "scheduled_in_month": len(fixtures),
                "year_query_probe": year_check,
            }
        except Exception as exc:
            return {
                "slug": slug, "state": "PROBE_ERROR",
                "http_or_transport_error": (
                    f"{type(exc).__name__}: {str(exc)[:180]}"
                ),
                "provider_active": False,
                "scheduled_in_month": 0,
            }

    if not slugs:
        results = []
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(slugs))) as pool:
            results = list(pool.map(examine, slugs))

    counts = Counter(item["state"] for item in results)
    return {
        "database": database,
        "target_wat_date": target_wat_date,
        "source_month": month,
        "original_saved_board_snapshot": original_snapshot,
        "requested_failed_leagues": len(slugs),
        "states": dict(sorted(counts.items())),
        "per_league": results,
        "year_fallback_probed": probe_year_fallback,
        "source_diagnostic_only": True,
        "prepared_board_refreshed": False,
        "publishing_changed": False,
        "booking_codes_created": False,
        "note": (
            "A reachable ESPN scoreboard may still have zero eligible "
            "upcoming fixtures. No provider response changes the official "
            "prediction pool until a separate authorized board rebuild."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument(
        "--probe-year", action="store_true",
        help="Also try the documented YYYY filter for monthly HTTP 400 "
             "leagues, without publishing or modifying the fixture cache",
    )
    parser.add_argument(
        "--slugs", default=None,
        help="Optional comma-separated ESPN slugs; defaults to failed leagues "
             "from saved staging board",
    )
    opts = parser.parse_args()
    slugs = None if opts.slugs is None else [
        slug.strip() for slug in opts.slugs.split(",") if slug.strip()
    ]
    print(json.dumps(probe(
        opts.date, slugs=slugs, probe_year_fallback=opts.probe_year,
    ), sort_keys=True))
