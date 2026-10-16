"""Verified, time-bounded website-hero campaigns.

This is editorial WEBSITE content, not social publishing, model predictions,
betting codes, prices or a way to alter historical performance. Defaults are
off; a logged-in admin must explicitly review and schedule each campaign.
"""
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

_ALLOWED_PATHS = frozenset({"/predictions", "/build-slip", "/results", "/rollover"})
_FIELDS = frozenset({
    "enabled", "reviewed", "eyebrow", "headline", "description",
    "cta_text", "cta_path", "starts_on", "ends_on", "source_url",
})

DEFAULT_CAMPAIGN = {
    "enabled": False, "reviewed": False, "eyebrow": "",
    "headline": "", "description": "", "cta_text": "View predictions",
    "cta_path": "/predictions", "starts_on": "", "ends_on": "",
    "source_url": "",
}


def validate_campaign(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Campaign must be an object.")
    unknown = set(payload) - _FIELDS
    if unknown:
        raise ValueError("Unknown campaign fields: " + ", ".join(sorted(unknown)))
    out = dict(DEFAULT_CAMPAIGN)
    out.update(payload)
    for field in ("enabled", "reviewed"):
        if not isinstance(out[field], bool):
            raise ValueError(field + " must be a boolean.")
    limits = {
        "eyebrow": 50, "headline": 85, "description": 220,
        "cta_text": 36, "cta_path": 60, "starts_on": 10,
        "ends_on": 10, "source_url": 350,
    }
    for field, limit in limits.items():
        if not isinstance(out[field], str):
            raise ValueError(field + " must be text.")
        out[field] = out[field].strip()
        if len(out[field]) > limit or any(ord(c) < 32 for c in out[field]):
            raise ValueError(field + " contains invalid characters or is too long.")
    if out["cta_path"] not in _ALLOWED_PATHS:
        raise ValueError("Campaign CTA must link to an existing BetSightly page.")
    if out["source_url"]:
        parts = urlparse(out["source_url"])
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("Source must be a public HTTPS URL.")
    if out["enabled"]:
        if not out["reviewed"]:
            raise ValueError("Admin must confirm the event and dates were reviewed.")
        for key in ("eyebrow", "headline", "description", "starts_on", "ends_on"):
            if not out[key]:
                raise ValueError(key + " is required for an active campaign.")
        if not out["source_url"]:
            raise ValueError("Include a source URL for the verified event.")
    if out["starts_on"] or out["ends_on"]:
        try:
            if len(out["starts_on"]) != 10 or len(out["ends_on"]) != 10:
                raise ValueError
            start = date.fromisoformat(out["starts_on"])
            end = date.fromisoformat(out["ends_on"])
        except ValueError as exc:
            raise ValueError("Use YYYY-MM-DD start and end dates.") from exc
        if end < start or (end - start).days > 90:
            raise ValueError("Campaign date range must be 1–91 calendar days.")
    return out


def current_campaign(value: object, today: date | None = None) -> dict | None:
    """Safe public projection; expiry is authoritative and requires no job."""
    if not isinstance(value, dict):
        return None
    try:
        c = validate_campaign(value)
        today = today or datetime.now(ZoneInfo("Africa/Lagos")).date()
        if not (c["enabled"] and c["reviewed"]):
            return None
        if not date.fromisoformat(c["starts_on"]) <= today <= date.fromisoformat(c["ends_on"]):
            return None
        return {key: c[key] for key in (
            "eyebrow", "headline", "description", "cta_text", "cta_path",
            "starts_on", "ends_on",
        )}
    except (ValueError, TypeError, OverflowError):
        return None
