#!/usr/bin/env python3
"""
Production Deployment Script for BetSightly Backend

This script handles production deployment with comprehensive checks,
security validations, and performance optimizations.
"""

import os
import sys
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ProductionDeployment:
    """Production deployment manager with comprehensive checks."""
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.deployment_log = []
        self.errors = []
        self.warnings = []
    
    def log_step(self, message: str, level: str = "INFO"):
        """Log deployment step."""
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] {level}: {message}"
        
        if level == "ERROR":
            logger.error(message)
            self.errors.append(log_entry)
        elif level == "WARNING":
            logger.warning(message)
            self.warnings.append(log_entry)
        else:
            logger.info(message)
        
        self.deployment_log.append(log_entry)
    
    def check_environment_variables(self) -> bool:
        """Check that all required environment variables are set."""
        self.log_step("Checking environment variables...")
        
        required_vars = [
            "FOOTBALL_DATA_KEY",
            "SECRET_KEY",
            "ENVIRONMENT",
            "DATABASE_URL"
        ]
        
        missing_vars = []
        
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            self.log_step(f"Missing required environment variables: {missing_vars}", "ERROR")
            return False
        
        # Check for default/example values
        dangerous_defaults = {
            "SECRET_KEY": ["your-super-secret-key-change-this-in-production"],
            "FOOTBALL_DATA_KEY": ["your_football_data_api_key_here"],
        }
        
        for var, defaults in dangerous_defaults.items():
            value = os.getenv(var, "")
            if value in defaults:
                self.log_step(f"Environment variable {var} still has default value!", "ERROR")
                return False
        
        self.log_step("✓ Environment variables check passed")
        return True
    
    def check_security_configuration(self) -> bool:
        """Check security configuration."""
        self.log_step("Checking security configuration...")
        
        # Check environment
        environment = os.getenv("ENVIRONMENT", "development")
        if environment == "production":
            # Production security checks
            debug = os.getenv("DEBUG", "True").lower()
            if debug == "true":
                self.log_step("DEBUG mode is enabled in production!", "ERROR")
                return False
            
            # Check CORS origins
            allowed_origins = os.getenv("ALLOWED_ORIGINS", "")
            if "localhost" in allowed_origins:
                self.log_step("Localhost is allowed in CORS origins for production", "WARNING")
        
        self.log_step("✓ Security configuration check passed")
        return True
    
    def check_database_connection(self) -> bool:
        """Check database connection and setup."""
        self.log_step("Checking database connection...")
        
        try:
            from database import init_db, get_db
            from sqlalchemy import text
            
            # Initialize database
            if not init_db():
                self.log_step("Database initialization failed", "ERROR")
                return False
            
            # Test connection
            db = next(get_db())
            result = db.execute(text("SELECT 1")).fetchone()
            db.close()
            
            if result[0] != 1:
                self.log_step("Database connection test failed", "ERROR")
                return False
            
            self.log_step("✓ Database connection check passed")
            return True
            
        except Exception as e:
            self.log_step(f"Database check failed: {str(e)}", "ERROR")
            return False
    
    def check_ml_models(self) -> bool:
        """Check ML models availability."""
        self.log_step("Checking ML models...")
        
        try:
            from utils.config import settings
            
            model_dir = Path(settings.ml.MODEL_DIR)
            if not model_dir.exists():
                self.log_step("Model directory does not exist", "WARNING")
                return True  # Not critical for deployment
            
            # Check for at least one model file
            model_files = list(model_dir.glob("*.joblib"))
            if not model_files:
                self.log_step("No trained models found", "WARNING")
                return True  # Not critical for deployment
            
            self.log_step(f"✓ Found {len(model_files)} ML model files")
            return True
            
        except Exception as e:
            self.log_step(f"ML models check failed: {str(e)}", "WARNING")
            return True  # Not critical for deployment
    
    def check_api_keys(self) -> bool:
        """Check API keys validity."""
        self.log_step("Checking API keys...")
        
        try:
            from services.api_client import FootballDataClient
            
            # Test Football-Data.org API
            football_key = os.getenv("FOOTBALL_DATA_KEY")
            if football_key:
                client = FootballDataClient()
                # Simple test request (this might fail if no quota, but that's ok)
                try:
                    response = client.get("/competitions", use_cache=False, max_retries=1)
                    self.log_step("✓ Football-Data.org API key is valid")
                except Exception as e:
                    self.log_step(f"Football-Data.org API test failed: {str(e)}", "WARNING")
            
            return True
            
        except Exception as e:
            self.log_step(f"API keys check failed: {str(e)}", "WARNING")
            return True  # Not critical for deployment
    
    def optimize_for_production(self) -> bool:
        """Apply production optimizations."""
        self.log_step("Applying production optimizations...")
        
        try:
            # Create necessary directories
            directories = ["logs", "cache", "data", "models"]
            for directory in directories:
                dir_path = self.project_root / directory
                dir_path.mkdir(exist_ok=True)
                self.log_step(f"Created directory: {directory}")
            
            # Set up database optimizations
            from utils.database_optimization import create_database_indexes, optimize_query_performance
            
            create_database_indexes()
            optimize_query_performance()
            
            self.log_step("✓ Production optimizations applied")
            return True
            
        except Exception as e:
            self.log_step(f"Production optimization failed: {str(e)}", "ERROR")
            return False
    
    def run_health_checks(self) -> bool:
        """Run comprehensive health checks."""
        self.log_step("Running health checks...")
        
        try:
            # Import and run test fixes
            from test_fixes import run_all_tests
            
            if run_all_tests():
                self.log_step("✓ All health checks passed")
                return True
            else:
                self.log_step("Some health checks failed", "ERROR")
                return False
                
        except Exception as e:
            self.log_step(f"Health checks failed: {str(e)}", "ERROR")
            return False
    
    def generate_deployment_report(self) -> str:
        """Generate deployment report."""
        report = f"""
# BetSightly Backend Deployment Report

**Deployment Time**: {datetime.now().isoformat()}
**Environment**: {os.getenv('ENVIRONMENT', 'unknown')}
**Status**: {'SUCCESS' if not self.errors else 'FAILED'}

## Summary
- Total Steps: {len(self.deployment_log)}
- Errors: {len(self.errors)}
- Warnings: {len(self.warnings)}

## Errors
{chr(10).join(self.errors) if self.errors else 'None'}

## Warnings
{chr(10).join(self.warnings) if self.warnings else 'None'}

## Full Log
{chr(10).join(self.deployment_log)}

## Next Steps
{'✅ Deployment successful! The application is ready for production.' if not self.errors else '❌ Deployment failed. Please fix the errors above and try again.'}

## Monitoring
- Health Check: GET /api/health/detailed
- Metrics: Check logs/betsightly.log
- Performance: Monitor response times and error rates

## Security Reminders
- Regularly rotate API keys
- Monitor for suspicious activity
- Keep dependencies updated
- Backup database regularly
"""
        return report
    
    def deploy(self) -> bool:
        """Run full deployment process."""
        self.log_step("Starting BetSightly Backend deployment...")
        
        checks = [
            ("Environment Variables", self.check_environment_variables),
            ("Security Configuration", self.check_security_configuration),
            ("Database Connection", self.check_database_connection),
            ("ML Models", self.check_ml_models),
            ("API Keys", self.check_api_keys),
            ("Production Optimizations", self.optimize_for_production),
            ("Health Checks", self.run_health_checks),
        ]
        
        success = True
        
        for check_name, check_func in checks:
            self.log_step(f"Running {check_name} check...")
            try:
                if not check_func():
                    success = False
                    self.log_step(f"{check_name} check failed", "ERROR")
                else:
                    self.log_step(f"{check_name} check passed")
            except Exception as e:
                success = False
                self.log_step(f"{check_name} check failed with exception: {str(e)}", "ERROR")
        
        # Generate report
        report = self.generate_deployment_report()
        
        # Save report
        report_file = self.project_root / f"deployment_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(report_file, 'w') as f:
            f.write(report)
        
        self.log_step(f"Deployment report saved to: {report_file}")
        
        if success:
            self.log_step("🎉 Deployment completed successfully!")
        else:
            self.log_step("💥 Deployment failed. Check the report for details.")
        
        return success


def main():
    """Main deployment function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Deploy BetSightly Backend to Production")
    parser.add_argument("--check-only", action="store_true", help="Only run checks, don't deploy")
    parser.add_argument("--skip-health", action="store_true", help="Skip health checks")
    
    args = parser.parse_args()
    
    deployment = ProductionDeployment()
    
    if args.check_only:
        logger.info("Running deployment checks only...")
        success = deployment.check_environment_variables()
        success &= deployment.check_security_configuration()
        success &= deployment.check_database_connection()
        
        if success:
            logger.info("✅ All checks passed. Ready for deployment.")
            sys.exit(0)
        else:
            logger.error("❌ Some checks failed. Fix issues before deployment.")
            sys.exit(1)
    else:
        success = deployment.deploy()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
