"""
Improve Models

This script runs the model improvement pipeline:
1. Fetch historical data from schochastics/football-data
2. Train ensemble models
3. Evaluate model performance
"""

import os
import sys
import logging
import subprocess
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"model_improvement_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
logger = logging.getLogger(__name__)

def run_command(command: str, description: str) -> bool:
    """
    Run a command and log the output.
    
    Args:
        command: Command to run
        description: Description of the command
        
    Returns:
        True if command was successful, False otherwise
    """
    logger.info(f"Running {description}...")
    
    try:
        # Run the command
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        # Get output
        stdout, stderr = process.communicate()
        
        # Log output
        if stdout:
            for line in stdout.splitlines():
                logger.info(line)
        
        if stderr:
            for line in stderr.splitlines():
                logger.error(line)
        
        # Check return code
        if process.returncode == 0:
            logger.info(f"{description} completed successfully")
            return True
        else:
            logger.error(f"{description} failed with return code {process.returncode}")
            return False
    
    except Exception as e:
        logger.error(f"Error running {description}: {str(e)}")
        return False

def fetch_historical_data() -> bool:
    """
    Fetch historical data from schochastics/football-data.
    
    Returns:
        True if successful, False otherwise
    """
    return run_command(
        "python scripts/fetch_football_data_github.py",
        "historical data fetch"
    )

def train_models() -> bool:
    """
    Train ensemble models.
    
    Returns:
        True if successful, False otherwise
    """
    return run_command(
        "python scripts/train_ml_models.py",
        "ensemble model training"
    )

def evaluate_models() -> bool:
    """
    Evaluate model performance.
    
    Returns:
        True if successful, False otherwise
    """
    return run_command(
        "python scripts/evaluate_model.py",
        "model evaluation"
    )

def main():
    """Main function to run the model improvement pipeline."""
    logger.info("Starting model improvement pipeline...")
    
    # Add the current directory to the Python path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Fetch historical data
    if not fetch_historical_data():
        logger.error("Failed to fetch historical data. Exiting...")
        sys.exit(1)
    
    # Train models
    if not train_models():
        logger.error("Failed to train models. Exiting...")
        sys.exit(1)
    
    # Evaluate models
    if not evaluate_models():
        logger.error("Failed to evaluate models. Exiting...")
        sys.exit(1)
    
    logger.info("Model improvement pipeline completed successfully")

if __name__ == "__main__":
    main()
