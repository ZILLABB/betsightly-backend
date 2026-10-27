"""Zero-cost, fail-closed NBA STAGING-only research automation triggers.

No private information or bookmaker observations are emitted to workflow logs.
The endpoints cannot publish, wager, generate codes, modify football, or
accept caller-provided fixtures. This script only validates the server receipt.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

HOST = "https://betsightly-nba-research-stage-20261025.onrender.com"
JOBS = {
    "forecast": (
        "/api/growth/internal/nba-research/forecast",
        "x-betsightly-nba-forecast-token",
        "NBA_STAGE_FORECAST_JOB_TOKEN",
    ),
    "market": (
        "/api/growth/internal/nba-research/markets/refresh",
        "x-betsightly-nba-market-token",
        "NBA_STAGE_MARKET_JOB_TOKEN",
    ),
}
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_BODY = 524_288


class PrivateStageFailure(RuntimeError):
    pass


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PrivateStageFailure("NBA_STAGE_REDIRECT_REJECTED")


def open_strict(request, *, timeout):
    return build_opener(RejectRedirect()).open(request, timeout=timeout)


def verified_receipt(kind: str, body: object) -> dict:
    if kind not in JOBS or not isinstance(body, dict):
        raise PrivateStageFailure("NBA_STAGE_INVALID_RECEIPT")
    if body.get("research_only") is not True or body.get("not_bookable") is not True:
        raise PrivateStageFailure("NBA_STAGE_ISOLATION_UNVERIFIED")

    status = body.get("status")
    if kind == "forecast":
        if status not in (
            "archived_before_tipoff",
            "no_new_eligible_forecasts",
            "no_upcoming_eligible_source_window",
        ):
            raise PrivateStageFailure("NBA_FORECAST_SOURCE_UNVERIFIED")
        if not isinstance(body.get("archive_digest"), str) or not SHA.fullmatch(
            body["archive_digest"]
        ):
            raise PrivateStageFailure("NBA_FORECAST_ARCHIVE_UNVERIFIED")
        counts = body.get("new_forecasts")
        if not isinstance(counts, dict) or not all(
            k in ("moneyline", "original_score", "advanced_score") and
            type(v) is int and 0 <= v <= 500 for k, v in counts.items()
        ):
            raise PrivateStageFailure("NBA_FORECAST_MODEL_COUNTS_INVALID")
        if body.get("advanced_model_recomputed") is True:
            raise PrivateStageFailure("NBA_FORECAST_ADVANCED_MODEL_UNEXPECTED")
        return {"kind": kind, "status": status, "new_forecasts": sum(counts.values())}

    if status not in ("saved", "already_saved"):
        raise PrivateStageFailure("NBA_MARKET_SOURCE_UNVERIFIED")
    if body.get("archive_unchanged") is not True:
        raise PrivateStageFailure("NBA_MARKET_ARCHIVE_MUTATED")
    if not isinstance(body.get("digest"), str) or not SHA.fullmatch(body["digest"]):
        raise PrivateStageFailure("NBA_MARKET_RECEIPT_UNVERIFIED")
    if body.get("calibrated_betting_edge") is not False or (
        body.get("public_publishing_enabled") is not False
    ):
        raise PrivateStageFailure("NBA_MARKET_BETTING_OUTPUT_UNEXPECTED")
    matches = body.get("fixture_matches")
    if type(matches) is not int or not 0 <= matches <= 500:
        raise PrivateStageFailure("NBA_MARKET_FIXTURE_COUNT_INVALID")
    return {"kind": kind, "status": status, "fixture_matches": matches}


def invoke(kind: str, token: str, *, opener=open_strict, sleeper=time.sleep) -> dict:
    if kind not in JOBS:
        raise PrivateStageFailure("NBA_STAGE_UNKNOWN_JOB")
    if not isinstance(token, str) or len(token) < 48 or "\n" in token or "\r" in token:
        raise PrivateStageFailure("NBA_STAGE_MACHINE_TOKEN_MISSING")
    path, header, _ = JOBS[kind]
    request = Request(
        HOST + path,
        method="POST",
        headers={
            "Accept": "application/json",
            header: token,
            "User-Agent": "BetSightly-NBA-Private-GHA/1",
        },
        data=b"",
    )
    for attempt in range(2):
        try:
            with opener(request, timeout=170) as response:
                if response.status != 200:
                    raise PrivateStageFailure("NBA_STAGE_HTTP_" + str(response.status))
                raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise PrivateStageFailure("NBA_STAGE_OVERSIZED_RECEIPT")
            return verified_receipt(kind, json.loads(raw))
        except HTTPError as exc:
            if attempt == 0 and (exc.code == 429 or exc.code >= 500):
                sleeper(18)
                continue
            raise PrivateStageFailure("NBA_STAGE_HTTP_" + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            if attempt == 0:
                sleeper(18)
                continue
            raise PrivateStageFailure("NBA_STAGE_NETWORK_UNAVAILABLE") from None
        except (ValueError, UnicodeDecodeError):
            raise PrivateStageFailure("NBA_STAGE_NON_JSON_RECEIPT") from None
    raise PrivateStageFailure("NBA_STAGE_RETRY_EXHAUSTED")


def main(args: list[str]) -> int:
    if len(args) != 1 or args[0] not in JOBS:
        print("::error::Use forecast or market", file=sys.stderr)
        return 2
    kind = args[0]
    secret_name = JOBS[kind][2]
    try:
        result = invoke(kind, os.getenv(secret_name, ""))
    except PrivateStageFailure as exc:
        print("::error::" + str(exc), file=sys.stderr)
        return 1
    print("NBA private staging: " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
