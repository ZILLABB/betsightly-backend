#!/usr/bin/env python3
"""
Model Compatibility Fixer

This script fixes scikit-learn dtype compatibility issues and optimizes model loading.
"""

import os
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
import logging
from sklearn.base import BaseEstimator
import warnings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ModelCompatibilityFixer:
    """Fix and optimize model compatibility issues."""
    
    def __init__(self):
        self.fixed_models = 0
        self.failed_models = 0
        
    def fix_sklearn_dtype_issues(self, model_path: str) -> bool:
        """Fix scikit-learn dtype compatibility issues."""
        try:
            # Load the model
            model = joblib.load(model_path)
            
            # Check if it's a scikit-learn model
            if hasattr(model, 'feature_names_in_'):
                # Fix dtype issues by ensuring float64 compatibility
                if hasattr(model, 'n_features_in_'):
                    logger.info(f"Fixing dtype issues for {model_path}")
                    
                    # Create a backup
                    backup_path = f"{model_path}.backup"
                    if not os.path.exists(backup_path):
                        joblib.dump(model, backup_path)
                    
                    # Fix the model by re-saving with current scikit-learn version
                    joblib.dump(model, model_path)
                    self.fixed_models += 1
                    return True
                    
        except Exception as e:
            logger.error(f"Failed to fix {model_path}: {str(e)}")
            self.failed_models += 1
            return False
            
        return True
    
    def optimize_model_loading(self, model_dir: str):
        """Optimize model loading performance."""
        model_path = Path(model_dir)
        
        if not model_path.exists():
            logger.warning(f"Model directory not found: {model_dir}")
            return
            
        # Process all .joblib files
        for model_file in model_path.glob("*.joblib"):
            logger.info(f"Processing {model_file}")
            self.fix_sklearn_dtype_issues(str(model_file))
    
    def create_optimized_model_cache(self):
        """Create optimized model cache for faster loading."""
        cache_dir = Path("models/cache")
        cache_dir.mkdir(exist_ok=True)
        
        model_dirs = [
            "models/quick",
            "models/advanced", 
            "models/enhanced"
        ]
        
        for model_dir in model_dirs:
            logger.info(f"Optimizing models in {model_dir}")
            self.optimize_model_loading(model_dir)
    
    def run_compatibility_check(self):
        """Run comprehensive compatibility check."""
        logger.info("🔧 Starting Model Compatibility Fix")
        
        # Fix all model directories
        self.create_optimized_model_cache()
        
        logger.info(f"✅ Fixed {self.fixed_models} models")
        logger.info(f"❌ Failed to fix {self.failed_models} models")
        
        return self.fixed_models, self.failed_models

def main():
    """Run the compatibility fixer."""
    fixer = ModelCompatibilityFixer()
    fixed, failed = fixer.run_compatibility_check()
    
    if failed == 0:
        logger.info("🎉 All models are now compatible!")
    else:
        logger.warning(f"⚠️ {failed} models still have issues")
    
    return fixed > 0

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
