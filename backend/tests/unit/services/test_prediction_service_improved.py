"""
Test Prediction Service Improved

This module contains tests for the improved prediction service.
"""

import os
import sys
import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import the app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from app.services.prediction_service_improved import PredictionService

class TestPredictionService:
    """Tests for the PredictionService class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.service = PredictionService()
    
    @patch("app.services.prediction_service_improved.load_json_file")
    @patch("app.services.prediction_service_improved.api_football_client")
    @patch("app.services.prediction_service_improved.improved_ensemble_model")
    def test_get_predictions_for_date_cached(self, mock_model, mock_api_client, mock_load_json_file):
        """Test getting predictions from cache."""
        # Mock cached predictions
        mock_load_json_file.return_value = {
            "status": "success",
            "date": "2023-05-01",
            "predictions": [{"fixture": {}, "predictions": []}],
            "categories": {}
        }
        
        # Get predictions
        predictions = self.service.get_predictions_for_date("2023-05-01")
        
        # Check predictions
        assert predictions["status"] == "success"
        assert predictions["date"] == "2023-05-01"
        assert "predictions" in predictions
        assert "categories" in predictions
        
        # Check API client was not called
        mock_api_client.get_fixtures_improved.assert_not_called()
        
        # Check model was not called
        mock_model.predict.assert_not_called()
    
    @patch("app.services.prediction_service_improved.load_json_file")
    @patch("app.services.prediction_service_improved.save_json_file")
    @patch("app.services.prediction_service_improved.api_football_client")
    @patch("app.services.prediction_service_improved.improved_ensemble_model")
    def test_get_predictions_for_date_no_fixtures(self, mock_model, mock_api_client, mock_save_json_file, mock_load_json_file):
        """Test getting predictions with no fixtures."""
        # Mock empty cache
        mock_load_json_file.return_value = None
        
        # Mock API client
        mock_api_client.get_fixtures_improved.return_value = {
            "status": "success",
            "response": []
        }
        
        # Get predictions
        predictions = self.service.get_predictions_for_date("2023-05-01")
        
        # Check predictions
        assert predictions["status"] == "success"
        assert predictions["date"] == "2023-05-01"
        assert predictions["predictions"] == []
        assert predictions["categories"] == {}
        
        # Check API client was called
        mock_api_client.get_fixtures_improved.assert_called_once_with(date="2023-05-01")
        
        # Check model was not called
        mock_model.predict.assert_not_called()
        
        # Check predictions were saved
        mock_save_json_file.assert_called_once()
    
    @patch("app.services.prediction_service_improved.load_json_file")
    @patch("app.services.prediction_service_improved.save_json_file")
    @patch("app.services.prediction_service_improved.api_football_client")
    @patch("app.services.prediction_service_improved.improved_ensemble_model")
    @patch("app.services.prediction_service_improved.PredictionService._get_historical_data")
    def test_get_predictions_for_date_with_fixtures(self, mock_get_historical_data, mock_model, mock_api_client, mock_save_json_file, mock_load_json_file):
        """Test getting predictions with fixtures."""
        # Mock empty cache
        mock_load_json_file.return_value = None
        
        # Mock historical data
        mock_get_historical_data.return_value = pd.DataFrame()
        
        # Mock API client
        mock_api_client.get_fixtures_improved.return_value = {
            "status": "success",
            "response": [
                {
                    "fixture": {
                        "id": 12345,
                        "date": "2023-05-01T15:00:00+00:00",
                        "status": {"short": "NS"}
                    },
                    "league": {
                        "name": "Premier League"
                    },
                    "teams": {
                        "home": {"name": "Manchester United"},
                        "away": {"name": "Liverpool"}
                    }
                }
            ]
        }
        
        # Mock model
        mock_model.predict.return_value = {
            "status": "success",
            "predictions": [
                {
                    "prediction_type": "Match Result",
                    "prediction": "Home Win",
                    "odds": 2.1,
                    "confidence": 65.5,
                    "explanation": "Home team win predicted with 65.5% confidence"
                }
            ]
        }
        
        # Get predictions
        predictions = self.service.get_predictions_for_date("2023-05-01")
        
        # Check predictions
        assert predictions["status"] == "success"
        assert predictions["date"] == "2023-05-01"
        assert len(predictions["predictions"]) == 1
        assert "categories" in predictions
        
        # Check API client was called
        mock_api_client.get_fixtures_improved.assert_called_once_with(date="2023-05-01")
        
        # Check model was called
        mock_model.predict.assert_called_once()
        
        # Check predictions were saved
        mock_save_json_file.assert_called_once()
    
    def test_categorize_predictions(self):
        """Test categorizing predictions."""
        # Create sample predictions
        predictions = [
            {
                "fixture": {
                    "fixture_id": 12345,
                    "date": "2023-05-01T15:00:00+00:00",
                    "league": "Premier League",
                    "home_team": "Manchester United",
                    "away_team": "Liverpool"
                },
                "predictions": [
                    {
                        "prediction_type": "Match Result",
                        "prediction": "Home Win",
                        "odds": 2.1,
                        "confidence": 65.5,
                        "explanation": "Home team win predicted with 65.5% confidence"
                    }
                ]
            },
            {
                "fixture": {
                    "fixture_id": 12346,
                    "date": "2023-05-01T15:00:00+00:00",
                    "league": "Premier League",
                    "home_team": "Arsenal",
                    "away_team": "Chelsea"
                },
                "predictions": [
                    {
                        "prediction_type": "Match Result",
                        "prediction": "Away Win",
                        "odds": 3.5,
                        "confidence": 55.5,
                        "explanation": "Away team win predicted with 55.5% confidence"
                    }
                ]
            },
            {
                "fixture": {
                    "fixture_id": 12347,
                    "date": "2023-05-01T15:00:00+00:00",
                    "league": "Premier League",
                    "home_team": "Manchester City",
                    "away_team": "Tottenham"
                },
                "predictions": [
                    {
                        "prediction_type": "Match Result",
                        "prediction": "Home Win",
                        "odds": 1.5,
                        "confidence": 75.5,
                        "explanation": "Home team win predicted with 75.5% confidence"
                    }
                ]
            }
        ]
        
        # Categorize predictions
        categories = self.service._categorize_predictions(predictions)
        
        # Check categories
        assert "2_odds" in categories
        assert "5_odds" in categories
        assert "10_odds" in categories
        assert "rollover" in categories
        assert "rollover_combinations" in categories
    
    def test_generate_rollover_combinations(self):
        """Test generating rollover combinations."""
        # Create sample rollover predictions
        rollover_predictions = [
            {
                "fixture": {"fixture_id": 1},
                "prediction": {"odds": 1.5, "confidence": 80.0}
            },
            {
                "fixture": {"fixture_id": 2},
                "prediction": {"odds": 1.6, "confidence": 75.0}
            },
            {
                "fixture": {"fixture_id": 3},
                "prediction": {"odds": 1.7, "confidence": 70.0}
            }
        ]
        
        # Generate combinations
        combinations = self.service._generate_rollover_combinations(rollover_predictions, 5.0)
        
        # Check combinations
        assert len(combinations) > 0
        assert "predictions" in combinations[0]
        assert "combined_odds" in combinations[0]
        assert "combined_confidence" in combinations[0]
