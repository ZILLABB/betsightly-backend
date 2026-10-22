"""Private, bookmaker-only jackpot matching — independent of prediction grades.

Uses only actual SportyBet board event/outcome/price mappings; no fabricated
events, unpriced markets, unknown provider IDs or changes to public models.
Admin authentication belongs to the existing growth API routes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite, prod
from zoneinfo import ZoneInfo

from growth.jackpot_paste import parse_fixture_lines
from growth.private_jackpot import MAX_LEGS, MAX_TARGET, MIN_ODDS
from leagues import sportybet
from leagues.market_registry import MARKET_TO_SPORTYBET

_NG = ZoneInfo("Africa/Lagos")
_PROVIDER_MATCH_ONLY = {"tsg", "rb", "nk", "gnk", "rsc", "hnk", "fk", "pfc", "kf"}
# Explicit aliases for football-club identities, NOT generic fuzzy matching.
# Keep youth, women and reserves as distinct squads via _squad checks below.
_EQUIVALENT_CLUB_NAMES = {
    "agf aarhus": "aarhus",
    "kups kuopio": "kuopion palloseura",
    "kups": "kuopion palloseura",
    "st truidense": "sint truidense",
    "sint truidense vv": "sint truidense",
    "st truidense vv": "sint truidense",
    "egnatia rrogozhine": "egnatia",
    "hajduk split": "hajduk split",
}


def _identity(name: str) -> str:
    """Normalize auditable football-club names without removing age markers."""
    normalized = sportybet._norm(str(name or ""))
    words = normalized.split()
    while len(words) > 1 and words[0] in _PROVIDER_MATCH_ONLY:
        words.pop(0)
    key = " ".join(words)
    return _EQUIVALENT_CLUB_NAMES.get(key, key)


def _same_club(left: str, right: str) -> bool:
    a, b = _identity(left), _identity(right)
    if not a or not b:
        return False
    # Strict bookmaker helper covers transliteration e.g. Lillestroem /
    # Lillestrøm. A match must still be unique by both teams, date and squad.
    return a == b or sportybet._same_team(a, b)


def _entry_kickoff(entry: dict) -> datetime | None:
    try:
        stamp = float(entry["kickoff_ms"])
        return datetime.fromtimestamp(stamp / 1000, timezone.utc)
    except (KeyError, TypeError, ValueError, OSError, OverflowError):
        return None


def _price(entry: dict, market: str) -> tuple[str, float | None]:
    mapping = MARKET_TO_SPORTYBET.get(market)
    if not mapping:
        return "NOT_MAPPED", None
    market_id, specifier, outcome_id = mapping
    ref = (entry.get("market_refs") or {}).get(f"{market_id}|{specifier}")
    if ref is not None:
        outcome = (ref.get("outcomes") or {}).get(outcome_id)
        if outcome is None:
            return "OUTCOME_NOT_OFFERED", None
        if not outcome.get("active", False):
            return "OUTCOME_SUSPENDED", None
        quote = outcome.get("odds")
    else:
        quote = (entry.get("prices") or {}).get(market)
        if quote is None:
            return "MARKET_NOT_OFFERED", None
    try:
        value = float(quote)
    except (ValueError, TypeError):
        return "ODDS_UNAVAILABLE", None
    if not isfinite(value) or value <= 1:
        return "ODDS_UNAVAILABLE", None
    return "BOOKABLE", value


def bookmaker_paste_preview(payload: dict, *, board: dict | None = None,
                            now: datetime | None = None) -> dict:
    """One-day exact picks from the bookmaker itself, not model candidates."""
    rows = parse_fixture_lines(str(payload.get("fixtures_text") or ""))
    if any(not item["requested_market"] for item in rows):
        raise ValueError(
            "Bookmaker-only mode requires an exact market on EVERY line after |."
        )
    if len(rows) > min(MAX_LEGS, int(payload.get("max_legs") or MAX_LEGS)):
        raise ValueError("The private accumulator permits 1 to 50 legs.")
    target = float(payload.get("target_odds") or MAX_TARGET)
    if not isfinite(target) or not MIN_ODDS <= target <= MAX_TARGET:
        raise ValueError("Target odds must be between 2x and 100,000x.")
    if str(payload.get("horizon") or "today") != "today":
        raise ValueError("Bookmaker-only experimental mode is restricted to today.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Current time must be timezone-aware.")
    if board is None:
        # Deliberately never launch a full bookmaker crawl on the HTTP request.
        # A scheduled refresh is responsible for obtaining fresh quotes.
        board = sportybet.cached_board_for_admin()
    if not board:
        return {
            "status": "BOARD_REFRESH_REQUIRED",
            "reason": (
                "No complete SportyBet snapshot is available within the "
                "configured three-hour cache window. Refresh the scheduled "
                "bookmaker feed; "
                "no share-code request was made."
            ),
            "share_code": None, "matched": [], "unmatched": [],
            "pasted_fixture_count": len(rows),
            "matched_fixture_count": 0,
            "unmatched_fixture_count": len(rows),
            "source": "SPORTYBET_BOOKMAKER_ONLY_EXPERIMENT",
            "exact_market_mode": True,
            "requested_market_count": len(rows),
            "prediction_quality_gate_applied": False,
            "full_ticket_complete": False,
            "partial_reference_odds": None,
            "indicative_odds": None,
            "maximum_reference_odds": None,
            "distinct_fixture_count": 0,
            "booking_code_created": False,
        }
    meta = sportybet.board_metadata(board)
    fixtures = [entry for _, entry in sportybet._board_entries(board)]
    if not fixtures:
        return {
            "status": "BOOKMAKER_BOARD_UNAVAILABLE",
            "reason": "The cached SportyBet board has no upcoming fixtures.",
            "share_code": None, "matched": [], "unmatched": [],
            "pasted_fixture_count": len(rows),
            "matched_fixture_count": 0,
            "unmatched_fixture_count": len(rows),
            "exact_market_mode": True,
            "requested_market_count": len(rows),
            "full_ticket_complete": False,
            "partial_reference_odds": None,
            "maximum_reference_odds": None,
            "booking_code_created": False,
        }

    # Include every name match for collision detection. Reject repeated event
    # names rather than guessing at which league/date a fixture refers to.
    matched, unmatched, used = [], [], set()
    today = current.astimezone(_NG).date()
    for row in rows:
        matches = [
            candidate for candidate in fixtures
            if _same_club(row["home_team"], candidate.get("home_team") or "")
            and _same_club(row["away_team"], candidate.get("away_team") or "")
            and sportybet._squad(row["home_team"]) == candidate.get("home_squad", "")
            and sportybet._squad(row["away_team"]) == candidate.get("away_squad", "")
        ]
        when = [(entry, _entry_kickoff(entry)) for entry in matches]
        same_day = [(entry, dt) for entry, dt in when
                    if dt and dt.astimezone(_NG).date() == today]
        upcoming = [(entry, dt) for entry, dt in same_day
                    if dt >= current + timedelta(minutes=20)]

        if not matches:
            reason, detail = ("FIXTURE_NOT_ON_SPORTYBET_BOARD",
                              "No bookmaker fixture matched both teams.")
        elif not same_day:
            reason, detail = ("NOT_SCHEDULED_TODAY",
                              "Bookmaker lists the fixture on another date or without a kickoff.")
        elif not upcoming:
            reason, detail = ("STARTED_OR_TOO_CLOSE_TO_KICKOFF",
                              "The event has started or begins within 20 minutes.")
        elif len(upcoming) != 1:
            reason, detail = ("AMBIGUOUS_BOOKMAKER_FIXTURE",
                              "More than one upcoming event matches both teams.")
        else:
            entry, kickoff = upcoming[0]
            event_id = str(entry.get("event_id") or "")
            market = str(row["requested_market"])
            if not event_id or event_id in used:
                reason, detail = ("DUPLICATE_OR_MISSING_EVENT_ID",
                                  "Exact bookmaker event ID cannot be uniquely assigned.")
            elif market.startswith("under_") or "_under_" in market:
                reason, detail = ("UNDER_MARKET_EXCLUDED",
                                  "This private mode respects the no-Under preference.")
            else:
                reason, price = _price(entry, market)
                detail = "The exact bookmaker market is not active and priced."
                if reason == "BOOKABLE":
                    used.add(event_id)
                    matched.append({
                        **row, "match_id": event_id,
                        "selection_id": f"{event_id}:{market}",
                        "matched_home": entry["home_team"],
                        "matched_away": entry["away_team"],
                        "market": market,
                        "odds": price,
                        "kickoff": kickoff.isoformat(),
                        "league": entry.get("competition") or "",
                        "event_id": event_id,
                        "match_method": "bookmaker_exact_club_and_date",
                    })
                    continue
        unmatched.append({**row, "reason": reason, "detail": detail})

    complete = len(matched) == len(rows) and not unmatched
    subtotal = prod(float(row["odds"]) for row in matched)
    sufficient = subtotal >= target
    status = ("UNMATCHED_FIXTURES" if not complete else
              "BELOW_TARGET" if not sufficient else "PROPOSED_NOT_BOOKED")
    return {
        "status": status,
        "source": "SPORTYBET_BOOKMAKER_ONLY_EXPERIMENT",
        "portfolio_type": "USER_SUPPLIED_BOOKMAKER_ONLY",
        "prediction_quality_gate_applied": False,
        "exact_market_mode": True,
        "requested_market_count": len(rows),
        "pasted_fixture_count": len(rows),
        "matched_fixture_count": len(matched),
        "unmatched_fixture_count": len(unmatched),
        "matched": matched,
        "unmatched": unmatched,
        "partial_reference_odds": round(subtotal, 3),
        "full_ticket_complete": complete,
        "indicative_odds": round(subtotal, 3) if complete else None,
        "maximum_reference_odds": round(subtotal, 3) if complete else None,
        "maximum_model_eligible_reference_odds": None,
        "distinct_fixture_count": len(matched),
        "candidate_count": len(matched),
        "legs": len(matched),
        "selection_ids": [row["selection_id"] for row in matched] if complete else [],
        "selected_games": matched if complete else [],
        "board_complete": bool(meta.get("is_complete")),
        "board_generated_at": meta.get("fetched_at"),
        "board_age_seconds": round(
            max(0, current.timestamp() - float(meta.get("fetched_at") or current.timestamp()))
        ),
        "quote_status": "INDICATIVE_CACHED_PRICES_RECHECK_AT_BOOKING",
        "share_code": None,
        "booking_code_created": False,
        "reason": (
            f"{len(unmatched)} exact bookmaker fixtures/markets were unavailable. "
            "The displayed subtotal is ONLY for matched legs, not the "
            "maximum odds for your complete pasted ticket."
            if not complete else
            f"Bookmaker prices total {subtotal:,.2f}x, below {target:,.2f}x."
            if not sufficient else
            "All exact selections are currently bookable on the SportyBet board. "
            "A code still requires explicit confirmation and full readback."
        ),
    }


def bookmaker_paste_book(payload: dict) -> dict:
    """Create only a complete privately confirmed code, with full readback."""
    # One snapshot and one validation pass. The previous implementation ran
    # the fixture discovery twice, which amplified expensive bookmaker/cache
    # lookups on every user click and could produce inconsistent snapshots.
    board = sportybet.cached_board_for_admin() or {}
    verified = bookmaker_paste_preview(payload, board=board)
    if verified["status"] != "PROPOSED_NOT_BOOKED":
        return {**verified, "share_code": None}
    from leagues.booking import create_booking
    games = [{
        "home_team": row["matched_home"],
        "away_team": row["matched_away"],
        "market": row["market"],
        "kickoff": row["kickoff"],
        "date": row["kickoff"],
        "league": row["league"],
        "sportybet_event_id": row["event_id"],
    } for row in verified["matched"]]
    booking = create_booking(games, board, allow_partial=False,
                             booking_status="FULL",
                             original_games=games,
                             predicted_odds=verified["indicative_odds"])
    exact = (
        booking.get("booking_status") in {"FULL", "REBUILT_FULL"}
        and booking.get("readback_validation") == "PASSED"
        and int(booking.get("booked_leg_count") or 0) == len(games)
        and bool(booking.get("share_code"))
    )
    try:
        actual = float(booking.get("actual_sportybet_odds") or 0)
    except (TypeError, ValueError):
        actual = 0
    if not exact or not isfinite(actual) or actual < float(payload["target_odds"]):
        return {
            **verified,
            "status": "BOOKING_UNAVAILABLE" if not exact else "BELOW_TARGET",
            "reason": (booking.get("reason") or booking.get("failure_category")
                       or "Exact bookmaker readback failed.")
                      if not exact else "SportyBet verified odds fell below target.",
            "verified_odds": actual if actual > 0 else None,
            "share_code": None, "readback_status": "FAILED",
        }
    return {
        **verified,
        "status": "success",
        "share_code": booking["share_code"],
        "share_url": booking.get("share_url"),
        "verified_odds": round(actual, 3),
        "readback_status": "PASSED",
        "priced_at": booking.get("priced_at"),
        "expires_at": booking.get("expires_at"),
        "publication_status": "PRIVATE_NOT_PUBLISHED",
        "note": "Bookmaker-only experiment; no model calibration, public publishing or stake.",
    }
