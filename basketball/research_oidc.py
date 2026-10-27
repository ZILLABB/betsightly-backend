"""Verify short-lived GitHub Actions OIDC identity for isolated NBA staging jobs.

No long-lived GitHub Actions secret. The JWT signature, exact source repo
identity, default branch, workflow and event are always verified.
"""
from __future__ import annotations

import time
from typing import Callable

import requests
from jose import jwt
from jose.exceptions import JOSEError

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = ISSUER + "/.well-known/jwks"
AUDIENCE = "betsightly-nba-stage-scheduler-v1"
REPOSITORY_ID = "987952639"
REPOSITORY = "ZILLABB/betsightly-backend"
BRANCH = "refs/heads/dev"
WORKFLOWS = {
    "settlement": REPOSITORY + "/.github/workflows/nba-private-stage-settlement.yml@" + BRANCH,
    "forecast": REPOSITORY + "/.github/workflows/nba-private-stage-research.yml@" + BRANCH,
    "market": REPOSITORY + "/.github/workflows/nba-private-stage-research.yml@" + BRANCH,
    "migration": REPOSITORY + "/.github/workflows/nba-private-stage-migration.yml@" + BRANCH,
}


def fetch_public_signing_keys() -> dict:
    # A fixed URL, never derived from untrusted token claims or header fields.
    response = requests.get(JWKS_URL, timeout=6, allow_redirects=False,
                            headers={"Accept": "application/json"})
    if response.status_code != 200 or len(response.content) > 100_000:
        raise ValueError("GITHUB_OIDC_KEYS_UNAVAILABLE")
    return response.json()


def verify_github_job(token: str, job: str, *,
                      jwks_provider: Callable[[], dict] = fetch_public_signing_keys,
                      clock: Callable[[], float] = time.time) -> dict:
    if job not in WORKFLOWS or not isinstance(token, str) or not 80 <= len(token) <= 10_000:
        raise ValueError("GITHUB_OIDC_DENIED")
    try:
        header = jwt.get_unverified_header(token)
        if not isinstance(header, dict) or header.get("alg") != "RS256" or any(
            field in header for field in ("jku", "jwk", "x5u", "crit")
        ):
            raise ValueError("GITHUB_OIDC_HEADER_DENIED")
        kid = header.get("kid")
        if not isinstance(kid, str) or not 1 <= len(kid) <= 180:
            raise ValueError("GITHUB_OIDC_KEY_ID_DENIED")
        public_keys = jwks_provider()
        if not isinstance(public_keys, dict) or not isinstance(public_keys.get("keys"), list):
            raise ValueError("GITHUB_OIDC_KEYS_INVALID")
        matches = [key for key in public_keys["keys"] if
                   isinstance(key, dict) and key.get("kid") == kid and
                   key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
                   and key.get("alg", "RS256") == "RS256"]
        if len(matches) != 1:
            raise ValueError("GITHUB_OIDC_KEY_NOT_TRUSTED")
        claims = jwt.decode(token, matches[0], algorithms=["RS256"],
                            audience=AUDIENCE, issuer=ISSUER,
                            options={"verify_aud": True, "verify_iss": True,
                                     "verify_exp": True, "verify_iat": True,
                                     "require_exp": True, "require_iat": True,
                                     "require_sub": True})
        now = clock()
        issued, expires = claims.get("iat"), claims.get("exp")
        if type(issued) is not int or type(expires) is not int or not (
            now - 300 <= issued <= now + 20 and now < expires <= now + 600
        ):
            raise ValueError("GITHUB_OIDC_TIME_DENIED")
        expected = {
            "sub": "repo:" + REPOSITORY + ":ref:" + BRANCH,
            "repository": REPOSITORY,
            "repository_id": REPOSITORY_ID,
            "ref": BRANCH,
            "workflow_ref": WORKFLOWS[job],
        }
        if any(claims.get(key) != value for key, value in expected.items()):
            raise ValueError("GITHUB_OIDC_SOURCE_DENIED")
        if claims.get("event_name") not in ("schedule", "workflow_dispatch"):
            raise ValueError("GITHUB_OIDC_EVENT_DENIED")
        return claims
    except (JOSEError, KeyError, TypeError, requests.RequestException) as exc:
        raise ValueError("GITHUB_OIDC_INVALID") from exc
