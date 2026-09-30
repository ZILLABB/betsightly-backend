"""Evidence gate for legs used by the on-demand Slip Builder."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Iterable

# ``selection_quality.price_quality_reason_codes`` mixes descriptive labels
# with genuinely adverse price/evidence signals. PRICE_POSITIVE,
# PRICE_NEUTRAL, PRICE_NEGATIVE and DNB_PUSH_AWARE are diagnostics used by
# ranking/UI. They must not become trust rejections merely because a pick was
# quality-annotated before evaluate_leg_trust() runs.
#
# These codes, however, describe real evidence problems and remain blocking.
TRUST_BLOCKING_PRICE_REASON_CODES = {
    "SPARSE_COMPETITION_EVIDENCE",
    "EXTREME_PRICE_MODEL_DISAGREEMENT",
    "UNSUPPORTED_PRICE_EDGE",
}

def reprice_for_live_sportybet(pick: dict) -> dict:
    """Recompute selection economics from the exact currently bookable price.

    The model may be produced before SportyBet enrichment.  Once the exact
    selection price exists it is the only price the Builder can offer, so it
    must become the trust/return input before ranking or optimization.
    """
    availability = pick.get("sportybet_availability") or {}
    price = availability.get("sportybet_odds")
    if not (pick.get("bookable") and availability.get("status", "BOOKABLE") == "BOOKABLE"):
        return pick
    try:
        price = float(price)
    except (TypeError, ValueError):
        return pick
    if price <= 1:
        return pick
    confidence = float(pick.get("confidence") or 0)
    implied = 1.0 / price
    reasons = list(pick.get("price_quality_reason_codes") or [])
    sparse = (int(pick.get("competition_historical_sample") or 0) == 0
              and pick.get("base_rate_source") == "global_default")
    gap = confidence - implied
    if sparse:
        reasons.append("SPARSE_COMPETITION_EVIDENCE")
    if gap > .25:
        reasons.append("EXTREME_PRICE_MODEL_DISAGREEMENT")
    if sparse and gap > .15:
        reasons.append("UNSUPPORTED_PRICE_EDGE")
    pick.update({
        "sportybet_odds": round(price, 3), "odds": round(price, 3),
        "odds_are_real": True, "odds_provider": "SportyBet",
        "raw_break_even_probability": round(implied, 6),
        "market_implied_probability": round(implied, 6),
        "model_price_disagreement": round(abs(gap), 6),
        "expected_value": round(confidence * price - 1.0, 6),
        "risk_adjusted_return": round(max(0.0, confidence - abs(gap) * (.75 if sparse else .35)) * price - 1.0, 6),
        "price_quality_reason_codes": list(dict.fromkeys(reasons)),
    })
    return pick

def no_vig_probability(selected_odds: float, all_outcome_odds: Iterable[float]) -> float | None:
    """Normalize implied prices when the complete market is available."""
    try:
        selected = float(selected_odds)
        prices = [float(value) for value in all_outcome_odds]
    except (TypeError, ValueError):
        return None
    if selected <= 1 or len(prices) < 2 or any(value <= 1 for value in prices):
        return None
    overround = sum(1.0 / value for value in prices)
    return (1.0 / selected) / overround if overround > 0 else None

@dataclass(frozen=True)
class LegTrust:
    raw_confidence: float | None
    calibrated_confidence: float
    calibration_group: str | None
    calibration_sample_size: int
    historical_calibration_error: float | None
    market_implied_probability: float | None
    model_market_disagreement: float | None
    internal_model_agreement: float | None
    odds_freshness: str
    sportybet_bookability: bool
    data_completeness: str
    trust_score: int
    trust_grade: str
    accepted: bool
    rejection_reasons: tuple[str, ...]
    evidence_state: str
    evidence_strength: float
    historical_reliability_estimate: float | None
    live_reliability_estimate: float | None
    evidence_adjusted_probability: float
    lower_reliability_bound: float
    evidence_level: str
    def to_dict(self) -> dict:
        value = asdict(self)
        value["rejection_reasons"] = list(self.rejection_reasons)
        return value

def evaluate_leg_trust(pick: dict, *, minimum_samples: int | None = None) -> dict:
    """Conservatively decide trust from facts already produced by the pipeline."""
    from leagues.picks import MIN_EVIDENCE_LEGS
    minimum_samples = MIN_EVIDENCE_LEGS if minimum_samples is None else minimum_samples
    confidence = float(pick.get("confidence") or 0)
    raw = pick.get("raw_confidence")
    raw = float(raw) if raw is not None else None
    sample = int(pick.get("calibration_sample") or 0)
    from leagues.evidence_fusion import fused_market_evidence
    fused = fused_market_evidence(pick.get("market", ""), confidence,
                                  (pick.get("_fixture") or {}).get("league"),
                                  pick.get("calibration_evidence"))
    availability = pick.get("sportybet_availability") or {}
    bookable = bool(pick.get("bookable") and availability.get("sportybet_available", True)
                    and availability.get("status", "BOOKABLE") == "BOOKABLE")
    implied = pick.get("market_implied_probability")
    implied = float(implied) if implied is not None else None
    market_delta = abs(confidence - implied) if implied is not None else None
    # A neutral/default-feature ML vector is an extrapolation, not an
    # independent football signal.  Keep it in diagnostics, but never allow it
    # to increase or veto trust as though it were a genuine second opinion.
    ml = pick.get("ml_confidence")
    ml_provenance = (pick.get("ml_provenance") or "UNAVAILABLE").upper()
    if ml_provenance in ("NEUTRAL_FALLBACK", "UNAVAILABLE"):
        ml = None
    model_delta = abs(confidence - float(ml)) if ml is not None else None
    fixture = pick.get("_fixture") or {}
    complete = bool(pick.get("match_id") and pick.get("market") and fixture.get("commence_time"))
    reasons = []
    reasons.extend(
        code
        for code in (pick.get("price_quality_reason_codes") or [])
        if code in TRUST_BLOCKING_PRICE_REASON_CODES
    )
    if not bookable: reasons.append("sportybet_selection_not_exactly_bookable")
    if (not pick.get("safe_tier_eligible", sample >= minimum_samples)
            and fused["state"] not in ("SUPPORTED", "PROVEN")):
        reasons.append("insufficient_market_evidence")
    if fused["state"] in ("SHADOW", "REJECTED"):
        reasons.append("market_evidence_restricted")
    uncertainty_gap = max(0.0, confidence - fused["lower_reliability_bound"])
    if fused["lower_reliability_bound"] < .50 or uncertainty_gap > .30:
        reasons.append("weak_reliability_lower_bound")
    if confidence <= 0 or confidence >= 1: reasons.append("invalid_calibrated_probability")
    if model_delta is not None and model_delta > .15: reasons.append("large_internal_model_disagreement")
    if market_delta is not None and market_delta > .25: reasons.append("large_model_market_disagreement")
    sparse_context = (int(pick.get("competition_historical_sample") or 0) == 0
                      and pick.get("base_rate_source") == "global_default")
    if sparse_context: reasons.append("sparse_competition_evidence")
    if not complete: reasons.append("incomplete_fixture_data")
    cell = pick.get("calibration_evidence") or {}
    cal_error = (abs(float(cell["promised"]) - float(cell["actual"]))
                 if cell.get("promised") is not None and cell.get("actual") is not None else None)
    score = 100
    score -= (0 if fused["state"] in ("SUPPORTED","PROVEN") else 30) if sample < minimum_samples else (8 if sample < minimum_samples * 2 else 0)
    score -= 6 if implied is None else min(20, round((market_delta or 0) * 50))
    score -= 4 if model_delta is None else (15 if model_delta > .10 else 0)
    score -= min(20, round(cal_error * 100)) if cal_error is not None else 0
    score -= min(20, round(uncertainty_gap * 50))
    if sparse_context: score -= 28
    if "EXTREME_PRICE_MODEL_DISAGREEMENT" in reasons: score -= 25
    context = fixture.get("competition") or {}
    # Two-leg/knockout incentives and inferred neutral venues are recorded as
    # uncertainty, not as invented probability adjustments. Real bookmaker
    # agreement can still support the leg; thin unpriced evidence cannot look A-grade.
    if context.get("second_leg"):
        score -= 6
    elif context.get("knockout"):
        score -= 3
    if context.get("neutral_venue") and implied is None:
        score -= 5
    score -= 40 if not bookable else 0
    score -= 25 if not complete else 0
    score = max(0, min(100, int(score)))
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"
    # The final admission probability is conservative with respect to the
    # exact live price.  A claimed edge that is both sparse and far from the
    # book cannot retain the pre-booking reliability estimate.
    price_penalty = 0.0
    if market_delta is not None:
        price_penalty = max(0.0, market_delta - .08) * (
            1.5 if sparse_context else .75
        )
    conservative = min(
        float(fused["evidence_adjusted_probability"]),
        max(0.0, confidence - price_penalty),
    )
    lower_bound = min(float(fused["lower_reliability_bound"]), conservative)
    return LegTrust(raw, confidence, pick.get("calibration_group"), sample, cal_error,
                    implied, market_delta, model_delta,
                    "current_board" if availability.get("board_snapshot_id") else "unknown",
                    bookable, "complete" if complete else "incomplete", score, grade,
                    not reasons and grade in ("A", "B"), tuple(reasons), fused["state"],
                    float(fused.get("evidence_strength") or 0),
                    fused["historical_reliability_estimate"],fused["live_reliability_estimate"],
                    conservative, lower_bound,
                    fused["hierarchy_level"]).to_dict()
