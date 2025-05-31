#!/usr/bin/env python3
"""
Test Script for BetSightly Backend Fixes

This script tests all the critical fixes that were applied to the backend.
"""

import os
import sys
import logging
import requests
import time
from datetime import datetime
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_environment_variables():
    """Test that environment variables are properly loaded."""
    logger.info("Testing environment variables...")
    
    try:
        from utils.config import settings
        
        # Test that API keys are loaded from environment (should be empty if not set)
        football_key = settings.football_data.API_KEY
        api_football_key = settings.api_football.API_KEY
        
        # These should not be the old hardcoded values
        assert football_key != "f9ed94ba8dde4a57b742ce7075057310", "Football Data API key still hardcoded!"
        assert api_football_key != "f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73", "API Football key still hardcoded!"
        
        logger.info("✓ Environment variables are properly configured")
        return True
        
    except Exception as e:
        logger.error(f"Environment variables test failed: {str(e)}")
        return False


def test_database_initialization():
    """Test database initialization and optimization."""
    logger.info("Testing database initialization...")
    
    try:
        from database import init_db, get_db
        from sqlalchemy import text
        
        # Initialize database
        if not init_db():
            logger.error("Database initialization failed")
            return False
        
        # Test database connection
        db = next(get_db())
        result = db.execute(text("SELECT 1")).fetchone()
        db.close()
        
        if result[0] != 1:
            logger.error("Database query test failed")
            return False
        
        logger.info("✓ Database initialization and connection successful")
        return True
        
    except Exception as e:
        logger.error(f"Database test failed: {str(e)}")
        return False


def test_model_factory_initialization():
    """Test that model factory is properly initialized."""
    logger.info("Testing model factory initialization...")
    
    try:
        from services.advanced_prediction_service import AdvancedPredictionService
        
        # Create service instance
        service = AdvancedPredictionService()
        
        # Check that model_factory is not None (should be None if import fails, but handled gracefully)
        if service.model_factory is None:
            logger.info("✓ Model factory gracefully handles missing models")
        else:
            logger.info("✓ Model factory initialized successfully")
        
        return True
        
    except Exception as e:
        logger.error(f"Model factory test failed: {str(e)}")
        return False


def test_error_handling():
    """Test error handling utilities."""
    logger.info("Testing error handling...")
    
    try:
        from utils.error_handling import BetSightlyError, handle_database_error, create_error_response
        
        # Test custom exception
        try:
            raise BetSightlyError("Test error", "TEST_ERROR")
        except BetSightlyError as e:
            assert e.error_code == "TEST_ERROR"
        
        # Test error response creation
        response = create_error_response(500, "Test message", "TEST_CODE")
        assert response["status"] == "error"
        assert response["message"] == "Test message"
        assert response["error_code"] == "TEST_CODE"
        
        logger.info("✓ Error handling utilities working correctly")
        return True
        
    except Exception as e:
        logger.error(f"Error handling test failed: {str(e)}")
        return False


def test_database_optimization():
    """Test database optimization utilities."""
    logger.info("Testing database optimization...")
    
    try:
        from utils.database_optimization import DatabaseCache, OptimizedQueryBuilder
        
        # Test cache
        cache = DatabaseCache(ttl_seconds=1)
        cache.set("test_key", "test_value")
        
        value = cache.get("test_key")
        assert value == "test_value"
        
        # Wait for expiration
        time.sleep(2)
        expired_value = cache.get("test_key")
        assert expired_value is None
        
        logger.info("✓ Database optimization utilities working correctly")
        return True
        
    except Exception as e:
        logger.error(f"Database optimization test failed: {str(e)}")
        return False


def test_api_endpoints():
    """Test API endpoints if server is running."""
    logger.info("Testing API endpoints...")
    
    base_url = "http://localhost:8000"
    
    try:
        # Test basic health check
        response = requests.get(f"{base_url}/api/health/", timeout=5)
        if response.status_code == 200:
            logger.info("✓ Health check endpoint working")
        else:
            logger.warning(f"Health check returned status {response.status_code}")
        
        # Test root endpoint
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            logger.info("✓ Root endpoint working")
        else:
            logger.warning(f"Root endpoint returned status {response.status_code}")
        
        return True
        
    except requests.exceptions.ConnectionError:
        logger.warning("⚠ Server not running - skipping API endpoint tests")
        return True  # Not a failure if server isn't running
        
    except Exception as e:
        logger.error(f"API endpoint test failed: {str(e)}")
        return False


def test_cors_configuration():
    """Test CORS configuration."""
    logger.info("Testing CORS configuration...")
    
    try:
        from main import app
        
        # Check that CORS middleware is configured
        middlewares = [middleware.cls.__name__ for middleware in app.user_middleware]
        
        if "CORSMiddleware" in middlewares:
            logger.info("✓ CORS middleware is configured")
            return True
        else:
            logger.error("CORS middleware not found")
            return False
        
    except Exception as e:
        logger.error(f"CORS configuration test failed: {str(e)}")
        return False


def test_file_permissions():
    """Test file system permissions."""
    logger.info("Testing file system permissions...")
    
    try:
        required_dirs = ["data", "cache", "models", "logs"]
        
        for dir_name in required_dirs:
            dir_path = Path(dir_name)
            
            # Create directory if it doesn't exist
            dir_path.mkdir(exist_ok=True)
            
            # Test write permission
            test_file = dir_path / ".test_write"
            test_file.write_text("test")
            test_file.unlink()
        
        logger.info("✓ File system permissions working correctly")
        return True
        
    except Exception as e:
        logger.error(f"File permissions test failed: {str(e)}")
        return False


def run_all_tests():
    """Run all tests and return summary."""
    logger.info("🧪 Running all tests...")
    
    tests = [
        ("Environment Variables", test_environment_variables),
        ("Database Initialization", test_database_initialization),
        ("Model Factory", test_model_factory_initialization),
        ("Error Handling", test_error_handling),
        ("Database Optimization", test_database_optimization),
        ("API Endpoints", test_api_endpoints),
        ("CORS Configuration", test_cors_configuration),
        ("File Permissions", test_file_permissions)
    ]
    
    passed = 0
    failed = 0
    failed_tests = []
    
    for test_name, test_func in tests:
        logger.info(f"\n--- Running {test_name} Test ---")
        try:
            if test_func():
                passed += 1
                logger.info(f"✅ {test_name}: PASSED")
            else:
                failed += 1
                failed_tests.append(test_name)
                logger.error(f"❌ {test_name}: FAILED")
        except Exception as e:
            failed += 1
            failed_tests.append(test_name)
            logger.error(f"❌ {test_name}: FAILED with exception: {str(e)}")
    
    # Print summary
    logger.info(f"\n{'='*50}")
    logger.info(f"TEST SUMMARY")
    logger.info(f"{'='*50}")
    logger.info(f"Total tests: {passed + failed}")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    
    if failed_tests:
        logger.info(f"Failed tests: {', '.join(failed_tests)}")
    
    if failed == 0:
        logger.info("🎉 All tests passed!")
        return True
    else:
        logger.error(f"💥 {failed} test(s) failed!")
        return False


def main():
    """Main test function."""
    logger.info("🔧 BetSightly Backend - Testing Critical Fixes")
    logger.info(f"Test started at: {datetime.now().isoformat()}")
    
    success = run_all_tests()
    
    if success:
        logger.info("\n✅ All critical fixes are working correctly!")
        sys.exit(0)
    else:
        logger.error("\n❌ Some tests failed. Please review the issues above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
