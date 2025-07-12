#!/usr/bin/env python3
"""
Test Enhanced ML Models

This script tests the newly activated ML models to ensure they're working correctly.
"""

import os
import sys
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_model_factory():
    """Test the model factory and available models."""
    try:
        from ml.model_factory import model_factory
        
        logger.info("🧪 Testing Model Factory...")
        
        # Get available models
        available_models = model_factory.get_available_models()
        logger.info(f"✅ Available models: {available_models}")
        
        # Test creating each model
        for model_type in available_models:
            try:
                model = model_factory.create_model(model_type)
                if model is not None:
                    logger.info(f"✅ Successfully created model: {model_type}")
                    
                    # Test model info
                    try:
                        info = model_factory.get_model_info(model_type)
                        logger.info(f"   Model info: {info}")
                    except Exception as e:
                        logger.warning(f"   Could not get model info: {str(e)}")
                else:
                    logger.warning(f"⚠️  Failed to create model: {model_type}")
            except Exception as e:
                logger.error(f"❌ Error creating model {model_type}: {str(e)}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Model factory test failed: {str(e)}")
        return False

def test_advanced_prediction_service():
    """Test the advanced prediction service with enhanced models."""
    try:
        from services.advanced_prediction_service import AdvancedPredictionService
        
        logger.info("🧪 Testing Advanced Prediction Service...")
        
        # Initialize service
        service = AdvancedPredictionService()
        
        # Get model info
        model_info = service.get_model_info()
        logger.info(f"✅ Total models loaded: {model_info['total_models']}")
        logger.info(f"✅ Model types: {model_info['model_types']}")
        logger.info(f"✅ Advanced features: {model_info['advanced_features']}")
        
        # List all loaded models
        logger.info("📋 Loaded models:")
        for model_name in model_info['models']:
            logger.info(f"   - {model_name}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Advanced prediction service test failed: {str(e)}")
        return False

def test_individual_ml_models():
    """Test individual ML model types."""
    logger.info("🧪 Testing Individual ML Models...")
    
    # Test LightGBM
    try:
        from ml.lightgbm_models import LightGBMBTTSModel
        model = LightGBMBTTSModel()
        logger.info("✅ LightGBM model created successfully")
    except Exception as e:
        logger.error(f"❌ LightGBM model test failed: {str(e)}")
    
    # Test Neural Network
    try:
        from ml.neural_network_models import NeuralNetworkOverUnderModel
        model = NeuralNetworkOverUnderModel(threshold=2.5)
        logger.info("✅ Neural Network model created successfully")
    except Exception as e:
        logger.error(f"❌ Neural Network model test failed: {str(e)}")
    
    # Test LSTM
    try:
        from ml.lstm_models import LSTMTeamFormModel
        model = LSTMTeamFormModel(prediction_type="match_result")
        logger.info("✅ LSTM model created successfully")
    except Exception as e:
        logger.error(f"❌ LSTM model test failed: {str(e)}")
    
    # Test Ensemble
    try:
        from ml.ensemble_model_improved import MatchResultModel, OverUnderModel, BTTSModel
        match_model = MatchResultModel()
        over_under_model = OverUnderModel()
        btts_model = BTTSModel()
        logger.info("✅ Ensemble models created successfully")
    except Exception as e:
        logger.error(f"❌ Ensemble model test failed: {str(e)}")

def test_model_directories():
    """Test that model directories exist and contain models."""
    logger.info("🧪 Testing Model Directories...")
    
    model_dirs = [
        "models/xgboost",
        "models/enhanced", 
        "models/advanced",
        "models/quick"
    ]
    
    for model_dir in model_dirs:
        if os.path.exists(model_dir):
            model_files = [f for f in os.listdir(model_dir) if f.endswith('.joblib')]
            logger.info(f"✅ {model_dir}: {len(model_files)} model files")
            for model_file in model_files[:3]:  # Show first 3
                logger.info(f"   - {model_file}")
            if len(model_files) > 3:
                logger.info(f"   ... and {len(model_files) - 3} more")
        else:
            logger.warning(f"⚠️  Directory not found: {model_dir}")

def main():
    """Run all tests."""
    logger.info("🚀 Starting Enhanced ML Models Test Suite")
    logger.info("=" * 60)
    
    tests = [
        ("Model Directories", test_model_directories),
        ("Individual ML Models", test_individual_ml_models),
        ("Model Factory", test_model_factory),
        ("Advanced Prediction Service", test_advanced_prediction_service),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        logger.info(f"\n📋 Running: {test_name}")
        logger.info("-" * 40)
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"❌ Test {test_name} failed with exception: {str(e)}")
            results[test_name] = False
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 TEST RESULTS SUMMARY")
    logger.info("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"{status}: {test_name}")
        if result:
            passed += 1
    
    logger.info(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! Enhanced ML models are working correctly.")
        return True
    else:
        logger.warning(f"⚠️  {total - passed} tests failed. Check the logs above for details.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
