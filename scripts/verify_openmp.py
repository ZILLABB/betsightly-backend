#!/usr/bin/env python3
"""
Script to verify that OpenMP is properly configured for XGBoost and LightGBM.
"""

import os
import sys
import time
import numpy as np
from sklearn.datasets import make_classification

def check_environment_variables():
    """Check if OpenMP environment variables are set."""
    print("=== OpenMP Environment Variables ===")
    openmp_path = os.environ.get('OPENMP_PATH')
    omp_num_threads = os.environ.get('OMP_NUM_THREADS')
    
    if openmp_path:
        print(f"✅ OPENMP_PATH: {openmp_path}")
    else:
        print("❌ OPENMP_PATH: Not set")
    
    if omp_num_threads:
        print(f"✅ OMP_NUM_THREADS: {omp_num_threads}")
    else:
        print("❌ OMP_NUM_THREADS: Not set")
    
    cflags = os.environ.get('CFLAGS')
    if cflags and '-fopenmp' in cflags:
        print(f"✅ CFLAGS: Contains -fopenmp")
    else:
        print("❌ CFLAGS: Missing or doesn't contain -fopenmp")
    
    ldflags = os.environ.get('LDFLAGS')
    if ldflags and '-lomp' in ldflags:
        print(f"✅ LDFLAGS: Contains -lomp")
    else:
        print("❌ LDFLAGS: Missing or doesn't contain -lomp")
    
    print()

def check_xgboost():
    """Check if XGBoost is available and properly configured."""
    print("=== XGBoost Configuration ===")
    try:
        import xgboost as xgb
        print("✅ XGBoost is installed")
        
        # Check XGBoost configuration
        config = xgb.get_config()
        print(f"XGBoost configuration: {config}")
        
        # Create a synthetic dataset
        X, y = make_classification(n_samples=10000, n_features=20, random_state=42)
        
        # Train a model with single thread
        xgb.config_context(nthread=1)
        start_time = time.time()
        model_single = xgb.XGBClassifier(n_estimators=100, random_state=42)
        model_single.fit(X, y)
        single_thread_time = time.time() - start_time
        print(f"Single-threaded training time: {single_thread_time:.2f} seconds")
        
        # Train a model with multiple threads
        num_threads = int(os.environ.get('OMP_NUM_THREADS', '4'))
        xgb.config_context(nthread=num_threads)
        start_time = time.time()
        model_multi = xgb.XGBClassifier(n_estimators=100, random_state=42)
        model_multi.fit(X, y)
        multi_thread_time = time.time() - start_time
        print(f"Multi-threaded ({num_threads} threads) training time: {multi_thread_time:.2f} seconds")
        
        # Calculate speedup
        speedup = single_thread_time / multi_thread_time
        print(f"Speedup: {speedup:.2f}x")
        
        if speedup > 1.5:
            print("✅ XGBoost is using multiple threads effectively")
        else:
            print("⚠️ XGBoost multi-threading may not be working optimally")
    
    except ImportError:
        print("❌ XGBoost is not installed")
    except Exception as e:
        print(f"❌ Error testing XGBoost: {str(e)}")
    
    print()

def check_lightgbm():
    """Check if LightGBM is available and properly configured."""
    print("=== LightGBM Configuration ===")
    try:
        import lightgbm as lgb
        print("✅ LightGBM is installed")
        
        # Create a synthetic dataset
        X, y = make_classification(n_samples=10000, n_features=20, random_state=42)
        
        # Train a model with single thread
        start_time = time.time()
        model_single = lgb.LGBMClassifier(n_estimators=100, random_state=42, n_jobs=1)
        model_single.fit(X, y)
        single_thread_time = time.time() - start_time
        print(f"Single-threaded training time: {single_thread_time:.2f} seconds")
        
        # Train a model with multiple threads
        num_threads = int(os.environ.get('OMP_NUM_THREADS', '4'))
        start_time = time.time()
        model_multi = lgb.LGBMClassifier(n_estimators=100, random_state=42, n_jobs=num_threads)
        model_multi.fit(X, y)
        multi_thread_time = time.time() - start_time
        print(f"Multi-threaded ({num_threads} threads) training time: {multi_thread_time:.2f} seconds")
        
        # Calculate speedup
        speedup = single_thread_time / multi_thread_time
        print(f"Speedup: {speedup:.2f}x")
        
        if speedup > 1.5:
            print("✅ LightGBM is using multiple threads effectively")
        else:
            print("⚠️ LightGBM multi-threading may not be working optimally")
    
    except ImportError:
        print("❌ LightGBM is not installed")
    except Exception as e:
        print(f"❌ Error testing LightGBM: {str(e)}")
    
    print()

def main():
    """Main function."""
    print("OpenMP Verification for ML Libraries\n")
    
    # Check environment variables
    check_environment_variables()
    
    # Check XGBoost
    check_xgboost()
    
    # Check LightGBM
    check_lightgbm()
    
    print("=== Summary ===")
    print("If you see warnings or errors above, please follow these steps:")
    print("1. Install OpenMP: brew install libomp")
    print("2. Set environment variables:")
    print("   export OPENMP_PATH=$(brew --prefix libomp)")
    print("   export CFLAGS=\"-Xpreprocessor -fopenmp -I$OPENMP_PATH/include\"")
    print("   export CXXFLAGS=\"-Xpreprocessor -fopenmp -I$OPENMP_PATH/include\"")
    print("   export LDFLAGS=\"-L$OPENMP_PATH/lib -lomp\"")
    print("   export OMP_NUM_THREADS=4")
    print("3. Reinstall XGBoost and LightGBM:")
    print("   pip uninstall -y xgboost lightgbm")
    print("   pip install xgboost lightgbm --no-binary :all:")
    print("\nFor more details, see docs/OpenMP_Installation_Guide_macOS.md")

if __name__ == "__main__":
    main()
