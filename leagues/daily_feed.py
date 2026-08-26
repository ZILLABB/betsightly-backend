"""
Daily feed — builds the categories and rollover chain the frontend consumes.

Everything here is downstream of leagues.engine.run_pipeline(), so every
published pick has passed through the same model: ESPN fixtures with real
DraftKings prices -> measured per-league base rates -> ELO second opinion
where available -> predictor -> pick construction -> selection.

Categories are selected by leagues.selection, which searches for the
combination most likely to land at each target multiplier instead of stacking
whatever looks most confident. Each category reports `hit_probability` — the
chance every leg wins — so a 10x slip is presented as the long shot it is.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent / "data"

_accum_cache: dict = {"result": None, "ts": 0}
_ACCUM_CACHE_TTL = 900  # 15 min — the card itself is locked, this just trims DB reads

# Rollover chain length. Cut from 10 because the daily target went up to 2x,
# and the two numbers are not independent: a day at 2x lands about 45% of the
# time, and every day has to land. Ten days of that is 0.03% — a chain nobody
# completes. Three days of it is 9.1% and pays about 8x, which is a challenge
# somebody actually wins now and then.
TARGET_DAYS = 3

# How close two confidences have to be before the bookmaker's margin is
# allowed to decide between them. Two points: wide enough that near-identical
# picks are actually compared on price, narrow enough that a cheap market can
# never buy its way past a genuinely stronger pick.
_MARGIN_TIE_BAND = 0.02

# Nigeria is UTC+1 year-round (no daylight saving), and the audience books in
# the morning. The card is published at 08:00 WAT so a full day of fixtures is
# still ahead of the user rather than half-gone.
WAT_OFFSET = timedelta(hours=1)
PUBLISH_HOUR_WAT = 8

# Fixtures kicking off sooner than this are left out at publish time — a pick
# a user cannot realistically get on is not a pick.
BOOKING_BUFFER = timedelta(minutes=20)


def _wat_now() -> datetime:
    return datetime.now(timezone.utc) + WAT_OFFSET


def _publish_date() -> str:
    """The WAT day whose card should currently be showing.

    Before 08:00 WAT the previous day's card is still the published one, so an
    early-morning visitor sees a settled, finished card rather than a
    half-built one for a day that has not opened yet.
    """
    wat = _wat_now()
    if wat.hour < PUBLISH_HOUR_WAT:
        wat -= timedelta(days=1)
    return wat.strftime("%Y-%m-%d")


def _save(filename: str, data):
    with open(DATA_DIR / filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── Categories ─────────────────────────────────────────────

def _select_tier(picks: list, target: float, max_picks: int,
                 min_confidence: float, min_ev: float,
                 prefer: str = "joint", band_low: float = 0.80):
    """Select a tier, and say which of the two reasons left it empty.

    A blank tier has two quite different causes and they were reported with
    the same "not enough matches" line, which is misleading when there were
    plenty of matches and the slip was simply refused for being poor value.
    Re-running ungated tells them apart: if a slip exists without the floor,
    the day had the fixtures and the value was the problem.
    """
    from leagues.selection import select_accumulator

    sel = select_accumulator(picks, target, max_picks, min_confidence,
                             min_ev=min_ev, prefer=prefer, band_low=band_low)
    if sel[0]:
        return sel, None

    ungated = select_accumulator(picks, target, max_picks, min_confidence,
                                 min_ev=0.0, prefer=prefer, band_low=band_low)
    if ungated[0]:
        _, total, joint = ungated
        return sel, (
            f"Today's best {target:g}x slip lands about {joint:.0%} of the time, "
            f"which returns roughly {total * joint:.2f} for every 1 staked. "
            f"That is too thin to put our name on, so we are sitting it out."
        )
    return sel, (
        f"Not enough matches today to reach {target:g}x safely — "
        f"check back tomorrow."
    )


def build_daily_accumulators(force: bool = False) -> dict:
    """Category picks + rollover chain for the next actionable match day."""
    import time as _time
    now_ts = _time.time()
    if not force and _accum_cache["result"] and (now_ts - _accum_cache["ts"]) < _ACCUM_CACHE_TTL:
        return _accum_cache["result"]

    from leagues.engine import run_pipeline, picks_for_date
    from leagues.selection import select_accumulator, select_banker
    from leagues.picks import (
        ESTIMATE_MARGIN, MIN_CANDIDATE_CONFIDENCE, MIN_PUBLISHABLE_CONFIDENCE,
        to_game)

    now = datetime.now(timezone.utc)
    publish_date = _publish_date()

    # Serve the locked card if today's has already been published. Re-selecting
    # through the day would quietly swap picks out from under anyone who booked
    # off the morning card.
    if not force:
        locked = _load_locked(publish_date)
        if locked:
            # Refresh statuses from the persisted chain without rerunning the
            # entire fixture/ML pipeline on a read. Extending the chain is a
            # scheduled publishing responsibility; a page view must stay a
            # cheap, predictable database read.
            rollover = _build_rollover([], now.strftime("%Y-%m-%d"))
            if rollover.get("chain_length") or not locked.get("rollover"):
                locked["rollover"] = rollover
            # Revision metadata travels with the stored card, so a reader gets
            # the same answer whether the card is served fresh or from the lock.
            _rev = locked.pop("_card_revision", 1)
            _updated = locked.pop("_last_updated_at", None)
            _first = locked.pop("_first_published_at", None)
            result = {
                "status": "success",
                "date": publish_date,
                "source": "leagues",
                "published_at_wat": f"{PUBLISH_HOUR_WAT:02d}:00",
                "locked": True,
                "revision": _rev,
                "first_published_at": _first,
                "last_updated_at": _updated,
                "total_fixtures": sum(len(c.get("games", [])) for c in locked.values() if isinstance(c, dict)),
                "accumulators": _attach_bookings(
                    publish_date, _mark_started(locked, now)),
            }
            _accum_cache.update({"result": result, "ts": now_ts})
            return result

    all_picks, fixtures = run_pipeline(days_ahead=4, force=force)
    if not all_picks:
        return None

    today = now.strftime("%Y-%m-%d")

    # Only fixtures a user can still get on. Anything already under way, or
    # about to be, is excluded from a freshly published card.
    bookable_from = (now + BOOKING_BUFFER).isoformat().replace("+00:00", "Z")
    all_picks = [p for p in all_picks if p["_fixture"]["commence_time"] >= bookable_from]
    if not all_picks:
        return None

    # Prefer the publishing day; fall back to the next day with enough fixtures
    # so a late-evening rebuild does not publish a one-game card.
    day_picks = picks_for_date(publish_date, all_picks)
    target_date = publish_date
    if len({p["match_id"] for p in day_picks}) < 3:
        for offset in range(0, 5):
            nxt = (now + timedelta(days=offset)).strftime("%Y-%m-%d")
            nxt_picks = picks_for_date(nxt, all_picks)
            if len({p["match_id"] for p in nxt_picks}) >= 3:
                day_picks, target_date = nxt_picks, nxt
                break

    if not day_picks:
        return None

    # Floors are on expected value — payout times the chance it lands.
    #
    # Each leg gives up roughly 6% to the bookmaker's margin, so a slip's value
    # is about 0.94^legs before anything else: ~0.83 at three legs, ~0.73 at
    # five. A floor has to sit *below* that structural cost, or it rejects the
    # tier for being what it is. The first pass set 5 odds at 0.78, which fell
    # between two near-identical slips — 0.796 one day, 0.766 the next — so the
    # tier blinked out over a 3-point difference that means nothing. These sit
    # under the normal range for each tier's leg count, so they catch a slip
    # that is genuinely bad rather than one that is merely long.
    # Every tier now draws from the same 65% floor. The long tiers used to
    # reach down to 0.55 to buy the multiplier, and that is precisely where the
    # losses were: sub-65% legs landed 48% of the time against 59% promised,
    # while everything at or above 65% landed 75.5% against 76.2% promised.
    # A long tier now needs more legs to reach its target instead of worse
    # ones, which costs hit rate honestly rather than by overstating each leg.
    FLOOR = MIN_PUBLISHABLE_CONFIDENCE

    # Tiers are built one after another, each excluding the fixtures already
    # used, so they are genuinely different bets.
    #
    # They were not. On 19 August Shanghai Port Win sat in 2 odds, 5 odds and
    # 10 odds at once; it lost and killed all three. The next day Vancouver
    # Whitecaps did exactly the same. Two days running, "almost every tier
    # failed" was one bad pick counted three times — somebody staking the whole
    # card was not making five bets, they were making one at triple stake, and
    # nothing on the site said so.
    #
    # Safest tier first, so banker and 2 odds get first refusal on the best
    # picks; the long tiers are built from longer prices anyway and lose least
    # by being excluded. If a tier cannot be built from what is left it falls
    # back to the full pool rather than going empty — on a thin day a shared
    # leg beats no slip at all.
    # Counted, not a flat set: on a thin day full independence is impossible —
    # banker, 2 odds, 5 odds and 10 odds want thirteen legs and there may only
    # be nine fixtures left after the booking buffer. Falling straight back to
    # the whole pool put every tier back on the same picks, which is the exact
    # failure this exists to stop, so the limit is relaxed one step at a time
    # and stops at the first level that can actually build the tier.
    fixture_uses: dict = {}

    def _tier(target, max_picks, floor, min_ev, band_low=0.80,
              safe_only=False):
        sel, why = ([], 0.0, 0.0), None
        tier_picks = ([p for p in day_picks if p.get("safe_tier_eligible")]
                      if safe_only else day_picks)
        for limit in (1, 2, None):
            pool = ([p for p in tier_picks
                     if fixture_uses.get(p["match_id"], 0) < limit]
                    if limit is not None else tier_picks)
            sel, why = _select_tier(pool, target, max_picks, floor, min_ev,
                                    band_low=band_low)
            if sel[0]:
                break
        for pick in sel[0]:
            fixture_uses[pick["match_id"]] = fixture_uses.get(pick["match_id"], 0) + 1
        return sel, why

    safe_picks = [p for p in day_picks if p.get("safe_tier_eligible")]
    banker = select_banker(safe_picks)
    for _p in banker[0]:
        fixture_uses[_p["match_id"]] = fixture_uses.get(_p["match_id"], 0) + 1

    # Chance-to-land, not expected value: these are bought to come in. On
    # 22 August that is 2 odds landing 57.5% instead of 49.2%, and 5 odds
    # 24.1% instead of 17.4%. The band floor keeps 2 Odds honest to its name —
    # maximising landing alone drifts it down to 1.63x, which is not 2 odds.
    two, two_why = _tier(2.0, 4, FLOOR, 0.82, band_low=0.92,
                         safe_only=True)
    # The long tiers reach down to the per-market floors, which lets them use
    # a 1.60-1.80 leg from a market that has earned it instead of stacking six
    # short ones. Fewer legs is worth a lot here: 5x from 3 legs at 1.80
    # returns 0.84 and lands 14.4%, against 0.75 and 11.7% from 5 at 1.45.
    five, five_why = _tier(5.0, 6, MIN_CANDIDATE_CONFIDENCE, 0.72)
    # Reaching 10x from legs that are never priced above ~1.45 takes seven of
    # them; capping at six made the tier unbuildable rather than merely long.
    ten, ten_why = _tier(10.0, 8, MIN_CANDIDATE_CONFIDENCE, 0.63)

    # Over 1.5 — a list of singles, one per fixture, safest first.
    #
    # This tier is not an accumulator and treating it as one was the mistake.
    # As a slip it had to stop at about three legs to stay worth staking, so a
    # market with ten good candidates published three of them; ten legs at 70%
    # would land 2.8% of the time and return about -45%, which is not a product
    # anyone should be handed.
    #
    # Bet individually the arithmetic is completely different: each pick stands
    # on its own at roughly -5.7%, and adding a tenth costs the ninth nothing.
    # So the full list is published and `presentation` marks it as singles, so
    # no channel renders a joint probability that would not apply.
    #
    # The confidence floor is on the *calibrated* number. It used to be 0.70
    # against uncalibrated confidences; once the goals correction landed
    # (-0.41 in log-odds) that same 0.70 silently started demanding a raw 77.9%,
    # which is why a thin day produced a single pick. 0.65 restores roughly the
    # bar that was originally intended, measured honestly.
    OVER_MIN_CONFIDENCE = 0.65
    OVER_MAX_PICKS = 10

    def _over_rank(p):
        # Confidence first, then the cheaper price, then whether a bookmaker
        # priced the fixture at all.
        #
        # Confidence is banded rather than compared outright so the margin can
        # actually decide something. Raw confidences are continuous, so exact
        # ties never happen and a strict confidence sort would leave margin
        # dead code — but 82.4% and 81.9% are the same pick for staking
        # purposes, and between two picks that good the one the book prices
        # tightest is worth more.
        #
        # This tier is where that matters most. These are ten singles, and a
        # single pays the margin once where an accumulator pays it per leg, so
        # a point off the margin is a point of return rather than a point
        # divided among fourteen legs. Measured across 296 Over 1.5 markets on
        # one board: 5.95% median against 4.03% in the tightest decile.
        #
        # An estimated price carries ESTIMATE_MARGIN flat, so it sorts exactly
        # where its real equivalent would rather than being pushed to the back.
        # Bookability sits between confidence and margin. This tier lost its
        # code entirely on 25 August because three of its ten legs had no
        # SportyBet counterpart, and ten legs means ten chances to miss — so
        # among equally confident picks, one that can be booked is worth more
        # than one that is a fraction cheaper.
        margin = p.get("market_margin")
        if margin is None:
            margin = ESTIMATE_MARGIN - 1.0
        return (-round(p["confidence"] / _MARGIN_TIE_BAND),
                not p.get("bookable"),
                margin,
                not (p.get("_model") or {}).get("has_market"))

    over_picks, seen = [], set()
    for p in sorted(day_picks, key=_over_rank):
        if p["market"] != "over_1_5" or p["match_id"] in seen:
            continue
        if p["confidence"] < OVER_MIN_CONFIDENCE:
            continue
        over_picks.append(p)
        seen.add(p["match_id"])
        if len(over_picks) >= OVER_MAX_PICKS:
            break

    # For singles the meaningful headline is the typical chance of any one
    # landing, not the product of all of them.
    over_avg = (sum(p["confidence"] for p in over_picks) / len(over_picks)
                if over_picks else 0.0)
    over_total = 1.0
    for p in over_picks:
        over_total *= p["odds"]

    rollover = _build_rollover(all_picks, today)

    def mk_cat(sel, risk, reason_if_empty, presentation="accumulator"):
        picks_, total, joint = sel
        if not picks_:
            return {"selected": False, "games": [], "total_odds": 0,
                    "risk_level": risk, "hit_probability": 0,
                    "presentation": presentation, "reason": reason_if_empty}
        return {
            "selected": True,
            # Ordered by kick-off so the card reads as the day runs: what is
            # about to start is at the top, and a leg that has already gone is
            # never buried under one that kicks off tonight. Selection is
            # unaffected — this is purely how the chosen picks are presented.
            "games": _by_kickoff([to_game(p) for p in picks_]),
            "total_odds": round(total, 2),
            "risk_level": risk,
            # For an accumulator this is the chance every leg lands. For a list
            # of singles it is the average chance of one landing, and
            # `presentation` is what tells a renderer which it is looking at —
            # multiplying singles together would state a risk nobody is taking.
            "hit_probability": round(joint, 3),
            "presentation": presentation,
            "reason": None,
        }

    thin = "Not enough matches today to build this safely — check back tomorrow."

    _built_at = now.isoformat()
    result = {
        "status": "success",
        "date": target_date,
        # When this card was first put together, and how many times it has been
        # rebuilt. A rebuild used to replace the day's card leaving no trace, so
        # a reader refreshing a tier had no way to tell what had changed.
        "first_published_at": _built_at,
        "last_built_at": _built_at,
        "revision": 1,
        "source": "leagues",
        "published_at_wat": f"{PUBLISH_HOUR_WAT:02d}:00",
        "locked": False,
        "total_fixtures": len({p["match_id"] for p in day_picks}),
        "accumulators": {
            "banker": mk_cat(banker, "Banker", "No pick met the banker threshold today."),
            "2_odds": mk_cat(two, "Low", two_why),
            "5_odds": mk_cat(five, "Medium", five_why),
            "10_odds": mk_cat(ten, "High", ten_why),
            "over_1_5": mk_cat(
                (over_picks, over_total, over_avg) if over_picks else ([], 0, 0),
                "Very Safe",
                "No match cleared the Over 1.5 confidence bar today.",
                presentation="singles",
            ),
            "rollover": rollover,
        },
    }

    _archive(target_date, result["accumulators"])

    # Lock the card for the publishing day so it is served unchanged from here
    if target_date == publish_date:
        try:
            from leagues.picks_db import save_card
            save_card(publish_date, result["accumulators"])
            result["locked"] = True
        except Exception as e:
            logger.debug(f"card lock skipped: {e}")

    result["accumulators"] = _mark_started(result["accumulators"], now)
    if target_date == publish_date:
        # Only the publishing day's card has bookings. A card that has fallen
        # forward to tomorrow's fixtures must not wear today's codes.
        result["accumulators"] = _attach_bookings(
            publish_date, result["accumulators"])
    _accum_cache.update({"result": result, "ts": now_ts})
    return result


def _by_kickoff(games: list[dict]) -> list[dict]:
    """Order games by kick-off, earliest first."""
    return sorted(games, key=lambda g: (g.get("kickoff") or g.get("date") or "9999"))


def build_bookable_now() -> dict | None:
    """A slip built only from fixtures that have not kicked off yet.

    Answers the problem the lock creates. The morning card must not change —
    it is what people booked at 08:00 and it is what the track record scores —
    but by mid-afternoon several of its legs have started and a visitor
    arriving then cannot place it. Showing them a slip they cannot get on is
    the same as showing them nothing.

    So this is a *second*, separate thing rather than a rewrite of the first:
    the published card stays exactly as it was, and this is generated fresh on
    request from whatever is still ahead. It is deliberately never archived and
    never settled, because a slip that regenerates on every request has no
    fixed identity to score — counting it would let the record quietly reroll
    its losers, which is the exact failure the lock exists to prevent.
    """
    from leagues.engine import run_pipeline
    from leagues.picks import (
        MIN_CANDIDATE_CONFIDENCE, MIN_PUBLISHABLE_CONFIDENCE, to_game)
    from leagues.selection import select_banker

    now = datetime.now(timezone.utc)
    all_picks, _ = run_pipeline(days_ahead=2)
    if not all_picks:
        return None

    bookable_from = (now + BOOKING_BUFFER).isoformat().replace("+00:00", "Z")
    today = now.strftime("%Y-%m-%d")
    live = [p for p in all_picks
            if p["_fixture"]["commence_time"] >= bookable_from
            and p["_fixture"]["commence_time"][:10] == today]
    if not live:
        return None

    F = MIN_PUBLISHABLE_CONFIDENCE
    banker = select_banker(live)
    two, _ = _select_tier(live, 2.0, 4, F, 0.82)
    five, _ = _select_tier(live, 5.0, 6, F, 0.72)
    ten, _ = _select_tier(live, 10.0, 8, F, 0.63)

    over, seen = [], set()
    for p in sorted(live, key=lambda x: -x["confidence"]):
        if p["market"] != "over_1_5" or p["match_id"] in seen or p["confidence"] < 0.65:
            continue
        over.append(p)
        seen.add(p["match_id"])
        if len(over) >= 10:
            break
    over_avg = sum(p["confidence"] for p in over) / len(over) if over else 0.0
    over_total = 1.0
    for p in over:
        over_total *= p["odds"]

    def cat(sel, risk, presentation="accumulator"):
        picks_, total, joint = sel
        if not picks_:
            return {"selected": False, "games": [], "total_odds": 0,
                    "risk_level": risk, "hit_probability": 0,
                    "presentation": presentation,
                    "reason": "Nothing left to build this from today."}
        return {"selected": True,
                "games": _by_kickoff([to_game(p) for p in picks_]),
                "total_odds": round(total, 2), "risk_level": risk,
                "hit_probability": round(joint, 3),
                "presentation": presentation, "reason": None}

    return {
        "status": "success",
        "date": today,
        "generated_at": now.isoformat(),
        "kickoffs_remaining": len({p["match_id"] for p in live}),
        "accumulators": {
            "banker": cat(banker, "Banker"),
            "2_odds": cat(two, "Low"),
            "5_odds": cat(five, "Medium"),
            "10_odds": cat(ten, "High"),
            "over_1_5": cat((over, over_total, over_avg) if over else ([], 0, 0),
                            "Very Safe", presentation="singles"),
        },
    }


def _attach_bookings(publish_date: str, accumulators: dict) -> dict:
    """Hang stored booking codes on the card, never failing the card for it.

    A bookmaker being unreachable must not take the predictions down with it —
    the picks are the product, the code is a convenience on top.
    """
    try:
        from leagues.booking import attach_bookings
        out = attach_bookings(publish_date, accumulators)
        attached = sum(1 for v in out.values()
                       if isinstance(v, dict) and v.get("booking"))
        logger.info(f"booking attach {publish_date}: {attached} tier(s) carry a code")
        return out
    except Exception as e:
        # Logged loudly, not at debug. A booking that silently fails to attach
        # looks identical to a day nothing was booked, and the card gives no
        # hint which it is.
        logger.warning(f"booking attach failed: {e}", exc_info=True)
        return accumulators


def _load_locked(publish_date: str):
    try:
        from leagues.picks_db import load_card
        return load_card(publish_date)
    except Exception:
        return None


def _mark_started(accumulators: dict, now: datetime) -> dict:
    """Flag legs whose match has kicked off.

    The card stays fixed once published — that is the point — but a visitor
    arriving at midday still needs to see which legs are no longer bookable
    rather than being shown a slip that reads as if it were all still open.
    """
    cutoff = now.isoformat().replace("+00:00", "Z")
    for cat in accumulators.values():
        if not isinstance(cat, dict):
            continue
        games = cat.get("games") or []
        started = 0
        for g in games:
            ko = g.get("kickoff") or g.get("date") or ""
            g["started"] = bool(ko and ko <= cutoff)
            if g["started"]:
                started += 1
        if games:
            cat["started_count"] = started
            cat["all_started"] = started == len(games)
    return accumulators


def _archive(date: str, accumulators: dict) -> None:
    """Record today's slips so they can be settled and shown as history."""
    try:
        from leagues.picks_db import archive_slip
    except Exception:
        return
    for category, cat in accumulators.items():
        if category == "rollover" or not cat.get("selected"):
            continue
        try:
            archive_slip(
                date=date,
                category=category,
                games=cat.get("games", []),
                total_odds=cat.get("total_odds", 0),
                hit_probability=cat.get("hit_probability", 0),
                presentation=cat.get("presentation", "accumulator"),
            )
        except Exception as e:
            logger.debug(f"archive {category} failed: {e}")


# ── Rollover chain ─────────────────────────────────────────

def _build_rollover(all_picks: list, today: str) -> dict:
    """10-day chain, one slot per match day, persisted to Postgres."""
    from leagues.engine import picks_for_date
    from leagues.selection import select_rollover_day
    from leagues.picks import to_game

    try:
        from leagues.rollover_db import (
            load_chain as _db_load,
            append_day as _db_append,
            reset_chain as _db_reset,
            update_day_status as _db_update,
        )
        db_available = True
    except Exception:
        db_available = False
        _db_load = _db_append = _db_reset = _db_update = None  # type: ignore

    chain_path = DATA_DIR / "rollover_chain.json"
    if db_available:
        chain = _db_load(today)
    elif chain_path.exists():
        chain = json.loads(chain_path.read_text(encoding="utf-8"))
    else:
        chain = {"start_date": today, "days": [], "status": "active"}

    # Retire a chain that has drifted far past its start
    if chain.get("start_date"):
        try:
            start = datetime.strptime(chain["start_date"], "%Y-%m-%d")
            if (datetime.utcnow() - start).days > 45:
                if db_available:
                    _db_reset(chain["start_date"])
                chain = {"start_date": today, "days": [], "status": "active"}
        except Exception:
            chain = {"start_date": today, "days": [], "status": "active"}

    # Void days whose matches finished more than two days ago but never
    # resolved — otherwise one unresolvable day freezes the chain forever.
    stale_cutoff = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
    for day in chain.get("days", []):
        if day.get("status") == "pending" and day.get("date", "") < stale_cutoff:
            day["status"] = "void"
            logger.info(f"Voiding stale rollover day {day.get('date')}")
            if db_available:
                try:
                    _db_update(day["date"], "void")
                except Exception:
                    pass

    # Start fresh once the chain is complete
    if len(chain.get("days", [])) >= TARGET_DAYS:
        if all(d.get("status") in ("won", "lost", "void") for d in chain["days"]):
            logger.info(f"Chain {chain.get('start_date')} complete — starting a new one")
            chain = {"start_date": today, "days": [], "status": "active"}

    used_matches = {
        pk.get("match_id")
        for day in chain.get("days", [])
        for pk in day.get("picks", [])
        if pk.get("match_id")
    }

    # Group remaining picks by match day
    by_date: dict[str, list] = {}
    for p in all_picks:
        if p["match_id"] in used_matches:
            continue
        d = p["_fixture"]["commence_time"][:10]
        if d >= today:
            by_date.setdefault(d, []).append(p)

    last_date = chain["days"][-1]["date"] if chain.get("days") else ""
    needed = TARGET_DAYS - len(chain.get("days", []))

    for date in sorted(by_date):
        if needed <= 0:
            break
        if date <= last_date:
            continue
        chosen, combined, joint = select_rollover_day(by_date[date])
        if not chosen:
            continue
        # Earliest kick-off first, matching the category cards. The rollover
        # builds its own pick dicts rather than going through mk_cat, so it
        # needs the same ordering applied here or it is the one tier on the
        # site still listed in selection order.
        chosen = sorted(chosen, key=lambda p: p["_fixture"]["commence_time"])

        new_day = {
            "day_number": len(chain["days"]) + 1,
            "date": date,
            "status": "pending",
            "combined_odds": round(combined, 2),
            "hit_probability": round(joint, 3),
            "picks": [
                {
                    "match_id": p["match_id"],
                    "match": f"{p['_fixture']['home']['name']} vs {p['_fixture']['away']['name']}",
                    "home_team": p["_fixture"]["home"]["name"],
                    "away_team": p["_fixture"]["away"]["name"],
                    "home_team_logo": p["_fixture"]["home"].get("logo"),
                    "away_team_logo": p["_fixture"]["away"].get("logo"),
                    "league": p["_fixture"]["league"],
                    "commence_time": p["_fixture"]["commence_time"],
                    "prediction": p["prediction"],
                    "market": p["market_group"],
                    # The specific market, not just its group. `market` above
                    # holds the group and is left alone because settlement and
                    # the frontend already read it, but a group cannot be
                    # booked: "match_result" does not say which side won the
                    # pick, so "FC Cologne Win" was unrecoverable from stored
                    # data and rollover was the one tier that could never
                    # carry a booking code.
                    "market_key": p["market"],
                    # Carried for the same reason as market_key: a rollover
                    # leg with no SportyBet counterpart cannot be booked, and
                    # the chain should prefer legs that can be.
                    "bookable": p.get("bookable", False),
                    "odds": p["odds"],
                    "odds_are_real": p["odds_are_real"],
                    "confidence": p["confidence"],
                    "raw_confidence": p.get("raw_confidence"),
                    "status": "pending",
                }
                for p in chosen
            ],
        }
        chain["days"].append(new_day)
        needed -= 1

        if db_available:
            if not _db_append(chain["start_date"], new_day):
                logger.error(f"Rollover day {new_day['date']} not persisted")
                _save("rollover_chain.json", chain)
        else:
            _save("rollover_chain.json", chain)

    cumulative = 1.0
    for d in chain.get("days", []):
        cumulative *= d.get("combined_odds", 1.0)

    today_day = next(
        (d for d in chain.get("days", []) if d["date"] >= today and d.get("status") == "pending"),
        None,
    )
    games = []
    if today_day:
        for pk in today_day.get("picks", []):
            games.append({
                "fixture_id": abs(hash(pk.get("match_id", ""))) % 1_000_000,
                "match_id": pk.get("match_id"),
                "home_team": pk.get("home_team", ""),
                "away_team": pk.get("away_team", ""),
                "home_team_logo": pk.get("home_team_logo"),
                "away_team_logo": pk.get("away_team_logo"),
                "league": pk.get("league", ""),
                "date": pk.get("commence_time", ""),
                "kickoff": pk.get("commence_time", ""),
                "prediction": pk.get("prediction", ""),
                "prediction_type": pk.get("market", "match_result"),
                # Every other tier publishes the specific market under this
                # key; rollover omitted it entirely. Absent on chains stored
                # before `market_key` existed, which simply means those legs
                # cannot be booked rather than being booked wrongly.
                "market": pk.get("market_key"),
                "bookable": pk.get("bookable", False),
                "confidence": pk.get("confidence", 0.5),
                "estimated_odds": pk.get("odds"),
                "odds": pk.get("odds"),
                "real_odds": pk.get("odds") if pk.get("odds_are_real") else None,
                "odds_are_real": pk.get("odds_are_real", False),
                "risk_level": "low",
                "model_type": "market_poisson",
            })

    today_odds = today_day.get("combined_odds", 0) if today_day else 0

    return {
        "selected": bool(games),
        "games": games,
        # The multiplier for today's slot — the number a user actually stakes
        # against. The compounded figure is `cumulative_odds`; publishing that
        # as total_odds made the category tab advertise "1746x".
        "total_odds": round(today_odds, 2),
        "risk_level": "Challenge",
        "reason": None if games else "No safe rollover slot for today",
        "chain": chain.get("days", []),
        "chain_length": len(chain.get("days", [])),
        "target_days": TARGET_DAYS,
        "cumulative_odds": round(cumulative, 2),
        "today_hit_probability": today_day.get("hit_probability") if today_day else None,
    }
