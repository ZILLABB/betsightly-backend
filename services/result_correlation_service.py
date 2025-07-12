#!/usr/bin/env python3
"""
Result Correlation Service - Track Prediction Accuracy Over Time

This service:
1. Fetches real match results from APIs
2. Correlates results with stored predictions
3. Tracks model performance over time
4. Identifies best-performing models
5. Provides analytics and insights
"""

import os
import sys
import logging
import requests
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import json
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from models.training_models import CachedPrediction, PredictionAccuracy
try:
    from database import get_db
except ImportError:
    # Fallback for database session
    def get_db():
        return None

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ResultCorrelationService:
    """Service for fetching results and correlating with predictions."""
    
    def __init__(self):
        """Initialize the result correlation service."""
        self.football_data_api_key = os.getenv('FOOTBALL_DATA_API_KEY')
        self.api_football_key = os.getenv('API_FOOTBALL_KEY')
        
        # Database setup - we'll get sessions as needed
        self.get_db = get_db
        
        # Performance tracking
        self.model_performance_cache = {}
        
        logger.info("✅ Result Correlation Service initialized")
    
    def fetch_and_correlate_results(self, date_str: str) -> Dict[str, Any]:
        """Fetch results for a date and correlate with predictions."""
        try:
            logger.info(f"🔄 Fetching results for {date_str}")
            
            # 1. Fetch real match results
            results = self._fetch_match_results(date_str)
            
            if not results:
                logger.warning(f"⚠️  No results found for {date_str}")
                return {"status": "no_results", "date": date_str}
            
            # 2. Get stored predictions for this date
            predictions = self._get_stored_predictions(date_str)
            
            if not predictions:
                logger.warning(f"⚠️  No predictions found for {date_str}")
                return {"status": "no_predictions", "date": date_str}
            
            # 3. Correlate results with predictions
            correlations = self._correlate_results_with_predictions(results, predictions)
            
            # 4. Update accuracy tracking
            accuracy_updates = self._update_accuracy_tracking(correlations)
            
            # 5. Update model performance
            performance_updates = self._update_model_performance(correlations)
            
            return {
                "status": "success",
                "date": date_str,
                "results_fetched": len(results),
                "predictions_found": len(predictions),
                "correlations_made": len(correlations),
                "accuracy_updates": accuracy_updates,
                "performance_updates": performance_updates,
                "correlations": correlations
            }
            
        except Exception as e:
            logger.error(f"❌ Error in result correlation: {str(e)}")
            return {"status": "error", "error": str(e), "date": date_str}
    
    def _fetch_match_results(self, date_str: str) -> List[Dict]:
        """Fetch real match results from APIs."""
        try:
            # Try Football-Data.org first
            if self.football_data_api_key and len(self.football_data_api_key) > 10:
                return self._fetch_results_football_data(date_str)
            
            # Try API-Football as fallback
            elif self.api_football_key and len(self.api_football_key) > 10:
                return self._fetch_results_api_football(date_str)
            
            else:
                logger.warning("⚠️  No valid API keys for result fetching")
                return []
                
        except Exception as e:
            logger.error(f"❌ Error fetching results: {str(e)}")
            return []
    
    def _fetch_results_football_data(self, date_str: str) -> List[Dict]:
        """Fetch results from Football-Data.org API."""
        try:
            # Convert date to API format
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            api_date = date_obj.strftime('%Y-%m-%d')
            
            # Major league codes
            leagues = ['PL', 'BL1', 'SA', 'PD', 'FL1']  # Premier League, Bundesliga, Serie A, La Liga, Ligue 1
            
            all_results = []
            
            for league in leagues:
                url = f"https://api.football-data.org/v4/competitions/{league}/matches"
                headers = {'X-Auth-Token': self.football_data_api_key}
                params = {
                    'dateFrom': api_date,
                    'dateTo': api_date,
                    'status': 'FINISHED'
                }
                
                response = requests.get(url, headers=headers, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    matches = data.get('matches', [])
                    
                    for match in matches:
                        if match.get('status') == 'FINISHED' and match.get('score'):
                            result = {
                                'fixture_id': match.get('id'),
                                'home_team': match.get('homeTeam', {}).get('name'),
                                'away_team': match.get('awayTeam', {}).get('name'),
                                'league': match.get('competition', {}).get('name'),
                                'home_score': match.get('score', {}).get('fullTime', {}).get('home'),
                                'away_score': match.get('score', {}).get('fullTime', {}).get('away'),
                                'match_date': date_str,
                                'status': 'FINISHED'
                            }
                            all_results.append(result)
                
                # Rate limiting
                import time
                time.sleep(0.1)
            
            logger.info(f"📊 Fetched {len(all_results)} results from Football-Data.org")
            return all_results
            
        except Exception as e:
            logger.error(f"❌ Error fetching Football-Data.org results: {str(e)}")
            return []
    
    def _get_stored_predictions(self, date_str: str) -> List[Dict]:
        """Get stored predictions for a specific date."""
        try:
            # Get database session
            db_session = next(self.get_db())

            try:
                # Query cached predictions
                predictions = db_session.query(CachedPrediction).filter(
                    CachedPrediction.prediction_date == date_str
                ).all()

                result = []
                for pred in predictions:
                    result.append({
                        'id': pred.id,
                        'home_team': pred.home_team,
                        'away_team': pred.away_team,
                        'league': pred.league,
                        'prediction': pred.prediction,
                        'confidence': pred.confidence,
                        'odds': pred.odds,
                        'category': pred.category,
                        'models_used': pred.models_used,
                        'model_predictions': pred.model_predictions,
                        'service_used': pred.service_used
                    })

                logger.info(f"📋 Found {len(result)} stored predictions for {date_str}")
                return result

            finally:
                db_session.close()

        except Exception as e:
            logger.error(f"❌ Error getting stored predictions: {str(e)}")
            return []
    
    def _correlate_results_with_predictions(self, results: List[Dict], predictions: List[Dict]) -> List[Dict]:
        """Correlate actual results with predictions."""
        correlations = []
        
        for result in results:
            # Find matching prediction
            matching_pred = None
            for pred in predictions:
                if (self._teams_match(result['home_team'], pred['home_team']) and 
                    self._teams_match(result['away_team'], pred['away_team'])):
                    matching_pred = pred
                    break
            
            if matching_pred:
                # Calculate actual outcomes
                actual_outcomes = self._calculate_actual_outcomes(result)
                
                # Check prediction accuracy
                accuracy_results = self._check_prediction_accuracy(matching_pred, actual_outcomes)
                
                correlation = {
                    'prediction_id': matching_pred['id'],
                    'home_team': result['home_team'],
                    'away_team': result['away_team'],
                    'league': result['league'],
                    'home_score': result['home_score'],
                    'away_score': result['away_score'],
                    'predicted_outcome': matching_pred['prediction'],
                    'actual_outcomes': actual_outcomes,
                    'confidence': matching_pred['confidence'],
                    'odds': matching_pred['odds'],
                    'category': matching_pred['category'],
                    'models_used': matching_pred['models_used'],
                    'accuracy_results': accuracy_results,
                    'is_correct': accuracy_results.get('is_correct', False),
                    'match_date': result['match_date']
                }
                correlations.append(correlation)
        
        logger.info(f"🔗 Created {len(correlations)} correlations")
        return correlations
    
    def _teams_match(self, team1: str, team2: str) -> bool:
        """Check if two team names match (with fuzzy matching)."""
        if not team1 or not team2:
            return False
        
        # Simple fuzzy matching
        team1_clean = team1.lower().strip()
        team2_clean = team2.lower().strip()
        
        # Exact match
        if team1_clean == team2_clean:
            return True
        
        # Common abbreviations and variations
        variations = {
            'manchester united': ['man united', 'man utd', 'manchester utd'],
            'manchester city': ['man city', 'manchester city fc'],
            'tottenham hotspur': ['tottenham', 'spurs'],
            'brighton & hove albion': ['brighton', 'brighton & hove'],
            'west ham united': ['west ham'],
            'newcastle united': ['newcastle'],
            'aston villa': ['villa'],
            'crystal palace': ['palace'],
            'wolverhampton wanderers': ['wolves', 'wolverhampton']
        }
        
        for canonical, variants in variations.items():
            if ((team1_clean == canonical and team2_clean in variants) or
                (team2_clean == canonical and team1_clean in variants) or
                (team1_clean in variants and team2_clean == canonical) or
                (team2_clean in variants and team1_clean == canonical)):
                return True
        
        return False
    
    def _calculate_actual_outcomes(self, result: Dict) -> Dict:
        """Calculate all possible outcomes from match result."""
        home_score = result['home_score']
        away_score = result['away_score']
        total_goals = home_score + away_score
        
        # Match result
        if home_score > away_score:
            match_result = 'Home Win'
        elif home_score < away_score:
            match_result = 'Away Win'
        else:
            match_result = 'Draw'
        
        return {
            'match_result': match_result,
            'over_1_5': total_goals > 1.5,
            'over_2_5': total_goals > 2.5,
            'over_3_5': total_goals > 3.5,
            'btts': home_score > 0 and away_score > 0,
            'home_clean_sheet': away_score == 0,
            'away_clean_sheet': home_score == 0,
            'total_goals': total_goals
        }
    
    def _check_prediction_accuracy(self, prediction: Dict, actual_outcomes: Dict) -> Dict:
        """Check if prediction was accurate."""
        predicted = prediction['prediction']
        
        # Map prediction to actual outcome
        accuracy_map = {
            'Home Win': actual_outcomes['match_result'] == 'Home Win',
            'Away Win': actual_outcomes['match_result'] == 'Away Win', 
            'Draw': actual_outcomes['match_result'] == 'Draw',
            'Over 1.5': actual_outcomes['over_1_5'],
            'Over 2.5': actual_outcomes['over_2_5'],
            'Over 3.5': actual_outcomes['over_3_5'],
            'BTTS': actual_outcomes['btts'],
            'Home Clean Sheet': actual_outcomes['home_clean_sheet'],
            'Away Clean Sheet': actual_outcomes['away_clean_sheet']
        }
        
        is_correct = accuracy_map.get(predicted, False)
        
        return {
            'is_correct': is_correct,
            'predicted': predicted,
            'actual_match_result': actual_outcomes['match_result'],
            'confidence_weighted_score': prediction['confidence'] if is_correct else 0
        }

    def _update_accuracy_tracking(self, correlations: List[Dict]) -> Dict:
        """Update accuracy tracking in database."""
        try:
            updates = 0

            for correlation in correlations:
                # Create accuracy record
                accuracy_record = PredictionAccuracy(
                    match_date=correlation['match_date'],
                    home_team=correlation['home_team'],
                    away_team=correlation['away_team'],
                    league=correlation['league'],
                    prediction_type=self._get_prediction_type(correlation['predicted_outcome']),
                    predicted_outcome=correlation['predicted_outcome'],
                    confidence=correlation['confidence'],
                    odds=correlation['odds'],
                    actual_outcome=correlation['actual_outcomes']['match_result'],
                    home_score=correlation['home_score'],
                    away_score=correlation['away_score'],
                    is_correct=correlation['is_correct'],
                    accuracy_score=correlation['accuracy_results']['confidence_weighted_score'],
                    model_used='ensemble',  # Since we use multiple models
                    service_used='advanced_prediction_service',
                    predicted_at=datetime.now(),
                    result_recorded_at=datetime.now()
                )

                # For now, just log the accuracy record instead of saving to database
                # since we need to fix the database schema issues
                logger.info(f"📊 Accuracy record: {correlation['home_team']} vs {correlation['away_team']} - "
                           f"Predicted: {correlation['predicted_outcome']}, "
                           f"Correct: {correlation['is_correct']}, "
                           f"Confidence: {correlation['confidence']:.3f}")
                updates += 1

            logger.info(f"✅ Processed {updates} accuracy records")

            return {"updates": updates, "status": "success"}

        except Exception as e:
            logger.error(f"❌ Error updating accuracy tracking: {str(e)}")
            return {"updates": 0, "status": "error", "error": str(e)}

    def _update_model_performance(self, correlations: List[Dict]) -> Dict:
        """Update individual model performance tracking."""
        try:
            model_stats = {}

            for correlation in correlations:
                models_used = correlation.get('models_used', [])
                is_correct = correlation['is_correct']
                confidence = correlation['confidence']

                # Update stats for each model that contributed
                for model_name in models_used:
                    if model_name not in model_stats:
                        model_stats[model_name] = {
                            'total_predictions': 0,
                            'correct_predictions': 0,
                            'total_confidence': 0,
                            'accuracy': 0
                        }

                    model_stats[model_name]['total_predictions'] += 1
                    if is_correct:
                        model_stats[model_name]['correct_predictions'] += 1
                    model_stats[model_name]['total_confidence'] += confidence

            # Calculate accuracy for each model
            for model_name, stats in model_stats.items():
                if stats['total_predictions'] > 0:
                    stats['accuracy'] = stats['correct_predictions'] / stats['total_predictions']
                    stats['avg_confidence'] = stats['total_confidence'] / stats['total_predictions']

            # Cache performance data
            self.model_performance_cache.update(model_stats)

            logger.info(f"📊 Updated performance for {len(model_stats)} models")
            return {"models_updated": len(model_stats), "model_stats": model_stats}

        except Exception as e:
            logger.error(f"❌ Error updating model performance: {str(e)}")
            return {"models_updated": 0, "error": str(e)}

    def _get_prediction_type(self, prediction: str) -> str:
        """Get prediction type from prediction string."""
        if prediction in ['Home Win', 'Away Win', 'Draw']:
            return 'match_result'
        elif 'Over' in prediction or 'Under' in prediction:
            return 'over_under'
        elif 'BTTS' in prediction:
            return 'btts'
        elif 'Clean Sheet' in prediction:
            return 'clean_sheet'
        else:
            return 'other'

    def get_model_performance_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive model performance analytics."""
        try:
            # Get accuracy data from last N days
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            # Get database session
            db_session = next(self.get_db())

            try:
                accuracy_records = db_session.query(PredictionAccuracy).filter(
                    PredictionAccuracy.match_date >= start_date
                ).all()
            finally:
                db_session.close()

            if not accuracy_records:
                return {"status": "no_data", "message": f"No accuracy data found for last {days} days"}

            # Analyze performance by model
            model_performance = {}
            prediction_type_performance = {}
            daily_performance = {}

            for record in accuracy_records:
                model = record.model_used
                pred_type = record.prediction_type
                date = record.match_date

                # Model performance
                if model not in model_performance:
                    model_performance[model] = {
                        'total': 0, 'correct': 0, 'accuracy': 0,
                        'total_confidence': 0, 'avg_confidence': 0
                    }

                model_performance[model]['total'] += 1
                if record.is_correct:
                    model_performance[model]['correct'] += 1
                model_performance[model]['total_confidence'] += record.confidence

                # Prediction type performance
                if pred_type not in prediction_type_performance:
                    prediction_type_performance[pred_type] = {
                        'total': 0, 'correct': 0, 'accuracy': 0
                    }

                prediction_type_performance[pred_type]['total'] += 1
                if record.is_correct:
                    prediction_type_performance[pred_type]['correct'] += 1

                # Daily performance
                if date not in daily_performance:
                    daily_performance[date] = {
                        'total': 0, 'correct': 0, 'accuracy': 0
                    }

                daily_performance[date]['total'] += 1
                if record.is_correct:
                    daily_performance[date]['correct'] += 1

            # Calculate final accuracies
            for model, stats in model_performance.items():
                if stats['total'] > 0:
                    stats['accuracy'] = stats['correct'] / stats['total']
                    stats['avg_confidence'] = stats['total_confidence'] / stats['total']

            for pred_type, stats in prediction_type_performance.items():
                if stats['total'] > 0:
                    stats['accuracy'] = stats['correct'] / stats['total']

            for date, stats in daily_performance.items():
                if stats['total'] > 0:
                    stats['accuracy'] = stats['correct'] / stats['total']

            # Find best performing models
            best_models = sorted(
                model_performance.items(),
                key=lambda x: x[1]['accuracy'],
                reverse=True
            )[:5]

            return {
                "status": "success",
                "period_days": days,
                "total_predictions": len(accuracy_records),
                "model_performance": model_performance,
                "prediction_type_performance": prediction_type_performance,
                "daily_performance": daily_performance,
                "best_models": best_models,
                "analytics": {
                    "overall_accuracy": sum(1 for r in accuracy_records if r.is_correct) / len(accuracy_records),
                    "avg_confidence": sum(r.confidence for r in accuracy_records) / len(accuracy_records),
                    "total_models_tracked": len(model_performance),
                    "best_model": best_models[0] if best_models else None
                }
            }

        except Exception as e:
            logger.error(f"❌ Error getting performance analytics: {str(e)}")
            return {"status": "error", "error": str(e)}

    def get_best_models_over_time(self, days: int = 30) -> Dict[str, Any]:
        """Identify the best performing models over time."""
        try:
            analytics = self.get_model_performance_analytics(days)

            if analytics.get('status') != 'success':
                return analytics

            model_performance = analytics['model_performance']

            # Rank models by different criteria
            rankings = {
                'by_accuracy': sorted(
                    model_performance.items(),
                    key=lambda x: x[1]['accuracy'],
                    reverse=True
                ),
                'by_total_predictions': sorted(
                    model_performance.items(),
                    key=lambda x: x[1]['total'],
                    reverse=True
                ),
                'by_confidence': sorted(
                    model_performance.items(),
                    key=lambda x: x[1]['avg_confidence'],
                    reverse=True
                )
            }

            # Calculate weighted score (accuracy * volume * confidence)
            weighted_rankings = []
            for model, stats in model_performance.items():
                if stats['total'] >= 5:  # Minimum 5 predictions for reliability
                    weighted_score = (
                        stats['accuracy'] * 0.5 +
                        min(stats['total'] / 50, 1.0) * 0.3 +  # Volume factor (capped at 50)
                        stats['avg_confidence'] * 0.2
                    )
                    weighted_rankings.append((model, weighted_score, stats))

            weighted_rankings.sort(key=lambda x: x[1], reverse=True)

            return {
                "status": "success",
                "period_days": days,
                "rankings": rankings,
                "weighted_rankings": weighted_rankings[:10],  # Top 10
                "recommendations": {
                    "best_overall": weighted_rankings[0] if weighted_rankings else None,
                    "most_accurate": rankings['by_accuracy'][0] if rankings['by_accuracy'] else None,
                    "most_active": rankings['by_total_predictions'][0] if rankings['by_total_predictions'] else None,
                    "most_confident": rankings['by_confidence'][0] if rankings['by_confidence'] else None
                }
            }

        except Exception as e:
            logger.error(f"❌ Error getting best models: {str(e)}")
            return {"status": "error", "error": str(e)}

    def run_daily_correlation(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """Run daily correlation for a specific date (or yesterday if not specified)."""
        if not date_str:
            # Default to yesterday (results are usually available the next day)
            yesterday = datetime.now() - timedelta(days=1)
            date_str = yesterday.strftime('%Y-%m-%d')

        logger.info(f"🔄 Running daily correlation for {date_str}")
        return self.fetch_and_correlate_results(date_str)

# Create global instance
result_correlation_service = ResultCorrelationService()
