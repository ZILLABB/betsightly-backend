#!/usr/bin/env python3
"""
TensorFlow Environment Setup

This script sets up the optimal Python environment for TensorFlow integration.
"""

import subprocess
import sys
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TensorFlowEnvironmentSetup:
    """Setup optimal environment for TensorFlow integration."""
    
    def __init__(self):
        self.python_versions = ["3.11.9", "3.10.12", "3.9.18"]
        self.tensorflow_version = "2.15.0"
        
    def check_current_python(self):
        """Check current Python version."""
        version = sys.version_info
        current = f"{version.major}.{version.minor}.{version.micro}"
        logger.info(f"Current Python version: {current}")
        return current
    
    def install_pyenv_if_needed(self):
        """Install pyenv for Python version management."""
        try:
            subprocess.run(["pyenv", "--version"], check=True, capture_output=True)
            logger.info("✅ pyenv is already installed")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.info("📦 Installing pyenv...")
            
            # Install pyenv
            install_script = """
            curl https://pyenv.run | bash
            echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
            echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
            echo 'eval "$(pyenv init -)"' >> ~/.bashrc
            """
            
            try:
                subprocess.run(install_script, shell=True, check=True)
                logger.info("✅ pyenv installed successfully")
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"❌ Failed to install pyenv: {e}")
                return False
    
    def setup_tensorflow_compatible_python(self):
        """Setup Python version compatible with TensorFlow."""
        logger.info("🐍 Setting up TensorFlow-compatible Python environment")
        
        # Try to install a compatible Python version
        for python_version in self.python_versions:
            try:
                logger.info(f"Installing Python {python_version}...")
                subprocess.run([
                    "pyenv", "install", "-s", python_version
                ], check=True)
                
                # Set as local version for this project
                subprocess.run([
                    "pyenv", "local", python_version
                ], check=True)
                
                logger.info(f"✅ Python {python_version} installed and set as local version")
                return python_version
                
            except subprocess.CalledProcessError as e:
                logger.warning(f"⚠️ Failed to install Python {python_version}: {e}")
                continue
        
        logger.error("❌ Failed to install any compatible Python version")
        return None
    
    def install_tensorflow_dependencies(self):
        """Install TensorFlow and related dependencies."""
        logger.info("📦 Installing TensorFlow dependencies...")
        
        dependencies = [
            f"tensorflow=={self.tensorflow_version}",
            "tensorflow-probability==0.23.0",
            "keras==2.15.0",
            "tensorboard==2.15.1"
        ]
        
        try:
            for dep in dependencies:
                logger.info(f"Installing {dep}...")
                subprocess.run([
                    sys.executable, "-m", "pip", "install", dep
                ], check=True)
            
            logger.info("✅ TensorFlow dependencies installed successfully")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to install TensorFlow dependencies: {e}")
            return False
    
    def verify_tensorflow_installation(self):
        """Verify TensorFlow installation."""
        try:
            import tensorflow as tf
            logger.info(f"✅ TensorFlow {tf.__version__} installed successfully")
            
            # Test basic functionality
            test_tensor = tf.constant([1, 2, 3, 4])
            logger.info(f"✅ TensorFlow basic test passed: {test_tensor}")
            
            # Check for GPU support
            if tf.config.list_physical_devices('GPU'):
                logger.info("🚀 GPU support detected!")
            else:
                logger.info("💻 CPU-only TensorFlow (normal for most setups)")
            
            return True
            
        except ImportError as e:
            logger.error(f"❌ TensorFlow import failed: {e}")
            return False
    
    def create_tensorflow_requirements(self):
        """Create requirements file for TensorFlow environment."""
        tf_requirements = """# TensorFlow Environment Requirements
# Core ML libraries
tensorflow==2.15.0
tensorflow-probability==0.23.0
keras==2.15.0
tensorboard==2.15.1

# Existing requirements
fastapi==0.104.1
uvicorn[standard]==0.24.0
gunicorn==21.2.0
pydantic==2.5.0
pydantic-settings==2.1.0
pandas==2.1.4
numpy==1.25.2
scikit-learn==1.3.2
joblib==1.3.2
xgboost==1.7.6
lightgbm==4.1.0
sqlalchemy==2.0.23
python-dotenv==1.0.0
python-telegram-bot==20.7
requests==2.31.0
"""
        
        with open("requirements-tensorflow.txt", "w") as f:
            f.write(tf_requirements)
        
        logger.info("✅ Created requirements-tensorflow.txt")
    
    def run_setup(self):
        """Run complete TensorFlow environment setup."""
        logger.info("🚀 Starting TensorFlow Environment Setup")
        logger.info("=" * 60)
        
        # Step 1: Check current environment
        current_python = self.check_current_python()
        
        # Step 2: Install pyenv if needed
        if not self.install_pyenv_if_needed():
            logger.error("❌ Cannot proceed without pyenv")
            return False
        
        # Step 3: Setup compatible Python
        python_version = self.setup_tensorflow_compatible_python()
        if not python_version:
            logger.error("❌ Cannot setup compatible Python version")
            return False
        
        # Step 4: Install TensorFlow
        if not self.install_tensorflow_dependencies():
            logger.error("❌ TensorFlow installation failed")
            return False
        
        # Step 5: Verify installation
        if not self.verify_tensorflow_installation():
            logger.error("❌ TensorFlow verification failed")
            return False
        
        # Step 6: Create requirements file
        self.create_tensorflow_requirements()
        
        logger.info("🎉 TensorFlow environment setup completed successfully!")
        logger.info(f"✅ Python {python_version} with TensorFlow {self.tensorflow_version}")
        logger.info("🔄 Restart your terminal and run: source ~/.bashrc")
        
        return True

def main():
    """Run the TensorFlow environment setup."""
    setup = TensorFlowEnvironmentSetup()
    success = setup.run_setup()
    
    if success:
        print("\n🎯 NEXT STEPS:")
        print("1. Restart your terminal")
        print("2. Run: source ~/.bashrc")
        print("3. Verify: python --version")
        print("4. Test: python -c 'import tensorflow as tf; print(tf.__version__)'")
        print("5. Run: python test_enhanced_ml_models.py")
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
