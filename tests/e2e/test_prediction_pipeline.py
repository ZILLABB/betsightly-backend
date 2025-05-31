"""
End-to-End Tests for Prediction Pipeline

This module contains end-to-end tests for the complete prediction pipeline.
"""

import pytest
import sys
import os
import requests
import time
from datetime import datetime, timedelta

# Add the parent directory to the path so we can import the app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestPredictionPipelineE2E:
    """End-to-end tests for the prediction pipeline."""
    
    @pytest.fixture(scope="class")
    def base_url(self):
        """Base URL for the API."""
        return "http://localhost:8000"
    
    @pytest.fixture(scope="class")
    def api_client(self, base_url):
        """API client for making requests."""
        return APITestClient(base_url)
    
    def test_complete_prediction_workflow(self, api_client):
        """Test the complete prediction workflow from API to response."""
        # Skip if server is not running
        if not api_client.is_server_running():
            pytest.skip("Server is not running")
        
        # Step 1: Check health
        health_response = api_client.get("/api/health/")
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "healthy"
        
        # Step 2: Get predictions for today
        today = datetime.now().strftime("%Y-%m-%d")
        predictions_response = api_client.get(f"/api/predictions/?date={today}")
        
        # Should get a successful response
        assert predictions_response.status_code == 200
        data = predictions_response.json()
        
        # Check response structure
        assert "status" in data
        if data["status"] == "success":
            assert "date" in data
            # Should have either predictions or categories
            assert "predictions" in data or "categories" in data
    
    def test_enhanced_predictions_with_explanations(self, api_client):
        """Test enhanced predictions with explanations."""
        if not api_client.is_server_running():
            pytest.skip("Server is not running")
        
        # Get enhanced predictions
        response = api_client.get("/api/predictions/enhanced/?include_explanations=true")
        
        assert response.status_code == 200
        data = response.json()
        
        if data.get("status") == "success":
            assert "explanations_included" in data
            assert "meta_stacking_used" in data
            
            # If there are predictions, check for explanations
            if data.get("predictions"):
                for prediction in data["predictions"]:
                    if "explanations" in prediction:
                        assert isinstance(prediction["explanations"], dict)
    
    def test_prediction_categories_workflow(self, api_client):
        """Test prediction categories workflow."""
        if not api_client.is_server_running():
            pytest.skip("Server is not running")
        
        # Test each category
        categories = ["2_odds", "5_odds", "10_odds", "rollover"]
        
        for category in categories:
            response = api_client.get(f"/api/predictions/?category={category}")
            assert response.status_code == 200
            
            data = response.json()
            if data.get("status") == "success":
                # Should return data for the specific category
                if "categories" in data:
                    assert category in data["categories"] or len(data["categories"]) == 0
    
    def test_basketball_predictions_integration(self, api_client):
        """Test basketball predictions integration."""
        if not api_client.is_server_running():
            pytest.skip("Server is not running")
        
        # Test basketball predictions endpoint
        response = api_client.get("/api/basketball-predictions/")
        
        # Should not return 404 (endpoint should exist)
        assert response.status_code != 404
        
        # If implemented, should return valid structure
        if response.status_code == 200:
            data = response.json()
            assert "status" in data
    
    def test_api_performance(self, api_client):
        """Test API performance and response times."""
        if not api_client.is_server_running():
            pytest.skip("Server is not running")
        
        # Test response time for predictions endpoint
        start_time = time.time()
        response = api_client.get("/api/predictions/")
        end_time = time.time()
        
        response_time = end_time - start_time
        
        # Should respond within reasonable time (adjust as needed)
        assert response_time < 30.0  # 30 seconds max
        assert response.status_code == 200
    
    def test_error_handling_e2e(self, api_client):
        """Test error handling in end-to-end scenarios."""
        if not api_client.is_server_running():
            pytest.skip("Server is not running")
        
        # Test invalid date
        response = api_client.get("/api/predictions/?date=invalid-date")
        assert response.status_code == 422  # Validation error
        
        # Test invalid category
        response = api_client.get("/api/predictions/?category=invalid-category")
        assert response.status_code == 422  # Validation error
    
    def test_data_consistency(self, api_client):
        """Test data consistency across multiple requests."""
        if not api_client.is_server_running():
            pytest.skip("Server is not running")
        
        # Make multiple requests for the same date
        today = datetime.now().strftime("%Y-%m-%d")
        
        response1 = api_client.get(f"/api/predictions/?date={today}")
        response2 = api_client.get(f"/api/predictions/?date={today}")
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Responses should be consistent (assuming caching)
        data1 = response1.json()
        data2 = response2.json()
        
        if data1.get("status") == "success" and data2.get("status") == "success":
            # Basic consistency check
            assert data1.get("date") == data2.get("date")


class TestMLPipelineE2E:
    """End-to-end tests for the ML pipeline."""
    
    def test_model_loading_and_prediction(self):
        """Test that models can be loaded and make predictions."""
        try:
            from ml.model_factory import model_factory
            
            # Test that model factory is available
            assert model_factory is not None
            
            # Test basic model functionality (if models are available)
            # This would be expanded based on actual model implementation
            
        except ImportError:
            pytest.skip("ML models not available")
    
    def test_feature_engineering_pipeline(self):
        """Test the feature engineering pipeline."""
        try:
            from ml.advanced_feature_engineering import AdvancedFootballFeatureEngineer
            
            # Test feature engineer initialization
            feature_engineer = AdvancedFootballFeatureEngineer()
            assert feature_engineer is not None
            
        except ImportError:
            pytest.skip("Advanced feature engineering not available")
    
    def test_explainability_pipeline(self):
        """Test the explainability pipeline."""
        try:
            from ml.model_explainer import model_explainer
            
            # Test explainer is available
            assert model_explainer is not None
            
        except ImportError:
            pytest.skip("Model explainer not available")


class APITestClient:
    """Helper class for making API requests in tests."""
    
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
    
    def is_server_running(self):
        """Check if the server is running."""
        try:
            response = self.session.get(f"{self.base_url}/api/health/", timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def get(self, endpoint, **kwargs):
        """Make a GET request."""
        url = f"{self.base_url}{endpoint}"
        return self.session.get(url, **kwargs)
    
    def post(self, endpoint, **kwargs):
        """Make a POST request."""
        url = f"{self.base_url}{endpoint}"
        return self.session.post(url, **kwargs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
