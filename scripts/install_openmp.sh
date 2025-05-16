#!/bin/bash
# Script to install OpenMP and configure the environment for XGBoost and LightGBM

# Set up colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== OpenMP Installation Script for ML Libraries ===${NC}"
echo -e "${BLUE}This script will help you install OpenMP and configure your environment for XGBoost and LightGBM.${NC}"
echo ""

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo -e "${YELLOW}Homebrew is not installed. Installing Homebrew...${NC}"
    echo -e "${YELLOW}You may be prompted for your password.${NC}"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Check if Homebrew was installed successfully
    if ! command -v brew &> /dev/null; then
        echo -e "${RED}Failed to install Homebrew. Please install it manually from https://brew.sh${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}Homebrew installed successfully!${NC}"
else
    echo -e "${GREEN}Homebrew is already installed.${NC}"
fi

# Install OpenMP
echo -e "${BLUE}Installing OpenMP...${NC}"
brew install libomp

# Check if OpenMP was installed successfully
if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to install OpenMP. Please try again or install it manually with 'brew install libomp'.${NC}"
    exit 1
fi

echo -e "${GREEN}OpenMP installed successfully!${NC}"

# Get OpenMP installation path
OPENMP_PATH=$(brew --prefix libomp)
echo -e "${BLUE}OpenMP installed at: ${OPENMP_PATH}${NC}"

# Create or update .env file with OpenMP configuration
ENV_FILE="../.env"
if [ -f "$ENV_FILE" ]; then
    echo -e "${BLUE}Updating .env file with OpenMP configuration...${NC}"
    # Remove any existing OpenMP configuration
    grep -v "OPENMP_" "$ENV_FILE" > "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
else
    echo -e "${BLUE}Creating .env file with OpenMP configuration...${NC}"
    touch "$ENV_FILE"
fi

# Add OpenMP configuration to .env file
echo "OPENMP_PATH=$OPENMP_PATH" >> "$ENV_FILE"
echo "CFLAGS=\"-Xpreprocessor -fopenmp -I$OPENMP_PATH/include\"" >> "$ENV_FILE"
echo "CXXFLAGS=\"-Xpreprocessor -fopenmp -I$OPENMP_PATH/include\"" >> "$ENV_FILE"
echo "LDFLAGS=\"-L$OPENMP_PATH/lib -lomp\"" >> "$ENV_FILE"

echo -e "${GREEN}Environment variables added to .env file.${NC}"

# Create a Python script to configure the environment for XGBoost and LightGBM
PYTHON_SCRIPT="configure_openmp.py"
cat > "$PYTHON_SCRIPT" << 'EOF'
#!/usr/bin/env python3
import os
import sys
import subprocess
import site
import platform

def get_openmp_path():
    """Get OpenMP installation path from environment or try to find it."""
    # Try to get from environment
    openmp_path = os.environ.get('OPENMP_PATH')
    if openmp_path:
        return openmp_path
    
    # Try to find using brew
    try:
        result = subprocess.run(['brew', '--prefix', 'libomp'], 
                               capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

def create_xgboost_config():
    """Create XGBoost configuration file."""
    openmp_path = get_openmp_path()
    if not openmp_path:
        print("Error: Could not determine OpenMP installation path.")
        return False
    
    # Get user site-packages directory
    user_site = site.getusersitepackages()
    
    # Create XGBoost config directory if it doesn't exist
    xgb_config_dir = os.path.join(os.path.expanduser("~"), ".xgboost")
    os.makedirs(xgb_config_dir, exist_ok=True)
    
    # Create config.json file
    config_path = os.path.join(xgb_config_dir, "config.json")
    with open(config_path, 'w') as f:
        f.write('{\n')
        f.write('    "verbosity": 2,\n')
        f.write('    "use_rmm": false,\n')
        f.write(f'    "nthread": 4\n')
        f.write('}\n')
    
    print(f"Created XGBoost config at {config_path}")
    return True

def create_lightgbm_config():
    """Create LightGBM configuration file."""
    # Get user site-packages directory
    user_site = site.getusersitepackages()
    
    # Create LightGBM config directory if it doesn't exist
    lgbm_config_dir = os.path.join(os.path.expanduser("~"), ".lightgbm")
    os.makedirs(lgbm_config_dir, exist_ok=True)
    
    # Create config file
    config_path = os.path.join(lgbm_config_dir, "config.ini")
    with open(config_path, 'w') as f:
        f.write('[default]\n')
        f.write('num_threads=4\n')
        f.write('force_row_wise=true\n')
        f.write('verbose=-1\n')
    
    print(f"Created LightGBM config at {config_path}")
    return True

def main():
    """Main function."""
    print("Configuring environment for XGBoost and LightGBM...")
    
    # Create configuration files
    xgb_success = create_xgboost_config()
    lgbm_success = create_lightgbm_config()
    
    if xgb_success and lgbm_success:
        print("\nConfiguration completed successfully!")
        print("\nTo use OpenMP with XGBoost and LightGBM, you need to set the following environment variables:")
        print("For bash/zsh:")
        openmp_path = get_openmp_path()
        if openmp_path:
            print(f"export OPENMP_PATH={openmp_path}")
            print(f"export CFLAGS=\"-Xpreprocessor -fopenmp -I{openmp_path}/include\"")
            print(f"export CXXFLAGS=\"-Xpreprocessor -fopenmp -I{openmp_path}/include\"")
            print(f"export LDFLAGS=\"-L{openmp_path}/lib -lomp\"")
            print(f"export OMP_NUM_THREADS=4")
        
        print("\nYou can add these to your ~/.bashrc or ~/.zshrc file to make them permanent.")
        print("\nYou may need to reinstall XGBoost and LightGBM with:")
        print("pip uninstall -y xgboost lightgbm")
        print("pip install xgboost lightgbm --no-binary :all:")
    else:
        print("\nConfiguration failed. Please check the error messages above.")

if __name__ == "__main__":
    main()
EOF

chmod +x "$PYTHON_SCRIPT"

# Run the Python script
echo -e "${BLUE}Configuring environment for XGBoost and LightGBM...${NC}"
python3 "$PYTHON_SCRIPT"

# Instructions for reinstalling XGBoost and LightGBM
echo -e "${BLUE}=== Next Steps ===${NC}"
echo -e "${YELLOW}To complete the setup, you should reinstall XGBoost and LightGBM:${NC}"
echo -e "pip uninstall -y xgboost lightgbm"
echo -e "pip install xgboost lightgbm --no-binary :all:"
echo ""
echo -e "${YELLOW}To use OpenMP in your current shell session, run:${NC}"
echo -e "source ../.env"
echo ""
echo -e "${GREEN}Installation and configuration completed!${NC}"
