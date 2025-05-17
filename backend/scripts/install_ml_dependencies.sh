#!/bin/bash

# Script to install ML dependencies for the football prediction system
# This script handles different OS environments

echo "Installing ML dependencies for football prediction system..."

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    echo "Detected macOS system"
    
    # Check if Homebrew is installed
    if ! command -v brew &> /dev/null; then
        echo "Homebrew not found. Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    
    # Install OpenMP for macOS (needed for XGBoost and LightGBM)
    echo "Installing OpenMP..."
    brew install libomp
    
    # Set environment variables for OpenMP
    export CC=/usr/bin/clang
    export CXX=/usr/bin/clang++
    export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"
    export CFLAGS="$CFLAGS -I/usr/local/opt/libomp/include"
    export CXXFLAGS="$CXXFLAGS -I/usr/local/opt/libomp/include"
    export LDFLAGS="$LDFLAGS -L/usr/local/opt/libomp/lib -lomp"
    
    # Add to .bash_profile or .zshrc if not already there
    if [[ -f ~/.zshrc ]]; then
        if ! grep -q "libomp" ~/.zshrc; then
            echo '# OpenMP settings for ML libraries' >> ~/.zshrc
            echo 'export CC=/usr/bin/clang' >> ~/.zshrc
            echo 'export CXX=/usr/bin/clang++' >> ~/.zshrc
            echo 'export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"' >> ~/.zshrc
            echo 'export CFLAGS="$CFLAGS -I/usr/local/opt/libomp/include"' >> ~/.zshrc
            echo 'export CXXFLAGS="$CXXFLAGS -I/usr/local/opt/libomp/include"' >> ~/.zshrc
            echo 'export LDFLAGS="$LDFLAGS -L/usr/local/opt/libomp/lib -lomp"' >> ~/.zshrc
        fi
    elif [[ -f ~/.bash_profile ]]; then
        if ! grep -q "libomp" ~/.bash_profile; then
            echo '# OpenMP settings for ML libraries' >> ~/.bash_profile
            echo 'export CC=/usr/bin/clang' >> ~/.bash_profile
            echo 'export CXX=/usr/bin/clang++' >> ~/.bash_profile
            echo 'export CPPFLAGS="$CPPFLAGS -Xpreprocessor -fopenmp"' >> ~/.bash_profile
            echo 'export CFLAGS="$CFLAGS -I/usr/local/opt/libomp/include"' >> ~/.bash_profile
            echo 'export CXXFLAGS="$CXXFLAGS -I/usr/local/opt/libomp/include"' >> ~/.bash_profile
            echo 'export LDFLAGS="$LDFLAGS -L/usr/local/opt/libomp/lib -lomp"' >> ~/.bash_profile
        fi
    fi
    
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    echo "Detected Linux system"
    
    # Install build essentials
    echo "Installing build essentials..."
    sudo apt-get update
    sudo apt-get install -y build-essential
    
    # Install OpenMP
    echo "Installing OpenMP..."
    sudo apt-get install -y libomp-dev
fi

# Install Python dependencies
echo "Installing Python ML packages..."

# Core ML packages
pip install --upgrade scikit-learn pandas numpy joblib

# XGBoost
echo "Installing XGBoost..."
pip install --upgrade xgboost

# LightGBM
echo "Installing LightGBM..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS - use prebuilt wheel
    pip install --upgrade lightgbm
else
    # Linux - compile with OpenMP support
    pip install --upgrade lightgbm --install-option=--openmp
fi

# CatBoost
echo "Installing CatBoost..."
pip install --upgrade catboost

# TensorFlow for Neural Networks and LSTM
echo "Installing TensorFlow..."
pip install --upgrade tensorflow

# Visualization libraries
echo "Installing visualization libraries..."
pip install --upgrade matplotlib seaborn

echo "ML dependencies installation complete!"
echo "You may need to restart your terminal for environment variables to take effect."
