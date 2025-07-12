#!/usr/bin/env python3
"""
Test environment variable loading
"""

import os
from dotenv import load_dotenv

def test_env_loading():
    """Test environment variable loading."""
    print("🔍 TESTING ENVIRONMENT VARIABLE LOADING")
    print("=" * 50)
    
    # Load .env file
    load_dotenv()
    
    # Check raw environment variables
    print("Raw environment variables:")
    env_vars = [
        "FOOTBALL_DATA_API_KEY",
        "API_FOOTBALL_API_KEY", 
        "FOOTBALL_DATA_KEY",
        "API_FOOTBALL_KEY",
        "ENVIRONMENT",
        "DEBUG"
    ]
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            if "KEY" in var:
                print(f"✅ {var}: {value[:10]}...")
            else:
                print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: Not found")
    
    # Test pydantic settings
    print("\nTesting pydantic settings:")
    try:
        from utils.config import settings
        print(f"✅ Settings loaded")
        print(f"   Environment: {settings.ENVIRONMENT}")
        print(f"   Debug: {settings.DEBUG}")
        print(f"   Football Data Key: {settings.football_data.API_KEY[:10]}..." if settings.football_data.API_KEY else "❌ No Football Data Key")
        print(f"   API Football Key: {settings.api_football.API_KEY[:10]}..." if settings.api_football.API_KEY else "❌ No API Football Key")
        
        # Test individual settings
        print("\nTesting individual settings:")
        from utils.config import FootballDataSettings, APIFootballSettings
        
        football_settings = FootballDataSettings()
        print(f"   Football Data Settings: {football_settings.API_KEY[:10]}..." if football_settings.API_KEY else "❌ No key")
        
        api_football_settings = APIFootballSettings()
        print(f"   API Football Settings: {api_football_settings.API_KEY[:10]}..." if api_football_settings.API_KEY else "❌ No key")
        
    except Exception as e:
        print(f"❌ Settings error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_env_loading()
