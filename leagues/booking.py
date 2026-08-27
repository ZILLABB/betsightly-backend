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
import urllib.request
from datetime import datetime, timezone

from leagues.sportybet import MARKET_TO_SPORTYBET

logger = logging.getLogger(__name__)

BASE_URL = None  # resolved from the adapter so there is one host to change


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

    raw_odds = (data.get("ticket") or {}).get("displayTotalOdds")
    if raw_odds is None:
        raw_odds = (data.get("ticket") or {}).get("totalOdds")
    try:
        actual_odds = round(float(raw_odds), 3)
    except (TypeError, ValueError):
        actual_odds = None
    return True, "ok", actual_odds


def create_booking(games: list, board: dict, allow_partial: bool = False,
                   booking_status: str | None = None,
                   original_games: list | None = None,
                   replacements: list | None = None,
                   predicted_odds: float | None = None,
                   ticket_type: str = "accumulator") -> dict:
    """Book one tier. Returns a record describing what happened, always.

    Failure is a first-class outcome here rather than an exception: a tier
    that cannot be booked still has to publish its picks, with an honest note
    instead of a code.
    """
    now = datetime.now(timezone.utc).isoformat()
    original_games = original_games or games
    replacements = replacements or []
    selections, unmapped = selections_for(games, board)
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
        return {**base, "status": "unavailable", "share_code": None, "legs": 0,
                "unmapped": unmapped, "priced_at": now,
                "reason": "no leg could be matched to a SportyBet selection"}

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
        return {**base, "status": "unavailable", "share_code": None,
                "legs": len(selections), "unmapped": unmapped, "priced_at": now,
                "reason": (f"{len(unmapped)} of {len(games)} legs could not be "
                           f"matched; a partial slip is not the published tier")}

    try:
        payload = _post_share(selections)
    except Exception as e:
        logger.warning(f"booking request failed: {e}")
        return {**base, "status": "failed", "booking_status": "BOOKING_FAILED",
                "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": now,
                "reason": f"booking request failed: {str(e)[:120]}"}

    if payload.get("bizCode") != 10000:
        return {**base, "status": "failed", "booking_status": "BOOKING_FAILED",
                "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": now,
                "reason": f"bookmaker refused: {payload.get('message')}"}

    data = payload.get("data") or {}
    code = data.get("shareCode")
    if not code:
        return {**base, "status": "failed", "booking_status": "BOOKING_FAILED",
                "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": now,
                "reason": "response carried no share code"}

    ok, why, actual_odds = validate_code_details(code, selections)
    if not ok:
        return {**base, "status": "invalid", "booking_status": "VALIDATION_FAILED",
                "share_code": None, "legs": len(selections),
                "unmapped": [], "priced_at": now,
                "reason": f"validation failed: {why}"}

    expires = None
    if data.get("deadline"):
        try:
            expires = datetime.fromtimestamp(
                data["deadline"] / 1000.0, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            expires = None

    if actual_odds is None:
        actual_odds = 1.0
        for game in games:
            availability = game.get("sportybet_availability") or {}
            price = availability.get("sportybet_odds")
            if price and availability.get("sportybet_available"):
                actual_odds *= float(price)
        actual_odds = round(actual_odds, 3) if actual_odds > 1.0 else None

    final_status = booking_status or ("PARTIAL" if unmapped else "FULL")
    return {**base,
        "status": "active",
        "booking_status": final_status,
        "share_code": code,
        "share_url": data.get("shareURL") or f"{_base()}/ng/?shareCode={code}",
        "legs": len(selections),
        "booked_leg_count": len(selections),
        "excluded_leg_count": len(unmapped),
        "actual_sportybet_odds": actual_odds,
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
        "priced_at": now,
        "expires_at": expires,
        # Stated plainly when a singles tier booked only part of itself, so
        # the card can say "7 of 10 picks" rather than implying the code holds
        # everything on screen.
        "partial": bool(unmapped),
        "unbooked": [u["match"] for u in unmapped],
    }


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
        return select_banker(pool)
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
        band_low=rule.get("band_low", 0.80))


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
                         original_count: int) -> list:
    """Fill only missing slots, then verify with the tier's real selector."""
    if unavailable_count <= 0:
        return available
    used_fixtures = {g.get("match_id") for g in available}
    used_signatures = {(g.get("match_id"), g.get("market")) for g in available}
    pool = [g for g in candidates
            if g.get("match_id") not in used_fixtures
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
        unchanged = (prior.get("leg_fingerprint") == leg_fingerprint(games))
        if prior.get("status") == "active" and unchanged and not force:
            report["skipped"].append(f"{tier}: {prior.get('share_code')}")
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
            rebuilt = _select_replacements(
                available_original, bookable_candidates,
                len(unavailable_original), rule, len(games))
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
