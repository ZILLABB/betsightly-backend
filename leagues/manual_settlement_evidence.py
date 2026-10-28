"""Two-step, append-only, admin-attested manual final-score evidence.

Never fetch user-controlled URLs. A posted link is an audit reference, not
machine verification. An authenticated reviewer must explicitly attest to
the original 90-minute score before the shared grading engine runs.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from urllib.parse import urlsplit

from sqlalchemy import text


def _utc(kickoff: object) -> datetime:
    try:
        dt = datetime.fromisoformat(str(kickoff or "").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Fixture kickoff lacks timezone")
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Fixture has no exact UTC kickoff; review cannot settle it") from None


def _validate_url(value: str) -> str:
    url = (value or "").strip()
    if not url or len(url) > 700 or any(ord(c) < 32 for c in url):
        raise ValueError("Provide a valid public official HTTPS match-result URL")
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if (parts.scheme != "https" or not host or parts.username or parts.password
            or parts.port not in (None, 443)
            or host == "localhost" or host.endswith((".local", ".internal", ".onion"))
            or not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host
            or re.fullmatch(r"[0-9.]+", host)):
        raise ValueError("Evidence must be a public official HTTPS source")
    # The server never requests this URL. The admin attests the content.
    return url


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _create_table(conn) -> None:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS manual_settlement_review_audit (
            review_id VARCHAR(36) NOT NULL,
            stage VARCHAR(12) NOT NULL,
            event_id VARCHAR(100) NOT NULL,
            record TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (review_id, stage),
            CHECK (stage IN ('proposed', 'approved'))
        )
    """))


def _load_record(raw):
    obj = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(obj, dict):
        raise ValueError("Stored ticket has invalid details")
    return obj


def _matching_games(rows, *, day: str, tier: str, event_id: str):
    selected = None
    for publish_day, saved_tier, raw in rows:
        if str(publish_day) != day or str(saved_tier) != tier:
            continue
        for game in _load_record(raw).get("games") or []:
            if str(game.get("sportybet_event_id") or "") == event_id:
                if selected is not None:
                    raise ValueError("Event is duplicated within the saved ticket")
                selected = game
    if selected is None:
        raise ValueError("No saved SportyBet event matches that date and tier")
    return selected


def _identity(game) -> dict:
    kickoff = _utc(game.get("kickoff") or game.get("commence_time"))
    return {
        "event_id": str(game.get("sportybet_event_id") or ""),
        "home": str(game.get("home_team") or ""),
        "away": str(game.get("away_team") or ""),
        "kickoff": kickoff.isoformat(),
        "league": str(game.get("league") or ""),
        "market": str(game.get("market") or ""),
    }


def _require_pending(game, now: datetime) -> None:
    if game.get("status", "pending") != "pending":
        raise ValueError("Event is already graded; settled results are immutable")
    kickoff = _utc(game.get("kickoff") or game.get("commence_time"))
    if kickoff + timedelta(minutes=90) > now:
        raise ValueError("Game has not completed regulation time")
    if not game.get("sportybet_event_id") or not game.get("home_team") or not game.get("away_team"):
        raise ValueError("Saved fixture has incomplete SportyBet identity")


def _rows(conn):
    sql = ("SELECT publish_date, tier, detail FROM editorial_tier_slips "
           "ORDER BY publish_date, tier")
    if conn.dialect.name == "postgresql":
        sql += " FOR UPDATE"
    return conn.execute(text(sql)).all()


def propose_evidence(*, publish_date: str, tier: str, event_id: str,
                     home_score: int, away_score: int, evidence_url: str,
                     evidence_note: str, actor: str) -> dict:
    """A proposal does not settle, grade or update any ticket."""
    from database import engine

    if not re.fullmatch(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]", publish_date):
        raise ValueError("Publication day must be YYYY-MM-DD")
    if not re.fullmatch(r"[a-z0-9_]{2,30}", tier):
        raise ValueError("Invalid tier")
    if not re.fullmatch(r"[A-Za-z0-9:_-]{3,100}", event_id):
        raise ValueError("Invalid SportyBet event identifier")
    if (type(home_score) is not int or type(away_score) is not int
            or not (0 <= home_score <= 30 and 0 <= away_score <= 30)):
        raise ValueError("Regulation-time goals must be integers between 0 and 30")
    url = _validate_url(evidence_url)
    note = (evidence_note or "").strip()
    if len(note) < 45 or len(note) > 1000:
        raise ValueError("Provide a 45–1000 character independent evidence explanation")
    if not actor:
        raise ValueError("Admin identity missing")

    with engine.begin() as conn:
        _create_table(conn)
        game = _matching_games(_rows(conn), day=publish_date, tier=tier,
                               event_id=event_id)
        current = _now()
        _require_pending(game, current)
        review_id = str(uuid4())
        payload = {
            "review_id": review_id,
            "publish_date": publish_date, "tier": tier,
            "fixture": _identity(game),
            "score_90": {"home": home_score, "away": away_score},
            "evidence_url": url, "evidence_note": note,
            "source_class": "human_inspected_official_match_report",
            "actor": actor, "proposed_at": current.isoformat(),
            "manual_attestation_required": True,
        }
        conn.execute(text(
            "INSERT INTO manual_settlement_review_audit "
            "(review_id,stage,event_id,record,created_at) "
            "VALUES (:rid,'proposed',:eid,:payload,:at)"
        ), {"rid": review_id, "eid": event_id,
            "payload": json.dumps(payload, sort_keys=True),
            "at": current.isoformat()})
    return {
        "status": "AWAITING_EXPLICIT_APPROVAL", "review_id": review_id,
        "fixture": payload["fixture"], "score_90": payload["score_90"],
        "evidence_url": url, "booking_unchanged": True,
        "message": ("Check the official source independently. Approval attests "
                    "that the score is the full 90-minute result, excluding extra "
                    "time and penalties."),
    }


def _grade_one(record: dict, *, fixture: dict, match: dict,
               now: datetime):
    from leagues.results_checker import _settlement_detail, _proposed_published_slip_status

    original = record.get("games") or []
    updated = []
    changes = 0
    for original_game in original:
        game = dict(original_game)
        if (str(game.get("sportybet_event_id") or "") == fixture["event_id"]
                and _identity(game) == fixture and
                game.get("status", "pending") == "pending"):
            outcome, detail = _settlement_detail(game, match, now=now)
            if outcome not in ("won", "lost", "void") or not detail.get("settlement_evidence"):
                raise ValueError("Market cannot be safely graded from the supplied score")
            game["status"] = outcome
            game["settlement_evidence"] = detail["settlement_evidence"]
            game.pop("settlement_pending_reason", None)
            changes += 1
        updated.append(game)
    if not changes:
        return None
    output = dict(record)
    output["games"] = updated
    statuses = [g.get("status", "pending") for g in updated]
    proposal = _proposed_published_slip_status(updated, statuses, "accumulator")
    previous = record.get("result_status") or "pending"
    output["result_status"] = previous if previous in ("won","lost","void") else proposal
    output["settled_legs"] = sum(s in ("won","lost","void") for s in statuses)
    output["pending_legs"] = sum(s == "pending" for s in statuses)
    output["settlement_track"] = "editorial_separate"
    if output["result_status"] in ("won","lost","void") and not output.get("settled_at"):
        output["settled_at"] = now.isoformat()
    return output


def approve_evidence(*, review_id: str, confirmed_event_id: str,
                     attest_regulation_90: bool, actor: str) -> dict:
    """The second explicit admin action commits score + append-only audit.

    Re-check the exact saved ticket under row locks, then grade every pending
    occurrence of the SAME immutable event identity. No unrelated fixture or
    previously settled leg can be changed.
    """
    from database import engine

    if not attest_regulation_90 or not actor:
        raise ValueError("Explicit 90-minute evidence attestation required")
    with engine.begin() as conn:
        _create_table(conn)
        fetched = conn.execute(text(
            "SELECT record FROM manual_settlement_review_audit "
            "WHERE review_id=:rid AND stage='proposed'"
        ), {"rid": review_id}).scalar()
        if not fetched:
            raise ValueError("Evidence proposal was not found")
        proposal = json.loads(fetched)
        fixture = proposal["fixture"]
        if confirmed_event_id != fixture["event_id"]:
            raise ValueError("Confirmation must repeat the exact SportyBet event ID")
        if conn.execute(text(
            "SELECT 1 FROM manual_settlement_review_audit "
            "WHERE review_id=:rid AND stage='approved'"
        ), {"rid": review_id}).first():
            return {"status": "ALREADY_APPROVED", "review_id": review_id}

        rows = _rows(conn)
        original = _matching_games(rows, day=proposal["publish_date"],
                                   tier=proposal["tier"], event_id=fixture["event_id"])
        current = _now()
        _require_pending(original, current)
        if _identity(original) != fixture:
            raise ValueError("Stored bookmaker fixture changed since proposal")
        score = proposal["score_90"]
        match = {
            "home_score": score["home"], "away_score": score["away"],
            "score_90": score, "provider": "admin-reviewed-official-evidence",
            "provider_event_id": fixture["event_id"],
            "match_status": "FT_90", "completed": True,
            "evidence_url": proposal["evidence_url"],
        }
        changed = []
        for day, tier, raw in rows:
            record = _load_record(raw)
            updated = _grade_one(record, fixture=fixture, match=match, now=current)
            if updated is None:
                continue
            conn.execute(text(
                "UPDATE editorial_tier_slips SET detail=:payload "
                "WHERE publish_date=:d AND tier=:t"
            ), {"payload":json.dumps(updated), "d":day, "t":tier})
            changed.append({"date":str(day), "tier":str(tier),
                            "previous_result":record.get("result_status", "pending"),
                            "result":updated["result_status"],
                            "event_id":fixture["event_id"]})
        if not changed:
            raise ValueError("No exact, pending event remains to settle")
        receipt = {
            "review_id": review_id, "stage":"approved", "actor":actor,
            "approved_at":current.isoformat(), "proposal": proposal,
            "changed_tickets": changed,
            "immutable_booking_codes":True, "model_results_untouched":True,
        }
        conn.execute(text(
            "INSERT INTO manual_settlement_review_audit "
            "(review_id,stage,event_id,record,created_at) "
            "VALUES (:rid,'approved',:eid,:payload,:at)"
        ), {"rid":review_id, "eid":fixture["event_id"],
            "payload":json.dumps(receipt,sort_keys=True),
            "at":current.isoformat()})
    return {
        "status":"APPROVED_AND_SETTLED", "review_id":review_id,
        "event_id":fixture["event_id"],
        "legs_updated":len(changed), "changed_tickets":changed,
        "booking_codes_unchanged":True,
    }
