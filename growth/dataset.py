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


def _leg(game: dict, tier: str | None = None) -> dict:
    """One pick, flattened to the fields any channel might render."""
    conf = game.get("confidence") or 0.0
    odds = game.get("odds") or game.get("estimated_odds") or 0.0
    return {
        "match_id": game.get("match_id"),
        "home_team": game.get("home_team"),
        "away_team": game.get("away_team"),
        "home_team_logo": game.get("home_team_logo"),
        "away_team_logo": game.get("away_team_logo"),
        "league": game.get("league"),
        "league_slug": game.get("league_slug"),
        "kickoff": game.get("kickoff") or game.get("date"),
        "prediction": game.get("prediction") or game.get("readable_prediction"),
        "market": game.get("market"),
        "market_group": game.get("prediction_type"),
        "confidence": round(float(conf), 4),
        "odds": round(float(odds), 2),
        "odds_are_real": bool(game.get("odds_are_real")),
        "started": bool(game.get("started")),
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
        "legs": [_leg(g, key) for g in games],
        "leg_count": len(games),
        "all_started": bool(cat.get("all_started")),
    }


def _rollover_block(cat: dict, today: str) -> dict:
    """Today's rollover slot plus the state of the chain around it."""
    chain = cat.get("chain") or []
    today_day = next(
        (d for d in chain
         if (d.get("date") or "") >= today and d.get("status") == "pending"),
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
                "slug": match_slug(p.get("home_team"), p.get("away_team")),
                "tier": "rollover",
            })

    won = sum(1 for d in chain if d.get("status") == "won")
    lost = sum(1 for d in chain if d.get("status") == "lost")
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
        "legs": legs,
        "leg_count": len(legs),
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


def _value_bets(days_ahead: int = 2, limit: int = 5) -> list[dict]:
    """Genuine +EV bets, or an empty list when the shop is unavailable.

    Wrapped because this is the one part of the dataset that reaches a paid
    third-party API with a monthly credit budget. A marketing job must never
    be the reason the budget is spent or the reason a post fails.
    """
    try:
        from leagues.engine import run_pipeline
        from leagues.odds_shop import shop_odds, lookup, SLUG_TO_ODDS_KEY
        from collections import Counter

        _, fixtures = run_pipeline(days_ahead=days_ahead)
        ranked = [s for s, _ in Counter(f["league_slug"] for f in fixtures).most_common()
                  if s in SLUG_TO_ODDS_KEY]
        shopped = shop_odds(ranked[:6])
        if not shopped:
            return []

        rows = []
        for f in fixtures:
            hit = lookup(shopped, f["home"]["name"], f["away"]["name"])
            if not hit:
                continue
            for outcome, o in hit["outcomes"].items():
                cp, bp = o.get("consensus_prob"), o.get("best_price")
                if not cp or not bp:
                    continue
                ev = cp * bp - 1
                if ev < 0.02:
                    continue
                label = {"home_win": f["home"]["name"],
                         "away_win": f["away"]["name"]}.get(outcome, "Draw")
                rows.append({
                    "match_id": f["match_id"],
                    "home_team": f["home"]["name"],
                    "away_team": f["away"]["name"],
                    "league": f["league"],
                    "kickoff": f["commence_time"],
                    "prediction": f"{label} Win" if outcome != "draw" else "Draw",
                    "confidence": round(cp, 4),
                    "odds": bp,
                    "book": o.get("best_book"),
                    "book_count": o.get("books"),
                    "edge_pct": round(ev * 100, 1),
                    "slug": match_slug(f["home"]["name"], f["away"]["name"]),
                    # Exchange prices are quoted before commission, which eats
                    # 2-5% of a thin edge. Channels must be able to say so.
                    "is_exchange": (o.get("best_book") or "").lower() in
                        ("betfair", "smarkets", "matchbook", "betdaq"),
                })
        rows.sort(key=lambda r: -r["edge_pct"])
        return rows[:limit]
    except Exception as e:
        logger.warning(f"growth: value bets unavailable ({e})")
        return []


def _recent_results(days: int = 7) -> dict:
    """Yesterday's settled slips plus the running record."""
    try:
        from leagues.picks_db import get_history, performance_summary

        history = get_history(limit_days=days)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        settled_yesterday = []
        for slip in history:
            if slip.get("date") != yesterday or slip.get("status") not in ("won", "lost"):
                continue
            settled_yesterday.append({
                "category": slip.get("category"),
                "label": TIER_LABELS.get(slip.get("category"), slip.get("category")),
                "status": slip.get("status"),
                "total_odds": round(float(slip.get("total_odds") or 0.0), 2),
                "legs": [
                    {
                        "home_team": p.get("home_team"),
                        "away_team": p.get("away_team"),
                        "prediction": p.get("prediction"),
                        "status": p.get("status"),
                    }
                    for p in slip.get("picks", [])
                ],
            })

        summary = performance_summary(limit_days=days)
        won = sum(c.get("won", 0) for c in summary.values())
        lost = sum(c.get("lost", 0) for c in summary.values())
        settled = won + lost

        return {
            "date": yesterday,
            "slips": settled_yesterday,
            "won": won,
            "lost": lost,
            "settled": settled,
            "win_rate": round(won / settled, 4) if settled else None,
            "window_days": days,
            "by_category": summary,
        }
    except Exception as e:
        logger.warning(f"growth: results unavailable ({e})")
        return {"date": None, "slips": [], "won": 0, "lost": 0,
                "settled": 0, "win_rate": None, "window_days": days,
                "by_category": {}}


def build(include_value_bets: bool = True) -> Optional[dict]:
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
        "value_bets": _value_bets() if include_value_bets else [],
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
