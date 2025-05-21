"""
Run Pipeline

This script runs the entire pipeline for the Football Betting Assistant:
1. Fetch historical data from schochastics/football-data
2. Train ML models
3. Start the backend server
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
        logging.FileHandler(f"pipeline_{datetime.now().strftime('%Y%m%d')}.log")
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

def train_ml_models() -> bool:
    """
    Train ML models.
    
    Returns:
        True if successful, False otherwise
    """
    return run_command(
        "python scripts/train_ml_models.py",
        "ML model training"
    )

def start_server() -> bool:
    """
    Start the backend server.
    
    Returns:
        True if successful, False otherwise
    """
    return run_command(
        "python start_server.py",
        "backend server"
    )

def main():
    """Main function to run the entire pipeline."""
    logger.info("Starting Football Betting Assistant pipeline...")
    
    # Add the current directory to the Python path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Fetch historical data
    if not fetch_historical_data():
        logger.error("Failed to fetch historical data. Exiting...")
        sys.exit(1)
    
    # Train ML models
    if not train_ml_models():
        logger.error("Failed to train ML models. Exiting...")
        sys.exit(1)
    
    # Start server
    if not start_server():
        logger.error("Failed to start server. Exiting...")
        sys.exit(1)
    
    logger.info("Pipeline completed successfully")

if __name__ == "__main__":
    main()
