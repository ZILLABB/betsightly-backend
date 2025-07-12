#!/usr/bin/env python3
"""
Test API functionality and endpoints
"""

import sys
import traceback
from datetime import datetime
import asyncio
from fastapi.testclient import TestClient

def test_api_endpoints():
    """Test all API endpoints functionality."""
    print("🌐 TESTING API ENDPOINTS")
    print("=" * 50)
    
    try:
        # Import the FastAPI app
        from main import app
        
        # Create test client
        client = TestClient(app)
        
        # Test health endpoint
        print("🔍 Testing health endpoints...")
        response = client.get("/api/health/")
        print(f"✅ Health endpoint: {response.status_code} - {response.json()}")
        
        # Test detailed health
        response = client.get("/api/health/detailed")
        print(f"✅ Detailed health: {response.status_code}")
        if response.status_code == 200:
            health_data = response.json()
            print(f"   Database: {health_data.get('database', {}).get('status', 'unknown')}")
            print(f"   Models: {health_data.get('models', {}).get('status', 'unknown')}")
            print(f"   API Keys: {health_data.get('api_keys', {}).get('status', 'unknown')}")
        
        # Test predictions endpoint
        print("\n🔮 Testing predictions endpoints...")
        response = client.get("/api/predictions/")
        print(f"✅ Main predictions: {response.status_code}")
        if response.status_code == 200:
            pred_data = response.json()
            if isinstance(pred_data, dict):
                categories = pred_data.keys()
                print(f"   Categories: {list(categories)}")
                total_predictions = sum(len(v) if isinstance(v, list) else 0 for v in pred_data.values())
                print(f"   Total predictions: {total_predictions}")
        
        # Test specific category
        response = client.get("/api/predictions/?category=2_odds")
        print(f"✅ Safe bets (2_odds): {response.status_code}")
        
        # Test enhanced predictions
        response = client.get("/api/predictions/enhanced/")
        print(f"✅ Enhanced predictions: {response.status_code}")
        
        # Test basketball predictions
        print("\n🏀 Testing basketball endpoints...")
        response = client.get("/api/basketball-predictions/")
        print(f"✅ Basketball predictions: {response.status_code}")
        if response.status_code == 200:
            bball_data = response.json()
            print(f"   Status: {bball_data.get('status', 'unknown')}")
            print(f"   Count: {bball_data.get('count', 0)}")
        
        # Test basketball models status
        response = client.get("/api/basketball-predictions/models/status")
        print(f"✅ Basketball models status: {response.status_code}")
        if response.status_code == 200:
            models_data = response.json()
            available_models = models_data.get('available_models', 0)
            total_models = models_data.get('total_models', 0)
            print(f"   Models: {available_models}/{total_models} available")
        
        return True
        
    except Exception as e:
        print(f"❌ API testing failed: {str(e)}")
        traceback.print_exc()
        return False

def test_prediction_services():
    """Test prediction services directly."""
    print("\n🤖 TESTING PREDICTION SERVICES")
    print("=" * 50)
    
    try:
        # Test quick prediction service
        from services.quick_prediction_service import quick_prediction_service
        
        print("🔍 Testing quick prediction service...")
        result = quick_prediction_service.get_predictions_for_date()
        print(f"✅ Quick service status: {result.get('status', 'unknown')}")
        print(f"   Date: {result.get('date', 'unknown')}")
        print(f"   Categories: {list(result.get('categories', {}).keys())}")
        
        # Test basketball service
        print("\n🏀 Testing basketball prediction service...")
        from basketball.prediction_service import BasketballPredictionService
        
        basketball_service = BasketballPredictionService()
        bball_result = basketball_service.generate_predictions()
        print(f"✅ Basketball service status: {bball_result.get('status', 'unknown')}")
        print(f"   Total games: {bball_result.get('total_games', 0)}")
        
        if bball_result.get('status') == 'success':
            categories = bball_result.get('categories', {})
            for category, predictions in categories.items():
                print(f"   {category}: {len(predictions)} predictions")
        
        return True
        
    except Exception as e:
        print(f"❌ Prediction services testing failed: {str(e)}")
        traceback.print_exc()
        return False

def test_model_loading():
    """Test model loading capabilities."""
    print("\n🧠 TESTING MODEL LOADING")
    print("=" * 50)
    
    try:
        # Test model factory
        from ml.model_factory import model_factory
        
        available_models = model_factory.get_available_models()
        print(f"✅ Model factory available models: {available_models}")
        
        # Test creating models
        working_models = 0
        for model_type in available_models[:3]:  # Test first 3
            try:
                model = model_factory.create_model(model_type)
                if model:
                    print(f"✅ {model_type}: Created successfully")
                    working_models += 1
                else:
                    print(f"❌ {model_type}: Failed to create")
            except Exception as e:
                print(f"❌ {model_type}: Error - {str(e)}")
        
        print(f"\n📊 Working models: {working_models}/{len(available_models[:3])}")
        
        # Test basketball models
        print("\n🏀 Testing basketball models...")
        from basketball.models import BasketballModelFactory
        
        basketball_factory = BasketballModelFactory()
        basketball_models = basketball_factory._get_models_status()
        print(f"✅ Basketball models status: {basketball_models}")
        
        return True
        
    except Exception as e:
        print(f"❌ Model loading testing failed: {str(e)}")
        traceback.print_exc()
        return False

def test_data_sources():
    """Test data source connections."""
    print("\n📡 TESTING DATA SOURCES")
    print("=" * 50)
    
    try:
        # Test API client
        from services.api_client import FootballDataClient
        
        client = FootballDataClient()
        print("✅ Football Data Client initialized")
        
        # Test configuration
        from utils.config import settings
        
        print(f"✅ Environment: {settings.ENVIRONMENT}")
        print(f"✅ Football Data API configured: {'Yes' if settings.football_data.API_KEY else 'No'}")
        print(f"✅ API Football configured: {'Yes' if settings.api_football.API_KEY else 'No'}")
        
        # Test database connection
        from database import get_db
        
        db_gen = get_db()
        db = next(db_gen)
        print("✅ Database connection successful")
        
        # Check for any existing data
        from sqlalchemy import text
        result = db.execute(text("SELECT COUNT(*) FROM fixtures")).scalar()
        print(f"📊 Fixtures in database: {result}")
        
        result = db.execute(text("SELECT COUNT(*) FROM predictions")).scalar()
        print(f"📊 Predictions in database: {result}")
        
        db.close()
        
        return True
        
    except Exception as e:
        print(f"❌ Data sources testing failed: {str(e)}")
        traceback.print_exc()
        return False

def main():
    """Run all functionality tests."""
    print("🔍 BETSIGHTLY BACKEND FUNCTIONALITY TESTING")
    print("=" * 60)
    print(f"📅 Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Run all tests
    tests = [
        ("API Endpoints", test_api_endpoints),
        ("Prediction Services", test_prediction_services),
        ("Model Loading", test_model_loading),
        ("Data Sources", test_data_sources)
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"❌ {test_name} test crashed: {str(e)}")
            results[test_name] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
    
    print(f"\n📊 Overall: {passed}/{total} tests passed ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 All functionality tests passed!")
    elif passed >= total * 0.75:
        print("⚠️ Most functionality working, some issues to address")
    else:
        print("🚨 Significant functionality issues detected")

if __name__ == "__main__":
    main()
