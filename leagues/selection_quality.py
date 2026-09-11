"""One conservative probability contract for every public selector.

The calibrated model probability is the starting point, not the final risk
input.  Evidence may lower it, statistical uncertainty pulls it toward the
reliability lower bound, and disagreement is charged only when it exceeds
that measured uncertainty.  Positive evidence never inflates the model.
"""
from __future__ import annotations

import math


def _number(value, fallback=None):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else fallback
    except (TypeError, ValueError):
        return fallback


def _clamp(value: float) -> float:
    return max(1e-6, min(.999999, value))


def selection_probability(pick: dict) -> float:
    """Probability used for ranking, accumulation, EV and quality gates.

    Evidence strength is an information weight in [0, 1]. Converting it to
    ``strength / (1 + strength)`` means even the strongest finite sample keeps
    at least half of the distance to its lower reliability bound. Grade-B
    Builder evidence uses the bound itself. This makes uncertainty compound
    honestly in long slips without inventing a second prediction model.
    """
    calibrated = _clamp(_number(pick.get("confidence"), 0.0))
    trust = pick.get("trust") or {}
    adjusted = _number(
        trust.get("evidence_adjusted_probability"),
        _number(pick.get("evidence_adjusted_probability"), calibrated),
    )
    # Negative evidence is allowed to reduce the model; positive evidence is
    # corroboration, not permission to manufacture a higher probability.
    centre = min(calibrated, _clamp(adjusted))
    lower_value = _number(
        trust.get("lower_reliability_bound"),
        _number(pick.get("lower_reliability_bound")),
    )
    if lower_value is None:
        conservative = centre
        uncertainty = 0.0
    else:
        lower = min(centre, _clamp(lower_value))
        uncertainty = centre - lower
        strength = _number(
            trust.get("evidence_strength"),
            _number(pick.get("evidence_strength"), 0.0),
        )
        strength = max(0.0, min(1.0, strength))
        if trust.get("trust_grade") == "B":
            conservative = lower
        else:
            information_weight = strength / (1.0 + strength)
            conservative = lower + information_weight * uncertainty

    # A price/model difference inside the measured reliability interval is
    # already represented by the lower bound. Only unsupported excess is
    # charged, so this adapts to evidence rather than relying on one universal
    # disagreement threshold across every market and league.
    implied = _number(pick.get("market_implied_probability"))
    if implied is not None and centre > implied:
        conservative -= .5 * max(0.0, centre - implied - uncertainty)
    ml = _number(pick.get("ml_confidence"))
    if ml is not None and centre > ml:
        # The shadow model is corroborative and has less held-out skill than
        # the bookmaker benchmark, so its excess-disagreement charge is lower.
        conservative -= .2 * max(0.0, centre - ml - uncertainty)

    return round(_clamp(conservative), 6)


def risk_adjusted_return(pick: dict) -> float:
    """Expected payout factor using the same conservative probability."""
    probability = selection_probability(pick)
    odds = max(1.0, _number(pick.get("odds"), 1.0))
    if pick.get("market") in {"dnb_home", "dnb_away"}:
        draw = _number(
            ((pick.get("_model") or {}).get("probabilities") or {}).get("draw")
        )
        if draw is not None:
            draw = max(0.0, min(1.0, draw))
            return round(probability * (1.0 - draw) * odds + draw, 6)
    return round(probability * odds, 6)


def price_quality(pick: dict) -> dict:
    """Return stable, diagnostic-only price quality for one Builder leg.

    The production admission threshold remains evidence/trust based until the
    decision archive contains enough settled observations to validate an EV
    cutoff.  This still makes contradictory pricing visible immediately.
    """
    probability = selection_probability(pick)
    odds = _number(pick.get("odds"))
    if odds is None or odds <= 1.0 or not pick.get("odds_are_real"):
        return {
            "selection_probability": probability,
            "sportybet_odds": odds,
            "raw_break_even_probability": None,
            "price_edge_probability": None,
            "risk_adjusted_return": risk_adjusted_return(pick),
            "price_quality_reason_codes": ["INSUFFICIENT_PRICE_DATA"],
        }
    rar = risk_adjusted_return(pick)
    if pick.get("market") in {"dnb_home", "dnb_away"}:
        return {
            "selection_probability": probability,
            "sportybet_odds": odds,
            "raw_break_even_probability": None,
            "price_edge_probability": None,
            "risk_adjusted_return": rar,
            "push_aware_expected_return": rar,
            "price_quality_reason_codes": [
                "DNB_PUSH_AWARE",
                "PRICE_POSITIVE" if rar > 1.005 else
                "PRICE_NEGATIVE" if rar < .995 else "PRICE_NEUTRAL",
            ],
        }
    break_even = 1.0 / odds
    edge = probability - break_even
    return {
        "selection_probability": probability,
        "sportybet_odds": odds,
        "raw_break_even_probability": round(break_even, 6),
        "price_edge_probability": round(edge, 6),
        "risk_adjusted_return": rar,
        "price_quality_reason_codes": [
            "PRICE_POSITIVE" if edge > .005 else
            "PRICE_NEGATIVE" if edge < -.005 else "PRICE_NEUTRAL"
        ],
    }


def attach_selection_quality(pick: dict) -> dict:
    pick.update(price_quality(pick))
    return pick
