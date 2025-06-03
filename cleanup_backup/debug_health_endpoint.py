#!/usr/bin/env python3
"""
Debug health endpoint issues
"""

import traceback
from fastapi.testclient import TestClient

def debug_health_endpoint():
    """Debug the health endpoint step by step."""
    print("🔍 DEBUGGING HEALTH ENDPOINT")
    print("=" * 50)
    
    try:
        # Test basic imports
        print("1. Testing basic imports...")
        from main import app
        print("✅ Main app imported")
        
        from api.endpoints.health import health_check
        print("✅ Health check function imported")
        
        # Test direct function call
        print("\n2. Testing direct function call...")
        result = health_check()
        print(f"✅ Direct call result: {result}")
        
        # Test with TestClient
        print("\n3. Testing with TestClient...")
        client = TestClient(app)
        
        # Test basic health endpoint
        print("Testing GET /api/health/")
        response = client.get("/api/health/")
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print(f"Content: {response.content}")
        
        if response.status_code == 200:
            print(f"✅ Response JSON: {response.json()}")
        else:
            print(f"❌ Error response: {response.status_code}")
            print(f"Response text: {response.text}")
        
        # Test detailed health endpoint
        print("\n4. Testing detailed health endpoint...")
        print("Testing GET /api/health/detailed")
        response = client.get("/api/health/detailed")
        print(f"Status Code: {response.status_code}")
        print(f"Content: {response.content}")
        
        if response.status_code == 200:
            print(f"✅ Detailed response JSON: {response.json()}")
        else:
            print(f"❌ Detailed error response: {response.status_code}")
            print(f"Response text: {response.text}")
        
        return True
        
    except Exception as e:
        print(f"❌ Debug failed: {str(e)}")
        traceback.print_exc()
        return False

def test_configuration():
    """Test configuration loading."""
    print("\n🔧 TESTING CONFIGURATION")
    print("=" * 50)
    
    try:
        from utils.config import settings
        
        print(f"✅ Environment: {settings.ENVIRONMENT}")
        print(f"✅ App Name: {settings.APP_NAME}")
        print(f"✅ Football Data Key: {settings.football_data.API_KEY[:10]}..." if settings.football_data.API_KEY else "❌ No Football Data Key")
        print(f"✅ API Football Key: {settings.api_football.API_KEY[:10]}..." if settings.api_football.API_KEY else "❌ No API Football Key")
        print(f"✅ Database URL: {settings.database.URL}")
        print(f"✅ Model Dir: {settings.ml.MODEL_DIR}")
        print(f"✅ Data Dir: {settings.ml.DATA_DIR}")
        print(f"✅ Cache Dir: {settings.ml.CACHE_DIR}")
        
        return True
        
    except Exception as e:
        print(f"❌ Configuration test failed: {str(e)}")
        traceback.print_exc()
        return False

def test_database_connection():
    """Test database connection."""
    print("\n🗄️ TESTING DATABASE CONNECTION")
    print("=" * 50)
    
    try:
        from database import get_db
        from sqlalchemy import text
        
        db_gen = get_db()
        db = next(db_gen)
        
        # Test simple query
        result = db.execute(text("SELECT 1")).scalar()
        print(f"✅ Database query result: {result}")
        
        # Test table existence
        result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        tables = [row[0] for row in result]
        print(f"✅ Database tables: {tables}")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Database test failed: {str(e)}")
        traceback.print_exc()
        return False

def test_api_routing():
    """Test API routing configuration."""
    print("\n🌐 TESTING API ROUTING")
    print("=" * 50)
    
    try:
        from main import app
        
        # Get all routes
        routes = []
        for route in app.routes:
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                routes.append(f"{list(route.methods)} {route.path}")
        
        print("Available routes:")
        for route in routes:
            print(f"  {route}")
        
        # Check if health routes are registered
        health_routes = [r for r in routes if '/health' in r]
        print(f"\n✅ Health routes found: {len(health_routes)}")
        for route in health_routes:
            print(f"  {route}")
        
        return True
        
    except Exception as e:
        print(f"❌ API routing test failed: {str(e)}")
        traceback.print_exc()
        return False

def main():
    """Run all debug tests."""
    print("🔍 HEALTH ENDPOINT DEBUG SESSION")
    print("=" * 60)
    
    tests = [
        ("Configuration", test_configuration),
        ("Database Connection", test_database_connection),
        ("API Routing", test_api_routing),
        ("Health Endpoint", debug_health_endpoint)
    ]
    
    results = {}
    for test_name, test_func in tests:
        print(f"\n{'='*60}")
        results[test_name] = test_func()
    
    # Summary
    print(f"\n{'='*60}")
    print("📊 DEBUG RESULTS SUMMARY")
    print("=" * 60)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
    
    passed = sum(results.values())
    total = len(results)
    print(f"\n📊 Overall: {passed}/{total} tests passed")

if __name__ == "__main__":
    main()
