"""Secretless NBA staging cron trigger with GitHub-issued short-lived identity.

Requires GitHub Actions permissions: id-token: write and runs only from
signed exact workflow/ref. Does not store or print bearer secrets/JWTs.
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError

AUDIENCE = "betsightly-nba-stage-scheduler-v1"
ENDPOINT = ("https://betsightly-nba-research-stage-20261025.onrender.com"
            "/api/growth/internal/nba-research/github-oidc")
JOBS = frozenset(("settlement", "forecast", "market"))
MAX_RESPONSE = 100_000


class JobFailure(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise JobFailure("NBA_OIDC_REDIRECT_REJECTED")


def strict_open(request: Request, *, timeout: int):
    return build_opener(NoRedirect()).open(request, timeout=timeout)


def read_json(request, *, opener=strict_open, timeout=20):
    with opener(request, timeout=timeout) as response:
        if response.status != 200:
            raise JobFailure("NBA_OIDC_UNEXPECTED_HTTP")
        body = response.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise JobFailure("NBA_OIDC_OVERSIZED_RESPONSE")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise JobFailure("NBA_OIDC_NON_OBJECT")
    return value


def github_identity(*, environ=os.environ, opener=strict_open) -> str:
    url = environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    token = environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or
        not parsed.hostname.endswith(".actions.githubusercontent.com") or
        parsed.username or parsed.password or parsed.fragment or not parsed.path or
        parsed.port not in (None, 443)):
        raise JobFailure("NBA_GITHUB_OIDC_URL_DENIED")
    if len(token) < 25 or any(c in token for c in "\r\n"):
        raise JobFailure("NBA_GITHUB_IDENTITY_UNAVAILABLE")
    separator = "&" if parsed.query else "?"
    request = Request(url + separator + urlencode({"audience": AUDIENCE}), headers={
        "Authorization": "bearer " + token,
        "Accept": "application/json",
    })
    answer = read_json(request, opener=opener, timeout=20)
    jwt = answer.get("value")
    if not isinstance(jwt, str) or not 80 <= len(jwt) <= 10_000:
        raise JobFailure("NBA_GITHUB_IDENTITY_INVALID")
    return jwt


def validate_receipt(job: str, data: dict) -> dict:
    if data.get("job") != job or data.get("research_only") is not True or (
        data.get("not_bookable") is not True
    ):
        raise JobFailure("NBA_STAGE_ISOLATION_UNVERIFIED")
    allowed = {
        "settlement": ("settled_and_verified", "idle", "no_new_verified_finals"),
        "forecast": ("archived_before_tipoff", "no_new_eligible_forecasts",
                     "no_upcoming_eligible_source_window"),
        "market": ("saved", "already_saved"),
    }
    if job not in JOBS or data.get("status") not in allowed[job]:
        raise JobFailure("NBA_STAGE_OPERATION_UNVERIFIED")
    if job == "settlement" and data.get("failed_dates"):
        raise JobFailure("NBA_STAGE_PROVIDER_INCOMPLETE")
    return {"job": job, "status": data["status"]}


def invoke(job: str, *, environ=os.environ, opener=strict_open,
           sleeper=time.sleep) -> dict:
    if job not in JOBS:
        raise JobFailure("NBA_JOB_UNRECOGNIZED")
    for attempt in range(2):
        try:
            identity = github_identity(environ=environ, opener=opener)
            request = Request(ENDPOINT, method="POST", data=json.dumps(
                {"job": job}, separators=(",", ":")
            ).encode("utf-8"), headers={
                "Authorization": "Bearer " + identity,
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
            return validate_receipt(
                job, read_json(request, opener=opener, timeout=170)
            )
        except HTTPError as exc:
            if attempt == 0 and (exc.code == 429 or exc.code >= 500):
                sleeper(12)
                continue
            raise JobFailure("NBA_STAGE_HTTP_" + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            if attempt == 0:
                sleeper(12)
                continue
            raise JobFailure("NBA_STAGE_TRANSPORT_UNAVAILABLE") from None
        except (ValueError, UnicodeDecodeError):
            raise JobFailure("NBA_STAGE_INVALID_JSON") from None
    raise JobFailure("NBA_STAGE_RETRIES_EXHAUSTED")


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in JOBS:
        print("::error::Expected settlement, forecast or market", file=sys.stderr)
        return 2
    try:
        outcome = invoke(argv[0])
    except JobFailure as exc:
        print("::error::" + str(exc), file=sys.stderr)
        return 1
    print("Verified private NBA staging receipt: " +
          json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
