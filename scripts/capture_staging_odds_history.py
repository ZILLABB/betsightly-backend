"""Capture real SportyBet cached-board prices into a separate staging warehouse.

Dry-run by default. NEVER re-label a cached snapshot with execution time:
captured_at is the provider board's original fetched_at, and a repeated source
snapshot is idempotent. Does not run the pipeline, fetch the sportsbook,
modify a prediction/settlement, publish, or generate a booking code.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from scripts.prepare_staging_board_once import preflight

TABLE = "public.sportybet_odds_history_v1"
CONFIRM = "CONFIRM_APPEND_ONLY_ODDS_HISTORY"
MAX_SNAPSHOT_AGE = timedelta(hours=6)
MIN_LEAD = timedelta(minutes=10)
CREATE_HISTORY = text("""
    CREATE TABLE IF NOT EXISTS public.sportybet_odds_history_v1 (
        snapshot_id VARCHAR(64) NOT NULL,
        sportybet_event_id VARCHAR(128) NOT NULL,
        market VARCHAR(64) NOT NULL,
        provider VARCHAR(24) NOT NULL DEFAULT 'sportybet',
        captured_at TIMESTAMPTZ NOT NULL,
        kickoff TIMESTAMPTZ NOT NULL,
        quoted_odds DOUBLE PRECISION NOT NULL,
        home_team VARCHAR(180) NOT NULL,
        away_team VARCHAR(180) NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (snapshot_id, sportybet_event_id, market),
        CONSTRAINT positive_bookmaker_odds CHECK (quoted_odds > 1),
        CONSTRAINT bookmaker_quote_prematch CHECK (captured_at < kickoff)
    )
""")
CREATE_INDEX = text("""
    CREATE INDEX IF NOT EXISTS ix_staging_odds_event_market_time
    ON public.sportybet_odds_history_v1
    (sportybet_event_id, market, captured_at)
""")
INSERT = text("""
    INSERT INTO public.sportybet_odds_history_v1
    (snapshot_id, sportybet_event_id, market, captured_at, kickoff,
     quoted_odds, home_team, away_team)
    VALUES (:snapshot_id, :sportybet_event_id, :market, :captured_at, :kickoff,
            :quoted_odds, :home_team, :away_team)
    ON CONFLICT (snapshot_id, sportybet_event_id, market) DO NOTHING
""")


def _utc(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def _source_entries(fixtures):
    """Accept the collision-safe SportyBet board cache without refetching."""
    if not isinstance(fixtures, dict):
        raise ValueError("SportyBet fixtures must be a mapping")
    for bucket in fixtures.values():
        if isinstance(bucket, dict):
            yield bucket
        elif isinstance(bucket, list):
            for entry in bucket:
                if isinstance(entry, dict):
                    yield entry


def rows_from_cache(cache: dict, *, now=None) -> tuple[list[dict], dict]:
    current = _utc(now or datetime.now(timezone.utc))
    meta = cache.get("metadata") or {}
    snapshot_id = str(meta.get("snapshot_id") or "")
    if not re.fullmatch(r"[a-f0-9]{16}", snapshot_id):
        raise ValueError("Missing/invalid source snapshot ID")
    if meta.get("is_complete") is not True or meta.get("error"):
        raise ValueError("Incomplete bookmaker board cannot become history")
    if not cache.get("fixtures"):
        raise ValueError("No cached bookmaker fixtures")
    try:
        source_timestamp = float(meta["fetched_at"])
        cache_timestamp = float(cache["fetched_at"])
    except (KeyError, ValueError, TypeError):
        raise ValueError("Source snapshot has no verified fetch time") from None
    if not all(math.isfinite(n) for n in (source_timestamp, cache_timestamp)):
        raise ValueError("Non-finite source fetch timestamp")
    if abs(source_timestamp - cache_timestamp) > 1:
        raise ValueError("Conflicting SportyBet snapshot timestamps")
    captured_at = _utc(source_timestamp)
    age = current - captured_at
    if age < timedelta(seconds=-30) or age > MAX_SNAPSHOT_AGE:
        raise ValueError("Cached board too old or dated in the future")

    deduped = {}
    rejected = {}
    fixture_ids = set()
    identities = {}
    for entry in _source_entries(cache["fixtures"]):
        event_id = str(entry.get("event_id") or "").strip()
        if not event_id or len(event_id) > 128:
            rejected["missing_event_id"] = rejected.get("missing_event_id", 0) + 1
            continue
        home = str(entry.get("home_team") or "").strip()
        away = str(entry.get("away_team") or "").strip()
        if not home or not away or len(home) > 180 or len(away) > 180:
            rejected["bad_teams"] = rejected.get("bad_teams", 0) + 1
            continue
        try:
            kickoff_ms = float(entry["kickoff_ms"])
            if not math.isfinite(kickoff_ms):
                raise ValueError("non-finite kickoff")
            kickoff = _utc(kickoff_ms / 1000)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            rejected["bad_kickoff"] = rejected.get("bad_kickoff", 0) + 1
            continue
        if kickoff - captured_at <= MIN_LEAD:
            rejected["started_or_near_kickoff"] = rejected.get(
                "started_or_near_kickoff", 0
            ) + 1
            continue
        # A bookmaker event ID must resolve to one fixture, even when
        # distinct partial pages list disjoint markets for that event.
        # Otherwise a collision silently joins unrelated odds as one match.
        identity = (home, away, kickoff)
        earlier_identity = identities.setdefault(event_id, identity)
        if earlier_identity != identity:
            raise ValueError("One source event ID mapped to multiple fixtures")
        prices = entry.get("prices") or {}
        if not isinstance(prices, dict):
            rejected["bad_price_map"] = rejected.get("bad_price_map", 0) + 1
            continue
        for market, raw in prices.items():
            market = str(market)
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", market):
                rejected["bad_market_key"] = rejected.get("bad_market_key", 0) + 1
                continue
            try:
                price = float(raw)
            except (TypeError, ValueError):
                rejected["bad_price"] = rejected.get("bad_price", 0) + 1
                continue
            if not math.isfinite(price) or price <= 1:
                rejected["bad_price"] = rejected.get("bad_price", 0) + 1
                continue
            record = {
                "snapshot_id": snapshot_id,
                "sportybet_event_id": event_id,
                "market": market,
                "captured_at": captured_at,
                "kickoff": kickoff,
                "quoted_odds": price,
                "home_team": home,
                "away_team": away,
            }
            key = (event_id, market)
            previous = deduped.get(key)
            if previous and previous != record:
                raise ValueError("Conflicting prices for same source event/market")
            deduped[key] = record
            fixture_ids.add(event_id)
    report = {
        "snapshot_id": snapshot_id,
        "source_captured_at": captured_at.isoformat(),
        "source_age_seconds": round(age.total_seconds()),
        "eligible_prices": len(deduped),
        "eligible_fixtures": len(fixture_ids),
        "skipped": rejected,
        "captured_from_existing_cache_only": True,
        "network_requests_made": False,
        "changes_to_predictions": False,
        "production_unchanged": True,
        "clv_proven": False,
    }
    if not deduped:
        raise ValueError("No eligible real, pre-match bookmaker prices")
    return list(deduped.values()), report


def fresh_bookmaker_cache(*, sportybet_module=None):
    """Get a genuinely new, complete bookmaker board without cache mutation.

    Opt-in only, staging CLI process with background jobs disabled.
    Ordinary model refresh, publishing and bookmaker_cache writes are NOT run.
    """
    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("No live-bookmaker fetches in GitHub Actions")
    if os.getenv("BETSIGHTLY_STAGING_ODDS_SOURCE_LIVE") != (
        "CONFIRM_SOURCE_ONLY_LIVE_FETCH"
    ):
        raise RuntimeError("Explicit staging source-only fetch guard required")
    if sportybet_module is None:
        from leagues import sportybet as sportybet_module
    original_get = sportybet_module._db_get
    original_set = sportybet_module._db_set
    try:
        sportybet_module._db_get = lambda *_a, **_kw: None
        sportybet_module._db_set = lambda *_a, **_kw: None
        board = sportybet_module.fetch_board(force=True)
    finally:
        sportybet_module._db_get = original_get
        sportybet_module._db_set = original_set
    if not isinstance(board, dict):
        raise ValueError("No complete live SportyBet board")
    metadata = dict(board.get("__meta__") or {})
    if metadata.get("is_complete") is not True or metadata.get("error"):
        raise ValueError("Incomplete live SportyBet board cannot be archived")
    if not metadata.get("fetched_at") or not metadata.get("snapshot_id"):
        raise ValueError("Live board lacks verified provider snapshot metadata")
    fixtures = {k: v for k, v in board.items() if not k.startswith("__")}
    if not fixtures:
        raise ValueError("Live SportyBet board has no upcoming fixtures")
    return {
        "metadata": metadata,
        "fetched_at": metadata["fetched_at"],
        "fixtures": fixtures,
    }


def require_write_guard():
    if os.getenv("GITHUB_ACTIONS", "").lower() == "true":
        raise RuntimeError("GitHub Actions cannot write bookmaker price history")
    if os.getenv("BETSIGHTLY_STAGING_ODDS_HISTORY_WRITE") != CONFIRM:
        raise RuntimeError(
            "Missing independent staging odds-history write confirmation"
        )


def capture(*, write=False, db_engine=None, now=None, source="cache",
            approve=None):
    """Only an explicit staging-admin invocation can create/append rows.

    For source=live, approval is invoked with the exact captured snapshot
    report before it is persisted. The real provider is NEVER re-fetched
    after approval; preview and write share one immutable in-memory quote set.
    """
    database = preflight()
    if database != "betsightly_db_staging":
        raise RuntimeError("Wrong database identity")
    if write:
        require_write_guard()
        if source == "live" and approve is None:
            raise RuntimeError(
                "Live source writes require same-snapshot operator review"
            )

    if db_engine is None:
        from database import engine
        db_engine = engine
    if db_engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL staging only")
    if source not in {"cache", "live"}:
        raise ValueError("Unknown SportyBet source mode")
    if source == "live":
        cache = fresh_bookmaker_cache()
    else:
        with db_engine.connect() as conn:
            row = conn.execute(text(
                "SELECT v FROM public.bookmaker_cache WHERE k = 'sportybet_board'"
            )).first()
        if not row or not row[0]:
            raise ValueError("SportyBet source cache not available")
        cache = json.loads(row[0])
    records, report = rows_from_cache(cache, now=now)
    report["source_mode"] = source
    report["captured_from_existing_cache_only"] = source == "cache"
    report["network_requests_made"] = source == "live"
    report["staging_bookmaker_cache_mutated"] = False
    report.update({
        "database": database,
        "mode": "WRITE_STAGING" if write else "DRY_RUN_ONLY",
        "rows_inserted": 0,
        "rows_already_captured": None,
        "append_only": True,
    })
    if not write:
        return report
    if approve is not None:
        # A refused or missing confirmation cannot fall through into a write.
        if approve(dict(report)) is not True:
            report["mode"] = "OPERATOR_DECLINED"
            return report

    # The exact pre-reviewed records are inserted. Never call fetch_board a
    # second time between the preview and this transaction.
    with db_engine.begin() as conn:
        if conn.execute(text("SHOW transaction_read_only")).scalar() != "off":
            raise RuntimeError("Writable staging transaction required")
        conn.execute(CREATE_HISTORY)
        conn.execute(CREATE_INDEX)
        existing = int(conn.execute(text("""
            SELECT COUNT(*) FROM public.sportybet_odds_history_v1
            WHERE snapshot_id = :sid
        """), {"sid": report["snapshot_id"]}).scalar())
        conn.execute(INSERT, records)
        after = int(conn.execute(text("""
            SELECT COUNT(*) FROM public.sportybet_odds_history_v1
            WHERE snapshot_id = :sid
        """), {"sid": report["snapshot_id"]}).scalar())
        inserted = after - existing
        if inserted < 0 or after > len(records):
            raise RuntimeError("Unexpected odds-history primary-key conflict")
    report["rows_inserted"] = inserted
    report["rows_already_captured"] = len(records) - inserted
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write-staging", action="store_true")
    mode.add_argument(
        "--review-live-and-write", action="store_true",
        help="Fetch once, preview exact fresh quotes, then ask before staging insert",
    )
    parser.add_argument(
        "--source", choices=("cache", "live"), default="cache",
        help="Cache-only by default; live requires separate source-only guard",
    )
    args = parser.parse_args()
    if args.review_live_and_write:
        if args.source != "live":
            parser.error("--review-live-and-write requires --source live")

        def approval(preview):
            print("Fresh, verified SOURCE snapshot preview:", flush=True)
            print(json.dumps(preview, indent=2, sort_keys=True), flush=True)
            try:
                reply = input(
                    "Type CAPTURE STAGING ODDS to append exactly this snapshot: "
                )
            except EOFError:
                return False
            return reply == "CAPTURE STAGING ODDS"

        result = capture(write=True, source="live", approve=approval)
    else:
        result = capture(write=args.write_staging, source=args.source)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
