"""Read-only September 2026 reconciliation for immutable Builder predictions.

This is deliberately disconnected from normal Builder settlement.  It exists
solely to inspect the historical incident before any repair is authorised.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select


START_DATE = "2026-09-15"
END_DATE = "2026-09-24"


def _proposed_status(outcomes: list[str]) -> str:
    """The Builder final-status policy, calculated without persisting it."""
    if any(outcome == "lost" for outcome in outcomes):
        return "lost"
    if not outcomes or any(outcome == "pending" for outcome in outcomes):
        return "pending"
    if all(outcome == "void" for outcome in outcomes):
        return "void"
    return "won"


def _created_range() -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(START_DATE).replace(tzinfo=timezone.utc)
    # Half-open range includes every created_at instant on 24 September.
    end = (datetime.fromisoformat(END_DATE).replace(tzinfo=timezone.utc)
           + timedelta(days=1))
    return start, end


def _as_iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def reconcile_builder_predictions() -> dict[str, Any]:
    """Compare every Builder prediction in the fixed incident window.

    The function opens a plain database connection and executes only a SELECT.
    It never calls ``ensure_table``, settlement writers, Builder generation,
    booking, calibration, or ``builder_runs`` operations.
    """
    from leagues import builder_runs
    from leagues.picks_db import settled_accumulator_return
    from leagues.results_checker import (
        _collect_scores_for_picks,
        _lookup_settlement_score,
        _settlement_detail,
    )

    start, end = _created_range()
    with builder_runs.engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(
            select(builder_runs.builder_predictions).where(
                builder_runs.builder_predictions.c.created_at >= start,
                builder_runs.builder_predictions.c.created_at < end,
            ).order_by(builder_runs.builder_predictions.c.created_at.asc())
        ).mappings().all()]

    archived = []
    for row in rows:
        try:
            picks = json.loads(row.get("picks") or "[]")
            if not isinstance(picks, list):
                raise ValueError("picks payload is not a list")
            payload_error = None
        except (TypeError, ValueError) as exc:
            picks = []
            payload_error = type(exc).__name__
        archived.append({**row, "parsed_picks": picks, "payload_error": payload_error})

    score_picks = [
        json.loads(json.dumps(pick))
        for row in archived for pick in row["parsed_picks"]
    ]
    scores, source = _collect_scores_for_picks(score_picks)
    current = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "dry_run": True,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "predictions_scanned": 0,
        "legs_scanned": 0,
        "score_source": source,
        "predictions": [],
        "likely_false_builder_voids": [],
        "likely_incorrect_builder_losses": [],
        "unresolved_builder_legs": [],
        "final_status_changes": [],
    }

    for row in archived:
        legs = []
        outcomes = []
        proposed_picks = []
        if row["payload_error"]:
            # Malformed evidence is never extrapolated into a final result.
            legs.append({
                "index": None, "stored_outcome": None,
                "proposed_outcome": "pending", "score_evidence": None,
                "unresolved_reason": "MALFORMED_PICKS",
            })
            outcomes.append("pending")
        for index, original_pick in enumerate(row["parsed_picks"]):
            pick = json.loads(json.dumps(original_pick))
            match_date = str(pick.get("kickoff") or pick.get("commence_time") or
                             pick.get("date") or "")[:10]
            match = _lookup_settlement_score(
                scores, pick.get("home_team", ""), pick.get("away_team", ""),
                match_date,
            )
            proposed, detail = _settlement_detail(pick, match, current)
            stored = pick.get("status") or "pending"
            evidence = detail.get("settlement_evidence")
            unresolved_reason = detail.get("settlement_pending_reason")
            proposed_pick = json.loads(json.dumps(pick))
            proposed_pick["status"] = proposed
            if evidence:
                proposed_pick["settlement_evidence"] = evidence
                proposed_pick.pop("settlement_pending_reason", None)
            elif unresolved_reason:
                proposed_pick["settlement_pending_reason"] = unresolved_reason
                proposed_pick.pop("settlement_evidence", None)
            proposed_picks.append(proposed_pick)
            leg = {
                "index": index,
                "fixture": {
                    "home_team": pick.get("home_team"),
                    "away_team": pick.get("away_team"),
                    "date": match_date,
                },
                "market": pick.get("market") or pick.get("market_key"),
                "prediction": pick.get("prediction"),
                "stored_outcome": stored,
                "proposed_outcome": proposed,
                "stored_evidence": pick.get("settlement_evidence"),
                "score_evidence": evidence,
                "unresolved_reason": unresolved_reason,
            }
            legs.append(leg)
            outcomes.append(proposed)
            report["legs_scanned"] += 1
            if proposed == "pending":
                report["unresolved_builder_legs"].append({
                    "selection_fingerprint": row["selection_fingerprint"], **leg,
                })
            if stored == "void" and proposed in {"won", "lost"}:
                report["likely_false_builder_voids"].append({
                    "selection_fingerprint": row["selection_fingerprint"], **leg,
                })
            if stored == "lost" and proposed in {"won", "void"}:
                report["likely_incorrect_builder_losses"].append({
                    "selection_fingerprint": row["selection_fingerprint"], **leg,
                })

        proposed_status = _proposed_status(outcomes)
        if proposed_status == "pending":
            proposed_return = proposed_profit = proposed_all_win = proposed_target_reached = None
        else:
            proposed_return, _ = settled_accumulator_return({
                "status": proposed_status,
                "picks": proposed_picks,
                "total_odds": row.get("generated_odds"),
            })
            proposed_return = round(float(proposed_return), 6)
            proposed_profit = round(proposed_return - 1.0, 6)
            proposed_all_win = bool(outcomes) and all(outcome == "won" for outcome in outcomes)
            proposed_target_reached = proposed_return >= float(row["target_odds"])

        prediction = {
            "selection_fingerprint": row["selection_fingerprint"],
            "created_at": _as_iso(row.get("created_at")),
            "target_odds": row.get("target_odds"),
            "horizon": row.get("horizon"),
            "stored_final_status": row.get("final_status") or "pending",
            "proposed_final_status": proposed_status,
            "proposed_actual_settled_return": proposed_return,
            "proposed_profit": proposed_profit,
            "proposed_all_win": proposed_all_win,
            "proposed_target_reached": proposed_target_reached,
            "legs": legs,
        }
        report["predictions"].append(prediction)
        report["predictions_scanned"] += 1
        if prediction["stored_final_status"] == "void" and proposed_status in {"won", "lost"}:
            report["likely_false_builder_voids"].append({
                "selection_fingerprint": row["selection_fingerprint"],
                "level": "prediction",
                "stored_final_status": prediction["stored_final_status"],
                "proposed_final_status": proposed_status,
            })
        if prediction["stored_final_status"] == "lost" and proposed_status in {"won", "void"}:
            report["likely_incorrect_builder_losses"].append({
                "selection_fingerprint": row["selection_fingerprint"],
                "level": "prediction",
                "stored_final_status": prediction["stored_final_status"],
                "proposed_final_status": proposed_status,
            })
        if prediction["stored_final_status"] != proposed_status:
            report["final_status_changes"].append({
                "selection_fingerprint": row["selection_fingerprint"],
                "created_at": prediction["created_at"],
                "before": prediction["stored_final_status"],
                "after": proposed_status,
            })
    return report
