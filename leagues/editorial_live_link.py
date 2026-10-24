"""One-time ESPN identity capture for manually published SportyBet fixtures.

Pre, live and full-time scoreboard observations are NOT settlement evidence.
This module stores only a verified provider EVENT ID after exact teams and
kickoff match. The normal final-score validator must still confirm FT/90'.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging

LOG = logging.getLogger(__name__)


def _datetime(raw: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _identity(game: dict) -> tuple[str, str, datetime] | None:
    from leagues.results_checker import _normalize_name

    kickoff = _datetime(game.get("kickoff_utc") or game.get("kickoff")
                        or game.get("commence_time") or game.get("date"))
    home = _normalize_name(game.get("home_team") or "")
    away = _normalize_name(game.get("away_team") or "")
    if kickoff is None or not home or not away or home == away:
        return None
    return home, away, kickoff


def collect_verified_manual_links(
    picks: list[dict], *, now: datetime | None = None, score_reader=None,
) -> dict[str, dict]:
    """Attach a unique ESPN event ID to recent manual bookmaking identities.

    Narrow, bounded scoreboard queries; no broad month sweep, no score grades.
    Unknown/ambiguous league labels, names, kickoff or event IDs fail closed.
    """
    from leagues.live_scores import (
        infer_published_competition_slugs, scores_for,
    )

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Identity reconciliation requires a timezone-aware clock")
    current = current.astimezone(timezone.utc)
    eligible: list[tuple[dict, str, tuple]] = []
    wanted: set[tuple[str, str]] = set()
    for pick in picks:
        if pick.get("status") in {"won", "lost", "void"}:
            continue
        if isinstance(pick.get("settlement_source_link"), dict):
            continue
        ident = _identity(pick)
        if not ident:
            continue
        # Linking is useful just before and shortly after play, not a full
        # historical backfill scan of every ungraded ticket every minute.
        if not (current - timedelta(hours=40) <= ident[2] <=
                current + timedelta(hours=8)):
            continue
        slug = str(pick.get("league_slug") or "")
        if not slug:
            slugs, unresolved = infer_published_competition_slugs([pick])
            if unresolved or len(slugs) != 1:
                continue
            slug = next(iter(slugs))
        # Only previously verified ESPN league slugs, never raw bookmaker URLs.
        mapped, unverified = infer_published_competition_slugs(
            [{"league_slug": slug}]
        )
        if unverified or mapped != {slug}:
            continue
        mid = str(pick.get("match_id") or "")
        if not mid:
            continue
        eligible.append((pick, slug, ident))
        wanted.add((slug, ident[2].strftime("%Y%m%d")))

    if not eligible:
        return {}
    # Cap outbound reads, rather than letting huge/old manual tickets trigger
    # unbounded requests. Later cycles will retry fixtures outside this slice.
    wanted = set(sorted(wanted)[:30])
    reader = score_reader or scores_for
    boards: dict[tuple[str, str], list[dict]] = {}
    for slug, day in sorted(wanted):
        try:
            board = reader([slug], day)
            boards[(slug, day)] = [
                row for row in (board or {}).values()
                if isinstance(row, dict) and row.get("source") == "espn"
            ]
        except Exception as exc:
            LOG.warning("Manual ESPN identity lookup unavailable: %s",
                        type(exc).__name__)
            boards[(slug, day)] = []

    linked = {}
    for pick, slug, (home, away, kickoff) in eligible:
        options = []
        for score in boards.get((slug, kickoff.strftime("%Y%m%d")), []):
            parsed = _identity(score)
            eid = str(score.get("provider_event_id") or "")
            if (not parsed or not eid.isdecimal()
                    or len(eid) > 20
                    or (parsed[0], parsed[1]) != (home, away)
                    or abs((parsed[2] - kickoff).total_seconds()) > 20*60):
                continue
            options.append((eid, parsed))
        # Reject multiple matching events or changing provider fixture IDs.
        if len(options) != 1:
            continue
        eid, (_, _, observed_kickoff) = options[0]
        mid = str(pick["match_id"])
        claim = linked.get(mid)
        proposed = {
            "provider": "espn",
            "event_id": eid,
            "fixture_day": kickoff.date().isoformat(),
            "kickoff_utc": kickoff.isoformat(),
            "observed_at": current.isoformat(),
            "source_competition": slug,
            "score_verified": False,
        }
        if claim and claim["event_id"] != eid:
            linked.pop(mid, None)
        elif not claim:
            linked[mid] = proposed

    # A single ESPN event may be reused across DIFFERENT slips with the
    # identical SportyBet match_id. Different bookmaker events cannot claim
    # the same ESPN identity without manual adjudication.
    by_event: dict[str, set[str]] = defaultdict(set)
    for mid, match in linked.items():
        by_event[match["event_id"]].add(mid)
    result = {
        mid: link for mid, link in linked.items()
        if len(by_event[link["event_id"]]) == 1
    }
    if result:
        LOG.info("Manual verified scoreboard identity links=%s", len(result))
    return result
