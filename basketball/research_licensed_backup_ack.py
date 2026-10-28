"""Validate actual private offsite hash readback against unchanged source rows.

Acknowledgement is NOT a restore. The new licensed table backup is separate
from the NBA full-V2 envelope and cannot imply training/public approval.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import re
from sqlalchemy import text
from basketball.research_licensed_backup import build_history_recovery
from database import SessionLocal

HEX = re.compile(r"^[0-9a-f]{64}$")

def verify_and_record_history_ack(body, *, session_factory=None,
                                  now=None, exporter=build_history_recovery):
    if not isinstance(body,dict) or set(body)!={
        "verified","store","tables_sha256","blob_sha256",
        "export_created_at","counts"
    } or body["verified"] is not True or (
        body["store"] != "private_vercel_blob_licensed_history_v1"
    ) or not all(isinstance(body[k],str) and HEX.fullmatch(body[k])
                 for k in ("tables_sha256","blob_sha256")):
        raise ValueError("BASKETBALL_HISTORY_ACK_BAD_RECEIPT")
    now = now or datetime.now(timezone.utc)
    try:
        exported_at = datetime.fromisoformat(
            body["export_created_at"].replace("Z","+00:00")
        )
    except (ValueError,AttributeError) as exc:
        raise ValueError("BASKETBALL_HISTORY_ACK_TIME_INVALID") from exc
    if (exported_at.tzinfo is None or exported_at.utcoffset() is None or
        not timedelta(0) <= now - exported_at <= timedelta(minutes=15)):
        raise ValueError("BASKETBALL_HISTORY_ACK_STALE")
    observed = exporter()
    if (observed["tables_sha256"] != body["tables_sha256"] or
        observed["counts"] != body["counts"]):
        raise ValueError("BASKETBALL_HISTORY_ACK_SOURCE_CHANGED")
    counts = observed["counts"]
    with (session_factory or SessionLocal)() as db:
        db.execute(text("""
            INSERT INTO nba_research.basketball_history_backup_receipts
            (tables_sha256,blob_sha256,rights_count,imports_count,
             games_count,probes_count,source_changed_after_export)
            VALUES (:tables,:blob,:rights,:imports,:games,:probes,false)
        """), {
            "tables":body["tables_sha256"],"blob":body["blob_sha256"],
            "rights":counts["rights"],"imports":counts["imports"],
            "games":counts["games"],"probes":counts["probes"]
        })
        db.commit()
    return {"status":"verified_licensed_history_private_blob_readback",
            "research_only":True,"not_bookable":True,
            "counts":counts,"tables_sha256":observed["tables_sha256"]}

def history_backup_health(*, session_factory=None):
    """Verified private-Blob ACK is not independent restore or model readiness."""
    with (session_factory or SessionLocal)() as db:
        row=db.execute(text("""
            SELECT id,tables_sha256,verified_at,rights_count,
                   imports_count,games_count,probes_count
            FROM nba_research.basketball_history_backup_receipts
            ORDER BY id DESC LIMIT 1
        """)).mappings().first()
    if row is None:
        return {"status":"never_verified_offsite",
                "last_verified_at":None,"rights_count":0,
                "imports_count":0,"games_count":0,"probes_count":0,
                "independent_postgres_restore_verified":False}
    return {"status":"historical_offsite_blob_verified",
            "last_verified_at":row["verified_at"].isoformat(),
            "rights_count":row["rights_count"],
            "imports_count":row["imports_count"],
            "games_count":row["games_count"],
            "probes_count":row["probes_count"],
            "independent_postgres_restore_verified":False}
