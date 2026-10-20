"""Narrow, fail-closed bridge from assistant-curated SportyBet codes to admin tiers.

The integration does NOT grant a chatbot a general admin session. A dedicated
Render secret authorizes one authenticated preview followed by an explicitly
confirmed, time-limited, exact-ticket publish. Existing editorial publication
remains the only writer; model outcomes and calibration are unaffected.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

CONFIRMATION = "PUBLISH_VERIFIED_TICKET"
TIERS = Literal["banker", "2_odds", "5_odds", "10_odds", "over_1_5", "rollover"]
TOKEN_SECONDS = 600


class AssistantTicket(BaseModel):
    tier: TIERS
    code: str = Field(min_length=4, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    expected_legs: int = Field(ge=1, le=20)


class AssistantPublish(AssistantTicket):
    preview_token: str = Field(min_length=24, max_length=4096)
    confirmation: Literal["PUBLISH_VERIFIED_TICKET"]


def _secret() -> bytes:
    raw = os.getenv("BETSIGHTLY_ASSISTANT_PUBLISH_KEY", "").strip()
    if len(raw) < 32:
        raise HTTPException(503, "Assistant publishing key is not configured")
    return raw.encode("utf-8")


def require_assistant_key(request: Request) -> None:
    """Separate least-privilege key; never accept a generic public API token."""
    secret = _secret()
    supplied = request.headers.get("x-betsightly-assistant-key", "")
    if not supplied or not hmac.compare_digest(supplied.encode("utf-8"), secret):
        raise HTTPException(401, "Unauthorized assistant publishing request")


def _encode_token(data: dict) -> str:
    blob = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(_secret(), blob, hashlib.sha256).digest()
    message = base64.urlsafe_b64encode(blob).decode("ascii")
    mac = base64.urlsafe_b64encode(signature).decode("ascii")
    return message + "." + mac


def _decode_token(token: str) -> dict:
    try:
        message, mac = token.split(".")
        blob = base64.b64decode(message, altchars=b"-_", validate=True)
        signature = base64.b64decode(mac, altchars=b"-_", validate=True)
        expected = hmac.new(_secret(), blob, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        payload = json.loads(blob)
        if not isinstance(payload, dict) or int(payload["exp"]) < int(time.time()):
            raise ValueError("expired")
        return payload
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError, binascii.Error):
        raise HTTPException(422, "Missing, expired or modified preview token") from None


def _import_exact(body: AssistantTicket) -> tuple[str, dict]:
    from leagues.editorial_manual import import_share_code

    imported = import_share_code(body.code, body.tier, convert_special=False)
    lines = imported.get("lines") or ""
    if (imported.get("status") != "IMPORTED_NOT_PUBLISHED"
            or imported.get("unresolved_count") or imported.get("converted_features")
            or imported.get("original_leg_count") != body.expected_legs
            or len(lines.splitlines()) != body.expected_legs):
        raise ValueError("Code must resolve to exactly the approved ordinary-market legs")
    if any(",under_" in line.lower().replace(" ", "") for line in lines.splitlines()):
        raise ValueError("Under-goals markets are excluded from assistant publishing")
    return lines, imported


def preview_assistant_ticket(body: AssistantTicket) -> dict:
    from leagues.editorial_manual import _today, preview

    lines, imported = _import_exact(body)
    result = preview(body.tier, lines)
    games = result.get("games") or []
    if result.get("status") != "PREVIEW" or len(games) != body.expected_legs:
        raise ValueError("Bookmaker preview did not retain every selected leg")
    if result.get("cross_tier_warnings"):
        raise ValueError("Fixture already used by a published tier; no-repeat policy")
    verified_odds = float(result.get("total_odds") or 0)
    if verified_odds <= 1:
        raise ValueError("No verified live odds available for this ticket")
    day = str(result.get("date") or "")
    if day != _today():
        raise ValueError("Ticket date is not today")
    token = _encode_token({
        "tier": body.tier, "code": body.code.upper(),
        "expected_legs": body.expected_legs, "day": day,
        "lines_sha256": hashlib.sha256(lines.encode("utf-8")).hexdigest(),
        "preview_odds": verified_odds,
        "exp": int(time.time()) + TOKEN_SECONDS,
    })
    return {
        "status": "PREVIEW_ONLY", "tier": body.tier, "date": day,
        "input_code": body.code.upper(), "leg_count": len(games),
        "total_odds": verified_odds, "games": games,
        "preview_token": token, "expires_in_seconds": TOKEN_SECONDS,
        "publish_confirmed": False, "frontend_changed": False,
        "official_engine_record_unchanged": True,
        "readback_input_leg_count": imported.get("original_leg_count"),
    }


def publish_assistant_ticket(body: AssistantPublish) -> dict:
    from leagues.editorial_manual import _today, publish

    payload = _decode_token(body.preview_token)
    if (payload.get("tier") != body.tier
            or payload.get("code") != body.code.upper()
            or payload.get("expected_legs") != body.expected_legs
            or payload.get("day") != _today()):
        raise ValueError("Preview is for another ticket or date")
    lines, _ = _import_exact(body)
    if hashlib.sha256(lines.encode("utf-8")).hexdigest() != payload.get("lines_sha256"):
        raise ValueError("Bookmaker ticket changed since preview; preview again")
    # A separate, current-price bookmaker readback happens inside publish().
    # Do not silently accept a >5% odds decrease after administrator approval.
    floor = round(float(payload["preview_odds"]) * 0.95, 3)
    published = publish(
        body.tier, lines, strict_no_overlap=True,
        min_publish_odds=floor,
    )
    if published.get("status") != "PUBLISHED" or published.get("leg_count") != body.expected_legs:
        raise ValueError("Publication did not retain every approved selection")
    return {
        **published,
        "source": "assistant_verified_import",
        "original_input_code": body.code.upper(),
        "share_code_rebooked": published.get("share_code") != body.code.upper(),
        "preview_approved": True,
        "frontend": "published_editorial_overlay",
        "calibration_unchanged": True,
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
    }
