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
import os
from math import prod
from datetime import datetime, timedelta, timezone
from pathlib import Path

from leagues.availability import BOOKING_BUFFER, game_kickoff_lifecycle
from leagues.selection_quality import selection_probability
from leagues.publication_policy import (
    MIN_SLIP_MODEL_RETURN,
    POLICY_VERSION as PUBLICATION_POLICY_VERSION,
    enforce_card_policy,
    filter_official_candidates,
    rejection_summary,
)

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

# Daily products are a single customer-facing portfolio, not five independent
# opportunities to repeat the same football opinion.  A selection identity is
# deliberately narrower than a fixture: different, independently defensible
# markets can still be considered as a last resort, but one exact selection is
# never published twice across the official accumulator products.
OFFICIAL_PORTFOLIO_VERSION = "official_exposure_v1"
MAX_OFFICIAL_SELECTION_EXPOSURE = 1
MAX_OFFICIAL_FIXTURE_EXPOSURE = 1
OFFICIAL_PORTFOLIO_PRODUCTS = ("rollover", "banker", "2_odds", "5_odds", "10_odds")

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


def _web_role_read_only() -> bool:
    """Deployed web processes may read cards but never generate them."""
    environment = os.getenv(
        "ENVIRONMENT", "development"
    ).strip().lower()

    role = os.getenv(
        "BETSIGHTLY_PROCESS_ROLE", ""
    ).strip().lower()

    return (
        environment in {"production", "prod", "staging"}
        and role == "web"
    )

def _trusted_rollover_picks(picks: list) -> list:
    """Markets with enough settled evidence for the site's safest challenge."""
    return [p for p in picks if p.get("safe_tier_eligible")]


def _pick_teams(pick: dict) -> set[str]:
    fixture = pick.get("_fixture") or {}
    return {
        str((fixture.get(side) or {}).get("name") or "").strip().casefold()
        for side in ("home", "away")
    } - {""}


def _selection_identity(pick: dict) -> str:
    """Stable identity for the exact football opinion published to a user."""
    market = pick.get("market_key") or pick.get("market") or ""
    prediction = pick.get("prediction") or ""
    return "|".join((str(pick.get("match_id") or ""), str(market), str(prediction)))


def _selection_ids(selection) -> list[str]:
    return [_selection_identity(pick) for pick in selection[0]]


def _sync_portfolio_diagnostics_from_card(
    accumulators: dict, diagnostics: dict
) -> None:
    """Make diagnostics describe the actual card that will be locked.

    Pre-publication SportyBet rebuilding may replace an unavailable leg with
    another already-qualified candidate.  The replacement is allowed to become
    official before first lock, so the audit record must follow that final set
    rather than continuing to describe the earlier model-only version.
    """
    products = diagnostics.get("products") or {}

    for name in ("banker", "2_odds", "5_odds", "10_odds"):
        data = accumulators.get(name) or {}
        entry = products.get(name)
        if not isinstance(entry, dict):
            continue

        games = data.get("games") or []
        entry["final_selection_ids"] = [
            _selection_identity(game) for game in games
        ]
        entry["final_odds"] = round(
            float(data.get("total_odds") or 0.0), 4
        )
        entry["final_joint_probability"] = round(
            float(data.get("hit_probability") or 0.0), 6
        )
        entry["quality_cost"] = round(
            max(
                0.0,
                float(entry.get("independent_joint_probability") or 0.0)
                - float(entry.get("final_joint_probability") or 0.0),
            ),
            6,
        )
        entry["prepublication_rebuilt"] = bool(
            data.get("prepublication_replacements")
        )

    selection_counts: dict[str, int] = {}
    fixture_counts: dict[str, int] = {}

    for name in OFFICIAL_PORTFOLIO_PRODUCTS:
        entry = products.get(name) or {}
        for identity in entry.get("final_selection_ids") or []:
            selection_counts[identity] = (
                selection_counts.get(identity, 0) + 1
            )
            fixture_id = str(identity).split("|", 1)[0]
            if fixture_id:
                fixture_counts[fixture_id] = (
                    fixture_counts.get(fixture_id, 0) + 1
                )

    duplicate_selections = sorted(
        identity
        for identity, count in selection_counts.items()
        if count > MAX_OFFICIAL_SELECTION_EXPOSURE
    )
    duplicate_fixtures = sorted(
        fixture_id
        for fixture_id, count in fixture_counts.items()
        if count > MAX_OFFICIAL_FIXTURE_EXPOSURE
    )

    if duplicate_selections or duplicate_fixtures:
        problems = []
        if duplicate_selections:
            problems.append(
                "duplicate exact selection "
                + ", ".join(duplicate_selections)
            )
        if duplicate_fixtures:
            problems.append(
                "duplicate fixture "
                + ", ".join(duplicate_fixtures)
            )
        raise RuntimeError(
            "official portfolio integrity violation after "
            "prepublication booking: " + "; ".join(problems)
        )

    diagnostics["portfolio_validation"] = {
        "exact_selection_overlap_count": 0,
        "fixture_overlap_count": 0,
        "max_selection_exposure": max(
            selection_counts.values(), default=0
        ),
        "max_fixture_exposure": max(
            fixture_counts.values(), default=0
        ),
        "fixture_count": len(fixture_counts),
        "selection_count": len(selection_counts),
        "valid": True,
    }


def _wat_now(now: datetime | None = None) -> datetime:
    # Return WAT wall-clock time for `now`, or for the current instant.
    return (now or datetime.now(timezone.utc)) + WAT_OFFSET


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
                 prefer: str = "joint", band_low: float = 0.80,
                 canonicalize: bool = True):
    """Select a tier, and say which of the two reasons left it empty.

    A blank tier has two quite different causes and they were reported with
    the same "not enough matches" line, which is misleading when there were
    plenty of matches and the slip was simply refused for being poor value.
    Re-running ungated tells them apart: if a slip exists without the floor,
    the day had the fixtures and the value was the problem.
    """
    from leagues.selection import select_accumulator

    sel = select_accumulator(picks, target, max_picks, min_confidence,
                             min_ev=min_ev, prefer=prefer, band_low=band_low,
                             canonicalize=canonicalize)
    if sel[0]:
        return sel, None

    ungated = select_accumulator(picks, target, max_picks, min_confidence,
                                 min_ev=0.0, prefer=prefer, band_low=band_low,
                                 canonicalize=canonicalize)
    if ungated[0]:
        _, total, joint = ungated
        return sel, (
            f"Today's best {target:g}x slip lands about {joint:.0%} of the time, "
            f"which returns roughly {total * joint:.2f} for every 1 staked. "
            f"That is too thin to put our name on, so we are sitting it out."
        )
    return sel, (
        f"No combination met today's prediction, price and slip-quality "
        f"rules for {target:g}x. Check the next board for new options."
    )


def build_daily_accumulators(force: bool = False, *, preview: dict | None = None,
                             allow_generation: bool = True) -> dict:
    """Category picks + rollover chain for the next actionable match day."""
    import time as _time

    # Defence in depth: even if a caller forgets allow_generation=False,
    # deployed web processes can never cold-start the prediction pipeline.
    if preview is None and _web_role_read_only():
        allow_generation = False

    now_ts = _time.time()
    if (preview is None and not force and _accum_cache["result"]
            and _accum_cache["result"].get("publication_date") == _publish_date()
            and (now_ts - _accum_cache["ts"]) < _ACCUM_CACHE_TTL):
        return _accum_cache["result"]

    from leagues.engine import run_pipeline, picks_for_date
    from leagues.selection import select_accumulator, select_banker
    from leagues.picks import (
        ESTIMATE_MARGIN, MIN_CANDIDATE_CONFIDENCE, MIN_PUBLISHABLE_CONFIDENCE,
        to_game)

    now = (datetime.fromisoformat(preview["captured_at"])
           if preview is not None else datetime.now(timezone.utc))
    publish_date = (preview["target_wat_date"]
                    if preview is not None else _publish_date())
    existing_card = None if preview is not None else _load_locked(publish_date)

    # Serve the locked card if today's has already been published. Re-selecting
    # through the day would quietly swap picks out from under anyone who booked
    # off the morning card.
    if preview is None and not force:
        locked = existing_card
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
            _fixture_target = locked.pop("_fixture_target_date", publish_date)
            locked.pop("_publication_date", None)
            result = {
                "status": "success",
                "date": publish_date,
                "publication_date": publish_date,
                "fixture_target_date": _fixture_target,
                "source": "leagues",
                "published_at_wat": f"{PUBLISH_HOUR_WAT:02d}:00",
                "locked": True,
                "revision": _rev,
                "first_published_at": _first,
                "last_updated_at": _updated,
                "total_fixtures": sum(len(c.get("games", [])) for c in locked.values() if isinstance(c, dict)),
                "accumulators": _attach_bookings(
                    publish_date, _mark_started(locked, now), now),
            }
            _accum_cache.update({"result": result, "ts": now_ts})
            return result

    if preview is None and not allow_generation:
        return None

    if preview is None:
        from leagues.engine import prepared_board
        prepared_picks, prepared_fixtures, board = prepared_board(4)
        if not force and board.get("ready") and not board.get("stale"):
            all_picks, fixtures = prepared_picks, prepared_fixtures
        else:
            all_picks, fixtures = run_pipeline(days_ahead=4, force=force)
    else:
        all_picks, fixtures = preview["picks"], preview["fixtures"]
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

    # Rank football opinions before any product asks them to buy a multiplier.
    from leagues.fixture_ranker import canonical_fixture_recommendations
    day_picks = canonical_fixture_recommendations(day_picks)
    if not day_picks:
        return None

    # Probability remains a quality floor, but it is no longer permission to
    # publish a bad price. The official publication contract separately
    # requires every leg and the completed slip to meet a >= 1.00 conservative
    # model-return floor. If the market does not offer that today, the product
    # is withheld instead of buying the target by accepting bookmaker margin.
    FLOOR = MIN_PUBLISHABLE_CONFIDENCE

    # Model analysis and official publication are deliberately separate.
    # The model may keep analysing a fixture, but a Premium product only sees
    # candidates that pass the single fail-closed publication contract.
    rollover_ranked = canonical_fixture_recommendations(all_picks)
    rollover_source, rollover_rejections = filter_official_candidates(
        rollover_ranked, "rollover"
    )
    official_source, official_rejections = filter_official_candidates(
        day_picks, "5_odds"
    )
    banker_source, banker_rejections = filter_official_candidates(
        day_picks, "banker"
    )
    over_source, over_rejections = filter_official_candidates(
        day_picks, "over_1_5"
    )

    # Build the football products independently first, but never below the
    # publication contract.  A missing tier is now a valid product decision.
    rollover = _build_rollover(
        rollover_source, today, preview=preview is not None
    )

    # A product rejected by Publication Contract v1 must not
    # reserve fixture/selection exposure from later tiers.
    _rollover_preallocation_card = {"rollover": rollover}
    enforce_card_policy(_rollover_preallocation_card)
    rollover = _rollover_preallocation_card["rollover"]
    independent_banker = select_banker(
        banker_source, canonicalize=False
    )
    independent_two, two_why = _select_tier(
        official_source, 2.0, 4, FLOOR, MIN_SLIP_MODEL_RETURN,
        band_low=0.92, canonicalize=False)
    independent_five, five_why = _select_tier(
        official_source, 5.0, 8, FLOOR, MIN_SLIP_MODEL_RETURN,
        canonicalize=False)
    independent_ten, ten_why = _select_tier(
        official_source, 10.0, 10, FLOOR, MIN_SLIP_MODEL_RETURN,
        canonicalize=False)

    fixture_uses = {
        str(game.get("match_id")) for game in rollover.get("games", [])
        if game.get("match_id")
    }
    selection_uses = {
        _selection_identity(game) for game in rollover.get("games", [])
        if game.get("match_id")
    }
    team_uses = {
        str(game.get(field) or "").strip().casefold()
        for game in rollover.get("games", [])
        for field in ("home_team", "away_team")
    } - {""}
    portfolio_diagnostics = {
        "portfolio_version": OFFICIAL_PORTFOLIO_VERSION,
        "policy": "OFFICIAL_SELECTION_EXPOSURE_FIRST",
        "max_official_selection_exposure": MAX_OFFICIAL_SELECTION_EXPOSURE,
        "max_official_fixture_exposure": MAX_OFFICIAL_FIXTURE_EXPOSURE,
        "rollover_isolated_first": True,
"official_product_order": list(OFFICIAL_PORTFOLIO_PRODUCTS),
"publication_policy": {
    "version": PUBLICATION_POLICY_VERSION,
    "minimum_model_return": MIN_SLIP_MODEL_RETURN,
    "rejections": {
        "official": rejection_summary(official_rejections),
        "banker": rejection_summary(banker_rejections),
        "over_1_5": rejection_summary(over_rejections),
        "rollover": rejection_summary(rollover_rejections),
    },
},
"products": {},
    }
    rollover_selection = (rollover.get("games", []), rollover.get("total_odds", 0),
                          rollover.get("today_hit_probability", 0) or 0)
    portfolio_diagnostics["products"]["rollover"] = {
        "independent_odds": rollover_selection[1],
        "final_odds": rollover_selection[1],
        "independent_joint_probability": rollover_selection[2],
        "final_joint_probability": rollover_selection[2],
        "independent_selection_ids": _selection_ids(rollover_selection),
        "final_selection_ids": _selection_ids(rollover_selection),
        "exact_selection_overlap_count": 0,
        "fixture_overlap_count": 0,
        "excluded_due_to_selection_exposure": [],
        "decision": "INDEPENDENT_BEST",
        "quality_cost": 0.0,
    }

    def _record_use(selection):
        for pick in selection[0]:
            fixture_uses.add(str(pick["match_id"]))
            selection_uses.add(_selection_identity(pick))
            team_uses.update(_pick_teams(pick))

    def _portfolio_product(name, independent, source, selector):
        independent_ids = _selection_ids(independent)
        exact_conflicts = [
            pick for pick in independent[0]
            if _selection_identity(pick) in selection_uses
        ]
        fixture_conflicts = [
            pick for pick in independent[0]
            if str(pick["match_id"]) in fixture_uses
        ]
        team_conflicts = [
            pick for pick in independent[0]
            if str(pick["match_id"]) not in fixture_uses
            and bool(_pick_teams(pick) & team_uses)
        ]
        excluded_exact = [
            pick for pick in source if _selection_identity(pick) in selection_uses
        ]
        # Exact selection exposure is an absolute customer-risk rule.  It is
        # applied before any tier search, so target odds can never make an
        # earlier published opinion reappear in a later official accumulator.
        exact_safe_pool = [
            pick for pick in source if _selection_identity(pick) not in selection_uses
        ]
        adjusted = selector(exact_safe_pool)
        decision = "INDEPENDENT_BEST"
        if exact_conflicts:
            decision = "DIVERSIFIED"
        if not adjusted[0] and independent[0]:
            # No eligible alternative after absolute selection de-duplication:
            # withhold this product rather than re-publish the same opinion.
            adjusted = ([], 0.0, 0.0)
            decision = "WITHHELD_FOR_SELECTION_EXPOSURE"

        # Exact fixture exposure is also a hard customer-risk rule. A
        # different market on the same match is still the same match-level
        # failure exposure. Team overlap across different fixtures remains a
        # softer diversification preference.
        if adjusted[0]:
            exact_fixture_conflicts = [
                pick for pick in adjusted[0]
                if str(pick["match_id"]) in fixture_uses
            ]
            if exact_fixture_conflicts:
                fixture_safe_pool = [
                    pick for pick in exact_safe_pool
                    if str(pick["match_id"]) not in fixture_uses
                ]
                fixture_safe = selector(fixture_safe_pool)
                if fixture_safe[0]:
                    adjusted = fixture_safe
                    decision = "DIVERSIFIED"
                else:
                    adjusted = ([], 0.0, 0.0)
                    decision = "WITHHELD_FOR_FIXTURE_EXPOSURE"

            # Different fixtures involving an already-used team are still
            # preferably diversified, but this is not the hard fixture cap.
            if adjusted[0]:
                team_conflicts = [
                    pick for pick in adjusted[0]
                    if bool(_pick_teams(pick) & team_uses)
                ]
                if team_conflicts:
                    team_safe_pool = [
                        pick for pick in exact_safe_pool
                        if str(pick["match_id"]) not in fixture_uses
                        and not (_pick_teams(pick) & team_uses)
                    ]
                    team_safe = selector(team_safe_pool)
                    if team_safe[0]:
                        adjusted = team_safe
                        decision = "DIVERSIFIED"
                    else:
                        decision = "QUALITY_CAPPED_FOR_TEAM_DIVERSIFICATION"

        quality_cost = max(0.0, independent[2] - adjusted[2]) if adjusted[0] else independent[2]
        _record_use(adjusted)
        portfolio_diagnostics["products"][name] = {
            "independent_odds": independent[1],
            "final_odds": adjusted[1],
            "independent_joint_probability": independent[2],
            "final_joint_probability": adjusted[2],
            "independent_selection_ids": independent_ids,
            "final_selection_ids": _selection_ids(adjusted),
            "exact_selection_overlap_count": len(exact_conflicts),
            "fixture_overlap_count": len(fixture_conflicts),
            "team_overlap_count": len(team_conflicts),
            "excluded_due_to_selection_exposure": [
                _selection_identity(pick) for pick in excluded_exact
            ],
            "excluded_due_to_fixture_exposure": sorted({
                str(pick["match_id"])
                for pick in source
                if str(pick["match_id"]) in fixture_uses
            }),
            "excluded_due_to_team_exposure": sorted({
                str(pick["match_id"])
                for pick in source
                if str(pick["match_id"]) not in fixture_uses
                and bool(_pick_teams(pick) & team_uses)
            }),
            "decision": decision,
            "quality_cost": round(quality_cost, 6),
        }
        return adjusted

    banker = _portfolio_product(
        "banker", independent_banker, banker_source,
        lambda pool: select_banker(pool, canonicalize=False))
    two = _portfolio_product(
        "2_odds", independent_two, official_source,
        lambda pool: _select_tier(
            pool, 2.0, 4, FLOOR, MIN_SLIP_MODEL_RETURN,
            band_low=0.92, canonicalize=False)[0])
    five = _portfolio_product(
        "5_odds", independent_five, official_source,
        lambda pool: _select_tier(
            pool, 5.0, 8, FLOOR, MIN_SLIP_MODEL_RETURN,
            canonicalize=False)[0])
    ten = _portfolio_product(
        "10_odds", independent_ten, official_source,
        lambda pool: _select_tier(
            pool, 10.0, 10, FLOOR, MIN_SLIP_MODEL_RETURN,
            canonicalize=False)[0])

    # A defensive invariant for future selector changes.  The individual
    # searches above are allowed to quality-cap or withhold, but publication
    # cannot silently reintroduce the same exact selection in two official
    # accumulator products.
    final_official = {
        "rollover": rollover_selection,
        "banker": banker,
        "2_odds": two,
        "5_odds": five,
        "10_odds": ten,
    }
    selection_exposure_counts: dict[str, int] = {}
    fixture_exposure_counts: dict[str, int] = {}

    for product in OFFICIAL_PORTFOLIO_PRODUCTS:
        for pick in final_official[product][0]:
            identity = _selection_identity(pick)
            selection_exposure_counts[identity] = (
                selection_exposure_counts.get(identity, 0) + 1
            )

            fixture_id = str(pick.get("match_id") or "")
            if fixture_id:
                fixture_exposure_counts[fixture_id] = (
                    fixture_exposure_counts.get(fixture_id, 0) + 1
                )

    duplicate_official = sorted(
        identity
        for identity, count in selection_exposure_counts.items()
        if count > MAX_OFFICIAL_SELECTION_EXPOSURE
    )
    duplicate_fixtures = sorted(
        fixture_id
        for fixture_id, count in fixture_exposure_counts.items()
        if count > MAX_OFFICIAL_FIXTURE_EXPOSURE
    )

    if duplicate_official or duplicate_fixtures:
        problems = []
        if duplicate_official:
            problems.append(
                "duplicate exact selection " + ", ".join(duplicate_official)
            )
        if duplicate_fixtures:
            problems.append(
                "duplicate fixture " + ", ".join(duplicate_fixtures)
            )
        raise RuntimeError(
            "official portfolio integrity violation: " + "; ".join(problems)
        )

    portfolio_diagnostics["portfolio_validation"] = {
        "exact_selection_overlap_count": 0,
        "fixture_overlap_count": 0,
        "max_selection_exposure": max(
            selection_exposure_counts.values(), default=0
        ),
        "max_fixture_exposure": max(
            fixture_exposure_counts.values(), default=0
        ),
        "fixture_count": len(fixture_exposure_counts),
        "selection_count": len(selection_exposure_counts),
        "valid": True,
    }

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
        return (-round(selection_probability(p) / _MARGIN_TIE_BAND),
                not p.get("bookable"),
                margin,
                not (p.get("_model") or {}).get("has_market"))

    over_picks, seen = [], set()
    for p in sorted(over_source, key=_over_rank):
        # Over 1.5 is presented separately, but it remains an official
        # customer exposure. Do not reuse a fixture already allocated to
        # Rollover, Banker, 2x, 5x or 10x (October 8 incident).
        if (p["market"] != "over_1_5"
                or p["match_id"] in seen
                or str(p["match_id"]) in fixture_uses):
            continue
        if selection_probability(p) < OVER_MIN_CONFIDENCE:
            continue
        over_picks.append(p)
        seen.add(p["match_id"])
        if len(over_picks) >= OVER_MAX_PICKS:
            break

    # For singles the meaningful headline is the typical chance of any one
    # landing, not the product of all of them.
    over_avg = (sum(selection_probability(p) for p in over_picks)
                / len(over_picks)
                if over_picks else 0.0)
    over_total = 1.0
    for p in over_picks:
        over_total *= p["odds"]

    def mk_cat(sel, risk, reason_if_empty, presentation="accumulator",
               booking_rule=None, target=None):
        picks_, total, joint = sel
        if not picks_:
            return {"selected": False, "games": [], "total_odds": 0,
                    "risk_level": risk, "hit_probability": 0,
                    "presentation": presentation, "reason": reason_if_empty,
                    "result_status": "NO_SAFE_COMBINATION",
                    "booking_rule": booking_rule}
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
            # A list may remain independent predictions while the one share
            # code which loads them is explicitly an accumulator ticket.
            "sportybet_ticket_type": "accumulator",
            "booking_rule": booking_rule,
            "reason": None,
            "result_status": (
                "TARGET_REACHED" if target is None or total >= target
                else "QUALITY_CAPPED"
            ),
        }

    thin = "Not enough matches today to build this safely — check back tomorrow."

    _built_at = now.isoformat()
    result = {
        "status": "success",
        "date": publish_date,
        "publication_date": publish_date,
        "fixture_target_date": target_date,
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
            "banker": mk_cat(
                banker, "Banker", "No pick met the banker threshold today.",
                booking_rule={"selector": "banker", "safe_only": True}),
            "2_odds": mk_cat(
                two, "Low", two_why,
                target=2.0,
                booking_rule={"selector": "accumulator", "target": 2.0,
                              "max_picks": 4, "min_confidence": FLOOR,
                              "min_ev": MIN_SLIP_MODEL_RETURN, "band_low": 0.92,
                              "safe_only": True}),
            "5_odds": mk_cat(
                five, "Medium", five_why,
                target=5.0,
                booking_rule={"selector": "accumulator", "target": 5.0,
                              "max_picks": 8,
                              "min_confidence": FLOOR,
                              "min_ev": MIN_SLIP_MODEL_RETURN, "band_low": 0.80}),
            "10_odds": mk_cat(
                ten, "High", ten_why,
                target=10.0,
                booking_rule={"selector": "accumulator", "target": 10.0,
                              "max_picks": 10,
                              "min_confidence": FLOOR,
                              "min_ev": MIN_SLIP_MODEL_RETURN, "band_low": 0.80}),
            "over_1_5": mk_cat(
                (over_picks, over_total, over_avg) if over_picks else ([], 0, 0),
                "Very Safe",
                "No match cleared the Over 1.5 confidence bar today.",
                presentation="singles",
                booking_rule={"selector": "over_1_5", "min_confidence":
                              OVER_MIN_CONFIDENCE, "max_picks": OVER_MAX_PICKS},
            ),
            "rollover": rollover,
            # The locked prediction remains unchanged.  This bounded,
            # deterministic snapshot only lets the later booking job find a
            # qualifying replacement without rerunning the prediction engine.
            "_booking_candidates": {
                "games": _booking_candidate_snapshot(official_source, limit=160),
                "bounded": True,
                "limit": 160,
            },
            "_portfolio": portfolio_diagnostics,
            "_publication_date": publish_date,
            "_fixture_target_date": target_date,
        },
    }

    # Explain portfolio exposure decisions directly on the public product.
    # A withheld tier is not an unexplained selector failure: it was available
    # independently but intentionally refused because the remaining safe board
    # would repeat exposure already carried by another official product.
    for product in ("banker", "2_odds", "5_odds", "10_odds"):
        decision = (
            portfolio_diagnostics["products"][product]["decision"]
        )

        if decision == "WITHHELD_FOR_SELECTION_EXPOSURE":
            result["accumulators"][product]["result_status"] = (
                "EXPOSURE_CAPPED"
            )
            result["accumulators"][product]["reason"] = (
                "Withheld because every qualifying version repeated an exact "
                "selection already used by another official BetSightly slip."
            )

        elif decision == "WITHHELD_FOR_FIXTURE_EXPOSURE":
            result["accumulators"][product]["result_status"] = (
                "EXPOSURE_CAPPED"
            )
            result["accumulators"][product]["reason"] = (
                "Withheld because the remaining qualifying versions reused a "
                "match already carried by another official BetSightly slip."
            )

        elif decision == "QUALITY_CAPPED_FOR_TEAM_DIVERSIFICATION":
            result["accumulators"][product]["result_status"] = (
                "QUALITY_CAPPED"
            )
            result["accumulators"][product]["reason"] = (
                "Best qualifying version retained. No different-team "
                "alternative met the existing prediction-quality rules."
            )

    # Final publication contract before any booking side effect.  Candidate
    # filtering should make this a no-op; this assertion prevents a future
    # selector change from bypassing the contract.
    result["publication_policy"] = enforce_card_policy(result["accumulators"])
    _sync_portfolio_diagnostics_from_card(
        result["accumulators"], portfolio_diagnostics
    )

    # Exact booking belongs before first-write lock.  If a chosen leg has
    # disappeared from SportyBet, the existing bounded qualified snapshot may
    # supply a fully validated quality-equivalent replacement; only that FULL
    # rebuilt set is promoted.  Force builds are simulations/repairs and never
    # create booking side effects here.
    if preview is None and not existing_card and not force:
        try:
            from leagues.booking import finalize_prepublication_card
            result["prepublication_booking"] = finalize_prepublication_card(
                publish_date, result["accumulators"]
            )
        except Exception as exc:
            logger.warning("prepublication booking skipped: %s", exc,
                           exc_info=True)

    # A validated pre-publication booking rebuild may have changed the
    # official games. Re-run both contracts before the final archive/lock.
    result["publication_policy"] = enforce_card_policy(result["accumulators"])
    _sync_portfolio_diagnostics_from_card(
        result["accumulators"], portfolio_diagnostics
    )

    # Preserve both the independent counterfactual and the actual version
    # that will be locked, including any validated pre-publication replacement.
    if preview is None:
        try:
            from leagues.decision_archive import record_daily
            snapshot_id = next((p.get("_board_snapshot_id") for p in day_picks
                                if p.get("_board_snapshot_id")), None)
            record_daily(
                snapshot_id, publish_date,
                {"rollover": rollover_selection,
                 "banker": independent_banker, "2_odds": independent_two,
                 "5_odds": independent_five, "10_odds": independent_ten},
                result["accumulators"], portfolio_diagnostics,
            )
            result["decision_snapshot_id"] = snapshot_id
        except Exception as exc:
            logger.warning("daily decision archive skipped: %s", exc,
                           exc_info=True)

    # Archive and lock by the audience-facing publication day even when a
    # thin late board deliberately draws from the next fixture day. Kickoff
    # remains on every leg; the card's immutable identity must not drift.
    if preview is None and not existing_card:
        _archive(publish_date, result["accumulators"])

    # Lock the publication exactly once. A force-build beside an existing
    # card is an unpublished comparison and must never overwrite or relabel it.
    if preview is None and not existing_card:
        try:
            from leagues.picks_db import save_card
            result["locked"] = bool(
                save_card(publish_date, result["accumulators"])
            )
        except Exception as e:
            logger.debug(f"card lock skipped: {e}")

    result["accumulators"] = _mark_started(result["accumulators"], now)
    if result["locked"]:
        # A thin-day card keeps today's publication identity while its legs
        # truthfully retain tomorrow's kickoffs, so today's stored booking is
        # still the exact code that belongs beside this official card.
        result["accumulators"] = _attach_bookings(
            publish_date, result["accumulators"], now)
    if preview is None:
        _accum_cache.update({"result": result, "ts": now_ts})
    return result


def recover_today_empty_tiers() -> dict:
    """Fill eligible empty tiers from the already prepared board only.

    This is a future scheduler entry point, deliberately not enabled by the
    scheduler.  It never calls ``run_pipeline`` and therefore cannot turn a
    maintenance action into an ESPN/history/ELO rebuild.
    """
    from leagues.engine import kickoff_wat_date, prepared_board_status, prepared_pipeline
    from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE, to_game
    from leagues.selection import select_banker
    from leagues.booking import create_booking
    from leagues import sportybet
    from leagues.empty_tier_recovery import recover_empty_tier

    publish_date = _publish_date()
    card = _load_locked(publish_date)
    if not card:
        return {"status": "NO_CARD", "tiers": {}}
    board_status = prepared_board_status(days_ahead=7)
    if not board_status.get("ready"):
        return {"status": "BOARD_UNAVAILABLE", "tiers": {}, "board": board_status}
    picks, _ = prepared_pipeline(days_ahead=7)
    target_day = card.get("_fixture_target_date") or publish_date
    now = datetime.now(timezone.utc)
    bookable_from = (now + BOOKING_BUFFER).isoformat().replace("+00:00", "Z")
    day = [p for p in picks if kickoff_wat_date(p.get("_fixture", {}).get("commence_time")) == target_day
           and p.get("_fixture", {}).get("commence_time", "") >= bookable_from]
    from leagues.fixture_ranker import canonical_fixture_recommendations
    day = canonical_fixture_recommendations(day)
    official_day, _ = filter_official_candidates(day, "5_odds")
    banker_day, _ = filter_official_candidates(day, "banker")

    reserved_fixture_ids = set()
    reserved_selection_ids = set()
    reserved_teams = set()

    for product in OFFICIAL_PORTFOLIO_PRODUCTS:
        current = card.get(product) or {}
        if not (
            isinstance(current, dict)
            and current.get("selected")
            and current.get("games")
        ):
            continue

        for game in current.get("games") or []:
            fixture_id = str(game.get("match_id") or "")
            if fixture_id:
                reserved_fixture_ids.add(fixture_id)

            identity = _selection_identity(game)
            if identity:
                reserved_selection_ids.add(identity)

            for field in ("home_team", "away_team"):
                team = str(game.get(field) or "").strip().casefold()
                if team:
                    reserved_teams.add(team)

    def recovery_available(source: list) -> list:
        return [
            pick
            for pick in source
            if (
                str(pick.get("match_id") or "") not in reserved_fixture_ids
                and _selection_identity(pick) not in reserved_selection_ids
                and not (_pick_teams(pick) & reserved_teams)
            )
        ]

    rules = {
        "banker": (None, 1, 0.80),
        "2_odds": (2.0, 4, .92),
        "5_odds": (5.0, 8, .80),
        "10_odds": (10.0, 10, .80),
    }
    out = {}
    board = None
    for tier, rule in rules.items():
        if isinstance(card.get(tier), dict) and card[tier].get("selected") and card[tier].get("games"):
            continue
        if tier == "banker":
            selected, odds, probability = select_banker(
                recovery_available(banker_day),
                canonicalize=False,
            )
            reason = "No safe banker is available on the prepared board."
        else:
            target, max_picks, band_low = rule
            selected, reason = _select_tier(
                recovery_available(official_day),
                target,
                max_picks,
                MIN_PUBLISHABLE_CONFIDENCE,
                MIN_SLIP_MODEL_RETURN,
                band_low=band_low,
                canonicalize=False,
            )
            selected, odds, probability = selected
        if not selected:
            out[tier] = {"status": "UNREACHABLE", "reason": reason,
                         "best_reachable": 0.0, "binding_constraint": "QUALITY_POLICY"}
            continue
        candidate = {"selected": True, "games": _by_kickoff([to_game(p) for p in selected]),
                     "total_odds": round(odds, 2), "hit_probability": round(probability, 4),
                     "presentation": "accumulator"}
        board = board or sportybet.fetch_board()
        booking = create_booking(candidate["games"], board, booking_status="FULL",
                                 original_games=candidate["games"], predicted_odds=candidate["total_odds"])
        recovery = recover_empty_tier(
            publish_date=publish_date, tier=tier, candidate=candidate, booking=booking,
            decision_snapshot_id=board_status.get("board_snapshot_id"))
        out[tier] = recovery

        if recovery.get("status") == "RECOVERED":
            for pick in selected:
                fixture_id = str(pick.get("match_id") or "")
                if fixture_id:
                    reserved_fixture_ids.add(fixture_id)

                identity = _selection_identity(pick)
                if identity:
                    reserved_selection_ids.add(identity)

                reserved_teams.update(_pick_teams(pick))

    return {"status": "COMPLETE", "tiers": out, "board": board_status}


def _by_kickoff(games: list[dict]) -> list[dict]:
    """Order games by kick-off, earliest first."""
    return sorted(games, key=lambda g: (g.get("kickoff") or g.get("date") or "9999"))


def _booking_candidate_snapshot(picks: list, limit: int = 160) -> list[dict]:
    """Bounded deterministic, market/price-stratified qualified candidates."""
    from leagues.picks import to_game
    buckets: dict[tuple, list] = {}
    for pick in picks:
        price = float(pick.get("odds") or 1)
        band = "short" if price < 1.35 else ("mid" if price < 1.7 else "long")
        buckets.setdefault((pick.get("market_group"), band), []).append(pick)
    for bucket in buckets.values():
        bucket.sort(key=lambda p: (
            -selection_probability(p), p["match_id"], p["market"]
        ))
    ordered, index = [], 0
    keys = sorted(buckets)
    while len(ordered) < limit:
        progressed = False
        for key in keys:
            if index < len(buckets[key]):
                game = to_game(buckets[key][index])
                game.pop("added_at", None)
                ordered.append(game)
                progressed = True
                if len(ordered) >= limit:
                    break
        if not progressed:
            break
        index += 1
    return ordered


def _attach_live_bookings(accumulators: dict, board: dict) -> dict:
    """Create and validate a SportyBet code for every live replacement tier.

    The available-now card is intentionally not persisted as the published
    record, but that must not make it a manual-entry card.  Each selected tier
    still goes through the same create -> read back -> exact-leg validation
    path as the morning card and carries its own booking result in the API.
    """
    from leagues.booking import create_booking

    for tier, data in (accumulators or {}).items():
        if tier.startswith("_") or not isinstance(data, dict):
            continue
        games = data.get("games") or []
        if not data.get("selected") or not games:
            continue
        data["booking"] = create_booking(
            games,
            board,
            allow_partial=data.get("presentation") == "singles",
            booking_status="FULL",
            original_games=games,
            predicted_odds=data.get("total_odds"),
            ticket_type=data.get("sportybet_ticket_type", "accumulator"),
        )
    return accumulators


def _validate_bookable_now_portfolio(accumulators: dict, rollover: dict) -> dict:
    """Fail closed if the live action card would repeat an official fixture.

    ``bookable-now`` is deliberately separate from the immutable morning card,
    but it is still presented as one diversified set of accumulator products.
    Selection-time exclusion should make this a no-op.  This final check is a
    defense against a future selector or booking change exposing a later tier
    that reuses a fixture already claimed by Rollover, Banker, 2 Odds, or 5
    Odds.  Over 1.5 remains independent singles by product design.
    """
    selection_counts: dict[str, int] = {}
    fixture_counts: dict[str, int] = {}
    withheld: list[dict] = []

    def claim(games: list[dict]) -> None:
        for game in games:
            identity = _selection_identity(game)
            fixture_id = str(game.get("match_id") or "")
            if identity:
                selection_counts[identity] = selection_counts.get(identity, 0) + 1
            if fixture_id:
                fixture_counts[fixture_id] = fixture_counts.get(fixture_id, 0) + 1

    # The original rollover chain is not rebuilt or rebooked here, but its
    # fixture exposure is reserved before dynamic tiers are considered.
    claim((rollover or {}).get("games") or [])

    for product in ("banker", "2_odds", "5_odds", "10_odds"):
        data = accumulators.get(product) or {}
        if not data.get("selected"):
            continue
        games = data.get("games") or []
        identities = [_selection_identity(game) for game in games]
        fixture_ids = [str(game.get("match_id") or "") for game in games]
        duplicate_selections = sorted({
            identity for identity in identities
            if identity and selection_counts.get(identity, 0) >= MAX_OFFICIAL_SELECTION_EXPOSURE
        })
        duplicate_fixtures = sorted({
            fixture_id for fixture_id in fixture_ids
            if fixture_id and fixture_counts.get(fixture_id, 0) >= MAX_OFFICIAL_FIXTURE_EXPOSURE
        })
        # A duplicate inside a dynamically-built tier is just as unsafe as a
        # duplicate across tiers.  Do not turn that tier into a different bet.
        duplicate_selections.extend(sorted({
            identity for identity in identities if identity and identities.count(identity) > 1
        }))
        duplicate_fixtures.extend(sorted({
            fixture_id for fixture_id in fixture_ids if fixture_id and fixture_ids.count(fixture_id) > 1
        }))
        duplicate_selections = sorted(set(duplicate_selections))
        duplicate_fixtures = sorted(set(duplicate_fixtures))
        if duplicate_selections or duplicate_fixtures:
            withheld.append({
                "product": product,
                "duplicate_selection_ids": duplicate_selections,
                "duplicate_fixture_ids": duplicate_fixtures,
            })
            # Do not expose a fresh code that represents a card we refuse to
            # display.  The immutable published code/card is never touched.
            data.pop("booking", None)
            data.update(
                selected=False, games=[], total_odds=0, hit_probability=0,
                reason="Withheld because it repeats a fixture in the live portfolio.",
            )
            continue
        claim(games)

    duplicate_selection_count = sum(
        count - MAX_OFFICIAL_SELECTION_EXPOSURE
        for count in selection_counts.values()
        if count > MAX_OFFICIAL_SELECTION_EXPOSURE
    )
    duplicate_fixture_count = sum(
        count - MAX_OFFICIAL_FIXTURE_EXPOSURE
        for count in fixture_counts.values()
        if count > MAX_OFFICIAL_FIXTURE_EXPOSURE
    )
    return {
        "portfolio_version": OFFICIAL_PORTFOLIO_VERSION,
        "policy": "available_now_official_exposure_v1",
        "rollover_claimed_fixture_ids": sorted(
            str(game.get("match_id")) for game in (rollover or {}).get("games") or []
            if game.get("match_id")
        ),
        "withheld_products": withheld,
        "portfolio_validation": {
            "exact_selection_overlap_count": duplicate_selection_count,
            "fixture_overlap_count": duplicate_fixture_count,
            "max_selection_exposure": max(selection_counts.values(), default=0),
            "max_fixture_exposure": max(fixture_counts.values(), default=0),
            "fixture_count": len(fixture_counts),
            "selection_count": len(selection_counts),
            "valid": not duplicate_selection_count and not duplicate_fixture_count,
        },
    }


def build_bookable_now(all_picks: list[dict] | None = None) -> dict | None:
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
    from leagues.engine import kickoff_wat_date, prepared_pipeline
    from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE, to_game
    from leagues.selection import select_banker

    now = datetime.now(timezone.utc)
    if all_picks is None:
        all_picks, _ = prepared_pipeline(days_ahead=2)
    if not all_picks:
        return None

    bookable_from = (now + BOOKING_BUFFER).isoformat().replace("+00:00", "Z")
    # "Today" is an audience-facing calendar day. Around midnight WAT the
    # UTC date is still yesterday, which used to make the available-now card
    # search the wrong fixtures for the first hour of the Nigerian day.
    today = _wat_now(now).strftime("%Y-%m-%d")
    live = [p for p in all_picks
            if p["_fixture"]["commence_time"] >= bookable_from
            and kickoff_wat_date(p["_fixture"]["commence_time"]) == today
            and p.get("bookable")]
    if not live:
        return None

    F = MIN_PUBLISHABLE_CONFIDENCE
    from leagues.fixture_ranker import canonical_fixture_recommendations
    live = canonical_fixture_recommendations(live)
    official_live, _ = filter_official_candidates(live, "5_odds")
    banker_live, _ = filter_official_candidates(live, "banker")
    over_live, _ = filter_official_candidates(live, "over_1_5")

    rollover = _build_rollover([], today)

    # Available Now obeys the same exposure rule as morning publication.
    _live_rollover_preallocation_card = {"rollover": rollover}
    enforce_card_policy(_live_rollover_preallocation_card)
    rollover = _live_rollover_preallocation_card["rollover"]
    fixture_uses = {
        game.get("match_id") for game in rollover.get("games", [])
        if game.get("match_id")
    }
    team_uses = {
        str(game.get(field) or "").strip().casefold()
        for game in rollover.get("games", [])
        for field in ("home_team", "away_team")
    } - {""}

    def available(source: list) -> list:
        return [p for p in source
                if p["match_id"] not in fixture_uses
                and not (_pick_teams(p) & team_uses)]

    banker = select_banker(available(banker_live), canonicalize=False)
    fixture_uses.update(p["match_id"] for p in banker[0])
    for pick in banker[0]:
        team_uses.update(_pick_teams(pick))
    two, _ = _select_tier(
        available(official_live), 2.0, 4, F, MIN_SLIP_MODEL_RETURN,
        band_low=0.92, canonicalize=False)
    fixture_uses.update(p["match_id"] for p in two[0])
    for pick in two[0]:
        team_uses.update(_pick_teams(pick))
    five, _ = _select_tier(
        available(official_live), 5.0, 8, F, MIN_SLIP_MODEL_RETURN,
        canonicalize=False)
    fixture_uses.update(p["match_id"] for p in five[0])
    for pick in five[0]:
        team_uses.update(_pick_teams(pick))
    ten, _ = _select_tier(
        available(official_live), 10.0, 10, F, MIN_SLIP_MODEL_RETURN,
        canonicalize=False)

    over, seen = [], set()
    for p in sorted(over_live, key=lambda x: -selection_probability(x)):
        if (p["market"] != "over_1_5" or p["match_id"] in seen
                or selection_probability(p) < 0.65):
            continue
        over.append(p)
        seen.add(p["match_id"])
        if len(over) >= 10:
            break
    over_avg = (sum(selection_probability(p) for p in over) / len(over)
                if over else 0.0)
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

    accumulators = {
        "banker": cat(banker, "Banker"),
        "2_odds": cat(two, "Low"),
        "5_odds": cat(five, "Medium"),
        "10_odds": cat(ten, "High"),
        "over_1_5": cat((over, over_total, over_avg) if over else ([], 0, 0),
                        "Very Safe", presentation="singles"),
    }

    # Reuse the cached board populated by run_pipeline where possible.  A
    # single snapshot is shared by every tier so the selections and codes are
    # validated against the same view of SportyBet availability.
    from leagues import sportybet
    board = sportybet.fetch_board()
    _attach_live_bookings(accumulators, board)
    enforce_card_policy(accumulators)

    active_tiers = 0
    for category in accumulators.values():
        booking = category.get("booking") or {}
        exact = (
            booking.get("status") == "active"
            and booking.get("booking_status") in {"FULL", "REBUILT_FULL"}
            and booking.get("readback_validation") == "PASSED"
            and booking.get("share_code")
        )
        if exact:
            active_tiers += 1
            continue
        # Available-now is an action surface, not the official record. Never
        # show a rebuilt tier as usable unless its current code was read back
        # and exactly matches every displayed selection.
        category.update(
            selected=False, games=[], total_odds=0, hit_probability=0,
            reason=(booking.get("reason") or
                    "No exact SportyBet-ready slip could be verified."),
        )

    portfolio = _validate_bookable_now_portfolio(accumulators, rollover)
    # A malformed rollover must not be used as the basis for a dynamic card.
    # Normal selector output has one fixture per product, so this is a final
    # fail-closed guard rather than a product-path change.
    if not portfolio["portfolio_validation"]["valid"]:
        for category in accumulators.values():
            if isinstance(category, dict) and category.get("selected"):
                category.pop("booking", None)
                category.update(
                    selected=False, games=[], total_odds=0, hit_probability=0,
                    reason="Live portfolio validation could not be completed safely.",
                )

    active_tiers = sum(
        1 for category in accumulators.values()
        if isinstance(category, dict) and category.get("selected")
    )

    return {
        "status": "success",
        "available": active_tiers > 0,
        "reason": (None if active_tiers else
                   "No future exact-bookable SportyBet slip could be verified."),
        "date": today,
        "generated_at": now.isoformat(),
        "kickoffs_remaining": len({p["match_id"] for p in live}),
        "accumulators": accumulators,
        "_portfolio": portfolio,
    }


def _attach_bookings(publish_date: str, accumulators: dict,
                     now: datetime | None = None) -> dict:
    """Hang stored booking codes on the card, never failing the card for it.

    A bookmaker being unreachable must not take the predictions down with it —
    the picks are the product, the code is a convenience on top.
    """
    try:
        from leagues.booking import attach_bookings
        out = attach_bookings(publish_date, accumulators, now)
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
    for cat in accumulators.values():
        if not isinstance(cat, dict):
            continue
        games = cat.get("games") or []
        started = 0
        for g in games:
            lifecycle = game_kickoff_lifecycle(g, now)
            g["kickoff_status"] = lifecycle
            g["started"] = lifecycle in {"started", "kickoff_buffer", "invalid"}
            g["actionable"] = lifecycle == "actionable"
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
        if (category == "rollover" or category.startswith("_")
                or not isinstance(cat, dict) or not cat.get("selected")):
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

def _build_rollover(all_picks: list, today: str, *, preview: bool = False) -> dict:
    """Short chain, one slot per match day, persisted to Postgres."""
    from leagues.engine import kickoff_wat_date, picks_for_date
    from leagues.selection import select_rollover_day
    from leagues.picks import to_game

    try:
        from leagues.rollover_db import (
            load_chain as _db_load,
            append_day as _db_append,
            reset_chain as _db_reset,
        )
        db_available = not preview
    except Exception:
        db_available = False
        _db_load = _db_append = _db_reset = None  # type: ignore

    chain_path = DATA_DIR / "rollover_chain.json"
    if preview:
        chain = {"start_date": today, "days": [], "status": "active"}
    elif db_available:
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

    # Result status belongs to the result checker.  This reader used to void
    # an entire day solely because its date was two days old, before the
    # checker had a chance to grade the scores it *could* find.  That both
    # erased real wins/losses and made chains appear never to complete.

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
        d = kickoff_wat_date(p["_fixture"]["commence_time"])
        if d is None:
            continue
        if d >= today:
            by_date.setdefault(d, []).append(p)

    last_date = chain["days"][-1]["date"] if chain.get("days") else ""
    needed = TARGET_DAYS - len(chain.get("days", []))

    for date in sorted(by_date):
        if needed <= 0:
            break
        if date <= last_date:
            continue
        # A challenge advertised as the safest route cannot be where a new,
        # uncalibrated market collects its first results.  Require the same
        # 25-leg evidence gate as Banker and 2 Odds; an empty day is safer than
        # another Under 3.5 leg with no settled record.
        trusted = _trusted_rollover_picks(by_date[date])
        chosen, combined, joint = select_rollover_day(trusted)
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
                    "league_slug": p["_fixture"].get("league_slug"),
                    "competition_type": p["_fixture"].get("competition_type"),
                    "competition_region": p["_fixture"].get("region"),
                    "team_type": p["_fixture"].get("team_type"),
                    "competition_stage": p["_fixture"].get("stage"),
                    "competition_context_label": p["_fixture"].get("context_label"),
                    "neutral_venue": p["_fixture"].get("neutral_venue", False),
                    "knockout": p["_fixture"].get("knockout", False),
                    "leg_number": p["_fixture"].get("leg_number"),
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
                    "safe_tier_eligible": p.get("safe_tier_eligible", False),
                    "calibration_sample": p.get("calibration_sample", 0),
                    "status": "pending",
                }
                for p in chosen
            ],
        }
        chain["days"].append(new_day)
        needed -= 1

        if preview:
            pass
        elif db_available:
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
        "completion_probability": round(
            prod(
                float(d.get("hit_probability") or d.get("avg_confidence") or 0)
                for d in chain.get("days", [])
            ), 4
        ) if chain.get("days") else None,
    }
