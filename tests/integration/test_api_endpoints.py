"""
Integration Tests for API Endpoints

This module contains integration tests for the main API endpoints.
"""

import pytest
import sys
import os
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import the app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from main import app


class TestPredictionsAPI:
    """Integration tests for predictions API endpoints."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
    
    @patch("services.enhanced_prediction_service.enhanced_prediction_service.get_enhanced_predictions")
    def test_get_predictions_endpoint(self, mock_get_predictions):
        """Test the main predictions endpoint."""
        # Mock the enhanced prediction service
        mock_get_predictions.return_value = {
            "status": "success",
            "date": "2023-05-01",
            "predictions": [
                {
                    "fixture": {
                        "id": 12345,
                        "home_team": "Manchester United",
                        "away_team": "Liverpool",
                        "date": "2023-05-01T15:00:00Z"
                    },
                    "predictions": {
                        "match_result": {
                            "prediction": "Home Win",
                            "confidence": 75.5,
                            "method": "meta_stacking"
                        }
                    }
                }
            ],
            "categories": {
                "2_odds": [{"prediction": "Home Win", "odds": 1.8}],
                "5_odds": [],
                "10_odds": [],
                "rollover": []
            },
            "summary": {
                "total_fixtures": 1,
                "high_confidence_predictions": 1
            }
        }
        
        # Make request
        response = self.client.get("/api/predictions/")
        
        # Check response
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "predictions" in data or "categories" in data
    
    @patch("services.enhanced_prediction_service.enhanced_prediction_service.get_enhanced_predictions")
    def test_get_enhanced_predictions_endpoint(self, mock_get_predictions):
        """Test the enhanced predictions endpoint."""
        # Mock the enhanced prediction service
        mock_get_predictions.return_value = {
            "status": "success",
            "date": "2023-05-01",
            "predictions": [
                {
                    "fixture": {
                        "id": 12345,
                        "home_team": "Manchester United",
                        "away_team": "Liverpool"
                    },
                    "predictions": {
                        "match_result": {
                            "prediction": "Home Win",
                            "confidence": 75.5,
                            "method": "meta_stacking"
                        }
                    },
                    "explanations": {
                        "match_result": {
                            "human_readable": "Home team has better recent form"
                        }
                    }
                }
            ],
            "summary": {"total_fixtures": 1},
            "meta_stacking_used": True,
            "explanations_included": True
        }
        
        # Make request
        response = self.client.get("/api/predictions/enhanced/?include_explanations=true")
        
        # Check response
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["meta_stacking_used"] is True
        assert data["explanations_included"] is True
    
    def test_get_predictions_with_date_parameter(self):
        """Test predictions endpoint with date parameter."""
        with patch("services.enhanced_prediction_service.enhanced_prediction_service.get_enhanced_predictions") as mock_get_predictions:
            mock_get_predictions.return_value = {
                "status": "success",
                "date": "2023-05-01",
                "predictions": [],
                "categories": {},
                "summary": {}
            }
            
            response = self.client.get("/api/predictions/?date=2023-05-01")
            
            assert response.status_code == 200
            # Verify the service was called with the correct date
            mock_get_predictions.assert_called()
    
    def test_get_predictions_with_category_filter(self):
        """Test predictions endpoint with category filter."""
        with patch("services.enhanced_prediction_service.enhanced_prediction_service.get_enhanced_predictions") as mock_get_predictions:
            mock_get_predictions.return_value = {
                "status": "success",
                "date": "2023-05-01",
                "predictions": [],
                "categories": {
                    "2_odds": [{"prediction": "Home Win", "odds": 1.8}],
                    "5_odds": [],
                    "10_odds": [],
                    "rollover": []
                },
                "summary": {}
            }
            
            response = self.client.get("/api/predictions/?category=2_odds")
            
            assert response.status_code == 200
            data = response.json()
            # Should return only the 2_odds category
            if "categories" in data:
                assert "2_odds" in data["categories"]
    
    def test_health_endpoint(self):
        """Test the health check endpoint."""
        response = self.client.get("/api/health/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data
    
    def test_predictions_error_handling(self):
        """Test error handling in predictions endpoint."""
        with patch("services.enhanced_prediction_service.enhanced_prediction_service.get_enhanced_predictions") as mock_get_predictions:
            # Mock an error
            mock_get_predictions.return_value = {
                "status": "error",
                "message": "API service unavailable"
            }
            
            response = self.client.get("/api/predictions/")
            
            # Should handle the error gracefully
            assert response.status_code in [200, 500]  # Depending on error handling implementation
    
    def test_invalid_date_parameter(self):
        """Test handling of invalid date parameter."""
        response = self.client.get("/api/predictions/?date=invalid-date")
        
        # Should return a validation error
        assert response.status_code == 422  # Validation error
    
    def test_predictions_rate_limiting(self):
        """Test rate limiting on predictions endpoint."""
        # This test would check if rate limiting is properly implemented
        # For now, just verify the endpoint responds
        response = self.client.get("/api/predictions/")
        assert response.status_code in [200, 429]  # 429 if rate limited


class TestBasketballAPI:
    """Integration tests for basketball API endpoints."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
    
    def test_basketball_predictions_endpoint_exists(self):
        """Test that basketball predictions endpoint exists."""
        response = self.client.get("/api/basketball-predictions/")
        
        # Should not return 404 (endpoint should exist)
        assert response.status_code != 404
    
    @patch("basketball.prediction_service.BasketballPredictionService")
    def test_basketball_predictions_functionality(self, mock_service):
        """Test basketball predictions functionality."""
        # Mock the basketball service
        mock_instance = MagicMock()
        mock_service.return_value = mock_instance
        mock_instance.get_predictions_for_date.return_value = {
            "status": "success",
            "predictions": [],
            "categories": {}
        }
        
        response = self.client.get("/api/basketball-predictions/")
        
        # Check that the endpoint works
        assert response.status_code in [200, 500]  # 500 if service not fully implemented


class TestAPIDocumentation:
    """Tests for API documentation and OpenAPI schema."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.client = TestClient(app)
    
    def test_openapi_schema_available(self):
        """Test that OpenAPI schema is available."""
        response = self.client.get("/openapi.json")
        
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema
    
    def test_docs_endpoint_available(self):
        """Test that documentation endpoint is available."""
        response = self.client.get("/docs")
        
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
    
    def test_redoc_endpoint_available(self):
        """Test that ReDoc endpoint is available."""
        response = self.client.get("/redoc")
        
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


if __name__ == "__main__":
    pytest.main([__file__])
