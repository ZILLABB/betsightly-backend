#!/usr/bin/env python3
"""
Initialize ML Enhancements for BetSightly

This script initializes the new ML enhancement features:
1. Model explainers (SHAP/LIME)
2. Meta-model stacking
3. Enhanced prediction service
"""

import os
import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def check_dependencies():
    """Check if all required dependencies are installed."""
    logger.info("Checking dependencies...")
    
    required_packages = ['shap', 'lime', 'optuna', 'pandas', 'numpy', 'joblib']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
            logger.info(f"✅ {package} is available")
        except ImportError:
            missing_packages.append(package)
            logger.error(f"❌ {package} is missing")
    
    if missing_packages:
        logger.error(f"Missing packages: {missing_packages}")
        logger.error("Please run: pip install -r requirements.txt")
        return False
    
    logger.info("✅ All dependencies are available")
    return True

def check_existing_models():
    """Check what trained models are available."""
    logger.info("Checking existing trained models...")
    
    model_dirs = [
        "models/xgboost",
        "models/enhanced", 
        "models/advanced",
        "models"
    ]
    
    found_models = []
    
    for model_dir in model_dirs:
        model_path = Path(model_dir)
        if model_path.exists():
            model_files = list(model_path.glob("*.joblib"))
            for model_file in model_files:
                found_models.append(str(model_file))
                logger.info(f"✅ Found model: {model_file}")
    
    if not found_models:
        logger.warning("❌ No trained models found. You may need to train models first.")
        return False
    
    logger.info(f"✅ Found {len(found_models)} trained models")
    return True

def initialize_explainers():
    """Initialize model explainers for existing models."""
    logger.info("Initializing model explainers...")
    
    try:
        from ml.model_explainer import model_explainer
        
        # Define feature names (basic set - you can expand this)
        feature_names = [
            'home_form', 'away_form', 'home_attack', 'home_defense',
            'away_attack', 'away_defense', 'h2h_home_wins', 'h2h_away_wins',
            'h2h_draws', 'league_position_diff', 'recent_goals_scored_home',
            'recent_goals_conceded_home', 'recent_goals_scored_away',
            'recent_goals_conceded_away', 'is_derby', 'is_important_match'
        ]
        
        # Try to initialize explainers for XGBoost models
        xgboost_models = {
            'match_result': 'models/xgboost/match_result_model.joblib',
            'over_under': 'models/xgboost/over_2_5_model.joblib',
            'btts': 'models/xgboost/btts_model.joblib'
        }
        
        initialized_count = 0
        
        for model_name, model_path in xgboost_models.items():
            if Path(model_path).exists():
                try:
                    model_explainer.initialize_explainers(
                        model_path, 
                        'xgboost', 
                        feature_names
                    )
                    logger.info(f"✅ Initialized explainer for {model_name}")
                    initialized_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to initialize explainer for {model_name}: {e}")
            else:
                logger.warning(f"⚠️ Model not found: {model_path}")
        
        if initialized_count > 0:
            logger.info(f"✅ Successfully initialized {initialized_count} explainers")
            return True
        else:
            logger.warning("❌ No explainers were initialized")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize explainers: {e}")
        return False

def initialize_meta_stacking():
    """Initialize meta-model stacking."""
    logger.info("Initializing meta-model stacking...")
    
    try:
        from ml.meta_model_stacking import meta_stacker
        
        # Register base models for meta-stacking
        model_registrations = [
            ('match_result', 'xgboost', 'models/xgboost/match_result_model.joblib'),
            ('over_under', 'xgboost', 'models/xgboost/over_2_5_model.joblib'),
            ('btts', 'xgboost', 'models/xgboost/btts_model.joblib'),
            ('match_result', 'ensemble', 'models/match_result_model.joblib'),
            ('over_under', 'ensemble', 'models/over_under_model.joblib'),
            ('btts', 'ensemble', 'models/btts_model.joblib'),
        ]
        
        registered_count = 0
        
        for pred_type, model_type, model_path in model_registrations:
            if Path(model_path).exists():
                try:
                    meta_stacker.register_base_model(pred_type, model_type, model_path)
                    logger.info(f"✅ Registered {model_type} model for {pred_type}")
                    registered_count += 1
                except Exception as e:
                    logger.error(f"❌ Failed to register {model_type} for {pred_type}: {e}")
            else:
                logger.warning(f"⚠️ Model not found: {model_path}")
        
        if registered_count > 0:
            logger.info(f"✅ Successfully registered {registered_count} models for meta-stacking")
            return True
        else:
            logger.warning("❌ No models were registered for meta-stacking")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to initialize meta-stacking: {e}")
        return False

def test_enhanced_service():
    """Test the enhanced prediction service."""
    logger.info("Testing enhanced prediction service...")
    
    try:
        from services.enhanced_prediction_service import enhanced_prediction_service
        
        # Test initialization
        logger.info("✅ Enhanced prediction service imported successfully")
        
        # You can add more specific tests here
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to test enhanced service: {e}")
        return False

def create_test_script():
    """Create a test script for the enhanced API."""
    test_script = """#!/usr/bin/env python3
'''
Test script for enhanced predictions API
'''

import requests
import json

def test_enhanced_api():
    base_url = "http://localhost:8000"
    
    # Test basic enhanced predictions
    print("Testing enhanced predictions API...")
    
    try:
        response = requests.get(f"{base_url}/api/predictions/enhanced/", params={
            "include_explanations": True,
            "explanation_detail": "human"
        })
        
        if response.status_code == 200:
            data = response.json()
            print("✅ Enhanced API is working!")
            print(f"Response keys: {list(data.keys())}")
            
            if "predictions" in data:
                print(f"Found {len(data['predictions'])} predictions")
            
            if "explanations_included" in data:
                print(f"Explanations included: {data['explanations_included']}")
                
        else:
            print(f"❌ API returned status code: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to API. Make sure the server is running:")
        print("   python -m uvicorn main:app --reload")
    except Exception as e:
        print(f"❌ Error testing API: {e}")

if __name__ == "__main__":
    test_enhanced_api()
"""
    
    with open("test_enhanced_api.py", "w") as f:
        f.write(test_script)
    
    logger.info("✅ Created test_enhanced_api.py script")

def main():
    """Main initialization function."""
    logger.info("🚀 Starting BetSightly ML Enhancement Initialization...")
    
    # Step 1: Check dependencies
    if not check_dependencies():
        logger.error("❌ Dependency check failed. Please install missing packages.")
        return False
    
    # Step 2: Check existing models
    if not check_existing_models():
        logger.warning("⚠️ No trained models found. Some features may not work.")
    
    # Step 3: Initialize explainers
    explainers_ok = initialize_explainers()
    
    # Step 4: Initialize meta-stacking
    stacking_ok = initialize_meta_stacking()
    
    # Step 5: Test enhanced service
    service_ok = test_enhanced_service()
    
    # Step 6: Create test script
    create_test_script()
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("🎯 INITIALIZATION SUMMARY")
    logger.info("="*50)
    logger.info(f"Dependencies: {'✅ OK' if True else '❌ FAILED'}")
    logger.info(f"Model Explainers: {'✅ OK' if explainers_ok else '❌ FAILED'}")
    logger.info(f"Meta-Stacking: {'✅ OK' if stacking_ok else '❌ FAILED'}")
    logger.info(f"Enhanced Service: {'✅ OK' if service_ok else '❌ FAILED'}")
    
    if explainers_ok or stacking_ok:
        logger.info("\n🎉 ML Enhancements are ready!")
        logger.info("\nNext steps:")
        logger.info("1. Start the server: python -m uvicorn main:app --reload")
        logger.info("2. Test the API: python test_enhanced_api.py")
        logger.info("3. Try the enhanced endpoint: /api/predictions/enhanced/")
    else:
        logger.warning("\n⚠️ Some features may not work properly.")
        logger.warning("Consider training models first or checking the setup.")
    
    return True

if __name__ == "__main__":
    main()
