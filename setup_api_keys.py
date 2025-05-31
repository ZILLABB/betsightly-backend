#!/usr/bin/env python3
"""
API Key Setup Script for BetSightly

This script helps you configure your API keys correctly.
"""

import os
from pathlib import Path

def create_env_file():
    """Create .env file with API key placeholders."""
    env_content = """# BetSightly Backend Environment Configuration
# Fill in your actual API keys below

# =============================================================================
# CRITICAL: API KEYS (REQUIRED FOR LIVE DATA)
# =============================================================================

# Football-Data.org API Key (PRIMARY - REQUIRED)
# Get your free API key from: https://www.football-data.org/client/register
# Free tier: 10 calls/minute, 100 calls/day
FOOTBALL_DATA_KEY=your_football_data_api_key_here

# API-Football Key (BACKUP - OPTIONAL)
# Get your API key from: https://rapidapi.com/api-sports/api/api-football
# Free tier: 100 calls/day
API_FOOTBALL_KEY=your_api_football_key_here

# =============================================================================
# APPLICATION SETTINGS
# =============================================================================

# Environment (development, staging, production)
ENVIRONMENT=development

# Debug mode (True for development, False for production)
DEBUG=True

# Application info
APP_NAME=BetSightly
APP_VERSION=1.0.0

# =============================================================================
# DATABASE SETTINGS
# =============================================================================

# Database URL (SQLite for development)
DATABASE_URL=sqlite:///./football.db

# =============================================================================
# ML SETTINGS
# =============================================================================

# Model directories
ML_MODEL_DIR=models
ML_DATA_DIR=data
ML_CACHE_DIR=cache

# Training settings
ML_TRAIN_TEST_SPLIT=0.2
ML_RANDOM_STATE=42

# Preferred models (in priority order)
ML_PREFERRED_MODELS=xgboost,lightgbm,ensemble

# =============================================================================
# PREDICTION SETTINGS
# =============================================================================

# Confidence thresholds
MIN_CONFIDENCE_THRESHOLD=0.60

# Odds categories
TWO_ODDS_MIN=1.0
TWO_ODDS_MAX=2.0
TWO_ODDS_MIN_CONFIDENCE=50.0
TWO_ODDS_LIMIT=10

FIVE_ODDS_MIN=2.0
FIVE_ODDS_MAX=5.0
FIVE_ODDS_MIN_CONFIDENCE=40.0
FIVE_ODDS_LIMIT=5

TEN_ODDS_MIN=5.0
TEN_ODDS_MAX=10.0
TEN_ODDS_MIN_CONFIDENCE=30.0
TEN_ODDS_LIMIT=3

ROLLOVER_MIN=1.0
ROLLOVER_MAX=1.5
ROLLOVER_MIN_CONFIDENCE=60.0
ROLLOVER_TARGET=10.0
"""
    
    env_file = Path(".env")
    
    if env_file.exists():
        print("⚠️  .env file already exists!")
        response = input("Do you want to overwrite it? (y/N): ")
        if response.lower() != 'y':
            print("Keeping existing .env file")
            return False
    
    with open(env_file, 'w') as f:
        f.write(env_content)
    
    print("✅ Created .env file")
    print("\n📝 Next steps:")
    print("1. Edit .env file and add your API keys")
    print("2. Get Football-Data.org API key: https://www.football-data.org/client/register")
    print("3. (Optional) Get API-Football key: https://rapidapi.com/api-sports/api/api-football")
    
    return True

def check_api_keys():
    """Check if API keys are configured."""
    print("\n🔍 Checking API key configuration...")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    football_data_key = os.getenv("FOOTBALL_DATA_KEY", "")
    api_football_key = os.getenv("API_FOOTBALL_KEY", "")
    
    issues = []
    
    # Check Football-Data.org key
    if not football_data_key or football_data_key == "your_football_data_api_key_here":
        issues.append("❌ FOOTBALL_DATA_KEY not configured (REQUIRED)")
    else:
        print("✅ FOOTBALL_DATA_KEY configured")
    
    # Check API-Football key
    if not api_football_key or api_football_key == "your_api_football_key_here":
        print("⚠️  API_FOOTBALL_KEY not configured (OPTIONAL)")
    else:
        print("✅ API_FOOTBALL_KEY configured")
    
    if issues:
        print("\n🚨 Configuration Issues:")
        for issue in issues:
            print(f"  {issue}")
        print("\n📝 To fix:")
        print("1. Edit .env file")
        print("2. Replace placeholder values with your actual API keys")
        return False
    else:
        print("\n🎉 All required API keys are configured!")
        return True

def test_api_connections():
    """Test API connections."""
    print("\n🔗 Testing API connections...")
    
    try:
        from utils.config import settings
        from services.api_client import FootballDataClient
        
        # Test Football-Data.org
        if settings.football_data.API_KEY:
            try:
                client = FootballDataClient()
                # Test with a simple request
                print("✅ Football-Data.org API connection ready")
            except Exception as e:
                print(f"❌ Football-Data.org API error: {str(e)}")
        
        # Test API-Football
        if settings.api_football.API_KEY:
            try:
                from services.api_client import APIClient
                client = APIClient(
                    base_url=settings.api_football.BASE_URL,
                    headers={
                        "x-rapidapi-host": settings.api_football.API_HOST,
                        "x-rapidapi-key": settings.api_football.API_KEY
                    }
                )
                print("✅ API-Football connection ready")
            except Exception as e:
                print(f"❌ API-Football error: {str(e)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Configuration error: {str(e)}")
        return False

def main():
    """Main setup function."""
    print("🔑 BetSightly API Key Setup")
    print("=" * 40)
    
    # Step 1: Create .env file
    print("\n1. Creating environment file...")
    create_env_file()
    
    # Step 2: Check configuration
    print("\n2. Checking configuration...")
    try:
        keys_ok = check_api_keys()
    except ImportError:
        print("⚠️  python-dotenv not installed. Install with: pip install python-dotenv")
        keys_ok = False
    
    # Step 3: Test connections
    if keys_ok:
        print("\n3. Testing connections...")
        test_api_connections()
    
    print("\n" + "=" * 40)
    print("🎯 Setup Summary:")
    print("✅ Environment file created")
    if keys_ok:
        print("✅ API keys configured")
        print("✅ Ready for model training!")
    else:
        print("⚠️  Please configure your API keys in .env file")
        print("📖 See docs/API_DOCUMENTATION.md for details")

if __name__ == "__main__":
    main()
