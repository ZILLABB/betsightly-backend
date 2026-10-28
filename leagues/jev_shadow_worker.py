"""Opt-in staging-only pregame Jev worker; not a publication pipeline.

The external provider requests run only in a separately guarded staging
worker. In production this component *always* returns disabled. No guesses,
no stored result changes, no unbookable ticket substitutions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import re

from leagues.jev_shadow_decision import evaluate_shadow, runtime_status
from leagues.jev_shadow_ledger import claim, complete
from leagues.jev_source_matcher import matched_evidence_envelope

LOG = logging.getLogger(__name__)
MAX_FIXTURES_PER_BATCH = 6
MAX_LEAGUES_PER_BATCH = 3
MAX_SOURCES_PER_RUN = 3


def configured_sources(value: str) -> list[tuple[str, int, int]]:
    """Explicit matchday inventory, no arbitrary external URL or league."""
    from leagues.external_openligadb import source_url
    result: list[tuple[str, int, int]] = []
    for chunk in value.split(";"):
        if not chunk.strip():
            continue
        values = chunk.strip().split(":")
        if (len(values) != 3 or not re.fullmatch(r"\d{4}", values[1])
                or not re.fullmatch(r"\d{1,2}", values[2])):
            raise ValueError("Invalid source-matchday configuration")
        league, season, matchday = values[0], int(values[1]), int(values[2])
        source_url(league, season, matchday)
        row = (league, season, matchday)
        if row not in result:
            result.append(row)
        if len(result) > MAX_SOURCES_PER_RUN:
            raise ValueError("Too many source requests")
    return result


def run_shadow_batch(picks, snapshots, *, as_of: datetime,
                     environ=None, db_engine=None, transport=None):
    """Bounded operation with a persisted claim before each paid call."""
    status = runtime_status(environ)
    if not status["network_allowed"]:
        return {"status": status["status"], "shadow_only": True,
                "publication_changed": False, "jev_calls": 0}
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if not isinstance(snapshots, list) or len(snapshots) > MAX_SOURCES_PER_RUN:
        raise ValueError("Source snapshot count exceeds limit")
    counts = {"matched": 0, "quarantined": 0, "already_claimed": 0,
              "jev_calls": 0, "evaluated": 0, "unavailable": 0}
    processed = set()
    for pick in list(picks)[:80]:
        fixture_id = str(pick.get("match_id") or "")
        if not fixture_id or fixture_id in processed:
            continue
        for snapshot in snapshots:
            report = matched_evidence_envelope(pick, snapshot, as_of=as_of)
            if report.get("status") != "ready_for_shadow_review":
                continue
            processed.add(fixture_id)
            counts["matched"] += 1
            claim_result = claim(report, db_engine=db_engine)
            if not claim_result["claimed"]:
                counts["already_claimed"] += 1
                break
            answer = evaluate_shadow(report, environ=environ,
                                     transport=transport, now=as_of)
            if answer.get("network_called"):
                counts["jev_calls"] += 1
            if answer.get("status") == "shadow_evaluated":
                counts["evaluated"] += 1
            else:
                counts["unavailable"] += 1
            complete(claim_result["audit_key"], answer, db_engine=db_engine)
            break
        if counts["matched"] >= MAX_FIXTURES_PER_BATCH:
            break
    return {"status": "shadow_research_only", "shadow_only": True,
            "publication_changed": False, **counts}


def run_staging_once(*, environ=None, now=None):
    """Run a bounded batch from existing cached picks and selected matchdays.

    Designed for a future cloud cron/worker with a dedicated staging database.
    Never runs a source fetch or Jev call when no flags/credentials are set.
    """
    env = os.environ if environ is None else environ
    allowed = runtime_status(env)
    if not allowed["network_allowed"]:
        return {"status": allowed["status"], "publication_changed": False,
                "source_calls": 0, "jev_calls": 0}
    sources = configured_sources(env.get("BETSIGHTLY_JEV_SOURCE_MATCHDAYS", ""))
    if not sources:
        return {"status": "no_source_matchdays_configured",
                "publication_changed": False, "source_calls": 0, "jev_calls": 0}
    from leagues.engine import prepared_board
    from leagues.external_openligadb import fetch_matchday
    current = now or datetime.now(timezone.utc)
    picks, _, board = prepared_board(2)
    if not board.get("ready") or board.get("stale"):
        return {"status": "prepared_board_not_ready",
                "publication_changed": False, "source_calls": 0, "jev_calls": 0}
    snapshots = []
    for league, season, matchday in sources:
        reply = fetch_matchday(league, season, matchday, environ=env, now=current)
        if reply.get("status") == "ok":
            snapshots.append(reply)
    if not snapshots:
        return {"status": "no_valid_source_snapshots",
                "publication_changed": False,
                "source_calls": len(sources), "jev_calls": 0}
    outcome = run_shadow_batch(
        picks, snapshots, as_of=current, environ=env,
    )
    return {**outcome, "source_calls": len(sources)}


def scheduler_shadow_tick(*, environ=None):
    """Background scheduled work must not delay or change daily publication."""
    env = os.environ if environ is None else environ
    if env.get("ENVIRONMENT", "").lower() != "staging":
        return {"status": "staging_only", "published_changed": False}
    if str(env.get("BETSIGHTLY_JEV_WORKER_ENABLED", "")).lower() not in {
        "yes", "1", "true",
    }:
        return {"status": "worker_disabled", "published_changed": False}
    try:
        return run_staging_once(environ=env)
    except Exception as exc:
        LOG.warning("Jev shadow staging tick: %s", type(exc).__name__)
        return {"status": "worker_unavailable", "published_changed": False,
                "error_type": type(exc).__name__}
