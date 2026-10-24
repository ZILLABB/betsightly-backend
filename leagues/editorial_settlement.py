"""Verified settlement of admin-curated bookmaker slips, isolated from model ROI.

No manual result is inserted into published_slips or model-calibration tables.
Only verified 90-minute full-time scores can decide a leg. A slip remains
pending for unresolved/ambiguous scores; lost slips are never made winners.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

LOG = logging.getLogger(__name__)
WAT = timezone(timedelta(hours=1))
TERMINAL = frozenset({"won", "lost", "void"})


def _kickoff(game: dict):
    value = game.get("commence_time") or game.get("kickoff") or game.get("date")
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def grade_manual_slip(payload: dict, scores: dict, *, now=None) -> dict:
    """Pure and idempotent, with the official evaluator but separate storage."""
    from leagues.results_checker import (
        _settlement_detail, _lookup_settlement_score,
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
    }
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT publish_date,tier,detail FROM editorial_tier_slips "
                "WHERE publish_date >= :earliest ORDER BY publish_date,tier"
            ), {"earliest": earliest}).all()
    except Exception as exc:
        # On a new deployment the table may not exist until the first manual
        # publication. Absence is not a reason to fail all settlement jobs.
        if type(exc).__name__ in {"ProgrammingError", "OperationalError"}:
            return summary
        raise

    queued = []
    checkable = []
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
            if kickoff and kickoff + timedelta(minutes=90) <= current:
                checkable.append({**game, "date": game.get("date") or day})

    if not queued:
        return summary
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
        scores, summary["score_source"] = (
            score_collector(checkable) if score_collector is not None
            else _collect_scores_for_picks(checkable, allow_fallback=allow_fallback)
        )
        for g in checkable:
            found = _lookup_settlement_score(
                scores, g.get("home_team", ""), g.get("away_team", ""),
                str(g.get("commence_time") or g.get("kickoff") or
                    g.get("date") or "")[:10],
            )
            if found and not found.get("ambiguous"):
                summary["verified_final_matches"] += 1
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
            graded = grade_manual_slip(previous, scores, now=current)
            if graded != previous:
                conn.execute(text(
                    "UPDATE editorial_tier_slips SET detail=:payload "
                    "WHERE publish_date=:d AND tier=:t"
                ), {"payload": json.dumps(graded), "d": day, "t": tier})
                summary["legs_updated"] += sum(
                    a.get("status") != b.get("status")
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
