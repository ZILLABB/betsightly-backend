#!/bin/bash
# Script to install OpenMP and configure the environment for XGBoost and LightGBM on macOS

# Set up colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== OpenMP Installation Script for ML Libraries on macOS ===${NC}"
echo -e "${BLUE}This script will help you install OpenMP and configure your environment for XGBoost and LightGBM.${NC}"
echo ""

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo -e "${YELLOW}Homebrew is not installed. Please install Homebrew first:${NC}"
    echo -e "${YELLOW}/bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"${NC}"
    echo -e "${YELLOW}After installing Homebrew, run this script again.${NC}"
    exit 1
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

# Create a file with environment variables
ENV_FILE="openmp_env.sh"
cat > "$ENV_FILE" << EOF
# OpenMP environment variables for macOS
export OPENMP_PATH=$OPENMP_PATH
export CFLAGS="-Xpreprocessor -fopenmp -I\$OPENMP_PATH/include"
export CXXFLAGS="-Xpreprocessor -fopenmp -I\$OPENMP_PATH/include"
export LDFLAGS="-L\$OPENMP_PATH/lib -lomp"
export OMP_NUM_THREADS=4
EOF

chmod +x "$ENV_FILE"
echo -e "${GREEN}Created environment variables file: $ENV_FILE${NC}"
echo -e "${YELLOW}To load these variables, run: source $ENV_FILE${NC}"

# Add to shell profile if desired
read -p "Would you like to add these environment variables to your shell profile? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Determine shell profile file
    if [ -n "$ZSH_VERSION" ]; then
        PROFILE_FILE="$HOME/.zshrc"
    elif [ -n "$BASH_VERSION" ]; then
        PROFILE_FILE="$HOME/.bash_profile"
        if [ ! -f "$PROFILE_FILE" ]; then
            PROFILE_FILE="$HOME/.bashrc"
        fi
    else
        echo -e "${YELLOW}Could not determine your shell profile file. Please add the variables manually.${NC}"
        PROFILE_FILE=""
    fi
    
    if [ -n "$PROFILE_FILE" ]; then
        echo -e "${BLUE}Adding environment variables to $PROFILE_FILE...${NC}"
        echo "" >> "$PROFILE_FILE"
        echo "# OpenMP environment variables for ML libraries" >> "$PROFILE_FILE"
        echo "export OPENMP_PATH=$OPENMP_PATH" >> "$PROFILE_FILE"
        echo 'export CFLAGS="-Xpreprocessor -fopenmp -I$OPENMP_PATH/include"' >> "$PROFILE_FILE"
        echo 'export CXXFLAGS="-Xpreprocessor -fopenmp -I$OPENMP_PATH/include"' >> "$PROFILE_FILE"
        echo 'export LDFLAGS="-L$OPENMP_PATH/lib -lomp"' >> "$PROFILE_FILE"
        echo 'export OMP_NUM_THREADS=4' >> "$PROFILE_FILE"
        echo -e "${GREEN}Environment variables added to $PROFILE_FILE${NC}"
        echo -e "${YELLOW}Please restart your terminal or run 'source $PROFILE_FILE' to apply the changes.${NC}"
    fi
fi

# Instructions for reinstalling XGBoost and LightGBM
echo -e "${BLUE}=== Next Steps ===${NC}"
echo -e "${YELLOW}To complete the setup, you should reinstall XGBoost and LightGBM:${NC}"
echo -e "source $ENV_FILE  # Load the environment variables"
echo -e "pip uninstall -y xgboost lightgbm"
echo -e "pip install xgboost lightgbm --no-binary :all:"
echo ""
echo -e "${GREEN}Installation and configuration completed!${NC}"
