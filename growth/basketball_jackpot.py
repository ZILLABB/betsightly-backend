"""Admin-only basketball SportyBet exact-selection desk.

No basketball model, football market mapper, staking, or public publication.
Never return a booking code until the complete ticket passes share-code readback.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from datetime import datetime, timezone

from leagues import sportybet
from leagues import booking

CACHE_KEY = "sportybet_basketball_board"
SCHEMA = 1
SPORT_ID = "sr:sport:2"
MARKET_IDS = ("219", "225")
PAGE_SIZE = 100
MAX_PAGES = 10
CACHE_AGE = 3 * 3600
KICKOFF_BUFFER = 10 * 60
MAX_LEGS = 50


def _active(value) -> bool:
    return value not in (False, 0, "0", "false", "False")


def _parse_event(raw: dict, league: str) -> dict | None:
    home, away = raw.get("homeTeamName"), raw.get("awayTeamName")
    event_id = str(raw.get("eventId") or "")
    try:
        kickoff = int(raw.get("estimateStartTime"))
    except (ValueError, TypeError):
        return None
    if not home or not away or not event_id.startswith("sr:match:") or kickoff <= 0:
        return None
    markets = []
    for market in raw.get("markets") or []:
        mid = str(market.get("id") or "")
        if mid not in MARKET_IDS:
            continue
        spec = str(market.get("specifier") or "")
        # Basketball point lines must be exact, never inferred or substituted.
        if mid == "225" and not re.fullmatch(r"total=\d+(?:\.\d+)?", spec):
            continue
        if mid == "219" and spec:
            continue
        outcomes = []
        for outcome in market.get("outcomes") or []:
            oid = str(outcome.get("id") or "")
            if (mid == "219" and oid not in {"4", "5"}) or (
                    mid == "225" and oid not in {"12", "13"}):
                continue
            try:
                price = float(outcome.get("odds"))
            except (ValueError, TypeError):
                continue
            if not math.isfinite(price) or price <= 1 or not _active(outcome.get("isActive", True)):
                continue
            # Keep bookmaker outcome IDs. Their IDs, not human-readable labels,
            # identify exactly what is sent to the share endpoint.
            title = (home if oid == "4" else away) if mid == "219" else (
                "Over " + spec[6:] if oid == "12" else "Under " + spec[6:])
            outcomes.append({"outcome_id": oid, "label": title,
                             "odds": round(price, 3)})
        if outcomes:
            markets.append({"market_id": mid, "specifier": spec,
                            "label": "Winner incl. OT" if mid == "219" else "Total points incl. OT",
                            "outcomes": outcomes})
    return {"event_id": event_id, "home_team": str(home),
            "away_team": str(away), "competition": league,
            "kickoff_ms": kickoff, "markets": markets}


def _valid_cached(cached, *, now: float | None = None) -> bool:
    if not isinstance(cached, dict):
        return False
    meta = cached.get("metadata") or {}
    try:
        age = (time.time() if now is None else now) - float(cached["fetched_at"])
    except (ValueError, TypeError, KeyError):
        return False
    return bool(meta.get("is_complete") is True
                and meta.get("schema") == SCHEMA
                and cached.get("fixtures")
                and -60 <= age <= CACHE_AGE)


def cached_board() -> dict | None:
    cached = sportybet._db_get(CACHE_KEY)
    return cached if _valid_cached(cached) else None


def refresh_board() -> dict:
    """Read the real SportyBet basketball board; promote complete crawls only."""
    fixtures = []
    seen = set()
    declared = None
    counted = 0
    pages = 0
    error = None
    try:
        for page in range(1, MAX_PAGES + 1):
            url = (f"{sportybet.BASE_URL}/api/ng/factsCenter/pcUpcomingEvents"
                   f"?sportId=sr%3Asport%3A2&marketId=219%2C225"
                   f"&pageSize={PAGE_SIZE}&pageNum={page}")
            response = sportybet._get_json(url, timeout=20)
            if response.get("bizCode") not in (None, 10000):
                raise ValueError("SportyBet basketball provider rejected the board request")
            data = response.get("data") or {}
            if declared is None:
                declared = int(data.get("totalNum") or 0)
                if declared <= 0 or declared > MAX_PAGES * PAGE_SIZE:
                    raise ValueError("Invalid basketball board total or page limit exceeded")
            tournaments = data.get("tournaments") or []
            if not tournaments:
                break
            pages = page
            for tournament in tournaments:
                # Pre-match basketball only; reject simulated, cyber and e-sport feeds.
                identity = (str(tournament.get("name") or "") + " " +
                            str(tournament.get("categoryName") or ""))
                if re.search("ebasketball|e-basketball|virtual|cyber|esport|simulated", identity, re.I):
                    # Filter only the presentation, not the pagination count.
                    for item in tournament.get("events") or []:
                        counted += 1
                        if not item.get("eventId"):
                            raise ValueError("Basketball feed contains an unidentified event")
                        seen.add(str(item["eventId"]))
                    continue
                for item in tournament.get("events") or []:
                    counted += 1
                    entry = _parse_event(item, str(tournament.get("name") or "Basketball"))
                    if entry is None:
                        raise ValueError("Unparsable basketball event; board not complete")
                    if entry["event_id"] in seen:
                        continue
                    seen.add(entry["event_id"])
                    fixtures.append(entry)
            if len(seen) >= declared and pages >= math.ceil(declared / PAGE_SIZE):
                break
        complete = bool(declared and counted >= declared and
                        len(seen) >= declared and
                        pages >= math.ceil(declared / PAGE_SIZE) and not error)
    except Exception as exc:
        error = str(exc)[:180]
        complete = False

    now = time.time()
    metadata = {"schema": SCHEMA, "sport": "basketball",
                "is_complete": complete, "declared_total": declared,
                "record_count": counted, "distinct_fixtures": len(seen),
                "pages": pages, "error": error,
                "snapshot_id": hashlib.sha256(
                    f"{now}|{declared}|{len(seen)}".encode()).hexdigest()[:16]}
    if complete:
        sportybet._db_set(CACHE_KEY, {
            "fetched_at": now, "fixtures": fixtures, "metadata": metadata})
    else:
        # Never evict the last complete snapshot following a partial crawl.
        sportybet._db_set(CACHE_KEY + "_attempt", {
            "fetched_at": now, "metadata": metadata})
    return {"status": "success" if complete else "REFRESH_INCOMPLETE",
            "metadata": metadata, "board_preserved": bool(cached_board()),
            "reason": error if error else (
                None if complete else "Basketball SportyBet crawl was incomplete")}


def board_status() -> dict:
    board = cached_board()
    if not board:
        return {"status": "BOARD_REFRESH_REQUIRED", "fixtures": [],
                "reason": "A complete SportyBet basketball board is required. Refresh first."}
    now = time.time() * 1000
    upcoming = [f for f in board["fixtures"] if f["kickoff_ms"] > now + KICKOFF_BUFFER * 1000
                and f.get("markets")]
    return {"status": "success", "fixtures": upcoming,
            "metadata": board["metadata"],
            "fetched_at": board["fetched_at"]}


def _select(request: dict, board: dict) -> dict:
    submitted = request.get("selections") or []
    if not 1 <= len(submitted) <= MAX_LEGS:
        raise ValueError("Basketball ticket must have 1 to 50 selections.")
    try:
        target = float(request.get("target_odds") or 2)
    except (ValueError, TypeError):
        raise ValueError("Invalid target odds.")
    if not math.isfinite(target) or not 2 <= target <= 100000:
        raise ValueError("Target odds must be between 2x and 100,000x.")
    indexes = {entry["event_id"]: entry for entry in board["fixtures"]}
    validated, unavailable, used = [], [], set()
    total = 1.0
    now_ms = time.time() * 1000
    for position, selection in enumerate(submitted, 1):
        eid = str(selection.get("event_id") or "")
        mid = str(selection.get("market_id") or "")
        oid = str(selection.get("outcome_id") or "")
        spec = str(selection.get("specifier") or "")
        event = indexes.get(eid)
        if eid in used or not event or event["kickoff_ms"] <= now_ms + KICKOFF_BUFFER * 1000:
            unavailable.append({"line": position, "reason": "DUPLICATE_OR_UNAVAILABLE_FIXTURE"})
            continue
        used.add(eid)
        outcomes = [o for market in event["markets"] if
                    (market["market_id"], market["specifier"]) == (mid, spec)
                    for o in market["outcomes"] if o["outcome_id"] == oid]
        if len(outcomes) != 1:
            unavailable.append({"line": position, "reason": "EXACT_MARKET_NOT_ACTIVE"})
            continue
        outcome = outcomes[0]
        total *= outcome["odds"]
        validated.append({"event_id": eid, "home_team": event["home_team"],
                          "away_team": event["away_team"],
                          "market_id": mid, "specifier": spec,
                          "outcome_id": oid, "selection": outcome["label"],
                          "odds": outcome["odds"], "kickoff_ms": event["kickoff_ms"]})
    complete = len(validated) == len(submitted) and not unavailable
    return {"status": ("EXACT_MARKETS_UNAVAILABLE" if not complete else
                       "BELOW_TARGET" if total < target else "PROPOSED_NOT_BOOKED"),
            "sport": "basketball", "matched": validated, "unmatched": unavailable,
            "pasted_fixture_count": len(submitted),
            "matched_fixture_count": len(validated),
            "full_ticket_complete": complete,
            "indicative_odds": round(total, 3) if complete else None,
            "target_odds": target, "snapshot_id": board["metadata"]["snapshot_id"],
            "share_code": None, "readback_status": "NOT_REQUESTED"}


def preview(request: dict) -> dict:
    board = cached_board()
    if not board:
        return {"status": "BOARD_REFRESH_REQUIRED", "matched": [],
                "unmatched": [], "full_ticket_complete": False,
                "share_code": None, "readback_status": "NOT_REQUESTED",
                "reason": "No complete fresh basketball SportyBet board. Refresh and retry."}
    return _select(request, board)


def book(request: dict) -> dict:
    """Anonymous code reservation only. Never place a stake or release partial slips."""
    board = cached_board()
    if not board:
        return {"status": "BOARD_REFRESH_REQUIRED", "share_code": None,
                "reason": "Basketball board unavailable"}
    checked = _select(request, board)
    if checked["status"] != "PROPOSED_NOT_BOOKED":
        return checked
    selections = [{"eventId": leg["event_id"], "marketId": leg["market_id"],
                   "outcomeId": leg["outcome_id"], "specifier": leg["specifier"]}
                  for leg in checked["matched"]]
    try:
        receipt = booking._post_share(selections)
    except Exception:
        return {**checked, "status": "BOOKING_UNAVAILABLE", "share_code": None,
                "reason": "SportyBet share request failed; do not blindly retry"}
    if receipt.get("bizCode") != 10000:
        return {**checked, "status": "BOOKING_UNAVAILABLE", "share_code": None,
                "reason": "SportyBet did not accept the requested ticket"}
    data = receipt.get("data") or {}
    code = str(data.get("shareCode") or "")
    if not re.fullmatch(r"[A-Za-z0-9]{4,32}", code):
        return {**checked, "status": "BOOKING_UNAVAILABLE", "share_code": None,
                "reason": "No valid code in bookmaker response"}
    valid, why, actual = booking.validate_code_details(code, selections)
    if not valid or actual is None or actual < checked["target_odds"]:
        return {**checked, "status": "BOOKING_UNAVAILABLE", "share_code": None,
                "readback_status": "FAILED", "reason": (
                    why if not valid else "Readback odds missing or below target")}
    return {**checked, "status": "success", "share_code": code,
            "share_url": data.get("shareURL"), "verified_odds": actual,
            "readback_status": "PASSED", "legs": len(selections),
            "note": "Basketball bookmaker-only experimental slip; no stake placed"}
