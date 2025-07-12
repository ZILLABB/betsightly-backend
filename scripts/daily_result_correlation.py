#!/usr/bin/env python3
"""
Daily Result Correlation Script - Automated Performance Tracking

This script:
1. Runs daily to fetch match results
2. Correlates results with stored predictions
3. Updates model performance tracking
4. Generates performance reports
5. Sends alerts if performance drops

Run this script daily via cron job:
0 8 * * * /usr/bin/python3 /path/to/scripts/daily_result_correlation.py
"""

import os
import sys
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from services.result_correlation_service import result_correlation_service
from services.performance_analytics_service import performance_analytics_service

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/daily_correlation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DailyResultCorrelation:
    """Automated daily result correlation and performance tracking."""
    
    def __init__(self):
        """Initialize the daily correlation service."""
        self.correlation_service = result_correlation_service
        self.analytics_service = performance_analytics_service
        
        # Performance thresholds for alerts
        self.ALERT_ACCURACY_THRESHOLD = 0.70
        self.ALERT_DECLINE_THRESHOLD = 0.05
        
        logger.info("✅ Daily Result Correlation initialized")
    
    def run_daily_correlation(self, date_str: str = None) -> dict:
        """Run the complete daily correlation process."""
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
            
            # Step 2: Generate performance analytics
            analytics_result = self.analytics_service.get_comprehensive_dashboard(7)  # Last 7 days
            
            # Step 3: Check for performance alerts
            alerts = self._check_performance_alerts(analytics_result)
            
            # Step 4: Generate daily report
            report = self._generate_daily_report(date_str, correlation_result, analytics_result, alerts)
            
            # Step 5: Save report
            self._save_daily_report(date_str, report)
            
            logger.info(f"✅ Daily correlation completed for {date_str}")
            
            return {
                "status": "success",
                "date": date_str,
                "correlation_result": correlation_result,
                "analytics_result": analytics_result,
                "alerts": alerts,
                "report": report
            }
            
        except Exception as e:
            logger.error(f"❌ Error in daily correlation: {str(e)}")
            return {"status": "error", "error": str(e), "date": date_str}
    
    def _check_performance_alerts(self, analytics: dict) -> list:
        """Check for performance issues and generate alerts."""
        alerts = []
        
        try:
            if analytics.get('status') != 'success':
                return alerts
            
            overview = analytics.get('overview', {})
            trends = analytics.get('trends', {})
            
            # Check overall accuracy
            overall_accuracy = overview.get('overall_accuracy', 0)
            if overall_accuracy < self.ALERT_ACCURACY_THRESHOLD:
                alerts.append({
                    "type": "low_accuracy",
                    "severity": "high",
                    "message": f"Overall accuracy ({overall_accuracy:.1%}) below threshold ({self.ALERT_ACCURACY_THRESHOLD:.1%})",
                    "value": overall_accuracy,
                    "threshold": self.ALERT_ACCURACY_THRESHOLD
                })
            
            # Check for declining trends
            if trends.get('status') == 'success':
                trend_analysis = trends.get('trend_analysis', {})
                accuracy_change = trend_analysis.get('accuracy_change', 0)
                
                if accuracy_change < -self.ALERT_DECLINE_THRESHOLD:
                    alerts.append({
                        "type": "declining_performance",
                        "severity": "medium",
                        "message": f"Performance declined by {abs(accuracy_change):.1%} in recent period",
                        "value": accuracy_change,
                        "threshold": -self.ALERT_DECLINE_THRESHOLD
                    })
            
            # Check model count
            total_models = overview.get('total_models', 0)
            if total_models == 0:
                alerts.append({
                    "type": "no_models",
                    "severity": "critical",
                    "message": "No models are being tracked",
                    "value": total_models
                })
            
            # Check prediction volume
            total_predictions = overview.get('total_predictions', 0)
            if total_predictions < 10:  # Expect at least 10 predictions per week
                alerts.append({
                    "type": "low_volume",
                    "severity": "medium",
                    "message": f"Low prediction volume: {total_predictions} predictions in last 7 days",
                    "value": total_predictions
                })
            
            return alerts
            
        except Exception as e:
            logger.error(f"❌ Error checking alerts: {str(e)}")
            return []
    
    def _generate_daily_report(self, date_str: str, correlation_result: dict, 
                              analytics_result: dict, alerts: list) -> dict:
        """Generate comprehensive daily report."""
        try:
            report = {
                "report_date": date_str,
                "generated_at": datetime.now().isoformat(),
                "summary": {
                    "status": "success",
                    "results_processed": correlation_result.get('results_fetched', 0),
                    "predictions_correlated": correlation_result.get('correlations_made', 0),
                    "alerts_generated": len(alerts)
                },
                "correlation_details": {
                    "results_fetched": correlation_result.get('results_fetched', 0),
                    "predictions_found": correlation_result.get('predictions_found', 0),
                    "correlations_made": correlation_result.get('correlations_made', 0),
                    "accuracy_updates": correlation_result.get('accuracy_updates', {}),
                    "performance_updates": correlation_result.get('performance_updates', {})
                },
                "performance_overview": {},
                "alerts": alerts,
                "recommendations": []
            }
            
            # Add performance overview if available
            if analytics_result.get('status') == 'success':
                overview = analytics_result.get('overview', {})
                report["performance_overview"] = {
                    "overall_accuracy": overview.get('overall_accuracy', 0),
                    "avg_confidence": overview.get('avg_confidence', 0),
                    "total_models": overview.get('total_models', 0),
                    "best_model": overview.get('best_model')
                }
                
                # Add recommendations from analytics
                recommendations = analytics_result.get('recommendations', {})
                report["recommendations"] = recommendations
            
            # Add daily insights
            report["insights"] = self._generate_daily_insights(correlation_result, analytics_result)
            
            return report
            
        except Exception as e:
            logger.error(f"❌ Error generating report: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _generate_daily_insights(self, correlation_result: dict, analytics_result: dict) -> list:
        """Generate actionable insights from daily data."""
        insights = []
        
        try:
            # Correlation insights
            correlations_made = correlation_result.get('correlations_made', 0)
            if correlations_made > 0:
                insights.append(f"Successfully correlated {correlations_made} predictions with actual results")
            
            # Performance insights
            if analytics_result.get('status') == 'success':
                overview = analytics_result.get('overview', {})
                accuracy = overview.get('overall_accuracy', 0)
                
                if accuracy > 0.90:
                    insights.append("🎉 Excellent performance! Accuracy above 90%")
                elif accuracy > 0.80:
                    insights.append("✅ Good performance! Accuracy above 80%")
                elif accuracy > 0.70:
                    insights.append("⚠️  Moderate performance. Consider model improvements")
                else:
                    insights.append("🚨 Poor performance. Immediate attention required")
                
                # Best model insight
                best_model = overview.get('best_model')
                if best_model:
                    insights.append(f"🏆 Best performing model: {best_model[0]} ({best_model[1]['accuracy']:.1%} accuracy)")
            
            return insights
            
        except Exception as e:
            logger.error(f"❌ Error generating insights: {str(e)}")
            return ["Error generating insights"]
    
    def _save_daily_report(self, date_str: str, report: dict) -> None:
        """Save daily report to file."""
        try:
            # Create reports directory if it doesn't exist
            reports_dir = Path("reports/daily_correlation")
            reports_dir.mkdir(parents=True, exist_ok=True)
            
            # Save report as JSON
            report_file = reports_dir / f"correlation_report_{date_str}.json"
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            
            logger.info(f"📄 Daily report saved: {report_file}")
            
        except Exception as e:
            logger.error(f"❌ Error saving report: {str(e)}")
    
    def run_weekly_summary(self) -> dict:
        """Generate weekly performance summary."""
        try:
            logger.info("📊 Generating weekly performance summary")
            
            # Get 7-day analytics
            analytics = self.analytics_service.get_comprehensive_dashboard(7)
            
            if analytics.get('status') != 'success':
                return analytics
            
            # Get best models over the week
            best_models = self.analytics_service.correlation_service.get_best_models_over_time(7)
            
            # Generate weekly insights
            weekly_summary = {
                "period": "7_days",
                "generated_at": datetime.now().isoformat(),
                "performance_summary": analytics.get('overview', {}),
                "best_models": best_models.get('weighted_rankings', [])[:5],
                "trends": analytics.get('trends', {}),
                "category_performance": analytics.get('category_performance', {}),
                "league_performance": analytics.get('league_performance', {}),
                "recommendations": analytics.get('recommendations', {}),
                "weekly_insights": self._generate_weekly_insights(analytics)
            }
            
            # Save weekly summary
            self._save_weekly_summary(weekly_summary)
            
            return weekly_summary
            
        except Exception as e:
            logger.error(f"❌ Error generating weekly summary: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _generate_weekly_insights(self, analytics: dict) -> list:
        """Generate weekly insights."""
        insights = []
        
        try:
            overview = analytics.get('overview', {})
            trends = analytics.get('trends', {})
            
            # Overall performance insight
            accuracy = overview.get('overall_accuracy', 0)
            total_predictions = overview.get('total_predictions', 0)
            
            insights.append(f"📊 Weekly Performance: {accuracy:.1%} accuracy across {total_predictions} predictions")
            
            # Trend insight
            if trends.get('status') == 'success':
                trend_analysis = trends.get('trend_analysis', {})
                trend_direction = trend_analysis.get('accuracy_trend', 'unknown')
                
                if trend_direction == 'improving':
                    insights.append("📈 Performance is improving over time")
                elif trend_direction == 'declining':
                    insights.append("📉 Performance is declining - attention needed")
                else:
                    insights.append("📊 Performance is stable")
            
            # Model insights
            total_models = overview.get('total_models', 0)
            insights.append(f"🤖 Tracking {total_models} models for performance optimization")
            
            return insights
            
        except Exception as e:
            logger.error(f"❌ Error generating weekly insights: {str(e)}")
            return ["Error generating weekly insights"]
    
    def _save_weekly_summary(self, summary: dict) -> None:
        """Save weekly summary to file."""
        try:
            reports_dir = Path("reports/weekly_summaries")
            reports_dir.mkdir(parents=True, exist_ok=True)
            
            week_start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            week_end = datetime.now().strftime('%Y-%m-%d')
            
            summary_file = reports_dir / f"weekly_summary_{week_start}_to_{week_end}.json"
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
            
            logger.info(f"📄 Weekly summary saved: {summary_file}")
            
        except Exception as e:
            logger.error(f"❌ Error saving weekly summary: {str(e)}")

def main():
    """Main function for command line execution."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Daily Result Correlation')
    parser.add_argument('--date', type=str, help='Date to process (YYYY-MM-DD)')
    parser.add_argument('--weekly', action='store_true', help='Generate weekly summary')
    
    args = parser.parse_args()
    
    correlation_service = DailyResultCorrelation()
    
    if args.weekly:
        result = correlation_service.run_weekly_summary()
        print(json.dumps(result, indent=2, default=str))
    else:
        result = correlation_service.run_daily_correlation(args.date)
        print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
