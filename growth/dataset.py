"""
The daily marketing dataset.

One read of the published card, normalised into the shape every channel
renders from. No selection, scoring or pricing happens here — those already
happened in `leagues/` and happened *once*, under the 08:00 WAT lock. This
module's only job is to pick out the parts worth talking about and hand them
over in a stable shape.

Two things it deliberately does not do:

- It does not re-run the pipeline. `build_daily_accumulators()` serves the
  locked card, so the picks in a Telegram post are byte-identical to the picks
  on the site. Calling the engine directly would re-select and could publish a
  slip the website never showed.
- It does not filter out started fixtures. The card marks them via `started`,
  and content generation decides what to do about it, because a morning post
  and an evening results post want opposite behaviour.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Confidence at or above which a leg is worth calling out on its own.
HIGH_CONFIDENCE = 0.70

# Tiers in the order a human would read them, safest first.
TIER_ORDER = ["banker", "over_1_5", "2_odds", "5_odds", "10_odds"]

TIER_LABELS = {
    "banker": "Banker",
    "over_1_5": "Over 1.5",
    "2_odds": "2 Odds",
    "5_odds": "5 Odds",
    "10_odds": "10 Odds",
    "rollover": "Rollover",
}


def _is_actionable(kickoff: str | None, started: bool = False) -> bool:
    """Whether a code can still be acted on at render time."""
    if not kickoff or started:
        return False
    try:
        parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed > datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False


def _leg(game: dict, tier: str | None = None) -> dict:
    """One pick, flattened to the fields any channel might render."""
    conf = game.get("confidence") or 0.0
    odds = game.get("odds") or game.get("estimated_odds") or 0.0
    kickoff = game.get("kickoff") or game.get("date")
    started = bool(game.get("started"))
    actionable = _is_actionable(kickoff, started)
    return {
        "match_id": game.get("match_id"),
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
        "home_team_logo": game.get("home_team_logo"),
        "away_team_logo": game.get("away_team_logo"),
        "league": game.get("league"),
        "league_slug": game.get("league_slug"),
        "kickoff": kickoff,
        "prediction": game.get("prediction") or game.get("readable_prediction"),
        "market": game.get("market"),
        "market_group": game.get("prediction_type"),
        "confidence": round(float(conf), 4),
        "odds": round(float(odds), 2),
        "odds_are_real": bool(game.get("odds_are_real")),
        "started": started,
        "actionable": actionable,
        "venue": game.get("venue"),
        "home_form": game.get("home_form"),
        "away_form": game.get("away_form"),
        # Slug used for the shareable match page. Stable for a given fixture.
        "slug": match_slug(game.get("home_team"), game.get("away_team")),
        "tier": tier,
    }


def match_slug(home: Optional[str], away: Optional[str]) -> Optional[str]:
    """URL slug for a fixture, e.g. `libertad-vs-sportivo-trinidense`.

    Deterministic so the same fixture always resolves to the same URL — a link
    posted at 09:00 has to still work when someone opens it that evening, and
    the canonical tag has to agree with whatever was shared.
    """
    import re
    import unicodedata

    if not home or not away:
        return None

    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
        return s

    h, a = norm(home), norm(away)
    return f"{h}-vs-{a}" if h and a else None


def _tier_block(key: str, cat: dict) -> dict:
    """A whole accumulator tier, with the honest numbers attached."""
    games = cat.get("games") or []
    total = float(cat.get("total_odds") or 0.0)
    hit = float(cat.get("hit_probability") or 0.0)
    legs = [_leg(g, key) for g in games]
    try:
        from leagues.booking import validated_public_booking
        booking = validated_public_booking(cat.get("booking"), games)
    except Exception as exc:
        logger.warning(f"growth: booking validation failed for {key} ({exc})")
        booking = None
    return {
        "key": key,
        "label": TIER_LABELS.get(key, key),
        "selected": bool(cat.get("selected")) and bool(games),
        "reason": cat.get("reason"),
        "total_odds": round(total, 2),
        "hit_probability": round(hit, 4),
        # Payout times the chance it lands. Published so no channel has to
        # imply a slip is better than it is.
        "expected_value": round(total * hit, 4) if total and hit else None,
        "legs": legs,
        "leg_count": len(games),
        "all_started": bool(cat.get("all_started")),
        "actionable": bool(legs) and all(leg["actionable"] for leg in legs),
        "booking": booking,
        "booking_verified": bool(booking),
    }


def _rollover_block(cat: dict, today: str) -> dict:
    """Today's rollover slot plus the state of the chain around it."""
    chain = cat.get("chain") or []
    today_day = next(
        (d for d in chain
         if (d.get("date") or "") == today and d.get("status") == "pending"),
        None,
    )
    legs = []
    if today_day:
        for p in today_day.get("picks", []):
            legs.append({
                "match_id": p.get("match_id"),
                "home_team": p.get("home_team"),
                "away_team": p.get("away_team"),
                "league": p.get("league"),
                "kickoff": p.get("commence_time"),
                "prediction": p.get("prediction"),
                "confidence": round(float(p.get("confidence") or 0.0), 4),
                "odds": round(float(p.get("odds") or 0.0), 2),
                "odds_are_real": bool(p.get("odds_are_real")),
                "started": not _is_actionable(p.get("commence_time")),
                "actionable": _is_actionable(p.get("commence_time")),
                "slug": match_slug(p.get("home_team"), p.get("away_team")),
                "tier": "rollover",
            })

    won = sum(1 for d in chain if d.get("status") == "won")
    lost = sum(1 for d in chain if d.get("status") == "lost")
    raw_games = cat.get("games") or []
    try:
        from leagues.booking import validated_public_booking
        booking = validated_public_booking(cat.get("booking"), raw_games)
    except Exception as exc:
        logger.warning(f"growth: rollover booking validation failed ({exc})")
        booking = None
    return {
        "key": "rollover",
        "label": "Rollover",
        "selected": bool(legs),
        "day_number": today_day.get("day_number") if today_day else None,
        "chain_length": cat.get("chain_length"),
        "target_days": cat.get("target_days"),
        "days_won": won,
        "days_lost": lost,
        "total_odds": round(float(cat.get("total_odds") or 0.0), 2),
        "hit_probability": round(float(cat.get("today_hit_probability") or 0.0), 4),
        "completion_probability": (
            round(float(cat.get("completion_probability")), 4)
            if cat.get("completion_probability") is not None else None
        ),
        "legs": legs,
        "leg_count": len(legs),
        "actionable": bool(legs) and all(leg["actionable"] for leg in legs),
        "booking": booking,
        "booking_verified": bool(booking),
    }


def _dedupe_by_fixture(legs: list[dict]) -> list[dict]:
    """One leg per fixture — the tiers deliberately share picks."""
    seen: set = set()
    out = []
    for leg in legs:
        mid = leg.get("match_id")
        if mid in seen:
            continue
        seen.add(mid)
        out.append(leg)
    return out


def _recent_results(days: int = 7) -> dict:
    """Completed-day product record plus individual-pick accuracy."""
    try:
        from leagues.picks_db import (
            get_history,
            performance_summary,
            product_performance_summary,
        )

        # Public reporting follows WAT, and excludes today's unfinished card.
        wat_now = (
            datetime.now(timezone.utc)
            + timedelta(hours=1)
        )

        yesterday = (
            wat_now
            - timedelta(days=1)
        ).strftime("%Y-%m-%d")

        history = get_history(
            limit_days=days,
            as_of=yesterday,
        )

        settled_yesterday = []

        for slip in history:
            if slip.get("date") != yesterday:
                continue

            if slip.get("status") not in (
                "won",
                "lost",
            ):
                continue

            legs = slip.get("picks") or []

            singles = (
                slip.get("presentation")
                == "singles"
            )

            leg_won = sum(
                1 for pick in legs
                if pick.get("status") == "won"
            )

            leg_lost = sum(
                1 for pick in legs
                if pick.get("status") == "lost"
            )

            settled_yesterday.append({
                "category":
                    slip.get("category"),

                "label":
                    TIER_LABELS.get(
                        slip.get("category"),
                        slip.get("category"),
                    ),

                "status":
                    slip.get("status"),

                "presentation":
                    (
                        "singles"
                        if singles
                        else "accumulator"
                    ),

                "leg_won":
                    leg_won,

                "leg_lost":
                    leg_lost,

                "total_odds":
                    (
                        0.0
                        if singles
                        else round(
                            float(
                                slip.get("total_odds")
                                or 0.0
                            ),
                            2,
                        )
                    ),

                "legs": [
                    {
                        "home_team":
                            pick.get("home_team"),

                        "away_team":
                            pick.get("away_team"),

                        "prediction":
                            pick.get("prediction"),

                        "status":
                            pick.get("status"),
                    }
                    for pick in legs
                ],
            })

        # Pick-level performance remains separate.
        summary = performance_summary(
            limit_days=days,
            as_of=yesterday,
        )

        # One published category/day = one public product outcome.
        product_record = (
            product_performance_summary(
                limit_days=days,
                as_of=yesterday,
            )
        )

        try:
            from leagues.rollover_db import (
                history as rollover_history,
            )

            rollover_settled = [
                row
                for row
                in rollover_history(
                    limit_days=days
                )
                if (
                    row.get("date") == yesterday
                    and row.get("status")
                    in (
                        "won",
                        "lost",
                        "void",
                    )
                )
            ]

        except Exception:
            rollover_settled = []

        pick_rows = [
            item
            for item
            in summary.values()
            if item.get("unit") == "pick"
        ]

        pick_won = sum(
            item.get("won", 0)
            for item in pick_rows
        )

        pick_lost = sum(
            item.get("lost", 0)
            for item in pick_rows
        )

        pick_settled = (
            pick_won + pick_lost
        )

        return {
            "date":
                yesterday,

            "window_end":
                yesterday,

            "window_days":
                days,

            "accounting_version":
                product_record[
                    "accounting_version"
                ],

            "won":
                product_record["won"],

            "lost":
                product_record["lost"],

            "settled":
                product_record["settled"],

            "win_rate":
                product_record["win_rate"],

            "pending_products":
                product_record["pending"],

            "void_products":
                product_record["void"],

            "oldest_pending_date":
                product_record[
                    "oldest_pending_date"
                ],

            "is_final":
                (
                    product_record["pending"]
                    == 0
                ),

            "product_record":
                product_record,

            "singles": {
                "won":
                    pick_won,

                "lost":
                    pick_lost,

                "settled":
                    pick_settled,

                "win_rate":
                    (
                        round(
                            pick_won / pick_settled,
                            4,
                        )
                        if pick_settled
                        else None
                    ),
            },

            "slips_settled":
                settled_yesterday,

            "rollover_settled":
                rollover_settled,

            "by_category":
                summary,
        }

    except Exception as e:
        logger.warning(
            f"growth: results unavailable ({e})"
        )

        return {
            "date": None,
            "window_end": None,
            "window_days": days,
            "won": 0,
            "lost": 0,
            "settled": 0,
            "win_rate": None,
            "pending_products": 0,
            "void_products": 0,
            "is_final": False,
            "singles": {
                "won": 0,
                "lost": 0,
                "settled": 0,
                "win_rate": None,
            },
            "slips_settled": [],
            "rollover_settled": [],
            "by_category": {},
        }


def build() -> Optional[dict]:
    """The day's marketing dataset, or None when nothing is published yet.

    Returns None rather than an empty skeleton so a caller cannot mistake
    "no card today" for "a card with no picks" and post an empty slip.
    """
    from leagues.daily_feed import build_daily_accumulators

    card = build_daily_accumulators()
    if not card or not card.get("accumulators"):
        logger.info("growth: no published card to build a dataset from")
        return None

    accums = card["accumulators"]
    date = card.get("date")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    tiers = {k: _tier_block(k, accums.get(k) or {}) for k in TIER_ORDER}
    rollover = _rollover_block(accums.get("rollover") or {}, today)

    # Every leg on the card, best first, one per fixture.
    all_legs = []
    for key in TIER_ORDER:
        all_legs.extend(tiers[key]["legs"])
    all_legs.sort(key=lambda l: -l["confidence"])
    unique = _dedupe_by_fixture(all_legs)

    # The banker tier exists precisely to be the day's most reliable pick, so
    # it is the honest answer to "best pick" when it was built. Falling back to
    # raw top confidence would otherwise promote an unpriced extrapolation over
    # a pick that cleared the banker price floor.
    best_pick = None
    if tiers["banker"]["selected"]:
        best_pick = tiers["banker"]["legs"][0]
    elif unique:
        best_pick = unique[0]

    upcoming = [l for l in unique if not l["started"]]

    dataset = {
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "best_pick": best_pick,
        "daily_top_5": upcoming[:5],
        "high_confidence": [l for l in upcoming if l["confidence"] >= HIGH_CONFIDENCE],
        "two_odds": tiers["2_odds"],
        "five_odds": tiers["5_odds"],
        "ten_odds": tiers["10_odds"],
        "banker": tiers["banker"],
        "over_1_5": tiers["over_1_5"],
        "rollover": rollover,
        "results": _recent_results(),
        "metadata": {
            "source": "leagues",
            "card_locked": bool(card.get("locked")),
            "published_at_wat": card.get("published_at_wat"),
            "total_fixtures": card.get("total_fixtures"),
            "total_legs": len(unique),
            "upcoming_legs": len(upcoming),
            "tiers_offered": [k for k in TIER_ORDER if tiers[k]["selected"]],
            "leagues": sorted({l["league"] for l in unique if l.get("league")}),
        },
    }
    return dataset
