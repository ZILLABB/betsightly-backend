"""Evidence-only acknowledgement for V2 off-provider NBA recovery.

Never changes which database is primary, publishes a tip, or permits restoring
over a populated source. The Vercel worker must first GET its private blob
and compare the complete raw-file SHA256 before calling this function.
"""
from __future__ import annotations

import re
from basketball.research_full_recovery import build_full_recovery

HEX = re.compile(r"^[0-9a-f]{64}$")


def verify_v2_backup_ack(body, *, recovery_loader=build_full_recovery):
    if not isinstance(body, dict) or set(body) != {
        "verified", "store", "archive_digest", "blob_sha256",
        "market_receipt_count", "job_receipt_count", "last_job_id"
    } or body["verified"] is not True or body["store"] != "private_vercel_blob_v2":
        raise ValueError("NBA_RECOVERY_ACK_FORMAT_INVALID")
    for key in ("archive_digest", "blob_sha256"):
        if not isinstance(body[key], str) or HEX.fullmatch(body[key]) is None:
            raise ValueError("NBA_RECOVERY_ACK_DIGEST_INVALID")
    for key in ("market_receipt_count", "job_receipt_count", "last_job_id"):
        if type(body[key]) is not int or body[key] < 0:
            raise ValueError("NBA_RECOVERY_ACK_COUNTER_INVALID")
    current = recovery_loader()
    jobs = current["job_receipts"]
    existing_last = jobs[-1]["id"] if jobs else 0
    if (current["portable_backup_v1"]["archive_digest"] != body["archive_digest"]
        or current["portable_backup_v1"]["market_receipt_count"] != body["market_receipt_count"]
        or len(jobs) != body["job_receipt_count"]
        or existing_last != body["last_job_id"]):
        raise ValueError("NBA_RECOVERY_ACK_STALE_CURRENT_SOURCE")
    return {
        "status": "verified_full_private_blob_readback",
        "archive_digest": body["archive_digest"],
        "market_receipt_count": body["market_receipt_count"],
        "job_receipt_count": body["job_receipt_count"],
        "last_job_id": body["last_job_id"],
        "research_only": True,
        "not_bookable": True,
        "offsite_readback_attested_by_private_worker": True,
    }
