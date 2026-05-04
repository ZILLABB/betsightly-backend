"""
Risk Scorer — rates how safe a prediction is for accumulator inclusion.

Risk score [0, 1]:  0 = safe,  1 = risky

Factors (weighted):
    1. Calibrated confidence     (0.40) — higher conf = safer
    2. Model disagreement        (0.30) — consensus = safer
    3. Estimated odds            (0.15) — very high odds = riskier
    4. ELO gap between teams     (0.15) — big gap = safer
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SAFE_CONFIDENCE_THRESHOLD = 0.72
SAFE_RISK_THRESHOLD = 0.40


class RiskScorer:
    def __init__(self, confidence_weight=0.40, agreement_weight=0.30, odds_weight=0.15, elo_weight=0.15):
        total = confidence_weight + agreement_weight + odds_weight + elo_weight
        self.w_conf = confidence_weight / total
        self.w_agree = agreement_weight / total
        self.w_odds = odds_weight / total
        self.w_elo = elo_weight / total

    def score(self, prediction):
        risk = (
            self.w_conf  * self._conf_risk(prediction.get("confidence", 0.5))
            + self.w_agree * self._agree_risk(prediction.get("model_disagreement", 0.5))
            + self.w_odds  * self._odds_risk(prediction.get("estimated_odds", 2.0))
            + self.w_elo   * self._elo_risk(prediction.get("elo_gap", 0.0))
        )
        return round(float(min(max(risk, 0.0), 1.0)), 4)

    def is_safe(self, prediction, risk_threshold=SAFE_RISK_THRESHOLD, confidence_threshold=SAFE_CONFIDENCE_THRESHOLD):
        if prediction.get("confidence", 0.0) < confidence_threshold: return False
        return self.score(prediction) <= risk_threshold

    def score_and_annotate(self, prediction):
        risk = self.score(prediction)
        safe = risk <= SAFE_RISK_THRESHOLD and prediction.get("confidence", 0) >= SAFE_CONFIDENCE_THRESHOLD
        return {**prediction, "risk_score": risk, "is_safe": safe, "risk_level": self._label(risk)}

    def filter_safe(self, predictions, risk_threshold=SAFE_RISK_THRESHOLD, confidence_threshold=SAFE_CONFIDENCE_THRESHOLD):
        scored = [self.score_and_annotate(p) for p in predictions]
        safe = [p for p in scored if p["risk_score"] <= risk_threshold and p.get("confidence", 0) >= confidence_threshold]
        return sorted(safe, key=lambda x: x["risk_score"])

    def _conf_risk(self, conf):
        return float(1.0 - min(max(conf, 0.0), 1.0))

    def _agree_risk(self, disagreement):
        return float(min(max(disagreement, 0.0), 1.0))

    def _odds_risk(self, odds):
        if odds <= 0: return 1.0
        if odds < 1.05: return 0.1
        elif odds <= 1.60: return (odds - 1.05) / 0.55 * 0.2
        elif odds <= 2.0: return 0.2 + (odds - 1.60) / 0.40 * 0.4
        elif odds <= 3.0: return 0.6 + (odds - 2.0) * 0.3
        else: return min(0.9 + (odds - 3.0) * 0.03, 1.0)

    def _elo_risk(self, elo_gap):
        return float(max(0.0, 0.8 - abs(elo_gap) / 500.0))

    @staticmethod
    def _label(risk):
        if risk <= 0.20: return "VERY_LOW"
        elif risk <= 0.35: return "LOW"
        elif risk <= 0.50: return "MEDIUM"
        elif risk <= 0.70: return "HIGH"
        else: return "VERY_HIGH"
