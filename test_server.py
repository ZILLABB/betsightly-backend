#!/usr/bin/env python3
"""
Test server startup and basic functionality.
"""

import sys
import traceback
from datetime import datetime

def test_server_startup():
    """Test if the server can start up."""
    try:
        print("🚀 Testing server startup...")
        
        # Import main app
        from main import app
        print("✅ Main app imported successfully")
        
        # Test basic configuration
        from utils.config import settings
        print(f"✅ Configuration loaded - Environment: {settings.ENVIRONMENT}")
        
        # Test database connection
        from database import get_db
        db_gen = get_db()
        db = next(db_gen)
        print("✅ Database connection successful")
        db.close()
        
        # Test health endpoint
        from api.endpoints.health import health_check
        health_result = health_check()
        print(f"✅ Health check: {health_result['status']}")
        
        # Test detailed health check
        from api.endpoints.health import detailed_health_check
        try:
            db_gen = get_db()
            db = next(db_gen)
            detailed_health = detailed_health_check(db)
            print(f"✅ Detailed health check: {detailed_health['status']}")
            db.close()
        except Exception as e:
            print(f"⚠️  Detailed health check issues: {str(e)}")
        
        print("✅ Server startup test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Server startup failed: {str(e)}")
        traceback.print_exc()
        return False

def test_api_endpoints():
    """Test API endpoints functionality."""
    try:
        print("\n🔗 Testing API endpoints...")
        
        # Test predictions endpoint
        from api.endpoints.predictions import get_predictions
        from database import get_db
        
        db_gen = get_db()
        db = next(db_gen)
        
        try:
            predictions = get_predictions(db=db, categorized=True)
            print(f"✅ Predictions endpoint works - Status: {predictions.get('status', 'unknown')}")
        except Exception as e:
            print(f"⚠️  Predictions endpoint issue: {str(e)}")
        
        db.close()
        
        # Test basketball predictions
        try:
            from api.endpoints.basketball_predictions import get_basketball_predictions
            db_gen = get_db()
            db = next(db_gen)
            basketball_preds = get_basketball_predictions(db=db)
            print(f"✅ Basketball predictions endpoint works - Status: {basketball_preds.get('status', 'unknown')}")
            db.close()
        except Exception as e:
            print(f"⚠️  Basketball predictions issue: {str(e)}")
        
        return True
        
    except Exception as e:
        print(f"❌ API endpoints test failed: {str(e)}")
        return False

def main():
    print(f"🔍 BetSightly Backend Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Test server startup
    startup_success = test_server_startup()
    
    # Test API endpoints
    if startup_success:
        test_api_endpoints()
    
    print("\n" + "=" * 60)
    print("✅ Basic functionality test completed!")

if __name__ == "__main__":
    main()
