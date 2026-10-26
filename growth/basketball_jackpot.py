"""Admin-only basketball SportyBet exact-selection desk.

No basketball model, football market mapper, staking, or public publication.
Never return a booking code until the complete ticket passes share-code readback.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from datetime import datetime, timezone

from leagues import sportybet
from leagues import booking

logger = logging.getLogger(__name__)
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
        if not _active(market.get("isActive", True)):
            continue
        if str(market.get("status") or "").upper() in {"SUSPENDED", "CLOSED", "INACTIVE"}:
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


def refresh_board(*, _retried: bool = False) -> dict:
    """Read the SportyBet board; retry one near-complete pagination drift.

    A changing upstream event count may leave one event out between pages.
    Retry the *whole* crawl once; never promote either incomplete snapshot.
    """
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

    # The provider's totalNum can shift while pages are being read.
    # Only a fresh COMPLETE second pass is accepted; never fill missing legs,
    # lower the declared total, or certify the first incomplete snapshot.
    if (not complete and not _retried and error is None and declared
            and 0 < declared - counted <= 2 and len(seen) == counted):
        return refresh_board(_retried=True)

    if complete and not any(entry.get("markets") for entry in fixtures):
        complete = False
        error = "SportyBet basketball board has no verified 219/225 markets"
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
                          "competition": event["competition"],
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



def recover_existing(fingerprint_value: str) -> dict:
    """Revalidate a saved code without making another bookmaker share POST.

    The administrator supplies only the ledger fingerprint. All selections,
    target odds and expiry are taken from the original immutable attempt.
    """
    from growth import basketball_history as history

    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint_value):
        raise ValueError("Invalid basketball booking fingerprint.")
    hidden = {"status": "RECOVERY_NOT_VERIFIED", "share_code": None,
              "readback_status": "NOT_VERIFIED", "reused_existing_code": True}

    try:
        record = history.get(fingerprint_value, private=True)
    except Exception:
        logger.exception("Basketball ledger recovery lookup failed")
        return {**hidden, "status": "BOOKING_HISTORY_UNAVAILABLE",
                "reason": "Could not safely retrieve the saved booking attempt."}
    if not record:
        return {**hidden, "status": "BOOKING_NOT_FOUND",
                "reason": "No matching saved basketball attempt was found."}
    if record.get("status") not in {"needs_review", "verifying"}:
        return {**hidden, "status": "RECOVERY_NOT_APPLICABLE",
                "reason": "This attempt is not awaiting code recovery. Check history."}

    legs = record.get("legs") or []
    code = str(record.get("share_code") or "")
    expires = record.get("expires_at")
    try:
        expiry = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        target = float(record["target_odds"])
        kickoffs = [int(leg["kickoff_ms"]) for leg in legs]
    except (ValueError, KeyError, TypeError, OverflowError):
        return {**hidden, "reason": "Saved expiry, target or fixture times are incomplete."}
    if (not re.fullmatch(r"[A-Za-z0-9]{4,32}", code)
            or expiry.tzinfo is None or expiry <= datetime.now(timezone.utc)
            or not math.isfinite(target) or target < 2
            or not 1 <= len(legs) <= MAX_LEGS
            or any(k <= (time.time() + KICKOFF_BUFFER) * 1000 for k in kickoffs)):
        return {**hidden, "reason": "The saved code or its fixtures are no longer eligible."}

    selections = [{"eventId": str(leg.get("event_id") or ""),
                   "marketId": str(leg.get("market_id") or ""),
                   "outcomeId": str(leg.get("outcome_id") or ""),
                   "specifier": str(leg.get("specifier") or "")}
                  for leg in legs]
    if (len({leg["eventId"] for leg in selections}) != len(selections)
            or any(not leg["eventId"] or not leg["marketId"]
                   or not leg["outcomeId"] for leg in selections)
            or history.fingerprint(selections) != fingerprint_value):
        return {**hidden, "reason": "Saved selection fingerprint is inconsistent."}

    try:
        valid, why, actual = booking.validate_code_details(code, selections)
    except Exception:
        logger.exception("Basketball saved share-code readback failed")
        return {**hidden, "reason": "SportyBet code readback is temporarily unavailable."}
    if not valid:
        return {**hidden, "readback_status": "FAILED",
                "reason": "The saved share code failed exact-leg readback: " + str(why)[:140]}

    source = "sportybet_code_readback"
    if actual is None:
        # A pre-booking snapshot must not certify a post-booking price. Reuse
        # only a complete snapshot created AFTER the failed booking attempt.
        board = cached_board()
        try:
            attempted_at = datetime.fromisoformat(
                str(record["updated_at"]).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError, KeyError, OverflowError):
            attempted_at = float("inf")
        if not board or float(board["fetched_at"]) <= attempted_at:
            fresh = refresh_board()
            board = cached_board() if fresh.get("status") == "success" else None
        if not board or float(board["fetched_at"]) <= attempted_at:
            return {**hidden, "readback_status": "ODDS_UNAVAILABLE",
                    "reason": "No complete bookmaker price snapshot newer than the failed attempt."}
        request = {"selections": [{"event_id": leg["eventId"],
                                   "market_id": leg["marketId"],
                                   "outcome_id": leg["outcomeId"],
                                   "specifier": leg["specifier"]}
                                  for leg in selections],
                   "target_odds": target}
        checked = _select(request, board)
        if checked["status"] != "PROPOSED_NOT_BOOKED":
            return {**hidden, "readback_status": "ODDS_UNAVAILABLE",
                    "reason": "Exact saved markets are unavailable or below the original target."}
        actual = math.prod(float(leg["odds"]) for leg in checked["matched"])
        source = "fresh_complete_sportybet_board"
    try:
        verified = float(actual)
    except (ValueError, TypeError, OverflowError):
        verified = float("nan")
    if not math.isfinite(verified) or verified < target:
        return {**hidden, "readback_status": "BELOW_TARGET",
                "reason": "The recovered price is invalid or below the original target."}

    try:
        history.mark(fingerprint_value, status="active", share_code=code,
                     verified_odds=round(verified, 3), odds_source=source,
                     expires_at=expires,
                     detail_update={"ticket_status": "pending",
                                    "recovery_method": "read_only_existing_code"})
    except Exception:
        logger.exception("Basketball saved-code recovery could not persist")
        return {**hidden, "status": "BOOKING_HISTORY_UNAVAILABLE",
                "reason": "The verified code could not be archived. No code released."}
    return {"status": "success", "share_code": code,
            "readback_status": "PASSED", "verified_odds": round(verified, 3),
            "verified_odds_source": source, "legs": len(legs),
            "history_saved": True, "reused_existing_code": True,
            "expires_at": expires,
            "note": "Existing share code verified without creating another code."}


def book(request: dict) -> dict:
    """Claim intent before one bookmaker POST; never silently repeat a code request."""
    from growth import basketball_history as history
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
        own, record = history.claim(selections, checked["matched"],
                                    checked["target_odds"], checked["snapshot_id"])
    except Exception:
        return {**checked, "status": "BOOKING_HISTORY_UNAVAILABLE",
                "share_code": None, "reason": (
                    "Could not save an idempotent booking intent. No SportyBet "
                    "code request was made.")}
    fp = record["fingerprint"]
    if not own:
        expires = record.get("expires_at")
        try:
            valid_expiry = (expires and
                            datetime.fromisoformat(expires.replace("Z", "+00:00")) >
                            datetime.now(timezone.utc))
        except (ValueError, TypeError):
            valid_expiry = False
        if (record["status"] in {"active", "won", "lost", "void"}
                and record.get("share_code") and valid_expiry):
            return {**checked, "status": "success",
                    "share_code": record["share_code"],
                    "verified_odds": record.get("verified_odds"),
                    "verified_odds_source": record.get("verified_odds_source"),
                    "expires_at": expires, "legs": len(selections),
                    "readback_status": "PASSED", "history_saved": True,
                    "reused_existing_code": True}
        # Revalidate an earlier privately saved bookmaker code in read-only
        # mode. Never send a second share POST for this exact fingerprint.
        if valid_expiry and record["status"] in {"needs_review", "verifying"}:
            try:
                private = history.get(fp, private=True)
                saved_code = str((private or {}).get("share_code") or "")
                if re.fullmatch(r"[A-Za-z0-9]{4,32}", saved_code):
                    valid, _reason, actual = booking.validate_code_details(
                        saved_code, selections)
                    source = "sportybet_code_readback"
                    if valid and actual is None:
                        fresh = refresh_board()
                        current = cached_board() if fresh.get("status") == "success" else None
                        second = _select(request, current) if current else None
                        if (second and second["full_ticket_complete"]
                                and second["status"] == "PROPOSED_NOT_BOOKED"):
                            actual = math.prod(float(leg["odds"])
                                               for leg in second["matched"])
                            source = "fresh_complete_sportybet_board"
                    original_target = float(record.get("target_odds") or checked["target_odds"])
                    if (valid and actual is not None and math.isfinite(float(actual))
                            and float(actual) >= max(original_target, checked["target_odds"])):
                        history.mark(fp, status="active", share_code=saved_code,
                                     verified_odds=round(float(actual), 3),
                                     odds_source=source, expires_at=expires)
                        return {**checked, "status": "success",
                                "share_code": saved_code,
                                "verified_odds": round(float(actual), 3),
                                "verified_odds_source": source,
                                "expires_at": expires, "legs": len(selections),
                                "readback_status": "PASSED", "history_saved": True,
                                "reused_existing_code": True}
            except Exception:
                logger.exception("Read-only basketball code recovery failed")
        return {**checked, "status": "BOOKING_PREVIOUS_ATTEMPT",
                "share_code": None, "readback_status": "NOT_RETRIED",
                "history_saved": True,
                "reason": ("This exact ticket already has a recorded booking "
                           "attempt. Inspect Booking History before requesting "
                           "another code; no additional share POST was sent.")}
    def hold(status, reason, **extra):
        try:
            history.mark(fp, status="needs_review",
                         detail_update={"failure_stage": status, "reason": reason})
        except Exception:
            logger.exception("Basketball booking ledger could not be updated")
        return {**checked, "status": status, "share_code": None,
                "history_saved": True, "reason": reason, **extra}

    try:
        receipt = booking._post_share(selections)
    except Exception:
        return hold("BOOKING_UNAVAILABLE",
                    "SportyBet share request outcome is uncertain. Review "
                    "booking history; do not repeat Generate blindly.")
    if receipt.get("bizCode") != 10000:
        return hold("BOOKING_UNAVAILABLE", "SportyBet did not accept the ticket.")
    data = receipt.get("data") or {}
    code = str(data.get("shareCode") or "")
    if not re.fullmatch(r"[A-Za-z0-9]{4,32}", code):
        return hold("BOOKING_UNAVAILABLE", "No valid share code was returned.")
    # Preserve a verifiable expiry even if subsequent odds checks fail.
    # This enables read-only recovery of a previously created share code.
    try:
        pending_expiry = datetime.fromtimestamp(float(data["deadline"]) / 1000,
                                                tz=timezone.utc)
        if pending_expiry <= datetime.now(timezone.utc):
            pending_expiry = None
    except (KeyError, ValueError, TypeError, OSError, OverflowError):
        pending_expiry = None
    try:
        history.mark(fp, status="verifying", share_code=code,
                     expires_at=pending_expiry.isoformat() if pending_expiry else None)
    except Exception:
        return {**checked, "status": "BOOKING_HISTORY_UNAVAILABLE",
                "share_code": None, "history_saved": False,
                "reason": "Code created but its private audit record could not be stored."}

    try:
        valid, why, actual = booking.validate_code_details(code, selections)
    except Exception:
        return hold("BOOKING_UNAVAILABLE", "Code readback did not complete.",
                    readback_status="FAILED")
    if not valid:
        return hold("BOOKING_UNAVAILABLE", why, readback_status="FAILED")
    odds_source = "sportybet_code_readback"
    if actual is None:
        fresh = refresh_board()
        if fresh.get("status") != "success":
            return hold("BOOKING_UNAVAILABLE",
                        "Code legs match, but a complete fresh bookmaker price "
                        "check failed. See history; do not create another code.",
                        readback_status="ODDS_UNAVAILABLE")
        current_board = cached_board()
        if current_board is None:
            return hold("BOOKING_UNAVAILABLE",
                        "Fresh bookmaker prices could not be persisted.",
                        readback_status="ODDS_UNAVAILABLE")
        refreshed = _select(request, current_board)
        if not refreshed["full_ticket_complete"]:
            return hold("BOOKING_UNAVAILABLE",
                        "One or more exact markets are no longer active.",
                        readback_status="ODDS_UNAVAILABLE",
                        unmatched=refreshed["unmatched"])
        actual = math.prod(float(leg["odds"]) for leg in refreshed["matched"])
        odds_source = "fresh_complete_sportybet_board"
    if not math.isfinite(float(actual)) or actual <= 1:
        return hold("BOOKING_UNAVAILABLE",
                    "Current bookmaker odds cannot be verified.",
                    readback_status="ODDS_UNAVAILABLE")
    if actual < checked["target_odds"]:
        return hold("BOOKING_UNAVAILABLE",
                    f"Current total {actual:.3f}x is below target "
                    f"{checked['target_odds']:g}x.",
                    readback_status="BELOW_TARGET",
                    verified_odds=round(actual, 3),
                    verified_odds_source=odds_source)
    try:
        expiry = datetime.fromtimestamp(float(data["deadline"]) / 1000,
                                        tz=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            raise ValueError("expired")
    except (KeyError, TypeError, ValueError, OSError):
        return hold("BOOKING_UNAVAILABLE",
                    "SportyBet did not provide a verifiable future code expiry.",
                    readback_status="FAILED")
    try:
        history.mark(fp, status="active", share_code=code,
                     verified_odds=round(actual, 3), odds_source=odds_source,
                     expires_at=expiry.isoformat(),
                     detail_update={"ticket_status": "pending"})
    except Exception:
        return {**checked, "status": "BOOKING_HISTORY_UNAVAILABLE",
                "share_code": None, "history_saved": False,
                "reason": "Verified code could not be archived. Inspect history."}
    return {**checked, "status": "success", "share_code": code,
            "share_url": data.get("shareURL"),
            "expires_at": expiry.isoformat(),
            "verified_odds": round(actual, 3),
            "verified_odds_source": odds_source, "history_saved": True,
            "readback_status": "PASSED", "legs": len(selections),
            "note": "No stake placed; the verified basketball ticket is archived."}
