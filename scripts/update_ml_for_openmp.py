#!/usr/bin/env python3
"""
Script to update ML model training scripts to properly use OpenMP on macOS.
This script modifies the train_enhanced_github_models.py file to correctly
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
    return backup_path

def find_training_script():
    """Find the ML model training script."""
    # Common locations to check
    possible_paths = [
        "scripts/train_enhanced_github_models.py",
        "backend/scripts/train_enhanced_github_models.py",
        "train_enhanced_github_models.py"
    ]
    
    # Start from the current directory
    current_dir = Path.cwd()
    
    # Check each possible path
    for path in possible_paths:
        full_path = current_dir / path
        if full_path.exists():
            return full_path
    
    # If not found, search recursively (limited depth)
    for root, dirs, files in os.walk(current_dir, topdown=True, followlinks=False):
        # Limit depth to avoid excessive searching
        if root.count(os.sep) - current_dir.count(os.sep) > 3:
            dirs.clear()  # Don't go deeper
            continue
            
        if "train_enhanced_github_models.py" in files:
            return Path(root) / "train_enhanced_github_models.py"
    
    return None

def update_openmp_imports(content):
    """Update the imports section to properly handle OpenMP."""
    # Define the new OpenMP handling code
    new_openmp_code = """# Configure OpenMP for XGBoost and LightGBM
import os

# Check for OpenMP environment variables
openmp_path = os.environ.get('OPENMP_PATH')
if openmp_path:
    logger.info(f"OpenMP found at {openmp_path}")
    # Set environment variables for OpenMP if not already set
    if 'OMP_NUM_THREADS' not in os.environ:
        os.environ['OMP_NUM_THREADS'] = '4'
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
    logger.warning("Ensemble models will continue without LightGBM")

try:
    from catboost import CatBoostClassifier
    CATBOOST_AVAILABLE = True
    logger.info("CatBoost is available and will be used in ensemble models")
except (ImportError, Exception) as e:
    CATBOOST_AVAILABLE = False
    logger.warning(f"CatBoost not available: {str(e)}")
    logger.warning("Ensemble models will continue without CatBoost")"""
    
    # Find the pattern to replace
    pattern = r"# Import XGBoost and LightGBM if available.*?CATBOOST_AVAILABLE = False.*?logger\.warning\(.*?\)"
    pattern_flags = re.DOTALL
    
    # Replace the pattern with the new code
    updated_content = re.sub(pattern, new_openmp_code, content, flags=pattern_flags)
    
    return updated_content

def update_xgboost_params(content):
    """Update XGBoost parameters to use OpenMP properly."""
    # Pattern to match XGBoost classifier initialization
    pattern = r"xgb\.XGBClassifier\(\s*n_estimators=\d+,\s*max_depth=\d+,\s*learning_rate=[\d\.]+,\s*random_state=\d+,\s*n_jobs=[\d\-]+,\s*use_label_encoder=\w+,\s*eval_metric=['\w]+(?:,\s*tree_method=['\w]+)?\s*\)"
    
    # New XGBoost parameters
    replacement = """xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=int(os.environ.get('OMP_NUM_THREADS', '1')),
                use_label_encoder=False,
                eval_metric='mlogloss',
                tree_method='hist'
            )"""
    
    # Replace all occurrences
    updated_content = re.sub(pattern, replacement, content)
    
    return updated_content

def update_lightgbm_params(content):
    """Update LightGBM parameters to use OpenMP properly."""
    # Pattern to match LightGBM classifier initialization
    pattern = r"lgb\.LGBMClassifier\(\s*n_estimators=\d+,\s*max_depth=\d+,\s*learning_rate=[\d\.]+,\s*random_state=\d+,\s*n_jobs=[\d\-]+(?:,\s*verbose=[\d\-]+)?(?:,\s*force_row_wise=\w+)?\s*\)"
    
    # New LightGBM parameters
    replacement = """lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.1,
                random_state=42,
                n_jobs=int(os.environ.get('OMP_NUM_THREADS', '1')),
                verbose=-1,
                force_row_wise=openmp_path is None  # Only force row-wise when OpenMP is not available
            )"""
    
    # Replace all occurrences
    updated_content = re.sub(pattern, replacement, content)
    
    return updated_content

def main():
    """Main function."""
    print("Searching for ML model training script...")
    script_path = find_training_script()
    
    if not script_path:
        print("Error: Could not find the ML model training script.")
        print("Please run this script from the project root directory.")
        sys.exit(1)
    
    print(f"Found ML model training script at: {script_path}")
    
    # Create a backup of the file
    backup_path = backup_file(script_path)
    print(f"Created backup at: {backup_path}")
    
    # Read the file content
    with open(script_path, 'r') as f:
        content = f.read()
    
    # Update the imports section
    print("Updating OpenMP imports...")
    updated_content = update_openmp_imports(content)
    
    # Update XGBoost parameters
    print("Updating XGBoost parameters...")
    updated_content = update_xgboost_params(updated_content)
    
    # Update LightGBM parameters
    print("Updating LightGBM parameters...")
    updated_content = update_lightgbm_params(updated_content)
    
    # Write the updated content back to the file
    with open(script_path, 'w') as f:
        f.write(updated_content)
    
    print(f"Successfully updated {script_path} to properly use OpenMP.")
    print("\nNext steps:")
    print("1. Install OpenMP using the install_openmp_mac.sh script:")
    print("   bash scripts/install_openmp_mac.sh")
    print("2. Load the OpenMP environment variables:")
    print("   source openmp_env.sh")
    print("3. Reinstall XGBoost and LightGBM:")
    print("   pip uninstall -y xgboost lightgbm")
    print("   pip install xgboost lightgbm --no-binary :all:")
    print("4. Run the updated ML model training script:")
    print("   python scripts/train_enhanced_github_models.py --ensemble --force")

if __name__ == "__main__":
    main()
