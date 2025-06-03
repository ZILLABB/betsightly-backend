#!/usr/bin/env python3
"""
Daily Cache Scheduler

This script handles automated daily prediction cache generation and
periodic model training for the BetSightly ML system.

Usage:
    python scripts/daily_cache_scheduler.py --task cache
    python scripts/daily_cache_scheduler.py --task training
    python scripts/daily_cache_scheduler.py --task both
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.daily_prediction_cache import daily_prediction_cache
from services.training_pipeline_service import training_pipeline_service
from database import init_db
from utils.common import setup_logging

# Set up logging
logger = setup_logging(__name__)

class DailyCacheScheduler:
    """
    Handles automated scheduling of cache generation and training tasks.
    
    Features:
    - Daily prediction cache generation
    - Weekly model training
    - Error handling and recovery
    - Performance monitoring
    """
    
    def __init__(self):
        """Initialize the scheduler."""
        self.cache_generation_time = "06:00"  # 6 AM UTC - Daily predictions
        self.training_day = "sunday"          # Weekly training on Sundays
        self.training_time = "02:00"          # 2 AM UTC - Weekly training
        self.sports_supported = ["football", "basketball"]  # Both sports
        
    def run_daily_cache_generation(self, date_str: str = None) -> bool:
        """
        Run daily prediction cache generation.
        
        Args:
            date_str: Date to generate cache for (default: today)
            
        Returns:
            True if successful, False otherwise
        """
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        logger.info(f"🚀 Starting daily cache generation for {date_str}")
        
        try:
            # Initialize database if needed
            init_db()
            
            # Generate daily cache
            result = daily_prediction_cache.generate_daily_predictions(date_str)
            
            if result.get('status') == 'success':
                logger.info(f"✅ Daily cache generation completed successfully")
                logger.info(f"📊 Generated {result.get('predictions_cached', 0)} predictions")
                logger.info(f"⏱️  Generation time: {result.get('generation_time_seconds', 0):.2f} seconds")
                
                # Also generate cache for tomorrow
                tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                logger.info(f"🔮 Pre-generating cache for tomorrow ({tomorrow})")
                
                tomorrow_result = daily_prediction_cache.generate_daily_predictions(tomorrow)
                if tomorrow_result.get('status') == 'success':
                    logger.info(f"✅ Tomorrow's cache pre-generated successfully")
                else:
                    logger.warning(f"⚠️  Tomorrow's cache generation failed: {tomorrow_result.get('error')}")
                
                return True
            else:
                logger.error(f"❌ Daily cache generation failed: {result.get('error')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in daily cache generation: {str(e)}")
            return False
    
    def run_weekly_training(self, force_retrain: bool = False) -> bool:
        """
        Run weekly model training using GitHub datasets for football and basketball.

        Args:
            force_retrain: Force retraining even if not needed

        Returns:
            True if successful, False otherwise
        """
        logger.info("🤖 Starting weekly model training")
        logger.info("📊 Training data sources:")
        logger.info("  - Football: GitHub dataset (50,000+ matches)")
        logger.info("  - Basketball: GitHub dataset + recent games")
        logger.info("🗓️  Training frequency: Weekly (Sundays)")

        try:
            # Initialize database if needed
            init_db()

            # Trigger training pipeline with GitHub data
            result = training_pipeline_service.trigger_training(
                training_type='scheduled',
                trigger_reason='weekly_schedule',
                force_retrain=force_retrain
            )
            
            if result.get('status') == 'success':
                logger.info(f"✅ Weekly training completed successfully")
                logger.info(f"🏃 Training run ID: {result.get('training_run_id')}")
                logger.info(f"📈 Deployment status: {result.get('deployment_status')}")
                logger.info(f"⏱️  Training time: {result.get('training_time_seconds', 0):.2f} seconds")
                return True
            else:
                logger.error(f"❌ Weekly training failed: {result.get('error')}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error in weekly training: {str(e)}")
            return False
    
    def run_cache_maintenance(self) -> bool:
        """
        Run cache maintenance tasks.
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("🧹 Starting cache maintenance")
        
        try:
            from database import SessionLocal
            from models.training_models import CachedPrediction, CacheStatus
            
            db = SessionLocal()
            
            try:
                # Clean up expired cache entries
                cutoff_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                
                deleted_predictions = db.query(CachedPrediction).filter(
                    CachedPrediction.prediction_date < cutoff_date
                ).delete()
                
                deleted_status = db.query(CacheStatus).filter(
                    CacheStatus.cache_date < cutoff_date
                ).delete()
                
                db.commit()
                
                logger.info(f"✅ Cache maintenance completed")
                logger.info(f"🗑️  Deleted {deleted_predictions} old predictions")
                logger.info(f"🗑️  Deleted {deleted_status} old status records")
                
                return True
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ Error in cache maintenance: {str(e)}")
            return False
    
    def run_health_check(self) -> bool:
        """
        Run system health check.
        
        Returns:
            True if system is healthy, False otherwise
        """
        logger.info("🏥 Running system health check")
        
        try:
            # Check database connectivity
            from database import SessionLocal
            db = SessionLocal()
            db.execute("SELECT 1")
            db.close()
            logger.info("✅ Database connectivity: OK")
            
            # Check cache service availability
            try:
                from services.daily_prediction_cache import daily_prediction_cache
                logger.info("✅ Daily cache service: Available")
            except Exception as e:
                logger.warning(f"⚠️  Daily cache service: {str(e)}")
            
            # Check training service availability
            try:
                from services.training_pipeline_service import training_pipeline_service
                logger.info("✅ Training pipeline service: Available")
            except Exception as e:
                logger.warning(f"⚠️  Training pipeline service: {str(e)}")
            
            # Check advanced ML service availability
            try:
                from services.advanced_prediction_service import advanced_prediction_service
                model_info = advanced_prediction_service.get_model_info()
                models_loaded = model_info.get('model_info', {}).get('total_models', 0)
                logger.info(f"✅ Advanced ML service: {models_loaded} models loaded")
            except Exception as e:
                logger.warning(f"⚠️  Advanced ML service: {str(e)}")
            
            logger.info("✅ System health check completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ System health check failed: {str(e)}")
            return False

def main():
    """Main entry point for the scheduler."""
    parser = argparse.ArgumentParser(description="Daily Cache Scheduler for BetSightly")
    parser.add_argument(
        "--task",
        choices=["cache", "training", "maintenance", "health", "both"],
        default="cache",
        help="Task to run"
    )
    parser.add_argument(
        "--date",
        help="Date for cache generation (YYYY-MM-DD, default: today)"
    )
    parser.add_argument(
        "--force-retrain",
        action="store_true",
        help="Force model retraining even if not needed"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Set up logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize scheduler
    scheduler = DailyCacheScheduler()
    
    success = True
    
    try:
        if args.task == "cache":
            success = scheduler.run_daily_cache_generation(args.date)
            
        elif args.task == "training":
            success = scheduler.run_weekly_training(args.force_retrain)
            
        elif args.task == "maintenance":
            success = scheduler.run_cache_maintenance()
            
        elif args.task == "health":
            success = scheduler.run_health_check()
            
        elif args.task == "both":
            cache_success = scheduler.run_daily_cache_generation(args.date)
            
            # Only run training on Sundays or if forced
            today = datetime.now().strftime("%A").lower()
            if today == "sunday" or args.force_retrain:
                training_success = scheduler.run_weekly_training(args.force_retrain)
                success = cache_success and training_success
            else:
                logger.info("⏭️  Skipping training (not Sunday)")
                success = cache_success
        
        if success:
            logger.info("🎉 Scheduler task completed successfully")
            sys.exit(0)
        else:
            logger.error("❌ Scheduler task failed")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("⏹️  Scheduler interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
