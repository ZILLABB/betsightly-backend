"""
Start Server Script

This script initializes the database and starts the FastAPI server.
It also sets up the necessary environment for the application.
"""

import os
import sys
import logging
import uvicorn
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"server_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
logger = logging.getLogger(__name__)

def initialize_database():
    """Initialize the database."""
    logger.info("Initializing database...")
    
    try:
        # Import database initialization function
        from app.database import init_db
        
        # Initialize database
        init_db()
        logger.info("Database initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        return False

def initialize_cache_directory():
    """Initialize the cache directory."""
    logger.info("Initializing cache directory...")
    
    try:
        # Create cache directory if it doesn't exist
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        logger.info(f"Cache directory initialized at {cache_dir}")
        return True
    except Exception as e:
        logger.error(f"Error initializing cache directory: {str(e)}")
        return False

def check_api_key():
    """Check if API key is set."""
    logger.info("Checking API key...")
    
    try:
        # Import settings
        from app.config import settings
        
        # Check API key
        if not settings.API_FOOTBALL_KEY:
            logger.warning("API-Football key not set. Some features may not work properly.")
            return False
        
        logger.info("API key is set")
        return True
    except Exception as e:
        logger.error(f"Error checking API key: {str(e)}")
        return False

def start_server():
    """Start the FastAPI server."""
    logger.info("Starting server...")
    
    try:
        # Run the app
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")
        sys.exit(1)

def main():
    """Main function to initialize and start the server."""
    logger.info("Starting Football Betting Assistant backend...")
    
    # Add the current directory to the Python path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    # Initialize cache directory
    if not initialize_cache_directory():
        logger.warning("Failed to initialize cache directory. Continuing anyway...")
    
    # Check API key
    if not check_api_key():
        logger.warning("API key check failed. Some features may not work properly.")
    
    # Initialize database
    if not initialize_database():
        logger.error("Failed to initialize database. Exiting...")
        sys.exit(1)
    
    # Start server
    start_server()

if __name__ == "__main__":
    main()
