#!/usr/bin/env python3
"""
Performance Analytics Service - Advanced ML Model Analytics

This service provides:
1. Real-time model performance tracking
2. Trend analysis over time
3. Best model identification
4. Performance predictions
5. Automated model selection recommendations
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import json
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from models.training_models import PredictionAccuracy, CachedPrediction
try:
    from database import get_db_session
except ImportError:
    # Fallback for database session
    def get_db_session():
        return None

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PerformanceAnalyticsService:
    """Advanced analytics for ML model performance."""
    
    def __init__(self):
        """Initialize the performance analytics service."""
        self.db_session = get_db_session()
        # Import here to avoid circular imports
        try:
            from services.result_correlation_service import result_correlation_service
            self.correlation_service = result_correlation_service
        except ImportError:
            self.correlation_service = None
        
        # Performance thresholds
        self.EXCELLENT_ACCURACY = 0.90
        self.GOOD_ACCURACY = 0.80
        self.POOR_ACCURACY = 0.60
        
        logger.info("✅ Performance Analytics Service initialized")
    
    def get_comprehensive_dashboard(self, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive performance dashboard."""
        try:
            logger.info(f"📊 Generating comprehensive dashboard for last {days} days")
            
            # Get basic analytics
            analytics = self.correlation_service.get_model_performance_analytics(days)
            
            if analytics.get('status') != 'success':
                return analytics
            
            # Get best models
            best_models = self.correlation_service.get_best_models_over_time(days)
            
            # Get trend analysis
            trends = self._analyze_performance_trends(days)
            
            # Get category performance
            category_performance = self._analyze_category_performance(days)
            
            # Get league performance
            league_performance = self._analyze_league_performance(days)
            
            # Get recommendations
            recommendations = self._generate_recommendations(analytics, best_models, trends)
            
            return {
                "status": "success",
                "generated_at": datetime.now().isoformat(),
                "period_days": days,
                "overview": {
                    "total_predictions": analytics.get('total_predictions', 0),
                    "overall_accuracy": analytics.get('analytics', {}).get('overall_accuracy', 0),
                    "avg_confidence": analytics.get('analytics', {}).get('avg_confidence', 0),
                    "total_models": analytics.get('analytics', {}).get('total_models_tracked', 0),
                    "best_model": analytics.get('analytics', {}).get('best_model')
                },
                "model_performance": analytics.get('model_performance', {}),
                "best_models": best_models.get('weighted_rankings', [])[:5],
                "trends": trends,
                "category_performance": category_performance,
                "league_performance": league_performance,
                "recommendations": recommendations
            }
            
        except Exception as e:
            logger.error(f"❌ Error generating dashboard: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _analyze_performance_trends(self, days: int) -> Dict[str, Any]:
        """Analyze performance trends over time."""
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Get daily accuracy data
            accuracy_records = self.db_session.query(PredictionAccuracy).filter(
                PredictionAccuracy.match_date >= start_date
            ).order_by(PredictionAccuracy.match_date).all()
            
            if not accuracy_records:
                return {"status": "no_data"}
            
            # Group by date
            daily_stats = defaultdict(lambda: {'total': 0, 'correct': 0, 'confidence_sum': 0})
            
            for record in accuracy_records:
                date = record.match_date
                daily_stats[date]['total'] += 1
                if record.is_correct:
                    daily_stats[date]['correct'] += 1
                daily_stats[date]['confidence_sum'] += record.confidence
            
            # Calculate daily accuracies
            dates = []
            accuracies = []
            confidences = []
            
            for date in sorted(daily_stats.keys()):
                stats = daily_stats[date]
                accuracy = stats['correct'] / stats['total'] if stats['total'] > 0 else 0
                avg_confidence = stats['confidence_sum'] / stats['total'] if stats['total'] > 0 else 0
                
                dates.append(date)
                accuracies.append(accuracy)
                confidences.append(avg_confidence)
            
            # Calculate trends
            if len(accuracies) >= 7:  # Need at least a week of data
                recent_accuracy = np.mean(accuracies[-7:])  # Last 7 days
                previous_accuracy = np.mean(accuracies[-14:-7]) if len(accuracies) >= 14 else np.mean(accuracies[:-7])
                
                accuracy_trend = "improving" if recent_accuracy > previous_accuracy else "declining"
                accuracy_change = recent_accuracy - previous_accuracy
            else:
                accuracy_trend = "insufficient_data"
                accuracy_change = 0
            
            return {
                "status": "success",
                "daily_data": {
                    "dates": dates,
                    "accuracies": accuracies,
                    "confidences": confidences
                },
                "trend_analysis": {
                    "accuracy_trend": accuracy_trend,
                    "accuracy_change": accuracy_change,
                    "recent_7_day_avg": np.mean(accuracies[-7:]) if len(accuracies) >= 7 else 0,
                    "overall_avg": np.mean(accuracies),
                    "best_day": dates[np.argmax(accuracies)] if accuracies else None,
                    "worst_day": dates[np.argmin(accuracies)] if accuracies else None
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Error analyzing trends: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _analyze_category_performance(self, days: int) -> Dict[str, Any]:
        """Analyze performance by prediction category (2_odds, 5_odds, etc.)."""
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Get predictions with categories
            predictions = self.db_session.query(CachedPrediction).filter(
                CachedPrediction.prediction_date >= start_date
            ).all()
            
            # Get accuracy records
            accuracy_records = self.db_session.query(PredictionAccuracy).filter(
                PredictionAccuracy.match_date >= start_date
            ).all()
            
            # Create mapping of predictions to accuracy
            accuracy_map = {}
            for record in accuracy_records:
                key = f"{record.home_team}_{record.away_team}_{record.match_date}"
                accuracy_map[key] = record.is_correct
            
            # Analyze by category
            category_stats = defaultdict(lambda: {'total': 0, 'correct': 0, 'accuracy': 0})
            
            for pred in predictions:
                key = f"{pred.home_team}_{pred.away_team}_{pred.prediction_date}"
                is_correct = accuracy_map.get(key, False)
                
                category_stats[pred.category]['total'] += 1
                if is_correct:
                    category_stats[pred.category]['correct'] += 1
            
            # Calculate accuracies
            for category, stats in category_stats.items():
                if stats['total'] > 0:
                    stats['accuracy'] = stats['correct'] / stats['total']
            
            return {
                "status": "success",
                "category_performance": dict(category_stats),
                "best_category": max(category_stats.items(), key=lambda x: x[1]['accuracy'])[0] if category_stats else None,
                "worst_category": min(category_stats.items(), key=lambda x: x[1]['accuracy'])[0] if category_stats else None
            }
            
        except Exception as e:
            logger.error(f"❌ Error analyzing category performance: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _analyze_league_performance(self, days: int) -> Dict[str, Any]:
        """Analyze performance by league."""
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            accuracy_records = self.db_session.query(PredictionAccuracy).filter(
                PredictionAccuracy.match_date >= start_date
            ).all()
            
            league_stats = defaultdict(lambda: {'total': 0, 'correct': 0, 'accuracy': 0})
            
            for record in accuracy_records:
                league = record.league
                league_stats[league]['total'] += 1
                if record.is_correct:
                    league_stats[league]['correct'] += 1
            
            # Calculate accuracies
            for league, stats in league_stats.items():
                if stats['total'] > 0:
                    stats['accuracy'] = stats['correct'] / stats['total']
            
            return {
                "status": "success",
                "league_performance": dict(league_stats),
                "best_league": max(league_stats.items(), key=lambda x: x[1]['accuracy'])[0] if league_stats else None,
                "worst_league": min(league_stats.items(), key=lambda x: x[1]['accuracy'])[0] if league_stats else None
            }
            
        except Exception as e:
            logger.error(f"❌ Error analyzing league performance: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _generate_recommendations(self, analytics: Dict, best_models: Dict, trends: Dict) -> Dict[str, Any]:
        """Generate actionable recommendations based on performance data."""
        recommendations = {
            "model_selection": [],
            "training_recommendations": [],
            "system_optimizations": [],
            "alerts": []
        }
        
        try:
            overall_accuracy = analytics.get('analytics', {}).get('overall_accuracy', 0)
            
            # Model selection recommendations
            if best_models.get('status') == 'success':
                top_models = best_models.get('weighted_rankings', [])[:3]
                if top_models:
                    recommendations["model_selection"].append({
                        "type": "use_top_models",
                        "message": f"Focus on top 3 models: {', '.join([m[0] for m in top_models])}",
                        "models": top_models
                    })
            
            # Training recommendations
            if overall_accuracy < self.POOR_ACCURACY:
                recommendations["training_recommendations"].append({
                    "type": "urgent_retraining",
                    "message": f"Overall accuracy ({overall_accuracy:.1%}) is below threshold. Urgent retraining needed.",
                    "priority": "high"
                })
            elif overall_accuracy < self.GOOD_ACCURACY:
                recommendations["training_recommendations"].append({
                    "type": "scheduled_retraining",
                    "message": f"Accuracy ({overall_accuracy:.1%}) could be improved. Schedule retraining.",
                    "priority": "medium"
                })
            
            # Trend-based recommendations
            if trends.get('status') == 'success':
                trend_analysis = trends.get('trend_analysis', {})
                if trend_analysis.get('accuracy_trend') == 'declining':
                    recommendations["alerts"].append({
                        "type": "declining_performance",
                        "message": f"Performance declining by {trend_analysis.get('accuracy_change', 0):.1%}",
                        "severity": "warning"
                    })
            
            # System optimizations
            total_models = analytics.get('analytics', {}).get('total_models_tracked', 0)
            if total_models > 20:
                recommendations["system_optimizations"].append({
                    "type": "model_pruning",
                    "message": f"Consider pruning {total_models} models to focus on top performers",
                    "action": "reduce_model_count"
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"❌ Error generating recommendations: {str(e)}")
            return recommendations
    
    def get_model_comparison(self, model_names: List[str], days: int = 30) -> Dict[str, Any]:
        """Compare specific models head-to-head."""
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # This would require model-specific tracking
            # For now, return placeholder structure
            
            comparison = {
                "status": "success",
                "models_compared": model_names,
                "period_days": days,
                "comparison_data": {},
                "winner": None,
                "recommendation": "Implement model-specific tracking for detailed comparison"
            }
            
            return comparison
            
        except Exception as e:
            logger.error(f"❌ Error comparing models: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def predict_future_performance(self, days_ahead: int = 7) -> Dict[str, Any]:
        """Predict future performance based on trends."""
        try:
            # Get recent trends
            trends = self._analyze_performance_trends(30)
            
            if trends.get('status') != 'success':
                return trends
            
            daily_data = trends.get('daily_data', {})
            accuracies = daily_data.get('accuracies', [])
            
            if len(accuracies) < 7:
                return {"status": "insufficient_data", "message": "Need at least 7 days of data"}
            
            # Simple linear trend prediction
            recent_trend = np.polyfit(range(len(accuracies[-14:])), accuracies[-14:], 1)[0]
            current_accuracy = accuracies[-1]
            
            predicted_accuracy = current_accuracy + (recent_trend * days_ahead)
            predicted_accuracy = max(0, min(1, predicted_accuracy))  # Clamp between 0 and 1
            
            confidence = "high" if abs(recent_trend) < 0.01 else "medium" if abs(recent_trend) < 0.05 else "low"
            
            return {
                "status": "success",
                "days_ahead": days_ahead,
                "current_accuracy": current_accuracy,
                "predicted_accuracy": predicted_accuracy,
                "trend_slope": recent_trend,
                "confidence": confidence,
                "recommendation": self._get_prediction_recommendation(predicted_accuracy, recent_trend)
            }
            
        except Exception as e:
            logger.error(f"❌ Error predicting performance: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _get_prediction_recommendation(self, predicted_accuracy: float, trend: float) -> str:
        """Get recommendation based on predicted performance."""
        if predicted_accuracy < self.POOR_ACCURACY:
            return "Immediate intervention required - predicted performance is poor"
        elif predicted_accuracy < self.GOOD_ACCURACY:
            return "Monitor closely - performance may need attention"
        elif trend < -0.02:
            return "Declining trend detected - consider proactive measures"
        else:
            return "Performance looks stable - continue current approach"

# Create global instance
performance_analytics_service = PerformanceAnalyticsService()
