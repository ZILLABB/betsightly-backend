"""
Growth Engine API.

Three groups of routes with different exposure, which is the important part:

- **Public, unauthenticated**: the tracking beacon and the crawler-facing
  match pages. These have to be open — a beacon behind auth records nothing
  and a share page behind auth previews as a login screen.
- **Admin, cookie-authenticated**: everything that reads business data or
  causes a public post. `require_admin` guards all of them.
- **Login**: rate-limited, and refuses to authenticate at all when the admin
  password is unconfigured rather than falling open.

Nothing here does prediction work. Generation and publishing delegate to
`growth.engine`, which never raises.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

from growth.admin_auth import login as _login, logout as _logout, require_admin, is_configured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Growth"])
public_router = APIRouter(tags=["Growth Public"])



# ── Protected manual prediction desk ───────────────────────
from pydantic import BaseModel, Field


class ManualTierRequest(BaseModel):
    tier: str = Field(min_length=3, max_length=20)
    lines: str = Field(min_length=3, max_length=6000)
    # Legacy Over Goals flag; retained for existing admin clients.
    replace_official_over: bool = False
    # Explicit replacement for a selected 2/5/10 Odds or Over Goals tier.
    # No Rollover or Banker override. Model records remain immutable.
    replace_official_display: bool = False


@router.get("/manual-tiers", dependencies=[Depends(require_admin)])
def manual_tiers_status():
    from leagues.editorial_manual import _today, list_published, rollover_eligibility
    day = _today()
    return {
        "date": day, "rollover": rollover_eligibility(day), "published": {
            k: {"tier": k, "total_odds": v.get("total_odds"),
                "leg_count": len(v.get("games") or []),
                "share_code": (v.get("booking") or {}).get("share_code"),
                "source": "admin_curated"}
            for k, v in list_published(day).items()
        },
    }


# Private jackpot booking uses the same signed admin cookie as publishing.
# Neither endpoint is exposed through the public BetSightly site.
class PrivateJackpotFilters(BaseModel):
    horizon: str = Field(default="today", pattern="^(today|3_days|7_days)$")
    min_trust_grade: str = Field(default="B", pattern="^[ABC]$")
    market_style: str = Field(default="all", pattern="^(all|goals|results|wins)$")
    min_leg_odds: float = Field(default=1.01, ge=1.01, le=100)
    min_probability: float = Field(default=.65, ge=.65, le=1)
    markets: list[str] = Field(default_factory=list, max_length=24)


class PrivateJackpotBookRequest(PrivateJackpotFilters):
    selection_ids: list[str] = Field(min_length=1, max_length=50)
    target_odds: float = Field(default=2, ge=2, le=100_000)


@router.post("/private-jackpot/candidates", dependencies=[Depends(require_admin)])
def private_jackpot_candidates(body: PrivateJackpotFilters):
    """Read approved/upcoming/bookable candidates without making any bet or code."""
    from growth.private_jackpot import candidate_board
    try:
        return candidate_board(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))



class PrivateJackpotOptimizeRequest(PrivateJackpotFilters):
    target_odds: float = Field(default=100_000, ge=2, le=100_000)
    max_legs: int = Field(default=50, ge=1, le=50)


@router.post("/private-jackpot/optimize", dependencies=[Depends(require_admin)])
def private_jackpot_optimize(body: PrivateJackpotOptimizeRequest):
    """Read-only feasibility and confidence-weighted suggestions; never books."""
    from growth.private_jackpot import optimize_request
    try:
        return optimize_request(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/private-jackpot/market-catalog", dependencies=[Depends(require_admin)])
def private_jackpot_market_catalog(body: PrivateJackpotFilters):
    """Return all registry-mapped SportyBet football outcomes with real approval flags."""
    from growth.jackpot_market_catalog import market_catalog_request
    try:
        return market_catalog_request(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class PrivateJackpotPasteRequest(PrivateJackpotOptimizeRequest):
    fixtures_text: str = Field(min_length=5, max_length=9000)
    # Admin-only, opt-in. The ordinary scored prediction path stays unchanged.
    selection_mode: str = Field(
        default="approved_model",
        pattern="^(approved_model|bookmaker_only)$",
    )


@router.post("/private-jackpot/paste-preview", dependencies=[Depends(require_admin)])
def private_jackpot_paste_preview(body: PrivateJackpotPasteRequest):
    """Match pasted match names to approved bookmaker-ready games; no write."""
    from growth.jackpot_paste import pasted_preview
    try:
        return pasted_preview(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/private-jackpot/paste-book", dependencies=[Depends(require_admin)])
def private_jackpot_paste_book(body: PrivateJackpotPasteRequest):
    """Explicit admin request: only full matches, exact verified readback."""
    from growth.jackpot_paste import pasted_auto_book
    try:
        return pasted_auto_book(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/private-jackpot/auto-book", dependencies=[Depends(require_admin)])
def private_jackpot_auto_book(body: PrivateJackpotOptimizeRequest):
    """Administrator-confirmed, automatic one-time optimize + exact-book."""
    from growth.private_jackpot import auto_booking_request
    try:
        return auto_booking_request(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/private-jackpot/book", dependencies=[Depends(require_admin)])
def private_jackpot_book(body: PrivateJackpotBookRequest):
    """Explicit admin request; accept only complete and verified SportyBet codes.

    Unrelated manual/public predictions, publishing and calibration never change.
    """
    from growth.private_jackpot import booking_request
    try:
        return booking_request(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class ManualCodeImportRequest(BaseModel):
    tier: str = Field(min_length=3, max_length=20)
    code: str = Field(min_length=4, max_length=32)
    convert_special: bool = False


@router.post("/manual-tiers/import-code", dependencies=[Depends(require_admin)])
def import_manual_code(body: ManualCodeImportRequest):
    from leagues.editorial_manual import import_share_code
    try:
        return import_share_code(
            body.code, body.tier, convert_special=body.convert_special,
            allow_review=body.convert_special,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/manual-tiers/preview", dependencies=[Depends(require_admin)])
def preview_manual_tier(body: ManualTierRequest):
    from leagues.editorial_manual import preview
    try:
        return preview(
            body.tier, body.lines,
            replace_official_over=body.replace_official_over,
            replace_official_display=body.replace_official_display,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/manual-tiers/inspect", dependencies=[Depends(require_admin)])
def inspect_manual_tier_prices(body: ManualTierRequest):
    """Read-only live price inspection even when this tier was already published.

    Does not create a booking code or authorize another publication. The normal
    preview and publish endpoints retain their tier and rollover guards.
    """
    from leagues.editorial_manual import preview
    try:
        return preview(body.tier, body.lines, inspection_only=True)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/manual-tiers/publish", dependencies=[Depends(require_admin)])
def publish_manual_tier(body: ManualTierRequest):
    from leagues.editorial_manual import publish
    try:
        return publish(
            body.tier, body.lines,
            replace_official_over=body.replace_official_over,
            replace_official_display=body.replace_official_display,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class ManualExistingCodePublishRequest(BaseModel):
    tier: str = Field(min_length=3, max_length=20)
    code: str = Field(min_length=4, max_length=32)
    replace_official_display: bool = False


@router.post("/manual-tiers/publish-imported", dependencies=[Depends(require_admin)])
def publish_imported_manual_code(body: ManualExistingCodePublishRequest):
    """Admin-only: resolve exact incoming code, reprice and publish a new verified code.

    The original code is an *input*, never asserted to be the newly generated
    code: SportyBet may regenerate a different share reference/price. Reject
    specials and unmapped selections; no silent leg drops or calibration edits.
    """
    from leagues.editorial_manual import import_share_code, publish
    try:
        imported = import_share_code(body.code, body.tier, convert_special=False)
        if imported.get("status") != "IMPORTED_NOT_PUBLISHED" or (
            imported.get("unresolved_count") or imported.get("converted_features")
        ):
            raise ValueError("Original code needs explicit review; nothing published")
        if (imported.get("original_leg_count")
                != len((imported.get("lines") or "").splitlines())):
            raise ValueError("Original booking code contains unmapped legs")
        result = publish(
            body.tier, imported["lines"],
            replace_official_display=body.replace_official_display,
        )
        return {
            **result, "imported_share_code": body.code,
            "share_code_rebooked": result.get("share_code") != body.code,
            "original_booking_code_unchanged": True,
        }
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# Assistant publication is intentionally separate from browser-admin sessions:
# callers need a dedicated Render secret and an explicit, expiring preview.
# Existing admin preview/publish endpoints and their cookie protections remain.
from leagues.assistant_publication import (
    AssistantTicket, AssistantPublish, require_assistant_key,
    preview_assistant_ticket, publish_assistant_ticket,
)


@router.post("/manual-tiers/assistant/preview",
             dependencies=[Depends(require_assistant_key)])
def preview_assistant_manual_ticket(body: AssistantTicket):
    try:
        return preview_assistant_ticket(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/manual-tiers/assistant/publish",
             dependencies=[Depends(require_assistant_key)])
def publish_assistant_manual_ticket(body: AssistantPublish):
    try:
        return publish_assistant_ticket(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@public_router.get("/homepage-campaign")
def homepage_campaign_public():
    """One approved, currently dated website-hero message, or null."""
    from growth.home_campaign import current_campaign
    from growth.models import get_setting
    return {"status": "success",
            "campaign": current_campaign(get_setting("home_campaign"))}


@router.get("/homepage-campaign", dependencies=[Depends(require_admin)])
def homepage_campaign_admin():
    from growth.models import get_setting
    from growth.home_campaign import validate_campaign, DEFAULT_CAMPAIGN
    stored = get_setting("home_campaign")
    try:
        campaign = validate_campaign(stored)
    except ValueError:
        campaign = DEFAULT_CAMPAIGN
    return {"status": "success", "campaign": campaign}


@router.post("/homepage-campaign", dependencies=[Depends(require_admin)])
def save_homepage_campaign(payload: dict = Body(...)):
    from growth.home_campaign import validate_campaign
    from growth.models import set_setting
    try:
        campaign = validate_campaign(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not set_setting("home_campaign", campaign):
        raise HTTPException(503, "Unable to save campaign configuration.")
    return {"status": "success", "campaign": campaign}


@public_router.get("/editorial-results")
def public_editorial_results(limit: int = Query(30, ge=1, le=90)):
    """Separate manual slip results, never official engine analytics."""
    from leagues.editorial_settlement import editorial_result_history
    return editorial_result_history(limit=limit)


# ── Public: tracking beacon ────────────────────────────────

@public_router.post("/track")
async def track(request: Request, payload: dict = Body(default={})):
    """Record an attributed event. Always returns 200.

    Analytics must never be able to break a page, so every failure path here
    is a quiet no-op rather than an error the frontend has to handle.
    """
    try:
        from growth import analytics
        from growth.analytics_enrichment import request_geo
        from growth.models import ensure_tables

        ensure_tables()
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() if fwd else (
            request.client.host if request.client else "")

        geo = request_geo(request.headers, payload.get("timezone"))
        metadata = (dict(payload.get("metadata"))
                    if isinstance(payload.get("metadata"), dict) else {})
        if payload.get("client_timestamp"):
            metadata["client_timestamp"] = str(payload["client_timestamp"])[:64]
        analytics.record(
            event_type=str(payload.get("event") or "pageview"),
            path=payload.get("path"),
            source=payload.get("utm_source"),
            medium=payload.get("utm_medium"),
            campaign=payload.get("utm_campaign"),
            content_tag=payload.get("content_tag") or payload.get("utm_content"),
            utm_term=payload.get("utm_term"),
            ref=payload.get("ref"),
            referrer=payload.get("referrer"),
            ip=ip,
            user_agent=request.headers.get("user-agent", ""),
            visitor_id=payload.get("visitor_id"),
            session_id=payload.get("session_id"),
            event_id=payload.get("event_id"),
            tier=payload.get("tier"),
            target_odds=payload.get("target_odds"),
            booking_status=payload.get("booking_status"),
            leg_count=payload.get("leg_count"),
            actual_odds=payload.get("actual_odds"),
            country_code=geo["country_code"], region=geo["region"],
            city=geo["city"], timezone_name=geo["timezone"],
            geo_source=geo["geo_source"],
            screen_width=payload.get("screen_width"),
            screen_height=payload.get("screen_height"),
            booking_id=payload.get("booking_id"),
            product_area=payload.get("product_source"),
            metadata=metadata,
        )
    except Exception as e:
        logger.debug(f"growth track failed: {e}")
    return {"ok": True}


# ── Public: crawler-facing match pages ─────────────────────

@public_router.get("/p/{slug}", response_class=HTMLResponse)
async def match_page(slug: str, request: Request):
    """Server-rendered preview for one fixture.

    Humans are redirected into the SPA; crawlers get the full document. The
    redirect keeps this from becoming a second, competing version of the site
    for people, while still giving link previews something real to read.
    """
    from growth.seo import find_leg, is_crawler, render_match_page

    found = find_leg(slug)
    if not found:
        # No thin pages: a slug with no published pick is a 404, not an empty
        # shell. Publishing contentless URLs is how a domain gets penalised.
        raise HTTPException(404, "No published prediction for this fixture.")

    if not is_crawler(request.headers.get("user-agent", "")):
        return RedirectResponse(
            url="https://www.betsightly.com/predictions"
                "?utm_source=share&utm_medium=referral&utm_campaign=match_page",
            status_code=302,
        )

    return HTMLResponse(render_match_page(slug, found["leg"], found["date"]))


# The app-wide SecurityMiddleware sets `default-src 'self'`, which blocks
# inline <style> and <script> — that is why the first version of the dashboard
# rendered as unstyled black-on-white with no working JavaScript. The CSS and
# JS are served as their own routes so `'self'` is satisfied, and this policy
# is set per-response so the middleware leaves it alone.
#
# `style-src` allows unsafe-inline because the markup uses style attributes for
# one-off layout; `script-src` deliberately does not, since inline script is
# the directive that actually stops an injected payload from executing.
_ADMIN_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)
_ADMIN_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": _ADMIN_CSP,
}


@public_router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard():
    """The dashboard shell.

    Public only in the sense that the HTML is served to anyone — it renders a
    sign-in form, and every byte of data behind it comes from routes guarded
    by `require_admin`. Served from this origin so the session cookie is
    first-party; see growth/admin_ui.py.
    """
    from growth.admin_ui import ADMIN_HTML
    return HTMLResponse(ADMIN_HTML, headers=_ADMIN_HEADERS)


@public_router.get("/admin/app.css")
async def admin_css():
    from growth.admin_ui import ADMIN_CSS
    return Response(ADMIN_CSS, media_type="text/css",
                    headers={"Cache-Control": "no-cache"})


@public_router.get("/admin/app.js")
async def admin_js():
    from growth.admin_ui import ADMIN_JS
    return Response(ADMIN_JS, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


@public_router.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap():
    """Sitemap including today's published match pages."""
    from growth.seo import build_sitemap
    return Response(content=build_sitemap(), media_type="application/xml")


# ── Admin: session ─────────────────────────────────────────

@router.get("/admin/config")
async def admin_config():
    """Whether admin login is usable. Safe to call signed out."""
    return {"configured": is_configured()}


@router.post("/admin/login")
async def admin_login(request: Request, response: Response,
                      payload: dict = Body(...)):
    return _login(request, response, str(payload.get("password") or ""))


@router.post("/admin/logout")
async def admin_logout(response: Response):
    return _logout(response)


@router.get("/admin/me")
async def admin_me(admin: str = Depends(require_admin)):
    return {"ok": True, "admin": admin}


# ── Admin: dataset + content ───────────────────────────────

@router.get("/daily")
async def growth_daily(admin: str = Depends(require_admin)):
    """Today's marketing dataset, exactly as the generators see it."""
    from growth.dataset import build
    data = build()
    if not data:
        raise HTTPException(404, "No published card yet today.")
    return {"status": "success", "data": data}


@router.post("/generate")
async def growth_generate(admin: str = Depends(require_admin),
                          publish: bool = Query(False),
                          force: bool = Query(False)):
    """Build and store today's content. Publishing is opt-in."""
    from growth.engine import run_daily
    return {"status": "success", "report": run_daily(force=force, publish=publish)}


@router.get("/content")
async def growth_content(admin: str = Depends(require_admin),
                         date: Optional[str] = None,
                         platform: Optional[str] = None,
                         status: Optional[str] = None,
                         limit: int = Query(200, le=500)):
    from growth.store import list_content
    rows = list_content(publish_date=date, platform=platform,
                        status=status, limit=limit)
    return {"status": "success", "count": len(rows), "content": rows}


@router.post("/content/{content_id}/approve")
async def growth_approve(content_id: int, admin: str = Depends(require_admin)):
    from growth.models import Status
    from growth.store import set_content_status
    row = set_content_status(content_id, Status.APPROVED, actor=admin)
    if not row:
        raise HTTPException(404, "Content not found.")
    return {"status": "success", "content": row}


@router.post("/content/{content_id}/cancel")
async def growth_cancel(content_id: int, admin: str = Depends(require_admin)):
    from growth.models import Status
    from growth.store import set_content_status
    row = set_content_status(content_id, Status.CANCELLED, actor=admin)
    if not row:
        raise HTTPException(404, "Content not found.")
    return {"status": "success", "content": row}


@router.post("/content/{content_id}/publish")
async def growth_publish(content_id: int, admin: str = Depends(require_admin)):
    """Publish one item now.

    Draft-only channels are refused explicitly rather than silently doing
    nothing, so the dashboard can explain why there is no publish button for
    Instagram instead of appearing broken.
    """
    from growth.models import Status
    from growth.publishers import get_sender, DRAFT_ONLY_CHANNELS
    from growth.store import get_content, publish_one, set_content_status

    row = get_content(content_id)
    if not row:
        raise HTTPException(404, "Content not found.")

    channel = row["platform"]
    if channel in DRAFT_ONLY_CHANNELS:
        raise HTTPException(
            400,
            f"{channel} is draft-only. Automated posting of betting content "
            f"there risks the account under the platform's policies — copy "
            f"the generated text and post it manually.",
        )

    sender = get_sender(channel)
    if sender is None:
        raise HTTPException(400, f"No publisher available for {channel}.")

    if row["status"] not in Status.PUBLISHABLE:
        set_content_status(content_id, Status.APPROVED, actor=admin)

    result = publish_one(content_id, sender)
    if not result.get("ok"):
        raise HTTPException(409, result.get("reason") or "Publish failed.")
    return {"status": "success", **result}


@router.get("/publications")
async def growth_publications(admin: str = Depends(require_admin),
                              date: Optional[str] = None,
                              limit: int = Query(200, le=500)):
    from growth.store import list_publications
    rows = list_publications(publish_date=date, limit=limit)
    return {"status": "success", "count": len(rows), "publications": rows}


@router.post("/retry")
async def growth_retry(admin: str = Depends(require_admin)):
    from growth.engine import retry_failed
    return {"status": "success", **retry_failed()}


# ── Admin: analytics + settings ────────────────────────────

@router.get("/analytics")
async def growth_analytics(admin: str = Depends(require_admin),
                           days: int = Query(1, ge=1, le=90),
                           start: Optional[str] = Query(None),
                           end: Optional[str] = Query(None)):
    from growth.analytics import compare, summary
    if bool(start) != bool(end):
        raise HTTPException(400, "Custom range requires both start and end dates.")
    if start and end:
        try:
            from datetime import datetime
            first = datetime.strptime(start, "%Y-%m-%d")
            last = datetime.strptime(end, "%Y-%m-%d")
            if last < first or (last - first).days > 90:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Choose a valid range of 90 days or less.")
    return {"status": "success",
            "summary": summary(days, start, end),
            "vs_previous": compare(days, start, end)}


@router.get("/status")
async def growth_status(admin: str = Depends(require_admin)):
    from growth.engine import status
    return {"status": "success", **status()}


@router.get("/market-readiness", dependencies=[Depends(require_admin)])
def growth_market_readiness():
    """Read-only evidence and rejection diagnostics, never a prediction trigger."""
    from growth.market_readiness import market_readiness_snapshot

    return {"status": "success", **market_readiness_snapshot()}


@router.get("/settings")
async def growth_get_settings(admin: str = Depends(require_admin)):
    from growth.models import all_settings
    return {"status": "success", "settings": all_settings()}


@router.post("/settings")
async def growth_set_settings(admin: str = Depends(require_admin),
                              payload: dict = Body(...)):
    """Update settings. Only known keys are accepted."""
    from growth.models import DEFAULT_SETTINGS, all_settings, set_setting

    unknown = [k for k in payload if k not in DEFAULT_SETTINGS]
    if unknown:
        raise HTTPException(400, f"Unknown setting(s): {', '.join(unknown)}")

    if "home_campaign" in payload:
        raise HTTPException(400, "Use the dedicated homepage-campaign editor.")
    for key, value in payload.items():
        set_setting(key, value)
    return {"status": "success", "settings": all_settings()}


@router.get("/referrals")
async def growth_referrals(admin: str = Depends(require_admin)):
    from database import SessionLocal
    from growth.models import GrowthReferral
    db = SessionLocal()
    try:
        rows = db.query(GrowthReferral).order_by(GrowthReferral.id.desc()).all()
        return {"status": "success", "referrals": [
            {"id": r.id, "code": r.code, "name": r.name,
             "active": r.active, "note": r.note,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ]}
    finally:
        db.close()


@router.post("/referrals")
async def growth_add_referral(admin: str = Depends(require_admin),
                              payload: dict = Body(...)):
    from database import SessionLocal
    from growth.models import GrowthReferral
    from growth.tracking import build_url

    code = (payload.get("code") or "").strip().lower()
    if not code or not code.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Code must be alphanumeric (dashes/underscores allowed).")

    db = SessionLocal()
    try:
        if db.query(GrowthReferral).filter(GrowthReferral.code == code).first():
            raise HTTPException(409, "That code already exists.")
        row = GrowthReferral(code=code, name=payload.get("name"),
                             note=payload.get("note"), active=True)
        db.add(row)
        db.commit()
        return {"status": "success", "code": code,
                "link": build_url("predictions", channel="referral",
                                  campaign="creator", ref=code)}
    finally:
        db.close()


@router.get("/admin/nba-research", dependencies=[Depends(require_admin)])
def nba_admin_research(response: Response):
    """Private read-only DB snapshot; do not silently invent empty fixtures."""
    import os
    if os.getenv("NBA_ADMIN_RESEARCH_ENABLED", "").lower() not in (
        "1", "true", "yes", "on"
    ):
        raise HTTPException(404, "Private NBA research is disabled.")
    from basketball.research_private_store import hosted_board
    try:
        result = hosted_board()
    except (ValueError, KeyError, OSError, TypeError) as exc:
        logger.warning("NBA stored research validation failed: %s",
                       type(exc).__name__)
        raise HTTPException(409, "NBA stored research integrity invalid.") from exc
    except Exception as exc:
        logger.warning("NBA research storage unavailable: %s",
                       type(exc).__name__)
        raise HTTPException(503, "NBA private research database unavailable.") from exc
    if result is None:
        raise HTTPException(503, "No verified NBA research archive has been imported.")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return result


def _nba_market_stage_enabled():
    import os
    return (
        os.getenv("ENVIRONMENT", "").lower() == "staging"
        and os.getenv("NBA_ADMIN_RESEARCH_ENABLED", "").lower() in
        ("1", "true", "yes", "on")
        and os.getenv("NBA_ADMIN_RESEARCH_MARKETS_ENABLED", "").lower() in
        ("1", "true", "yes", "on")
        and os.getenv("DATABASE_URL", "").startswith(
            ("postgresql://", "postgres://", "postgresql+psycopg://")
        )
    )


@router.get("/admin/nba-research/markets",
            dependencies=[Depends(require_admin)])
def nba_admin_market_research(response: Response):
    """Read signed, private exact NBA bookmaker line observations."""
    if not _nba_market_stage_enabled():
        raise HTTPException(404, "Private NBA market research disabled.")
    from basketball.research_market_store import read_observations
    try:
        result = read_observations()
    except ValueError as exc:
        logger.warning("NBA market snapshot integrity failed: %s", type(exc).__name__)
        raise HTTPException(409, "NBA market observation integrity invalid.") from exc
    except Exception as exc:
        logger.warning("NBA market snapshots unavailable: %s", type(exc).__name__)
        raise HTTPException(503, "NBA market observations unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return result


@router.post("/admin/nba-research/markets/refresh",
             dependencies=[Depends(require_admin)])
def nba_admin_market_refresh(response: Response):
    """Opt-in, read-only SportyBet crawl; persists ONLY private quoted prices."""
    if not _nba_market_stage_enabled():
        raise HTTPException(404, "Private NBA market research disabled.")
    from basketball.research_market_store import capture_observations
    try:
        result = capture_observations()
    except (ValueError, RuntimeError) as exc:
        logger.warning("NBA market source rejected: %s", type(exc).__name__)
        raise HTTPException(409, "No complete verified NBA bookmaker market snapshot.") from exc
    except Exception as exc:
        logger.warning("NBA market source unavailable: %s", type(exc).__name__)
        raise HTTPException(503, "NBA bookmaker market source unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return result


@router.post("/admin/nba-research/forecast",
             dependencies=[Depends(require_admin)])
def nba_admin_forecast_research(response: Response):
    """Research-only signed NBA pregame capture; never publishes a public tip."""
    import os
    enabled = lambda key: os.getenv(key, "").lower() in ("1", "true", "yes", "on")
    if (os.getenv("ENVIRONMENT", "").lower() != "staging"
        or not enabled("NBA_ADMIN_RESEARCH_ENABLED")
        or not enabled("NBA_ADMIN_RESEARCH_FORECAST_ENABLED")
        or not os.getenv("DATABASE_URL", "").startswith((
            "postgresql://", "postgres://", "postgresql+psycopg://"
        ))):
        raise HTTPException(404, "NBA cloud forecast research is disabled.")
    from basketball.research_hosted_forecast import forecast_hosted
    try:
        result = forecast_hosted()
    except ValueError as exc:
        logger.warning("NBA forecast source validation rejected: %s",
                       type(exc).__name__)
        raise HTTPException(409, "NBA cloud forecasts withheld by source validation.") from exc
    except Exception as exc:
        logger.warning("NBA forecast source unavailable: %s",
                       type(exc).__name__)
        raise HTTPException(503, "NBA cloud forecast input unavailable.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return result


@router.post("/admin/nba-research/settle", dependencies=[Depends(require_admin)])
def nba_admin_research_settle(response: Response):
    """Explicit staging-only verified NBA scoreboard settlement.

    Never publishes football, changes forecasts, or creates betting codes.
    Keep disabled until its separate stage flag is set after tests.
    """
    import os
    enabled = lambda key: os.getenv(key, "").lower() in ("1", "true", "yes", "on")
    if (os.getenv("ENVIRONMENT", "").lower() != "staging" or
        not enabled("NBA_ADMIN_RESEARCH_ENABLED") or
        not enabled("NBA_ADMIN_RESEARCH_SETTLE_ENABLED") or
        not os.getenv("DATABASE_URL", "").startswith(("postgresql://", "postgres://",
                                                       "postgresql+psycopg://"))):
        raise HTTPException(404, "Hosted NBA settlement disabled.")
    from basketball.research_hosted_settlement import settle_hosted
    try:
        result = settle_hosted()
    except ValueError as exc:
        logger.warning("NBA hosted settlement validation rejected: %s",
                       type(exc).__name__)
        raise HTTPException(409, "NBA evidence integrity prevented settlement.") from exc
    except Exception as exc:
        logger.warning("NBA hosted settlement unavailable: %s",
                       type(exc).__name__)
        raise HTTPException(503, "NBA score verification unavailable. No result confirmed.") from exc
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return result


@router.post("/internal/nba-research/settle")
def nba_private_cron_settle(request: Request, response: Response):
    """Machine-only staging settlement; requires dedicated 256-bit token.

    Distinct from interactive administrator cookies and disabled in production.
    Never accepts user-supplied fixtures, outcomes, model parameters or stakes.
    """
    import hmac
    import os
    configured = os.getenv("NBA_SETTLEMENT_JOB_TOKEN", "")
    incoming = request.headers.get("x-betsightly-nba-settle-token", "")
    if (os.getenv("ENVIRONMENT", "").lower() != "staging" or
        len(configured) < 32 or not incoming or
        not hmac.compare_digest(configured, incoming)):
        raise HTTPException(404, "Not found.")
    return nba_admin_research_settle(response)


@router.post("/admin/nba-research/import", dependencies=[Depends(require_admin)])
def nba_admin_research_import(request: Request, body: dict = Body(...)):
    """Explicit private import, never a public prediction or betting action."""
    import os
    def enabled(key):
        return os.getenv(key, "").lower() in ("1", "true", "yes", "on")
    if not (enabled("NBA_ADMIN_RESEARCH_ENABLED") and
            enabled("NBA_ADMIN_RESEARCH_IMPORT_ENABLED")):
        raise HTTPException(404, "Private NBA evidence importing is disabled.")
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > 760_000):
        raise HTTPException(413, "NBA research archive exceeds upload limit.")
    from basketball.research_private_store import import_bundle
    try:
        return import_bundle(body)
    except ValueError as exc:
        if "overwrite or delete" in str(exc) or "cannot be rewritten" in str(exc):
            raise HTTPException(409, str(exc)) from exc
        raise HTTPException(422, "NBA research archive failed integrity checks.") from exc
    except Exception as exc:
        logger.warning("NBA private import unavailable: %s",
                       type(exc).__name__)
        raise HTTPException(503, "NBA archive storage unavailable.") from exc
