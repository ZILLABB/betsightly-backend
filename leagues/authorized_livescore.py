"""Opt-in LiveScore consumer-CDN observations for the BetSightly score display.

IMPORTANT: the CDN has no published data licence for BetSightly. Set both
LIVESCORE_CDN_ENABLED=true and LIVESCORE_CDN_USAGE_AUTHORIZED=true *only after*
obtaining permission for commercial automated access. No auth bypass, retries,
proxy rotation or browser impersonation. Never use observations for settlement,
model accuracy, Telegram official results or bookmaker booking.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging
import os
import re
import threading
import time

import requests

logger = logging.getLogger(__name__)
_DATE_URL = "https://prod-cdn-public-api.livescore.com/v1/api/app/date/soccer/{date}/0"
_LIVE_URL = "https://prod-cdn-mev-api.livescore.com/v1/api/app/live/soccer/1"
_LOCK = threading.RLock()
_CACHE: dict = {"status": "disabled", "matches": [], "fetched_at": None}
_LAST_FETCH = 0.0
_TTL_SECONDS = 120
_SCORE = re.compile(r"^\d{1,2}$")
_KICKOFF = re.compile(r"^\d{14}$")
_LIVE_PERIOD = re.compile(r"^(?:\d{1,3}(?:\+\d{1,2})?['′]?)$")


def enabled() -> bool:
    return (os.getenv("LIVESCORE_CDN_ENABLED", "").lower() in {"true", "1", "yes"}
            and os.getenv("LIVESCORE_CDN_USAGE_AUTHORIZED", "").lower()
            in {"true", "1", "yes"})


def _score(raw) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return None
    value = str(raw)
    return int(value) if _SCORE.fullmatch(value) else None


def _team(raw) -> str:
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        return ""
    name = raw[0].get("Nm")
    return name.strip()[:120] if isinstance(name, str) else ""


def _parse_event(event: dict, league: str = "") -> dict | None:
    if not isinstance(event, dict):
        return None
    identifier = str(event.get("Eid") or "")
    if not identifier.isdigit() or len(identifier) > 18:
        return None
    home, away = _team(event.get("T1")), _team(event.get("T2"))
    if not home or not away:
        return None
    raw_date = str(event.get("Esd") or "")
    if not _KICKOFF.fullmatch(raw_date):
        return None
    try:
        kickoff = datetime.strptime(raw_date, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    phase = str(event.get("Eps") or "").strip().upper()
    try:
        esid = int(event.get("Esid"))
        epr = int(event.get("Epr"))
    except (ValueError, TypeError):
        return None
    # Only explicit, understood states may appear on the live scoreboard.
    # Ambiguous abandoned / delayed / penalties flags cannot make a fixture FT.
    finished = esid == 6 and epr == 2 and phase in {"FT", "FULL TIME"}
    live = epr == 1 and (esid in {2, 3, 10} or bool(_LIVE_PERIOD.fullmatch(phase)))
    pre = epr == 0 and esid == 1
    if not (finished or live or pre):
        return None
    hs, as_ = _score(event.get("Tr1")), _score(event.get("Tr2"))
    if not pre and (hs is None or as_ is None):
        return None
    # Keep FT marked as "reported", not independently verified. Tr1OR/Tr2OR
    # are carried for display diagnostics only. No bookmaker grading.
    return {
        "provider_event_id": identifier,
        "home_team": home, "away_team": away,
        "kickoff_utc": kickoff.isoformat(),
        "date": kickoff.date().isoformat(),
        "league": league[:120],
        "home_score": hs, "away_score": as_,
        "regulation_home_score": _score(event.get("Tr1OR")),
        "regulation_away_score": _score(event.get("Tr2OR")),
        "half_home_score": _score(event.get("Trh1")),
        "half_away_score": _score(event.get("Trh2")),
        "clock": phase if live else None,
        "detail": phase or None,
        "state": "post" if finished else "in" if live else "pre",
        "state_label": "finished (unverified)" if finished else "live" if live else "not started",
        "finished": finished, "live": live,
        "source": "livescore-cdn",
        "provisional": True, "score_verified": False,
    }


def parse_payload(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("Stages"), list):
        raise ValueError("unexpected_livescore_payload")
    indexed: dict[str, list[dict]] = defaultdict(list)
    for stage in payload["Stages"][:500]:
        if not isinstance(stage, dict):
            continue
        stage_name = str(stage.get("Snm") or stage.get("Cnm") or "")
        events = stage.get("Events")
        if not isinstance(events, list):
            continue
        for ev in events[:200]:
            parsed = _parse_event(ev, stage_name)
            if parsed:
                indexed[parsed["provider_event_id"]].append(parsed)
    # Repeated IDs with conflicting score or identity must not be guessed.
    out = []
    for rows in indexed.values():
        first = rows[0]
        if all(
            (row["home_team"], row["away_team"], row["kickoff_utc"], row["home_score"],
             row["away_score"], row["state"])
            == (first["home_team"], first["away_team"], first["kickoff_utc"],
                first["home_score"], first["away_score"], first["state"])
            for row in rows[1:]
        ):
            out.append(first)
    return out


def merge_live_rows(dated: list[dict], live: list[dict]) -> list[dict]:
    """Newer in-play data may replace same-event dated snapshot, never FT."""
    by_id = {row["provider_event_id"]: row for row in dated}
    for row in live:
        old = by_id.get(row["provider_event_id"])
        if old and ((old["home_team"], old["away_team"], old["kickoff_utc"])
                    != (row["home_team"], row["away_team"], row["kickoff_utc"])):
            by_id.pop(row["provider_event_id"], None)
            continue
        if row["live"] and not (old and old["finished"]):
            by_id[row["provider_event_id"]] = row
    return list(by_id.values())


def snapshot(dates: list[str]) -> dict:
    """Single-flight, bounded set of scoreboard observations, display only."""
    global _LAST_FETCH
    if not enabled():
        return {"status": "disabled", "matches": [], "fetched_at": None}
    requested = []
    for d in sorted(set(dates)):
        try:
            parsed = datetime.strptime(d, "%Y-%m-%d")
            if parsed.strftime("%Y-%m-%d") == d:
                requested.append(d.replace("-", ""))
        except (ValueError, TypeError):
            continue
    if not requested or len(requested) > 3:
        return {"status": "invalid_date_window", "matches": [], "fetched_at": None}
    with _LOCK:
        now = time.monotonic()
        key = tuple(requested)
        if _LAST_FETCH and now - _LAST_FETCH < _TTL_SECONDS and _CACHE.get("dates") == key:
            return dict(_CACHE)
        _LAST_FETCH = now  # throttle even after failed requests
        observed = []
        failed = 0
        for d in requested:
            try:
                resp = requests.get(
                    _DATE_URL.format(date=d),
                    params={"locale": "en"}, timeout=8,
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    failed += 1
                    continue
                observed.extend(parse_payload(resp.json()))
            except (requests.RequestException, ValueError, TypeError):
                failed += 1
        # Live snapshot is useful only for today's feed, never a final archive.
        try:
            resp = requests.get(
                _LIVE_URL, params={"countryCode": "NG", "locale": "en"},
                headers={"Accept": "application/json"}, timeout=8,
            )
            current = parse_payload(resp.json()) if resp.status_code == 200 else []
            observed = merge_live_rows(observed, current)
        except (requests.RequestException, ValueError, TypeError):
            pass
        if failed == len(requested):
            result = {"status": "unavailable", "matches": [],
                      "fetched_at": datetime.now(timezone.utc).isoformat(),
                      "dates": key}
        else:
            result = {"status": "partial" if failed else "ok",
                      "matches": observed,
                      "fetched_at": datetime.now(timezone.utc).isoformat(),
                      "dates": key}
        _CACHE.clear()
        _CACHE.update(result)
        return dict(result)


def overlay(scores: dict, games: list[dict], observations: list[dict]) -> tuple[dict, int]:
    """Only unique exact-team + near-kickoff event joins are displayed.

    Dates are normalized to UTC; home/away cannot be reversed, and the same
    event cannot be assigned to two published fixture IDs.
    """
    from leagues.results_checker import _normalize_name

    def when(raw):
        try:
            parsed = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
        except (ValueError, TypeError, OverflowError):
            return None

    # Deduplicate games by their published immutable ID, but never permit
    # different fixture identities to claim the same external event.
    unique: dict[str, dict] = {}
    for g in games:
        if isinstance(g, dict) and g.get("match_id"):
            unique.setdefault(str(g["match_id"]), g)
    proposed: dict[str, list[dict]] = {}
    for mid, game in unique.items():
        if mid in scores and isinstance(scores[mid], dict):
            existing = scores[mid]
            if existing.get("live") or existing.get("finished"):
                continue
        home = _normalize_name(game.get("home_team", ""))
        away = _normalize_name(game.get("away_team", ""))
        date = when(game.get("kickoff") or game.get("commence_time") or game.get("date"))
        if not home or not away or date is None:
            continue
        candidates = []
        for ev in observations:
            event_date = when(ev.get("kickoff_utc"))
            if (event_date is not None
                and abs((event_date - date).total_seconds()) <= 20 * 60
                and _normalize_name(ev.get("home_team", "")) == home
                and _normalize_name(ev.get("away_team", "")) == away
                and ev.get("provisional") is True
                and (ev.get("live") or ev.get("finished"))):
                candidates.append(ev)
        if len(candidates) == 1:
            proposed[mid] = candidates

    claims: dict[str, int] = defaultdict(int)
    for row in proposed.values():
        claims[row[0]["provider_event_id"]] += 1
    out = dict(scores)
    attached = 0
    for mid, selected in proposed.items():
        event = selected[0]
        if claims[event["provider_event_id"]] != 1:
            continue
        # Never overwrite a result already reported by ESPN as FT/in-play.
        out[mid] = dict(event, match_id=mid, identity_match="teams_and_kickoff")
        attached += 1
    return out, attached
