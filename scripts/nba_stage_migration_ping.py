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
    if mode not in ("probe", "restore", "compare"):
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
    if (result.get("job") != "migration" or
        result.get("research_only") is not True or
        result.get("not_bookable") is not True or
        result.get("source_unchanged") is not True or
        result.get("status") != ("target_empty" if mode == "probe"
                                 else "source_target_identical" if mode == "compare"
                                 else "restored_and_verified")):
        raise JobFailure("NBA_MIGRATION_RECEIPT_INVALID")
    return {
        "status": result["status"], "job": "migration",
        "source_unchanged": True,
        "target_schema": result.get("schema", "nba_research"),
        "archive_digest": result.get("archive_sha256") if mode in ("restore", "compare") else None,
        "market_receipt_count": result.get("market_receipt_count") if mode in ("restore", "compare") else None,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("probe", "restore", "compare"):
        print("::error::Private NBA migration requires probe, compare or restore", file=sys.stderr)
        raise SystemExit(2)
    try:
        result = invoke(sys.argv[1])
    except JobFailure as exc:
        print("::error::" + str(exc), file=sys.stderr)
        raise SystemExit(1)
    print("Verified NBA private migration result: " + json.dumps(result, sort_keys=True))
