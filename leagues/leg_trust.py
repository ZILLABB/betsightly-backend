"""Evidence gate for legs used by the on-demand Slip Builder."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Iterable

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
    ml = pick.get("ml_confidence")
    model_delta = abs(confidence - float(ml)) if ml is not None else None
    fixture = pick.get("_fixture") or {}
    complete = bool(pick.get("match_id") and pick.get("market") and fixture.get("commence_time"))
    reasons = []
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
    score -= 40 if not bookable else 0
    score -= 25 if not complete else 0
    score = max(0, min(100, int(score)))
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"
    return LegTrust(raw, confidence, pick.get("calibration_group"), sample, cal_error,
                    implied, market_delta, model_delta,
                    "current_board" if availability.get("board_snapshot_id") else "unknown",
                    bookable, "complete" if complete else "incomplete", score, grade,
                    not reasons and grade in ("A", "B"), tuple(reasons), fused["state"],
                    fused["historical_reliability_estimate"],fused["live_reliability_estimate"],
                    fused["evidence_adjusted_probability"],fused["lower_reliability_bound"],
                    fused["hierarchy_level"]).to_dict()
