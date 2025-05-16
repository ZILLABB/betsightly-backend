#!/usr/bin/env python3
"""
Script to update ML model training scripts to better handle OpenMP.
This script modifies the train_enhanced_github_models.py file to properly
configure XGBoost and LightGBM with OpenMP.
"""

import os
import re
import sys
import shutil
from pathlib import Path

def backup_file(file_path):
    """Create a backup of the file."""
    backup_path = f"{file_path}.bak"
    shutil.copy2(file_path, backup_path)
    print(f"Created backup at {backup_path}")

def update_openmp_handling(file_path):
    """Update OpenMP handling in the ML model training script."""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Define the new OpenMP handling code
    new_openmp_code = """# Configure OpenMP for XGBoost and LightGBM
import os

# Check for OpenMP environment variables
openmp_path = os.environ.get('OPENMP_PATH')
if openmp_path:
    logger.info(f"OpenMP found at {openmp_path}")
    # Set environment variables for OpenMP
    os.environ['OMP_NUM_THREADS'] = os.environ.get('OMP_NUM_THREADS', '4')
    logger.info(f"Using {os.environ['OMP_NUM_THREADS']} OpenMP threads")
else:
    logger.warning("OpenMP path not found in environment variables")
    logger.warning("Setting OMP_NUM_THREADS=1 to avoid OpenMP issues")
    os.environ['OMP_NUM_THREADS'] = '1'

# Import XGBoost with proper error handling
try:
    import xgboost as xgb
    # Configure XGBoost
    if openmp_path:
        # Use OpenMP with multiple threads
        xgb_params = {
            'verbosity': 0,
            'nthread': int(os.environ['OMP_NUM_THREADS']),
            'tree_method': 'hist'
        }
        xgb.config_context(**xgb_params)
        XGBOOST_AVAILABLE = True
        logger.info(f"XGBoost is available and configured with OpenMP ({os.environ['OMP_NUM_THREADS']} threads)")
    else:
        # Use single thread to avoid OpenMP issues
        xgb.config_context(verbosity=0, nthread=1)
        XGBOOST_AVAILABLE = True
        logger.info("XGBoost is available and configured in single-threaded mode")
except (ImportError, Exception) as e:
    XGBOOST_AVAILABLE = False
    logger.warning(f"XGBoost not available: {str(e)}")
    logger.warning("For Mac users, install OpenMP with: brew install libomp")
    logger.warning("Ensemble models will continue without XGBoost")

# Import LightGBM with proper error handling
try:
    import lightgbm as lgb
    # Configure LightGBM
    if openmp_path:
        # Use OpenMP with multiple threads
        LIGHTGBM_AVAILABLE = True
        logger.info(f"LightGBM is available and configured with OpenMP ({os.environ['OMP_NUM_THREADS']} threads)")
    else:
        # Use single thread to avoid OpenMP issues
        LIGHTGBM_AVAILABLE = True
        logger.info("LightGBM is available and configured in single-threaded mode")
except (ImportError, Exception) as e:
    LIGHTGBM_AVAILABLE = False
    logger.warning(f"LightGBM not available: {str(e)}")
    logger.warning("For Mac users, you may need to install additional dependencies")
    logger.warning("Ensemble models will continue without LightGBM")"""
    
    # Find the pattern to replace
    pattern = r"# Import XGBoost and LightGBM if available.*?# This is a duplicate logging setup, removed"
    pattern_flags = re.DOTALL
    
    # Replace the pattern with the new code
    updated_content = re.sub(pattern, new_openmp_code, content, flags=pattern_flags)
    
    # Update XGBoost parameters in the model creation
    xgb_pattern = r"xgb\.XGBClassifier\(\s*n_estimators=\d+,\s*max_depth=\d+,\s*learning_rate=[\d\.]+,\s*random_state=\d+,\s*n_jobs=[\d\-]+,\s*use_label_encoder=False,\s*eval_metric=['\w]+"
    xgb_replacement = """xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=int(os.environ.get('OMP_NUM_THREADS', '1')),
                use_label_encoder=False,
                eval_metric='mlogloss'"""
    
    updated_content = re.sub(xgb_pattern, xgb_replacement, updated_content)
    
    # Update LightGBM parameters in the model creation
    lgb_pattern = r"lgb\.LGBMClassifier\(\s*n_estimators=\d+,\s*max_depth=\d+,\s*learning_rate=[\d\.]+,\s*random_state=\d+,\s*n_jobs=[\d\-]+(?:,\s*verbose=[\d\-]+)?(?:,\s*force_row_wise=\w+)?"
    lgb_replacement = """lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=int(os.environ.get('OMP_NUM_THREADS', '1')),
                verbose=-1"""
    
    updated_content = re.sub(lgb_pattern, lgb_replacement, updated_content)
    
    # Write the updated content back to the file
    with open(file_path, 'w') as f:
        f.write(updated_content)
    
    print(f"Updated OpenMP handling in {file_path}")

def main():
    """Main function."""
    # Find the train_enhanced_github_models.py file
    script_dir = Path(__file__).parent
    target_file = script_dir / "train_enhanced_github_models.py"
    
    if not target_file.exists():
        # Try to find it in the parent directory
        target_file = script_dir.parent / "scripts" / "train_enhanced_github_models.py"
    
    if not target_file.exists():
        print(f"Error: Could not find train_enhanced_github_models.py")
        sys.exit(1)
    
    print(f"Found target file at {target_file}")
    
    # Create a backup of the file
    backup_file(target_file)
    
    # Update OpenMP handling
    update_openmp_handling(target_file)
    
    print("Script updated successfully!")
    print("\nTo use the updated script with OpenMP:")
    print("1. Install OpenMP with 'brew install libomp'")
    print("2. Set the environment variables:")
    print("   export OPENMP_PATH=$(brew --prefix libomp)")
    print("   export CFLAGS=\"-Xpreprocessor -fopenmp -I$OPENMP_PATH/include\"")
    print("   export CXXFLAGS=\"-Xpreprocessor -fopenmp -I$OPENMP_PATH/include\"")
    print("   export LDFLAGS=\"-L$OPENMP_PATH/lib -lomp\"")
    print("   export OMP_NUM_THREADS=4")
    print("3. Reinstall XGBoost and LightGBM:")
    print("   pip uninstall -y xgboost lightgbm")
    print("   pip install xgboost lightgbm --no-binary :all:")
    print("4. Run the updated script:")
    print("   python scripts/train_enhanced_github_models.py --ensemble --force")

if __name__ == "__main__":
    main()
