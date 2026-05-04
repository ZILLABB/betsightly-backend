"""
Accumulator Builder — Safe Games Only.

Greedy algorithm: combine many safe low-odds games until combined
odds hits the target range.  Never picks a risky game to hit a target.

Categories:
    2_odds   -> 1.80-2.50     rollover -> 2.00-3.00
    5_odds   -> 4.50-6.00     10_odds  -> 8.00-15.00
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from services.risk_scorer import RiskScorer, SAFE_RISK_THRESHOLD, SAFE_CONFIDENCE_THRESHOLD
except ImportError:
    from risk_scorer import RiskScorer, SAFE_RISK_THRESHOLD, SAFE_CONFIDENCE_THRESHOLD


class AccumulatorBuilder:

    TARGET_ODDS = {
        "2_odds":   {"min": 1.80, "max": 2.50},
        "5_odds":   {"min": 4.50, "max": 6.00},
        "10_odds":  {"min": 8.00, "max": 15.00},
        "rollover": {"min": 2.00, "max": 3.00},
    }
    MAX_GAMES = 15

    def __init__(
        self,
        risk_threshold: float = SAFE_RISK_THRESHOLD,
        confidence_threshold: float = SAFE_CONFIDENCE_THRESHOLD,
    ):
        self.risk_scorer = RiskScorer()
        self.risk_threshold = risk_threshold
        self.confidence_threshold = confidence_threshold

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def build_accumulators(self, predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            selections = self._extract_and_score(predictions)
            safe_pool = [s for s in selections if s.get("is_safe", False)]

            logger.info(
                "Accumulator: %d analyzed, %d scored, %d safe",
                len(predictions), len(selections), len(safe_pool),
            )

            if not safe_pool:
                return {
                    "status": "no_safe_selections",
                    "total_games_analyzed": len(predictions),
                    "safe_selections": 0,
                    "accumulators": self._empty_accumulators("No safe selections found"),
                    "summary": self._summary({}),
                }

            accumulators = {
                cat: self._build_category(safe_pool, cat, target)
                for cat, target in self.TARGET_ODDS.items()
            }

            return {
                "status": "success",
                "total_games_analyzed": len(predictions),
                "high_confidence_selections": len(selections),
                "safe_selections": len(safe_pool),
                "accumulators": accumulators,
                "summary": self._summary(accumulators),
            }
        except Exception as e:
            logger.error("AccumulatorBuilder error: %s", e, exc_info=True)
            return {
                "status": "error",
                "message": str(e),
                "accumulators": self._empty_accumulators("Internal error"),
            }

    # ------------------------------------------------------------------
    # Selection extraction — picks the safest prediction per fixture
    # ------------------------------------------------------------------

    def _extract_and_score(self, predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """For each fixture, pick the best prediction and score its risk.

        model_disagreement and elo_gap come from the fixture level
        (computed by BMA across all match-result models), not from
        individual sub-predictions.
        """
        selections: List[Dict[str, Any]] = []

        for pred in predictions:
            fi = pred.get("fixture_info", {})
            ml = pred.get("ml_predictions", {})
            fixture_disagreement = pred.get("model_disagreement", 0.5)
            fixture_elo_gap = pred.get("elo_gap", 0.0)

            best: Optional[Dict[str, Any]] = None

            for pk, pd in ml.items():
                conf = pd.get("confidence", 0.0)
                if conf < self.confidence_threshold:
                    continue

                candidate = {
                    "fixture_id": fi.get("fixture_id"),
                    "home_team": fi.get("home_team", ""),
                    "away_team": fi.get("away_team", ""),
                    "league": fi.get("league", ""),
                    "date": fi.get("date", ""),
                    "prediction_type": pd.get("model_name", pk),
                    "prediction_value": str(pd.get("prediction", "")),
                    "readable_prediction": self._fmt_readable(
                        str(pd.get("prediction", ""))
                    ),
                    "confidence": conf,
                    "estimated_odds": self._conf_to_odds(conf),
                    "model_type": pd.get("model_type", ""),
                    "raw_prediction": pd.get("prediction"),
                    "model_disagreement": fixture_disagreement,
                    "elo_gap": fixture_elo_gap,
                    "probabilities": pd.get("probabilities", {}),
                }

                # Score risk for this candidate
                candidate_risk = self.risk_scorer.score(candidate)

                if best is None or candidate_risk < best.get("_risk", 1.0):
                    candidate["_risk"] = candidate_risk
                    best = candidate

            if best is not None:
                best.pop("_risk", None)
                selections.append(self.risk_scorer.score_and_annotate(best))

        return sorted(selections, key=lambda x: x.get("risk_score", 1.0))

    # ------------------------------------------------------------------
    # Greedy safe accumulator building
    # ------------------------------------------------------------------

    def _build_category(
        self,
        safe_pool: List[Dict[str, Any]],
        category: str,
        target: Dict[str, float],
    ) -> Dict[str, Any]:
        min_odds, max_odds = target["min"], target["max"]

        if not safe_pool:
            return self._no(category, min_odds, max_odds, "No safe games available")

        chosen: List[Dict[str, Any]] = []
        running_odds = 1.0
        used: set = set()

        # Pass 1: add safest games that don't overshoot max_odds
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

        # Pass 2: if still below min_odds, allow up to 15% overshoot
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
                "Could not reach %.2f odds with safe games (best: %.2f)" % (min_odds, running_odds),
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
            "strategy": "safe_greedy",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _conf_to_odds(self, confidence: float) -> float:
        """Map model confidence to estimated decimal odds.

        Calibrated for 3-class football models where 40-50% is a strong
        signal.  Binary models (BTTS, over/under) will naturally get
        lower odds because their confidence is higher.
        """
        c = confidence
        if c >= 0.80:
            return 1.10
        elif c >= 0.70:
            return 1.20
        elif c >= 0.60:
            return 1.35
        elif c >= 0.55:
            return 1.50
        elif c >= 0.50:
            return 1.65
        elif c >= 0.45:
            return 1.80
        elif c >= 0.42:
            return 2.00
        elif c >= 0.40:
            return 2.15
        elif c >= 0.38:
            return 2.35
        elif c >= 0.36:
            return 2.60
        else:
            return 3.00

    def _fmt_readable(self, value: str) -> str:
        m = {
            "home_win": "Home Win", "away_win": "Away Win", "draw": "Draw",
            "yes": "BTTS Yes", "no": "BTTS No",
        }
        if "over" in value.lower():
            return "Over %s goals" % value.replace("over_", "").replace("_", ".")
        if "under" in value.lower():
            return "Under %s goals" % value.replace("under_", "").replace("_", ".")
        return m.get(value, value.replace("_", " ").title())

    def _fmt_game(self, g: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "fixture_id": g.get("fixture_id"),
            "home_team": g.get("home_team"),
            "away_team": g.get("away_team"),
            "league": g.get("league"),
            "date": g.get("date"),
            "prediction": g.get("readable_prediction", g.get("prediction_value", "")),
            "confidence": g.get("confidence"),
            "estimated_odds": g.get("estimated_odds"),
            "risk_score": g.get("risk_score"),
            "risk_level": g.get("risk_level"),
        }

    @staticmethod
    def _risk_label(avg_risk: float) -> str:
        if avg_risk <= 0.20:
            return "VERY_LOW"
        elif avg_risk <= 0.30:
            return "LOW"
        elif avg_risk <= 0.45:
            return "MEDIUM"
        else:
            return "HIGH"

    def _no(self, cat, mn, mx, reason):
        return {
            "selected": False,
            "category": cat,
            "target_range": "%.2f-%.2f" % (mn, mx),
            "reason": reason,
            "recommendation": "EXCLUDE",
        }

    def _empty_accumulators(self, reason: str) -> Dict[str, Any]:
        return {
            cat: self._no(cat, t["min"], t["max"], reason)
            for cat, t in self.TARGET_ODDS.items()
        }

    def _summary(self, accumulators: Dict[str, Any]) -> Dict[str, Any]:
        sel = [a for a in accumulators.values() if a.get("selected", False)]
        return {
            "categories_with_accumulators": len(sel),
            "total_categories": len(self.TARGET_ODDS),
            "total_games_in_accumulators": sum(a.get("num_games", 0) for a in sel),
            "success_rate": "%.1f%%" % (len(sel) / max(len(self.TARGET_ODDS), 1) * 100),
            "strategy": "safe_games_only",
        }


def format_accumulator_for_display(result: Dict[str, Any]) -> str:
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
