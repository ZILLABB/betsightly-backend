"""Fail-closed remote trigger for isolated, research-only NBA scoreboard settlement.

Invokes one fixed protected staging URL. No general URL, football database,
production credentials, bookmaker code creation, or forecast modifications.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

STAGING_URL = (
    "https://betsightly-nba-research-stage-20261025.onrender.com"
    "/api/growth/internal/nba-research/settle"
)
ALLOWED = {"idle", "no_new_verified_finals", "settled_and_verified"}
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\\Z")


class VerificationFailure(RuntimeError):
    """Non-sensitive operational failure: never dump raw upstream responses."""


def _validate(out: object) -> dict:
    if not isinstance(out, dict):
        raise VerificationFailure("NBA_RESULT_NOT_AN_OBJECT")
    if out.get("status") not in ALLOWED:
        raise VerificationFailure("NBA_UNCONFIRMED_RESULT_STATUS")
    if out.get("research_only") is not True or out.get("not_bookable") is not True:
        raise VerificationFailure("NBA_RESEARCH_ISOLATION_NOT_CONFIRMED")
    if out.get("failed_dates"):
        raise VerificationFailure("NBA_PROVIDER_DATES_UNVERIFIED")
    if out.get("provider_status", "idle") not in ("idle", "ok"):
        raise VerificationFailure("NBA_PROVIDER_VERIFICATION_DEGRADED")
    digest = out.get("archive_digest")
    if not isinstance(digest, str) or not HEX_SHA256.fullmatch(digest):
        raise VerificationFailure("NBA_DATABASE_READBACK_DIGEST_ABSENT")
    new_finals = out.get("new_finals")
    if type(new_finals) is not int or not 0 <= new_finals <= 500:
        raise VerificationFailure("NBA_FINAL_COUNT_INVALID")
    counts = out.get("new_settlements")
    if not isinstance(counts, dict) or set(counts) != {
        "moneyline", "original_score", "advanced_score"
    } or any(type(n) is not int or not 0 <= n <= 500 for n in counts.values()):
        raise VerificationFailure("NBA_MODEL_SETTLEMENT_COUNTS_INVALID")
    return {
        "status": out["status"],
        "new_finals": new_finals,
        "new_model_grades": sum(counts.values()),
    }


def invoke(token: str, *, opener=urlopen, sleeper=time.sleep) -> dict:
    """Retry one transient provider/transport error; never retry bad evidence."""
    if not isinstance(token, str) or len(token) < 32 or "\\n" in token or "\\r" in token:
        raise VerificationFailure("NBA_SETTLEMENT_MACHINE_TOKEN_NOT_CONFIGURED")
    request = Request(STAGING_URL, method="POST", headers={
        "Accept": "application/json",
        "X-Betsightly-NBA-Settle-Token": token,
        "User-Agent": "BetSightly-NBA-Private-Settlement-GHA/1",
    }, data=b"")
    for attempt in range(2):
        try:
            with opener(request, timeout=165) as response:
                if response.status != 200:
                    raise VerificationFailure("NBA_SETTLEMENT_HTTP_" + str(response.status))
                raw = response.read(16_385)
            if len(raw) > 16_384:
                raise VerificationFailure("NBA_RESULT_EXCEEDS_SAFE_SIZE")
            return _validate(json.loads(raw))
        except HTTPError as exc:
            if attempt == 0 and (exc.code == 429 or exc.code >= 500):
                sleeper(18)
                continue
            raise VerificationFailure("NBA_SETTLEMENT_HTTP_" + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            if attempt == 0:
                sleeper(18)
                continue
            raise VerificationFailure("NBA_SETTLEMENT_TRANSPORT_UNAVAILABLE") from None
        except (ValueError, UnicodeDecodeError):
            raise VerificationFailure("NBA_INVALID_SETTLEMENT_RESPONSE") from None
    raise VerificationFailure("NBA_SETTLEMENT_RETRIES_EXHAUSTED")


def main() -> int:
    try:
        result = invoke(os.getenv("NBA_STAGE_SETTLEMENT_JOB_TOKEN", ""))
    except VerificationFailure as exc:
        print("::error::" + str(exc), file=sys.stderr)
        return 1
    print("NBA private staging settlement: " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
