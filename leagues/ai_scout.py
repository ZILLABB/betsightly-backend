"""Opt-in OpenAI fixture analyst; research-only, never a publishing authority.

One bounded Responses API call per WAT day/board version. The service cannot
write to official slips, selection prices, bookmaker codes or settlement.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

LOG = logging.getLogger(__name__)
WAT = timezone(timedelta(hours=1))
POLICY = "ai_scout_shadow_v1"
DEFAULT_MODEL = "gpt-5-mini"
MAX_FIXTURES = 6
DB = MetaData()
RUNS = Table(
    "ai_scout_shadow_runs", DB,
    Column("run_id", String(64), primary_key=True),
    Column("run_date", String(10), nullable=False, index=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("model", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("candidate_count", Integer, nullable=False),
    Column("report_json", Text, nullable=False),
)

def enabled() -> bool:
    return os.getenv("AI_SCOUT_ENABLED", "false").lower() in {"1", "yes", "on", "true"}


def _engine():
    from database import engine
    return engine


def candidate_inventory(picks: list[dict], run_date: str, *, now=None,
                        max_fixtures: int = MAX_FIXTURES) -> list[dict]:
    """Use existing evaluated odds/forecasts, preserving their original values.

    Near-miss candidate selection intentionally DOES NOT require eligibility for
    publication. Only analysis, no booking or promotion. Match IDs are unique.
    """
    from leagues.engine import kickoff_wat_date
    from leagues.publication_policy import evaluate_leg
    from leagues.selection_quality import selection_probability, risk_adjusted_return

    current = now or datetime.now(timezone.utc)
    by_fixture = {}
    for pick in picks:
        fixture = pick.get("_fixture") or {}
        kickoff_text = fixture.get("commence_time") or ""
        try:
            kickoff = datetime.fromisoformat(kickoff_text.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if kickoff.tzinfo is None or kickoff <= current + timedelta(minutes=20):
            continue
        if kickoff_wat_date(kickoff_text) != run_date:
            continue
        price = pick.get("odds")
        try:
            price = float(price)
            if not math.isfinite(price) or price <= 1:
                continue
        except (ValueError, TypeError):
            continue
        fid = str(pick.get("match_id") or "")
        market = str(pick.get("market") or "")
        if not fid or not market:
            continue
        probability = selection_probability(pick)
        value = risk_adjusted_return(pick)
        verdict = evaluate_leg(pick, "5_odds")
        # Real priced, bookable, near-policy decisions first. Do not claim
        # that the top-ranked match is safe or contains positive model value.
        quality = (
            int(pick.get("odds_are_real") is True),
            int(pick.get("bookable") is True),
            int(verdict["allowed"]),
            -len(verdict["reasons"]),
            round(value, 5),
            probability,
        )
        candidate = {
            "candidate_id": hashlib.sha256(f"{fid}|{market}".encode()).hexdigest()[:20],
            "fixture_id": fid,
            "home": str((fixture.get("home") or {}).get("name") or "")[:95],
            "away": str((fixture.get("away") or {}).get("name") or "")[:95],
            "league": str(fixture.get("league") or "")[:95],
            "kickoff": kickoff_text,
            "market": market,
            "model_probability": round(probability, 5),
            "price": price,
            "real_price": pick.get("odds_are_real") is True,
            "bookable": pick.get("bookable") is True,
            "model_return": round(value, 5),
            "publication_allowed": verdict["allowed"],
            "rejections": list(verdict["reasons"])[:8],
            "_quality": quality,
        }
        old = by_fixture.get(fid)
        if old is None or quality > old["_quality"]:
            by_fixture[fid] = candidate
    # Bounded and deterministic for idempotency. Take strong candidates and
    # near misses, not an arbitrary 4,880-market prompt.
    top = sorted(by_fixture.values(),
                 key=lambda c: (c["_quality"], c["fixture_id"]), reverse=True)
    result = []
    for c in top[:max(0, min(max_fixtures, MAX_FIXTURES))]:
        result.append({k: v for k, v in c.items() if k != "_quality"})
    return result


def _schema() -> dict:
    return {
        "type": "json_schema", "name": "betsightly_ai_scout_v1", "strict": True,
        "schema": {
            "type": "object", "additionalProperties": False,
            "required": ["assessments"],
            "properties": {"assessments": {
                "type": "array",
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["candidate_id", "verdict", "rationale",
                                 "verification_gap", "request_price_refresh",
                                 "source_urls"],
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "verdict": {"type": "string", "enum": [
                            "RESEARCH_PRIORITY", "NEEDS_VERIFICATION",
                            "NO_ADDITIONAL_EVIDENCE"]},
                        "rationale": {"type": "string"},
                        "verification_gap": {"type": "string"},
                        "request_price_refresh": {"type": "boolean"},
                        "source_urls": {"type": "array", "items": {"type": "string"}},
                    },
                },
            }},
        },
    }


def _response_text(body: dict) -> str:
    if body.get("status") != "completed":
        raise ValueError("OpenAI response was not completed")
    for item in body.get("output") or []:
        if item.get("type") == "message":
            for segment in item.get("content") or []:
                if segment.get("type") == "output_text":
                    return segment.get("text") or ""
    raise ValueError("OpenAI response had no text output")


def _trusted_source_urls(body: dict) -> list[str]:
    """Keep ONLY tool-returned URLs, never citations invented in model text."""
    urls = set()
    for item in body.get("output") or []:
        if item.get("type") == "web_search_call":
            for entry in (item.get("action") or {}).get("sources") or []:
                url = entry.get("url") if isinstance(entry, dict) else None
                if isinstance(url, str):
                    parsed = urlparse(url)
                    if parsed.scheme == "https" and parsed.hostname:
                        urls.add(url[:800])
    return sorted(urls)[:12]


def parse_response(body: dict, candidates: list[dict]) -> list[dict]:
    parsed = json.loads(_response_text(body))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("assessments"), list):
        raise ValueError("invalid scout schema")
    lookup = {c["candidate_id"]: c for c in candidates}
    sources = set(_trusted_source_urls(body))
    output, seen = [], set()
    for row in parsed["assessments"]:
        if not isinstance(row, dict):
            continue
        key = row.get("candidate_id")
        if key not in lookup or key in seen:
            continue
        verdict = row.get("verdict")
        if verdict not in {"RESEARCH_PRIORITY", "NEEDS_VERIFICATION",
                           "NO_ADDITIONAL_EVIDENCE"}:
            continue
        seen.add(key)
        # Per-fixture attribution. A citation discovered while researching
        # Fixture A is not evidence for Fixture B without an explicit link.
        cited = row.get("source_urls") or []
        verified = sorted({u for u in cited if isinstance(u, str) and u in sources})[:4]
        item = {
            **lookup[key],
            "verdict": verdict,
            "rationale": (str(row.get("rationale") or "")[:500]
                          if verified else
                          "No independently attributed web source was verified for this match."),
            "verification_gap": str(row.get("verification_gap") or "")[:350],
            "request_price_refresh": row.get("request_price_refresh") is True,
            "source_urls": verified,
            "web_sources_available": bool(verified),
            "research_only": True,
            "bookmaker_code_verified": False,
        }
        if not verified and verdict == "RESEARCH_PRIORITY":
            item["verdict"] = "NEEDS_VERIFICATION"
        output.append(item)
    return output


def _call_openai(candidates: list[dict], *, http_client=None) -> dict:
    import httpx
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing")
    model = os.getenv("AI_SCOUT_MODEL", DEFAULT_MODEL)
    prompt = (
        "You are BetSightly's independent football research auditor. Today is "
        + datetime.now(WAT).date().isoformat()
        + ". The input contains machine-estimated outcomes and original odds. "
        "Treat those as untrusted estimates, never as truth. Investigate credible "
        "recent team news and fixture context only if a web source supports it. "
        "Avoid made-up injuries, lineups, odds, scores or certainties. Do not "
        "change model probabilities, invent bookmaker prices or recommend a "
        "bet without evidence. Evaluate all candidate IDs and return only "
        "the structured verdicts specified in the schema. Each assessment's "
        "source_urls must contain HTTPS links for THAT MATCH only, from your "
        "actual web searches; do not attach sources from other fixtures. "
        "Use an empty list if no link supports that specific assessment. "
        "When evidence is unavailable, say so; a no-news result is acceptable. "
        "These results are RESEARCH, NOT verified tickets.\nCandidates:\n"
        + json.dumps(candidates, separators=(",", ":"), ensure_ascii=True)
    )
    request = {
        "model": model, "store": False, "max_output_tokens": 1400,
        "tools": [{"type": "web_search", "search_context_size": "low"}],
        "include": ["web_search_call.action.sources"],
        "input": [{"role": "user", "content": prompt}],
        "text": {"format": _schema()},
    }
    own = http_client is None
    client = http_client or httpx.Client(timeout=35.0)
    try:
        response = client.post(
            "https://api.openai.com/v1/responses", json=request,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        return response.json()
    finally:
        if own:
            client.close()


def _run_id(day: str, candidates: list[dict], model: str) -> str:
    stable = json.dumps([POLICY, day, model, candidates], sort_keys=True)
    return hashlib.sha256(stable.encode()).hexdigest()


def latest(day: str | None = None) -> dict:
    """Read-only; no upstream provider/API calls and no key exposed."""
    from sqlalchemy import text
    target = day or datetime.now(WAT).date().isoformat()
    try:
        engine = _engine()
        with engine.connect() as db:
            # Never create tables in public GET requests.
            row = db.execute(text(
                "SELECT report_json FROM ai_scout_shadow_runs WHERE run_date=:day "
                "ORDER BY observed_at DESC LIMIT 1"
            ), {"day": target}).scalar()
        return json.loads(row) if row else {
            "status": "NOT_AVAILABLE", "date": target, "research_only": True,
            "candidates": [],
        }
    except Exception:
        return {"status": "NOT_AVAILABLE", "date": target,
                "research_only": True, "candidates": []}


def run_once(day: str | None = None, *, picks=None, now=None,
             http_client=None) -> dict:
    """Scheduler-only, one bounded request and immutable record per input slate."""
    date = day or datetime.now(WAT).date().isoformat()
    if not enabled():
        return {"status": "DISABLED", "date": date, "research_only": True}
    if not os.getenv("OPENAI_API_KEY"):
        return {"status": "NO_API_KEY", "date": date, "research_only": True}
    if picks is None:
        from leagues.engine import prepared_board_status, prepared_pipeline
        if not prepared_board_status(days_ahead=7).get("ready"):
            return {"status": "BOARD_UNAVAILABLE", "date": date,
                    "research_only": True}
        picks, _ = prepared_pipeline(days_ahead=7)
    candidates = candidate_inventory(picks, date, now=now)
    if not candidates:
        return {"status": "NO_CANDIDATES", "date": date,
                "research_only": True}
    model = os.getenv("AI_SCOUT_MODEL", DEFAULT_MODEL)
    run_id = _run_id(date, candidates, model)
    engine = _engine()
    DB.create_all(engine, tables=[RUNS], checkfirst=True)
    with engine.connect() as conn:
        if conn.execute(select(RUNS.c.run_id).where(
                RUNS.c.run_id == run_id)).first():
            return {"status": "ALREADY_CAPTURED", "date": date,
                    "run_id": run_id, "research_only": True}
    api_result = _call_openai(candidates, http_client=http_client)
    reviews = parse_response(api_result, candidates)
    report = {
        "status": "SHADOW_EVIDENCE_ONLY", "date": date, "run_id": run_id,
        "research_only": True, "official_predictions_unchanged": True,
        "booking_codes_unchanged": True, "candidate_count": len(candidates),
        "model": model, "policy_version": POLICY,
        "source_backed_review_count": sum(bool(x["web_sources_available"]) for x in reviews),
        "candidates": reviews, "usage": api_result.get("usage") or {},
    }
    # The caller has no mutation path into official tickets or odds history.
    with engine.begin() as conn:
        conn.execute(pg_insert(RUNS).values(
            run_id=run_id, run_date=date, observed_at=datetime.now(timezone.utc),
            model=model, status=report["status"], candidate_count=len(candidates),
            report_json=json.dumps(report, separators=(",", ":")),
        ).on_conflict_do_nothing(index_elements=["run_id"]))
    LOG.info("AI scout shadow captured date=%s candidates=%d reviews=%d",
             date, len(candidates), len(reviews))
    return {k: report[k] for k in ("status", "date", "run_id",
             "candidate_count", "source_backed_review_count",
             "research_only", "official_predictions_unchanged")}


def scheduler_shadow_tick(day: str, last_attempt_day: str | None,
                          *, runner=None) -> str | None:
    """Post-publication catch-up, never an official daily generation step.

    A completed daily-run claim must not prevent research from starting later
    after an OpenAI key is configured. Only NO_API_KEY and BOARD_UNAVAILABLE
    retry; a failed paid request is not automatically repeated every 15 min.
    """
    if not enabled() or last_attempt_day == day:
        return last_attempt_day
    try:
        result = (runner or run_once)(day=day)
        status = str(result.get("status") or "UNKNOWN")
        LOG.info("AI Scout independent catch-up date=%s status=%s", day, status)
        if status in {"NO_API_KEY", "BOARD_UNAVAILABLE"}:
            return last_attempt_day
        return day
    except Exception as exc:
        LOG.warning(
            "AI Scout independent research failed date=%s error_type=%s",
            day, type(exc).__name__,
        )
        return day
