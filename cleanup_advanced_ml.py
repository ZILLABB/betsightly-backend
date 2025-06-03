#!/usr/bin/env python3
"""
Advanced ML Cleanup Script

Remove all redundant files now that we have the advanced_prediction_service.
Keep only the essential components for production.
"""

import os
import shutil
import logging
from pathlib import Path
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AdvancedMLCleanup:
    """Clean up redundant files after advanced ML integration."""
    
    def __init__(self):
        self.project_root = Path(".")
        self.backup_dir = Path("cleanup_backup")
        
        # Files to remove (redundant training scripts)
        self.training_scripts_to_remove = [
            "train_models_hybrid.py",
            "train_models_quick.py", 
            "train_models_streaming.py",
            "ml_hybrid_pipeline.py",
            "ml_prediction_pipeline.py",
            "create_ml_models.py",
            "daily_advanced_predictions.py",
            "daily_predictions_xgboost.py",
            "evaluate_advanced_models.py",
            "evaluate_models.py"
        ]
        
        # Redundant prediction/test scripts
        self.prediction_scripts_to_remove = [
            "real_fixtures_prediction.py",
            "real_prediction_pipeline.py", 
            "predict_with_github_models.py",
            "generate_all_categories.py",
            "generate_rollover_predictions.py",
            "generate_rollover_with_reuse.py",
            "display_all_predictions.py",
            "display_current_predictions.py",
            "display_frontend_categories.py",
            "display_highest_confidence.py",
            "display_may22_predictions.py",
            "display_may23_predictions.py",
            "display_optimized_categories.py",
            "display_safe_bets.py",
            "optimize_categories.py",
            "optimize_highest_confidence.py",
            "optimize_may23_predictions.py",
            "optimize_safe_bets.py",
            "parse_best_predictions.py",
            "retrieve_categorized_predictions.py",
            "show_live_predictions.py"
        ]
        
        # Test and debug scripts
        self.test_scripts_to_remove = [
            "test_api.py",
            "test_api_functionality.py",
            "test_api_simple.py",
            "test_basketball_categories.py",
            "test_enhanced_api.py",
            "test_hybrid_simple.py",
            "test_live_api.py",
            "test_live_predictions.py",
            "test_model_loading.py",
            "test_prediction_pipeline.py",
            "test_quick_service.py",
            "test_real_basketball_models.py",
            "test_xgboost.py",
            "debug_fixtures.py",
            "debug_health_endpoint.py",
            "simplified_real_test.py"
        ]
        
        # Data processing scripts (replaced by advanced service)
        self.data_scripts_to_remove = [
            "fetch_fixtures.py",
            "fetch_fixtures_odds.py", 
            "fetch_football_data.py",
            "fetch_historical_data.py",
            "fetch_odds_by_bet.py",
            "prepare_football_data.py",
            "collect_enhanced_data.py",
            "process_additional_fixtures.py",
            "process_may22_fixtures.py",
            "update_fixtures_may23.py"
        ]
        
        # Utility and setup scripts (redundant)
        self.utility_scripts_to_remove = [
            "comprehensive_analysis.py",
            "initialize_ml_enhancements.py",
            "simple_init.py",
            "quick_verify.py",
            "verify_improvements.py",
            "verify_installation.py",
            "verify_basketball_models.py",
            "cleanup_redundant_files.py",
            "migrate_to_production.py",
            "deploy_heroku.py",
            "deploy_production.py",
            "deploy_render.py",
            "production_monitor.py"
        ]
        
        # Check scripts (replaced by model info endpoint)
        self.check_scripts_to_remove = [
            "check_all_fixture_times.py",
            "check_categories.py",
            "check_database.py",
            "check_db.py",
            "check_game_times.py",
            "check_latest_betting_codes.py",
            "check_prediction_categorization.py",
            "check_rollover.py",
            "check_rollover_db.py",
            "check_telegram_db.py",
            "check_todays_rollover.py",
            "check_training_status.py"
        ]
        
        # Documentation files (outdated)
        self.docs_to_remove = [
            "BASKETBALL_CATEGORIES_IMPLEMENTATION.md",
            "BASKETBALL_INTEGRATION_GUIDE.md", 
            "FIXES_APPLIED.md",
            "HIGH_PRIORITY_FIXES_SUMMARY.md",
            "HYBRID_IMPLEMENTATION_GUIDE.md",
            "ML_ENHANCEMENT_ROADMAP.md",
            "README_PRODUCTION.md",
            "README_STREAMLINED_PIPELINE.md"
        ]
        
        # Directories to remove (if empty)
        self.dirs_to_check = [
            "catboost_info",
            "frontend_example", 
            "predictions",
            "results",
            "logs"
        ]
        
        # Cache files to clean
        self.cache_patterns = [
            "cache/*.json",
            "*.log",
            "*.db-shm",
            "*.db-wal", 
            "*.backup_*"
        ]
    
    def create_backup(self):
        """Create backup of files before deletion."""
        if self.backup_dir.exists():
            shutil.rmtree(self.backup_dir)
        
        self.backup_dir.mkdir()
        logger.info(f"Created backup directory: {self.backup_dir}")
    
    def remove_file_list(self, file_list, category_name):
        """Remove a list of files."""
        removed_count = 0
        
        for file_path in file_list:
            full_path = self.project_root / file_path
            if full_path.exists():
                try:
                    # Backup before removal
                    backup_path = self.backup_dir / file_path
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(full_path, backup_path)
                    
                    # Remove original
                    full_path.unlink()
                    removed_count += 1
                    logger.info(f"✅ Removed {category_name}: {file_path}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to remove {file_path}: {str(e)}")
        
        logger.info(f"📊 Removed {removed_count} {category_name} files")
        return removed_count
    
    def clean_cache_files(self):
        """Clean cache and temporary files."""
        removed_count = 0
        
        # Clean cache directory
        cache_dir = self.project_root / "cache"
        if cache_dir.exists():
            try:
                shutil.rmtree(cache_dir)
                removed_count += 1
                logger.info("✅ Removed cache directory")
            except Exception as e:
                logger.error(f"❌ Failed to remove cache: {str(e)}")
        
        # Clean __pycache__ directories
        for pycache_dir in self.project_root.rglob("__pycache__"):
            try:
                shutil.rmtree(pycache_dir)
                removed_count += 1
                logger.info(f"✅ Removed {pycache_dir}")
            except Exception as e:
                logger.error(f"❌ Failed to remove {pycache_dir}: {str(e)}")
        
        # Clean log files
        for log_file in self.project_root.glob("*.log"):
            try:
                log_file.unlink()
                removed_count += 1
                logger.info(f"✅ Removed log file: {log_file}")
            except Exception as e:
                logger.error(f"❌ Failed to remove {log_file}: {str(e)}")
        
        logger.info(f"📊 Cleaned {removed_count} cache/temp items")
        return removed_count
    
    def remove_empty_directories(self):
        """Remove empty directories."""
        removed_count = 0
        
        for dir_name in self.dirs_to_check:
            dir_path = self.project_root / dir_name
            if dir_path.exists() and dir_path.is_dir():
                try:
                    # Check if directory is empty or contains only empty subdirs
                    if not any(dir_path.rglob("*")):
                        shutil.rmtree(dir_path)
                        removed_count += 1
                        logger.info(f"✅ Removed empty directory: {dir_name}")
                except Exception as e:
                    logger.error(f"❌ Failed to remove directory {dir_name}: {str(e)}")
        
        logger.info(f"📊 Removed {removed_count} empty directories")
        return removed_count

    def run_comprehensive_cleanup(self):
        """Run the complete cleanup process."""
        logger.info("🧹 Starting Advanced ML Cleanup...")
        logger.info("=" * 60)

        # Create backup
        self.create_backup()

        total_removed = 0

        # Remove redundant training scripts
        logger.info("\n🤖 Cleaning Training Scripts...")
        total_removed += self.remove_file_list(self.training_scripts_to_remove, "training scripts")

        # Remove redundant prediction scripts
        logger.info("\n🎯 Cleaning Prediction Scripts...")
        total_removed += self.remove_file_list(self.prediction_scripts_to_remove, "prediction scripts")

        # Remove test and debug scripts
        logger.info("\n🧪 Cleaning Test Scripts...")
        total_removed += self.remove_file_list(self.test_scripts_to_remove, "test scripts")

        # Remove data processing scripts
        logger.info("\n📊 Cleaning Data Scripts...")
        total_removed += self.remove_file_list(self.data_scripts_to_remove, "data scripts")

        # Remove utility scripts
        logger.info("\n🔧 Cleaning Utility Scripts...")
        total_removed += self.remove_file_list(self.utility_scripts_to_remove, "utility scripts")

        # Remove check scripts
        logger.info("\n✅ Cleaning Check Scripts...")
        total_removed += self.remove_file_list(self.check_scripts_to_remove, "check scripts")

        # Remove outdated documentation
        logger.info("\n📚 Cleaning Documentation...")
        total_removed += self.remove_file_list(self.docs_to_remove, "documentation files")

        # Clean cache and temporary files
        logger.info("\n🗑️ Cleaning Cache Files...")
        total_removed += self.clean_cache_files()

        # Remove empty directories
        logger.info("\n📁 Cleaning Empty Directories...")
        total_removed += self.remove_empty_directories()

        # Generate summary
        self.generate_cleanup_summary(total_removed)

        logger.info("\n🎉 Advanced ML Cleanup Complete!")
        logger.info(f"📊 Total items removed: {total_removed}")
        logger.info(f"💾 Backup created in: {self.backup_dir}")
        logger.info("🚀 Your codebase is now streamlined for advanced ML!")

    def generate_cleanup_summary(self, total_removed):
        """Generate cleanup summary report."""
        summary_file = self.project_root / "CLEANUP_SUMMARY.md"

        with open(summary_file, 'w') as f:
            f.write("# 🧹 Advanced ML Cleanup Summary\n\n")
            f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Total Items Removed**: {total_removed}\n\n")

            f.write("## 🎯 What Was Cleaned\n\n")
            f.write("### Redundant Training Scripts\n")
            for script in self.training_scripts_to_remove:
                f.write(f"- ❌ {script}\n")

            f.write("\n### Redundant Prediction Scripts\n")
            for script in self.prediction_scripts_to_remove[:10]:  # Show first 10
                f.write(f"- ❌ {script}\n")
            if len(self.prediction_scripts_to_remove) > 10:
                f.write(f"- ... and {len(self.prediction_scripts_to_remove) - 10} more\n")

            f.write("\n### Test and Debug Scripts\n")
            for script in self.test_scripts_to_remove[:10]:  # Show first 10
                f.write(f"- ❌ {script}\n")
            if len(self.test_scripts_to_remove) > 10:
                f.write(f"- ... and {len(self.test_scripts_to_remove) - 10} more\n")

            f.write("\n## ✅ What Was Kept\n\n")
            f.write("### Core Production Files\n")
            f.write("- ✅ `services/advanced_prediction_service.py` - **Main ML service**\n")
            f.write("- ✅ `services/basic_prediction_service.py` - **Fallback service**\n")
            f.write("- ✅ `services/quick_prediction_service.py` - **Fast predictions**\n")
            f.write("- ✅ `services/cached_prediction_service.py` - **Performance optimization**\n")
            f.write("- ✅ `ml/` directory - **All ML models and components**\n")
            f.write("- ✅ `models/` directory - **Pre-trained models**\n")
            f.write("- ✅ `api/endpoints/predictions.py` - **Advanced API endpoints**\n")
            f.write("- ✅ `main.py` - **Production server**\n")
            f.write("- ✅ `basketball/` directory - **Basketball predictions**\n")

            f.write("\n## 🚀 Next Steps\n\n")
            f.write("1. **Test the streamlined system**: `python -m pytest tests/`\n")
            f.write("2. **Deploy to production**: The codebase is now optimized\n")
            f.write("3. **Monitor performance**: Use `/api/predictions/models/info` endpoint\n")
            f.write("4. **Remove backup**: Delete `cleanup_backup/` when satisfied\n")

            f.write("\n## 📊 Advanced ML Features Active\n\n")
            f.write("- 🤖 **XGBoost Models**: High-accuracy predictions\n")
            f.write("- 🎯 **Ensemble Methods**: Multiple model voting\n")
            f.write("- 🔍 **SHAP Explanations**: Model interpretability\n")
            f.write("- ⚡ **Meta-Stacking**: Advanced model combination\n")
            f.write("- 🏗️ **Advanced Feature Engineering**: Sophisticated features\n")
            f.write("- 📈 **Real-time Predictions**: Live football data\n")

        logger.info(f"📄 Generated cleanup summary: {summary_file}")


def main():
    """Main cleanup execution."""
    cleanup = AdvancedMLCleanup()
    cleanup.run_comprehensive_cleanup()


if __name__ == "__main__":
    main()
