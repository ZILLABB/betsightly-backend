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
import logging
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BASE_URL = None  # resolved from the adapter so there is one host to change


# Our market vocabulary mapped onto SportyBet's. Verified against the live
# board: outcome ids are stable per market, and Over/Under is distinguished by
# its specifier rather than by a distinct market id.
MARKET_TO_SPORTYBET = {
    "home_win":     ("1", "", "1"),
    "draw":         ("1", "", "2"),
    "away_win":     ("1", "", "3"),
    "home_or_draw": ("10", "", "9"),
    "home_or_away": ("10", "", "10"),
    "away_or_draw": ("10", "", "11"),
    "over_1_5":     ("18", "total=1.5", "12"),
    "under_1_5":    ("18", "total=1.5", "13"),
    "over_2_5":     ("18", "total=2.5", "12"),
    "under_2_5":    ("18", "total=2.5", "13"),
    "over_3_5":     ("18", "total=3.5", "12"),
    "under_3_5":    ("18", "total=3.5", "13"),
    "btts_yes":     ("29", "", "74"),
    "btts_no":      ("29", "", "76"),
}


def _base() -> str:
    from leagues.sportybet import BASE_URL as SB
    return SB


def _oper_id() -> str:
    from leagues.sportybet import OPER_ID
    return OPER_ID


# ── Storage ────────────────────────────────────────────────

def _ensure_table(conn) -> None:
    from sqlalchemy import text
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
                "j": json.dumps(record)[:4000],
                "a": datetime.now(timezone.utc).isoformat(),
            }
            updated = conn.execute(text(
                "UPDATE tier_bookings SET share_code=:c, share_url=:u, legs=:l,"
                " status=:s, detail=:j, created_at=:a"
                " WHERE publish_date=:d AND tier=:t"), params).rowcount
            if not updated:
                conn.execute(text(
                    "INSERT INTO tier_bookings"
                    " (publish_date, tier, share_code, share_url, legs, status,"
                    "  detail, created_at)"
                    " VALUES (:d, :t, :c, :u, :l, :s, :j, :a)"), params)
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
        logger.debug(f"booking lookup failed: {e}")
        return {}
    for tier, detail in rows:
        try:
            out[tier] = json.loads(detail) if detail else {}
        except (TypeError, ValueError):
            continue
    return out


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
        mapping = MARKET_TO_SPORTYBET.get(market) if market else None
        if not mapping:
            unmapped.append({"match": f"{home} v {away}",
                             "reason": f"market not bookable: {market!r}"})
            continue
        hit = sportybet.lookup(board, home, away, g.get("kickoff") or "")
        if not hit:
            unmapped.append({"match": f"{home} v {away}",
                             "reason": "fixture not found on the board"})
            continue
        market_id, specifier, outcome_id = mapping
        selections.append({
            "eventId": hit["event_id"],
            "marketId": market_id,
            "outcomeId": outcome_id,
            "specifier": specifier or None,
        })
    return selections, unmapped


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
    """Read the code back and confirm it is the slip we asked for.

    HTTP 200 means the request was accepted, not that the right slip exists.
    A dropped or substituted leg would otherwise reach a reader as a code that
    looks fine and stakes something they never chose.
    """
    try:
        payload = _read_share(code)
    except Exception as e:
        return False, f"could not read back: {str(e)[:80]}"

    if payload.get("bizCode") != 10000:
        return False, f"code did not resolve: {payload.get('message')}"

    data = payload.get("data") or {}
    got = (data.get("ticket") or {}).get("selections") or []
    if len(got) != len(expected):
        return False, f"expected {len(expected)} legs, code holds {len(got)}"

    def key(sel):
        return (str(sel.get("eventId")), str(sel.get("marketId")),
                str(sel.get("outcomeId")), str(sel.get("specifier") or ""))

    if {key(s) for s in got} != {key(s) for s in expected}:
        return False, "selections in the code do not match the tier"

    unavailable = data.get("unavailableOutcomes") or []
    if unavailable:
        return False, f"{len(unavailable)} selection(s) already unavailable"

    return True, "ok"


def create_booking(games: list, board: dict) -> dict:
    """Book one tier. Returns a record describing what happened, always.

    Failure is a first-class outcome here rather than an exception: a tier
    that cannot be booked still has to publish its picks, with an honest note
    instead of a code.
    """
    now = datetime.now(timezone.utc).isoformat()
    selections, unmapped = selections_for(games, board)

    if not selections:
        return {"status": "unavailable", "share_code": None, "legs": 0,
                "unmapped": unmapped, "priced_at": now,
                "reason": "no leg could be matched to a SportyBet selection"}

    # Partial slips are refused. A four-leg code under a five-leg tier is a
    # different bet from the one on the card, and the reader has no way to see
    # the difference once the code is loaded.
    if unmapped:
        return {"status": "unavailable", "share_code": None,
                "legs": len(selections), "unmapped": unmapped, "priced_at": now,
                "reason": (f"{len(unmapped)} of {len(games)} legs could not be "
                           f"matched; a partial slip is not the published tier")}

    try:
        payload = _post_share(selections)
    except Exception as e:
        logger.warning(f"booking request failed: {e}")
        return {"status": "failed", "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": now,
                "reason": f"booking request failed: {str(e)[:120]}"}

    if payload.get("bizCode") != 10000:
        return {"status": "failed", "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": now,
                "reason": f"bookmaker refused: {payload.get('message')}"}

    data = payload.get("data") or {}
    code = data.get("shareCode")
    if not code:
        return {"status": "failed", "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": now,
                "reason": "response carried no share code"}

    ok, why = validate_code(code, selections)
    if not ok:
        return {"status": "invalid", "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": now,
                "reason": f"validation failed: {why}"}

    expires = None
    if data.get("deadline"):
        try:
            expires = datetime.fromtimestamp(
                data["deadline"] / 1000.0, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            expires = None

    return {
        "status": "active",
        "share_code": code,
        "share_url": data.get("shareURL") or f"{_base()}/ng/?shareCode={code}",
        "legs": len(selections),
        "unmapped": [],
        "leg_fingerprint": leg_fingerprint(games),
        # The prices in a code are the prices at the moment it was made. They
        # drift: a card locked at 08:00 and loaded at 19:00 will not quote the
        # same numbers, so the reader is told when this was priced rather than
        # being shown a figure presented as current.
        "priced_at": now,
        "expires_at": expires,
    }


def book_card(publish_date: str, accumulators: dict,
              force: bool = False) -> dict:
    """Book every tier on the day's card. Idempotent.

    A tier already holding a valid code is left alone, so this can be re-run
    without minting duplicates — which matters because the daily job may be
    retried and the in-process loop calls the same path.
    """
    from leagues import sportybet

    existing = bookings_for(publish_date)
    board = sportybet.fetch_board()
    report = {"date": publish_date, "booked": [], "skipped": [], "failed": []}

    if not board:
        report["failed"].append("no bookmaker board available")
        return report

    for tier, data in (accumulators or {}).items():
        if not isinstance(data, dict):
            continue
        games = data.get("games") or []
        if not games:
            continue

        prior = existing.get(tier) or {}
        # A held code is reused only while it still describes this tier. If the
        # tier was extended or rebuilt since, the old code is for a different
        # slip and has to be replaced rather than skipped over.
        unchanged = (prior.get("leg_fingerprint") == leg_fingerprint(games))
        if prior.get("status") == "active" and unchanged and not force:
            report["skipped"].append(f"{tier}: {prior.get('share_code')}")
            continue

        record = create_booking(games, board)
        _store(publish_date, tier, record)
        if record["status"] == "active":
            report["booked"].append(f"{tier}: {record['share_code']}")
        else:
            report["failed"].append(f"{tier}: {record.get('reason', '')[:90]}")

    logger.info(
        f"bookings {publish_date}: {len(report['booked'])} booked, "
        f"{len(report['skipped'])} already held, {len(report['failed'])} failed")
    return report


def attach_bookings(publish_date: str, accumulators: dict) -> dict:
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
        # A code minted against different legs is not this tier's code. Rather
        # than hiding it, say so — a reader who copied it earlier needs to
        # know it no longer matches what they are looking at.
        expected = record.get("leg_fingerprint")
        if (record.get("status") == "active" and expected
                and expected != leg_fingerprint(data.get("games") or [])):
            record = dict(record, status="stale", share_code=None,
                          reason=("this tier changed after the code was made; "
                                  "regenerate before staking"))
        data["booking"] = record
    return accumulators
