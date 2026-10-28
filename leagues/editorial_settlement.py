"""Verified settlement of admin-curated bookmaker slips, isolated from model ROI.

No manual result is inserted into published_slips or model-calibration tables.
Only verified 90-minute full-time scores can decide a leg. A slip remains
pending for unresolved/ambiguous scores; lost slips are never made winners.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

LOG = logging.getLogger(__name__)
WAT = timezone(timedelta(hours=1))
TERMINAL = frozenset({"won", "lost", "void"})

# Full recovery can start at any wall-clock minute. The old minute % 15 == 0
# condition could permanently skip older legs if polling started off-boundary.
_ARCHIVE_SLOT_LOCK = threading.Lock()
_ARCHIVE_SLOT_LAST: int | None = None


def _claim_historical_recovery_day(
    older_days: list[str], now: datetime, *, full_recovery: bool = True
) -> str | None:
    global _ARCHIVE_SLOT_LAST
    if not older_days or not full_recovery:
        return None
    slot = int(now.astimezone(timezone.utc).timestamp()) // (15 * 60)
    with _ARCHIVE_SLOT_LOCK:
        if slot == _ARCHIVE_SLOT_LAST:
            return None
        _ARCHIVE_SLOT_LAST = slot
    # Rotate one older publication date per 15-minute slot.
    return older_days[slot % len(older_days)]



def _kickoff(game: dict):
    value = game.get("commence_time") or game.get("kickoff") or game.get("date")
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def grade_manual_slip(payload: dict, scores: dict, *, now=None,
                      observed_links: dict | None = None) -> dict:
    """Pure and idempotent, with the official evaluator but separate storage."""
    from leagues.results_checker import (
        _settlement_detail, _lookup_settlement_score, _normalize_name,
        _proposed_published_slip_status,
    )

    current = now or datetime.now(timezone.utc)
    original = payload.get("games") or []
    games = []
    outcomes = []
    for original_game in original:
        game = dict(original_game)
        if game.get("status") in TERMINAL:
            outcomes.append(game["status"])
            games.append(game)
            continue
        # This mapping comes from a separate, STRICT match of scoreboard
        # home + away + kickoff + competition. Record its immutable event ID
        # early; NEVER grade its live score or accept a changed claim.
        match_id = str(game.get("match_id") or "")
        if (not game.get("settlement_source_link") and observed_links
                and match_id in observed_links):
            game["settlement_source_link"] = observed_links[match_id]
        link = game.get("settlement_source_link")
        match = None
        if isinstance(link, dict) and link.get("provider") == "espn":
            final = scores.get(f"espn:event:{link.get('event_id')}")
            if final:
                kickoff = _kickoff(game)
                # A linked final cannot settle a different fixture/date/league
                # even if a provider reused or changed a fixture label.
                valid = (
                    not final.get("ambiguous")
                    and kickoff is not None
                    and final.get("date") == kickoff.date().isoformat()
                    and final.get("league_slug") == link.get("source_competition")
                    and _normalize_name(final.get("home") or "") ==
                    _normalize_name(game.get("home_team") or "")
                    and _normalize_name(final.get("away") or "") ==
                    _normalize_name(game.get("away_team") or "")
                )
                match = final if valid else {"ambiguous": True}
        if match is None:
            match = _lookup_settlement_score(
                scores, game.get("home_team", ""), game.get("away_team", ""),
                str(game.get("commence_time") or game.get("kickoff") or
                    game.get("date") or "")[:10],
            )
        outcome, detail = _settlement_detail(game, match, now=current)
        game["status"] = outcome
        if outcome == "pending":
            game["settlement_pending_reason"] = (
                detail.get("settlement_pending_reason") or "FINAL_SCORE_UNVERIFIED"
            )
        else:
            game.pop("settlement_pending_reason", None)
            if detail.get("settlement_evidence"):
                game["settlement_evidence"] = detail["settlement_evidence"]
        outcomes.append(outcome)
        games.append(game)

    proposed = _proposed_published_slip_status(games, outcomes, "accumulator")
    # Preserve a final result if later providers disagree or go offline.
    previously = payload.get("result_status") or "pending"
    status = previously if previously in TERMINAL else proposed
    updated = dict(payload)
    updated["games"] = games
    updated["result_status"] = status
    updated["settlement_track"] = "editorial_separate"
    updated["settled_legs"] = sum(v in TERMINAL for v in outcomes)
    updated["pending_legs"] = sum(v == "pending" for v in outcomes)
    if status in TERMINAL and not updated.get("settled_at"):
        updated["settled_at"] = current.isoformat()
    return updated


def _pending_manual_query(dialect_name: str) -> str:
    """Include historical unresolved legs: no silent 14-day settlement expiry.

    Recent tickets are always included to preserve previous behavior. Older
    terminal slips are skipped, but older *individual* pending legs must remain
    eligible even if the accumulator already has a losing leg.
    """
    select = "SELECT publish_date,tier,detail FROM editorial_tier_slips "
    if dialect_name == "postgresql":
        return (
            select +
            "WHERE publish_date >= :earliest OR EXISTS ("
            "SELECT 1 FROM jsonb_array_elements("
            "COALESCE(detail::jsonb->'games', '[]'::jsonb)) AS g "
            "WHERE COALESCE(g->>'status','pending')='pending'"
            ") ORDER BY publish_date,tier"
        )
    # The local SQLite test database does not implement jsonb_array_elements.
    return select + "ORDER BY publish_date,tier"


def settle_pending_manual(*, allow_fallback=True, now=None, score_collector=None) -> dict:
    """Called from the background results cycle; never a public GET."""
    from database import engine
    from leagues.results_checker import _collect_scores_for_picks

    current = now or datetime.now(timezone.utc)
    earliest = (current.astimezone(WAT).date() - timedelta(days=14)).isoformat()
    summary = {
        "slips_checked": 0, "won": 0, "lost": 0, "void": 0,
        "still_pending": 0, "legs_updated": 0,
        "due_legs": 0, "verified_final_matches": 0,
        "overdue_48h": 0, "unmapped_competitions": 0,
        "pending_reasons": {}, "score_source": "none",
        "new_fixture_links": 0, "historical_recovery_day": None,
    }
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(_pending_manual_query(conn.dialect.name)),
                {"earliest": earliest},
            ).all()
    except Exception as exc:
        # On a new deployment the table may not exist until the first manual
        # publication. Absence is not a reason to fail all settlement jobs.
        if type(exc).__name__ in {"ProgrammingError", "OperationalError"}:
            return summary
        raise

    # A vast historical backlog must never stretch each one-minute recent
    # settlement run into a months-wide ESPN scoreboard request. Keep current
    # 14-day work on every cycle; rotate through ONE older publish day once
    # per 15 minutes as a separate verified-score collector batch.
    older_days = sorted({
        str(day) for day, _, raw in rows
        if str(day) < earliest and any(
            g.get("status") not in TERMINAL
            for g in (json.loads(raw).get("games") or [])
        )
    })
    # The one-minute rapid lane must not consume historical free-provider
    # quota. Recover archived days in the comprehensive pass, once per slot.
    archive_day = _claim_historical_recovery_day(
        older_days, current, full_recovery=score_collector is None,
    )
    rows = [
        item for item in rows
        if str(item[0]) >= earliest or str(item[0]) == archive_day
    ]
    queued = []
    checkable = []
    checkable_recent = []
    checkable_archive = []
    linkable = []
    for day, tier, raw in rows:
        record = json.loads(raw)
        games = record.get("games") or []
        if not games or all(g.get("status") in TERMINAL for g in games):
            continue
        queued.append((day, tier))
        for game in games:
            if game.get("status") in TERMINAL:
                continue
            kickoff = _kickoff(game)
            if kickoff and not game.get("settlement_source_link"):
                linkable.append({**game, "date": game.get("date") or day})
            if kickoff and kickoff + timedelta(minutes=90) <= current:
                candidate = {**game, "date": game.get("date") or day}
                checkable.append(candidate)
                if str(day) < earliest:
                    checkable_archive.append(candidate)
                else:
                    checkable_recent.append(candidate)

    if not queued:
        return summary
    summary["historical_recovery_day"] = archive_day
    scores = {}
    if checkable:
        from leagues.live_scores import infer_published_competition_slugs
        from leagues.results_checker import _lookup_settlement_score
        summary["due_legs"] = len(checkable)
        _, summary["unmapped_competitions"] = (
            infer_published_competition_slugs(checkable))
        summary["overdue_48h"] = sum(
            1 for g in checkable
            if _kickoff(g) and _kickoff(g) + timedelta(hours=48) <= current
        )
        sources = []
        for batch in (checkable_recent, checkable_archive):
            if not batch:
                continue
            observed, source = (
                score_collector(batch) if score_collector is not None
                else _collect_scores_for_picks(
                    batch, allow_fallback=allow_fallback)
            )
            sources.append(source)
            for key, evidence in observed.items():
                prior = scores.get(key)
                if prior and prior != evidence:
                    scores[key] = {"ambiguous": True}
                elif not prior:
                    scores[key] = evidence
        summary["score_source"] = "+".join(sources) if sources else "none"
        for g in checkable:
            found = _lookup_settlement_score(
                scores, g.get("home_team", ""), g.get("away_team", ""),
                str(g.get("commence_time") or g.get("kickoff") or
                    g.get("date") or "")[:10],
            )
            if found and not found.get("ambiguous"):
                summary["verified_final_matches"] += 1
    # Save the scoreboard's stable event identity for future final-score
    # reconciliation. Live-score observations cannot themselves win a leg.
    links = {}
    if linkable and score_collector is None:
        try:
            from leagues.editorial_live_link import collect_verified_manual_links
            links = collect_verified_manual_links(linkable, now=current)
        except Exception as exc:
            LOG.warning("Manual live identity probe unavailable: %s",
                        type(exc).__name__)
    reasons = Counter()
    for day, tier in queued:
        with engine.begin() as conn:
            # A matching admin session cannot alter this already-published
            # identity. The lock prevents concurrent settling from undoing
            # another cycle's newer evidence.
            row = conn.execute(text(
                "SELECT detail FROM editorial_tier_slips "
                "WHERE publish_date=:d AND tier=:t FOR UPDATE"
            ), {"d": day, "t": tier}).scalar()
            if not row:
                continue
            previous = json.loads(row)
            if not previous.get("games"):
                continue
            graded = grade_manual_slip(previous, scores, now=current,
                                       observed_links=links)
            if graded != previous:
                conn.execute(text(
                    "UPDATE editorial_tier_slips SET detail=:payload "
                    "WHERE publish_date=:d AND tier=:t"
                ), {"payload": json.dumps(graded), "d": day, "t": tier})
                summary["legs_updated"] += sum(
                    a.get("status") != b.get("status")
                    for a, b in zip(previous["games"], graded["games"])
                )
                summary["new_fixture_links"] += sum(
                    not a.get("settlement_source_link")
                    and bool(b.get("settlement_source_link"))
                    for a, b in zip(previous["games"], graded["games"])
                )
        summary["slips_checked"] += 1
        for game in graded.get("games") or []:
            if game.get("status") == "pending":
                reasons[game.get("settlement_pending_reason") or
                        "FINAL_SCORE_UNVERIFIED"] += 1
        result = graded.get("result_status", "pending")
        if result in TERMINAL:
            summary[result] += 1
        else:
            summary["still_pending"] += 1
    summary["pending_reasons"] = dict(reasons)
    if summary["overdue_48h"] and not summary["verified_final_matches"]:
        LOG.warning(
            "Manual settlement backlog: checked=%s overdue_48h=%s "
            "unmapped_competitions=%s source=%s; verified_finals=0",
            summary["due_legs"], summary["overdue_48h"],
            summary["unmapped_competitions"], summary["score_source"],
        )
    return summary


def editorial_result_history(*, limit=30) -> dict:
    """Public, read-only results kept distinct from official prediction KPIs."""
    from database import engine
    size = max(1, min(int(limit), 90))
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT publish_date,tier,detail FROM editorial_tier_slips "
                "ORDER BY publish_date DESC,created_at DESC LIMIT :n"
            ), {"n": size}).all()
    except Exception:
        return {"status": "not_available", "manual_editorial": True, "results": []}
    slips = []
    for day, tier, raw in rows:
        item = json.loads(raw)
        outstanding = [g for g in (item.get("games") or [])
                       if g.get("status") not in TERMINAL]
        now = datetime.now(timezone.utc)
        old_unverified = sum(
            1 for g in outstanding if _kickoff(g)
            and _kickoff(g) + timedelta(hours=6) < now
        )
        reasons = Counter(
            g.get("settlement_pending_reason") or "FINAL_SCORE_UNVERIFIED"
            for g in outstanding
        )
        slips.append({
            "date": day, "tier": tier,
            "score_verification_delayed": old_unverified > 0,
            "overdue_unverified_legs": old_unverified,
            "pending_reason_counts": dict(reasons),
            "status": item.get("result_status") or "pending",
            "settled_at": item.get("settled_at"),
            "games": [
                {"home_team": g.get("home_team"), "away_team": g.get("away_team"),
                 "market": g.get("market"), "odds": g.get("odds"),
                 "kickoff": g.get("kickoff"),
                 "status": g.get("status") or "pending",
                 "settlement_pending_reason": g.get("settlement_pending_reason"),
                 "settlement_evidence": g.get("settlement_evidence")}
                for g in (item.get("games") or [])
            ],
            "total_odds": item.get("total_odds"),
            "editorial_manual": True,
        })
    return {"status": "success", "manual_editorial": True, "results": slips,
            "official_record_unchanged": True}
