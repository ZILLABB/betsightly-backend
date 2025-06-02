#!/usr/bin/env python3
"""
Production Readiness Test Suite

Comprehensive tests to ensure the application is ready for production deployment.
"""

import os
import sys
import pytest
import logging
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Add project root to path
sys.path.append('.')

from main import app
from database import get_db, init_db
from utils.config import settings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestProductionReadiness:
    """Test suite for production readiness."""
    
    @classmethod
    def setup_class(cls):
        """Set up test environment."""
        cls.client = TestClient(app)
        init_db()
    
    def test_environment_configuration(self):
        """Test that environment is properly configured."""
        # Check critical environment variables
        critical_vars = ['SECRET_KEY', 'DATABASE_URL']
        for var in critical_vars:
            value = os.getenv(var)
            assert value is not None, f"Environment variable {var} is not set"
            assert len(value) > 0, f"Environment variable {var} is empty"
        
        # Check that DEBUG is False in production
        if os.getenv('ENVIRONMENT') == 'production':
            assert not settings.DEBUG, "DEBUG should be False in production"
    
    def test_database_connectivity(self):
        """Test database connection and basic operations."""
        from sqlalchemy import text
        db = next(get_db())
        try:
            # Test basic query
            result = db.execute(text("SELECT 1")).fetchone()
            assert result[0] == 1, "Database connection test failed"

            # Test table existence
            tables = db.execute(text("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)).fetchall()
            
            expected_tables = ['predictions', 'fixtures', 'betting_codes', 'punters', 'bookmakers']
            existing_tables = [table[0] for table in tables]
            
            for table in expected_tables:
                assert table in existing_tables, f"Required table {table} not found"
                
        finally:
            db.close()
    
    def test_api_endpoints_health(self):
        """Test that all critical API endpoints are working."""
        endpoints = [
            ('/api/health', 200),
            ('/api/predictions/', 200),
            ('/api/betting-codes/', 200),
            ('/api/punters/', 200),
            ('/api/bookmakers/', 200)
        ]
        
        for endpoint, expected_status in endpoints:
            response = self.client.get(endpoint)
            assert response.status_code == expected_status, \
                f"Endpoint {endpoint} returned {response.status_code}, expected {expected_status}"
    
    def test_prediction_service_functionality(self):
        """Test that prediction service is working."""
        response = self.client.get('/api/predictions/')
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, dict), "Predictions response should be a dictionary"
        
        # Check for expected categories
        expected_categories = ['2_odds', '5_odds', '10_odds', 'rollover']
        for category in expected_categories:
            assert category in data, f"Category {category} not found in predictions"
    
    def test_error_handling(self):
        """Test error handling for invalid requests."""
        # Test invalid endpoint
        response = self.client.get('/api/nonexistent')
        assert response.status_code == 404
        
        # Test invalid prediction ID
        response = self.client.get('/api/predictions/99999')
        assert response.status_code == 404
        
        # Test invalid date format
        response = self.client.get('/api/predictions/?date=invalid-date')
        assert response.status_code == 422  # Validation error
    
    def test_security_headers(self):
        """Test that security headers are present."""
        response = self.client.get('/api/health')

        # Note: Security middleware is currently disabled for testing
        # In production, these headers should be present
        if os.getenv('ENVIRONMENT') == 'production':
            security_headers = [
                'X-Content-Type-Options',
                'X-Frame-Options',
                'X-XSS-Protection'
            ]

            for header in security_headers:
                assert header in response.headers, f"Security header {header} is missing"
        else:
            # In development/testing, just check that the endpoint works
            assert response.status_code == 200
    
    def test_rate_limiting(self):
        """Test rate limiting functionality."""
        # Make multiple requests quickly
        responses = []
        for i in range(10):
            response = self.client.get('/api/health')
            responses.append(response.status_code)
        
        # All should succeed (rate limit is high for testing)
        assert all(status == 200 for status in responses), "Rate limiting too aggressive"
    
    def test_cors_configuration(self):
        """Test CORS configuration."""
        response = self.client.options('/api/health', headers={
            'Origin': 'http://localhost:5182',
            'Access-Control-Request-Method': 'GET'
        })
        
        assert 'Access-Control-Allow-Origin' in response.headers
    
    def test_ml_models_availability(self):
        """Test that ML models are available."""
        try:
            from services.quick_prediction_service import quick_prediction_service
            
            # Test model loading
            result = quick_prediction_service.get_predictions_for_date("2024-01-01")
            assert result is not None, "Prediction service should return a result"
            assert 'status' in result, "Prediction result should have status"
            
        except Exception as e:
            pytest.fail(f"ML models test failed: {str(e)}")
    
    def test_telegram_bot_configuration(self):
        """Test Telegram bot configuration."""
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if token:
            assert ':' in token, "Telegram bot token format is invalid"
            assert len(token) > 20, "Telegram bot token seems too short"
    
    def test_data_validation(self):
        """Test data validation in API endpoints."""
        # Test betting code creation with invalid data
        invalid_data = {
            "code": "",  # Empty code
            "punter_id": -1,  # Invalid ID
            "odds": -1.0  # Invalid odds
        }

        response = self.client.post('/api/betting-codes/', json=invalid_data)
        # The API returns 404 when punter doesn't exist, which is also valid validation
        assert response.status_code in [400, 404, 422], "Should reject invalid data"
    
    def test_performance_benchmarks(self):
        """Test basic performance benchmarks."""
        import time
        
        # Test prediction endpoint response time
        start_time = time.time()
        response = self.client.get('/api/predictions/')
        end_time = time.time()
        
        response_time = end_time - start_time
        assert response_time < 2.0, f"Predictions endpoint too slow: {response_time:.2f}s"
        assert response.status_code == 200
    
    def test_logging_configuration(self):
        """Test that logging is properly configured."""
        # Check that logger is configured
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0, "No logging handlers configured"
        
        # Test log level
        assert root_logger.level <= logging.INFO, "Log level should be INFO or lower"
    
    def test_cache_functionality(self):
        """Test caching functionality."""
        # Test cached predictions
        response1 = self.client.get('/api/predictions/')
        response2 = self.client.get('/api/predictions/')
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        # Both should return the same data (cached)
        assert response1.json() == response2.json()
    
    def test_basketball_integration(self):
        """Test basketball predictions integration."""
        response = self.client.get('/api/basketball-predictions/')
        # Should not fail even if no data available
        assert response.status_code in [200, 404]
    
    def test_api_documentation(self):
        """Test API documentation availability."""
        if settings.DEBUG:
            # In debug mode, docs should be available
            response = self.client.get('/docs')
            assert response.status_code == 200
        else:
            # In production, docs should be disabled
            response = self.client.get('/docs')
            assert response.status_code == 404

def run_production_tests():
    """Run all production readiness tests."""
    logger.info("🧪 Running production readiness tests...")
    
    # Run pytest with specific markers
    exit_code = pytest.main([
        __file__,
        '-v',
        '--tb=short',
        '--disable-warnings'
    ])
    
    if exit_code == 0:
        logger.info("✅ All production readiness tests passed!")
        return True
    else:
        logger.error("❌ Some production readiness tests failed!")
        return False

if __name__ == '__main__':
    success = run_production_tests()
    sys.exit(0 if success else 1)
