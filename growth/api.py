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


# ── Public: tracking beacon ────────────────────────────────

@public_router.post("/track")
async def track(request: Request, payload: dict = Body(default={})):
    """Record an attributed event. Always returns 200.

    Analytics must never be able to break a page, so every failure path here
    is a quiet no-op rather than an error the frontend has to handle.
    """
    try:
        from growth import analytics
        from growth.models import ensure_tables

        ensure_tables()
        fwd = request.headers.get("x-forwarded-for", "")
        ip = fwd.split(",")[0].strip() if fwd else (
            request.client.host if request.client else "")

        analytics.record(
            event_type=str(payload.get("event") or "pageview"),
            path=payload.get("path"),
            source=payload.get("utm_source"),
            medium=payload.get("utm_medium"),
            campaign=payload.get("utm_campaign"),
            content_tag=payload.get("content_tag") or payload.get("utm_content"),
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
            country=request.headers.get("x-vercel-ip-country") or payload.get("country"),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
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
