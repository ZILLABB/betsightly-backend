"""Read-only Jev research dashboard for the authenticated BetSightly admin.

Never exposes API keys, source article text, individual betting picks or a
button that could trigger a billable evaluation. No database table is created
when the admin opens the page. All publisher actions remain unchanged.
"""
from __future__ import annotations

from html import escape
from os import environ


def research_status() -> dict:
    from leagues.jev_shadow_decision import runtime_status
    from basketball.jev_research_evidence import basketball_research_status
    from leagues.jev_shadow_ledger import summary
    gateway = runtime_status()
    try:
        audits = summary()
    except Exception:
        audits = {"status": "unavailable", "total": None}
    source_enabled = str(environ.get(
        "BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED", "")).lower() in {
            "1", "true", "yes",
        }
    auto_discovery = str(environ.get(
        "BETSIGHTLY_JEV_SOURCE_AUTODISCOVER", "")).lower() in {
            "1", "true", "yes",
        }
    return {
        "status": "research_only",
        "shadow_only": True,
        "publication_authority": False,
        "provider": gateway,
        "audits": audits,
        "external_sources": {
            "openligadb_adapter_present": True,
            "openligadb_fetch_enabled": source_enabled,
            "matchday_auto_discovery_enabled": auto_discovery,
            "verified_live_match_count": None,
            "injuries_feed_approved": False,
            "lineups_feed_approved": False,
            "external_analyst_feed_approved": False,
        },
        "basketball": basketball_research_status(),
        "bookmaker_codes_changed": False,
        "official_settlements_changed": False,
        "controlled_publication_gating_enabled": False,
    }


def render_desk(status: dict) -> str:
    """One protected, Atlantic-styled, static monitoring view."""
    provider = status.get("provider") or {}
    audits = status.get("audits") or {}
    source = status.get("external_sources") or {}
    basket = status.get("basketball") or {}
    def val(value):
        return escape(str(value if value is not None else "not verified"),
                      quote=True)
    def section(label, value, detail):
        return (f'<article class="panel"><span class="label">{val(label)}</span>'
                f'<strong>{val(value)}</strong><p>{val(detail)}</p></article>')
    cards = "".join([
        section("Jev gateway", provider.get("status", "not configured"),
                "Production Gateway evaluations remain disabled. No secret is shown."),
        section("Research audits", audits.get("total", 0),
                "Only immutable, before-kickoff, evidence-versioned audit records."),
        section("External sources",
                "configured" if source.get("openligadb_fetch_enabled")
                else "off by default",
                "OpenLigaDB German league adapter. Live match coverage is not yet certified."),
        section("Private basketball", basket.get("NBA", "unverified"),
                "NBA paper research is separated from public football and betting."),
        section("Published predictions", "UNCHANGED",
                "Jev cannot alter tickets, create codes or settle games."),
        section("Source health checks",
                "not yet certified",
                "Official injuries, lineups, analyst opinions and real-world provider uptime."),
    ])
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>BetSightly Jev Research — Command Center</title>
<style>
:root{color-scheme:dark;--bg:#0B2238;--panel:#1A354A;--line:#35546D;
--fg:#F5F9FC;--muted:#C4D5E2;--brand:#69B0D6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font-family:Inter,system-ui,sans-serif;line-height:1.55}
main{max-width:1080px;padding:28px 20px 60px;margin:auto}
a{color:var(--brand)}header{display:flex;justify-content:space-between;
align-items:center;flex-wrap:wrap;gap:14px;padding-bottom:25px}
h1{font-size:clamp(25px,4vw,36px);margin:0 0 8px}
p{color:var(--muted)}.eyebrow{color:var(--brand);font-size:12px;
text-transform:uppercase;letter-spacing:.12em;font-weight:750}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;
padding:20px;min-height:160px}.panel strong{display:block;font-size:19px;
overflow-wrap:anywhere;margin:12px 0}.panel p{font-size:13px;margin:0}
.label{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.note{padding:18px;background:#203E55;border-left:3px solid var(--brand);
border-radius:9px;margin:20px 0;color:var(--muted)}
footer{margin-top:24px;color:var(--muted);font-size:13px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style></head><body><main><header><div><span class="eyebrow">BetSightly Command Center / Protected research</span>
<h1>Jev External Intelligence</h1><p>Source readiness, model audit volume and publication safety.</p></div>
<a href="/admin">Back to Command Center</a></header>
<div class="note">Research-only. A Jev judgment is not a match-win probability.
No public betting changes, automatic approvals, code generation or result settlement are authorized.</div>
<div class="grid">""" + cards + """</div>
<footer>Provider and data coverage are not certified until a real staging evaluation,
source reconciliation and independently verified settlements are completed.
<a href="/api/growth/jev-research/status">View protected JSON diagnostics</a>.</footer>
</main></body></html>"""
