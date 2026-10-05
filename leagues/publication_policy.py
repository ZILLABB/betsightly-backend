"""One fail-closed publication contract for every official BetSightly product.

The model may analyse many fixtures and markets.  Publication is a separate
decision: an official recommendation must be exact-bookable, carry a real
SportyBet price, have trusted evidence, avoid volatile friendlies and meet
the same conservative model-return floor everywhere.  A product is withheld
when the contract cannot be satisfied; targets are never bought by weakening
the standard.
"""
from __future__ import annotations

from collections import Counter
from math import prod

from leagues.selection_quality import risk_adjusted_return, selection_probability

POLICY_VERSION = "official_publication_v1"
MIN_LEG_MODEL_RETURN = 1.0
MIN_SLIP_MODEL_RETURN = 1.0
MIN_OFFICIAL_PROBABILITY = 0.65
BANKER_MIN_PROBABILITY = 0.72

BLOCKED_COMPETITION_TYPES = {"INTERNATIONAL_FRIENDLY"}
BLOCKED_LEAGUE_SLUGS = {"fifa.friendly", "club.friendly"}

OFFICIAL_PRODUCTS = (
    "rollover", "banker", "2_odds", "5_odds", "10_odds", "over_1_5"
)


def _fixture(pick: dict) -> dict:
    return pick.get("_fixture") or pick


def _competition_type(pick: dict) -> str:
    fixture = _fixture(pick)
    return str(
        fixture.get("competition_type")
        or pick.get("competition_type")
        or ""
    ).upper()


def _league_slug(pick: dict) -> str:
    fixture = _fixture(pick)
    return str(
        fixture.get("league_slug")
        or pick.get("league_slug")
        or ""
    ).casefold()


def _is_friendly(pick: dict) -> bool:
    return (
        _competition_type(pick) in BLOCKED_COMPETITION_TYPES
        or _league_slug(pick) in BLOCKED_LEAGUE_SLUGS
    )


def evaluate_leg(pick: dict, product: str) -> dict:
    """Return the single authoritative publication decision for one leg."""
    reasons: list[str] = []
    probability = selection_probability(pick)
    try:
        stored_return = pick.get("risk_adjusted_return")
        model_return = (
            float(stored_return)
            if stored_return is not None
            else risk_adjusted_return(pick)
        )
    except (TypeError, ValueError):
        model_return = risk_adjusted_return(pick)
    trust = pick.get("trust") or {}
    trust_grade = trust.get("trust_grade") or pick.get("trust_grade")
    trust_state = pick.get("market_trust_state")

    if not pick.get("market_floor_eligible", True):
        reasons.append("BELOW_MARKET_PUBLICATION_FLOOR")
    if not pick.get("safe_tier_eligible", False):
        reasons.append("INSUFFICIENT_SETTLED_EVIDENCE")
    if trust.get("accepted") is False:
        reasons.append("LEG_TRUST_REJECTED")
    if trust_grade and trust_grade not in {"A", "B"}:
        reasons.append("LOW_TRUST_GRADE")
    if trust_state and trust_state != "TRUSTED":
        reasons.append("MARKET_NOT_TRUSTED")
    if not pick.get("bookable", False):
        reasons.append("NOT_EXACTLY_BOOKABLE")
    if not pick.get("odds_are_real", False):
        reasons.append("ESTIMATED_PRICE")
    if _is_friendly(pick):
        reasons.append("FRIENDLY_COMPETITION")

    minimum_probability = (
        BANKER_MIN_PROBABILITY if product == "banker"
        else MIN_OFFICIAL_PROBABILITY
    )
    if probability < minimum_probability:
        reasons.append("BELOW_PRODUCT_PROBABILITY_FLOOR")
    if model_return < MIN_LEG_MODEL_RETURN:
        reasons.append("NEGATIVE_MODEL_VALUE")

    return {
        "allowed": not reasons,
        "policy_version": POLICY_VERSION,
        "product": product,
        "selection_probability": round(probability, 6),
        "risk_adjusted_return": round(model_return, 6),
        "minimum_probability": minimum_probability,
        "minimum_leg_model_return": MIN_LEG_MODEL_RETURN,
        "reasons": reasons,
    }


def filter_official_candidates(picks: list[dict], product: str) -> tuple[list[dict], list[dict]]:
    """Keep only legs allowed by the publication contract, with diagnostics."""
    allowed: list[dict] = []
    rejected: list[dict] = []
    for pick in picks:
        decision = evaluate_leg(pick, product)
        if decision["allowed"]:
            allowed.append(pick)
            continue
        rejected.append({
            "match_id": pick.get("match_id"),
            "market": pick.get("market"),
            "prediction": pick.get("prediction"),
            **decision,
        })
    return allowed, rejected


def rejection_summary(rejections: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rejections:
        counts.update(row.get("reasons") or [])
    return dict(sorted(counts.items()))


def evaluate_slip(games: list[dict], product: str) -> dict:
    """Validate the final displayed slip, not only the candidate pool."""
    legs = [evaluate_leg(game, product) for game in games]
    reasons = sorted({reason for leg in legs for reason in leg["reasons"]})
    fixture_ids = [str(game.get("match_id") or "") for game in games]
    duplicate_fixtures = sorted({fid for fid in fixture_ids if fid and fixture_ids.count(fid) > 1})
    if duplicate_fixtures:
        reasons.append("DUPLICATE_FIXTURE_IN_SLIP")
    model_return = prod(leg["risk_adjusted_return"] for leg in legs) if legs else 0.0
    if games and model_return < MIN_SLIP_MODEL_RETURN:
        reasons.append("NEGATIVE_SLIP_MODEL_VALUE")
    return {
        "allowed": bool(games) and not reasons,
        "policy_version": POLICY_VERSION,
        "product": product,
        "leg_count": len(games),
        "model_estimated_return": round(model_return, 6),
        "minimum_slip_model_return": MIN_SLIP_MODEL_RETURN,
        "duplicate_fixture_ids": duplicate_fixtures,
        "reasons": sorted(set(reasons)),
        "legs": legs,
    }


def _reason_copy(reasons: list[str]) -> str:
    reasons = set(reasons)
    if "FRIENDLY_COMPETITION" in reasons:
        return "No qualifying slip: friendlies are excluded from official BetSightly products."
    if "NEGATIVE_MODEL_VALUE" in reasons or "NEGATIVE_SLIP_MODEL_VALUE" in reasons:
        return "No qualifying slip: current SportyBet prices do not meet BetSightly's model-value standard."
    if "NOT_EXACTLY_BOOKABLE" in reasons or "ESTIMATED_PRICE" in reasons:
        return "No qualifying slip: every official selection must have a verified real SportyBet price."
    return "No qualifying slip met BetSightly's official publication standard today."


def _withhold(category: dict, decision: dict) -> None:
    category.pop("booking", None)
    category.update(
        selected=False,
        games=[],
        total_odds=0,
        hit_probability=0,
        result_status="PUBLICATION_POLICY_BLOCKED",
        reason=_reason_copy(decision.get("reasons") or []),
        model_estimated_return=round(float(decision.get("model_estimated_return") or 0), 4),
        publication_policy=decision,
    )


def enforce_card_policy(accumulators: dict) -> dict:
    """Fail closed on the final card, including booking-time replacements."""
    report = {
        "version": POLICY_VERSION,
        "minimum_leg_model_return": MIN_LEG_MODEL_RETURN,
        "minimum_slip_model_return": MIN_SLIP_MODEL_RETURN,
        "products": {},
    }
    for product in OFFICIAL_PRODUCTS:
        category = accumulators.get(product)
        if not isinstance(category, dict):
            continue
        if not category.get("selected") or not category.get("games"):
            report["products"][product] = {
                "allowed": False,
                "status": "NOT_SELECTED",
                "reasons": [],
            }
            continue

        games = list(category.get("games") or [])
        if category.get("presentation") == "singles":
            kept = []
            rejected = []
            for game in games:
                decision = evaluate_leg(game, product)
                if decision["allowed"]:
                    kept.append(game)
                else:
                    rejected.append({"match_id": game.get("match_id"), **decision})
            if not kept:
                decision = {
                    "allowed": False,
                    "policy_version": POLICY_VERSION,
                    "product": product,
                    "model_estimated_return": 0.0,
                    "reasons": sorted({r for row in rejected for r in row["reasons"]}),
                    "rejected": rejected,
                }
                _withhold(category, decision)
                report["products"][product] = decision
                continue
            category["games"] = kept
            category["total_odds"] = round(prod(float(g.get("odds") or 1) for g in kept), 2)
            category["hit_probability"] = round(
                sum(selection_probability(g) for g in kept) / len(kept), 3
            )
            category["model_estimated_return"] = round(
                sum(risk_adjusted_return(g) for g in kept) / len(kept), 4
            )
            decision = {
                "allowed": True,
                "policy_version": POLICY_VERSION,
                "product": product,
                "kept": len(kept),
                "rejected": rejected,
                "reasons": [],
            }
            category["publication_policy"] = decision
            report["products"][product] = decision
            continue

        decision = evaluate_slip(games, product)
        if not decision["allowed"]:
            _withhold(category, decision)
        else:
            category["model_estimated_return"] = round(decision["model_estimated_return"], 4)
            category["publication_policy"] = decision
        report["products"][product] = decision

    accumulators["_publication_policy"] = report
    return report
