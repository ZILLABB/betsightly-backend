"""
Crawler-facing match pages and sitemap.

The site is a client-rendered SPA, so every meta tag it produces is written by
JavaScript after load. Google will usually render that; **social crawlers will
not**. Facebook, X, WhatsApp, LinkedIn and Telegram's link preview all fetch
the HTML and read it as-is, which is why every Betsightly link currently
previews with the same generic title and image no matter what it points at.

Distribution is the entire point of the Growth Engine, and it fails at the
last step if the link people are asked to click looks broken in the preview.

So `/p/{slug}` is served here, from FastAPI, as real HTML with real metadata:
title, description, canonical, Open Graph, Twitter card and JSON-LD, all built
from the same published card the site and Telegram use. A human hitting the
URL is redirected straight into the SPA; a crawler gets a complete document.

Two things this is careful about:

- **The canonical points at the SPA route**, so this page never competes with
  the real one for ranking. It is a preview surface, not a duplicate site.
- **No thin pages.** A slug that is not on today's card 404s rather than
  rendering an empty shell, because publishing hundreds of contentless URLs is
  how a domain earns a manual action.
"""

import html
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

SITE = "https://www.betsightly.com"

# Crawlers that need server-rendered HTML. Matched case-insensitively against
# the user agent; anything not listed is a human and gets redirected.
CRAWLER_TOKENS = (
    "facebookexternalhit", "twitterbot", "linkedinbot", "slackbot",
    "whatsapp", "telegrambot", "discordbot", "pinterest", "redditbot",
    "googlebot", "bingbot", "duckduckbot", "yandexbot", "applebot",
    "embedly", "quora link preview", "vkshare", "skypeuripreview",
)


def is_crawler(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(token in ua for token in CRAWLER_TOKENS)


def find_leg(slug: str) -> Optional[dict]:
    """The published pick for a slug, or None if it is not on today's card.

    Reads the dataset, so a match page can only ever exist for a fixture we
    have actually published a pick on.
    """
    try:
        from growth.dataset import build
        data = build(include_value_bets=False)
        if not data:
            return None

        pools = []
        for key in ("banker", "over_1_5", "two_odds", "five_odds", "ten_odds"):
            tier = data.get(key) or {}
            pools.extend(tier.get("legs") or [])
        pools.extend((data.get("rollover") or {}).get("legs") or [])

        for leg in pools:
            if leg.get("slug") == slug:
                return {"leg": leg, "date": data.get("date")}
        return None
    except Exception as e:
        logger.warning(f"seo: lookup failed for {slug}: {e}")
        return None


def _jsonld(leg: dict, url: str) -> str:
    """SportsEvent markup. Describes the fixture, never asserts an outcome."""
    data = {
        "@context": "https://schema.org",
        "@type": "SportsEvent",
        "name": f"{leg['home_team']} vs {leg['away_team']}",
        "url": url,
        "sport": "Association Football",
        "competitor": [
            {"@type": "SportsTeam", "name": leg["home_team"]},
            {"@type": "SportsTeam", "name": leg["away_team"]},
        ],
    }
    if leg.get("kickoff"):
        data["startDate"] = leg["kickoff"]
    if leg.get("league"):
        data["superEvent"] = {"@type": "SportsOrganization", "name": leg["league"]}
    if leg.get("venue"):
        data["location"] = {"@type": "Place", "name": leg["venue"]}
    return json.dumps(data, ensure_ascii=False)


def render_match_page(slug: str, leg: dict, date: str) -> str:
    """Complete HTML document for one fixture."""
    from growth.compliance import DISCLAIMER, safe_confidence

    e = html.escape
    match = f"{leg['home_team']} vs {leg['away_team']}"
    conf = safe_confidence(leg.get("confidence") or 0)
    odds = leg.get("odds") or 0
    price_note = "" if leg.get("odds_are_real") else " (estimated)"

    title = f"{match} Prediction & Odds — {leg.get('league') or 'Football'} | BetSightly"
    description = (
        f"{match}: our model makes {leg.get('prediction')} "
        f"{conf} likely at odds of {odds:.2f}{price_note}. "
        f"Probabilistic, not a guarantee."
    )
    # Canonical points at the SPA route this page previews, so the preview
    # surface never competes with the real page in search.
    canonical = f"{SITE}/predictions"
    share_url = f"{SITE}/p/{slug}"
    spa_url = f"{SITE}/predictions?utm_source=share&utm_medium=referral&utm_campaign=match_page"

    kickoff = ""
    if leg.get("kickoff"):
        try:
            kickoff = datetime.fromisoformat(
                leg["kickoff"].replace("Z", "+00:00")
            ).strftime("%d %B %Y, %H:%M UTC")
        except Exception:
            kickoff = leg["kickoff"]

    rows = [
        ("League", leg.get("league")),
        ("Kick-off", kickoff),
        ("Venue", leg.get("venue")),
        ("Market", leg.get("market_group")),
        ("Prediction", leg.get("prediction")),
        ("Model confidence", conf),
        ("Odds", f"{odds:.2f}{price_note}"),
        ("Home form", leg.get("home_form")),
        ("Away form", leg.get("away_form")),
    ]
    table = "\n".join(
        f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>"
        for k, v in rows if v
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta name="robots" content="index,follow">

<meta property="og:type" content="article">
<meta property="og:site_name" content="BetSightly">
<meta property="og:title" content="{e(match)} — {e(str(leg.get('prediction')))}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(share_url)}">
<meta property="og:image" content="{SITE}/og-image.svg">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(match)} — {e(str(leg.get('prediction')))}">
<meta name="twitter:description" content="{e(description)}">
<meta name="twitter:image" content="{SITE}/og-image.svg">

<script type="application/ld+json">{_jsonld(leg, share_url)}</script>
<style>
 body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
   background:#0b0f14;color:#e6edf3;margin:0;padding:2rem 1rem;line-height:1.6}}
 main{{max-width:640px;margin:0 auto}}
 h1{{font-size:1.5rem;margin:0 0 .25rem}}
 .league{{color:#8b949e;font-size:.9rem;margin-bottom:1.5rem}}
 .pick{{background:#11171f;border-left:3px solid #2ea043;border-radius:8px;
   padding:1rem 1.25rem;margin-bottom:1.5rem}}
 .pick strong{{display:block;font-size:1.15rem;color:#2ea043}}
 table{{width:100%;border-collapse:collapse;margin-bottom:1.5rem}}
 th,td{{text-align:left;padding:.5rem 0;border-bottom:1px solid #1f2630;font-size:.92rem}}
 th{{color:#8b949e;font-weight:500;width:45%}}
 a.cta{{display:inline-block;background:#2ea043;color:#fff;padding:.7rem 1.2rem;
   border-radius:8px;text-decoration:none;font-weight:600}}
 .disclaimer{{margin-top:2rem;color:#8b949e;font-size:.8rem}}
</style>
</head>
<body>
<main>
  <h1>{e(match)}</h1>
  <div class="league">{e(str(leg.get('league') or ''))}{(' · ' + e(kickoff)) if kickoff else ''}</div>

  <div class="pick">
    <strong>{e(str(leg.get('prediction')))}</strong>
    <span>{e(conf)} model confidence · odds {odds:.2f}{e(price_note)}</span>
  </div>

  <table>{table}</table>

  <p><a class="cta" href="{e(spa_url)}">See today's full card</a></p>

  <p class="disclaimer">{e(DISCLAIMER)}</p>
</main>
</body>
</html>"""


def build_sitemap() -> str:
    """Sitemap covering the static routes plus today's published match pages.

    Generated rather than hand-maintained, so a match page is listed exactly
    while it exists and drops out when the card rolls over — a sitemap full of
    404s is worse than a small one.
    """
    static = [
        ("/", "1.0", "daily"),
        ("/predictions", "0.9", "daily"),
        ("/value", "0.9", "daily"),
        ("/rollover", "0.8", "daily"),
        ("/results", "0.8", "daily"),
        ("/punters", "0.6", "weekly"),
        ("/about", "0.4", "monthly"),
    ]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, priority, freq in static:
        parts.append(
            f"  <url><loc>{SITE}{path}</loc><lastmod>{today}</lastmod>"
            f"<changefreq>{freq}</changefreq><priority>{priority}</priority></url>"
        )

    try:
        from growth.dataset import build
        data = build(include_value_bets=False)
        if data:
            seen = set()
            for key in ("banker", "over_1_5", "two_odds", "five_odds", "ten_odds"):
                for leg in (data.get(key) or {}).get("legs") or []:
                    slug = leg.get("slug")
                    if not slug or slug in seen:
                        continue
                    seen.add(slug)
                    parts.append(
                        f"  <url><loc>{SITE}/p/{slug}</loc>"
                        f"<lastmod>{today}</lastmod>"
                        f"<changefreq>daily</changefreq><priority>0.7</priority></url>"
                    )
    except Exception as e:
        logger.warning(f"seo: sitemap match pages unavailable ({e})")

    parts.append("</urlset>")
    return "\n".join(parts)
