"""Append-only operational facts for slip-builder requests.

The browser reports intent and UX interactions. This table records what the
server actually produced, without storing a SportyBet code or model inputs.
"""

from __future__ import annotations

import uuid
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, MetaData, String, Table,
    Text, select,
)

from database import engine
from leagues.policy_version import PUBLISHED_SELECTION_POLICY_VERSION

metadata = MetaData()
builder_runs = Table(
    "builder_runs", metadata,
    Column("request_id", String(36), primary_key=True),
    Column("requested_at", DateTime(timezone=True), nullable=False, index=True),
    Column("target_odds", Float, nullable=False),
    Column("horizon", String(16), nullable=False),
    Column("refresh", Boolean, nullable=False, default=False),
    Column("result_status", String(24), nullable=False),
    Column("leg_count", Integer),
    Column("generated_odds", Float),
    Column("ticket_produced", Boolean, nullable=False, default=False),
    Column("booking_status", String(32)),
    Column("actual_sportybet_odds", Float),
    Column("validation_status", String(32)),
    Column("failure_category", String(64)),
    Column("booking_variant_id", String(64)),
    Column("cached", Boolean, nullable=False, default=False),
)

builder_predictions = Table(
    "builder_predictions", metadata,
    Column("selection_fingerprint", String(64), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("target_odds", Float, nullable=False),
    Column("horizon", String(16), nullable=False),
    Column("generated_odds", Float, nullable=False),
    Column("actual_sportybet_odds", Float),
    Column("leg_count", Integer, nullable=False),
    Column("picks", Text, nullable=False),
    Column("hit_probability", Float),
    Column("target_hit_probability", Float),
    Column("no_loss_probability", Float),
    Column("expected_return", Float),
    Column("avg_confidence", Float),
    Column("avg_evidence_probability", Float),
    Column("minimum_trust_score", Float),
    Column("policy_version", String(40)),
    Column("booking_status", String(32)),
    Column("validation_status", String(32)),
    Column("final_status", String(20), nullable=False, default="pending"),
    Column("all_win", Boolean),
    Column("target_reached", Boolean),
    Column("settled_at", DateTime(timezone=True)),
    Column("actual_settled_return", Float),
    Column("sportybet_settled_return", Float),
    Column("profit", Float),
)


def ensure_table() -> None:
    metadata.create_all(
        engine, tables=[builder_runs, builder_predictions], checkfirst=True
    )


def _failure_category(result: dict) -> str | None:
    booking = result.get("booking") or {}
    status = str(booking.get("booking_status") or booking.get("status") or "").upper()
    if result.get("status") != "success":
        return str(result.get("status") or "generation_failed")[:64]
    if not booking.get("share_code"):
        return status or "NO_BOOKING_CODE"
    if str(booking.get("readback_validation") or "").upper() not in ("", "PASSED"):
        return "VALIDATION_FAILED"
    return None


def record_run(target: float, horizon: str, refresh: bool, result: dict,
               *, cached: bool = False, request_id: str | None = None) -> str:
    """Persist one request outcome. Raises only to its caller, which logs and continues."""
    ensure_table()
    booking = result.get("booking") or {}
    produced = bool(booking.get("status") == "active" and booking.get("share_code"))
    request_id = request_id or str(uuid.uuid4())
    row = {
        "request_id": request_id,
        "requested_at": datetime.now(timezone.utc),
        "target_odds": float(target), "horizon": str(horizon)[:16],
        "refresh": bool(refresh), "result_status": str(result.get("status") or "error")[:24],
        "leg_count": result.get("legs"), "generated_odds": result.get("odds"),
        "ticket_produced": produced,
        "booking_status": str(booking.get("booking_status") or booking.get("status") or "")[:32] or None,
        "actual_sportybet_odds": booking.get("actual_sportybet_odds"),
        "validation_status": str(booking.get("readback_validation") or "")[:32] or None,
        "failure_category": _failure_category(result),
        "booking_variant_id": str(booking.get("sportybet_selection_fingerprint") or
                                  booking.get("booking_variant_fingerprint") or "")[:64] or None,
        "cached": bool(cached),
    }
    with engine.begin() as conn:
        conn.execute(builder_runs.insert().values(**row))
    if result.get("status") == "success" and result.get("games"):
        try:
            record_prediction(target, horizon, result)
        except Exception:
            # Outcome measurement must never break the user-facing Builder.
            pass
    return request_id


def _prediction_fingerprint(result: dict) -> str:
    from leagues.booking import leg_fingerprint
    return leg_fingerprint(result.get("games") or [])


def record_prediction(target: float, horizon: str, result: dict) -> bool:
    """Persist one immutable generated selection set, not one row per click."""
    ensure_table()
    games = result.get("games") or []
    if not games:
        return False
    fingerprint = _prediction_fingerprint(result)
    booking = result.get("booking") or {}
    row = {
        "selection_fingerprint": fingerprint,
        "created_at": datetime.now(timezone.utc),
        "target_odds": float(target),
        "horizon": str(horizon)[:16],
        "generated_odds": float(result.get("odds") or 1.0),
        "actual_sportybet_odds": (
            booking.get("actual_sportybet_odds")
            if str(booking.get("readback_validation") or "").upper() == "PASSED"
            else None
        ),
        "leg_count": len(games),
        "picks": json.dumps(games),
        "hit_probability": result.get("hit_probability"),
        "target_hit_probability": result.get("target_hit_probability"),
        "no_loss_probability": result.get("no_loss_probability"),
        "expected_return": result.get("expected_return"),
        "avg_confidence": result.get("avg_confidence"),
        "avg_evidence_probability": result.get("avg_evidence_probability"),
        "minimum_trust_score": result.get("minimum_trust_score"),
        "policy_version": PUBLISHED_SELECTION_POLICY_VERSION,
        "booking_status": str(booking.get("booking_status") or
                              booking.get("status") or "")[:32] or None,
        "validation_status": str(booking.get("readback_validation") or "")[:32]
        or None,
        "final_status": "pending",
    }
    with engine.begin() as conn:
        if conn.execute(select(builder_predictions.c.selection_fingerprint).where(
            builder_predictions.c.selection_fingerprint == fingerprint
        )).first():
            return False
        conn.execute(builder_predictions.insert().values(**row))
    return True


def pending_predictions() -> list[dict]:
    ensure_table()
    with engine.begin() as conn:
        rows = conn.execute(select(builder_predictions).where(
            builder_predictions.c.final_status == "pending"
        )).mappings().all()
    return [dict(row) for row in rows]


def settle_prediction(fingerprint: str, outcomes: list[str]) -> str | None:
    """Apply market-aware leg results already evaluated by results_checker."""
    ensure_table()
    with engine.begin() as conn:
        row = conn.execute(select(builder_predictions).where(
            builder_predictions.c.selection_fingerprint == fingerprint
        )).mappings().first()
        if not row:
            return None
        picks = json.loads(row["picks"] or "[]")
        for pick, outcome in zip(picks, outcomes):
            pick["status"] = outcome
        if not outcomes or any(outcome == "pending" for outcome in outcomes):
            status = "pending"
        elif any(outcome == "lost" for outcome in outcomes):
            status = "lost"
        elif all(outcome == "void" for outcome in outcomes):
            status = "void"
        else:
            status = "won"

        values = {"picks": json.dumps(picks)}
        if status != "pending":
            from leagues.picks_db import settled_accumulator_return
            settled_return, _ = settled_accumulator_return({
                "status": status,
                "picks": picks,
                "total_odds": row["generated_odds"],
            })
            sportybet_return = None
            if row["actual_sportybet_odds"] is not None:
                if status == "lost":
                    sportybet_return = 0.0
                elif status == "void":
                    sportybet_return = 1.0
                elif not any(outcome == "void" for outcome in outcomes):
                    sportybet_return = float(row["actual_sportybet_odds"])
                else:
                    # The stored SportyBet fact is an aggregate readback price.
                    # It cannot reveal the exact remaining price after a push,
                    # so exclude this build from actual-odds ROI instead of
                    # substituting the model/published leg prices.
                    sportybet_return = None
            values.update({
                "final_status": status,
                "all_win": bool(outcomes) and all(outcome == "won"
                                                     for outcome in outcomes),
                "target_reached": settled_return >= float(row["target_odds"]),
                "settled_at": datetime.now(timezone.utc),
                "actual_settled_return": round(settled_return, 6),
                "sportybet_settled_return": (
                    round(sportybet_return, 6)
                    if sportybet_return is not None else None
                ),
                "profit": round(settled_return - 1.0, 6),
            })
        conn.execute(builder_predictions.update().where(
            builder_predictions.c.selection_fingerprint == fingerprint
        ).values(**values))
    return status


def _performance_rows(rows: list[dict]) -> dict:
    settled = [row for row in rows if row["final_status"] in
               ("won", "lost", "void")]
    graded = [row for row in settled if row["final_status"] in ("won", "lost")]
    staked = len(graded)
    returned = sum(float(row["actual_settled_return"] or 0) for row in graded)
    sporty = [row for row in graded if row["sportybet_settled_return"] is not None]
    sporty_returned = sum(float(row["sportybet_settled_return"] or 0)
                          for row in sporty)
    probability_rows = [row for row in settled if row["hit_probability"] is not None
                        and row["all_win"] is not None]
    brier = (sum((float(row["hit_probability"]) - int(bool(row["all_win"]))) ** 2
                 for row in probability_rows) / len(probability_rows)
             if probability_rows else None)
    return {
        "unique_settled_builds": len(settled),
        "won": sum(row["final_status"] == "won" for row in settled),
        "lost": sum(row["final_status"] == "lost" for row in settled),
        "void": sum(row["final_status"] == "void" for row in settled),
        "target_reached_after_pushes": sum(bool(row["target_reached"])
                                           for row in settled),
        "average_predicted_hit_probability": (
            round(sum(float(row["hit_probability"]) for row in probability_rows)
                  / len(probability_rows), 4) if probability_rows else None
        ),
        "actual_all_win_rate": (
            round(sum(bool(row["all_win"]) for row in probability_rows)
                  / len(probability_rows), 4) if probability_rows else None
        ),
        "brier_score": round(brier, 5) if brier is not None else None,
        "published_record": {
            "settled": staked, "returned": round(returned, 4),
            "profit": round(returned - staked, 4),
            "roi": round((returned - staked) / staked, 4) if staked else None,
        },
        "bookable_record": {
            "settled": len(sporty), "returned": round(sporty_returned, 4),
            "profit": round(sporty_returned - len(sporty), 4),
            "roi": round((sporty_returned - len(sporty)) / len(sporty), 4)
            if sporty else None,
            "coverage": round(len(sporty) / staked, 4) if staked else 0.0,
        },
    }


def performance(days: int = 90) -> dict:
    ensure_table()
    first = datetime.now(timezone.utc) - timedelta(days=max(1, days) - 1)
    first = first.replace(hour=0, minute=0, second=0, microsecond=0)
    with engine.begin() as conn:
        rows = [dict(row) for row in conn.execute(select(builder_predictions).where(
            builder_predictions.c.created_at >= first
        )).mappings().all()]
    settled = [row for row in rows if row["final_status"] in
               ("won", "lost", "void")]
    by_target = {}
    for target in sorted({row["target_odds"] for row in settled}):
        by_target[str(int(target) if float(target).is_integer() else target)] = (
            _performance_rows([row for row in settled if row["target_odds"] == target])
        )
    by_horizon = {
        horizon: _performance_rows([row for row in settled
                                    if row["horizon"] == horizon])
        for horizon in sorted({row["horizon"] for row in settled})
    }
    return {
        "builds_generated": len(rows),
        "policy_version": PUBLISHED_SELECTION_POLICY_VERSION,
        **_performance_rows(rows),
        "by_target": by_target,
        "by_horizon": by_horizon,
    }


def summary(start: str, end: str) -> dict:
    ensure_table()
    first = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    last = last.replace(hour=23, minute=59, second=59, microsecond=999999)
    with engine.begin() as conn:
        rows = conn.execute(select(builder_runs).where(
            builder_runs.c.requested_at >= first,
            builder_runs.c.requested_at <= last,
        )).mappings().all()
    targets, failures = defaultdict(Counter), Counter()
    for row in rows:
        key = str(int(row["target_odds"]) if float(row["target_odds"]).is_integer()
                  else row["target_odds"])
        targets[key]["requests"] += 1
        targets[key]["tickets"] += int(bool(row["ticket_produced"]))
        if row["failure_category"]:
            failures[row["failure_category"]] += 1
    produced = sum(bool(row["ticket_produced"]) for row in rows)
    return {
        "requests": len(rows), "tickets_produced": produced,
        "ticket_rate": round(produced / len(rows), 4) if rows else None,
        "cache_hits": sum(bool(row["cached"]) for row in rows),
        "by_target": [{"target": key, **dict(value)} for key, value in sorted(targets.items())],
        "failures": [{"category": key, "count": value} for key, value in failures.most_common()],
    }
