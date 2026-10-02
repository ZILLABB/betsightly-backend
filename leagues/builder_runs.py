"""Append-only operational facts for slip-builder requests.

The browser reports intent and UX interactions. This table records what the
server actually produced, without storing a SportyBet code or model inputs.
"""

from __future__ import annotations

import uuid
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, MetaData, String, Table,
    Text, select, text,
)

from database import engine
from leagues.policy_version import PUBLISHED_SELECTION_POLICY_VERSION

metadata = MetaData()
builder_runs = Table(
    "builder_runs", metadata,
    Column("request_id", String(36), primary_key=True),
    Column("requested_at", DateTime(timezone=True), nullable=False, index=True),
    Column("target_odds", Float, nullable=True),
    Column("mode", String(24), nullable=False, server_default="target_odds"),
    Column("horizon", String(16), nullable=False),
    # Request intent is operational provenance, not model input.  Keeping it
    # alongside the produced market mix makes broader-fill runs auditable.
    Column("fill_strategy", String(48)),
    Column("requested_markets", Text),
    Column("selected_markets", Text),
    Column("requested_game_count", Integer),
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
    Column("target_odds", Float, nullable=True),
    Column("mode", String(24), nullable=False, server_default="target_odds"),
    Column("board_context", Text),
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


def _postgres_v2_schema_statements() -> tuple[str, ...]:
    """Idempotent reconciliation for pre-V2 runtime-created Builder tables."""
    return (
        "ALTER TABLE builder_runs "
        "ADD COLUMN IF NOT EXISTS mode VARCHAR(24) "
        "NOT NULL DEFAULT 'target_odds'",

        "ALTER TABLE builder_runs "
        "ADD COLUMN IF NOT EXISTS fill_strategy VARCHAR(48)",

        "ALTER TABLE builder_runs "
        "ADD COLUMN IF NOT EXISTS requested_markets TEXT",

        "ALTER TABLE builder_runs "
        "ADD COLUMN IF NOT EXISTS selected_markets TEXT",

        "ALTER TABLE builder_runs "
        "ADD COLUMN IF NOT EXISTS requested_game_count INTEGER",

        "ALTER TABLE builder_runs "
        "ALTER COLUMN target_odds DROP NOT NULL",

        "ALTER TABLE builder_predictions "
        "ADD COLUMN IF NOT EXISTS mode VARCHAR(24) "
        "NOT NULL DEFAULT 'target_odds'",

        "ALTER TABLE builder_predictions "
        "ADD COLUMN IF NOT EXISTS board_context TEXT",

        "ALTER TABLE builder_predictions "
        "ALTER COLUMN target_odds DROP NOT NULL",
    )


def ensure_table() -> None:
    metadata.create_all(
        engine, tables=[builder_runs, builder_predictions], checkfirst=True
    )

    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as conn:
        for statement in _postgres_v2_schema_statements():
            conn.execute(text(statement))


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


def record_run(target: float | None, horizon: str, refresh: bool, result: dict,
               *, cached: bool = False, request_id: str | None = None,
               mode: str = "target_odds", fill_strategy: str | None = None,
               requested_markets: list[str] | None = None,
               requested_game_count: int | None = None) -> str:
    """Persist one request outcome. Raises only to its caller, which logs and continues."""
    ensure_table()
    booking = result.get("booking") or {}
    produced = bool(booking.get("status") == "active" and booking.get("share_code"))
    request_id = request_id or str(uuid.uuid4())
    selected_markets = sorted({str(game.get("market")) for game in result.get("games") or []
                               if game.get("market")})
    row = {
        "request_id": request_id,
        "requested_at": datetime.now(timezone.utc),
        "target_odds": float(target) if target is not None else None,
        "mode": mode, "horizon": str(horizon)[:16],
        "fill_strategy": str(fill_strategy)[:48] if fill_strategy else None,
        "requested_markets": json.dumps(sorted({str(m) for m in requested_markets or []})),
        "selected_markets": json.dumps(selected_markets),
        "requested_game_count": int(requested_game_count) if requested_game_count is not None else None,
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
            record_prediction(target, horizon, result, mode=mode)
        except Exception as exc:
            # Outcome measurement must never break the user-facing Builder,
            # but a failed archive must be observable without logging inputs.
            logging.getLogger(__name__).error(
                "builder_prediction_persistence_failed request_id=%s error_type=%s",
                request_id, type(exc).__name__,
            )
    return request_id


def _prediction_fingerprint(result: dict) -> str:
    from leagues.booking import leg_fingerprint
    return leg_fingerprint(result.get("games") or [])


def record_prediction(target: float | None, horizon: str, result: dict,
                      *, mode: str = "target_odds") -> bool:
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
        "target_odds": float(target) if target is not None else None,
        "mode": mode,
        "board_context": json.dumps(result.get("board") or {}),
        "horizon": str(horizon)[:16],
        "generated_odds": float(result.get("odds") or 1.0),
        "actual_sportybet_odds": (
            booking.get("actual_sportybet_odds")
            if str(booking.get("readback_validation") or "").upper() == "PASSED"
            else None
        ),
        "leg_count": len(games),
        "picks": json.dumps(games),
        "hit_probability": result.get("hit_probability", result.get("estimated_all_leg_probability")),
        "target_hit_probability": result.get("target_hit_probability"),
        "no_loss_probability": result.get("no_loss_probability"),
        "expected_return": result.get("expected_return", result.get("estimated_expected_return")),
        "avg_confidence": result.get("avg_confidence", result.get("average_probability")),
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
        rows = conn.execute(select(builder_predictions)).mappings().all()
    return [dict(row) for row in rows if row["final_status"] == "pending" or
            any(pick.get("status") in (None, "pending")
                for pick in json.loads(row["picks"] or "[]"))]


def settle_prediction(fingerprint: str, outcomes: list[str],
                      details: list[dict] | None = None) -> str | None:
    """Apply market-aware leg results already evaluated by results_checker."""
    ensure_table()
    with engine.begin() as conn:
        row = conn.execute(
            select(builder_predictions)
            .where(
                builder_predictions.c.selection_fingerprint == fingerprint
            )
            .with_for_update()
        ).mappings().first()
        if not row:
            return None
        picks = json.loads(row["picks"] or "[]")
        outcomes = list(outcomes)
        for index, (pick, outcome) in enumerate(zip(picks, outcomes)):
            detail = (details or [])[index] if index < len(details or []) else {}
            if pick.get("status") in ("won", "lost", "void"):
                outcomes[index] = pick["status"]
                continue
            pick["status"] = outcome
            if outcome == "pending":
                if detail.get("settlement_pending_reason"):
                    pick["settlement_pending_reason"] = detail["settlement_pending_reason"]
            else:
                pick.pop("settlement_pending_reason", None)
                if detail.get("settlement_evidence") and not pick.get("settlement_evidence"):
                    pick["settlement_evidence"] = detail["settlement_evidence"]
        already_decided = row["final_status"] in ("won", "lost", "void")
        if already_decided:
            status = row["final_status"]
        elif any(outcome == "lost" for outcome in outcomes):
            status = "lost"
        elif not outcomes or any(outcome == "pending" for outcome in outcomes):
            status = "pending"
        elif all(outcome == "void" for outcome in outcomes):
            status = "void"
        else:
            status = "won"

        values = {"picks": json.dumps(picks)}
        if status != "pending" and not already_decided:
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
                "target_reached": (settled_return >= float(row["target_odds"])
                                   if row["target_odds"] is not None else None),
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
    for target in sorted({row["target_odds"] for row in settled if row["target_odds"] is not None}):
        by_target[str(int(target) if float(target).is_integer() else target)] = (
            _performance_rows([row for row in settled if row["target_odds"] == target])
        )
    by_horizon = {
        horizon: _performance_rows([row for row in settled
                                    if row["horizon"] == horizon])
        for horizon in sorted({row["horizon"] for row in settled})
    }
    by_mode = {
        mode: _performance_rows([
            row for row in settled
            if str(row.get("mode") or "target_odds") == mode
        ])
        for mode in sorted({
            str(row.get("mode") or "target_odds")
            for row in settled
        })
    }

    by_leg_count = {
        str(count): _performance_rows([
            row for row in settled
            if int(row.get("leg_count") or 0) == count
        ])
        for count in sorted({
            int(row.get("leg_count") or 0)
            for row in settled
            if int(row.get("leg_count") or 0) > 0
        })
    }

    markets: dict[str, list[dict]] = defaultdict(list)
    for row in settled:
        try:
            picks = json.loads(row.get("picks") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            picks = []

        for market in sorted({
            str(pick.get("market") or "").strip()
            for pick in picks
            if str(pick.get("market") or "").strip()
        }):
            markets[market].append(row)

    by_market_presence = {
        market: _performance_rows(items)
        for market, items in sorted(markets.items())
    }

    return {
        "builds_generated": len(rows),
        "pending_builds": sum(
            row.get("final_status") == "pending"
            for row in rows
        ),
        "policy_version": PUBLISHED_SELECTION_POLICY_VERSION,
        **_performance_rows(rows),
        "by_target": by_target,
        "by_horizon": by_horizon,
        "by_mode": by_mode,
        "by_leg_count": by_leg_count,
        # Build-level metric: a multi-market ticket can appear in more than
        # one bucket. This deliberately does not pretend to be leg-level ROI.
        "by_market_presence": by_market_presence,
    }


def _safe_list(value) -> list[str]:
    if not value:
        return []

    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(parsed, list):
        return []

    return sorted({
        str(item).strip()
        for item in parsed
        if str(item).strip()
    })


def _request_metrics(rows) -> dict:
    items = list(rows)
    produced = sum(
        bool(row["ticket_produced"])
        for row in items
    )

    return {
        "requests": len(items),
        "tickets_produced": produced,
        "ticket_rate": (
            round(produced / len(items), 4)
            if items
            else None
        ),
        "cache_hits": sum(
            bool(row["cached"])
            for row in items
        ),
    }


def _sort_group_key(value: str):
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _group_requests(rows, label: str, value_fn) -> list[dict]:
    buckets = defaultdict(list)

    for row in rows:
        value = value_fn(row)

        if value is None or value == "":
            continue

        buckets[str(value)].append(row)

    return [
        {
            label: key,
            **_request_metrics(items),
        }
        for key, items in sorted(
            buckets.items(),
            key=lambda item: _sort_group_key(item[0]),
        )
    ]


def _market_request_groups(rows, column: str) -> list[dict]:
    buckets = defaultdict(list)

    for row in rows:
        for market in _safe_list(row[column]):
            buckets[market].append(row)

    return [
        {
            "market": market,
            **_request_metrics(items),
        }
        for market, items in sorted(buckets.items())
    ]


def summary(start: str, end: str) -> dict:
    """Operational V2 Builder request contract.

    Request metrics answer what users asked the Builder to do. Settlement
    performance remains separate in :func:`performance`, because one click and
    one immutable generated selection set are intentionally different facts.
    """
    ensure_table()

    first = datetime.strptime(
        start,
        "%Y-%m-%d",
    ).replace(tzinfo=timezone.utc)

    last = datetime.strptime(
        end,
        "%Y-%m-%d",
    ).replace(tzinfo=timezone.utc)

    last = last.replace(
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    )

    with engine.begin() as conn:
        rows = list(
            conn.execute(
                select(builder_runs).where(
                    builder_runs.c.requested_at >= first,
                    builder_runs.c.requested_at <= last,
                )
            ).mappings().all()
        )

    failures = Counter()

    for row in rows:
        if row["failure_category"]:
            failures[
                str(row["failure_category"])
            ] += 1

    overall = _request_metrics(rows)

    by_target = _group_requests(
        [
            row for row in rows
            if row["target_odds"] is not None
        ],
        "target",
        lambda row: (
            str(
                int(row["target_odds"])
                if float(row["target_odds"]).is_integer()
                else row["target_odds"]
            )
        ),
    )

    by_mode = _group_requests(
        rows,
        "mode",
        lambda row: str(
            row["mode"]
            or "target_odds"
        ),
    )

    by_horizon = _group_requests(
        rows,
        "horizon",
        lambda row: row["horizon"],
    )

    by_game_count = _group_requests(
        [
            row for row in rows
            if row["requested_game_count"] is not None
        ],
        "game_count",
        lambda row: int(
            row["requested_game_count"]
        ),
    )

    by_fill_strategy = _group_requests(
        [
            row for row in rows
            if row["fill_strategy"]
        ],
        "fill_strategy",
        lambda row: row["fill_strategy"],
    )

    by_booking_status = _group_requests(
        [
            row for row in rows
            if row["booking_status"]
        ],
        "booking_status",
        lambda row: row["booking_status"],
    )

    by_validation_status = _group_requests(
        [
            row for row in rows
            if row["validation_status"]
        ],
        "validation_status",
        lambda row: row["validation_status"],
    )

    return {
        **overall,
        "by_target": by_target,
        "by_mode": by_mode,
        "by_horizon": by_horizon,
        "by_game_count": by_game_count,
        "by_fill_strategy": by_fill_strategy,
        "by_requested_market": _market_request_groups(
            rows,
            "requested_markets",
        ),
        "by_selected_market": _market_request_groups(
            rows,
            "selected_markets",
        ),
        "by_booking_status": by_booking_status,
        "by_validation_status": by_validation_status,
        "failures": [
            {
                "category": key,
                "count": value,
            }
            for key, value in failures.most_common()
        ],
        "contract": {
            "request_fact": "one_builder_request",
            "performance_fact": "one_unique_generated_selection_set",
            "market_performance_scope": "build_contains_market",
            "share_codes_persisted": False,
        },
    }
