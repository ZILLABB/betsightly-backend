"""Atomic, fixed-scope repair coordinator for the September settlement incident.

Not imported by normal settlement, scheduling, Builder, or API paths.
"""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from sqlalchemy import select
from leagues.published_slip_repair import START_DATE, END_DATE

CONFIRM_TOKEN = "REPAIR_SETTLEMENT_INCIDENT_20260915_20260924"

class RepairPreconditionError(RuntimeError): pass

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
def _iso(v): return v.isoformat() if hasattr(v, "isoformat") else v
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
        created=_iso(r["created_at"]) or ""
        if not START_DATE <= created[:10] <= END_DATE:
            raise RepairPreconditionError("builder row outside scope")

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
            if not evidence:
                raise RepairPreconditionError(
                    "final proposal is missing verified score evidence"
                )
            pick["settlement_evidence"] = evidence
    return picks

def _builder_values(row, target):
    from leagues.picks_db import settled_accumulator_return
    picks=_repaired_picks(row["picks"], target["legs"]); status=target["proposed_final_status"]
    if status == "pending":
        return {"picks":json.dumps(picks),"final_status":"pending","all_win":None,"target_reached":None,"settled_at":None,"actual_settled_return":None,"sportybet_settled_return":None,"profit":None}
    returned,_=settled_accumulator_return({"status":status,"picks":picks,"total_odds":row["generated_odds"]})
    sport=None
    if row.get("actual_sportybet_odds") is not None:
        sport=0.0 if status=="lost" else (1.0 if status=="void" else (float(row["actual_sportybet_odds"]) if not any(p["status"]=="void" for p in picks) else None))
    return {"picks":json.dumps(picks),"final_status":status,"all_win":bool(picks) and all(p["status"]=="won" for p in picks),"target_reached":float(returned)>=float(row["target_odds"]),"settled_at":datetime.now(timezone.utc),"actual_settled_return":round(float(returned),6),"sportybet_settled_return":round(sport,6) if sport is not None else None,"profit":round(float(returned)-1,6)}

def _backup(path, p_rows, b_rows):
    path=Path(path); path.mkdir(parents=True,exist_ok=True)
    out=path/f"settlement_incident_pre_repair_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps({"scope":[START_DATE,END_DATE],"published_slips":[_snapshot(r) for r in p_rows.values()],"builder_predictions":[_snapshot(r) for r in b_rows.values()]},indent=2,default=str),encoding="utf-8")
    return str(out)

def run(*, apply=False, confirmation="", backup_dir="maintenance_backups", verify=False):
    plan=build_plan()
    if verify:
        unresolved_ok=all(s["proposed_status"]=="pending" for s in plan["published"]["slips"] if any(l["proposed_outcome"]=="pending" for l in s["legs"])) and all(s["proposed_final_status"]=="pending" for s in plan["builder"]["predictions"] if any(l["proposed_outcome"]=="pending" for l in s["legs"]))
        return {"verification_clean":not plan["published_targets"] and not plan["builder_targets"] and unresolved_ok,"published_remaining":len(plan["published_targets"]),"builder_remaining":len(plan["builder_targets"]),"unresolved_ok":unresolved_ok}
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
    if confirmation != CONFIRM_TOKEN: raise RepairPreconditionError("confirmation token did not match")
    from database import engine
    from leagues.picks_db import PublishedSlip
    from leagues.builder_runs import builder_predictions
    pids=[s["slip_id"] for s in plan["published_targets"]]; bids=[s["selection_fingerprint"] for s in plan["builder_targets"]]
    with engine.begin() as conn:
        pr,br=_load_rows(conn,pids,bids); _validate(plan,pr,br); backup=_backup(backup_dir,pr,br)
        for s in plan["published_targets"]:
            r=pr[s["slip_id"]]; picks=_repaired_picks(r["picks"],s["legs"]); conn.execute(PublishedSlip.__table__.update().where(PublishedSlip.id==r["id"]).values(picks=json.dumps(picks),status=s["proposed_status"],settled_at=datetime.now(timezone.utc) if s["proposed_status"]!="pending" else None))
        for s in plan["builder_targets"]:
            r=br[s["selection_fingerprint"]]; conn.execute(builder_predictions.update().where(builder_predictions.c.selection_fingerprint==r["selection_fingerprint"]).values(**_builder_values(r,s)))
    return {"dry_run":False,"transaction_status":"committed","backup_path":backup,"published_rows_changed":len(pids),"builder_rows_changed":len(bids),"evidence_providers":[plan["published"]["score_source"],plan["builder"]["score_source"]]}
