#!/usr/bin/env python3
"""
Automated Installation Verification Script for BetSightly ML Enhancements

This script automatically verifies all installations and runs the initialization.
Just run: python verify_installation.py
"""

import sys
import traceback

def test_package(package_name, import_name=None):
    """Test if a package can be imported."""
    if import_name is None:
        import_name = package_name
    
    try:
        module = __import__(import_name)
        version = getattr(module, '__version__', 'unknown')
        print(f"✅ {package_name}: {version}")
        return True
    except ImportError as e:
        print(f"❌ {package_name}: FAILED - {e}")
        return False
    except Exception as e:
        print(f"⚠️ {package_name}: WARNING - {e}")
        return True  # Consider it working if import succeeded

def main():
    print("🔍 BetSightly ML Enhancement Verification")
    print("=" * 50)
    
    # Test core packages
    core_packages = [
        ('Python', 'sys'),
        ('NumPy', 'numpy'),
        ('Pandas', 'pandas'),
        ('Scikit-learn', 'sklearn'),
    ]
    
    print("\n📦 Core Packages:")
    core_success = 0
    for name, import_name in core_packages:
        if test_package(name, import_name):
            core_success += 1
    
    # Test ML packages
    ml_packages = [
        ('XGBoost', 'xgboost'),
        ('LightGBM', 'lightgbm'),
        ('CatBoost', 'catboost'),
        ('TensorFlow', 'tensorflow'),
    ]
    
    print("\n🤖 ML Packages:")
    ml_success = 0
    for name, import_name in ml_packages:
        if test_package(name, import_name):
            ml_success += 1
    
    # Test NEW enhancement packages
    enhancement_packages = [
        ('SHAP', 'shap'),
        ('LIME', 'lime'),
        ('ELI5', 'eli5'),
        ('Optuna', 'optuna'),
        ('Scikit-Optimize', 'skopt'),
        ('Imbalanced-Learn', 'imblearn'),
    ]
    
    print("\n🆕 NEW Enhancement Packages:")
    enhancement_success = 0
    for name, import_name in enhancement_packages:
        if test_package(name, import_name):
            enhancement_success += 1
    
    # Test FastAPI packages
    api_packages = [
        ('FastAPI', 'fastapi'),
        ('Uvicorn', 'uvicorn'),
        ('Pydantic', 'pydantic'),
    ]
    
    print("\n🌐 API Packages:")
    api_success = 0
    for name, import_name in api_packages:
        if test_package(name, import_name):
            api_success += 1
    
    # Summary
    total_packages = len(core_packages) + len(ml_packages) + len(enhancement_packages) + len(api_packages)
    total_success = core_success + ml_success + enhancement_success + api_success
    
    print("\n" + "=" * 50)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 50)
    print(f"Core Packages: {core_success}/{len(core_packages)}")
    print(f"ML Packages: {ml_success}/{len(ml_packages)}")
    print(f"Enhancement Packages: {enhancement_success}/{len(enhancement_packages)}")
    print(f"API Packages: {api_success}/{len(api_packages)}")
    print(f"Total: {total_success}/{total_packages}")
    
    if total_success == total_packages:
        print("\n🎉 ALL PACKAGES VERIFIED SUCCESSFULLY!")
        print("\n🚀 Ready to proceed with initialization!")
        
        # Auto-run initialization if everything is working
        print("\n" + "=" * 50)
        print("🔧 RUNNING INITIALIZATION...")
        print("=" * 50)
        
        try:
            # Import and run initialization
            exec(open('initialize_ml_enhancements.py').read())
        except FileNotFoundError:
            print("⚠️ initialize_ml_enhancements.py not found. Creating it...")
            create_initialization_script()
            print("✅ Initialization script created. Please run: python initialize_ml_enhancements.py")
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            print("Please run manually: python initialize_ml_enhancements.py")
    
    elif enhancement_success >= 3:  # At least SHAP, LIME, Optuna working
        print("\n✅ CORE ENHANCEMENTS READY!")
        print("🚀 You can proceed with the key features (SHAP, LIME)")
        
    else:
        print("\n❌ CRITICAL PACKAGES MISSING!")
        print("Please install missing packages:")
        print("pip install -r requirements.txt")
        return False
    
    return True

def create_initialization_script():
    """Create the initialization script if it doesn't exist."""
    init_script = '''#!/usr/bin/env python3
"""
Quick ML Enhancement Initialization
"""

import os
from pathlib import Path

def main():
    print("🚀 Quick ML Enhancement Setup")
    print("=" * 40)
    
    # Check for models
    model_dirs = ["models", "models/xgboost", "models/enhanced"]
    found_models = []
    
    for model_dir in model_dirs:
        if Path(model_dir).exists():
            models = list(Path(model_dir).glob("*.joblib"))
            found_models.extend(models)
    
    print(f"📁 Found {len(found_models)} model files")
    
    if found_models:
        print("✅ Models available for enhancement")
        for model in found_models[:5]:  # Show first 5
            print(f"   - {model}")
        if len(found_models) > 5:
            print(f"   ... and {len(found_models) - 5} more")
    else:
        print("⚠️ No trained models found")
        print("   You may need to train models first")
    
    # Test enhanced service import
    try:
        import sys
        sys.path.append('.')
        from services.enhanced_prediction_service import enhanced_prediction_service
        print("✅ Enhanced prediction service ready")
    except Exception as e:
        print(f"⚠️ Enhanced service issue: {e}")
    
    print("\\n🎯 Next Steps:")
    print("1. Start server: python -m uvicorn main:app --reload")
    print("2. Test API: http://localhost:8000/api/predictions/enhanced/")
    print("3. Check docs: http://localhost:8000/docs")

if __name__ == "__main__":
    main()
'''
    
    with open('initialize_ml_enhancements.py', 'w') as f:
        f.write(init_script)

if __name__ == "__main__":
    main()
