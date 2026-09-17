"""
Admin authentication.

The backend had no authentication of any kind before this: no users, no
sessions, no roles, and the one shared `API_KEY` is not set in production, so
every endpoint currently answers anybody. That was survivable while everything
was read-only public prediction data. It stops being survivable the moment
there are endpoints that publish to Telegram and change posting settings, so
this gates all of them.

Deliberately a single admin rather than a user system: the account phase is
still ahead, and inventing half a user model now would have to be unpicked
later. What it is not is a shared secret in a header — that leaks into logs,
browser history and screen shares.

How it works:
- Password lives only as a hash in `ADMIN_PASSWORD_HASH` (PBKDF2-SHA256).
  The plaintext is never in the environment, the database or the repo.
- Login returns a signed, expiring token in an httpOnly cookie, so page
  JavaScript cannot read it and an XSS cannot exfiltrate the session.
- Tokens are signed with SECRET_KEY, which Render already generates.
- Failed logins are rate-limited per IP, and comparisons are constant-time.

If no hash is configured the admin API refuses to authenticate anybody rather
than falling open, which is the failure mode the existing `require_api_key`
has and the reason production is currently unauthenticated.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlparse

from fastapi import Cookie, HTTPException, Request, Response

logger = logging.getLogger(__name__)

COOKIE_NAME = "bs_admin"
TOKEN_TTL = 12 * 3600           # a working day, then log in again
PBKDF2_ROUNDS = 240_000

# Per-IP login throttle. Small and in-memory on purpose: it exists to blunt
# online guessing, and the process runs single-worker.
_MAX_ATTEMPTS = 8
_ATTEMPT_WINDOW = 900
_attempts: dict[str, list[float]] = {}


class AdminNotConfigured(RuntimeError):
    pass


def _secret() -> bytes:
    key = os.getenv("SECRET_KEY", "")
    if not key:
        raise AdminNotConfigured("SECRET_KEY is not set")
    return key.encode()


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """`pbkdf2_sha256$rounds$salt$hash` — the string to put in the env var."""
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return (f"pbkdf2_sha256${PBKDF2_ROUNDS}$"
            f"{base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}")


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def is_configured() -> bool:
    return bool(os.getenv("ADMIN_PASSWORD_HASH", "").strip()
                and os.getenv("SECRET_KEY", "").strip())


# ── Tokens ─────────────────────────────────────────────────

def _sign(payload: bytes) -> str:
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return (base64.urlsafe_b64encode(payload).decode().rstrip("=") + "."
            + base64.urlsafe_b64encode(sig).decode().rstrip("="))


def _unsign(token: str) -> Optional[dict]:
    try:
        body_b64, sig_b64 = token.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)
        payload = base64.urlsafe_b64decode(pad(body_b64))
        sig = base64.urlsafe_b64decode(pad(sig_b64))
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(payload)
    except Exception:
        return None


def issue_token(subject: str = "admin") -> str:
    payload = json.dumps(
        {"sub": subject, "iat": int(time.time()), "exp": int(time.time()) + TOKEN_TTL},
        separators=(",", ":"),
    ).encode()
    return _sign(payload)


def validate_token(token: str) -> Optional[str]:
    data = _unsign(token)
    if not data:
        return None
    if int(data.get("exp", 0)) < int(time.time()):
        return None
    return data.get("sub")


# ── Login throttle ─────────────────────────────────────────

def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _throttled(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _attempts.get(ip, []) if now - t < _ATTEMPT_WINDOW]
    _attempts[ip] = hits
    return len(hits) >= _MAX_ATTEMPTS


def _record_attempt(ip: str) -> None:
    _attempts.setdefault(ip, []).append(time.time())


def login(request: Request, response: Response, password: str) -> dict:
    """Verify the password and set the session cookie."""
    ip = _client_ip(request)

    if not is_configured():
        # Refuses rather than falling open. An admin API that authenticates
        # nobody when misconfigured is safe; one that authenticates everybody
        # is how this backend ended up unauthenticated in production.
        raise HTTPException(
            503,
            "Admin login is not configured. Set ADMIN_PASSWORD_HASH and SECRET_KEY.",
        )

    if _throttled(ip):
        raise HTTPException(429, "Too many login attempts. Try again later.")

    if not verify_password(password or "", os.getenv("ADMIN_PASSWORD_HASH", "")):
        _record_attempt(ip)
        logger.warning(f"admin: failed login from {ip}")
        raise HTTPException(401, "Incorrect password.")

    _attempts.pop(ip, None)
    token = issue_token()
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=TOKEN_TTL,
        httponly=True,      # unreadable from page JS
        secure=True,        # HTTPS only
        samesite="strict",  # dashboard and API are deliberately same-origin
        path="/",
    )
    logger.info(f"admin: login from {ip}")
    return {"ok": True, "expires_in": TOKEN_TTL}


def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/", samesite="strict", secure=True)
    return {"ok": True}


def require_admin(request: Request,
                  bs_admin: Optional[str] = Cookie(default=None)) -> str:
    """FastAPI dependency guarding every admin route."""
    if not is_configured():
        raise HTTPException(503, "Admin access is not configured.")
    if not bs_admin:
        raise HTTPException(401, "Not signed in.")
    subject = validate_token(bs_admin)
    if not subject:
        raise HTTPException(401, "Session expired. Sign in again.")

    # SameSite=Strict is the primary CSRF boundary. This origin check is a
    # second layer for browsers on every state-changing request.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin:
            origin_host = urlparse(origin).netloc.lower()
            request_host = request.headers.get("host", "").lower()
            if not origin_host or origin_host != request_host:
                raise HTTPException(403, "Cross-origin admin request refused.")
    return subject
