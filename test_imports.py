#!/usr/bin/env python3
"""
Test imports to identify any issues.
"""

import sys
import traceback

def test_import(module_name, description=""):
    """Test importing a module."""
    try:
        __import__(module_name)
        print(f"✅ {module_name} {description}")
        return True
    except Exception as e:
        print(f"❌ {module_name} {description}: {str(e)}")
        return False

def main():
    print("🔍 Testing imports...")
    
    # Test basic dependencies
    test_import("fastapi", "- Web framework")
    test_import("uvicorn", "- ASGI server")
    test_import("sqlalchemy", "- Database ORM")
    test_import("pydantic", "- Data validation")
    test_import("pandas", "- Data processing")
    test_import("numpy", "- Numerical computing")
    test_import("sklearn", "- Machine learning")
    
    # Test project modules
    print("\n🏗️ Testing project modules...")
    test_import("utils.config", "- Configuration")
    test_import("database", "- Database setup")
    
    # Test API modules
    print("\n🌐 Testing API modules...")
    test_import("api.api", "- API router")
    
    # Test specific endpoints
    print("\n📡 Testing API endpoints...")
    test_import("api.endpoints.health", "- Health endpoints")
    test_import("api.endpoints.predictions", "- Predictions endpoints")
    test_import("api.endpoints.basketball_predictions", "- Basketball endpoints")
    
    # Test ML modules
    print("\n🤖 Testing ML modules...")
    test_import("ml.model_factory", "- Model factory")
    test_import("ml.xgboost_models", "- XGBoost models")
    test_import("ml.lightgbm_models", "- LightGBM models")
    
    # Test services
    print("\n🔧 Testing services...")
    test_import("services.api_client", "- API client")
    test_import("services.prediction_categorizer", "- Prediction categorizer")
    
    # Test basketball modules
    print("\n🏀 Testing basketball modules...")
    test_import("basketball.prediction_service", "- Basketball prediction service")
    test_import("basketball.models", "- Basketball models")
    
    print("\n✅ Import testing complete!")

if __name__ == "__main__":
    main()
