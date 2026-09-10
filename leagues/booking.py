"""
Turning a published tier into a SportyBet booking code.

The card tells a reader which bets to place. Until now they had to re-enter
every leg by hand — five fixtures, five markets, five prices, typed into a
different app. A booking code collapses that into six characters: the reader
types it into SportyBet and the exact slip loads, priced.

This does not place a bet. It builds a slip and hands it over; the stake and
the confirmation stay with the person. Nothing here authenticates, and no
account is involved — the share endpoint is SportyBet's own public feature,
and a code is created by an anonymous caller exactly as it is when a user taps
"share" in their app.

Two rules shape the code below.

*Never publish a code that does not match the card.* A tier is booked only if
every one of its legs resolves to a real SportyBet selection, and the created
code is read back and compared leg by leg before it is stored. A code that
silently dropped a leg would be worse than no code: the reader would stake a
slip they never chose.

*A code is as immutable as the card it belongs to.* Codes are generated once,
by the daily run, and stored. Serving the card only ever attaches what is
already stored, so a page load can never mint a new code — and two readers
opening the card an hour apart get the same slip.
"""

import json
import itertools
import logging
import threading
import time
import urllib.request
from datetime import datetime, timezone

from leagues.availability import game_kickoff_lifecycle
from leagues.sportybet import MARKET_TO_SPORTYBET

logger = logging.getLogger(__name__)

BASE_URL = None  # resolved from the adapter so there is one host to change
_GENERATED_BOOKING_LOCKS: dict[str, threading.Lock] = {}
_GENERATED_BOOKING_LOCKS_GUARD = threading.Lock()


def _base() -> str:
    from leagues.sportybet import BASE_URL as SB
    return SB


def _oper_id() -> str:
    from leagues.sportybet import OPER_ID
    return OPER_ID


# ── Storage ────────────────────────────────────────────────

def _ensure_table(conn) -> None:
    from sqlalchemy import inspect, text
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS tier_bookings ("
        "  publish_date VARCHAR(10) NOT NULL,"
        "  tier VARCHAR(24) NOT NULL,"
        "  share_code VARCHAR(32),"
        "  share_url VARCHAR(255),"
        "  legs INTEGER,"
        "  status VARCHAR(16) NOT NULL,"
        "  detail TEXT,"
        "  created_at VARCHAR(32),"
        "  PRIMARY KEY (publish_date, tier))"))
    existing = {c["name"] for c in inspect(conn).get_columns("tier_bookings")}
    additions = {
        "booking_status": "VARCHAR(24)",
        "original_leg_count": "INTEGER",
        "booked_leg_count": "INTEGER",
        "excluded_leg_count": "INTEGER",
        "replacement_count": "INTEGER",
        "predicted_odds": "FLOAT",
        "actual_sportybet_odds": "FLOAT",
        "board_snapshot_id": "VARCHAR(64)",
    }
    for name, sql_type in additions.items():
        if name not in existing:
            conn.execute(text(
                f"ALTER TABLE tier_bookings ADD COLUMN {name} {sql_type}"))
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS sportybet_booking_audit ("
        " occurred_at VARCHAR(32) NOT NULL, publish_date VARCHAR(10),"
        " tier VARCHAR(24), league VARCHAR(160), market VARCHAR(64),"
        " reason VARCHAR(64), status VARCHAR(32), count INTEGER NOT NULL)"))
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS generated_bookings ("
        " leg_fingerprint VARCHAR(64) PRIMARY KEY, share_code VARCHAR(32),"
        " detail TEXT NOT NULL, created_at VARCHAR(32) NOT NULL)"))


def _store(publish_date: str, tier: str, record: dict) -> None:
    from sqlalchemy import text
    from database import engine
    try:
        with engine.begin() as conn:
            _ensure_table(conn)
            params = {
                "d": publish_date, "t": tier,
                "c": record.get("share_code"), "u": record.get("share_url"),
                "l": record.get("legs") or 0, "s": record.get("status", "failed"),
                "bs": record.get("booking_status"),
                "ol": record.get("original_leg_count"),
                "bl": record.get("booked_leg_count"),
                "el": record.get("excluded_leg_count"),
                "rc": record.get("replacement_count"),
                "po": record.get("predicted_tier_odds"),
                "ao": record.get("actual_sportybet_odds"),
                "snap": record.get("board_snapshot_id"),
                "j": json.dumps(record),
                "a": datetime.now(timezone.utc).isoformat(),
            }
            updated = conn.execute(text(
                "UPDATE tier_bookings SET share_code=:c, share_url=:u, legs=:l,"
                " status=:s, booking_status=:bs, original_leg_count=:ol,"
                " booked_leg_count=:bl, excluded_leg_count=:el,"
                " replacement_count=:rc, predicted_odds=:po,"
                " actual_sportybet_odds=:ao, board_snapshot_id=:snap,"
                " detail=:j, created_at=:a"
                " WHERE publish_date=:d AND tier=:t"), params).rowcount
            if not updated:
                conn.execute(text(
                    "INSERT INTO tier_bookings"
                    " (publish_date, tier, share_code, share_url, legs, status,"
                    "  detail, created_at, booking_status, original_leg_count,"
                    "  booked_leg_count, excluded_leg_count, replacement_count,"
                    "  predicted_odds, actual_sportybet_odds, board_snapshot_id)"
                    " VALUES (:d,:t,:c,:u,:l,:s,:j,:a,:bs,:ol,:bl,:el,:rc,"
                    " :po,:ao,:snap)"), params)
    except Exception as e:
        logger.warning(f"booking persist failed for {tier}: {e}")


def bookings_for(publish_date: str) -> dict:
    """Stored bookings keyed by tier. Empty when nothing has been booked."""
    from sqlalchemy import text
    from database import engine
    out: dict = {}
    try:
        with engine.begin() as conn:
            _ensure_table(conn)
            rows = conn.execute(text(
                "SELECT tier, detail FROM tier_bookings WHERE publish_date = :d"),
                {"d": publish_date}).fetchall()
    except Exception as e:
        # Loud, not debug. A lookup that fails here returns an empty dict, and
        # an empty dict is indistinguishable from a day nothing was booked —
        # so a broken query looks exactly like a quiet morning and the card
        # simply carries no codes with nothing to say why.
        logger.warning(f"booking lookup failed for {publish_date}: "
                       f"{type(e).__name__}: {e}", exc_info=True)
        return {}
    for tier, detail in rows:
        try:
            out[tier] = json.loads(detail) if detail else {}
        except (TypeError, ValueError):
            continue
    return out


def booking_history(start_date: str) -> dict[tuple[str, str], dict]:
    """Stored booking facts from a date onward, keyed by exact card/tier.

    Results accounting uses this only when readback validation and immutable
    selection fingerprints prove that the booking represents the published
    set. Missing or malformed historical rows are simply absent from the
    SportyBet sample and remain in the published-odds record.
    """
    from sqlalchemy import text
    from database import engine
    out: dict[tuple[str, str], dict] = {}
    try:
        with engine.begin() as conn:
            _ensure_table(conn)
            rows = conn.execute(text(
                "SELECT publish_date, tier, detail FROM tier_bookings "
                "WHERE publish_date >= :start_date"
            ), {"start_date": start_date}).fetchall()
    except Exception as exc:
        logger.warning(f"booking history lookup failed: {exc}")
        return out
    for publish_date, tier, detail in rows:
        try:
            out[(publish_date, tier)] = json.loads(detail) if detail else {}
        except (TypeError, ValueError):
            continue
    return out


def generated_booking_for(fingerprint: str) -> dict | None:
    """A previously validated generated code for this exact normalized slip."""
    from sqlalchemy import text
    from database import engine
    try:
        with engine.begin() as conn:
            _ensure_table(conn)
            row = conn.execute(text(
                "SELECT detail FROM generated_bookings "
                "WHERE leg_fingerprint=:fingerprint"),
                {"fingerprint": fingerprint}).fetchone()
        return json.loads(row[0]) if row and row[0] else None
    except Exception as exc:
        logger.warning(f"generated booking lookup failed: {exc}")
        return None


def _store_generated_booking(fingerprint: str, record: dict) -> None:
    from sqlalchemy import text
    from database import engine
    try:
        now = datetime.now(timezone.utc).isoformat()
        params = {
            "fingerprint": fingerprint,
            "code": record.get("share_code"),
            "detail": json.dumps(record),
            "created": now,
        }
        with engine.begin() as conn:
            _ensure_table(conn)
            updated = conn.execute(text(
                "UPDATE generated_bookings SET share_code=:code, detail=:detail, "
                "created_at=:created WHERE leg_fingerprint=:fingerprint"),
                params).rowcount
            if not updated:
                conn.execute(text(
                    "INSERT INTO generated_bookings "
                    "(leg_fingerprint,share_code,detail,created_at) "
                    "VALUES (:fingerprint,:code,:detail,:created)"), params)
    except Exception as exc:
        logger.warning(f"generated booking persist failed: {exc}")


def _audit(publish_date: str, tier: str, status: str, games: list,
           reason: str | None = None, once: bool = False) -> None:
    """Durable counters; audit failure can never block prediction publishing."""
    from sqlalchemy import text
    from database import engine
    rows = games or [{}]
    try:
        with engine.begin() as conn:
            _ensure_table(conn)
            if once:
                seen = conn.execute(text(
                    "SELECT COUNT(*) FROM sportybet_booking_audit"
                    " WHERE publish_date=:d AND tier=:t AND status=:s"),
                    {"d": publish_date, "t": tier, "s": status}).scalar()
                if seen:
                    return
            for game in rows:
                availability = game.get("sportybet_availability") or {}
                conn.execute(text(
                    "INSERT INTO sportybet_booking_audit"
                    " (occurred_at,publish_date,tier,league,market,reason,status,count)"
                    " VALUES (:at,:d,:t,:l,:m,:r,:s,1)"), {
                        "at": datetime.now(timezone.utc).isoformat(),
                        "d": publish_date, "t": tier,
                        "l": game.get("league"), "m": game.get("market"),
                        "r": reason or availability.get("status"), "s": status,
                    })
    except Exception as exc:
        logger.warning(f"booking audit persist failed: {exc}")


# ── Building a slip ────────────────────────────────────────

def leg_fingerprint(games: list) -> str:
    """A stable signature of what a tier actually contains.

    Booking and serving are separated in time, and a tier can change between
    them — it may be extended when a later fixture qualifies, or rebuilt if
    the card is forced. A code minted against the old legs would then be
    served beside the new ones, and the reader would stake a slip that is not
    the one on screen. Comparing this on the way out catches that.

    Derived from the card's own fields, never from the bookmaker board, so
    attaching a code stays a pure database read.
    """
    import hashlib
    parts = []
    for g in games or []:
        parts.append("|".join([
            str(g.get("match_id") or ""),
            str(g.get("home_team") or ""),
            str(g.get("away_team") or ""),
            str(g.get("market") or ""),
        ]))
    parts.sort()
    return hashlib.md5("~".join(parts).encode()).hexdigest()[:16]


def booking_lifecycle(record: dict | None, games: list,
                      now: datetime | None = None) -> dict | None:
    """Apply local, deterministic safety checks before a code is exposed.

    This never contacts SportyBet. Network readback happens when the code is
    created/reused; serving first checks immutable card identity, expiry and
    the canonical 20-minute kickoff boundary.
    """
    if not record:
        return None
    checked = dict(record)

    def invalid(status: str, category: str, reason: str) -> dict:
        checked.update({
            "status": status,
            "lifecycle_status": status,
            "failure_category": category,
            "reason": reason,
            "actionable": False,
            "share_code": None,
            "share_url": None,
        })
        return checked

    if record.get("status") != "active" or not record.get("share_code"):
        return invalid(
            str(record.get("status") or "unavailable").lower(),
            str(record.get("failure_category") or "CODE_GENERATION_FAILED"),
            str(record.get("reason") or "No active SportyBet code is available."),
        )
    if str(record.get("readback_validation") or "").upper() != "PASSED":
        return invalid("validation_failed", "READBACK_FAILED",
                       "The SportyBet code did not pass readback validation.")
    booking_status = str(record.get("booking_status") or "").upper()
    if booking_status not in {"FULL", "REBUILT_FULL"}:
        return invalid("unavailable", "READBACK_MISMATCH",
                       "The code is not the complete displayed accumulator.")
    if record.get("partial") or int(record.get("excluded_leg_count") or 0):
        return invalid("unavailable", "READBACK_MISMATCH",
                       "A partial code cannot represent the full displayed slip.")

    expected = leg_fingerprint(games)
    if not expected or record.get("leg_fingerprint") != expected:
        return invalid("stale", "READBACK_MISMATCH",
                       "This tier changed after the code was created.")
    original_count = int(record.get("original_leg_count") or 0)
    booked_count = int(record.get("booked_leg_count") or record.get("legs") or 0)
    if original_count != len(games) or booked_count != len(games):
        return invalid("stale", "READBACK_MISMATCH",
                       "The code leg count no longer matches the displayed slip.")

    current = now or datetime.now(timezone.utc)
    expires_at = record.get("expires_at")
    if not expires_at:
        return invalid("expired", "CODE_EXPIRED",
                       "The code has no verifiable expiry time.")
    try:
        expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return invalid("expired", "CODE_EXPIRED",
                       "The code expiry time is invalid.")
    if expires <= current:
        return invalid("expired", "CODE_EXPIRED",
                       "The SportyBet code has expired.")

    states = [game_kickoff_lifecycle(game, current) for game in games]
    if "invalid" in states:
        return invalid("stale", "KICKOFF_MISMATCH",
                       "A displayed fixture has no valid kickoff time.")
    if "started" in states:
        return invalid("started", "FIXTURE_STARTED",
                       "At least one fixture in this code has started.")
    if "kickoff_buffer" in states:
        return invalid("kickoff_buffer", "KICKOFF_BUFFER",
                       "A fixture starts within the 20-minute booking buffer.")

    checked.update({"lifecycle_status": "active", "actionable": True,
                    "failure_category": None})
    return checked


def validated_public_booking(record: dict | None, games: list,
                             now: datetime | None = None) -> dict | None:
    """Return a stored booking only when it is safe to advertise.

    This is a read-only gate over facts already produced by booking readback.
    A rebuilt full ticket is allowed because its original fingerprint still
    proves which locked card it came from. Partial and stale tickets are not.
    """
    checked = booking_lifecycle(record, games, now)
    if not checked or not checked.get("actionable"):
        return None
    # Preserve identity for callers that use it as a zero-copy gate.
    return record


def selection_fingerprint(selections: list) -> str:
    """Stable identity of the exact SportyBet legs a generated code contains."""
    import hashlib
    parts = sorted("|".join([
        str(selection.get("eventId") or ""),
        str(selection.get("marketId") or ""),
        str(selection.get("outcomeId") or ""),
        str(selection.get("specifier") or ""),
    ]) for selection in (selections or []))
    return hashlib.sha256("~".join(parts).encode()).hexdigest()[:32]


def selections_for(games: list, board: dict) -> tuple[list, list]:
    """Map a tier's published games onto SportyBet selections.

    Returns (selections, unmapped). A game is unmapped when its fixture is not
    on the board, when the two feeds disagree irreconcilably about a club's
    name, or when the market is one SportyBet does not quote.
    """
    from leagues import sportybet

    selections, unmapped = [], []
    for g in games or []:
        market = g.get("market")
        home, away = g.get("home_team", ""), g.get("away_team", "")
        availability = sportybet.availability_for(
            board, home, away, g.get("kickoff") or g.get("date") or "",
            g.get("league") or "", market or "")
        if not availability.get("sportybet_available"):
            unmapped.append({
                "match": f"{home} v {away}", "home_team": home,
                "away_team": away, "market": market,
                "status": availability.get("status"),
                "reason": availability.get("failure_reason") or
                          f"market not bookable: {market!r}",
            })
            continue
        market_id = availability["market_id"]
        specifier = availability["specifier"]
        outcome_id = availability["outcome_id"]
        selections.append({
            "eventId": availability["event_id"],
            "marketId": market_id,
            "outcomeId": outcome_id,
            "specifier": specifier,
        })
    return selections, unmapped


def _mapping_failure_category(unmapped: list) -> str:
    if not unmapped:
        return "FIXTURE_MAPPING_FAILED"
    item = unmapped[0]
    status = str(item.get("status") or "").upper()
    reason = str(item.get("reason") or "").lower()
    if status == "KICKOFF_MISMATCH":
        return "KICKOFF_MISMATCH"
    if status == "MARKET_NOT_FOUND":
        return "MARKET_NOT_FOUND"
    if status == "SELECTION_NOT_FOUND":
        if "suspend" in reason:
            return "OUTCOME_SUSPENDED"
        return "SELECTION_NOT_FOUND"
    if status == "ODDS_UNAVAILABLE":
        return "ODDS_UNAVAILABLE"
    if status == "SPORTYBET_DATA_ERROR":
        return "SPORTYBET_DATA_ERROR"
    return "FIXTURE_MAPPING_FAILED"


def _post_share(selections: list) -> dict:
    body = json.dumps({"selections": selections}).encode()
    req = urllib.request.Request(
        f"{_base()}/api/ng/orders/share", data=body, method="POST",
        headers={"Content-Type": "application/json;charset=UTF-8",
                 "OperId": _oper_id()})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read())


def _read_share(code: str) -> dict:
    req = urllib.request.Request(f"{_base()}/api/ng/orders/share/{code}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def validate_code(code: str, expected: list) -> tuple[bool, str]:
    ok, why, _ = validate_code_details(code, expected)
    return ok, why


def validate_code_details(code: str, expected: list) -> tuple[bool, str, float | None]:
    """Read the code back and confirm it is the slip we asked for.

    HTTP 200 means the request was accepted, not that the right slip exists.
    A dropped or substituted leg would otherwise reach a reader as a code that
    looks fine and stakes something they never chose.
    """
    try:
        payload = _read_share(code)
    except Exception as e:
        return False, f"could not read back: {str(e)[:80]}", None

    if payload.get("bizCode") != 10000:
        return False, f"code did not resolve: {payload.get('message')}", None

    data = payload.get("data") or {}
    got = (data.get("ticket") or {}).get("selections") or []
    if len(got) != len(expected):
        return False, f"expected {len(expected)} legs, code holds {len(got)}", None

    def key(sel):
        return (str(sel.get("eventId")), str(sel.get("marketId")),
                str(sel.get("outcomeId")), str(sel.get("specifier") or ""))

    if {key(s) for s in got} != {key(s) for s in expected}:
        return False, "selections in the code do not match the tier", None

    unavailable = data.get("unavailableOutcomes") or []
    if unavailable:
        return False, f"{len(unavailable)} selection(s) already unavailable", None

    ticket = data.get("ticket") or {}
    raw_odds = ticket.get("displayTotalOdds")
    if raw_odds is None:
        raw_odds = ticket.get("totalOdds")
    if raw_odds is None:
        raw_odds = data.get("displayTotalOdds") or data.get("totalOdds")
    if raw_odds is None:
        # Some SportyBet readbacks omit an aggregate but return a current
        # price on every exact selection. Their product is still bookmaker-
        # returned odds; a board/model estimate is never substituted here.
        prices = []
        for selection in got:
            raw_price = selection.get("odds") or selection.get("displayOdds")
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                prices = []
                break
            if price <= 1:
                prices = []
                break
            prices.append(price)
        if prices and len(prices) == len(got):
            raw_odds = 1.0
            for price in prices:
                raw_odds *= price
    try:
        actual_odds = round(float(raw_odds), 3)
    except (TypeError, ValueError):
        # SportyBet's current create/readback schema proves the exact events,
        # markets and outcomes but omits prices entirely. The caller may use
        # the exact same live board snapshot for odds; it must still fail if
        # neither source contains a valid price.
        actual_odds = None
    return True, "ok", actual_odds


def _validation_failure_category(reason: str) -> str:
    lowered = (reason or "").lower()
    if "unavailable" in lowered:
        return "OUTCOME_SUSPENDED"
    if "odds" in lowered:
        return "ODDS_UNAVAILABLE"
    if "could not read" in lowered or "did not resolve" in lowered:
        return "READBACK_FAILED"
    return "READBACK_MISMATCH"


def create_booking(games: list, board: dict, allow_partial: bool = False,
                   booking_status: str | None = None,
                   original_games: list | None = None,
                   replacements: list | None = None,
                   predicted_odds: float | None = None,
                   ticket_type: str = "accumulator",
                   now: datetime | None = None) -> dict:
    """Book one tier. Returns a record describing what happened, always.

    Failure is a first-class outcome here rather than an exception: a tier
    that cannot be booked still has to publish its picks, with an honest note
    instead of a code.
    """
    timing_started = time.perf_counter()
    timings: dict[str, int] = {}

    def elapsed_ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)

    def finished(payload: dict) -> dict:
        timings["total"] = elapsed_ms(timing_started)
        payload["timing_ms"] = dict(timings)
        return payload

    current = now or datetime.now(timezone.utc)
    priced_at = current.isoformat()
    original_games = original_games or games
    replacements = replacements or []
    kickoff_states = [game_kickoff_lifecycle(game, current) for game in games]
    if "invalid" in kickoff_states:
        return finished({"status": "stale", "booking_status": "UNAVAILABLE",
                         "share_code": None, "share_url": None,
                         "failure_category": "KICKOFF_MISMATCH",
                         "reason": "a fixture has no valid kickoff time",
                         "priced_at": priced_at})
    if "started" in kickoff_states:
        return finished({"status": "started", "booking_status": "UNAVAILABLE",
                         "share_code": None, "share_url": None,
                         "failure_category": "FIXTURE_STARTED",
                         "reason": "a fixture has already started",
                         "priced_at": priced_at})
    if "kickoff_buffer" in kickoff_states:
        return finished({"status": "kickoff_buffer",
                         "booking_status": "UNAVAILABLE",
                         "share_code": None, "share_url": None,
                         "failure_category": "KICKOFF_BUFFER",
                         "reason": "a fixture starts within 20 minutes",
                         "priced_at": priced_at})
    stage_started = time.perf_counter()
    selections, unmapped = selections_for(games, board)
    timings["selection_mapping"] = elapsed_ms(stage_started)
    base = {
        "booking_status": "UNAVAILABLE",
        "original_leg_count": len(original_games),
        "booked_leg_count": len(selections),
        "excluded_leg_count": len(unmapped),
        "replacement_count": len(replacements),
        "predicted_tier_odds": predicted_odds,
        "actual_sportybet_odds": None,
        "board_snapshot_id": ((board.get("__meta__") or {}).get("snapshot_id")
                              if isinstance(board, dict) else None),
        "original_legs": original_games,
        "final_booked_legs": [g for g in games if not any(
            u.get("home_team") == g.get("home_team")
            and u.get("away_team") == g.get("away_team")
            and u.get("market") == g.get("market") for u in unmapped)],
        "excluded_legs": unmapped,
        "replacements": replacements,
        "ticket_type": ticket_type,
    }

    if not selections:
        return finished({**base, "status": "unavailable", "share_code": None, "legs": 0,
                "unmapped": unmapped, "priced_at": priced_at,
                "failure_category": _mapping_failure_category(unmapped),
                "reason": "no leg could be matched to a SportyBet selection"})

    # Partial slips are refused for accumulators. A four-leg code under a
    # five-leg tier is a different bet from the one on the card, and the reader
    # has no way to see the difference once the code is loaded.
    #
    # Singles are the exception, and the distinction is real rather than a
    # convenience. Ten Over 1.5 picks are ten separate bets that happen to be
    # listed together, so a code carrying seven of them is seven of those bets
    # — not a different bet. Refusing the lot because three fixtures could not
    # be matched left that tier with no code at all on 25 August, which helped
    # nobody: the seven bookable picks were perfectly good.
    if unmapped and not allow_partial:
        return finished({**base, "status": "unavailable", "share_code": None,
                "legs": len(selections), "unmapped": unmapped, "priced_at": priced_at,
                "failure_category": _mapping_failure_category(unmapped),
                "reason": (f"{len(unmapped)} of {len(games)} legs could not be "
                           f"matched; a partial slip is not the published tier")})

    stage_started = time.perf_counter()
    try:
        payload = _post_share(selections)
    except Exception as e:
        timings["code_generation"] = elapsed_ms(stage_started)
        logger.warning(f"booking request failed: {e}")
        return finished({**base, "status": "failed", "booking_status": "BOOKING_FAILED",
                "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": priced_at,
                "failure_category": "SPORTYBET_DATA_ERROR",
                "reason": f"booking request failed: {str(e)[:120]}"})
    timings["code_generation"] = elapsed_ms(stage_started)

    if payload.get("bizCode") != 10000:
        return finished({**base, "status": "failed", "booking_status": "BOOKING_FAILED",
                "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": priced_at,
                "failure_category": "CODE_GENERATION_FAILED",
                "reason": f"bookmaker refused: {payload.get('message')}"})

    data = payload.get("data") or {}
    code = data.get("shareCode")
    if not code:
        return finished({**base, "status": "failed", "booking_status": "BOOKING_FAILED",
                "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": priced_at,
                "failure_category": "CODE_GENERATION_FAILED",
                "reason": "response carried no share code"})

    stage_started = time.perf_counter()
    ok, why, actual_odds = validate_code_details(code, selections)
    timings["validation_readback"] = elapsed_ms(stage_started)
    if not ok:
        return finished({**base, "status": "invalid", "booking_status": "VALIDATION_FAILED",
                "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": priced_at,
                "failure_category": _validation_failure_category(why),
                "reason": f"validation failed: {why}"})

    expires = None
    if data.get("deadline"):
        try:
            expires = datetime.fromtimestamp(
                data["deadline"] / 1000.0, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            expires = None

    if not expires:
        return finished({**base, "status": "expired",
                "booking_status": "VALIDATION_FAILED", "share_code": None,
                "legs": len(selections), "unmapped": [],
                "priced_at": priced_at, "failure_category": "CODE_EXPIRED",
                "reason": "SportyBet returned no verifiable code expiry"})
    parsed_expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    if parsed_expiry <= current:
        return finished({**base, "status": "expired",
                "booking_status": "VALIDATION_FAILED", "share_code": None,
                "legs": len(selections), "unmapped": [],
                "priced_at": priced_at, "failure_category": "CODE_EXPIRED",
                "reason": "SportyBet returned an already-expired code"})

    odds_source = "readback" if actual_odds is not None else None
    if actual_odds is None:
        actual_odds = 1.0
        for game in games:
            availability = game.get("sportybet_availability") or {}
            if not availability.get("sportybet_available"):
                from leagues.sportybet import availability_for
                availability = availability_for(
                    board, game.get("home_team", ""), game.get("away_team", ""),
                    game.get("kickoff") or game.get("date") or "",
                    game.get("league") or "", game.get("market") or "",
                )
            price = availability.get("sportybet_odds")
            if price and availability.get("sportybet_available"):
                actual_odds *= float(price)
            else:
                actual_odds = 1.0
                break
        actual_odds = round(actual_odds, 3) if actual_odds > 1.0 else None
        if actual_odds is not None:
            odds_source = "live_board_snapshot"
    if actual_odds is None:
        return finished({**base, "status": "invalid",
                "booking_status": "VALIDATION_FAILED", "share_code": None,
                "legs": len(selections), "unmapped": [],
                "priced_at": priced_at, "failure_category": "ODDS_UNAVAILABLE",
                "reason": "validated code has no verifiable SportyBet odds"})

    final_status = booking_status or ("PARTIAL" if unmapped else "FULL")
    return finished({**base,
        "status": "active",
        "booking_status": final_status,
        "share_code": code,
        "share_url": data.get("shareURL") or f"{_base()}/ng/?shareCode={code}",
        "legs": len(selections),
        "booked_leg_count": len(selections),
        "excluded_leg_count": len(unmapped),
        "actual_sportybet_odds": actual_odds,
        "actual_sportybet_odds_source": odds_source,
        "readback_validation": "PASSED",
        "unmapped": [],
        # Attachment follows the immutable published prediction. The booking
        # variant has its own fingerprint so a rebuilt ticket is not mistaken
        # for a stale code merely because its qualified replacement differs.
        "leg_fingerprint": leg_fingerprint(original_games),
        "booking_variant_fingerprint": leg_fingerprint(games),
        # The prices in a code are the prices at the moment it was made. They
        # drift: a card locked at 08:00 and loaded at 19:00 will not quote the
        # same numbers, so the reader is told when this was priced rather than
        # being shown a figure presented as current.
        "priced_at": priced_at,
        "expires_at": expires,
        # Stated plainly when a singles tier booked only part of itself, so
        # the card can say "7 of 10 picks" rather than implying the code holds
        # everything on screen.
        "partial": bool(unmapped),
        "unbooked": [u["match"] for u in unmapped],
    })


def create_or_reuse_generated_booking(games: list, board: dict,
                                      predicted_odds: float | None = None,
                                      force: bool = False) -> dict:
    """Serialize identical selection sets so concurrent requests reuse one code."""
    selections, _ = selections_for(games, board)
    fingerprint = (selection_fingerprint(selections) if selections
                   else leg_fingerprint(games))
    with _GENERATED_BOOKING_LOCKS_GUARD:
        lock = _GENERATED_BOOKING_LOCKS.setdefault(fingerprint, threading.Lock())
    with lock:
        return _create_or_reuse_generated_booking(
            games, board, predicted_odds=predicted_odds, force=force,
        )


def _create_or_reuse_generated_booking(games: list, board: dict,
                                       predicted_odds: float | None = None,
                                       force: bool = False) -> dict:
    """Return one validated code per exact generated leg set.

    The in-memory API cache is only an optimisation. This persisted fingerprint
    lookup is what prevents a restart or second worker from minting another
    code for an identical slip. Reuse still performs SportyBet readback, so an
    expired or changed code is replaced rather than trusted blindly.
    """
    timing_started = time.perf_counter()
    stage_started = time.perf_counter()
    selections, unmapped = selections_for(games, board)
    selection_ms = round((time.perf_counter() - stage_started) * 1000)
    fingerprint = (selection_fingerprint(selections) if selections
                   else leg_fingerprint(games))
    # A refresh may change the board or selected legs, but it must not mint a
    # second code when the exact deterministic selection fingerprint is still
    # active. Failed/unavailable records are not reused and can recover.
    if selections and not unmapped:
        stage_started = time.perf_counter()
        prior = generated_booking_for(fingerprint)
        persistence_ms = round((time.perf_counter() - stage_started) * 1000)
        code = (prior or {}).get("share_code")
        prior_checked = booking_lifecycle(prior, games)
        if prior_checked and prior_checked.get("actionable") and code:
            stage_started = time.perf_counter()
            ok, _, actual_odds = validate_code_details(code, selections)
            validation_ms = round((time.perf_counter() - stage_started) * 1000)
            if ok:
                reused = dict(prior)
                reused.update({
                    "code_reused": True,
                    "readback_validation": "PASSED",
                    "sportybet_selection_fingerprint": fingerprint,
                })
                if actual_odds is not None:
                    reused["actual_sportybet_odds"] = actual_odds
                reused["timing_ms"] = {
                    "selection_mapping": selection_ms,
                    "code_generation": 0,
                    "validation_readback": validation_ms,
                    "database_persistence": persistence_ms,
                    "total": round((time.perf_counter() - timing_started) * 1000),
                }
                return reused

    record = create_booking(
        games, board, booking_status="FULL", predicted_odds=predicted_odds)
    record["code_reused"] = False
    record["sportybet_selection_fingerprint"] = fingerprint
    create_timings = record.get("timing_ms") or {}
    persistence_ms = 0
    if record.get("status") == "active":
        stage_started = time.perf_counter()
        _store_generated_booking(fingerprint, record)
        persistence_ms = round((time.perf_counter() - stage_started) * 1000)
    record["timing_ms"] = {
        "selection_mapping": selection_ms + create_timings.get("selection_mapping", 0),
        "code_generation": create_timings.get("code_generation", 0),
        "validation_readback": create_timings.get("validation_readback", 0),
        "database_persistence": persistence_ms,
        "total": round((time.perf_counter() - timing_started) * 1000),
    }
    return record


def _qualified_shape(game: dict) -> dict:
    shaped = dict(game)
    shaped["market_group"] = (game.get("market_group")
                              or game.get("prediction_type") or "other")
    shaped.setdefault("odds_are_real", True)
    shaped.setdefault("expected_value", 0.0)
    shaped.setdefault("market_margin", None)
    shaped.setdefault("safe_tier_eligible", False)
    return shaped


def _revalidate_games(games: list, board: dict) -> tuple[list, list]:
    """Copy and enrich games against one booking-time board snapshot."""
    from leagues.sportybet import availability_for
    good, bad = [], []
    for original in games or []:
        game = _qualified_shape(original)
        availability = availability_for(
            board, game.get("home_team", ""), game.get("away_team", ""),
            game.get("kickoff") or game.get("date") or "",
            game.get("league") or "", game.get("market") or "")
        game["sportybet_availability"] = availability
        game["bookable"] = bool(availability.get("sportybet_available"))
        if game["bookable"]:
            # Replacement selection is evaluated with the exact price which
            # will be booked, while confidence/calibration remain untouched.
            game["odds"] = availability["sportybet_odds"]
            game["real_odds"] = availability["sportybet_odds"]
            game["odds_are_real"] = True
            good.append(game)
        else:
            bad.append(game)
    return good, bad


def _select_bookable_variant(candidates: list, rule: dict) -> tuple[list, float, float]:
    from leagues.selection import select_accumulator, select_banker, select_rollover_day
    pool = [g for g in candidates if (not rule.get("safe_only")
                                      or g.get("safe_tier_eligible"))]
    selector = rule.get("selector")
    if selector == "banker":
        return select_banker(pool, canonicalize=False)
    if selector == "rollover":
        return select_rollover_day(pool)
    if selector == "over_1_5":
        chosen = sorted(
            [g for g in pool if g.get("market") == "over_1_5"
             and g.get("confidence", 0) >= rule.get("min_confidence", 0)],
            key=lambda g: (-g.get("confidence", 0), g.get("match_id", "")),
        )[:rule.get("max_picks", 10)]
        total, joint = 1.0, 1.0
        for game in chosen:
            total *= game["odds"]
            joint *= game["confidence"]
        return chosen, round(total, 2), round(joint, 4)
    return select_accumulator(
        pool, target_odds=rule.get("target", 2.0),
        max_picks=rule.get("max_picks", 6),
        min_confidence=rule.get("min_confidence", 0.65),
        min_ev=rule.get("min_ev", 0.0),
        prefer=rule.get("prefer", "joint"),
        band_low=rule.get("band_low", 0.80), canonicalize=False)


def _replacement_details(original: list, final: list, unavailable: list) -> list:
    def signature(g):
        return (g.get("match_id"), g.get("market"))
    original_keys = {signature(g) for g in original}
    additions = [g for g in final if signature(g) not in original_keys]
    details = []
    for index, replacement in enumerate(additions):
        removed = unavailable[index] if index < len(unavailable) else None
        details.append({
            "original_leg": removed,
            "replacement_leg": replacement,
            "reason": ((removed or {}).get("sportybet_availability") or {}).get(
                "status") or "unavailable on SportyBet",
        })
    return details


def _select_replacements(available: list, candidates: list,
                         unavailable_count: int, rule: dict,
                         original_count: int,
                         excluded_fixtures: set | None = None) -> list:
    """Fill only missing slots, then verify with the tier's real selector."""
    if unavailable_count <= 0:
        return available
    used_fixtures = {g.get("match_id") for g in available}
    excluded_fixtures = excluded_fixtures or set()
    used_signatures = {(g.get("match_id"), g.get("market")) for g in available}
    pool = [g for g in candidates
            if g.get("match_id") not in used_fixtures
            and g.get("match_id") not in excluded_fixtures
            and (g.get("match_id"), g.get("market")) not in used_signatures]
    pool.sort(key=lambda g: (-g.get("confidence", 0),
                             g.get("market_margin") is None,
                             g.get("market_margin") or 99,
                             g.get("match_id", ""), g.get("market", "")))
    # Replacement gaps are normally one or two. Bound the combinatorial check
    # while preserving enough market/price variety for long tiers.
    cap = (60 if unavailable_count == 1 else
           36 if unavailable_count == 2 else
           (18 if unavailable_count == 3 else unavailable_count + 6))
    pool = pool[:cap]
    best, best_key = [], None
    for additions in itertools.combinations(pool, unavailable_count):
        combo = list(available) + list(additions)
        if len(combo) != original_count:
            continue
        chosen, total, joint = _select_bookable_variant(combo, rule)
        chosen_keys = {(g.get("match_id"), g.get("market")) for g in chosen}
        combo_keys = {(g.get("match_id"), g.get("market")) for g in combo}
        if len(chosen) != original_count or chosen_keys != combo_keys:
            continue
        target = float(rule.get("target") or total or 1)
        key = (joint, -abs(total - target),
               tuple(sorted(f"{g.get('match_id')}|{g.get('market')}"
                            for g in additions)))
        if best_key is None or key > best_key:
            best, best_key = combo, key
    return best


def book_card(publish_date: str, accumulators: dict,
              force: bool = False) -> dict:
    """Book every tier on the day's card. Idempotent.

    A tier already holding a valid code is left alone, so this can be re-run
    without minting duplicates — which matters because the daily job may be
    retried and the in-process loop calls the same path.
    """
    from leagues import sportybet

    existing = bookings_for(publish_date)
    try:
        board = sportybet.fetch_board(force=True)
    except TypeError:  # compact test doubles and older adapters
        board = sportybet.fetch_board()
    report = {"date": publish_date, "booked": [], "skipped": [], "failed": []}

    if not board:
        report["failed"].append("no bookmaker board available")
        return report

    snapshot = ((accumulators or {}).get("_booking_candidates") or {}).get(
        "games") or []
    bookable_candidates, _ = _revalidate_games(snapshot, board)
    if snapshot:
        _audit(publish_date, "_qualified_pool", "QUALIFIED", snapshot, once=True)

    # Reserve every fixture already assigned to another accumulator before
    # looking for SportyBet replacements. Without this second-stage guard, a
    # clean model card could become concentrated again during booking.
    portfolio_originals = {
        tier: {
            game.get("match_id") for game in (data.get("games") or [])
            if game.get("match_id")
        }
        for tier, data in (accumulators or {}).items()
        if (not tier.startswith("_") and tier != "over_1_5"
            and isinstance(data, dict))
    }
    claimed_replacements: set = set()

    for tier, data in (accumulators or {}).items():
        if tier.startswith("_"):
            continue
        if not isinstance(data, dict):
            continue
        games = data.get("games") or []
        if tier == "rollover" and not games:
            pending = next((d for d in (data.get("days") or [])
                            if d.get("date") == publish_date
                            and d.get("status") == "pending"), None)
            games = [{
                **pick,
                "market": pick.get("market_key") or pick.get("market"),
                "prediction_type": pick.get("market"),
                "kickoff": pick.get("commence_time"),
            } for pick in ((pending or {}).get("picks") or [])]
            if games and not data.get("booking_rule"):
                data = dict(data, booking_rule={"selector": "rollover",
                                                "safe_only": True})
        if not games:
            continue

        prior = existing.get(tier) or {}
        # A held code is reused only while it still describes this tier. If the
        # tier was extended or rebuilt since, the old code is for a different
        # slip and has to be replaced rather than skipped over.
        prior_checked = booking_lifecycle(prior, games)
        if prior_checked and prior_checked.get("actionable") and not force:
            report["skipped"].append(f"{tier}: {prior.get('share_code')}")
            if tier != "over_1_5":
                claimed_replacements.update(
                    game.get("match_id")
                    for game in (prior.get("final_booked_legs") or games)
                    if game.get("match_id")
                )
            continue

        predicted_odds = data.get("total_odds")
        available_original, unavailable_original = _revalidate_games(games, board)

        if not unavailable_original:
            record = create_booking(
                available_original, board, booking_status="FULL",
                original_games=games, predicted_odds=predicted_odds,
                ticket_type=data.get("sportybet_ticket_type", "accumulator"))
        else:
            # Replacement is selected only from the locked, already-qualified
            # snapshot and with the exact same tier rule captured at publish.
            rule = data.get("booking_rule") or {}
            excluded = set(claimed_replacements)
            if tier != "over_1_5":
                for other_tier, fixture_ids in portfolio_originals.items():
                    if other_tier != tier:
                        excluded.update(fixture_ids)
            rebuilt = _select_replacements(
                available_original, bookable_candidates,
                len(unavailable_original), rule, len(games),
                excluded_fixtures=excluded)
            if rebuilt:
                replacements = _replacement_details(
                    games, rebuilt, unavailable_original)
                record = create_booking(
                    rebuilt, board, booking_status="REBUILT_FULL",
                    original_games=games, replacements=replacements,
                    predicted_odds=predicted_odds,
                    ticket_type=data.get("sportybet_ticket_type", "accumulator"))
            else:
                minimum = 1 if tier in ("banker", "over_1_5") else 2
                if len(available_original) >= minimum:
                    record = create_booking(
                        available_original, board, allow_partial=True,
                        booking_status="PARTIAL", original_games=games,
                        predicted_odds=predicted_odds,
                        ticket_type=data.get("sportybet_ticket_type", "accumulator"))
                    record["excluded_legs"] = unavailable_original
                    record["excluded_leg_count"] = len(unavailable_original)
                    record["partial"] = True
                else:
                    record = {
                        "status": "unavailable", "booking_status": "UNAVAILABLE",
                        "share_code": None, "legs": len(available_original),
                        "original_leg_count": len(games),
                        "booked_leg_count": 0,
                        "excluded_leg_count": len(unavailable_original),
                        "replacement_count": 0,
                        "predicted_tier_odds": predicted_odds,
                        "actual_sportybet_odds": None,
                        "board_snapshot_id": (sportybet.board_metadata(board).get(
                            "snapshot_id")),
                        "original_legs": games, "final_booked_legs": [],
                        "excluded_legs": unavailable_original,
                        "replacements": [],
                        "reason": "no valid full, rebuilt, or partial ticket",
                    }
        _store(publish_date, tier, record)
        if tier != "over_1_5":
            claimed_replacements.update(
                game.get("match_id")
                for game in (record.get("final_booked_legs") or [])
                if game.get("match_id")
            )
        _audit(publish_date, tier, record.get("booking_status", "UNAVAILABLE"),
               games, record.get("reason"))
        if record["status"] == "active":
            report["booked"].append(f"{tier}: {record['share_code']}")
        else:
            report["failed"].append(f"{tier}: {record.get('reason', '')[:90]}")

    logger.info(
        f"bookings {publish_date}: {len(report['booked'])} booked, "
        f"{len(report['skipped'])} already held, {len(report['failed'])} failed")
    return report


def finalize_prepublication_card(publish_date: str,
                                 accumulators: dict) -> dict:
    """Book first, then promote an exact rebuilt variant before card lock.

    A replacement made after publication is only a booking convenience and
    must never rewrite the official prediction.  Before first write, however,
    a fully validated quality-equivalent replacement can become the official
    product itself.  Normal FULL tiers are unchanged; PARTIAL/failed bookings
    never mutate prediction truth.
    """
    from math import prod
    from leagues.selection_quality import selection_probability

    report = book_card(publish_date, accumulators)
    stored = bookings_for(publish_date)
    promoted = []
    for tier, data in (accumulators or {}).items():
        if (tier.startswith("_") or tier in {"over_1_5", "rollover"}
                or not isinstance(data, dict)):
            continue
        record = stored.get(tier) or {}
        if (record.get("status") != "active"
                or record.get("booking_status") != "REBUILT_FULL"):
            continue
        final_games = record.get("final_booked_legs") or []
        if not final_games or len(final_games) != len(data.get("games") or []):
            continue

        replacements = list(record.get("replacements") or [])
        data["games"] = final_games
        data["total_odds"] = round(prod(
            float(game.get("odds") or 1) for game in final_games
        ), 2)
        data["hit_probability"] = round(prod(
            selection_probability(game) for game in final_games
        ), 4)
        data["prepublication_replacements"] = replacements
        data["prepublication_booking_status"] = "REBUILT_FULL"

        # The promoted set is now the official card.  Normalize the stored
        # booking identity so the scheduled booking step reuses this exact
        # validated code instead of treating it as a post-lock variant.
        fingerprint = leg_fingerprint(final_games)
        normalized = {
            **record,
            "booking_status": "FULL",
            "leg_fingerprint": fingerprint,
            "booking_variant_fingerprint": fingerprint,
            "original_legs": final_games,
            "original_leg_count": len(final_games),
            "predicted_tier_odds": data["total_odds"],
            "prepublication_replacements": replacements,
        }
        _store(publish_date, tier, normalized)
        promoted.append(tier)
    return {**report, "promoted_before_lock": promoted}


def attach_bookings(publish_date: str, accumulators: dict,
                    now: datetime | None = None) -> dict:
    """Hang stored codes on the card. Read-only — never books.

    Serving the card must not create bookings: a page load would then POST to
    a bookmaker, and two readers could hold different codes for one tier.
    """
    stored = bookings_for(publish_date)
    if not stored:
        return accumulators
    for tier, data in (accumulators or {}).items():
        if not isinstance(data, dict):
            continue
        record = stored.get(tier)
        if not record:
            continue
        data["booking"] = booking_lifecycle(
            record, data.get("games") or [], now
        )
    return accumulators
