#!/usr/bin/env python3
"""
Heroku Deployment Script for BetSightly Backend

This script prepares and deploys the codebase to Heroku.
"""

import os
import sys
import subprocess
import json
from pathlib import Path

def check_heroku_cli():
    """Check if Heroku CLI is installed."""
    try:
        result = subprocess.run(['heroku', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Heroku CLI: {result.stdout.strip()}")
            return True
        else:
            print("❌ Heroku CLI not found")
            return False
    except FileNotFoundError:
        print("❌ Heroku CLI not installed")
        print("💡 Install from: https://devcenter.heroku.com/articles/heroku-cli")
        return False

def login_heroku():
    """Login to Heroku."""
    print("🔐 Logging into Heroku...")
    try:
        result = subprocess.run(['heroku', 'auth:whoami'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Logged in as: {result.stdout.strip()}")
            return True
        else:
            print("❌ Not logged in to Heroku")
            print("💡 Run: heroku login")
            return False
    except Exception as e:
        print(f"❌ Error checking Heroku login: {e}")
        return False

def create_heroku_app(app_name="betsightly-backend"):
    """Create Heroku app."""
    print(f"🏗️  Creating Heroku app: {app_name}")
    try:
        result = subprocess.run(['heroku', 'create', app_name], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ App created: {app_name}")
            return True
        elif "Name is already taken" in result.stderr:
            print(f"⚠️  App {app_name} already exists, using existing app")
            return True
        else:
            print(f"❌ Failed to create app: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Error creating app: {e}")
        return False

def add_postgresql(app_name="betsightly-backend"):
    """Add PostgreSQL to Heroku app."""
    print("🗄️  Adding PostgreSQL database...")
    try:
        result = subprocess.run(['heroku', 'addons:create', 'heroku-postgresql:mini', '-a', app_name], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ PostgreSQL database added")
            return True
        else:
            print(f"❌ Failed to add PostgreSQL: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Error adding PostgreSQL: {e}")
        return False

def set_environment_variables(app_name="betsightly-backend"):
    """Set environment variables."""
    print("🔧 Setting environment variables...")
    
    env_vars = {
        'ENVIRONMENT': 'production',
        'DEBUG': 'false',
        'SECRET_KEY': 'betsightly-super-secret-production-key-2024'
    }
    
    for key, value in env_vars.items():
        try:
            result = subprocess.run(['heroku', 'config:set', f'{key}={value}', '-a', app_name], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✅ Set {key}")
            else:
                print(f"❌ Failed to set {key}: {result.stderr}")
        except Exception as e:
            print(f"❌ Error setting {key}: {e}")

def deploy_to_heroku(app_name="betsightly-backend"):
    """Deploy to Heroku."""
    print("🚀 Deploying to Heroku...")
    
    # Copy requirements for Heroku
    try:
        subprocess.run(['cp', 'requirements-heroku.txt', 'requirements.txt'], check=True)
        print("✅ Requirements file prepared")
    except:
        # Windows fallback
        try:
            subprocess.run(['copy', 'requirements-heroku.txt', 'requirements.txt'], shell=True, check=True)
            print("✅ Requirements file prepared")
        except Exception as e:
            print(f"❌ Failed to prepare requirements: {e}")
            return False
    
    # Add git remote
    try:
        result = subprocess.run(['heroku', 'git:remote', '-a', app_name], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Git remote added")
        else:
            print(f"⚠️  Git remote: {result.stderr}")
    except Exception as e:
        print(f"❌ Error adding git remote: {e}")
    
    # Deploy
    try:
        print("📤 Pushing to Heroku...")
        result = subprocess.run(['git', 'push', 'heroku', 'main'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ Deployment successful!")
            return True
        else:
            print(f"❌ Deployment failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Error during deployment: {e}")
        return False

def main():
    """Main deployment function."""
    print("🚀 BetSightly Heroku Deployment")
    print("=" * 50)
    
    app_name = input("Enter app name (default: betsightly-backend): ").strip()
    if not app_name:
        app_name = "betsightly-backend"
    
    # Check Heroku CLI
    if not check_heroku_cli():
        return False
    
    # Login to Heroku
    if not login_heroku():
        return False
    
    # Create app
    if not create_heroku_app(app_name):
        return False
    
    # Add PostgreSQL
    if not add_postgresql(app_name):
        return False
    
    # Set environment variables
    set_environment_variables(app_name)
    
    # Deploy
    if not deploy_to_heroku(app_name):
        return False
    
    print("\n" + "=" * 50)
    print("✅ HEROKU DEPLOYMENT COMPLETE!")
    print("=" * 50)
    print(f"\n🌐 Your app: https://{app_name}.herokuapp.com")
    print(f"🔧 Dashboard: https://dashboard.heroku.com/apps/{app_name}")
    print("\n📋 NEXT STEPS:")
    print("1. Add your API keys:")
    print(f"   heroku config:set FOOTBALL_DATA_API_KEY=your-key -a {app_name}")
    print(f"   heroku config:set API_FOOTBALL_API_KEY=your-key -a {app_name}")
    print(f"   heroku config:set TELEGRAM_BOT_TOKEN=your-token -a {app_name}")
    print("2. Test your endpoints:")
    print(f"   https://{app_name}.herokuapp.com/api/health")
    print(f"   https://{app_name}.herokuapp.com/api/predictions/")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
