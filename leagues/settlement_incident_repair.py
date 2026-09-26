"""Atomic, fixed-scope repair coordinator for the September settlement incident.

Not imported by normal settlement, scheduling, Builder, or API paths.
"""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from sqlalchemy import select, text
from leagues.published_slip_repair import START_DATE, END_DATE

CONFIRM_TOKEN = "REPAIR_SETTLEMENT_INCIDENT_20260915_20260924"
INCIDENT_START_UTC = datetime(2026, 9, 15, tzinfo=timezone.utc)
INCIDENT_END_UTC = datetime(2026, 9, 25, tzinfo=timezone.utc)
EXPECTED_PRODUCTION_DATABASE = "betsightly_lik1"
EXPECTED_SCORE_SOURCE = "espn"
REVIEWED_SCOPE = {
    "published_scanned": 35,
    "published_legs": 157,
    "published_targets": 35,
    "published_status_changes": 29,
    "published_unresolved": 6,
    "builder_scanned": 14,
    "builder_legs": 148,
    "builder_targets": 14,
    "builder_status_changes": 11,
    "builder_unresolved": 5,
    "providers": ["espn", "espn"],
}

class RepairPreconditionError(RuntimeError): pass

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
def _iso(v): return v.isoformat() if hasattr(v, "isoformat") else v

def _as_utc(v):
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RepairPreconditionError("builder created_at is invalid") from exc
    if not isinstance(v, datetime):
        raise RepairPreconditionError("builder created_at is not a datetime")
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)

def _core_evidence(v):
    if not v: return None
    return {k: v.get(k) for k in ("provider", "provider_event_id", "home_score", "away_score", "score_90", "match_status")}
def _needs(leg):
    if leg["stored_outcome"] != leg["proposed_outcome"]:
        return True
    if leg["proposed_outcome"] != "pending":
        return _core_evidence(leg.get("stored_evidence")) != _core_evidence(
            leg.get("score_evidence")
        )
    return (
        bool(leg.get("stored_evidence"))
        or leg.get("stored_pending_reason") != leg.get("unresolved_reason")
    )

def _reports():
    from leagues.results_checker import reconcile_published_slips
    from leagues.builder_reconciliation import reconcile_builder_predictions
    return (reconcile_published_slips(start_date=START_DATE, end_date=END_DATE, dry_run=True),
            reconcile_builder_predictions())

def build_plan():
    """Fresh, read-only plan. Every target comes from current canonical reports."""
    pub, builder = _reports()
    pub_targets = [s for s in pub["slips"] if s["stored_status"] != s["proposed_status"] or any(_needs(l) for l in s["legs"])]
    builder_targets = [s for s in builder["predictions"] if s["stored_final_status"] != s["proposed_final_status"] or any(_needs(l) for l in s["legs"])]
    return {"published": pub, "builder": builder, "published_targets": pub_targets,
            "builder_targets": builder_targets, "dry_run": True,
            "start_date": START_DATE, "end_date": END_DATE}

def _load_rows(conn, pids, bids):
    from leagues.picks_db import PublishedSlip
    from leagues.builder_runs import builder_predictions

    p = {}
    if pids:
        published_stmt = (
            select(PublishedSlip.__table__)
            .where(PublishedSlip.id.in_(pids))
            .with_for_update()
        )
        p = {
            r["id"]: dict(r)
            for r in conn.execute(published_stmt).mappings()
        }

    b = {}
    if bids:
        builder_stmt = (
            select(builder_predictions)
            .where(builder_predictions.c.selection_fingerprint.in_(bids))
            .with_for_update()
        )
        b = {
            r["selection_fingerprint"]: dict(r)
            for r in conn.execute(builder_stmt).mappings()
        }
    return p, b

def _snapshot(row): return {k: _iso(v) for k, v in row.items()}
def _validate(plan, p_rows, b_rows):
    if len(p_rows) != len(plan["published_targets"]) or len(b_rows) != len(plan["builder_targets"]):
        raise RepairPreconditionError("a planned row no longer exists")
    for s in plan["published_targets"]:
        r=p_rows.get(s["slip_id"])
        if not r or (r["date"],r["category"],r["status"] or "pending") != (s["date"],s["category"],s["stored_status"]):
            raise RepairPreconditionError(f"published slip {s['slip_id']} changed after reconciliation")
        if not START_DATE <= r["date"] <= END_DATE:
            raise RepairPreconditionError("published slip outside scope")
        if _hash(r["picks"] or "") != s.get("stored_picks_hash"):
            raise RepairPreconditionError(
                f"published slip {s['slip_id']} picks changed after reconciliation"
            )
    for s in plan["builder_targets"]:
        r=b_rows.get(s["selection_fingerprint"])
        if not r or (r["final_status"] or "pending") != s["stored_final_status"]:
            raise RepairPreconditionError(f"builder prediction {s['selection_fingerprint']} changed after reconciliation")
        if len(json.loads(r["picks"] or "[]")) != len(s["legs"]):
            raise RepairPreconditionError("builder leg count changed")
        if _hash(r["picks"] or "") != s.get("stored_picks_hash"):
            raise RepairPreconditionError(
                f"builder prediction {s['selection_fingerprint']} picks changed after reconciliation"
            )
        created = _as_utc(r["created_at"])
        if _as_utc(s["created_at"]) != created:
            raise RepairPreconditionError("builder created_at changed")
        if not INCIDENT_START_UTC <= created < INCIDENT_END_UTC:
            raise RepairPreconditionError("builder row outside scope")
        for field in (
            "target_odds", "horizon", "generated_odds",
            "actual_sportybet_odds", "validation_status",
        ):
            if r.get(field) != s.get(field):
                raise RepairPreconditionError(f"builder {field} changed")

def _repaired_picks(raw, legs):
    picks=json.loads(raw or "[]")
    if len(picks)!=len(legs): raise RepairPreconditionError("leg count changed")
    for pick, leg in zip(picks, legs):
        pick["status"]=leg["proposed_outcome"]
        if leg["proposed_outcome"] == "pending":
            pick.pop("settlement_evidence", None)
            if leg.get("unresolved_reason"):
                pick["settlement_pending_reason"] = leg["unresolved_reason"]
            else:
                pick.pop("settlement_pending_reason", None)
        else:
            pick.pop("settlement_pending_reason", None)
            evidence = leg.get("score_evidence")
            _validate_final_evidence(evidence)
            pick["settlement_evidence"] = evidence
    return picks

def _builder_values(row, target):
    from leagues.picks_db import settled_accumulator_return
    picks=_repaired_picks(row["picks"], target["legs"]); status=target["proposed_final_status"]
    if status == "pending":
        return {"picks":json.dumps(picks),"final_status":"pending","all_win":None,"target_reached":None,"settled_at":None,"actual_settled_return":None,"sportybet_settled_return":None,"profit":None}
    returned,_=settled_accumulator_return({"status":status,"picks":picks,"total_odds":row["generated_odds"]})
    sport=None
    if (
        row.get("actual_sportybet_odds") is not None
        and str(row.get("validation_status") or "").upper() == "PASSED"
    ):
        sport=0.0 if status=="lost" else (1.0 if status=="void" else (float(row["actual_sportybet_odds"]) if not any(p["status"]=="void" for p in picks) else None))
    settled_at = (
        row.get("settled_at")
        if (row.get("final_status") or "pending") == status
        else datetime.now(timezone.utc)
    )
    return {"picks":json.dumps(picks),"final_status":status,"all_win":bool(picks) and all(p["status"]=="won" for p in picks),"target_reached":float(returned)>=float(row["target_odds"]),"settled_at":settled_at,"actual_settled_return":round(float(returned),6),"sportybet_settled_return":round(sport,6) if sport is not None else None,"profit":round(float(returned)-1,6)}

def _validate_final_evidence(evidence):
    if not isinstance(evidence, dict):
        raise RepairPreconditionError("final proposal is missing verified score evidence")
    if evidence.get("provider") != EXPECTED_SCORE_SOURCE:
        raise RepairPreconditionError("final evidence provider is not ESPN")
    if not str(evidence.get("provider_event_id") or "").strip():
        raise RepairPreconditionError("final evidence is missing provider event id")
    for key in ("home_score", "away_score"):
        value = evidence.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise RepairPreconditionError(f"invalid final evidence {key}")
    status = str(evidence.get("match_status") or "").upper()
    if "FINAL" not in status and "FULL_TIME" not in status:
        raise RepairPreconditionError("final evidence is not final")

def _scope_summary(plan):
    return {
        "published_scanned": plan["published"]["slips_scanned"],
        "published_legs": plan["published"]["legs_scanned"],
        "published_targets": len(plan["published_targets"]),
        "published_status_changes": sum(
            s["stored_status"] != s["proposed_status"]
            for s in plan["published"]["slips"]
        ),
        "published_unresolved": len(plan["published"]["unresolved_legs"]),
        "builder_scanned": plan["builder"]["predictions_scanned"],
        "builder_legs": plan["builder"]["legs_scanned"],
        "builder_targets": len(plan["builder_targets"]),
        "builder_status_changes": len(plan["builder"]["final_status_changes"]),
        "builder_unresolved": len(plan["builder"]["unresolved_builder_legs"]),
        "providers": [
            plan["published"]["score_source"],
            plan["builder"]["score_source"],
        ],
    }

def _stable_leg(leg):
    return {
        "index": leg.get("index"),
        "stored_outcome": leg.get("stored_outcome"),
        "proposed_outcome": leg.get("proposed_outcome"),
        "stored_pending_reason": leg.get("stored_pending_reason"),
        "unresolved_reason": leg.get("unresolved_reason"),
        "evidence": _core_evidence(leg.get("score_evidence")),
    }

def _plan_hash(plan):
    payload = {
        "scope": [START_DATE, END_DATE],
        "providers": [
            plan["published"]["score_source"],
            plan["builder"]["score_source"],
        ],
        "published": [
            {
                "slip_id": s["slip_id"],
                "date": s["date"],
                "category": s["category"],
                "stored_status": s["stored_status"],
                "proposed_status": s["proposed_status"],
                "stored_picks_hash": s.get("stored_picks_hash"),
                "legs": [_stable_leg(l) for l in s["legs"]],
            }
            for s in sorted(plan["published_targets"], key=lambda x: x["slip_id"])
        ],
        "builder": [
            {
                "selection_fingerprint": s["selection_fingerprint"],
                "created_at": s["created_at"],
                "target_odds": s.get("target_odds"),
                "horizon": s.get("horizon"),
                "generated_odds": s.get("generated_odds"),
                "actual_sportybet_odds": s.get("actual_sportybet_odds"),
                "validation_status": s.get("validation_status"),
                "stored_final_status": s["stored_final_status"],
                "proposed_final_status": s["proposed_final_status"],
                "stored_picks_hash": s.get("stored_picks_hash"),
                "legs": [_stable_leg(l) for l in s["legs"]],
            }
            for s in sorted(
                plan["builder_targets"],
                key=lambda x: x["selection_fingerprint"],
            )
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return _hash(raw)

def _assert_reviewed_scope(plan):
    actual = _scope_summary(plan)
    if actual != REVIEWED_SCOPE:
        raise RepairPreconditionError(
            f"repair population changed after review: {actual}"
        )

def _validate_database_scope(conn):
    if conn.dialect.name != "postgresql":
        return conn.dialect.name
    name = conn.execute(text("select current_database()")).scalar_one()
    if name != EXPECTED_PRODUCTION_DATABASE:
        raise RepairPreconditionError(
            f"refusing repair on unexpected database {name!r}"
        )
    read_only = str(
        conn.execute(text("show transaction_read_only")).scalar_one()
    ).lower()
    if read_only in {"on", "true", "1"}:
        raise RepairPreconditionError(
            "repair transaction is read-only; clear PGOPTIONS only for authorised apply"
        )
    return name

def _backup(path, p_rows, b_rows, plan_hash):
    path=Path(path); path.mkdir(parents=True,exist_ok=True)
    out=path/f"settlement_incident_pre_repair_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    payload={
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "published": [START_DATE, END_DATE],
            "builder_start_utc": INCIDENT_START_UTC.isoformat(),
            "builder_end_utc_exclusive": INCIDENT_END_UTC.isoformat(),
        },
        "plan_hash": plan_hash,
        "published_slips":[_snapshot(r) for r in p_rows.values()],
        "builder_predictions":[_snapshot(r) for r in b_rows.values()],
    }
    with out.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
    return str(out)

def _unresolved_ok(plan):
    legs = (
        list(plan["published"]["unresolved_legs"])
        + list(plan["builder"]["unresolved_builder_legs"])
    )
    return all(
        leg.get("proposed_outcome") == "pending"
        and bool(leg.get("unresolved_reason"))
        for leg in legs
    )

def run(*, apply=False, confirmation="", backup_dir="maintenance_backups", verify=False, expected_plan_hash=""):
    plan=build_plan()
    plan_hash = _plan_hash(plan)
    if verify:
        unresolved_ok = _unresolved_ok(plan)
        return {
            "verification_clean": (
                not plan["published_targets"]
                and not plan["builder_targets"]
                and unresolved_ok
            ),
            "published_remaining": len(plan["published_targets"]),
            "builder_remaining": len(plan["builder_targets"]),
            "unresolved_ok": unresolved_ok,
            "unresolved_published": len(plan["published"]["unresolved_legs"]),
            "unresolved_builder": len(plan["builder"]["unresolved_builder_legs"]),
            "plan_hash": plan_hash,
        }
    if not apply:
        published_status_changes = [
            {
                "slip_id": s["slip_id"],
                "date": s["date"],
                "category": s["category"],
                "before": s["stored_status"],
                "after": s["proposed_status"],
            }
            for s in plan["published"]["slips"]
            if s["stored_status"] != s["proposed_status"]
        ]
        return {
            "dry_run": True,
            "plan_hash": plan_hash,
            "reviewed_scope_match": _scope_summary(plan) == REVIEWED_SCOPE,
            "scope_summary": _scope_summary(plan),
            "published": {
                "rows_targeted": len(plan["published_targets"]),
                "legs_targeted": sum(
                    sum(_needs(l) for l in s["legs"])
                    for s in plan["published_targets"]
                ),
                "final_status_changes": published_status_changes,
                "likely_historical_false_voids": plan["published"][
                    "likely_historical_false_voids"
                ],
                "likely_incorrect_losses": plan["published"][
                    "likely_incorrect_losses"
                ],
                "unresolved_legs": plan["published"]["unresolved_legs"],
            },
            "builder": {
                "rows_targeted": len(plan["builder_targets"]),
                "legs_targeted": sum(
                    sum(_needs(l) for l in s["legs"])
                    for s in plan["builder_targets"]
                ),
                "final_status_changes": plan["builder"]["final_status_changes"],
                "unresolved_legs": plan["builder"]["unresolved_builder_legs"],
                "proposed_totals": {
                    x: sum(
                        s["proposed_final_status"] == x
                        for s in plan["builder"]["predictions"]
                    )
                    for x in ("won", "lost", "pending", "void")
                },
            },
            "evidence_providers": [
                plan["published"]["score_source"],
                plan["builder"]["score_source"],
            ],
        }
    if confirmation != CONFIRM_TOKEN:
        raise RepairPreconditionError("confirmation token did not match")
    if not expected_plan_hash:
        raise RepairPreconditionError("reviewed plan hash is required for apply")
    if expected_plan_hash != plan_hash:
        raise RepairPreconditionError(
            "repair plan changed after review; rerun dry-run"
        )
    from database import engine
    from leagues.picks_db import PublishedSlip
    from leagues.builder_runs import builder_predictions
    pids=[s["slip_id"] for s in plan["published_targets"]]; bids=[s["selection_fingerprint"] for s in plan["builder_targets"]]
    with engine.begin() as conn:
        database_name = _validate_database_scope(conn)
        if conn.dialect.name == "postgresql":
            _assert_reviewed_scope(plan)
        pr,br=_load_rows(conn,pids,bids)
        _validate(plan,pr,br)
        backup=_backup(backup_dir,pr,br,plan_hash)
        for s in plan["published_targets"]:
            r=pr[s["slip_id"]]
            picks=_repaired_picks(r["picks"],s["legs"])
            settled_at = (
                None
                if s["proposed_status"] == "pending"
                else (
                    r.get("settled_at")
                    if (r.get("status") or "pending") == s["proposed_status"]
                    else datetime.now(timezone.utc)
                )
            )
            result = conn.execute(
                PublishedSlip.__table__.update()
                .where(PublishedSlip.id==r["id"])
                .values(
                    picks=json.dumps(picks),
                    status=s["proposed_status"],
                    settled_at=settled_at,
                )
            )
            if result.rowcount != 1:
                raise RepairPreconditionError("published update rowcount mismatch")
        for s in plan["builder_targets"]:
            r=br[s["selection_fingerprint"]]
            result = conn.execute(
                builder_predictions.update()
                .where(
                    builder_predictions.c.selection_fingerprint
                    == r["selection_fingerprint"]
                )
                .values(**_builder_values(r,s))
            )
            if result.rowcount != 1:
                raise RepairPreconditionError("builder update rowcount mismatch")
    return {
        "dry_run":False,
        "transaction_status":"committed",
        "database": database_name,
        "plan_hash": plan_hash,
        "backup_path":backup,
        "published_rows_changed":len(pids),
        "builder_rows_changed":len(bids),
        "evidence_providers":[
            plan["published"]["score_source"],
            plan["builder"]["score_source"],
        ],
    }
