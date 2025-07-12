#!/usr/bin/env python3
"""
Daily Result Correlation Runner
Automatically fetches match results and correlates with predictions
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.result_correlation_service import result_correlation_service
from services.performance_analytics_service import performance_analytics_service
from utils.common import setup_logging

# Setup logging
logger = setup_logging(__name__)

class DailyCorrelationRunner:
    """Handles daily result correlation and performance tracking."""
    
    def __init__(self):
        self.correlation_service = result_correlation_service
        self.analytics_service = performance_analytics_service
        
    def run_daily_correlation(self, date_str: str = None) -> dict:
        """Run daily correlation for a specific date."""
        try:
            if not date_str:
                # Default to yesterday (results are usually available the next day)
                yesterday = datetime.now() - timedelta(days=1)
                date_str = yesterday.strftime('%Y-%m-%d')
            
            logger.info(f"🚀 Starting daily correlation for {date_str}")
            
            # Step 1: Fetch and correlate results
            correlation_result = self.correlation_service.fetch_and_correlate_results(date_str)
            
            if correlation_result.get('status') != 'success':
                logger.warning(f"⚠️  Correlation failed: {correlation_result}")
                return correlation_result
            
            # Step 2: Update performance analytics
            analytics_result = self._update_performance_analytics(date_str, correlation_result)
            
            # Step 3: Generate summary report
            summary = self._generate_daily_summary(date_str, correlation_result, analytics_result)
            
            logger.info(f"✅ Daily correlation completed successfully")
            logger.info(f"📊 Processed {correlation_result.get('correlations_made', 0)} correlations")
            
            return {
                "status": "success",
                "date": date_str,
                "correlation_result": correlation_result,
                "analytics_result": analytics_result,
                "summary": summary
            }
            
        except Exception as e:
            logger.error(f"❌ Error in daily correlation: {str(e)}")
            return {"status": "error", "error": str(e), "date": date_str}
    
    def _update_performance_analytics(self, date_str: str, correlation_result: dict) -> dict:
        """Update performance analytics based on correlation results."""
        try:
            logger.info(f"📈 Updating performance analytics for {date_str}")
            
            # Get comprehensive analytics for the last 30 days
            analytics = self.analytics_service.get_comprehensive_dashboard(30)
            
            return {
                "status": "success",
                "analytics_updated": True,
                "total_predictions_tracked": analytics.get('overview', {}).get('total_predictions', 0),
                "overall_accuracy": analytics.get('overview', {}).get('overall_accuracy', 0),
                "best_model": analytics.get('overview', {}).get('best_model', 'Unknown')
            }
            
        except Exception as e:
            logger.error(f"❌ Error updating analytics: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _generate_daily_summary(self, date_str: str, correlation_result: dict, analytics_result: dict) -> dict:
        """Generate a daily summary report."""
        try:
            correlations = correlation_result.get('correlations', [])
            
            # Calculate daily statistics
            total_correlations = len(correlations)
            correct_predictions = sum(1 for c in correlations if c.get('is_correct', False))
            daily_accuracy = (correct_predictions / total_correlations * 100) if total_correlations > 0 else 0
            
            # Calculate average confidence
            avg_confidence = sum(c.get('confidence', 0) for c in correlations) / total_correlations if total_correlations > 0 else 0
            
            # Group by category
            category_stats = {}
            for correlation in correlations:
                category = correlation.get('category', 'unknown')
                if category not in category_stats:
                    category_stats[category] = {'total': 0, 'correct': 0}
                category_stats[category]['total'] += 1
                if correlation.get('is_correct', False):
                    category_stats[category]['correct'] += 1
            
            # Calculate category accuracies
            for category in category_stats:
                stats = category_stats[category]
                stats['accuracy'] = (stats['correct'] / stats['total'] * 100) if stats['total'] > 0 else 0
            
            summary = {
                "date": date_str,
                "daily_stats": {
                    "total_correlations": total_correlations,
                    "correct_predictions": correct_predictions,
                    "daily_accuracy": round(daily_accuracy, 2),
                    "average_confidence": round(avg_confidence, 3)
                },
                "category_performance": category_stats,
                "overall_analytics": {
                    "total_predictions_tracked": analytics_result.get('total_predictions_tracked', 0),
                    "overall_accuracy": analytics_result.get('overall_accuracy', 0),
                    "best_model": analytics_result.get('best_model', 'Unknown')
                }
            }
            
            logger.info(f"📋 Daily summary generated: {daily_accuracy:.1f}% accuracy on {total_correlations} predictions")
            return summary
            
        except Exception as e:
            logger.error(f"❌ Error generating summary: {str(e)}")
            return {"error": str(e)}
    
    def run_weekly_summary(self) -> dict:
        """Generate a weekly performance summary."""
        try:
            logger.info("📊 Generating weekly performance summary")
            
            # Get 7-day analytics
            weekly_analytics = self.analytics_service.get_comprehensive_dashboard(7)
            
            return {
                "status": "success",
                "period": "7 days",
                "analytics": weekly_analytics,
                "generated_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error generating weekly summary: {str(e)}")
            return {"status": "error", "error": str(e)}

def main():
    """Main function for command line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Daily Result Correlation Runner")
    parser.add_argument("--date", help="Date to process (YYYY-MM-DD). Defaults to yesterday.")
    parser.add_argument("--weekly", action="store_true", help="Generate weekly summary instead")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    runner = DailyCorrelationRunner()
    
    if args.weekly:
        result = runner.run_weekly_summary()
    else:
        result = runner.run_daily_correlation(args.date)
    
    if result.get('status') == 'success':
        print("✅ Daily correlation completed successfully")
        if not args.weekly:
            summary = result.get('summary', {})
            daily_stats = summary.get('daily_stats', {})
            print(f"📊 Processed {daily_stats.get('total_correlations', 0)} predictions")
            print(f"🎯 Daily accuracy: {daily_stats.get('daily_accuracy', 0):.1f}%")
            print(f"🔮 Average confidence: {daily_stats.get('average_confidence', 0):.3f}")
    else:
        print(f"❌ Daily correlation failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)

if __name__ == "__main__":
    main()
