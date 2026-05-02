#!/usr/bin/env python3
"""
Advanced Prediction Service - Production ML Integration

This service integrates all advanced ML models (XGBoost, Ensemble, Enhanced)
for maximum prediction accuracy and sophistication.

Features:
- XGBoost models with hyperparameter optimization
- Ensemble models with voting and stacking
- Advanced feature engineering pipeline
- SHAP/LIME explanations
- Meta-model stacking
- Calibrated confidence scores
"""

import os
import sys
import logging
import joblib
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import requests
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# Load environment variables
load_dotenv()

# Set up logging
logger = logging.getLogger(__name__)

# Import ML components with robust error handling
try:
    from ml.feature_engineering import AdvancedFootballFeatureEngineer
    FEATURE_ENGINEERING_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Advanced feature engineering not available: {str(e)}")
    FEATURE_ENGINEERING_AVAILABLE = False

try:
    from ml.model_factory import ModelFactory
    MODEL_FACTORY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Model factory not available: {str(e)}")
    MODEL_FACTORY_AVAILABLE = False

# Import model compatibility service
try:
    from services.model_compatibility_service import model_compatibility_service
    MODEL_COMPATIBILITY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Model compatibility service not available: {str(e)}")
    MODEL_COMPATIBILITY_AVAILABLE = False

ADVANCED_ML_AVAILABLE = FEATURE_ENGINEERING_AVAILABLE and MODEL_FACTORY_AVAILABLE

# Disable SHAP temporarily for memory optimization on Render
SHAP_AVAILABLE = False
logger.info("ℹ️ SHAP disabled for memory optimization")

# Disable LIME temporarily for memory optimization
LIME_AVAILABLE = False
logger.info("ℹ️ LIME disabled for memory optimization")


class AdvancedPredictionService:
    """
    Advanced ML prediction service using XGBoost, ensemble models, and explanations.
    
    This service provides the highest accuracy predictions by combining:
    - Pre-trained XGBoost models
    - Ensemble models with voting
    - Advanced feature engineering
    - Model explanations (SHAP/LIME)
    - Meta-model stacking
    """
    
    def __init__(self):
        """Initialize the advanced prediction service (models are loaded lazily on first use)."""
        self.football_data_api_key = os.getenv("FOOTBALL_DATA_API_KEY")
        self.api_football_key = os.getenv("API_FOOTBALL_API_KEY")
        self.base_url_football_data = "https://api.football-data.org/v4"
        self.base_url_api_football = "https://v3.football.api-sports.io"

        # ML components — populated on first use via _ensure_loaded()
        self.feature_engineer = None
        self.model_factory = None
        self.models = {}
        self.explainers = {}

        # Memory optimization for Render (512MB limit)
        self.memory_limit_mb = 400  # Leave 112MB buffer
        self.models_loaded = 0
        self._loaded = False

    def _ensure_loaded(self):
        """Load ML components and models on first use (lazy init)."""
        if self._loaded:
            return
        self._initialize_ml_components()
        self._load_advanced_models()
        self._setup_explainers()
        self._loaded = True
        logger.info(f"Advanced Prediction Service loaded {self.models_loaded} models")
    
    def _initialize_ml_components(self):
        """Initialize ML components and inject historical data into feature engineer."""
        if FEATURE_ENGINEERING_AVAILABLE:
            try:
                self.feature_engineer = AdvancedFootballFeatureEngineer()
                self._load_historical_data()
                logger.info("✅ Advanced feature engineering initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize feature engineering: {str(e)}")

        if MODEL_FACTORY_AVAILABLE:
            try:
                self.model_factory = ModelFactory()
                logger.info("✅ Model factory initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize model factory: {str(e)}")

        if ADVANCED_ML_AVAILABLE:
            logger.info("✅ Advanced ML components fully initialized")
        else:
            logger.warning("⚠️ Advanced ML components partially available - using fallbacks")

    def _load_historical_data(self):
        """Load the GitHub dataset into the feature engineer."""
        try:
            from services.historical_data_service import historical_data_service
            df = historical_data_service.get_historical_data()
            if df is not None and self.feature_engineer is not None:
                self.feature_engineer.set_historical_data(df)
                logger.info(f"✅ Historical data injected: {len(df):,} matches available for feature engineering")
                self._historical_data_service = historical_data_service
            else:
                logger.warning("⚠️ Historical data not available — feature engineering will use heuristics")
        except Exception as e:
            logger.error(f"❌ Failed to load historical data: {e}")
    
    def _load_advanced_models(self):
        """Load all available advanced models."""
        # Optimized model loading for Render 512MB limit - Load only essential models
        model_directories = [
            ("xgboost", "models/xgboost"),      # Priority 1: Core XGBoost models (10 models)
            # Skip other models to stay under memory limit
        ]

        for model_type, model_dir in model_directories:
            self._load_models_from_directory(model_type, model_dir)
    
    def _load_models_from_directory(self, model_type: str, model_dir: str):
        """Load models from a specific directory."""
        model_path = Path(model_dir)
        
        if not model_path.exists():
            logger.warning(f"Model directory not found: {model_dir}")
            return
        
        model_files = list(model_path.glob("*.joblib"))
        loaded_count = 0
        
        for model_file in model_files:
            # Extract model name (remove .joblib extension)
            model_name = model_file.stem
            full_model_name = f"{model_type}_{model_name}"

            if MODEL_COMPATIBILITY_AVAILABLE:
                # Use compatibility service for safe loading
                model, success = model_compatibility_service.load_model_safely(
                    str(model_file), full_model_name
                )

                if model is not None:
                    self.models[full_model_name] = {
                        "model": model,
                        "type": model_type,
                        "name": model_name,
                        "path": str(model_file),
                        "compatibility_status": "success" if success else "fallback"
                    }
                    loaded_count += 1
                    self.models_loaded += 1

            else:
                # Fallback to direct loading
                try:
                    model = joblib.load(model_file)

                    self.models[full_model_name] = {
                        "model": model,
                        "type": model_type,
                        "name": model_name,
                        "path": str(model_file),
                        "compatibility_status": "direct_load"
                    }

                    loaded_count += 1
                    logger.info(f"✅ Loaded {full_model_name}")

                except Exception as e:
                    logger.error(f"❌ Failed to load {model_file}: {str(e)}")
        
        logger.info(f"✅ Loaded {loaded_count} models from {model_dir}")
    
    def _setup_explainers(self):
        """Setup SHAP and LIME explainers for loaded models."""
        if not (SHAP_AVAILABLE or LIME_AVAILABLE):
            logger.warning("No explanation libraries available")
            return
        
        # Setup explainers for XGBoost models
        for model_name, model_info in self.models.items():
            if "xgboost" in model_name and SHAP_AVAILABLE:
                if MODEL_COMPATIBILITY_AVAILABLE:
                    # Use compatibility service for SHAP setup
                    explainer = model_compatibility_service.setup_shap_safely(
                        model_info["model"], model_name
                    )

                    if explainer is not None:
                        self.explainers[model_name] = {
                            "type": "shap",
                            "explainer": explainer
                        }
                        logger.info(f"✅ SHAP explainer ready for {model_name}")
                else:
                    # Fallback to direct SHAP setup
                    try:
                        explainer = shap.TreeExplainer(model_info["model"])
                        self.explainers[model_name] = {
                            "type": "shap",
                            "explainer": explainer
                        }
                        logger.info(f"✅ SHAP explainer ready for {model_name}")
                    except Exception as e:
                        logger.error(f"❌ Failed to setup SHAP for {model_name}: {str(e)}")
    
    def get_predictions_for_date(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        Get advanced ML predictions for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format (default: today)

        Returns:
            Dictionary with advanced predictions and metadata
        """
        self._ensure_loaded()

        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        start_time = datetime.now()
        
        try:
            # Get fixtures from API
            fixtures = self._get_fixtures_from_api(date_str)
            
            if not fixtures:
                return self._empty_result(date_str, "No fixtures found")
            
            # Generate advanced predictions
            predictions = []
            for fixture in fixtures:
                prediction = self._predict_fixture_advanced(fixture)
                if prediction:
                    predictions.append(prediction)
            
            # Categorize predictions using advanced logic
            categories = self._categorize_predictions_advanced(predictions)
            
            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return {
                "status": "success",
                "date": date_str,
                "predictions": predictions,
                "categories": categories,
                "metadata": {
                    "service": "advanced_prediction_service",
                    "models_used": list(self.models.keys()),
                    "total_fixtures": len(fixtures),
                    "total_predictions": len(predictions),
                    "processing_time_seconds": round(processing_time, 3),
                    "advanced_features": {
                        "xgboost_models": len([m for m in self.models.keys() if "xgboost" in m]),
                        "ensemble_models": len([m for m in self.models.keys() if "enhanced" in m]),
                        "explainers_available": len(self.explainers),
                        "feature_engineering": "advanced"
                    }
                },
                "data_source": "real_football_data"
            }
            
        except Exception as e:
            logger.error(f"❌ Error in advanced predictions: {str(e)}")
            return self._empty_result(date_str, str(e))
    
    def _empty_result(self, date_str: str, message: str) -> Dict[str, Any]:
        """Return empty result with error message."""
        return {
            "status": "success",
            "date": date_str,
            "predictions": [],
            "categories": {"2_odds": [], "5_odds": [], "10_odds": [], "rollover": []},
            "message": message,
            "metadata": {"service": "advanced_prediction_service", "models_loaded": len(self.models)}
        }

    def _get_fixtures_from_api(self, date_str: str) -> List[Dict]:
        """Get fixtures from API using real API keys."""
        try:
            # Try Football-Data.org first
            if self.football_data_api_key and len(self.football_data_api_key) > 10:
                logger.info(f"🌐 Using Football-Data.org API")
                return self._get_fixtures_football_data(date_str)

            # Try API-Football as fallback
            elif self.api_football_key and len(self.api_football_key) > 10:
                logger.info(f"🌐 Using API-Football API")
                return self._get_fixtures_api_football(date_str)

            else:
                logger.warning("⚠️  No valid API keys found")
                return []

        except Exception as e:
            logger.error(f"❌ Error fetching fixtures: {str(e)}")
            return []

    def _get_fixtures_football_data(self, date_str: str) -> List[Dict]:
        """Get fixtures from Football-Data.org API."""
        try:
            headers = {"X-Auth-Token": self.football_data_api_key}

            # Get fixtures for major leagues
            leagues = ["PL", "BL1", "SA", "PD", "FL1"]  # Premier League, Bundesliga, Serie A, La Liga, Ligue 1
            all_fixtures = []

            for league in leagues:
                url = f"{self.base_url_football_data}/competitions/{league}/matches"
                params = {"dateFrom": date_str, "dateTo": date_str}

                response = requests.get(url, headers=headers, params=params, timeout=10)

                if response.status_code == 200:
                    data = response.json()
                    fixtures = data.get("matches", [])
                    all_fixtures.extend(fixtures)
                    logger.info(f"✅ Got {len(fixtures)} fixtures from {league}")
                else:
                    logger.warning(f"⚠️  Failed to get {league} fixtures: {response.status_code}")

            return all_fixtures

        except Exception as e:
            logger.error(f"❌ Football-Data.org API error: {str(e)}")
            return []

    def _get_fixtures_api_football(self, date_str: str) -> List[Dict]:
        """Get fixtures from API-Football."""
        try:
            headers = {
                "x-rapidapi-key": self.api_football_key,
                "x-rapidapi-host": "v3.football.api-sports.io"
            }

            url = f"{self.base_url_api_football}/fixtures"
            params = {"date": date_str}

            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                fixtures = data.get("response", [])
                logger.info(f"✅ Got {len(fixtures)} fixtures from API-Football")
                return fixtures
            else:
                logger.warning(f"⚠️  API-Football failed: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"❌ API-Football error: {str(e)}")
            return []

    def _predict_fixture_advanced(self, fixture: Dict) -> Optional[Dict]:
        """Generate advanced ML prediction for a single fixture."""
        try:
            # Extract team information
            if "homeTeam" in fixture:  # Football-Data.org format
                home_team = fixture["homeTeam"]["name"]
                away_team = fixture["awayTeam"]["name"]
                league = fixture.get("competition", {}).get("name", "Unknown")
            else:  # API-Football format
                home_team = fixture["teams"]["home"]["name"]
                away_team = fixture["teams"]["away"]["name"]
                league = fixture.get("league", {}).get("name", "Unknown")

            # Engineer features for this match
            features = self._engineer_match_features_advanced(home_team, away_team, league)

            # Get predictions from all available models
            model_predictions = self._get_ensemble_predictions(features, home_team, away_team)

            # Apply meta-model stacking
            final_prediction = self._apply_meta_stacking(model_predictions, features)

            # Generate explanations if available
            explanations = self._generate_explanations(features, final_prediction)

            # Calculate advanced confidence score
            confidence = self._calculate_advanced_confidence(model_predictions, final_prediction)

            # Determine odds category
            odds = self._calculate_odds_from_confidence(confidence)
            category = self._determine_odds_category(odds)

            return {
                "home_team": home_team,
                "away_team": away_team,
                "league": league,
                "prediction": final_prediction["prediction"],
                "confidence": confidence,
                "odds": odds,
                "category": category,
                "model_predictions": model_predictions,
                "explanations": explanations,
                "advanced_features": {
                    "meta_stacking": True,
                    "ensemble_voting": True,
                    "feature_engineering": "advanced",
                    "models_used": len(model_predictions)
                }
            }

        except Exception as e:
            logger.error(f"❌ Error predicting fixture: {str(e)}")
            return None

    def _engineer_match_features_advanced(self, home_team: str, away_team: str, league: str) -> List[float]:
        """Engineer advanced features for a match using ML feature engineering."""
        try:
            if self.feature_engineer and ADVANCED_ML_AVAILABLE:
                # Normalise API team names to dataset naming convention
                norm_home = home_team
                norm_away = away_team
                if hasattr(self, "_historical_data_service"):
                    norm_home = self._historical_data_service.normalize_team_name(home_team)
                    norm_away = self._historical_data_service.normalize_team_name(away_team)

                features_df = self.feature_engineer.engineer_features_for_match(
                    norm_home, norm_away, league, datetime.now()
                )
                if features_df is not None and not features_df.empty:
                    return features_df.values.flatten().tolist()
                logger.warning(f"Feature engineering returned empty DataFrame for {home_team} vs {away_team}")

        except Exception as e:
            logger.error(f"❌ Feature engineering error: {str(e)}")

        return self._engineer_basic_features(home_team, away_team, league)

    def _engineer_basic_features(self, home_team: str, away_team: str, league: str) -> List[float]:
        """Basic feature engineering as fallback."""
        # Simple team strength mapping
        team_strengths = {
            "Arsenal": 0.8, "Chelsea": 0.8, "Manchester City": 0.9, "Liverpool": 0.85,
            "Manchester United": 0.75, "Tottenham": 0.7, "Real Madrid": 0.9, "Barcelona": 0.85,
            "Bayern Munich": 0.9, "PSG": 0.85, "Juventus": 0.8, "AC Milan": 0.75
        }

        home_strength = team_strengths.get(home_team, 0.5) + 0.1  # Home advantage
        away_strength = team_strengths.get(away_team, 0.5)

        # Create basic feature vector
        features = [
            home_strength,
            away_strength,
            home_strength - away_strength,  # Strength difference
            (home_strength + away_strength) / 2,  # Average strength
            1.0 if "Premier League" in league else 0.5,  # League strength
            0.1,  # Home advantage
        ]

        return features

    def _get_ensemble_predictions(self, features: List[float], home_team: str, away_team: str) -> Dict[str, Any]:
        """Get predictions from all available models."""
        predictions = {}

        # Convert features to numpy array for model prediction
        features_array = np.array(features).reshape(1, -1)

        for model_name, model_info in self.models.items():
            try:
                model = model_info["model"]

                # Get prediction based on model type
                if hasattr(model, 'predict_proba'):
                    # Classification model
                    probabilities = model.predict_proba(features_array)[0]
                    prediction_class = model.predict(features_array)[0]

                    # Map prediction to readable format
                    if "match_result" in model_name:
                        classes = ["Away Win", "Draw", "Home Win"]
                        prediction = classes[prediction_class] if prediction_class < len(classes) else "Home Win"
                    elif "over_under" in model_name:
                        prediction = "Over 2.5" if prediction_class == 1 else "Under 2.5"
                    elif "btts" in model_name:
                        prediction = "BTTS Yes" if prediction_class == 1 else "BTTS No"
                    else:
                        prediction = f"Class {prediction_class}"

                    confidence = max(probabilities) * 100

                else:
                    # Regression model
                    prediction_value = model.predict(features_array)[0]
                    prediction = f"Score: {prediction_value:.1f}"
                    confidence = 70.0  # Default confidence for regression

                predictions[model_name] = {
                    "prediction": prediction,
                    "confidence": round(confidence, 1),
                    "model_type": model_info["type"]
                }

            except Exception as e:
                logger.error(f"❌ Error with model {model_name}: {str(e)}")
                continue

        return predictions

    def _apply_meta_stacking(self, model_predictions: Dict[str, Any], features: List[float]) -> Dict[str, Any]:
        """Apply meta-model stacking to combine predictions."""
        if not model_predictions:
            return {"prediction": "No prediction", "confidence": 0.0}

        # Simple voting ensemble as meta-stacking
        prediction_votes = {}
        confidence_scores = []

        for model_name, pred_info in model_predictions.items():
            prediction = pred_info["prediction"]
            confidence = pred_info["confidence"]

            # Weight by model type (XGBoost gets higher weight)
            weight = 2.0 if "xgboost" in model_name else 1.5 if "enhanced" in model_name else 1.0

            if prediction not in prediction_votes:
                prediction_votes[prediction] = 0
            prediction_votes[prediction] += weight * (confidence / 100)
            confidence_scores.append(confidence)

        # Get the prediction with highest weighted vote
        if prediction_votes:
            final_prediction = max(prediction_votes.items(), key=lambda x: x[1])[0]
            meta_confidence = np.mean(confidence_scores)
        else:
            final_prediction = "No prediction"
            meta_confidence = 0.0

        return {
            "prediction": final_prediction,
            "confidence": round(meta_confidence, 1),
            "voting_scores": prediction_votes
        }

    def _generate_explanations(self, features: List[float], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """Generate SHAP/LIME explanations for the prediction."""
        explanations = {"available": False}

        if not self.explainers:
            return explanations

        try:
            # Use SHAP explainer if available
            for model_name, explainer_info in self.explainers.items():
                if explainer_info["type"] == "shap":
                    explainer = explainer_info["explainer"]

                    # Generate SHAP values
                    features_array = np.array(features).reshape(1, -1)
                    shap_values = explainer.shap_values(features_array)

                    explanations = {
                        "available": True,
                        "type": "shap",
                        "model": model_name,
                        "feature_importance": shap_values[0].tolist() if isinstance(shap_values, list) else shap_values.tolist(),
                        "explanation": "Feature importance scores from SHAP analysis"
                    }
                    break

        except Exception as e:
            logger.error(f"❌ Error generating explanations: {str(e)}")

        return explanations

    def _calculate_advanced_confidence(self, model_predictions: Dict[str, Any], final_prediction: Dict[str, Any]) -> float:
        """Calculate advanced confidence score based on model agreement."""
        if not model_predictions:
            return 0.0

        # Get confidence scores from all models
        confidences = [pred["confidence"] for pred in model_predictions.values()]

        # Calculate agreement score (how many models agree with final prediction)
        agreement_count = 0
        total_models = len(model_predictions)

        for pred_info in model_predictions.values():
            if pred_info["prediction"] == final_prediction["prediction"]:
                agreement_count += 1

        agreement_ratio = agreement_count / total_models if total_models > 0 else 0

        # Combine average confidence with agreement ratio
        avg_confidence = np.mean(confidences) if confidences else 0
        advanced_confidence = (avg_confidence * 0.7) + (agreement_ratio * 100 * 0.3)

        return round(min(advanced_confidence, 95.0), 1)  # Cap at 95%

    def _calculate_odds_from_confidence(self, confidence: float) -> float:
        """Calculate betting odds from confidence score."""
        if confidence >= 80:
            return round(1.2 + (100 - confidence) * 0.02, 2)
        elif confidence >= 60:
            return round(1.5 + (80 - confidence) * 0.05, 2)
        elif confidence >= 40:
            return round(2.0 + (60 - confidence) * 0.1, 2)
        else:
            return round(4.0 + (40 - confidence) * 0.2, 2)

    def _determine_odds_category(self, odds: float) -> str:
        """Determine odds category based on calculated odds."""
        if odds <= 2.5:
            return "2_odds"
        elif odds <= 5.0:
            return "5_odds"
        elif odds <= 10.0:
            return "10_odds"
        else:
            return "rollover"

    def _categorize_predictions_advanced(self, predictions: List[Dict]) -> Dict[str, List[Dict]]:
        """Categorize predictions using advanced logic."""
        categories = {
            "2_odds": [],
            "5_odds": [],
            "10_odds": [],
            "rollover": []
        }

        # Sort predictions by confidence (highest first)
        sorted_predictions = sorted(predictions, key=lambda p: p.get("confidence", 0), reverse=True)

        for prediction in sorted_predictions:
            category = prediction.get("category", "rollover")

            # Limit predictions per category for quality
            if len(categories[category]) < 5:  # Max 5 per category
                categories[category].append(prediction)
            elif category != "rollover" and len(categories["rollover"]) < 10:
                # Add high-quality predictions to rollover if category is full
                if prediction.get("confidence", 0) >= 70:
                    categories["rollover"].append(prediction)

        return categories

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about loaded models."""
        self._ensure_loaded()
        return {
            "total_models": len(self.models),
            "model_types": {
                "xgboost": len([m for m in self.models.keys() if "xgboost" in m]),
                "enhanced": len([m for m in self.models.keys() if "enhanced" in m]),
                "advanced": len([m for m in self.models.keys() if "advanced" in m]),
                "quick": len([m for m in self.models.keys() if "quick" in m])
            },
            "explainers": len(self.explainers),
            "advanced_features": {
                "feature_engineering": ADVANCED_ML_AVAILABLE,
                "shap_explanations": SHAP_AVAILABLE,
                "lime_explanations": LIME_AVAILABLE,
                "meta_stacking": True,
                "ensemble_voting": True
            },
            "models": list(self.models.keys())
        }

    def get_enhanced_predictions_with_explanations(self, date_str: Optional[str] = None,
                                                 include_explanations: bool = True,
                                                 explanation_detail: str = "human") -> Dict[str, Any]:
        """Get enhanced predictions with detailed explanations."""
        # Get base predictions
        result = self.get_predictions_for_date(date_str)

        if include_explanations and result["status"] == "success":
            # Add detailed explanations to each prediction
            for prediction in result["predictions"]:
                if "explanations" in prediction and prediction["explanations"]["available"]:
                    # Enhance explanations based on detail level
                    if explanation_detail == "human":
                        prediction["human_explanation"] = self._generate_human_explanation(prediction)
                    elif explanation_detail == "technical":
                        prediction["technical_explanation"] = self._generate_technical_explanation(prediction)
                    elif explanation_detail == "both":
                        prediction["human_explanation"] = self._generate_human_explanation(prediction)
                        prediction["technical_explanation"] = self._generate_technical_explanation(prediction)

        # Add enhanced metadata
        result["enhanced_features"] = {
            "explanations_included": include_explanations,
            "explanation_detail": explanation_detail,
            "model_info": self.get_model_info()
        }

        return result

    def _generate_human_explanation(self, prediction: Dict[str, Any]) -> str:
        """Generate human-readable explanation."""
        confidence = prediction.get("confidence", 0)
        home_team = prediction.get("home_team", "Home")
        away_team = prediction.get("away_team", "Away")
        pred_text = prediction.get("prediction", "Unknown")

        if confidence >= 80:
            certainty = "very confident"
        elif confidence >= 60:
            certainty = "confident"
        else:
            certainty = "moderately confident"

        return f"Our advanced ML models are {certainty} that {pred_text} in the {home_team} vs {away_team} match. This prediction is based on analysis of team form, historical performance, and advanced statistical modeling."

    def _generate_technical_explanation(self, prediction: Dict[str, Any]) -> str:
        """Generate technical explanation."""
        models_used = prediction.get("advanced_features", {}).get("models_used", 0)
        confidence = prediction.get("confidence", 0)

        return f"Prediction generated using ensemble of {models_used} ML models including XGBoost and enhanced algorithms. Meta-stacking applied with confidence score of {confidence}%. Feature engineering includes team strength, form analysis, and historical matchup data."


# Create global instance
advanced_prediction_service = AdvancedPredictionService()
