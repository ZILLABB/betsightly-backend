"""GitHub-signed NBA research migration probe/restore. Never logs secrets.

Unlike ordinary NBA research jobs, this workflow cannot choose a target,
backup file, fixture, query or SQL command. The staging service owns both
the source and the destination connection details in its private env.
"""
from __future__ import annotations

import json
import sys
from urllib.request import Request
from urllib.error import HTTPError, URLError

from scripts.nba_stage_oidc_ping import (
    JobFailure, github_identity, read_json, strict_open,
)

MIGRATION_ENDPOINT = (
    "https://betsightly-nba-research-stage-20261025.onrender.com"
    "/api/growth/internal/nba-research/github-oidc-migration"
)


def invoke(mode: str, *, identity_provider=github_identity, opener=strict_open):
    if mode not in ("probe", "restore", "compare", "history"):
        raise JobFailure("NBA_MIGRATION_MODE_REFUSED")
    bearer = identity_provider()
    request = Request(
        MIGRATION_ENDPOINT,
        method="POST", data=json.dumps({"mode": mode}).encode("utf-8"),
        headers={"Authorization": "Bearer " + bearer,
                 "Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    try:
        result = read_json(request, opener=opener, timeout=180)
    except HTTPError as exc:
        raise JobFailure("NBA_MIGRATION_HTTP_" + str(exc.code)) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise JobFailure("NBA_MIGRATION_TRANSPORT_UNAVAILABLE") from None
    expected_status = ("target_empty" if mode == "probe"
                       else "audit_history_mirrored" if mode == "history"
                       else "restored_and_verified")
    status = result.get("status")
    if mode == "compare":
        # After an independently verified cutover the target may have
        # legitimate newer observations. Never mistake this for equality.
        if status == "source_target_prefix_verified":
            source_n = result.get("original_source_market_receipts")
            appended = result.get("new_target_market_receipts")
            total = result.get("market_receipt_count")
            valid_status = (type(source_n) is int and source_n >= 0
                            and type(appended) is int and appended > 0
                            and type(total) is int
                            and total == source_n + appended)
        else:
            valid_status = status == "source_target_identical"
        digest = result.get("archive_sha256")
        valid_status = (valid_status and isinstance(digest, str)
                        and len(digest) == 64
                        and all(c in "0123456789abcdef" for c in digest))
    else:
        valid_status = status == expected_status
    if (result.get("job") != "migration" or
        result.get("research_only") is not True or
        result.get("not_bookable") is not True or
        result.get("source_unchanged") is not True or
        not valid_status):
        raise JobFailure("NBA_MIGRATION_RECEIPT_INVALID")
    return {
        "status": result["status"], "job": "migration",
        "source_unchanged": True,
        "target_schema": result.get("schema", "nba_research"),
        "archive_digest": result.get("archive_sha256") if mode in ("restore", "compare") else None,
        "market_receipt_count": result.get("market_receipt_count") if mode in ("restore", "compare") else None,
        "original_source_market_receipts": result.get("original_source_market_receipts") if mode == "compare" else None,
        "new_target_market_receipts": result.get("new_target_market_receipts") if mode == "compare" else None,
        "audit_rows_verified": result.get("rows_verified") if mode == "history" else None,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("probe", "restore", "compare", "history"):
        print("::error::Private NBA migration requires probe, compare, history or restore", file=sys.stderr)
        raise SystemExit(2)
    try:
        result = invoke(sys.argv[1])
    except JobFailure as exc:
        print("::error::" + str(exc), file=sys.stderr)
        raise SystemExit(1)
    print("Verified NBA private migration result: " + json.dumps(result, sort_keys=True))
