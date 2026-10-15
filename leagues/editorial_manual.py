"""Admin-curated fallback for empty prediction tiers, kept separate from model history.

Editors choose real SportyBet event IDs and canonical markets. Nothing is
published until the full SportyBet share code is read back and verified.
This database is separate from published_slips to avoid corrupting official
model/calibration/ROI evidence. Existing auto tickets are never overwritten.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from math import prod

from sqlalchemy import text

LOG = logging.getLogger(__name__)
WAT = timezone(timedelta(hours=1))
TIERS = {"banker", "2_odds", "5_odds", "10_odds", "over_1_5", "rollover"}
MAX_LEGS = {"banker": 1, "2_odds": 12, "5_odds": 20,
            "10_odds": 20, "over_1_5": 10, "rollover": 12}
MIN_ODDS = {"banker": 1.01, "2_odds": 2.0, "5_odds": 5.0,
            "10_odds": 10.0, "over_1_5": 1.01, "rollover": 2.0}

# Keep the old database tier key for settlement and historical results.
# Same existing Over Goals tier; home/away totals are 90-minute team goals,
# while BTTS Yes requires one from EACH side. Do not accept unders or BTTS No.
MANUAL_OVER_GOALS = frozenset({
    "over_0_5", "over_1_5", "over_2_5", "over_3_5", "over_4_5",
    "home_over_0_5", "away_over_0_5",
    "home_over_1_5", "away_over_1_5", "btts_yes",
})

def rollover_eligibility(day: str | None = None, *, card=None, chain=None) -> dict:
    """Rollover may be filled manually only for the next eligible, empty stage."""
    from leagues.rollover_db import load_chain
    from leagues.rollover_lifecycle import chain_state
    from leagues.picks_db import load_card

    day = day or _today()
    if card is None:
        card = load_card(day) or {}
    if chain is None:
        chain = load_chain(day)
    prior = chain.get("days") or []
    decision = chain_state(prior, day)
    has_official = bool((card.get("rollover") or {}).get("selected"))
    # Never put a second rollover stage on the same WAT day, even across chains.
    has_slot = any(str(slot.get("date")) == day for slot in prior)
    allowed = bool(decision.get("can_generate") and not has_official and not has_slot)
    return {
        "allowed": allowed,
        "date": day,
        "day_number": decision.get("day_number"),
        "chain_start_date": day if decision.get("new_chain") else chain.get("start_date", day),
        "reason": (
            "An engine Rollover stage is already published today." if has_official
            else "A Rollover stage already exists for today." if has_slot
            else f"Rollover is not eligible: {decision['status']}." if not decision.get("can_generate")
            else None
        ),
        "challenge_status": decision.get("status"),
    }


def _rollover_day_picks(games: list[dict]) -> list[dict]:
    """Preserve canonical markets and booking identity for the chain settler."""
    return [{
        "match_id": g["match_id"],
        "sportybet_event_id": g["sportybet_event_id"],
        "home_team": g["home_team"], "away_team": g["away_team"],
        "match": f"{g['home_team']} vs {g['away_team']}",
        "league": g.get("league"), "commence_time": g["kickoff"],
        "prediction": g["prediction"],
        "market": g.get("prediction_type", "editorial"),
        "market_key": g["market"],
        "bookable": True, "odds_are_real": True,
        "odds": g["odds"], "status": "pending",
        "editorial_manual": True, "source": "admin_curated",
        "model_probability_available": False, "confidence": None,
    } for g in games]


def _over_display_conflict(card: dict, tier: str, replace: bool) -> bool:
    if replace and tier != "over_1_5":
        raise ValueError("Only Over Goals can replace a current tier's display")
    return bool((card.get(tier) or {}).get("selected")) and not replace

def _avoid_original_over_games(games: list, card: dict) -> None:
    original = (card.get("over_1_5") or {}).get("games") or []
    ids = {str(g.get("sportybet_event_id")) for g in original if g.get("sportybet_event_id")}
    ids |= {str(g.get("match_id")) for g in original if g.get("match_id")}
    if any(str(g.get("sportybet_event_id")) in ids or
           str(g.get("match_id")) in ids for g in games):
        raise ValueError("This match is on today's original Over Goals slip. "
                         "Choose a different fixture; the original remains in Results.")

def _now():
    return datetime.now(timezone.utc)

def _today():
    return _now().astimezone(WAT).date().isoformat()

def _engine():
    from database import engine
    return engine

def _ensure(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS editorial_tier_slips (
            publish_date VARCHAR(10) NOT NULL,
            tier VARCHAR(24) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            detail TEXT NOT NULL,
            PRIMARY KEY (publish_date, tier)
        )
    """))

def parse_input(lines: str, tier: str) -> list[tuple[str, str]]:
    """Accepted lines: SportyBet event ID,canonical_market (also CSV files)."""
    from leagues.sportybet import MARKET_TO_SPORTYBET
    if tier not in TIERS:
        raise ValueError("Unknown prediction tier")
    results = []
    for n, line in enumerate(lines.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        columns = [value.strip().strip('"') for value in line.split(",")]
        if len(columns) != 2:
            raise ValueError(f"Row {n}: expected event_id,market")
        event, market = columns
        if event.lower() in {"event_id", "sportybet_event_id", "id"} and market.lower() == "market":
            continue
        if not event or len(event) > 60 or not event.isascii() or any(
                c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ:-_"
                for c in event):
            raise ValueError(f"Row {n}: invalid SportyBet event ID")
        aliases = {
            alias: "over_" + line.replace(".", "_")
            for line in ("0.5", "1.5", "2.5", "3.5", "4.5")
            for alias in (line, "o" + line, "over " + line,
                          "over" + line, "over_" + line.replace(".", "_"))
        }
        market = aliases.get(market.lower().strip(), market.lower().strip().replace(" ", "_"))
        if market not in MARKET_TO_SPORTYBET:
            raise ValueError(f"Row {n}: {market!r} is not a mapped SportyBet market")
        if tier == "over_1_5" and market not in MANUAL_OVER_GOALS:
            raise ValueError("Over Goals only accepts match-total Overs, individual-team "
                             "Over 0.5/1.5 or BTTS Yes when available at SportyBet")
        if (event, market) in results or any(e == event for e, _ in results):
            raise ValueError(f"Row {n}: fixture repeated in the same ticket")
        results.append((event, market))
    if not results or len(results) > MAX_LEGS[tier]:
        raise ValueError(f"Enter 1–{MAX_LEGS[tier]} distinct fixtures for {tier}")
    if tier == "banker" and len(results) != 1:
        raise ValueError("Banker requires exactly one selection")
    return results

def _current_bookable_games(requested: list[tuple[str, str]], board: dict,
                            *, now=None, date=None) -> list[dict]:
    """Resolve by exact SportyBet event IDs, not ambiguous team-name matching."""
    from leagues.sportybet import _board_entries, availability_for
    from leagues.market_registry import MARKETS

    at = now or _now()
    target = date or at.astimezone(WAT).date().isoformat()
    ids = {event for event, _ in requested}
    entries = {}
    for _, entry in _board_entries(board):
        key = str(entry.get("event_id") or "")
        if key in ids:
            if key in entries:
                raise ValueError(f"SportyBet event {key} appears more than once")
            entries[key] = entry
    games = []
    for event_id, market in requested:
        entry = entries.get(event_id)
        if not entry:
            raise ValueError(f"SportyBet event {event_id} not on the live board")
        kickoff_ms = entry.get("kickoff_ms")
        try:
            kickoff = datetime.fromtimestamp(float(kickoff_ms) / 1000, timezone.utc)
        except (TypeError, ValueError, OSError):
            raise ValueError(f"SportyBet event {event_id} has no valid kickoff")
        if kickoff <= at + timedelta(minutes=20):
            raise ValueError(f"SportyBet event {event_id} started or is too close to kickoff")
        if kickoff.astimezone(WAT).date().isoformat() != target:
            raise ValueError(f"SportyBet event {event_id} is not on {target} WAT")
        home, away = str(entry["home_team"]), str(entry["away_team"])
        league = str(entry.get("competition") or "Football")[:120]
        availability = availability_for(
            board, home, away, kickoff.isoformat(), league, market,
            event_id=event_id,
        )
        if not availability.get("sportybet_available"):
            raise ValueError(
                f"{event_id} {market}: {availability.get('failure_reason') or availability.get('status')}"
            )
        price = float(availability["sportybet_odds"])
        if not math.isfinite(price) or price <= 1:
            raise ValueError(f"{event_id}: invalid market price")
        spec = MARKETS.get(market)
        label = (spec.label if spec is not None else market)
        try:
            readable = label.format(home=home, away=away)
        except (ValueError, KeyError):
            readable = market.replace("_", " ").title()
        game = {
            "match_id": f"sportybet:{event_id}",
            "sportybet_event_id": event_id,
            "fixture_id": int(event_id) if event_id.isdigit() else 0,
            "selection_id": f"sportybet:{event_id}:{market}",
            "home_team": home, "away_team": away,
            "league": league, "kickoff": kickoff.isoformat(),
            "date": kickoff.isoformat(), "market": market,
            "prediction": readable,
            "prediction_type": getattr(spec, "group", "editorial"),
            "odds": price, "real_odds": price,
            "odds_are_real": True, "odds_provider": "SportyBet",
            "bookable": True, "bookmaker": "SportyBet",
            "sportybet_availability": availability,
            "editorial_manual": True,
            "model_probability_available": False,
            "model_sources": ["Admin curated · bookmaker verified"],
        }
        games.append(game)
    return games

def check_tier_target(tier: str, total_odds: float, count: int) -> None:
    if count > MAX_LEGS[tier]:
        raise ValueError("Too many selections for this tier")
    if tier == "rollover" and total_odds > 4.0 + 1e-8:
        raise ValueError("Rollover must stay within 2.00x–4.00x verified odds")
    if total_odds + 1e-8 < MIN_ODDS[tier]:
        raise ValueError(
            f"{tier} must reach {MIN_ODDS[tier]:.2f}x verified odds, "
            f"current total is {total_odds:.2f}x"
        )

def _claimed_identifiers(card: dict, booking_rows: dict, manual_rows: dict,
                         *, exclude: str = "") -> set[str]:
    ids = set()
    for tier, data in (card or {}).items():
        if tier == exclude or not isinstance(data, dict) or not data.get("selected"):
            continue
        for g in data.get("games") or []:
            if g.get("sportybet_event_id"):
                ids.add(str(g["sportybet_event_id"]))
            if g.get("match_id"):
                ids.add(str(g["match_id"]))
    for tier, booking in (booking_rows or {}).items():
        if tier == exclude:
            continue
        for g in booking.get("final_booked_legs") or []:
            if g.get("sportybet_event_id"):
                ids.add(str(g["sportybet_event_id"]))
            if g.get("match_id"):
                ids.add(str(g["match_id"]))
    for tier, data in (manual_rows or {}).items():
        if tier == exclude:
            continue
        for g in data.get("games") or []:
            if g.get("sportybet_event_id"):
                ids.add(str(g["sportybet_event_id"]))
    return ids

def _check_exposure(games, card, booking_rows, manual_rows, *, tier):
    ids = _claimed_identifiers(card, booking_rows, manual_rows, exclude=tier)
    for game in games:
        if (str(game["sportybet_event_id"]) in ids
                or str(game["match_id"]) in ids):
            raise ValueError(
                f"{game['home_team']} vs {game['away_team']} is already used "
                "in a published BetSightly product"
            )

def list_published(date: str | None = None) -> dict[str, dict]:
    """No table creation in customer-facing read requests."""
    date = date or _today()
    try:
        with _engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT tier, detail FROM editorial_tier_slips WHERE publish_date=:d"
            ), {"d": date}).all()
        return {tier: json.loads(detail) for tier, detail in rows}
    except Exception:
        return {}

def preview(tier: str, lines: str, *, board=None, now=None,
            replace_official_over: bool = False) -> dict:
    """Admin-only price preview. Never writes a card or creates a booking."""
    from leagues import sportybet
    from leagues.picks_db import load_card
    from leagues.booking import bookings_for

    at = now or _now()
    day = at.astimezone(WAT).date().isoformat()
    requested = parse_input(lines, tier)
    card = load_card(day) or {}
    if tier == "rollover":
        eligibility = rollover_eligibility(day, card=card)
        if not eligibility["allowed"]:
            raise ValueError(eligibility["reason"])
    if _over_display_conflict(card, tier, replace_official_over):
        raise ValueError(f"{tier} already has an immutable official slip today. "
                         "Choose explicit Over Goals display replacement; "
                         "the original stays in official results.")
    manual = list_published(day)
    if tier in manual:
        raise ValueError(f"{tier} already has a published manual slip")
    live_board = board if board is not None else sportybet.fetch_board(force=True)
    games = _current_bookable_games(requested, live_board, now=at, date=day)
    _check_exposure(games, card, bookings_for(day), manual, tier=tier)
    if replace_official_over:
        _avoid_original_over_games(games, card)
    total = round(prod(g["odds"] for g in games), 3)
    check_tier_target(tier, total, len(games))
    return {
        "status": "PREVIEW", "date": day, "tier": tier,
        "games": games, "total_odds": total,
        "booking_code_created": False, "research_only": False,
        "editorial_manual": True,
        "replaces_official_display": bool(replace_official_over),
        "original_official_record_preserved": True,
    }

def publish(tier: str, lines: str, *,
            replace_official_over: bool = False) -> dict:
    """Full bookmaker readback first, then atomic one-way publication."""
    from leagues import sportybet
    from leagues.booking import create_booking, bookings_for
    from leagues.picks_db import load_card

    inspected = preview(tier, lines, replace_official_over=replace_official_over)
    day, games = inspected["date"], inspected["games"]
    board = sportybet.fetch_board(force=True)
    # Fresh booking-time repricing and kickoff validation.
    revised = _current_bookable_games(parse_input(lines, tier), board, date=day)
    original_card = load_card(day) or {}
    _check_exposure(revised, original_card, bookings_for(day),
                    list_published(day), tier=tier)
    if replace_official_over:
        _avoid_original_over_games(revised, original_card)
    odds = round(prod(g["odds"] for g in revised), 3)
    check_tier_target(tier, odds, len(revised))
    booked = create_booking(
        revised, board, booking_status="FULL",
        original_games=revised, predicted_odds=odds,
        ticket_type="accumulator",
    )
    if (booked.get("status") != "active"
            or booked.get("booking_status") != "FULL"
            or booked.get("readback_validation") != "PASSED"
            or not booked.get("share_code")
            or len(booked.get("final_booked_legs") or []) != len(revised)):
        raise ValueError(
            "SportyBet did not return a verified full-match booking code; "
            "nothing has been published"
        )
    actual = float(booked.get("actual_sportybet_odds") or 0)
    check_tier_target(tier, actual, len(revised))
    payload = {
        "date": day, "tier": tier,
        "editorial_manual": True, "source": "admin_curated",
        "games": revised, "total_odds": actual,
        "booking": booked, "published_at": _now().isoformat(),
        "model_probability_available": False,
        "settlement_track": "editorial_separate",
        "replaces_official_display": bool(replace_official_over),
        "original_official_record_preserved": True,
    }
    with _engine().begin() as conn:
        _ensure(conn)
        # Serialize all manual publication for a day, guarding cross-tier
        # reuse even when admins submit in two tabs simultaneously.
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                         {"k": f"editorial:{day}"})
            # Auto Rollover and editorial writers share a date-scoped lock.
            if tier == "rollover":
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                             {"k": f"rollover:{day}"})
        existing = conn.execute(text(
            "SELECT tier, detail FROM editorial_tier_slips WHERE publish_date=:d"
        ), {"d": day}).all()
        manual = {key: json.loads(value) for key, value in existing}
        if tier in manual:
            raise ValueError("This tier was published in another session")
        locked = conn.execute(text(
            "SELECT payload FROM daily_cards WHERE publish_date=:d"
        ), {"d": day}).scalar()
        card = json.loads(locked) if locked else {}
        if _over_display_conflict(card, tier, replace_official_over):
            raise ValueError("This tier already has an immutable engine slip")
        if replace_official_over:
            _avoid_original_over_games(revised, card)
        # Every originally verified booking keeps its fixture reservation.
        _check_exposure(revised, card, bookings_for(day), manual, tier=tier)
        if tier == "rollover":
            # Enforce the chain progression invariant inside the SAME SQL
            # transaction as the manual publication. No orphaned stages.
            from leagues.rollover_lifecycle import chain_state, allow_append_day
            from leagues.policy_version import PUBLISHED_SELECTION_POLICY_VERSION
            all_days = conn.execute(text(
                "SELECT chain_start_date, day_number, date, status FROM "
                "wc_rollover_days ORDER BY chain_start_date DESC, day_number"
            )).all()
            if any(str(row[2]) == day for row in all_days):
                raise ValueError("Rollover already has a stage on this date")
            start = str(all_days[0][0]) if all_days else day
            previous = [
                {"day_number": row[1], "date": row[2], "status": row[3]}
                for row in all_days if str(row[0]) == start
            ]
            decision = chain_state(previous, day)
            if not decision["can_generate"]:
                raise ValueError(f"Rollover chain blocked: {decision['status']}")
            if decision["new_chain"]:
                start, previous = day, []
            slot = {
                "day_number": decision["day_number"], "date": day, "status": "pending",
                "picks": _rollover_day_picks(revised),
                "combined_odds": actual, "hit_probability": None,
            }
            if not allow_append_day(previous, slot, start):
                raise ValueError("Rollover stage violates the chain order")
            conn.execute(text(
                "INSERT INTO wc_rollover_days "
                "(chain_start_date, day_number, date, picks, combined_odds, "
                "avg_confidence, status, policy_version, created_at, updated_at) "
                "VALUES (:chain, :num, :date, :picks, :odds, :confidence, "
                ":status, :policy, :created, :created)"
            ), {
                "chain": start, "num": slot["day_number"], "date": day,
                "picks": json.dumps(slot["picks"]), "odds": actual,
                "confidence": 0.0, "status": "pending",
                "policy": PUBLISHED_SELECTION_POLICY_VERSION,
                "created": _now().replace(tzinfo=None),
            })
            payload["rollover_chain_start_date"] = start
            payload["rollover_day_number"] = slot["day_number"]
        conn.execute(text(
            "INSERT INTO editorial_tier_slips"
            " (publish_date,tier,created_at,detail)"
            " VALUES (:d,:t,:at,:detail)"
        ), {"d": day, "t": tier, "at": _now(),
            "detail": json.dumps(payload)})
    # Clear any in-process day cache; locked reads also have a short TTL.
    from leagues import daily_feed
    daily_feed._accum_cache.update({"result": None, "ts": 0})
    return {
        "status": "PUBLISHED", "date": day, "tier": tier,
        "total_odds": actual, "leg_count": len(revised),
        "share_code": booked["share_code"],
        "editorial_manual": True, "official_engine_record_unchanged": True,
        "replaces_official_display": bool(replace_official_over),
    }

def overlay_on_card(date: str, accumulators: dict) -> dict:
    """Public display override without mutating locked engine publication."""
    merged = dict(accumulators)
    from leagues.booking import booking_lifecycle
    for tier, record in list_published(date).items():
        if tier not in TIERS:
            continue
        original = merged.get(tier) or {}
        override = tier == "over_1_5" and record.get("replaces_official_display") is True
        # Manual rollover creates the authoritative chain slot first. Only
        # attach its verified ticket if that SAME stage is in the chain.
        chain_slot = next((
            slot for slot in original.get("chain", [])
            if slot.get("date") == date and
            any(p.get("editorial_manual") for p in slot.get("picks", []))
        ), None) if tier == "rollover" else None
        manual_chain = bool(chain_slot and original.get("selected"))
        if original.get("selected") and not (override or manual_chain):
            continue
        if tier == "rollover" and not manual_chain:
            continue
        games = record["games"]
        if manual_chain:
            chain_ids = {str(p.get("sportybet_event_id")) for p in chain_slot["picks"]}
            manual_ids = {str(g.get("sportybet_event_id")) for g in games}
            if not chain_ids or chain_ids != manual_ids:
                continue
        booking = booking_lifecycle(record["booking"], games)
        merged[tier] = {
            **(original if manual_chain else {}),
            "selected": True,
            "games": games,
            "total_odds": record["total_odds"],
            "hit_probability": None,
            "model_probability_available": False,
            "reason": "Admin-curated selection; statistical confidence not evaluated",
            "presentation": "accumulator",
            "sportybet_ticket_type": "accumulator",
            "editorial_manual": True,
            "source": "admin_curated",
            "booking": booking,
            "booking_code": (booking or {}).get("share_code"),
            "risk_level": "Unscored editorial accumulator",
            "replaces_official_display": bool(override),
            "original_official_record_preserved": True,
            "replaced_official_selection_count": (
                len(original.get("games") or []) if override else 0
            ),
        }
    return merged



def _selection_market_label(selection: dict) -> str:
    """Use the bookmaker's market *name*, never a guessed market ID."""
    names = []
    for key in ("marketName", "marketDesc", "marketLabel", "marketDisplayName",
                "betTypeName", "market"):
        value = selection.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("description")
        if isinstance(value, str):
            names.append(value)
    return " ".join(names).strip()


def _explicitly_activated(value) -> bool:
    """Active customer toggle only, never an advertised/eligible feature."""
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "on", "yes", "enabled", "selected", "active"}
    if isinstance(value, dict):
        return any(_explicitly_activated(value.get(k)) for k in
                   ("enabled", "selected", "active", "applied", "checked", "isSelected"))
    return False


def _ticket_selected_special_features(data: dict, ticket: dict) -> list[str]:
    """Detect explicitly selected slip-wide 1UP, 2UP and EarlyGoals toggles.

    A SportyBet share payload may encode these in ticket options rather than
    per-leg market descriptors. Do not confuse offered promotions with applied
    promotions; ambiguous metadata is not proof of selection.
    """
    names = {
        "EarlyGoals": ("earlyGoals", "earlyGoal", "earlyGoalsEnabled",
                       "isEarlyGoals", "earlyGoalEnabled", "useEarlyGoals",
                       "earlyGoalsSelected", "early_goal_enabled"),
        "1UP": ("oneUp", "oneUpEnabled", "is1Up", "use1Up", "isOneUp"),
        "2UP": ("twoUp", "twoUpEnabled", "is2Up", "use2Up", "isTwoUp"),
    }
    observed: set[str] = set()
    # A whitelist of slip option containers, never an undirected recursive
    # scan that would misinterpret advertising or eligible promo banners.
    for root in (ticket, data):
        if not isinstance(root, dict):
            continue
        containers = [root]
        for k in ("betOptions", "options", "selectedOptions", "betSettings",
                  "promotions", "specialMarkets", "betFeatures"):
            if isinstance(root.get(k), dict):
                containers.append(root[k])
        for part in containers:
            for label, keys in names.items():
                if any(k in part and _explicitly_activated(part[k]) for k in keys):
                    observed.add(label)
    return [name for name in ("EarlyGoals", "1UP", "2UP") if name in observed]


def _selection_special_type(selection: dict) -> str | None:
    """Detect early-settlement variants even when their base market IDs match."""
    import re
    pieces = [_selection_market_label(selection)]
    # Some SportyBet responses expose the toggles as booleans/dictionaries,
    # rather than naming the promo in marketName.
    for feature, keys in (
        ("EarlyGoals", ("earlyGoals", "isEarlyGoals", "earlyGoalEnabled", "useEarlyGoals")),
        ("1UP", ("oneUp", "oneUpEnabled", "is1Up")),
        ("2UP", ("twoUp", "twoUpEnabled", "is2Up")),
    ):
        if any(k in selection and _explicitly_activated(selection[k]) for k in keys):
            return feature
    for key in ("betType", "earlyPayoutType", "promotionType", "specialMarketName",
                "marketType"):
        v = selection.get(key)
        if isinstance(v, str):
            pieces.append(v)
    # Ignore unrelated ticket-level advertisements; only inspect this leg.
    label = " ".join(pieces).lower()
    if re.search(r"\b1\s*up\b", label):
        return "1UP"
    if re.search(r"\b2\s*up\b", label):
        return "2UP"
    if re.search(r"early\s*goals?", label):
        return "EarlyGoals"
    return None


def _standard_market_from_special(selection: dict, feature: str) -> str | None:
    """Only convert when the original named market AND outcome both agree.

    We have no verified source of SportyBet's special market IDs, so avoid
    fabricating one. The normal equivalent is separately re-priced/booked.
    """
    from leagues.market_registry import MARKET_TO_SPORTYBET
    name = _selection_market_label(selection).lower().replace("_", " ")
    outcome = str(selection.get("outcomeId") or "")
    named = " ".join(str(selection.get(k) or "") for k in (
        "outcomeName", "outcomeDesc", "outcomeLabel"
    )).strip().casefold()
    # If bookmaker labels are present, contradictory labels are never mapped.
    known_labels = {
        "home": {"1"}, "home win": {"1"}, "1": {"1"},
        "away": {"3"}, "away win": {"3"}, "2": {"3"},
        "draw": {"2"}, "x": {"2"},
        "home or draw": {"9"}, "1x": {"9"},
        "home or away": {"10"}, "12": {"10"},
        "draw or away": {"11"}, "away or draw": {"11"}, "x2": {"11"},
    }
    if feature in {"1UP", "2UP"}:
        if named in known_labels and outcome not in known_labels[named]:
            return None
        if "double chance" in name:
            candidates = {"9": "home_or_draw", "10": "home_or_away",
                          "11": "away_or_draw"}
        elif "1x2" in name or "match result" in name:
            candidates = {"1": "home_win", "2": "draw", "3": "away_win"}
        else:
            return None
        key = candidates.get(outcome)
        return key if key in MARKET_TO_SPORTYBET else None
    # An explicitly named EarlyGoals market can carry the SAME goal line
    # in its outcomeName/specifier even though marketName no longer says
    # "Over/Under". We still require outcome 12 and a proved goal line;
    # "1 goal by 10 min" alone is NEVER treated as Over 1.5.
    if feature == "EarlyGoals" and any(label in name for label in
                                       ("over/under", "total", "earlygoals", "early goals")):
        if outcome != "12" or "under" in named:
            return None
        specifier = str(selection.get("specifier") or "")
        label = " ".join(str(selection.get(k) or "") for k in
                         ("outcomeName", "outcomeDesc", "outcomeLabel"))
        import re
        explicit = re.search(r"over\s*(1\.5|2\.5|3\.5|4\.5)", label.lower())
        if explicit:
            spec = "total=" + explicit.group(1)
            if specifier and specifier != spec:
                return None
        elif specifier in {"total=1.5", "total=2.5", "total=3.5", "total=4.5"}:
            spec = specifier
        else:
            return None
        key = "over_" + spec.split("=")[1].replace(".", "_")
        return key if key in MARKET_TO_SPORTYBET else None
    return None


def _resolve_import_market(selection: dict, *, convert_special: bool) -> tuple[str, str | None]:
    """Return standard selection and optional name of lost early-pay benefit."""
    from leagues.market_registry import MARKET_TO_SPORTYBET
    exact = (str(selection.get("marketId")),
             str(selection.get("specifier") or ""),
             str(selection.get("outcomeId")))
    matches = [key for key, mapping in MARKET_TO_SPORTYBET.items()
               if tuple(str(part or "") for part in mapping) == exact]
    feature = _selection_special_type(selection)
    if feature:
        if not convert_special:
            raise ValueError(
                f"{feature} is an early-settlement variant. Tick 'Convert special "
                "markets to standard selections' to create a different ticket "
                "WITHOUT this early-settlement benefit."
            )
        standard = (_standard_market_from_special(selection, feature)
                    or (matches[0] if len(matches) == 1 else None))
        # Even a matching numeric base-market ID is insufficient if the
        # returned human-readable outcome explicitly contradicts the choice.
        outcome_label = " ".join(
            str(selection.get(k) or "") for k in
            ("outcomeName", "outcomeDesc", "outcomeLabel")
        ).strip().casefold()
        labels = {
            "home": "home_win", "home win": "home_win", "1": "home_win",
            "draw": "draw", "x": "draw",
            "away": "away_win", "away win": "away_win", "2": "away_win",
            "home or draw": "home_or_draw", "1x": "home_or_draw",
            "draw or away": "away_or_draw", "away or draw": "away_or_draw",
            "x2": "away_or_draw", "home or away": "home_or_away",
            "12": "home_or_away",
        }
        if standard and (
            (outcome_label in labels and labels[outcome_label] != standard)
            or (outcome_label.startswith("under ") and standard.startswith("over_"))
            or (outcome_label.startswith("over ") and standard.startswith("under_"))
        ):
            raise ValueError(
                f"{feature} outcome conflicts with the bookmaker label; "
                "manual conversion was refused"
            )
        if not standard:
            raise ValueError(
                f"{feature} cannot be converted safely: the code did not provide "
                "an unambiguous standard market, line and outcome. Enter this "
                "SportyBet event ID and the desired regular market manually."
            )
        return standard, feature
    if len(matches) == 1:
        return matches[0], None
    raise ValueError(
        "Unsupported market/outcome cannot be mapped safely; "
        "from this code. Enter the SportyBet event ID and a regular market "
        "manually, or use a code with supported markets."
    )

def import_share_code(code: str, tier: str, *, board=None,
                      convert_special: bool = False,
                      allow_review: bool = False) -> dict:
    """Decode all share-code selections before the separate live preview.

    Import itself never books or publishes. Today's tier availability, kickoff,
    market price, duplicate exposure and live board validity are enforced by
    the existing preview/publish functions, which are unchanged.
    Special early-payout markets require explicit conversion consent and are
    always disclosed as changed terms. No legs are silently discarded.
    """
    import math
    import re
    from leagues.booking import _read_share

    if tier not in TIERS:
        raise ValueError("Unknown prediction tier")
    code = code.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{4,32}", code):
        raise ValueError("Enter a valid SportyBet booking code")
    try:
        response = _read_share(code)
    except Exception as exc:
        LOG.warning("SportyBet code lookup failed: %s", type(exc).__name__)
        raise ValueError(
            "SportyBet code lookup timed out or failed. Try again; "
            "nothing has been imported or published."
        ) from None
    if str(response.get("bizCode")) != "10000":
        raise ValueError("SportyBet did not recognize this code")

    data = response.get("data") or {}
    ticket = data.get("ticket") or {}
    selected_features = _ticket_selected_special_features(data, ticket)
    if selected_features and not convert_special:
        raise ValueError(
            "SportyBet code has an activated " + ", ".join(selected_features) +
            " ticket option. The regular BetSightly publisher cannot "
            "reproduce or settle that early-payout benefit. Tick 'Convert "
            "1UP / 2UP / EarlyGoals to regular markets' to IMPORT a DIFFERENT "
            "standard ticket for review; the original special benefits "
            "will not be preserved."
        )
    selections = ticket.get("selections") or []
    if not isinstance(selections, list) or not selections:
        raise ValueError("SportyBet returned no selections in this code")
    if len(selections) > 50:
        raise ValueError("This code contains too many selections to import")

    rows = []
    games = []
    converted = [
        {"event_id": "TICKET", "from": feature,
         "to": "ordinary 90-minute markets", "scope": "ticket"}
        for feature in selected_features
    ]
    unresolved = []
    seen = set()
    for pos, selection in enumerate(selections, 1):
        event = str(selection.get("eventId") or "").strip()
        if not event or len(event) > 60 or not event.isascii() or any(
            c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ:-_"
            for c in event
        ):
            raise ValueError(f"Selection {pos} has no recognizable SportyBet event ID")
        if event in seen:
            raise ValueError(f"SportyBet code includes event {event} more than once")
        seen.add(event)
        try:
            market, feature = _resolve_import_market(
                selection, convert_special=convert_special
            )
        except ValueError as exc:
            # The readback may use a special/promo market ID without
            # disclosing its canonical line/outcome. Preserve this fixture
            # for EXPLICIT admin review instead of dropping it or guessing.
            # This mode is opt-in and only available when standard-market
            # conversion was explicitly requested.
            if not (allow_review and convert_special):
                raise ValueError(f"Event {event}: {exc}") from None
            unresolved_game = {
                "sportybet_event_id": event,
                "market": None, "requires_review": True,
                "original_selection_index": pos,
                "reported_market": _selection_market_label(selection)[:160],
                "reported_outcome": " ".join(
                    str(selection.get(k) or "") for k in
                    ("outcomeName", "outcomeDesc", "outcomeLabel")
                ).strip()[:100],
                "original_feature": _selection_special_type(selection),
                "reason": str(exc)[:220],
                "home_team": None, "away_team": None, "odds": None,
                "bookable": False,
            }
            unresolved.append(unresolved_game)
            games.append(unresolved_game)
            continue
        if feature:
            converted.append({"event_id": event, "from": feature, "to": market})
        rows.append(f"{event},{market}")
        games.append({
            "sportybet_event_id": event,
            "market": market,
            # Names and current prices require a separate live board check.
            "home_team": None, "away_team": None, "odds": None,
            "bookable": False,
        })

    raw_odds = (ticket.get("displayTotalOdds") or ticket.get("totalOdds")
                or data.get("displayTotalOdds") or data.get("totalOdds"))
    try:
        original_odds = float(raw_odds)
        if not math.isfinite(original_odds) or original_odds <= 1:
            original_odds = None
    except (ValueError, TypeError):
        original_odds = None

    warnings = []
    if data.get("unavailableOutcomes"):
        warnings.append("Some selections are unavailable on SportyBet.")
    if len(selections) > MAX_LEGS[tier]:
        warnings.append(f"{tier} allows at most {MAX_LEGS[tier]} selections.")
    if tier == "banker" and len(selections) != 1:
        warnings.append("Banker requires exactly one selection.")
    if unresolved:
        warnings.append(
            f"{len(unresolved)} of {len(selections)} selection(s) need an "
            "explicit regular market choice before live price preview. "
            "No selection has been dropped and nothing has been published."
        )
    if tier == "over_1_5" and any(g["market"] not in MANUAL_OVER_GOALS for g in games):
        warnings.append("Over Goals only accepts match-total Overs (0.5–4.5), "
                        "team Overs (0.5/1.5) or BTTS Yes.")
    if original_odds is not None and original_odds + 1e-8 < MIN_ODDS[tier]:
        warnings.append(
            f"Original {original_odds:.2f}x odds are below "
            f"the {tier} minimum of {MIN_ODDS[tier]:.2f}x."
        )
    if converted:
        warnings.append(
            "Special early-settlement features were explicitly converted "
            "to ordinary 90-minute markets; early payouts are NOT preserved. "
            "Even if the displayed base selections match, this is a DIFFERENT "
            "ticket from your original EarlyGoals/1UP/2UP code."
        )

    return {
        "status": ("NEEDS_MANUAL_REVIEW" if unresolved
                   else "IMPORTED_NOT_PUBLISHED"),
        "date": _today(),
        "tier": tier,
        "lines": "\n".join(rows),
        "games": games,
        "total_odds": original_odds,
        "warnings": warnings,
        "imported_share_code": code,
        "import_mode": "sportybet_code",
        "conversion_requested": bool(convert_special),
        "converted_features": converted,
        "unresolved_selections": unresolved,
        "unresolved_count": len(unresolved),
        "original_leg_count": len(selections),
        "booking_code_created": False,
        "live_prices_verified": False,
        "publish_ready": False,
        "note": (
            "Original code decoded. The original bookmaker odds (if shown) "
            "are NOT current verified tier odds. EarlyGoals, 1UP, 2UP, "
            "Flexi, bonuses and other special betslip options are NOT preserved. "
            "Click Check prices / preview before any new verified booking "
            "or publication."
        ),
    }
