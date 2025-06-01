"""
Test Enhanced Prediction Service

This module contains comprehensive tests for the enhanced prediction service.
"""

import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import patch, MagicMock, Mock
import sys
import os

# Add the parent directory to the path so we can import the app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from services.enhanced_prediction_service import EnhancedPredictionService


class TestEnhancedPredictionService:
    """Tests for the EnhancedPredictionService class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        with patch('services.enhanced_prediction_service.AdvancedFootballFeatureEngineer'), \
             patch('services.enhanced_prediction_service.FootballDataClient'), \
             patch('services.enhanced_prediction_service.meta_stacker'), \
             patch('services.enhanced_prediction_service.model_explainer'):
            self.service = EnhancedPredictionService()
    
    @patch("services.enhanced_prediction_service.EnhancedPredictionService._fetch_fixtures")
    def test_get_enhanced_predictions_no_fixtures(self, mock_fetch_fixtures):
        """Test getting enhanced predictions with no fixtures."""
        # Mock no fixtures
        mock_fetch_fixtures.return_value = []
        
        # Get predictions
        predictions = self.service.get_enhanced_predictions("2023-05-01")
        
        # Check predictions
        assert predictions["status"] == "success"
        assert predictions["date"] == "2023-05-01"
        assert predictions["predictions"] == []
        assert "summary" in predictions
        assert predictions["message"] == "No fixtures found for this date"
        
        # Check fixtures were fetched
        mock_fetch_fixtures.assert_called_once_with("2023-05-01")
    
    @patch("services.enhanced_prediction_service.EnhancedPredictionService._fetch_fixtures")
    @patch("services.enhanced_prediction_service.EnhancedPredictionService._predict_fixture")
    def test_get_enhanced_predictions_with_fixtures(self, mock_predict_fixture, mock_fetch_fixtures):
        """Test getting enhanced predictions with fixtures."""
        # Mock fixtures
        mock_fixtures = [
            {
                "id": 12345,
                "utcDate": "2023-05-01T15:00:00Z",
                "homeTeam": {"name": "Manchester United"},
                "awayTeam": {"name": "Liverpool"},
                "competition": {"name": "Premier League"},
                "status": "SCHEDULED"
            }
        ]
        mock_fetch_fixtures.return_value = mock_fixtures
        
        # Mock prediction result
        mock_prediction_result = {
            "fixture": {
                "id": 12345,
                "date": "2023-05-01T15:00:00Z",
                "home_team": "Manchester United",
                "away_team": "Liverpool",
                "competition": "Premier League",
                "status": "SCHEDULED"
            },
            "predictions": {
                "match_result": {
                    "prediction": "Home Win",
                    "confidence": 75.5,
                    "probabilities": [0.755, 0.145, 0.1],
                    "method": "meta_stacking"
                }
            },
            "timestamp": "2023-05-01T12:00:00"
        }
        mock_predict_fixture.return_value = mock_prediction_result
        
        # Get predictions
        predictions = self.service.get_enhanced_predictions("2023-05-01", include_explanations=True)
        
        # Check predictions
        assert predictions["status"] == "success"
        assert predictions["date"] == "2023-05-01"
        assert len(predictions["predictions"]) == 1
        assert "summary" in predictions
        assert predictions["explanations_included"] is True
        
        # Check fixtures were fetched
        mock_fetch_fixtures.assert_called_once_with("2023-05-01")
        
        # Check prediction was made
        mock_predict_fixture.assert_called_once()
    
    def test_extract_fixture_info(self):
        """Test extracting fixture information."""
        fixture = {
            "id": 12345,
            "utcDate": "2023-05-01T15:00:00Z",
            "homeTeam": {"name": "Manchester United"},
            "awayTeam": {"name": "Liverpool"},
            "competition": {"name": "Premier League"},
            "status": "SCHEDULED"
        }
        
        fixture_info = self.service._extract_fixture_info(fixture)
        
        assert fixture_info["id"] == 12345
        assert fixture_info["date"] == "2023-05-01T15:00:00Z"
        assert fixture_info["home_team"] == "Manchester United"
        assert fixture_info["away_team"] == "Liverpool"
        assert fixture_info["competition"] == "Premier League"
        assert fixture_info["status"] == "SCHEDULED"
    
    def test_generate_basic_features(self):
        """Test generating basic features."""
        fixture = {
            "id": 12345,
            "homeTeam": {"name": "Manchester United"},
            "awayTeam": {"name": "Liverpool"}
        }
        
        features = self.service._generate_basic_features(fixture)
        
        assert isinstance(features, pd.DataFrame)
        assert len(features) == 1
        assert "home_form" in features.columns
        assert "away_form" in features.columns
        assert "home_attack" in features.columns
        assert "home_defense" in features.columns
        assert "away_attack" in features.columns
        assert "away_defense" in features.columns
    
    @patch("services.enhanced_prediction_service.EnhancedPredictionService._fetch_fixtures")
    def test_get_enhanced_predictions_api_error(self, mock_fetch_fixtures):
        """Test handling API errors."""
        # Mock API error
        mock_fetch_fixtures.side_effect = Exception("API Error")
        
        # Get predictions
        predictions = self.service.get_enhanced_predictions("2023-05-01")
        
        # Check error handling
        assert predictions["status"] == "error"
        assert "API Error" in predictions["message"]
        assert predictions["date"] == "2023-05-01"
    
    def test_generate_prediction_summary_empty(self):
        """Test generating summary with no predictions."""
        summary = self.service._generate_prediction_summary([])
        
        assert summary == {}
    
    def test_generate_prediction_summary_with_predictions(self):
        """Test generating summary with predictions."""
        predictions = [
            {
                "predictions": {
                    "match_result": {"confidence": 75.5},
                    "over_under": {"confidence": 65.0}
                }
            },
            {
                "predictions": {
                    "match_result": {"confidence": 80.0},
                    "btts": {"confidence": 55.0}
                }
            }
        ]
        
        summary = self.service._generate_prediction_summary(predictions)
        
        assert summary["total_fixtures"] == 2
        assert summary["high_confidence_predictions"] == 2  # 75.5 and 80.0 > 70
        assert summary["average_confidence"] > 0
        assert "prediction_types_available" in summary
    
    @patch("services.enhanced_prediction_service.meta_stacker")
    @patch("services.enhanced_prediction_service.model_explainer")
    def test_predict_fixture_with_meta_stacking(self, mock_explainer, mock_meta_stacker):
        """Test predicting fixture with meta-stacking."""
        # Mock meta-stacker
        mock_meta_stacker.predict_with_stacking.return_value = {
            "status": "success",
            "predictions": ["Home Win"],
            "confidence_scores": [75.5],
            "calibrated_probabilities": [[0.755, 0.145, 0.1]],
            "base_models_used": ["xgboost", "lightgbm"]
        }
        
        # Mock explainer
        mock_explainer.explain_prediction.return_value = {
            "status": "success",
            "feature_importance": {"home_form": 0.3, "away_form": 0.2}
        }
        mock_explainer.generate_human_readable_explanation.return_value = "Home team has better form"
        
        # Set service as initialized
        self.service.models_initialized = True
        self.service.explainers_initialized = True
        
        fixture = {
            "id": 12345,
            "utcDate": "2023-05-01T15:00:00Z",
            "homeTeam": {"name": "Manchester United"},
            "awayTeam": {"name": "Liverpool"},
            "competition": {"name": "Premier League"},
            "status": "SCHEDULED"
        }
        
        with patch.object(self.service, '_generate_features') as mock_generate_features:
            mock_generate_features.return_value = pd.DataFrame({"feature1": [1.0]})
            
            result = self.service._predict_fixture(fixture, True, True)
        
        assert result is not None
        assert "fixture" in result
        assert "predictions" in result
        assert "explanations" in result
        assert result["fixture"]["id"] == 12345


class TestEnhancedPredictionServiceIntegration:
    """Integration tests for the enhanced prediction service."""
    
    def test_service_initialization(self):
        """Test that the service can be initialized without errors."""
        with patch('services.enhanced_prediction_service.AdvancedFootballFeatureEngineer'), \
             patch('services.enhanced_prediction_service.FootballDataClient'), \
             patch('services.enhanced_prediction_service.meta_stacker'), \
             patch('services.enhanced_prediction_service.model_explainer'):
            service = EnhancedPredictionService()
            assert service is not None
            assert hasattr(service, 'feature_engineer')
            assert hasattr(service, 'api_client')
    
    def test_get_feature_names(self):
        """Test getting feature names."""
        with patch('services.enhanced_prediction_service.AdvancedFootballFeatureEngineer'), \
             patch('services.enhanced_prediction_service.FootballDataClient'), \
             patch('services.enhanced_prediction_service.meta_stacker'), \
             patch('services.enhanced_prediction_service.model_explainer'):
            service = EnhancedPredictionService()
            feature_names = service._get_feature_names()
            
            assert isinstance(feature_names, list)
            assert len(feature_names) > 0
            assert "home_form" in feature_names
            assert "away_form" in feature_names


if __name__ == "__main__":
    pytest.main([__file__])
