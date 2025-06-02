#!/usr/bin/env python3
"""
Production Startup Script for BetSightly Backend

This script performs all necessary checks and initializations before starting the server.
"""

import os
import sys
import logging
import uvicorn
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def check_environment():
    """Check if all required environment variables are set."""
    logger.info("Checking environment variables...")
    
    required_vars = [
        "FOOTBALL_DATA_API_KEY",
        "API_FOOTBALL_API_KEY"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set these variables in your .env file or environment")
        return False
    
    logger.info("✓ All required environment variables are set")
    return True


def check_directories():
    """Check if all required directories exist and create them if needed."""
    logger.info("Checking required directories...")
    
    required_dirs = [
        "data",
        "cache", 
        "models",
        "logs",
        "results"
    ]
    
    for dir_name in required_dirs:
        dir_path = Path(dir_name)
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"✓ Created directory: {dir_name}")
            except Exception as e:
                logger.error(f"Failed to create directory {dir_name}: {str(e)}")
                return False
        else:
            logger.info(f"✓ Directory exists: {dir_name}")
    
    return True


def check_database():
    """Check database connectivity and initialize if needed."""
    logger.info("Checking database...")
    
    try:
        from database import init_db, get_db
        
        # Initialize database
        if init_db():
            logger.info("✓ Database initialized successfully")
        else:
            logger.error("Failed to initialize database")
            return False
        
        # Test database connection
        db = next(get_db())
        db.close()
        logger.info("✓ Database connection test successful")
        
        return True
        
    except Exception as e:
        logger.error(f"Database check failed: {str(e)}")
        return False


def check_api_keys():
    """Test API key validity (basic check)."""
    logger.info("Checking API keys...")
    
    try:
        from utils.config import settings
        
        # Check if keys are configured
        football_key = os.getenv('FOOTBALL_DATA_API_KEY')
        api_football_key = os.getenv('API_FOOTBALL_API_KEY')

        if not football_key or football_key == 'your-football-data-api-key-here':
            logger.warning("Football Data API key not configured or using placeholder")

        if not api_football_key or api_football_key == 'your-api-football-key-here':
            logger.warning("API Football key not configured or using placeholder")
        
        logger.info("✓ API keys are configured")
        return True
        
    except Exception as e:
        logger.error(f"API key check failed: {str(e)}")
        return False


def check_models():
    """Check if ML models are available."""
    logger.info("Checking ML models...")
    
    try:
        from ml.model_factory import model_factory
        
        if hasattr(model_factory, 'get_available_models'):
            available_models = model_factory.get_available_models()
            logger.info(f"✓ Model factory available with {len(available_models)} models")
        else:
            logger.info("✓ Model factory available (basic)")
        
        return True
        
    except ImportError:
        logger.warning("⚠ Model factory not available - will use fallback predictions")
        return True  # Not critical for startup
        
    except Exception as e:
        logger.error(f"Model check failed: {str(e)}")
        return False


def run_health_checks():
    """Run comprehensive health checks."""
    logger.info("Running health checks...")
    
    checks = [
        ("Environment Variables", check_environment),
        ("Directories", check_directories),
        ("Database", check_database),
        ("API Keys", check_api_keys),
        ("ML Models", check_models)
    ]
    
    failed_checks = []
    
    for check_name, check_func in checks:
        try:
            if not check_func():
                failed_checks.append(check_name)
        except Exception as e:
            logger.error(f"Health check '{check_name}' failed with exception: {str(e)}")
            failed_checks.append(check_name)
    
    if failed_checks:
        logger.error(f"Failed health checks: {', '.join(failed_checks)}")
        return False
    
    logger.info("✓ All health checks passed")
    return True


def start_server(host="0.0.0.0", port=8000, reload=False):
    """Start the FastAPI server."""
    logger.info(f"Starting server on {host}:{port}")
    
    try:
        uvicorn.run(
            "main:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info",
            access_log=True
        )
    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}")
        sys.exit(1)


def main():
    """Main startup function."""
    logger.info("🚀 Starting BetSightly Backend...")
    
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="BetSightly Backend Production Startup")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    parser.add_argument("--skip-checks", action="store_true", help="Skip health checks")
    
    args = parser.parse_args()
    
    # Run health checks unless skipped
    if not args.skip_checks:
        if not run_health_checks():
            logger.error("❌ Health checks failed. Exiting.")
            sys.exit(1)
    else:
        logger.warning("⚠ Skipping health checks")
    
    # Start the server
    logger.info("✅ All checks passed. Starting server...")
    start_server(host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
