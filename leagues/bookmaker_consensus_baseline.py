"""Market-consensus-only match forecasts for broad fixture coverage.

Every active, real-priced fixture with complete 1X2 odds receives a baseline
distribution. These ARE NOT independently trained probabilities or an
automated betting tip. Official value, calibration, model and booking-code
quality gates remain completely separate.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

WAT = timezone(timedelta(hours=1))
RESULT_MARKETS = ("home_win", "draw", "away_win")
SIMULATED = (" SRL", "SIMULATED", "VIRTUAL", "EFOOTBALL", "E-FOOTBALL")


def devig_market(prices: dict, markets: tuple[str, ...]):
    """Normalized three- or two-way odds with no inferred edge.

    Do not normalize unrelated alternative markets as one market.
    """
    values = []
    for market in markets:
        try:
            odds = float(prices.get(market) or 0)
        except (ValueError, TypeError):
            return None
        if not math.isfinite(odds) or odds <= 1.0:
            return None
        values.append(odds)
    implied = [1.0 / odds for odds in values]
    total = sum(implied)
    if total <= 0 or not math.isfinite(total):
        return None
    return {
        "probabilities": dict(zip(markets, [round(v / total, 6) for v in implied])),
        "bookmaker_overround": round(total - 1.0, 6),
        "market": markets,
    }


def fixture_consensus(fixture: dict, *, date_wat: str) -> dict:
    """One SportyBet fixture, with explicit abstention instead of fake stats."""
    prices = fixture.get("prices") or {}
    home = str(fixture.get("home_team") or "")
    away = str(fixture.get("away_team") or "")
    competition = str(fixture.get("competition") or "")
    event_id = str(fixture.get("event_id") or "")
    base = {
        "event_id": event_id, "home_team": home, "away_team": away,
        "competition": competition, "date_wat": date_wat,
        "forecast_kind": "BOOKMAKER_CONSENSUS_NOT_INDEPENDENT_MODEL",
        "officially_publishable": False,
        "bookmaker_booking_validated": False,
    }
    # Date scope must be checked BEFORE simulated/youth/identity policy.
    # Otherwise a fixture from tomorrow gets counted as a rejected match
    # today, inflating the daily total (441 against 383 on 2026-10-09).
    try:
        kickoff = datetime.fromtimestamp(
            float(fixture.get("kickoff_ms")) / 1000, tz=timezone.utc,
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return {**base, "status": "INVALID_KICKOFF"}
    if kickoff.astimezone(WAT).date().isoformat() != date_wat:
        return {**base, "status": "WRONG_WAT_DAY"}
    base["kickoff_wat"] = kickoff.astimezone(WAT).isoformat()
    if not event_id or not home or not away or home.casefold() == away.casefold():
        return {**base, "status": "UNVERIFIED_FIXTURE_IDENTITY"}
    fields = " ".join((home, away, competition)).upper()
    if any(word in fields for word in SIMULATED):
        return {**base, "status": "SIMULATED_EXCLUDED"}
    if fixture.get("home_squad") or fixture.get("away_squad"):
        return {**base, "status": "NON_SENIOR_EXCLUDED"}
    result = devig_market(prices, RESULT_MARKETS)
    if result is None:
        return {**base, "status": "INSUFFICIENT_REAL_ODDS"}
    probs = result["probabilities"]
    ranked = sorted(probs.items(), key=lambda item: (-item[1], item[0]))
    # The user gets a top outcome EVEN when the certainty is low.
    # Margin and forecast ambiguity are transparent, not clipped.
    uncertain = ranked[0][1] < .45 or ranked[0][1] - ranked[1][1] < .08
    return {
        **base,
        "status": "MARKET_BASELINE_ONLY",
        "probabilities_1x2": probs,
        "bookmaker_overround_1x2": result["bookmaker_overround"],
        "most_likely_outcome": ranked[0][0],
        "most_likely_probability": ranked[0][1],
        "uncertain": uncertain,
        "suggested_analysis_market": "review_double_chance" if uncertain
                                     else "review_1x2",
        "comparison": {
            "over_1_5": devig_market(prices, ("over_1_5", "under_1_5")),
            "over_2_5": devig_market(prices, ("over_2_5", "under_2_5")),
            "btts": devig_market(prices, ("btts_yes", "btts_no")),
        },
        "limitation": (
            "Bookmaker-implied probabilities are a reference baseline, "
            "not an independent edge, team-history prediction or value bet."
        ),
    }


def full_day_baseline(board: dict, *, date_wat: str) -> dict:
    """One row per exact bookmaker event; never silently shrink to 50 picks."""
    from leagues.sportybet import _board_entries

    entries = []
    seen = set()
    for _, fixture in _board_entries(board):
        forecast = fixture_consensus(fixture, date_wat=date_wat)
        if forecast["status"] in {"WRONG_WAT_DAY", "INVALID_KICKOFF"}:
            continue
        # Deduplicate AFTER date validation: a malformed/out-of-day copy
        # cannot hide the real event within the requested WAT date.
        event_id = str(fixture.get("event_id") or "")
        if event_id and event_id in seen:
            continue
        if event_id:
            seen.add(event_id)
        entries.append(forecast)
    entries.sort(key=lambda x: (
        x.get("kickoff_wat", ""), x.get("competition", ""),
        x.get("event_id", ""),
    ))
    from collections import Counter
    states = Counter(x["status"] for x in entries)
    return {
        "date_wat": date_wat,
        "count": len(entries),
        "statuses": dict(sorted(states.items())),
        "pre_match_forecasts": sum(
            x["status"] == "MARKET_BASELINE_ONLY" for x in entries
        ),
        "full_day_fixtures": entries,
        "official_predictions_changed": False,
        "champion_model_changed": False,
        "source": "Cached SportyBet odds; price-derived baseline only",
    }
