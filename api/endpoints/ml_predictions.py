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
        self.ensemble_meta: Dict[str, Any] = {}   # per-target weights + classes
        self.calibrators: Dict[str, Any] = {}     # per-target calibration payload

        self._load_api_football_models()

    def _load_api_football_models(self):
        """Load the .joblib models retrained on API-Football data."""
        meta_path = self.models_dir / "meta.json"
        if not meta_path.exists():
            logger.warning(f"No model meta at {meta_path} — run scripts/retrain_models.py")
            return

        with open(meta_path) as f:
            meta = json.load(f)

        # Feature schema the saved models were trained with. Older bundles
        # are 19 features; newer ones add 4 market features on the end.
        self.feature_columns = meta.get("feature_columns", [])
        self.expects_market_features = "mkt_prob_home" in self.feature_columns

        for model_name in meta.get("models", []):
            p = self.models_dir / f"{model_name}.joblib"
            if p.exists():
                try:
                    self.api_models[model_name] = joblib.load(p)
                except Exception as e:
                    logger.warning(f"Skipping model {model_name}: {e}")

        logger.info(f"Loaded {len(self.api_models)} API-Football models")

        # Load ensemble weights + calibrators (graceful if absent → old behavior)
        self.ensemble_meta = meta.get("ensemble", {}) or {}
        calib_path = self.models_dir / "calibrators.joblib"
        if calib_path.exists():
            try:
                self.calibrators = joblib.load(calib_path)
                logger.info(f"Loaded calibrators for {len(self.calibrators)} targets")
            except Exception as e:
                logger.warning(f"Could not load calibrators: {e}")

        # Populate self.models for backward-compat with daily_predictions_service
        self.models = {"api_football": {k: {"model": v} for k, v in self.api_models.items()}}

        # Load historical CSV for feature computation
        try:
            if MATCHES_CSV.exists():
                self.api_df = pd.read_csv(MATCHES_CSV, low_memory=False)
                self.api_df["date"] = pd.to_datetime(self.api_df["date"], errors="coerce")
                self.api_df = self.api_df.dropna(subset=["date"]).sort_values("date")
                logger.info(f"Historical data: {len(self.api_df):,} matches")
                self._build_team_index()
                _init_statistical_models(self.api_df)
            else:
                logger.warning(f"{MATCHES_CSV} not found — run scripts/fetch_history.py")
        except Exception as e:
            logger.warning(f"Could not load historical data: {e}")

        # Also load encoders for backward compat (may not exist)
        self.encoders = {}

    def _build_team_index(self):
        """Pre-index match history per team so feature computation is O(1).

        Replaces 7 full-DataFrame scans + iterrows() per fixture (seconds each
        on Render's shared CPU) with dict lookups. Built once at load (~0.1s).
        Lists preserve the DataFrame's date order, so tail-N slices match the
        old `.tail(n)` semantics exactly.
        """
        self._team_games: Dict[str, list] = {}   # team -> [(scored, conceded), ...]
        self._home_games: Dict[str, list] = {}   # team -> [(home_score, away_score), ...]
        self._away_games: Dict[str, list] = {}   # team -> [(away_score, home_score), ...]
        self._h2h_games: Dict[tuple, list] = {}  # sorted (a,b) -> [(home_team, hs, as), ...]

        df = self.api_df
        for home, away, hs, aw in zip(
            df["home_team"], df["away_team"], df["home_score"], df["away_score"]
        ):
            if pd.isna(hs) or pd.isna(aw):
                continue
            self._team_games.setdefault(home, []).append((hs, aw))
            self._team_games.setdefault(away, []).append((aw, hs))
            self._home_games.setdefault(home, []).append((hs, aw))
            self._away_games.setdefault(away, []).append((aw, hs))
            key = (home, away) if home <= away else (away, home)
            self._h2h_games.setdefault(key, []).append((home, hs, aw))

        logger.info(f"Team index built: {len(self._team_games)} teams, {len(self._h2h_games)} h2h pairs")

    # Same defaults as scripts/retrain_models.py:MKT_DEFAULTS — global base
    # rates with has_odds=0 so the model can discount them.
    _MKT_DEFAULTS = (0.44, 0.26, 0.30, 0.0)

    @staticmethod
    def _market_features(odds: Optional[Dict[str, Any]]) -> tuple:
        """(p_home, p_draw, p_away, has_odds) from live bookmaker odds."""
        try:
            oh = float((odds or {}).get("home") or 0)
            od = float((odds or {}).get("draw") or 0)
            oa = float((odds or {}).get("away") or 0)
            if oh <= 1.0 or od <= 1.0 or oa <= 1.0:
                return RealMLPredictionService._MKT_DEFAULTS
            ih, idr, ia = 1.0 / oh, 1.0 / od, 1.0 / oa
            tot = ih + idr + ia
            return (ih / tot, idr / tot, ia / tot, 1.0)
        except (TypeError, ValueError):
            return RealMLPredictionService._MKT_DEFAULTS

    def _compute_features(self, home: str, away: str, league_tier: int = 1,
                          odds: Optional[Dict[str, Any]] = None) -> Optional[list]:
        """Compute the feature vector from the pre-built team index.

        Must mirror scripts/retrain_models.py:build_dataset_fast() exactly —
        same formulas and same fallback defaults, just O(1) lookups instead
        of full-DataFrame scans. Emits 19 features for legacy model bundles,
        +4 market features (bookmaker-implied probabilities) for new ones.
        """
        if self.api_df is None or len(self.api_df) == 0:
            return None
        if not hasattr(self, "_team_games"):
            self._build_team_index()

        def team_stats(team, n):
            games = self._team_games.get(team, [])[-n:]
            if not games:
                return {"win_rate": 0.5, "draw_rate": 0.25, "goals_scored": 1.2, "goals_conceded": 1.2}
            wins = draws = gs = gc = 0
            for s, c in games:
                gs += s; gc += c
                if s > c: wins += 1
                elif s == c: draws += 1
            n_g = len(games)
            return {"win_rate": wins/n_g, "draw_rate": draws/n_g,
                    "goals_scored": gs/n_g, "goals_conceded": gc/n_g}

        def home_stats(team, n):
            games = self._home_games.get(team, [])[-n:]
            if not games:
                return {"win_rate": 0.5, "goals_scored": 1.5}
            wins = sum(1 for hs, aw in games if hs > aw)
            goals = sum(hs for hs, _ in games)
            return {"win_rate": wins/len(games), "goals_scored": goals/len(games)}

        def away_stats(team, n):
            games = self._away_games.get(team, [])[-n:]
            if not games:
                return {"win_rate": 0.35, "goals_scored": 1.1}
            wins = sum(1 for aw, hs in games if aw > hs)
            goals = sum(aw for aw, _ in games)
            return {"win_rate": wins/len(games), "goals_scored": goals/len(games)}

        def h2h_stats(home_t, away_t, n):
            key = (home_t, away_t) if home_t <= away_t else (away_t, home_t)
            h2h = self._h2h_games.get(key, [])[-n:]
            if not h2h:
                return {"home_win_rate": 0.45, "avg_goals": 2.5, "btts_rate": 0.5, "n": 0}
            hw = btts = tg = 0
            for match_home, hs, aw in h2h:
                hg = hs if match_home == home_t else aw
                ag = aw if match_home == home_t else hs
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

        feats = [
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
        if getattr(self, "expects_market_features", False):
            feats.extend(self._market_features(odds))
        return feats

    # Maps from integer class -> human label, per target
    _CLASS_LABELS = {
        "match_result": {0: "away_win", 1: "draw", 2: "home_win"},
        "over_1_5": {0: "under_1_5", 1: "over_1_5"},
        "over_2_5": {0: "under_2_5", 1: "over_2_5"},
        "btts": {0: "no", 1: "yes"},
    }

    def _ensemble_for_target(self, label: str, X) -> Optional[Dict[str, Any]]:
        """Weighted + calibrated ensemble prediction for one target.

        Blends every base model's probability using the saved log-loss
        weights, applies isotonic calibration, and returns the calibrated
        winner. Returns None if the ensemble isn't available (pre-retrain
        models) so callers fall back to per-model behavior.
        """
        meta = self.ensemble_meta.get(label)
        if not meta:
            return None
        classes = meta.get("classes", [])
        weights = meta.get("weights", {})
        if not classes or not weights:
            return None

        agg = np.zeros(len(classes))
        used = 0.0
        for tag, w in weights.items():
            model = self.api_models.get(f"{label}_{tag}")
            if model is None:
                continue
            try:
                p = model.predict_proba(X)[0]
                model_classes = list(model.classes_)
                aligned = np.zeros(len(classes))
                for j, c in enumerate(classes):
                    if c in model_classes:
                        aligned[j] = p[model_classes.index(c)]
                agg += w * aligned
                used += w
            except Exception as e:
                logger.debug(f"Ensemble model {label}_{tag} failed: {e}")
        if used == 0:
            return None
        agg /= used  # renormalize over models that actually fired

        # Calibrate (per-class isotonic) if available
        calib = self.calibrators.get(label)
        if calib and calib.get("classes") == classes:
            cal = np.array([
                calib["calibrators"][j].predict([agg[j]])[0]
                for j in range(len(classes))
            ])
            s = cal.sum()
            if s > 0:
                agg = cal / s

        best_idx = int(np.argmax(agg))
        best_class = classes[best_idx]
        label_map = self._CLASS_LABELS.get(label, {})
        return {
            "prediction": label_map.get(best_class, str(best_class)),
            "probabilities": agg.tolist(),
            "confidence": float(agg[best_idx]),
            "model_type": "ensemble",
            "model_name": f"ensemble_{'result' if label == 'match_result' else label}",
        }

    def _has_team_history(self, team: str) -> bool:
        """Check if a team has any historical data in matches.csv."""
        if self.api_df is None or len(self.api_df) == 0:
            return False
        if not hasattr(self, "_team_games"):
            self._build_team_index()
        return team in self._team_games

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

            features = self._compute_features(
                home_team, away_team, league_tier, odds=fixture.get("odds")
            )
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

            # Weighted + calibrated ensemble per target (the headline picks).
            # These are what the accumulator and results loop prefer; the
            # individual model entries above are kept for transparency.
            for label in ("match_result", "over_1_5", "over_2_5", "btts"):
                ens = self._ensemble_for_target(label, X)
                if ens:
                    ml_predictions[ens["model_name"]] = ens
                    if label == "match_result":
                        bma_inputs.append({
                            "model_name": ens["model_name"],
                            "prediction": ens["prediction"],
                            "confidence": ens["confidence"],
                            "probabilities": {
                                "away_win": ens["probabilities"][0],
                                "draw": ens["probabilities"][1],
                                "home_win": ens["probabilities"][2],
                            },
                        })

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

# Guards duplicate background generation kicks from concurrent requests
_generation_in_flight = {"date": None}


def _read_predictions_from_db(today: str) -> Optional[Dict[str, Any]]:
    """Reconstruct the /today response from stored DailyPrediction rows.

    Returns None when nothing has been generated for the date yet.
    """
    from database import SessionLocal
    from services.daily_predictions_service import DailyPrediction, DailyPredictionSummary

    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    db = SessionLocal()
    try:
        summary = db.query(DailyPredictionSummary).filter(
            DailyPredictionSummary.prediction_date == today_date
        ).first()
        if summary is None or summary.generation_status != "completed":
            return None

        rows = db.query(DailyPrediction).filter(
            DailyPrediction.prediction_date == today_date
        ).all()

        predictions_results = []
        for row in rows:
            try:
                predictions_results.append({
                    "fixture_info": {
                        "fixture_id": row.fixture_id,
                        "home_team": row.home_team,
                        "away_team": row.away_team,
                        "league": row.league_name,
                        "date": row.fixture_date.isoformat() if row.fixture_date else "",
                        "status": row.fixture_status,
                        "home_team_logo": "",
                        "away_team_logo": "",
                        "league_logo": "",
                    },
                    "ml_predictions": json.loads(row.ml_predictions or "{}"),
                    "model_summary": {
                        "total_predictions": row.total_models_used,
                        "successful_predictions": row.total_models_used,
                    },
                })
            except Exception as e:
                logger.warning(f"Skipping malformed DB prediction row {row.id}: {e}")

        return {
            "status": "success",
            "date": today,
            "total_fixtures": summary.total_fixtures,
            "upcoming_fixtures": summary.upcoming_fixtures,
            "predictions_generated": len(predictions_results),
            "models_used": summary.models_used,
            "predictions": predictions_results,
            "source": "database",
            "cached": False,
        }
    finally:
        db.close()


def _kick_background_generation(today: str) -> None:
    """Start prediction generation in a background thread (deduped per date).

    The request path must never run ML inference inline: with a single
    uvicorn worker, computing features for a full match day pins the worker
    for a minute+ and every other request queues behind it.
    """
    import threading

    if _generation_in_flight["date"] == today:
        return
    _generation_in_flight["date"] = today

    def _run():
        try:
            from services.daily_predictions_service import DailyPredictionsService
            DailyPredictionsService().generate_daily_predictions(today)
        except Exception as e:
            logger.error(f"Background generation failed: {e}")
        finally:
            _generation_in_flight["date"] = None

    threading.Thread(target=_run, daemon=True, name=f"predict-gen-{today}").start()


@router.get("/today")
def get_todays_predictions(force_refresh: bool = Query(False)):
    """Get today's ML predictions.

    Serves from the in-process cache, then PostgreSQL. If nothing has been
    generated yet, kicks off generation in the background and tells the
    client to retry — it never computes predictions in the request path.
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()

        if (not force_refresh
                and _predictions_cache["date"] == today
                and _predictions_cache["data"]
                and (now - _predictions_cache["timestamp"]).total_seconds() < 1800):
            return _predictions_cache["data"]

        db_result = _read_predictions_from_db(today)
        if db_result is not None:
            _predictions_cache.update(date=today, data=db_result, timestamp=now)
            return db_result

        # Nothing in the DB yet — generate in the background, respond now
        _kick_background_generation(today)
        return {
            "status": "generating",
            "date": today,
            "total_fixtures": 0,
            "upcoming_fixtures": 0,
            "predictions_generated": 0,
            "models_used": len(ml_service.api_models) if ml_service else 0,
            "predictions": [],
            "message": "Predictions are being generated — retry in ~60 seconds.",
            "retry_after_seconds": 60,
        }

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


@router.get("/accuracy")
def get_prediction_accuracy(days: int = Query(30, ge=1, le=365)):
    """Real, settled prediction accuracy per market over the last N days.

    Backed by the results loop: every stored prediction is scored against
    the actual final score, so these numbers are measured, not estimated.
    """
    try:
        from services.prediction_results_service import PredictionResultsService
        return {
            "status": "success",
            **PredictionResultsService().get_accuracy(days=days),
        }
    except Exception as e:
        logger.error(f"Accuracy endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Failed to compute accuracy")


@router.post("/results/settle")
def settle_results(date: Optional[str] = Query(None, description="YYYY-MM-DD, default yesterday")):
    """Manually trigger results settlement for a date (admin/debug)."""
    try:
        from services.prediction_results_service import PredictionResultsService
        return {"status": "success", **PredictionResultsService().settle_date(date)}
    except Exception as e:
        logger.error(f"Settle endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Failed to settle results")
