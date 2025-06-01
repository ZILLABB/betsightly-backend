#!/usr/bin/env python3
"""
Check Training Status

Quick script to check if model training has completed.
"""

import os
from pathlib import Path

def check_training_status():
    """Check the status of model training."""
    print("🔍 CHECKING TRAINING STATUS")
    print("=" * 40)
    
    # Check if training data was downloaded
    training_data_file = "data/github_training_data.csv"
    if os.path.exists(training_data_file):
        file_size = os.path.getsize(training_data_file) / (1024 * 1024)  # MB
        print(f"✅ Training data downloaded: {file_size:.1f} MB")
    else:
        print("⏳ Training data still downloading...")
    
    # Check if models directory exists
    models_dir = Path("models/hybrid")
    if models_dir.exists():
        model_files = list(models_dir.glob("*.joblib"))
        print(f"✅ Models directory exists: {len(model_files)} model files")
        
        # List model files
        for model_file in model_files:
            file_size = model_file.stat().st_size / 1024  # KB
            print(f"  - {model_file.name} ({file_size:.1f} KB)")
    else:
        print("⏳ Models not yet created...")
    
    # Check if training is complete
    expected_models = [
        "xgboost_match_result_model.joblib",
        "xgboost_over_under_model.joblib", 
        "xgboost_btts_model.joblib",
        "ensemble_match_result_model.joblib",
        "ensemble_over_under_model.joblib",
        "ensemble_btts_model.joblib"
    ]
    
    if models_dir.exists():
        existing_models = [f.name for f in models_dir.glob("*.joblib")]
        completed_models = [m for m in expected_models if m in existing_models]
        
        print(f"\n📊 Training Progress: {len(completed_models)}/{len(expected_models)} models")
        
        if len(completed_models) == len(expected_models):
            print("🎉 TRAINING COMPLETED!")
            print("\n📝 Next steps:")
            print("1. Test predictions: curl http://localhost:8000/api/predictions/")
            print("2. Test enhanced: curl http://localhost:8000/api/predictions/enhanced/")
            return True
        else:
            print("⏳ Training still in progress...")
            missing = [m for m in expected_models if m not in existing_models]
            print(f"Missing: {missing}")
            return False
    else:
        print("⏳ Training not started yet...")
        return False

def check_api_status():
    """Check API server status."""
    print("\n🌐 CHECKING API STATUS")
    print("=" * 40)
    
    try:
        import requests
        response = requests.get("http://localhost:8000/api/health/", timeout=5)
        
        if response.status_code == 200:
            health_data = response.json()
            print(f"✅ API Server: {health_data.get('status', 'unknown')}")
            
            # Check detailed health
            try:
                detailed_response = requests.get("http://localhost:8000/api/health/detailed", timeout=5)
                if detailed_response.status_code == 200:
                    detailed_data = detailed_response.json()
                    api_keys = detailed_data.get("api_keys", {})
                    print(f"🔑 API Keys: {api_keys.get('status', 'unknown')}")
            except:
                pass
                
            return True
        else:
            print(f"❌ API Server error: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ API Server not responding: {str(e)}")
        print("💡 Start server: py -m uvicorn main:app --reload")
        return False

def main():
    """Main status check."""
    training_complete = check_training_status()
    api_running = check_api_status()
    
    print("\n" + "=" * 40)
    print("📊 OVERALL STATUS")
    print("=" * 40)
    
    print(f"Training: {'✅ Complete' if training_complete else '⏳ In Progress'}")
    print(f"API Server: {'✅ Running' if api_running else '❌ Not Running'}")
    
    if training_complete and api_running:
        print("\n🎉 SYSTEM READY!")
        print("You can now make predictions!")
    elif training_complete:
        print("\n⚠️  Training complete but API not running")
        print("Start API: py -m uvicorn main:app --reload")
    elif api_running:
        print("\n⚠️  API running but training not complete")
        print("Wait for training to finish or check training process")
    else:
        print("\n⚠️  System not ready")
        print("1. Start training: py train_models_hybrid.py")
        print("2. Start API: py -m uvicorn main:app --reload")

if __name__ == "__main__":
    main()
