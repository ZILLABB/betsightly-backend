"""
Trackable links.

Every outbound link carries where it came from, so "which content actually
brings people in" is answerable from data rather than guessed at.

Two rules shape this module:

- **Canonical URLs must not change.** Tracking lives entirely in the query
  string. `/predictions` and `/predictions?utm_source=telegram` are the same
  page, and the canonical tag on it points at the bare path, so adding
  campaign parameters can never split the page's search ranking.
- **Parameters are appended, never replaced.** A link that already carries a
  creator ref keeps it.
"""

from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

SITE = "https://www.betsightly.com"

# Landing pages a piece of content can point at.
LANDINGS = {
    "predictions": "/predictions",
    "results": "/results",
    "rollover": "/rollover",
    "home": "/",
}

# utm_medium per channel. Organic social and a bot broadcast are genuinely
# different acquisition paths and get separated here rather than in analysis.
CHANNEL_MEDIUM = {
    "telegram": "messaging",
    "instagram": "social",
    "facebook": "social",
    "x": "social",
    "tiktok": "social",
    "youtube": "social",
    "website": "internal",
}


def build_url(landing: str = "predictions", *, channel: str = "telegram",
              campaign: str = "daily_picks", content: str | None = None,
              ref: str | None = None, match_slug: str | None = None) -> str:
    """A tracked URL for one piece of content on one channel."""
    if match_slug:
        path = f"/p/{match_slug}"
    else:
        path = LANDINGS.get(landing, LANDINGS["predictions"])

    params = {
        "utm_source": channel,
        "utm_medium": CHANNEL_MEDIUM.get(channel, "referral"),
        "utm_campaign": campaign,
    }
    if content:
        params["utm_content"] = content
    if ref:
        params["ref"] = ref

    parsed = urlparse(f"{SITE}{path}")
    existing = dict(parse_qsl(parsed.query))
    # Existing parameters win — a creator's ref must survive templating.
    merged = {**params, **existing}
    return urlunparse(parsed._replace(query=urlencode(merged)))


def canonical_url(path: str) -> str:
    """The indexable URL for a path, with every tracking parameter stripped."""
    parsed = urlparse(path if path.startswith("http") else f"{SITE}{path}")
    return urlunparse(parsed._replace(query="", fragment=""))
