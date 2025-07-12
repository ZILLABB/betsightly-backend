#!/usr/bin/env python3
"""
Comprehensive BetSightly Backend Analysis
"""

import sys
import traceback
import requests
import json
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import os

def analyze_project_structure():
    """Analyze the project structure and organization."""
    print("🏗️ PROJECT STRUCTURE ANALYSIS")
    print("=" * 50)
    
    # Key directories to check
    key_dirs = [
        "api", "api/endpoints", "ml", "services", "utils", 
        "basketball", "models", "database", "tests"
    ]
    
    structure_score = 0
    for dir_path in key_dirs:
        if Path(dir_path).exists():
            files = list(Path(dir_path).glob("*.py"))
            print(f"✅ {dir_path}: {len(files)} Python files")
            structure_score += 1
        else:
            print(f"❌ {dir_path}: Missing")
    
    print(f"\n📊 Structure Score: {structure_score}/{len(key_dirs)} ({structure_score/len(key_dirs)*100:.1f}%)")
    return structure_score / len(key_dirs)

def analyze_dependencies():
    """Analyze dependencies and their status."""
    print("\n📦 DEPENDENCIES ANALYSIS")
    print("=" * 50)
    
    # Check requirements.txt
    if Path("requirements.txt").exists():
        with open("requirements.txt", "r") as f:
            requirements = f.read().strip().split("\n")
        
        print(f"✅ requirements.txt: {len(requirements)} dependencies")
        
        # Test key imports
        key_imports = [
            ("fastapi", "Web framework"),
            ("uvicorn", "ASGI server"),
            ("sqlalchemy", "Database ORM"),
            ("pandas", "Data processing"),
            ("numpy", "Numerical computing"),
            ("sklearn", "Machine learning"),
            ("xgboost", "XGBoost ML"),
            ("lightgbm", "LightGBM ML")
        ]
        
        import_score = 0
        for module, desc in key_imports:
            try:
                __import__(module)
                print(f"✅ {module}: {desc}")
                import_score += 1
            except ImportError:
                print(f"❌ {module}: {desc} - NOT AVAILABLE")
        
        print(f"\n📊 Import Score: {import_score}/{len(key_imports)} ({import_score/len(key_imports)*100:.1f}%)")
        return import_score / len(key_imports)
    else:
        print("❌ requirements.txt not found")
        return 0

def analyze_database():
    """Analyze database status and content."""
    print("\n🗄️ DATABASE ANALYSIS")
    print("=" * 50)
    
    db_file = "football.db"
    if not Path(db_file).exists():
        print(f"❌ Database file {db_file} not found")
        return 0
    
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Get tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cursor.fetchall()]
        print(f"✅ Database tables: {tables}")
        
        # Check data
        data_score = 0
        total_records = 0
        
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                total_records += count
                print(f"📊 {table}: {count} records")
                if count > 0:
                    data_score += 1
            except Exception as e:
                print(f"⚠️ {table}: Error - {str(e)}")
        
        conn.close()
        
        print(f"\n📊 Database Score: {data_score}/{len(tables)} tables with data")
        print(f"📊 Total Records: {total_records}")
        
        return data_score / len(tables) if tables else 0
        
    except Exception as e:
        print(f"❌ Database error: {str(e)}")
        return 0

def analyze_models():
    """Analyze ML models availability."""
    print("\n🤖 ML MODELS ANALYSIS")
    print("=" * 50)
    
    model_dirs = ["models", "models/xgboost", "models/enhanced", "models/advanced", "models/quick"]
    total_models = 0
    working_models = 0
    
    for model_dir in model_dirs:
        if Path(model_dir).exists():
            model_files = list(Path(model_dir).glob("*.joblib"))
            total_models += len(model_files)
            print(f"✅ {model_dir}: {len(model_files)} model files")
            
            # Test loading a few models
            for model_file in model_files[:2]:  # Test first 2 models
                try:
                    import joblib
                    model = joblib.load(model_file)
                    working_models += 1
                    print(f"  ✅ {model_file.name}: Loadable")
                except Exception as e:
                    print(f"  ❌ {model_file.name}: Error - {str(e)}")
        else:
            print(f"❌ {model_dir}: Not found")
    
    # Check basketball models
    basketball_models_dir = Path("basketball/models")
    if basketball_models_dir.exists():
        basketball_models = list(basketball_models_dir.glob("*.joblib"))
        print(f"🏀 Basketball models: {len(basketball_models)} files")
        total_models += len(basketball_models)
    else:
        print("🏀 Basketball models: Directory not found")
    
    print(f"\n📊 Models Score: {working_models}/{total_models} models working")
    return working_models / total_models if total_models > 0 else 0

def test_api_endpoints():
    """Test API endpoints functionality."""
    print("\n🌐 API ENDPOINTS TESTING")
    print("=" * 50)
    
    # Test basic imports first
    try:
        from main import app
        print("✅ Main app imports successfully")
        
        from api.endpoints.health import health_check
        health_result = health_check()
        print(f"✅ Health endpoint: {health_result['status']}")
        
        # Test prediction service
        from services.quick_prediction_service import quick_prediction_service
        print("✅ Quick prediction service available")
        
        # Test basketball service
        try:
            from basketball.prediction_service import BasketballPredictionService
            basketball_service = BasketballPredictionService()
            print("✅ Basketball prediction service available")
        except Exception as e:
            print(f"⚠️ Basketball service issue: {str(e)}")
        
        return True
        
    except Exception as e:
        print(f"❌ API testing failed: {str(e)}")
        traceback.print_exc()
        return False

def analyze_configuration():
    """Analyze configuration and environment setup."""
    print("\n⚙️ CONFIGURATION ANALYSIS")
    print("=" * 50)
    
    config_score = 0
    total_checks = 4
    
    # Check .env file
    if Path(".env").exists():
        print("✅ .env file exists")
        config_score += 1
        
        # Check for API keys
        with open(".env", "r") as f:
            env_content = f.read()
        
        if "FOOTBALL_DATA_KEY" in env_content:
            print("✅ Football Data API key configured")
            config_score += 1
        else:
            print("❌ Football Data API key missing")
            
        if "API_FOOTBALL_KEY" in env_content:
            print("✅ API Football key configured")
            config_score += 1
        else:
            print("❌ API Football key missing")
    else:
        print("❌ .env file not found")
    
    # Check config module
    try:
        from utils.config import settings
        print("✅ Configuration module loads successfully")
        config_score += 1
    except Exception as e:
        print(f"❌ Configuration module error: {str(e)}")
    
    print(f"\n📊 Configuration Score: {config_score}/{total_checks} ({config_score/total_checks*100:.1f}%)")
    return config_score / total_checks

def generate_recommendations(scores):
    """Generate recommendations based on analysis."""
    print("\n🎯 RECOMMENDATIONS")
    print("=" * 50)
    
    structure_score, deps_score, db_score, models_score, api_score, config_score = scores
    
    # Critical issues (score < 0.5)
    critical_issues = []
    if deps_score < 0.5:
        critical_issues.append("Missing critical dependencies")
    if config_score < 0.5:
        critical_issues.append("Configuration issues")
    if not api_score:
        critical_issues.append("API endpoints not working")
    
    # High priority issues (score < 0.7)
    high_priority = []
    if models_score < 0.7:
        high_priority.append("ML models need attention")
    if db_score < 0.7:
        high_priority.append("Database needs data")
    
    # Medium priority issues (score < 0.9)
    medium_priority = []
    if structure_score < 0.9:
        medium_priority.append("Project structure improvements")
    
    print("🔴 CRITICAL ISSUES:")
    for issue in critical_issues:
        print(f"  - {issue}")
    
    print("\n🟡 HIGH PRIORITY:")
    for issue in high_priority:
        print(f"  - {issue}")
    
    print("\n🟢 MEDIUM PRIORITY:")
    for issue in medium_priority:
        print(f"  - {issue}")
    
    # Overall health
    overall_score = sum(scores) / len(scores)
    print(f"\n📊 OVERALL HEALTH: {overall_score*100:.1f}%")
    
    if overall_score >= 0.8:
        print("🎉 System is in good health!")
    elif overall_score >= 0.6:
        print("⚠️ System needs some attention")
    else:
        print("🚨 System needs significant work")

def main():
    """Run comprehensive analysis."""
    print("🔍 BETSIGHTLY BACKEND COMPREHENSIVE ANALYSIS")
    print("=" * 60)
    print(f"📅 Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Run all analyses
    structure_score = analyze_project_structure()
    deps_score = analyze_dependencies()
    db_score = analyze_database()
    models_score = analyze_models()
    api_score = 1.0 if test_api_endpoints() else 0.0
    config_score = analyze_configuration()
    
    # Generate recommendations
    scores = [structure_score, deps_score, db_score, models_score, api_score, config_score]
    generate_recommendations(scores)
    
    print("\n" + "=" * 60)
    print("✅ COMPREHENSIVE ANALYSIS COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    main()
