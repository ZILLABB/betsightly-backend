"""
Accumulator Builder — Best Confidence, Safe Games Only.

Only includes predictions that are genuinely confident:
  - Match result (3-class): >= 45% confidence + ALL models agree
  - Over/Under (binary):    >= 60% confidence + XGB & LGBM agree
  - BTTS (binary):          >= 60% confidence + XGB & LGBM agree

Then combines many low-odds safe games until combined odds hits target.
Never picks a weak or risky game just to fill a target.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from services.risk_scorer import RiskScorer, SAFE_RISK_THRESHOLD
except ImportError:
    from risk_scorer import RiskScorer, SAFE_RISK_THRESHOLD

# Confidence floors per prediction type
MIN_CONFIDENCE_MATCH_RESULT = 0.45   # 3-class (random = 33%)
MIN_CONFIDENCE_BINARY = 0.60         # binary  (random = 50%)


class AccumulatorBuilder:

    TARGET_ODDS = {
        "2_odds":   {"min": 1.80, "max": 2.50},
        "5_odds":   {"min": 4.50, "max": 6.00},
        "10_odds":  {"min": 8.00, "max": 15.00},
        "rollover": {"min": 2.00, "max": 3.00},
    }
    MAX_GAMES = 15

    def __init__(self, risk_threshold: float = SAFE_RISK_THRESHOLD):
        self.risk_scorer = RiskScorer()
        self.risk_threshold = risk_threshold

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def build_accumulators(self, predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            selections = self._extract_best_selections(predictions)
            safe_pool = [s for s in selections if s.get("is_safe", False)]

            logger.info(
                "Accumulator: %d fixtures -> %d quality picks -> %d safe",
                len(predictions), len(selections), len(safe_pool),
            )

            if not safe_pool:
                return {
                    "status": "no_safe_selections",
                    "total_games_analyzed": len(predictions),
                    "quality_selections": len(selections),
                    "safe_selections": 0,
                    "accumulators": self._empty_accumulators("No confident + safe selections found"),
                    "summary": self._summary({}),
                }

            accumulators = {
                cat: self._build_category(safe_pool, cat, target)
                for cat, target in self.TARGET_ODDS.items()
            }

            return {
                "status": "success",
                "total_games_analyzed": len(predictions),
                "quality_selections": len(selections),
                "safe_selections": len(safe_pool),
                "accumulators": accumulators,
                "summary": self._summary(accumulators),
            }
        except Exception as e:
            logger.error("AccumulatorBuilder error: %s", e, exc_info=True)
            return {
                "status": "error", "message": str(e),
                "accumulators": self._empty_accumulators("Internal error"),
            }

    # ------------------------------------------------------------------
    # Selection extraction — quality-gated per prediction type
    # ------------------------------------------------------------------

    def _extract_best_selections(self, predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """For each fixture, find the best genuinely confident prediction.

        Quality gates:
          - match_result: conf >= 45%, ALL match-result models agree
          - over_under:   conf >= 60%, XGB and LGBM agree
          - btts:         conf >= 60%, XGB and LGBM agree
        """
        selections: List[Dict[str, Any]] = []

        for pred in predictions:
            fi = pred.get("fixture_info", {})
            ml = pred.get("ml_predictions", {})
            fixture_disagreement = pred.get("model_disagreement", 0.5)
            fixture_elo_gap = pred.get("elo_gap", 0.0)

            candidates = []

            # --- Evaluate match result predictions ---
            mr_candidate = self._evaluate_match_result(ml, fi, fixture_disagreement, fixture_elo_gap)
            if mr_candidate:
                candidates.append(mr_candidate)

            # --- Evaluate over/under predictions ---
            ou_candidate = self._evaluate_binary_pair(
                ml, fi, fixture_disagreement, fixture_elo_gap,
                key_pattern="over_2_5",
                pos_label="over_2_5", neg_label="under_2_5",
                pos_readable="Over 2.5 goals", neg_readable="Under 2.5 goals",
            )
            if ou_candidate:
                candidates.append(ou_candidate)

            # --- Evaluate BTTS predictions ---
            btts_candidate = self._evaluate_binary_pair(
                ml, fi, fixture_disagreement, fixture_elo_gap,
                key_pattern="btts",
                pos_label="yes", neg_label="no",
                pos_readable="BTTS Yes", neg_readable="BTTS No",
            )
            if btts_candidate:
                candidates.append(btts_candidate)

            if not candidates:
                continue

            # Pick the candidate with the highest confidence
            best = max(candidates, key=lambda c: c["confidence"])
            scored = self.risk_scorer.score_and_annotate(best)
            selections.append(scored)

        return sorted(selections, key=lambda x: x.get("risk_score", 1.0))

    def _evaluate_match_result(
        self, ml: dict, fi: dict, disagreement: float, elo_gap: float
    ) -> Optional[Dict[str, Any]]:
        """Check if match-result models produce a confident, unanimous pick."""
        mr_models = {}
        for key, pd in ml.items():
            if "match_result" in key or key in ("elo_rating", "dixon_coles"):
                prediction = pd.get("prediction", "")
                if prediction in ("home_win", "draw", "away_win"):
                    mr_models[key] = {
                        "prediction": prediction,
                        "confidence": pd.get("confidence", 0),
                    }

        if len(mr_models) < 2:
            return None

        # Check unanimity — ALL match-result models must agree
        predictions_set = set(m["prediction"] for m in mr_models.values())
        if len(predictions_set) != 1:
            return None  # Models disagree — skip

        agreed_prediction = predictions_set.pop()

        # Use the highest confidence among agreeing models
        best_conf = max(m["confidence"] for m in mr_models.values())

        if best_conf < MIN_CONFIDENCE_MATCH_RESULT:
            return None  # Not confident enough

        # Average confidence across all agreeing models
        avg_conf = sum(m["confidence"] for m in mr_models.values()) / len(mr_models)

        return self._make_candidate(
            fi, agreed_prediction, self._fmt_readable(agreed_prediction),
            best_conf, avg_conf, 0.0, elo_gap, "match_result",
            models_agreed=len(mr_models),
        )

    def _evaluate_binary_pair(
        self, ml: dict, fi: dict, disagreement: float, elo_gap: float,
        key_pattern: str, pos_label: str, neg_label: str,
        pos_readable: str, neg_readable: str,
    ) -> Optional[Dict[str, Any]]:
        """Check if XGB and LGBM agree on a binary prediction with high confidence."""
        xgb_pred = None
        lgbm_pred = None

        for key, pd in ml.items():
            if key_pattern not in key:
                continue
            prediction = pd.get("prediction", "")
            conf = pd.get("confidence", 0)
            if "xgb" in key:
                xgb_pred = {"prediction": prediction, "confidence": conf}
            elif "lgbm" in key:
                lgbm_pred = {"prediction": prediction, "confidence": conf}

        if xgb_pred is None or lgbm_pred is None:
            return None

        # Both must agree
        if xgb_pred["prediction"] != lgbm_pred["prediction"]:
            return None

        agreed = xgb_pred["prediction"]
        best_conf = max(xgb_pred["confidence"], lgbm_pred["confidence"])
        avg_conf = (xgb_pred["confidence"] + lgbm_pred["confidence"]) / 2

        if best_conf < MIN_CONFIDENCE_BINARY:
            return None  # Not confident enough

        readable = pos_readable if agreed == pos_label else neg_readable

        return self._make_candidate(
            fi, agreed, readable, best_conf, avg_conf, 0.0, elo_gap,
            key_pattern, models_agreed=2,
        )

    def _make_candidate(
        self, fi: dict, prediction: str, readable: str,
        best_conf: float, avg_conf: float,
        disagreement: float, elo_gap: float, pred_type: str,
        models_agreed: int = 0,
    ) -> Dict[str, Any]:
        return {
            "fixture_id": fi.get("fixture_id"),
            "home_team": fi.get("home_team", ""),
            "away_team": fi.get("away_team", ""),
            "league": fi.get("league", ""),
            "date": fi.get("date", ""),
            "prediction_type": pred_type,
            "prediction_value": prediction,
            "readable_prediction": readable,
            "confidence": best_conf,
            "average_confidence": avg_conf,
            "estimated_odds": self._conf_to_odds(best_conf, pred_type),
            "model_disagreement": disagreement,
            "elo_gap": elo_gap,
            "models_agreed": models_agreed,
        }

    # ------------------------------------------------------------------
    # Greedy safe accumulator building
    # ------------------------------------------------------------------

    def _build_category(self, safe_pool, category, target):
        min_odds, max_odds = target["min"], target["max"]
        if not safe_pool:
            return self._no(category, min_odds, max_odds, "No safe games available")

        chosen = []
        running_odds = 1.0
        used = set()

        # Pass 1: strict — stay within max_odds
        for game in safe_pool:
            if len(chosen) >= self.MAX_GAMES:
                break
            fid = game.get("fixture_id")
            if fid in used:
                continue
            projected = running_odds * game.get("estimated_odds", 1.5)
            if projected <= max_odds:
                chosen.append(game)
                running_odds = projected
                if fid is not None:
                    used.add(fid)
                if running_odds >= min_odds:
                    break

        # Pass 2: allow up to 15% overshoot if needed
        if running_odds < min_odds:
            for game in safe_pool:
                if len(chosen) >= self.MAX_GAMES:
                    break
                fid = game.get("fixture_id")
                if fid in used:
                    continue
                projected = running_odds * game.get("estimated_odds", 1.5)
                if projected <= max_odds * 1.15:
                    chosen.append(game)
                    running_odds = projected
                    if fid is not None:
                        used.add(fid)
                    if running_odds >= min_odds:
                        break

        if not chosen or running_odds < min_odds * 0.80:
            return self._no(
                category, min_odds, max_odds,
                "Not enough confident predictions to reach %.2f odds (best: %.2f)" % (min_odds, running_odds),
            )

        avg_conf = sum(g["confidence"] for g in chosen) / len(chosen)
        avg_risk = sum(g.get("risk_score", 0) for g in chosen) / len(chosen)

        return {
            "selected": True,
            "category": category,
            "games": [self._fmt_game(g) for g in chosen],
            "total_odds": round(running_odds, 3),
            "target_range": "%.2f-%.2f" % (min_odds, max_odds),
            "num_games": len(chosen),
            "average_confidence": round(avg_conf, 4),
            "average_risk_score": round(avg_risk, 4),
            "risk_level": self._risk_label(avg_risk),
            "recommendation": "INCLUDE",
            "strategy": "best_confidence_safe_greedy",
        }

    # ------------------------------------------------------------------
    # Confidence → Odds mapping
    # ------------------------------------------------------------------

    def _conf_to_odds(self, confidence: float, pred_type: str = "") -> float:
        """Map confidence to estimated decimal odds.

        Separate curves for 3-class (match result) vs binary predictions.
        """
        c = confidence

        if pred_type == "match_result":
            # 3-class: 45% is already strong (random = 33%)
            if c >= 0.75:
                return 1.15
            elif c >= 0.65:
                return 1.25
            elif c >= 0.55:
                return 1.40
            elif c >= 0.50:
                return 1.55
            elif c >= 0.45:
                return 1.75
            else:
                return 2.10
        else:
            # Binary: 60% is the minimum (random = 50%)
            if c >= 0.80:
                return 1.15
            elif c >= 0.75:
                return 1.25
            elif c >= 0.70:
                return 1.35
            elif c >= 0.65:
                return 1.45
            elif c >= 0.60:
                return 1.55
            else:
                return 1.80

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _fmt_readable(self, value: str) -> str:
        m = {
            "home_win": "Home Win", "away_win": "Away Win", "draw": "Draw",
            "yes": "BTTS Yes", "no": "BTTS No",
            "over_2_5": "Over 2.5 goals", "under_2_5": "Under 2.5 goals",
        }
        return m.get(value, value.replace("_", " ").title())

    def _fmt_game(self, g):
        return {
            "fixture_id": g.get("fixture_id"),
            "home_team": g.get("home_team"),
            "away_team": g.get("away_team"),
            "league": g.get("league"),
            "date": g.get("date"),
            "prediction": g.get("readable_prediction", g.get("prediction_value", "")),
            "prediction_type": g.get("prediction_type"),
            "confidence": round(g.get("confidence", 0), 4),
            "average_confidence": round(g.get("average_confidence", 0), 4),
            "estimated_odds": g.get("estimated_odds"),
            "risk_score": g.get("risk_score"),
            "risk_level": g.get("risk_level"),
            "models_agreed": g.get("models_agreed", 0),
        }

    @staticmethod
    def _risk_label(r):
        if r <= 0.20: return "VERY_LOW"
        elif r <= 0.30: return "LOW"
        elif r <= 0.45: return "MEDIUM"
        else: return "HIGH"

    def _no(self, cat, mn, mx, reason):
        return {"selected": False, "category": cat,
                "target_range": "%.2f-%.2f" % (mn, mx), "reason": reason,
                "recommendation": "EXCLUDE"}

    def _empty_accumulators(self, reason):
        return {cat: self._no(cat, t["min"], t["max"], reason)
                for cat, t in self.TARGET_ODDS.items()}

    def _summary(self, accumulators):
        sel = [a for a in accumulators.values() if a.get("selected", False)]
        return {
            "categories_with_accumulators": len(sel),
            "total_categories": len(self.TARGET_ODDS),
            "total_games_in_accumulators": sum(a.get("num_games", 0) for a in sel),
            "success_rate": "%.1f%%" % (len(sel) / max(len(self.TARGET_ODDS), 1) * 100),
            "strategy": "best_confidence_safe_greedy",
        }


def format_accumulator_for_display(result):
    lines = ["Accumulator Result (%s)" % result.get("status", "unknown")]
    for cat, acc in result.get("accumulators", {}).items():
        if acc.get("selected"):
            lines.append(
                "  %s: %d games @ %.2f odds (avg conf: %.1f%%, risk: %s)"
                % (cat, acc["num_games"], acc["total_odds"],
                   acc["average_confidence"] * 100, acc["risk_level"])
            )
        else:
            lines.append("  %s: NOT SELECTED - %s" % (cat, acc.get("reason", "")))
    return "\n".join(lines)
