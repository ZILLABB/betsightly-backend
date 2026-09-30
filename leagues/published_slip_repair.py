"""Guarded, one-off repair support for the September 2026 slip incident.

This module is intentionally not imported by normal settlement or any API
route.  ``scripts/repair_published_slips_incident.py`` is its only production
entry point.  The fixed scope and confirmation token make it unsuitable as a
generic historical mutation tool.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


START_DATE = "2026-09-15"
END_DATE = "2026-09-24"
CONFIRM_TOKEN = "REPAIR_PUBLISHED_SLIPS_20260915_20260924"


class RepairPreconditionError(RuntimeError):
    """The archive changed after review; no partial repair is safe."""


def _is_final(outcome: str | None) -> bool:
    return outcome in {"won", "lost", "void"}


def build_repair_plan() -> dict[str, Any]:
    """Create a fresh, read-only repair plan using canonical reconciliation."""
    from leagues.results_checker import reconcile_published_slips

    reconciliation = reconcile_published_slips(
        start_date=START_DATE, end_date=END_DATE, dry_run=True,
    )
    targets = []
    newly_valid_observations = 0
    for slip in reconciliation["slips"]:
        changed_legs = [
            leg for leg in slip["legs"]
            if (leg["stored_outcome"] != leg["proposed_outcome"])
        ]
        if not changed_legs and slip["stored_status"] == slip["proposed_status"]:
            continue
        for leg in changed_legs:
            # A previous void never contributed a usable win/loss observation
            # to calibration either, so count it alongside pending records.
            if (leg["stored_outcome"] not in {"won", "lost"}
                    and leg["proposed_outcome"] in {"won", "lost"}):
                newly_valid_observations += 1
        targets.append({
            "slip_id": slip["slip_id"], "date": slip["date"],
            "category": slip["category"],
            "stored_status": slip["stored_status"],
            "proposed_status": slip["proposed_status"],
            "legs": slip["legs"],
        })
    return {
        "dry_run": True,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "reconciliation": reconciliation,
        "targets": targets,
        "rows_to_change": len(targets),
        "legs_to_change": sum(
            sum(leg["stored_outcome"] != leg["proposed_outcome"]
                for leg in target["legs"])
            for target in targets
        ),
        "forecast_observations_newly_valid": newly_valid_observations,
    }


def _row_snapshot(row) -> dict[str, Any]:
    """Serializable pre-repair evidence, including immutable archive fields."""
    def iso(value):
        return value.isoformat() if value is not None else None

    return {
        "id": row.id,
        "date": row.date,
        "category": row.category,
        "picks": json.loads(row.picks or "[]"),
        "status": row.status,
        "settled_at": iso(row.settled_at),
        "presentation": row.presentation,
        "total_odds": row.total_odds,
        "hit_probability": row.hit_probability,
        "policy_version": row.policy_version,
        "selection_fingerprint": row.selection_fingerprint,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _write_backup(rows: list, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"published_slips_pre_repair_{timestamp}.json"
    path.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"start_date": START_DATE, "end_date": END_DATE},
        "rows": [_row_snapshot(row) for row in rows],
    }, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _apply_target(row, target: dict[str, Any]) -> int:
    """Apply one already-validated report row inside the caller transaction."""
    picks = json.loads(row.picks or "[]")
    if len(picks) != len(target["legs"]):
        raise RepairPreconditionError(
            f"slip {row.id} leg count changed after reconciliation"
        )
    legs_changed = 0
    for pick, leg in zip(picks, target["legs"]):
        proposed = leg["proposed_outcome"]
        if pick.get("status") != proposed:
            legs_changed += 1
        pick["status"] = proposed
        if proposed == "pending":
            # A historical final is not evidence when the current matcher
            # cannot verify this exact fixture.  Preserve the pending reason,
            # never manufacture a loss/void, and remove stale final evidence.
            pick.pop("settlement_evidence", None)
            if leg.get("unresolved_reason"):
                pick["settlement_pending_reason"] = leg["unresolved_reason"]
            else:
                pick.pop("settlement_pending_reason", None)
        else:
            pick.pop("settlement_pending_reason", None)
            evidence = leg.get("score_evidence")
            if not evidence:
                raise RepairPreconditionError(
                    f"slip {row.id} has final proposal without verified score evidence"
                )
            pick["settlement_evidence"] = evidence

    row.picks = json.dumps(picks)
    row.status = target["proposed_status"]
    row.settled_at = (datetime.now(timezone.utc)
                      if _is_final(target["proposed_status"]) else None)
    return legs_changed


def apply_repair_plan(plan: dict[str, Any], *, confirmation: str,
                      backup_dir: str | Path = "maintenance_backups") -> dict[str, Any]:
    """Atomically apply a reviewed plan after all archive preconditions hold."""
    if confirmation != CONFIRM_TOKEN:
        raise RepairPreconditionError("confirmation token did not match")
    if plan.get("start_date") != START_DATE or plan.get("end_date") != END_DATE:
        raise RepairPreconditionError("repair plan has an invalid date scope")

    from database import SessionLocal
    from leagues.picks_db import PublishedSlip

    targets = plan.get("targets") or []
    target_ids = [target["slip_id"] for target in targets]
    if len(target_ids) != len(set(target_ids)):
        raise RepairPreconditionError("repair plan has duplicate slip IDs")

    db = SessionLocal()
    try:
        with db.begin():
            rows = (
                db.query(PublishedSlip)
                .filter(PublishedSlip.id.in_(target_ids))
                .order_by(PublishedSlip.id.asc())
                .all() if target_ids else []
            )
            by_id = {row.id: row for row in rows}
            if set(by_id) != set(target_ids):
                raise RepairPreconditionError("one or more planned slips no longer exist")

            # Check every target before the first assignment.  Any concurrent
            # status/category/date change aborts the entire transaction.
            ordered_rows = []
            for target in targets:
                row = by_id[target["slip_id"]]
                observed = (row.id, row.date, row.category, row.status or "pending")
                expected = (target["slip_id"], target["date"],
                            target["category"], target["stored_status"])
                if observed != expected:
                    raise RepairPreconditionError(
                        f"slip {row.id} changed after reconciliation: "
                        f"expected {expected}, found {observed}"
                    )
                if not (START_DATE <= row.date <= END_DATE):
                    raise RepairPreconditionError(f"slip {row.id} is outside repair scope")
                ordered_rows.append(row)

            backup_path = _write_backup(ordered_rows, Path(backup_dir))
            legs_changed = 0
            status_changes = []
            for row, target in zip(ordered_rows, targets):
                legs_changed += _apply_target(row, target)
                status_changes.append({
                    "slip_id": row.id, "date": row.date,
                    "category": row.category,
                    "before": target["stored_status"],
                    "after": target["proposed_status"],
                })
        # Context manager committed successfully at this point.
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    reconciliation = plan["reconciliation"]
    return {
        "dry_run": False,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "rows_changed": len(targets),
        "legs_changed": legs_changed,
        "status_changes": status_changes,
        "unresolved_legs": reconciliation["unresolved_legs"],
        "evidence_source": reconciliation["score_source"],
        "backup_file": str(backup_path),
        "forecast_observations_newly_valid": plan[
            "forecast_observations_newly_valid"
        ],
    }


def run_repair(*, apply: bool = False, confirmation: str | None = None,
               backup_dir: str | Path = "maintenance_backups") -> dict[str, Any]:
    """Generate the plan, or execute it only with explicit incident approval."""
    plan = build_repair_plan()
    if not apply:
        return {
            "dry_run": True,
            "rows_to_change": plan["rows_to_change"],
            "legs_to_change": plan["legs_to_change"],
            "forecast_observations_newly_valid": plan[
                "forecast_observations_newly_valid"
            ],
            "reconciliation": plan["reconciliation"],
        }
    return apply_repair_plan(plan, confirmation=confirmation or "",
                             backup_dir=backup_dir)
