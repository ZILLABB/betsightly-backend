"""Read-only SportyBet result observations.

This is an experimental source: SportyBet does not publish a supported
developer results API, and its on-site scoreboard is not settlement authority.
Until a verified public football response and usage permission are confirmed,
the observer stays OFF by default. No output from this module may be passed
directly to the official settlement evaluator or model calibration.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)
_BASE = "https://www.sportybet.com"
_PATH = "/api/ng/factsCenter/eventResultList"
_LOCK = threading.Lock()
_LAST_FETCH = 0.0
_HEALTH: dict[str, Any] = {
    "enabled": False, "mode": "shadow_only", "status": "disabled",
    "observed": 0, "matched": 0, "agreements": 0, "disagreements": 0,
    "last_checked_at": None,
}
_FINAL = {"FT", "FULL_TIME", "FULLTIME", "FINISHED", "ENDED",
          "STATUS_FINAL", "STATUS_FULL_TIME"}
_DISALLOWED = {"AET", "AFTER_EXTRA_TIME", "PEN", "PENALTIES",
               "ABANDONED", "POSTPONED", "CANCELLED", "CANCELED", "INTERRUPTED"}
_MAX_DATES = 2
_INTERVAL = 300


def enabled() -> bool:
    return os.getenv("SPORTYBET_RESULTS_SHADOW_ENABLED", "").lower() in ("1", "true", "yes")


def health() -> dict:
    with _LOCK:
        return dict(_HEALTH, enabled=enabled())


def _int_score(v: Any) -> int | None:
    # Do not accept missing or fabricated zeros from incomplete events.
    if isinstance(v, bool) or v is None:
        return None
    try:
        if isinstance(v, float) and not v.is_integer():
            return None
        n = int(str(v))
        return n if 0 <= n <= 99 and str(v).strip() in (str(n), f"{n}.0") else None
    except (ValueError, TypeError):
        return None


def _team_name(ev: dict, side: str) -> str:
    value = ev.get(side + "TeamName") or ev.get(side + "_team")
    if not value:
        t = ev.get(side + "Team") or ev.get(side)
        value = t.get("name") if isinstance(t, dict) else t
    return value.strip() if isinstance(value, str) else ""


def _score_90(ev: dict) -> tuple[int, int] | None:
    # Deliberately use regulation/full-time score, not an ambiguous aggregate
    # that could contain extra-time or penalty shootout goals.
    full = (ev.get("score90") or ev.get("score_90")
            or ev.get("fullTimeScore") or ev.get("full_time_score"))
    if isinstance(full, dict):
        h = _int_score(full.get("home") if "home" in full else full.get("homeScore"))
        a = _int_score(full.get("away") if "away" in full else full.get("awayScore"))
        return (h, a) if h is not None and a is not None else None
    # For a verified FT event with no extra-time indicators, direct score
    # fields can represent regulation play.
    if any(key in ev for key in ("extraTimeScore", "penaltyScore", "extra_time", "penalties")):
        return None
    h = _int_score(ev.get("homeScore"))
    a = _int_score(ev.get("awayScore"))
    return (h, a) if h is not None and a is not None else None


def _date(ev: dict) -> str | None:
    raw = ev.get("estimateStartTime") or ev.get("startTime") or ev.get("kickoff")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            ts = float(raw) / (1000 if float(raw) > 10_000_000_000 else 1)
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            return parsed.astimezone(timezone.utc).date().isoformat()
        except ValueError:
            return None
    return None


def _events(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("bizCode") not in (None, 10000, "10000"):
        return []
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return []
    rows: list[dict] = []
    for field in ("events", "results", "matches"):
        entries = data.get(field)
        if isinstance(entries, list):
            rows.extend(x for x in entries if isinstance(x, dict))
    tournaments = data.get("tournaments")
    if isinstance(tournaments, list):
        for league in tournaments:
            if isinstance(league, dict):
                for field in ("events", "results", "matches"):
                    entries = league.get(field)
                    if isinstance(entries, list):
                        rows.extend(x for x in entries if isinstance(x, dict))
    return rows[:500]


def parse_final(ev: dict) -> dict | None:
    status = ev.get("matchStatus") or ev.get("status") or ev.get("match_status")
    # SportyBet scoreboard field meanings must be validated before adoption.
    if isinstance(status, dict):
        status = status.get("short") or status.get("name")
    status = str(status or "").strip().upper()
    if status in _DISALLOWED or status not in _FINAL:
        return None
    event_id = str(ev.get("eventId") or ev.get("event_id") or "")
    if not event_id.startswith("sr:match:"):
        return None
    home, away = _team_name(ev, "home"), _team_name(ev, "away")
    match_date = _date(ev)
    score = _score_90(ev)
    if not (home and away and match_date and score is not None):
        return None
    return {
        "event_id": event_id, "home_team": home, "away_team": away,
        "date": match_date, "home_score": score[0], "away_score": score[1],
        "status": status, "source": "sportybet_unverified_shadow",
    }


def reconcile(picks: list[dict], rows: list[dict], verified: dict,
              *, normalize=None, lookup=None) -> dict:
    """Compare observations to official feed; NEVER mutate it.

    Require exact SportyBet event ID, BOTH team names and kickoff UTC date.
    This excludes lookalike reserve/youth/rematch events.
    """
    if normalize is None or lookup is None:
        from leagues.results_checker import _normalize_name, _lookup_score
        normalize = normalize or _normalize_name
        lookup = lookup or _lookup_score
    indexed: dict[str, list[dict]] = {}
    for ev in rows:
        item = parse_final(ev)
        if item:
            indexed.setdefault(item["event_id"], []).append(item)
    matched = agreements = disagreements = 0
    samples = []
    for p in picks:
        event_id = str(p.get("sportybet_event_id")
                       or (p.get("sportybet_availability") or {}).get("event_id") or "")
        kickoff = p.get("commence_time") or p.get("kickoff") or p.get("date") or ""
        try:
            dt = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
            date = dt.astimezone(timezone.utc).date().isoformat() if dt.tzinfo else None
        except ValueError:
            date = None
        if not (event_id and date):
            continue
        candidates = [r for r in indexed.get(event_id, []) if
                      r["date"] == date and
                      normalize(r["home_team"]) == normalize(p.get("home_team") or "") and
                      normalize(r["away_team"]) == normalize(p.get("away_team") or "")]
        if len(candidates) != 1:
            continue
        match = candidates[0]
        matched += 1
        official = lookup(verified, p.get("home_team") or "",
                          p.get("away_team") or "", date)
        if official and not official.get("ambiguous"):
            agreement = (official.get("home_score"), official.get("away_score")) == (
                match["home_score"], match["away_score"])
            agreements += int(agreement)
            disagreements += int(not agreement)
            if not agreement and len(samples) < 5:
                samples.append(event_id)
    return {"observed": sum(len(v) for v in indexed.values()),
            "matched": matched, "agreements": agreements,
            "disagreements": disagreements, "disagreement_event_ids": samples}


def observe(picks: list[dict], verified: dict) -> dict:
    """Opt-in, rate-limited GETs only. Inaccessible/changed endpoints fail closed."""
    global _LAST_FETCH
    if not enabled():
        return health()
    now = time.monotonic()
    with _LOCK:
        if _LAST_FETCH and now - _LAST_FETCH < _INTERVAL:
            return dict(_HEALTH)
        _LAST_FETCH = now
    dates = sorted({str(p.get("commence_time") or p.get("kickoff") or
                        p.get("date") or "")[:10] for p in picks})
    dates = [d for d in dates if len(d) == 10][- _MAX_DATES:]
    rows: list[dict] = []
    status = "no_verified_response"
    try:
        for day in dates:
            response = requests.get(
                _BASE + _PATH,
                params={"sportId": "sr:sport:1", "date": day,
                        "pageNum": 1, "pageSize": 100},
                headers={"Accept": "application/json"}, timeout=8)
            if response.status_code != 200:
                status = "http_" + str(response.status_code)
                break
            obj = response.json()
            if not isinstance(obj, dict) or obj.get("bizCode") not in (10000, "10000"):
                status = "unverified_payload"
                break
            rows.extend(_events(obj))
            status = "read_only_observation"
        report = reconcile(picks, rows, verified)
        report["status"] = status
    except (requests.RequestException, ValueError, TypeError) as exc:
        report = {"status": "source_unavailable:" + type(exc).__name__,
                  "observed": 0, "matched": 0,
                  "agreements": 0, "disagreements": 0, "disagreement_event_ids": []}
    with _LOCK:
        _HEALTH.update(report)
        _HEALTH["last_checked_at"] = datetime.now(timezone.utc).isoformat()
    if report.get("disagreements"):
        logger.warning("SportyBet shadow disagreement count=%s, event_ids=%s",
                       report["disagreements"], report["disagreement_event_ids"])
    else:
        logger.info("SportyBet shadow result probe status=%s matched=%s",
                    report["status"], report["matched"])
    return dict(report, enabled=True, mode="shadow_only")
