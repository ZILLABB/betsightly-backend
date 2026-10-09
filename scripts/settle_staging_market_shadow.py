"""Safely reconcile staging market-shadow observations with verified ESPN finals.

Default: DRY RUN. Only --write-staging with an explicit independent confirmation
can update rows in the isolated staging warehouse. No other database table,
published slip, champion model, or booking code is ever written.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import text

from scripts.prepare_staging_board_once import preflight

CONFIRMATION = "CONFIRM_VERIFIED_SHADOW_SETTLEMENT_ONLY"
TABLE = "public.market_shadow_forecasts_v1"
SELECT_PENDING = text("""
    SELECT observation_key, fixture_id, market, league_slug,
           home_team, away_team, kickoff, observed_at
    FROM public.market_shadow_forecasts_v1
    WHERE status = 'pending'
      AND kickoff <= :cutoff
      AND observed_at < kickoff
      AND home_score IS NULL AND away_score IS NULL
      AND outcome IS NULL
    ORDER BY kickoff ASC, observation_key ASC
    LIMIT :limit
""")
UPDATE_ONE = text("""
    UPDATE public.market_shadow_forecasts_v1
    SET status = :status, home_score = :home_score, away_score = :away_score,
        outcome = :outcome, settlement_source = :source, settled_at = :settled_at
    WHERE observation_key = :observation_key AND status = 'pending'
      AND observed_at < kickoff AND kickoff <= :cutoff
      AND home_score IS NULL AND away_score IS NULL AND outcome IS NULL
""")


def _utc(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware fixture timestamp required")
    return dt.astimezone(timezone.utc)


def require_write_authorization():
    """Never use GitHub's read-only evaluation role to mutate evidence."""
    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("Staging settlement writes are prohibited in GitHub Actions")
    if os.getenv("BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE") != CONFIRMATION:
        raise RuntimeError(
            "Refusing write without BETSIGHTLY_STAGING_MARKET_SHADOW_WRITE="
            + CONFIRMATION
        )


def database_guard(*, write, db_engine):
    """Fail closed against a wrong database, permissive CI, or readonly writer."""
    name = preflight()
    if name != "betsightly_db_staging":
        raise RuntimeError("Wrong staging database")
    if write:
        require_write_authorization()
    with db_engine.connect() as conn:
        checks = conn.execute(text("""
            SELECT current_database() AS db_name,
                   current_setting('transaction_read_only') AS read_only,
                   to_regclass('public.market_shadow_forecasts_v1')
                       IS NOT NULL AS table_exists,
                   has_table_privilege(
                       CURRENT_USER, 'public.market_shadow_forecasts_v1',
                       'UPDATE'
                   ) AS can_update
        """)).mappings().one()
    if checks["db_name"] != "betsightly_db_staging" or not checks["table_exists"]:
        raise RuntimeError("Staging market-shadow warehouse missing or wrong DB")
    if write and (checks["read_only"] != "off" or not checks["can_update"]):
        raise RuntimeError("Writer must have explicit staging UPDATE permission")
    return name


def _normalize(name):
    from leagues.results_checker import _normalize_name
    return _normalize_name(name)


def _event_final(event, league_slug):
    """Require completed status, both named sides, exact UTC start and 90m score."""
    from leagues.results_checker import regulation_score
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
        return None
    competitors = comp.get("competitors") or []
    home = next((x for x in competitors if x.get("homeAway") == "home"), None)
    away = next((x for x in competitors if x.get("homeAway") == "away"), None)
    if home is None or away is None:
        return None
    home_name = (home.get("team") or {}).get("displayName")
    away_name = (away.get("team") or {}).get("displayName")
    if not home_name or not away_name or not event.get("date"):
        return None
    try:
        kickoff = _utc(event["date"])
    except (ValueError, TypeError):
        return None
    scored = regulation_score(comp)
    if not scored:
        return None
    try:
        hs, ass = int(scored["home_score"]), int(scored["away_score"])
    except (TypeError, ValueError, KeyError):
        return None
    if hs < 0 or ass < 0:
        return None
    event_id = str(event.get("id") or "")
    if not event_id:
        return None
    return {
        "league_slug": league_slug,
        "home": _normalize(home_name),
        "away": _normalize(away_name),
        "kickoff": kickoff,
        "home_score": hs,
        "away_score": ass,
        "source": f"espn:{league_slug}:{event_id}"[:80],
        "provider_event_id": event_id,
    }


def fetch_verified_finals(rows):
    """Read only completed ESPN events for the exact leagues/months required."""
    indexed = defaultdict(list)
    failures = Counter()
    requests_needed = sorted({
        (str(r["league_slug"]), _utc(r["kickoff"]).strftime("%Y%m"))
        for r in rows if r.get("league_slug")
    })
    for slug, month in requests_needed:
        # Never interpolate arbitrary slugs into a URL.
        if not slug or not all(c.isalnum() or c in "._-" for c in slug):
            failures["invalid_league_slug"] += 1
            continue
        try:
            response = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
                params={"dates": month, "limit": 500}, timeout=20,
            )
            if response.status_code != 200:
                failures[f"http_{response.status_code}"] += 1
                continue
            data = response.json()
            events = data.get("events") if isinstance(data, dict) else None
            if not isinstance(events, list):
                failures["invalid_response"] += 1
                continue
        except (requests.RequestException, ValueError):
            failures["provider_unavailable"] += 1
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            record = _event_final(event, slug)
            if record:
                indexed[(slug, record["home"], record["away"])].append(record)
    return indexed, dict(failures)


def _match_final(row, finals):
    """Require same league, exact named teams and kickoff within 90 minutes."""
    key = (
        str(row["league_slug"]),
        _normalize(row["home_team"]),
        _normalize(row["away_team"]),
    )
    fixture_kickoff = _utc(row["kickoff"])
    hits = [
        event for event in finals.get(key, ())
        if abs((_utc(event["kickoff"]) - fixture_kickoff).total_seconds()) <= 5400
    ]
    unique = {event["provider_event_id"]: event for event in hits}
    if len(unique) > 1:
        return None, "AMBIGUOUS_FINAL"
    if not unique:
        return None, "NO_EXACT_VERIFIED_FINAL"
    return next(iter(unique.values())), "VERIFIED"


def decisions_for_rows(rows, finals):
    """Prepare updates without ever treating a missing final as a loss/void."""
    from leagues.results_checker import _evaluate_pick
    updates = []
    skipped = Counter()
    matches = set()
    for row in rows:
        match, reason = _match_final(row, finals)
        if match is None:
            skipped[reason] += 1
            continue
        state = _evaluate_pick(
            {"market": row["market"], "home_team": row["home_team"],
             "away_team": row["away_team"]},
            match["home_score"], match["away_score"],
        )
        if state not in {"won", "lost", "void"}:
            skipped["UNSUPPORTED_MARKET"] += 1
            continue
        updates.append({
            "observation_key": row["observation_key"],
            "status": "void" if state == "void" else "settled",
            "outcome": None if state == "void" else int(state == "won"),
            "home_score": match["home_score"],
            "away_score": match["away_score"],
            "source": match["source"],
        })
        matches.add(row["fixture_id"])
    return updates, dict(skipped), len(matches)


def reconcile(*, write=False, limit=1000, now=None, db_engine=None,
              fetcher=fetch_verified_finals):
    from database import engine
    db_engine = db_engine or engine
    current = _utc(now or datetime.now(timezone.utc))
    cutoff = current - timedelta(hours=3)
    db_name = database_guard(write=write, db_engine=db_engine)
    bounded = max(1, min(1000, int(limit)))
    with db_engine.connect() as conn:
        rows = [dict(x) for x in conn.execute(
            SELECT_PENDING, {"cutoff": cutoff, "limit": bounded},
        ).mappings()]
    finals, failures = fetcher(rows) if rows else ({}, {})
    updates, unresolved, matched_fixtures = decisions_for_rows(rows, finals)
    affected = 0
    if write and updates:
        with db_engine.begin() as conn:
            for update in updates:
                result = conn.execute(
                    UPDATE_ONE,
                    {**update, "settled_at": current, "cutoff": cutoff},
                )
                affected += result.rowcount
    return {
        "status": "STAGING_SHADOW_SETTLEMENT" if write else "DRY_RUN_ONLY",
        "database": db_name,
        "write_executed": write,
        "pending_mature_rows_checked": len(rows),
        "verified_fixture_count": matched_fixtures,
        "would_settle": sum(u["status"] == "settled" for u in updates),
        "would_void": sum(u["status"] == "void" for u in updates),
        "rows_updated": affected,
        "unresolved": unresolved,
        "provider_failures": failures,
        "production_unchanged": True,
        "official_predictions_unchanged": True,
        "promotion_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--write-staging", action="store_true")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(
        reconcile(write=args.write_staging, limit=args.limit),
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
