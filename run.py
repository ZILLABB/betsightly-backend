"""
Run Script

This script runs the FastAPI application.
"""

import os
import sys
import logging
import uvicorn

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Run the FastAPI application."""
    try:
        logger.info("Starting BetSightly backend server...")
        
        # Add the current directory to the Python path
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        # Run the app
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
    
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
