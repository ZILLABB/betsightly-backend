#!/usr/bin/env python3
"""
Render Deployment Script for BetSightly Backend

This script prepares and validates the codebase for Render deployment.
"""

import os
import sys
import subprocess
import json
from pathlib import Path

def check_requirements():
    """Check if all required files exist."""
    required_files = [
        'main.py',
        'requirements-render.txt',
        'render.yaml',
        'Procfile',
        'runtime.txt'
    ]
    
    missing_files = []
    for file in required_files:
        if not Path(file).exists():
            missing_files.append(file)
    
    if missing_files:
        print(f"❌ Missing required files: {missing_files}")
        return False
    
    print("✅ All required files present")
    return True

def validate_environment():
    """Validate environment configuration."""
    print("🔍 Validating environment configuration...")
    
    # Check if .env file exists
    if Path('.env').exists():
        print("✅ .env file found")
    else:
        print("⚠️  No .env file found - will use environment variables")
    
    # Check Python version
    python_version = sys.version_info
    if python_version.major == 3 and python_version.minor >= 11:
        print(f"✅ Python version: {python_version.major}.{python_version.minor}")
    else:
        print(f"⚠️  Python version {python_version.major}.{python_version.minor} - recommend 3.11+")
    
    return True

def test_imports():
    """Test critical imports."""
    print("🧪 Testing critical imports...")
    
    try:
        import fastapi
        print(f"✅ FastAPI: {fastapi.__version__}")
    except ImportError:
        print("❌ FastAPI not installed")
        return False
    
    try:
        import uvicorn
        print(f"✅ Uvicorn: {uvicorn.__version__}")
    except ImportError:
        print("❌ Uvicorn not installed")
        return False
    
    try:
        import gunicorn
        print(f"✅ Gunicorn: {gunicorn.__version__}")
    except ImportError:
        print("❌ Gunicorn not installed")
        return False
    
    return True

def create_deployment_summary():
    """Create deployment summary."""
    summary = {
        "platform": "Render",
        "app_name": "betsightly-backend",
        "python_version": "3.11.7",
        "start_command": "gunicorn main:app --host 0.0.0.0 --port $PORT --workers 2 --worker-class uvicorn.workers.UvicornWorker",
        "health_check": "/api/health",
        "database": "PostgreSQL (free tier)",
        "environment_variables": [
            "ENVIRONMENT=production",
            "DEBUG=false",
            "DATABASE_URL (auto-generated)",
            "SECRET_KEY (auto-generated)",
            "FOOTBALL_DATA_API_KEY (manual)",
            "API_FOOTBALL_API_KEY (manual)",
            "TELEGRAM_BOT_TOKEN (manual)"
        ],
        "estimated_cost": "$0/month (free tier)",
        "deployment_time": "5-10 minutes"
    }
    
    with open('deployment_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)
    
    print("📋 Deployment summary created: deployment_summary.json")

def main():
    """Main deployment preparation function."""
    print("🚀 BetSightly Render Deployment Preparation")
    print("=" * 50)
    
    # Check requirements
    if not check_requirements():
        print("❌ Deployment preparation failed")
        return False
    
    # Validate environment
    if not validate_environment():
        print("❌ Environment validation failed")
        return False
    
    # Test imports
    if not test_imports():
        print("❌ Import testing failed")
        print("💡 Run: pip install -r requirements-render.txt")
        return False
    
    # Create deployment summary
    create_deployment_summary()
    
    print("\n" + "=" * 50)
    print("✅ RENDER DEPLOYMENT READY!")
    print("=" * 50)
    print("\n📋 NEXT STEPS:")
    print("1. Push code to GitHub")
    print("2. Go to render.com and sign up")
    print("3. Connect your GitHub repository")
    print("4. Choose 'Blueprint' deployment")
    print("5. Select render.yaml file")
    print("6. Add your API keys in environment variables")
    print("7. Deploy!")
    print("\n🔗 Render Dashboard: https://dashboard.render.com")
    print("📚 Documentation: https://render.com/docs")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
