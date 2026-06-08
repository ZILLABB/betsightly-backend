"""
Real ML Predictions API Endpoints.

Uses the API-Football retrained models (.joblib) whose feature vector
is computed from the same data source as live fixtures, so team names
align perfectly. Also runs ELO, Dixon-Coles, and combines via BMA.
"""

import logging
import sys
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from collections import Counter

import joblib
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from services.fixture_service import FixtureService

logger = logging.getLogger(__name__)
router = APIRouter()

MATCHES_CSV = Path("data/api-football/matches.csv")
MODELS_DIR = Path("models/api_football")

# Saved statistical model paths (train once, load instantly)
ELO_SAVE_PATH = MODELS_DIR / "elo_ratings.json"
DC_SAVE_PATH = MODELS_DIR / "dixon_coles.json"
STAT_MODEL_MAX_AGE_DAYS = 7  # retrain if saved model is older than this

# Statistical model singletons (loaded once, reused)
_elo_system = None
_dixon_coles = None
_bma = None


def _is_model_fresh(path: Path, max_age_days: int = STAT_MODEL_MAX_AGE_DAYS) -> bool:
    """Check if a saved model file exists and is recent enough."""
    if not path.exists():
        return False
    age = datetime.now().timestamp() - path.stat().st_mtime
    return age < max_age_days * 86400


def _init_statistical_models(df: pd.DataFrame):
    """Load ELO and Dixon-Coles from disk. Only retrain if missing or stale.

    First run: trains from scratch and saves to models/api_football/.
    Subsequent runs: loads instantly from disk (< 1 second).
    Models auto-retrain every 7 days to stay current.
    """
    global _elo_system, _dixon_coles, _bma

    # --- ELO: load or train ---
    try:
        from ml.elo_model import EloRatingSystem
        _elo_system = EloRatingSystem()
        if _is_model_fresh(ELO_SAVE_PATH):
            _elo_system.load(str(ELO_SAVE_PATH))
            logger.info(f"ELO loaded from disk: {len(_elo_system.ratings)} teams (instant)")
        else:
            matches = _df_to_matches(df)
            if matches:
                _elo_system.train(matches)
                _elo_system.save(str(ELO_SAVE_PATH))
                logger.info(f"ELO trained and saved: {len(_elo_system.ratings)} teams")
    except Exception as e:
        logger.warning(f"ELO init failed: {e}")
        _elo_system = None

    # --- Dixon-Coles: load or train ---
    try:
        from ml.dixon_coles_model import DixonColesModel
        _dixon_coles = DixonColesModel()
        if _is_model_fresh(DC_SAVE_PATH):
            _dixon_coles.load(str(DC_SAVE_PATH))
            logger.info(f"Dixon-Coles loaded from disk: {len(_dixon_coles.teams)} teams (instant)")
        else:
            matches = _df_to_matches(df)
            if matches:
                logger.info("Dixon-Coles training (first run or weekly refresh)...")
                _dixon_coles.train(matches[-500:])
                _dixon_coles.save(str(DC_SAVE_PATH))
                logger.info(f"Dixon-Coles trained and saved: {len(_dixon_coles.teams)} teams")
    except Exception as e:
        logger.warning(f"Dixon-Coles init failed: {e}")
        _dixon_coles = None

    # --- BMA ---
    try:
        from ml.bayesian_averaging import BayesianModelAverager
        _bma = BayesianModelAverager()
    except Exception as e:
        logger.warning(f"BMA init failed: {e}")


def _df_to_matches(df: pd.DataFrame) -> list:
    """Convert DataFrame to list of match dicts for training."""
    matches = []
    for _, r in df.iterrows():
        try:
            matches.append({
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "home_goals": int(r["home_score"]),
                "away_goals": int(r["away_score"]),
                "date": str(r["date"]),
            })
        except (ValueError, KeyError):
            continue
    return matches


class RealMLPredictionService:
    """Prediction service using API-Football retrained models + statistical models."""

    def __init__(self):
        self.fixture_service = FixtureService()
        self.models_dir = MODELS_DIR
        self.api_models: Dict[str, Any] = {}
        self.api_df: Optional[pd.DataFrame] = None
        self.models: Dict[str, Dict] = {}

        self._load_api_football_models()

    def _load_api_football_models(self):
        """Load the .joblib models retrained on API-Football data."""
        meta_path = self.models_dir / "meta.json"
        if not meta_path.exists():
            logger.warning(f"No model meta at {meta_path} — run scripts/retrain_models.py")
            return

        with open(meta_path) as f:
            meta = json.load(f)

        for model_name in meta.get("models", []):
            p = self.models_dir / f"{model_name}.joblib"
            if p.exists():
                try:
                    self.api_models[model_name] = joblib.load(p)
                except Exception as e:
                    logger.warning(f"Skipping model {model_name}: {e}")

        logger.info(f"Loaded {len(self.api_models)} API-Football models")

        # Populate self.models for backward-compat with daily_predictions_service
        self.models = {"api_football": {k: {"model": v} for k, v in self.api_models.items()}}

        # Load historical CSV for feature computation
        try:
            if MATCHES_CSV.exists():
                self.api_df = pd.read_csv(MATCHES_CSV, low_memory=False)
                self.api_df["date"] = pd.to_datetime(self.api_df["date"], errors="coerce")
                self.api_df = self.api_df.dropna(subset=["date"]).sort_values("date")
                logger.info(f"Historical data: {len(self.api_df):,} matches")
                _init_statistical_models(self.api_df)
            else:
                logger.warning(f"{MATCHES_CSV} not found — run scripts/fetch_history.py")
        except Exception as e:
            logger.warning(f"Could not load historical data: {e}")

        # Also load encoders for backward compat (may not exist)
        self.encoders = {}

    def _compute_features(self, home: str, away: str, league_tier: int = 1) -> Optional[list]:
        """Compute 19-feature vector from historical data.

        Must mirror scripts/retrain_models.py:compute_features() exactly.
        """
        if self.api_df is None or len(self.api_df) == 0:
            return None

        now = datetime.now()
        df_past = self.api_df[self.api_df["date"] < pd.Timestamp(now)]

        def team_stats(team, n):
            games = df_past[(df_past["home_team"] == team) | (df_past["away_team"] == team)].tail(n)
            if len(games) == 0:
                return {"win_rate": 0.5, "draw_rate": 0.25, "goals_scored": 1.2, "goals_conceded": 1.2}
            wins = draws = gs = gc = 0
            for _, r in games.iterrows():
                if r["home_team"] == team:
                    s, c = r["home_score"], r["away_score"]
                else:
                    s, c = r["away_score"], r["home_score"]
                gs += s; gc += c
                if s > c: wins += 1
                elif s == c: draws += 1
            n_g = len(games)
            return {"win_rate": wins/n_g, "draw_rate": draws/n_g,
                    "goals_scored": gs/n_g, "goals_conceded": gc/n_g}

        def home_stats(team, n):
            games = df_past[df_past["home_team"] == team].tail(n)
            if len(games) == 0:
                return {"win_rate": 0.5, "goals_scored": 1.5}
            wins = sum(1 for _, r in games.iterrows() if r["home_score"] > r["away_score"])
            goals = sum(r["home_score"] for _, r in games.iterrows())
            return {"win_rate": wins/len(games), "goals_scored": goals/len(games)}

        def away_stats(team, n):
            games = df_past[df_past["away_team"] == team].tail(n)
            if len(games) == 0:
                return {"win_rate": 0.35, "goals_scored": 1.1}
            wins = sum(1 for _, r in games.iterrows() if r["away_score"] > r["home_score"])
            goals = sum(r["away_score"] for _, r in games.iterrows())
            return {"win_rate": wins/len(games), "goals_scored": goals/len(games)}

        def h2h_stats(home_t, away_t, n):
            h2h = df_past[
                ((df_past["home_team"] == home_t) & (df_past["away_team"] == away_t)) |
                ((df_past["home_team"] == away_t) & (df_past["away_team"] == home_t))
            ].tail(n)
            if len(h2h) == 0:
                return {"home_win_rate": 0.45, "avg_goals": 2.5, "btts_rate": 0.5, "n": 0}
            hw = btts = tg = 0
            for _, r in h2h.iterrows():
                hg = r["home_score"] if r["home_team"] == home_t else r["away_score"]
                ag = r["away_score"] if r["home_team"] == home_t else r["home_score"]
                tg += hg + ag
                if hg > ag: hw += 1
                if hg > 0 and ag > 0: btts += 1
            n_g = len(h2h)
            return {"home_win_rate": hw/n_g, "avg_goals": tg/n_g, "btts_rate": btts/n_g, "n": n_g}

        h5  = team_stats(home, 5);  h10 = team_stats(home, 10)
        hh5 = home_stats(home, 5)
        a5  = team_stats(away, 5);  a10 = team_stats(away, 10)
        aa5 = away_stats(away, 5)
        h2h = h2h_stats(home, away, 10)

        return [
            h5["win_rate"], h10["win_rate"], h5["draw_rate"],
            h5["goals_scored"], h5["goals_conceded"],
            hh5["win_rate"], hh5["goals_scored"],
            a5["win_rate"], a10["win_rate"], a5["draw_rate"],
            a5["goals_scored"], a5["goals_conceded"],
            aa5["win_rate"], aa5["goals_scored"],
            h2h["home_win_rate"], h2h["avg_goals"], h2h["btts_rate"],
            min(h2h["n"], 10) / 10,
            league_tier / 2,
        ]

    def _has_team_history(self, team: str) -> bool:
        """Check if a team has any historical data in matches.csv."""
        if self.api_df is None or len(self.api_df) == 0:
            return False
        return ((self.api_df["home_team"] == team) | (self.api_df["away_team"] == team)).any()

    def _odds_based_predictions(self, fixture: Dict[str, Any]) -> Dict[str, Any]:
        """Generate predictions from bookmaker odds when no historical data exists.

        This is used for World Cup / international matches where we don't have
        club-level historical stats.  Bookmaker odds encode expert assessment
        of each team's strength, so implied probabilities are a solid signal.
        """
        home_team = fixture.get("home_team", "Unknown")
        away_team = fixture.get("away_team", "Unknown")
        league = fixture.get("league_name", "Unknown")
        odds = fixture.get("odds", {}) or {}

        home_odds = odds.get("home")
        draw_odds = odds.get("draw")
        away_odds = odds.get("away")
        over_odds = odds.get("over_2_5")
        under_odds = odds.get("under_2_5")

        if not home_odds or not draw_odds or not away_odds:
            return {"error": "No odds available for odds-based prediction"}

        # Convert decimal odds to implied probabilities (remove overround)
        raw_h = 1.0 / home_odds
        raw_d = 1.0 / draw_odds
        raw_a = 1.0 / away_odds
        total = raw_h + raw_d + raw_a
        prob_h = raw_h / total
        prob_d = raw_d / total
        prob_a = raw_a / total

        # Match result prediction
        probs = {"home_win": prob_h, "draw": prob_d, "away_win": prob_a}
        best_result = max(probs, key=probs.get)
        best_conf = probs[best_result]

        ml_predictions = {}

        # Odds-implied match result (treated like a high-quality model)
        ml_predictions["odds_implied_result"] = {
            "prediction": best_result,
            "probabilities": [prob_a, prob_d, prob_h],
            "confidence": best_conf,
            "model_type": "odds_implied",
            "model_name": "odds_implied_result",
        }

        # Over/Under 2.5
        if over_odds and under_odds:
            raw_over = 1.0 / over_odds
            raw_under = 1.0 / under_odds
            ou_total = raw_over + raw_under
            prob_over = raw_over / ou_total
            prob_under = raw_under / ou_total
            ou_pred = "over_2_5" if prob_over > prob_under else "under_2_5"
            ou_conf = max(prob_over, prob_under)
            ml_predictions["odds_implied_over_2_5"] = {
                "prediction": ou_pred,
                "probabilities": [prob_under, prob_over],
                "confidence": ou_conf,
                "model_type": "odds_implied",
                "model_name": "odds_implied_over_2_5",
            }
        else:
            # World Cup average: ~2.5 goals/game, roughly 50/50 for over 2.5
            ml_predictions["odds_implied_over_2_5"] = {
                "prediction": "over_2_5",
                "probabilities": [0.48, 0.52],
                "confidence": 0.52,
                "model_type": "odds_implied",
                "model_name": "odds_implied_over_2_5",
            }

        # Over 1.5 (World Cup games almost always have 2+ goals — ~82% historically)
        ml_predictions["odds_implied_over_1_5"] = {
            "prediction": "over_1_5",
            "probabilities": [0.18, 0.82],
            "confidence": 0.82,
            "model_type": "odds_implied",
            "model_name": "odds_implied_over_1_5",
        }

        # BTTS — estimate from odds. Tight games (close odds) = more likely BTTS
        odds_gap = abs(prob_h - prob_a)
        btts_prob = 0.55 - (odds_gap * 0.3)  # tighter game = higher BTTS chance
        btts_prob = max(0.35, min(0.65, btts_prob))
        btts_pred = "yes" if btts_prob > 0.5 else "no"
        ml_predictions["odds_implied_btts"] = {
            "prediction": btts_pred,
            "probabilities": [1 - btts_prob, btts_prob],
            "confidence": max(btts_prob, 1 - btts_prob),
            "model_type": "odds_implied",
            "model_name": "odds_implied_btts",
        }

        return {
            "fixture_info": {
                "fixture_id": fixture.get("fixture_id"),
                "home_team": home_team,
                "away_team": away_team,
                "league": league,
                "date": fixture.get("date"),
                "status": fixture.get("status"),
                "home_team_logo": fixture.get("home_team_logo", ""),
                "away_team_logo": fixture.get("away_team_logo", ""),
                "league_logo": fixture.get("league_logo", ""),
            },
            "ml_predictions": ml_predictions,
            "model_disagreement": 0.0,
            "elo_gap": 0.0,
            "prediction_mode": "odds_implied",
            "model_summary": {
                "total_predictions": len(ml_predictions),
                "successful_predictions": len(ml_predictions),
                "note": "Odds-based predictions (no club history for national teams)",
            },
        }

    def generate_predictions_for_fixture(self, fixture: Dict[str, Any]) -> Dict[str, Any]:
        """Generate predictions for a single fixture using all available models."""
        try:
            home_team = fixture.get("home_team", "Unknown")
            away_team = fixture.get("away_team", "Unknown")
            league = fixture.get("league_name", "Unknown")
            league_id = fixture.get("league_id", 0)

            # Check if both teams have historical data
            home_has_history = self._has_team_history(home_team)
            away_has_history = self._has_team_history(away_team)

            # If either team has no history (national teams, new clubs),
            # use odds-based predictions instead of ML models with default features
            if not home_has_history or not away_has_history:
                logger.info(
                    f"Odds-based mode for {home_team} vs {away_team} "
                    f"(history: home={home_has_history}, away={away_has_history})"
                )
                return self._odds_based_predictions(fixture)

            # Determine league tier
            tier_2_leagues = {40, 62, 79, 136, 141}
            league_tier = 2 if league_id in tier_2_leagues else 1

            features = self._compute_features(home_team, away_team, league_tier)
            if features is None:
                return {"error": "Could not compute features (no historical data)"}

            X = np.array(features).reshape(1, -1)
            result_classes = {0: "away_win", 1: "draw", 2: "home_win"}
            ml_predictions = {}
            bma_inputs = []

            # Run API-Football retrained models
            for model_name, model in self.api_models.items():
                try:
                    proba = model.predict_proba(X)[0]
                    pred_idx = int(np.argmax(proba))
                    conf = float(proba[pred_idx])

                    if "match_result" in model_name:
                        pred_key = result_classes.get(pred_idx, "home_win")
                        prob_dict = {}
                        for ci, ck in result_classes.items():
                            prob_dict[ck] = float(proba[ci]) if ci < len(proba) else 0.0
                        bma_inputs.append({
                            "model_name": model_name,
                            "prediction": pred_key,
                            "confidence": conf,
                            "probabilities": prob_dict,
                        })
                        prediction_value = pred_key
                    elif "over_1_5" in model_name:
                        prediction_value = "over_1_5" if pred_idx == 1 else "under_1_5"
                    elif "over_2_5" in model_name:
                        prediction_value = "over_2_5" if pred_idx == 1 else "under_2_5"
                    elif "btts" in model_name:
                        prediction_value = "yes" if pred_idx == 1 else "no"
                    else:
                        prediction_value = str(pred_idx)

                    ml_predictions[model_name] = {
                        "prediction": prediction_value,
                        "probabilities": proba.tolist(),
                        "confidence": conf,
                        "model_type": model_name.split("_")[-1],
                        "model_name": model_name,
                    }
                except Exception as e:
                    logger.debug(f"Model {model_name} failed: {e}")

            # Run ELO
            elo_gap = 0.0
            if _elo_system is not None:
                try:
                    elo_pred = _elo_system.predict(home_team, away_team)
                    elo_gap = elo_pred.get("elo_gap", 0.0)
                    ml_predictions["elo_rating"] = {
                        "prediction": elo_pred["prediction"],
                        "probabilities": elo_pred.get("probabilities", {}),
                        "confidence": elo_pred["confidence"],
                        "model_type": "elo",
                        "model_name": "elo_rating",
                        "elo_gap": elo_gap,
                    }
                    bma_inputs.append({
                        "model_name": "elo_rating",
                        "prediction": elo_pred["prediction"],
                        "confidence": elo_pred["confidence"],
                        "probabilities": elo_pred.get("probabilities", {}),
                    })
                except Exception as e:
                    logger.debug(f"ELO failed: {e}")

            # Run Dixon-Coles
            if _dixon_coles is not None and _dixon_coles.is_trained:
                try:
                    dc_pred = _dixon_coles.predict(home_team, away_team)
                    ml_predictions["dixon_coles"] = {
                        "prediction": dc_pred["prediction"],
                        "probabilities": dc_pred.get("probabilities", {}),
                        "confidence": dc_pred["confidence"],
                        "model_type": "dixon_coles",
                        "model_name": "dixon_coles",
                        "expected_home_goals": dc_pred.get("expected_home_goals"),
                        "expected_away_goals": dc_pred.get("expected_away_goals"),
                        "over_2_5_probability": dc_pred.get("over_2_5_probability"),
                        "btts_probability": dc_pred.get("btts_probability"),
                    }
                    bma_inputs.append({
                        "model_name": "dixon_coles",
                        "prediction": dc_pred["prediction"],
                        "confidence": dc_pred["confidence"],
                        "probabilities": dc_pred.get("probabilities", {}),
                    })
                except Exception as e:
                    logger.debug(f"Dixon-Coles failed: {e}")

            if not ml_predictions:
                return {"error": "All models failed"}

            # Compute model disagreement via BMA or fallback
            model_disagreement = 0.0
            if _bma is not None and len(bma_inputs) >= 2:
                try:
                    combined = _bma.combine(bma_inputs)
                    model_disagreement = combined.get("model_disagreement", 0.0)
                except Exception:
                    pass
            elif len(bma_inputs) >= 2:
                pred_vals = [p["prediction"] for p in bma_inputs]
                majority = Counter(pred_vals).most_common(1)[0]
                model_disagreement = 1.0 - majority[1] / len(pred_vals)

            return {
                "fixture_info": {
                    "fixture_id": fixture.get("fixture_id"),
                    "home_team": home_team,
                    "away_team": away_team,
                    "league": league,
                    "date": fixture.get("date"),
                    "status": fixture.get("status"),
                    "home_team_logo": fixture.get("home_team_logo", ""),
                    "away_team_logo": fixture.get("away_team_logo", ""),
                    "league_logo": fixture.get("league_logo", ""),
                },
                "ml_predictions": ml_predictions,
                "model_disagreement": round(model_disagreement, 4),
                "elo_gap": round(elo_gap, 1),
                "model_summary": {
                    "total_predictions": len(ml_predictions),
                    "successful_predictions": len(ml_predictions),
                },
            }
        except Exception as e:
            logger.error(f"Error generating predictions: {e}")
            return {"error": str(e)}


# ------------------------------------------------------------------
# Module-level init
# ------------------------------------------------------------------
try:
    ml_service = RealMLPredictionService()
except Exception as _init_err:
    logger.error(f"ML service init failed (app will run without ML predictions): {_init_err}")
    ml_service = None  # type: ignore

_predictions_cache: Dict[str, Any] = {"date": None, "data": None, "timestamp": None}


# ------------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------------

@router.get("/today")
def get_todays_predictions(force_refresh: bool = Query(False)):
    """Get today's fixtures with ML predictions."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()

        if (not force_refresh
                and _predictions_cache["date"] == today
                and _predictions_cache["data"]
                and (now - _predictions_cache["timestamp"]).total_seconds() < 1800):
            return _predictions_cache["data"]

        all_fixtures = ml_service.fixture_service.get_daily_fixtures(today)
        upcoming = [fx for fx in all_fixtures if fx.get("status") in ("NS", "TBD")]

        predictions_results = []
        for fixture in upcoming:
            result = ml_service.generate_predictions_for_fixture(fixture)
            if "error" not in result:
                predictions_results.append(result)

        result = {
            "status": "success",
            "date": today,
            "total_fixtures": len(all_fixtures),
            "upcoming_fixtures": len(upcoming),
            "predictions_generated": len(predictions_results),
            "models_used": len(ml_service.api_models),
            "predictions": predictions_results,
            "cached": False,
        }

        _predictions_cache.update(date=today, data=result, timestamp=now)
        return result

    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve predictions")


@router.get("/categories")
def get_betting_categories():
    """Get today's betting categories."""
    try:
        resp = get_todays_predictions()
        return {
            "status": "success",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "predictions": resp.get("predictions", []),
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve betting categories")


@router.get("/fixture/{fixture_id}")
def get_fixture_prediction(fixture_id: int):
    """Get ML predictions for a specific fixture."""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        all_fixtures = ml_service.fixture_service.get_daily_fixtures(today)

        target = next((fx for fx in all_fixtures if fx.get("fixture_id") == fixture_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Fixture not found")

        result = ml_service.generate_predictions_for_fixture(target)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return {"status": "success", "fixture_id": fixture_id, "prediction": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve fixture prediction")


@router.get("/models/status")
def get_models_status():
    """Get status of loaded ML models."""
    return {
        "status": "success",
        "api_football_models": len(ml_service.api_models),
        "model_names": list(ml_service.api_models.keys()),
        "historical_data_loaded": ml_service.api_df is not None,
        "historical_matches": len(ml_service.api_df) if ml_service.api_df is not None else 0,
        "elo_available": _elo_system is not None,
        "elo_teams": len(_elo_system.ratings) if _elo_system else 0,
        "dixon_coles_available": _dixon_coles is not None and getattr(_dixon_coles, "is_trained", False),
        "dixon_coles_teams": len(_dixon_coles.teams) if _dixon_coles else 0,
        "bma_available": _bma is not None,
    }
