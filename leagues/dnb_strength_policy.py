"""Fail-closed Draw No Bet side checks for the official selection pipeline.

Do not conflate a team being listed first with it being stronger. Use
forecasted unconditional 1X2 win probabilities and the exact bookmaker 1X2
prices attached to the same fixture. Disagreement means no DNB pick, not
a switch to the other side or a fabricated bookmaker edge.
"""
from __future__ import annotations

import math


def _finite_positive(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def dnb_strength_reasons(pick: dict) -> list[str]:
    market = pick.get("market_key") or pick.get("market")
    if market not in ("dnb_home", "dnb_away"):
        return []

    model = ((pick.get("_model") or {}).get("probabilities") or {})
    fixture = pick.get("_fixture") or {}
    prices = fixture.get("odds") or {}

    home_prob = _finite_positive(model.get("home_win"))
    away_prob = _finite_positive(model.get("away_win"))
    if home_prob is None:
        home_prob = _finite_positive(pick.get("model_home_win_probability"))
    if away_prob is None:
        away_prob = _finite_positive(pick.get("model_away_win_probability"))

    home_price = _finite_positive(prices.get("home_win"))
    away_price = _finite_positive(prices.get("away_win"))
    if home_price is None:
        home_price = _finite_positive(pick.get("bookmaker_home_win_odds"))
    if away_price is None:
        away_price = _finite_positive(pick.get("bookmaker_away_win_odds"))

    reasons = []
    if home_prob is None or away_prob is None:
        reasons.append("DNB_MODEL_STRENGTH_UNVERIFIED")
    elif (market == "dnb_home" and home_prob <= away_prob) or (
        market == "dnb_away" and away_prob <= home_prob
    ):
        reasons.append("DNB_NOT_MODEL_FAVOURITE")

    if home_price is None or away_price is None or min(home_price, away_price) <= 1:
        reasons.append("DNB_BOOKMAKER_STRENGTH_UNVERIFIED")
    elif (market == "dnb_home" and home_price >= away_price) or (
        market == "dnb_away" and away_price >= home_price
    ):
        reasons.append("DNB_NOT_BOOKMAKER_FAVOURITE")

    return reasons
