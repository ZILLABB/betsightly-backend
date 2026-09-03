"""Privacy-safe request enrichment and analytics event classification."""

from __future__ import annotations

from typing import Mapping, Optional
from urllib.parse import unquote, urlparse


USER_EVENT = "USER_EVENT"
SYSTEM_EVENT = "SYSTEM_EVENT"

USER_EVENT_TYPES = {
    "pageview", "prediction_viewed", "rollover_viewed", "builder_opened",
    "builder_target_selected", "builder_generate_requested", "builder_generated",
    "builder_bookable", "booking_code_viewed", "booking_code_copied",
    "sportybet_opened", "sportybet_open_clicked", "fallback_shown",
    "alternative_market_used", "replacement_used", "partial_booking_used",
    "partial_booking_created",
    "results_viewed", "telegram_join_clicked", "cta_click", "registration",
    "outbound", "code_regenerated", "replacement_details_opened",
}

SYSTEM_EVENT_TYPES = {
    "booking_code_generated", "booking_code_validated",
    "prediction_run_completed", "sportybet_catalogue_fetched",
    "settlement_completed", "scheduler_job_completed",
}

PRODUCT_SOURCES = {
    "PREDICTIONS", "ROLLOVER", "BUILD_SLIP", "BANKER", "TWO_ODDS",
    "FIVE_ODDS", "TEN_ODDS", "OVER_1_5", "FALLBACK", "OTHER",
}

_TIER_SOURCES = {
    "banker": "BANKER", "two_odds": "TWO_ODDS", "2_odds": "TWO_ODDS",
    "five_odds": "FIVE_ODDS", "5_odds": "FIVE_ODDS",
    "ten_odds": "TEN_ODDS", "10_odds": "TEN_ODDS",
    "over_1_5": "OVER_1_5", "over1.5": "OVER_1_5",
    "rollover": "ROLLOVER",
}


def classify_event(event_type: str) -> str:
    if event_type in USER_EVENT_TYPES:
        return USER_EVENT
    if event_type in SYSTEM_EVENT_TYPES:
        return SYSTEM_EVENT
    return SYSTEM_EVENT


def _clean(value: Optional[str], limit: int) -> Optional[str]:
    value = unquote(str(value or "")).strip()
    return value[:limit] or None


def _country_code(value: Optional[str]) -> Optional[str]:
    code = str(value or "").strip().upper()
    return code if len(code) == 2 and code.isalpha() and code != "XX" else None


def request_geo(headers: Mapping[str, str], browser_timezone: Optional[str] = None) -> dict:
    """Use trusted edge metadata; never retain or return the request IP."""
    # Vercel attaches x-vercel-id on the normal same-origin proxy path. This is
    # appropriate coarse product analytics, not an authentication boundary:
    # like every public analytics beacon, a determined non-browser client can
    # fabricate a request and must not turn these fields into security facts.
    if headers.get("x-vercel-id"):
        return {
            "country_code": _country_code(headers.get("x-vercel-ip-country")),
            "region": _clean(headers.get("x-vercel-ip-country-region"), 96),
            "city": _clean(headers.get("x-vercel-ip-city"), 96),
            "timezone": _clean(headers.get("x-vercel-ip-timezone"), 64)
                        or _clean(browser_timezone, 64),
            "geo_source": "vercel",
        }
    # Cloudflare provides a trustworthy country header only when the request
    # actually traversed its network (cf-ray is injected by Cloudflare).
    if headers.get("cf-ray"):
        return {
            "country_code": _country_code(headers.get("cf-ipcountry")),
            "region": None, "city": None,
            "timezone": _clean(browser_timezone, 64),
            "geo_source": "cloudflare",
        }
    return {
        "country_code": None, "region": None, "city": None,
        "timezone": _clean(browser_timezone, 64), "geo_source": None,
    }


def device_info(user_agent: str) -> dict:
    ua = (user_agent or "").strip()
    low = ua.lower()
    if not low:
        return {"device_type": "unknown", "operating_system": "unknown",
                "browser": "Unknown"}

    if "ipad" in low or "tablet" in low or ("android" in low and "mobile" not in low):
        device = "tablet"
    elif any(token in low for token in ("iphone", "ipod", "mobile")):
        device = "mobile"
    else:
        device = "desktop"

    if "android" in low:
        operating_system = "Android"
    elif any(token in low for token in ("iphone", "ipad", "ipod")):
        operating_system = "iOS"
    elif "windows" in low:
        operating_system = "Windows"
    elif any(token in low for token in ("macintosh", "mac os x")):
        operating_system = "macOS"
    elif "linux" in low:
        operating_system = "Linux"
    else:
        operating_system = "Other"

    if "samsungbrowser" in low:
        browser = "Samsung Internet"
    elif any(token in low for token in ("edg/", "edga/", "edgios/")):
        browser = "Edge"
    elif any(token in low for token in ("crios/", "chrome/")):
        browser = "Chrome"
    elif any(token in low for token in ("fxios/", "firefox/")):
        browser = "Firefox"
    elif "safari/" in low and not any(token in low for token in ("chrome/", "crios/", "android")):
        browser = "Safari"
    else:
        browser = "Other"
    return {"device_type": device, "operating_system": operating_system,
            "browser": browser}


def traffic_source(source: Optional[str], medium: Optional[str],
                   referrer: Optional[str]) -> tuple[str, str, Optional[str]]:
    raw_source = (source or "").strip().lower()
    raw_medium = (medium or "").strip().lower()
    try:
        host = (urlparse(referrer or "").hostname or "").lower() or None
    except Exception:
        host = None
    internal = bool(host and "betsightly" in host)

    paid = raw_medium in {"cpc", "ppc", "paid", "paid_social", "display", "ads"}
    if paid:
        label = "Google Ads" if "google" in raw_source else "Other Paid"
    elif raw_source:
        if "google" in raw_source:
            label = "Google Organic" if raw_medium in {"", "organic"} else "Google"
        elif "bing" in raw_source:
            label = "Bing Organic" if raw_medium in {"", "organic"} else "Bing"
        elif any(x in raw_source for x in ("telegram", "t.me")):
            label = "Telegram"
        elif "whatsapp" in raw_source:
            label = "WhatsApp"
        elif raw_source in {"facebook", "fb"}:
            label = "Facebook"
        elif raw_source == "instagram":
            label = "Instagram"
        elif raw_source in {"x", "twitter"}:
            label = "X"
        elif raw_medium == "referral" or raw_source in {"referral", "share"}:
            label = "Referral"
        else:
            label = source[:64]
    elif not host or internal:
        label = "Direct"
    elif "google." in host:
        label = "Google Organic"
    elif "bing." in host:
        label = "Bing Organic"
    elif host in {"t.me", "telegram.me"} or "telegram." in host:
        label = "Telegram"
    elif "whatsapp." in host or host == "wa.me":
        label = "WhatsApp"
    elif "facebook." in host or host.startswith("fb."):
        label = "Facebook"
    elif "instagram." in host:
        label = "Instagram"
    elif host in {"t.co", "x.com", "twitter.com"}:
        label = "X"
    else:
        label = "Referral"
    normalized_medium = raw_medium or ("organic" if label.endswith("Organic") else
                                       "referral" if label == "Referral" else "none")
    return label, normalized_medium, None if internal else host


def product_source(explicit: Optional[str], content_source: Optional[str],
                   path: Optional[str], tier: Optional[str]) -> str:
    candidate = str(explicit or "").strip().upper()
    if candidate in PRODUCT_SOURCES:
        return candidate
    if content_source == "generator":
        return "BUILD_SLIP"
    if content_source == "bookable_now":
        return "FALLBACK"
    low_path = (path or "").lower()
    if "rollover" in low_path:
        return "ROLLOVER"
    if "build" in low_path:
        return "BUILD_SLIP"
    tier_source = _TIER_SOURCES.get((tier or "").lower())
    if tier_source:
        return tier_source
    if "prediction" in low_path or content_source == "daily_card":
        return "PREDICTIONS"
    return "OTHER"
