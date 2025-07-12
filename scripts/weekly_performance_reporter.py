#!/usr/bin/env python3
"""
Weekly Performance Reporter
Generates comprehensive weekly performance reports for BetSightly ML system
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.performance_analytics_service import performance_analytics_service
from services.result_correlation_service import result_correlation_service
from utils.common import setup_logging

# Setup logging
logger = setup_logging(__name__)

class WeeklyPerformanceReporter:
    """Generates comprehensive weekly performance reports."""
    
    def __init__(self):
        self.analytics_service = performance_analytics_service
        self.correlation_service = result_correlation_service
        
    def generate_weekly_report(self, weeks: int = 1) -> Dict[str, Any]:
        """Generate a comprehensive weekly performance report."""
        try:
            logger.info(f"📊 Generating weekly performance report for {weeks} week(s)")
            
            # Get analytics dashboard data
            dashboard_data = self.analytics_service.get_comprehensive_dashboard(days=weeks*7)

            # Get future performance prediction as weekly summary
            weekly_summary = self.analytics_service.predict_future_performance(days_ahead=7)
            
            # Generate insights and recommendations
            insights = self._generate_insights(dashboard_data, weekly_summary)
            
            # Create comprehensive report
            report = {
                "report_type": "weekly_performance",
                "period": f"{weeks} week(s)",
                "generated_at": datetime.now().isoformat(),
                "dashboard_data": dashboard_data,
                "weekly_summary": weekly_summary,
                "insights": insights,
                "recommendations": self._generate_recommendations(dashboard_data, insights)
            }
            
            # Save report to file
            report_file = self._save_report(report)
            
            logger.info(f"✅ Weekly report generated successfully: {report_file}")
            return report
            
        except Exception as e:
            logger.error(f"❌ Error generating weekly report: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def _generate_insights(self, dashboard_data: Dict, weekly_summary: Dict) -> Dict[str, Any]:
        """Generate insights from the performance data."""
        try:
            insights = {
                "performance_trend": "stable",
                "accuracy_status": "good",
                "volume_status": "normal",
                "model_performance": {},
                "category_analysis": {},
                "alerts": []
            }
            
            # Analyze overall accuracy
            overall_accuracy = dashboard_data.get('overview', {}).get('overall_accuracy', 0)
            if overall_accuracy >= 80:
                insights["accuracy_status"] = "excellent"
            elif overall_accuracy >= 70:
                insights["accuracy_status"] = "good"
            elif overall_accuracy >= 60:
                insights["accuracy_status"] = "fair"
            else:
                insights["accuracy_status"] = "poor"
                insights["alerts"].append("Low overall accuracy detected")
            
            # Analyze prediction volume
            total_predictions = dashboard_data.get('overview', {}).get('total_predictions', 0)
            if total_predictions < 10:
                insights["volume_status"] = "low"
                insights["alerts"].append("Low prediction volume")
            elif total_predictions > 100:
                insights["volume_status"] = "high"
            
            # Analyze model performance
            models_performance = dashboard_data.get('models_performance', {})
            if models_performance:
                best_model = max(models_performance.items(), key=lambda x: x[1].get('accuracy', 0))
                worst_model = min(models_performance.items(), key=lambda x: x[1].get('accuracy', 0))
                
                insights["model_performance"] = {
                    "best_model": {
                        "name": best_model[0],
                        "accuracy": best_model[1].get('accuracy', 0)
                    },
                    "worst_model": {
                        "name": worst_model[0],
                        "accuracy": worst_model[1].get('accuracy', 0)
                    }
                }
                
                # Check for underperforming models
                for model_name, model_data in models_performance.items():
                    if model_data.get('accuracy', 0) < 50:
                        insights["alerts"].append(f"Model {model_name} underperforming")
            
            # Analyze category performance
            category_performance = dashboard_data.get('category_performance', {})
            for category, data in category_performance.items():
                accuracy = data.get('accuracy', 0)
                if accuracy < 60:
                    insights["alerts"].append(f"Category {category} has low accuracy: {accuracy:.1f}%")
            
            return insights
            
        except Exception as e:
            logger.error(f"❌ Error generating insights: {str(e)}")
            return {"error": str(e)}
    
    def _generate_recommendations(self, dashboard_data: Dict, insights: Dict) -> List[str]:
        """Generate actionable recommendations based on performance data."""
        recommendations = []
        
        try:
            # Accuracy-based recommendations
            accuracy_status = insights.get("accuracy_status", "unknown")
            if accuracy_status == "poor":
                recommendations.append("🔧 Consider retraining models with recent data")
                recommendations.append("📊 Review feature engineering and data quality")
                recommendations.append("🎯 Adjust confidence thresholds for better precision")
            elif accuracy_status == "fair":
                recommendations.append("📈 Monitor model performance closely")
                recommendations.append("🔍 Investigate specific model weaknesses")
            
            # Volume-based recommendations
            volume_status = insights.get("volume_status", "normal")
            if volume_status == "low":
                recommendations.append("📅 Increase prediction frequency")
                recommendations.append("🌍 Consider expanding to more leagues")
            elif volume_status == "high":
                recommendations.append("⚡ Optimize prediction pipeline for performance")
                recommendations.append("💾 Consider database optimization")
            
            # Model-specific recommendations
            model_performance = insights.get("model_performance", {})
            if model_performance:
                best_model = model_performance.get("best_model", {})
                worst_model = model_performance.get("worst_model", {})
                
                if best_model.get("accuracy", 0) > 80:
                    recommendations.append(f"🏆 Increase weight for {best_model.get('name')} model")
                
                if worst_model.get("accuracy", 0) < 50:
                    recommendations.append(f"⚠️ Consider removing or retraining {worst_model.get('name')} model")
            
            # Alert-based recommendations
            alerts = insights.get("alerts", [])
            if "Low overall accuracy detected" in alerts:
                recommendations.append("🚨 URGENT: Review and retrain all models")
            if "Low prediction volume" in alerts:
                recommendations.append("📊 Investigate data source issues")
            
            # General recommendations
            recommendations.extend([
                "📈 Continue monitoring daily performance metrics",
                "🔄 Schedule regular model retraining",
                "📋 Review prediction categories for optimization",
                "🎯 Maintain confidence threshold balance"
            ])
            
            return recommendations
            
        except Exception as e:
            logger.error(f"❌ Error generating recommendations: {str(e)}")
            return ["❌ Error generating recommendations"]
    
    def _save_report(self, report: Dict) -> str:
        """Save the report to a file."""
        try:
            # Create reports directory if it doesn't exist
            reports_dir = Path("reports")
            reports_dir.mkdir(exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"weekly_performance_report_{timestamp}.json"
            filepath = reports_dir / filename
            
            # Save report
            with open(filepath, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            
            logger.info(f"📄 Report saved to: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"❌ Error saving report: {str(e)}")
            return "error_saving_report"
    
    def generate_summary_text(self, report: Dict) -> str:
        """Generate a human-readable summary of the report."""
        try:
            dashboard = report.get('dashboard_data', {}).get('overview', {})
            insights = report.get('insights', {})
            
            summary = f"""
📊 BetSightly Weekly Performance Report
{'='*50}

📅 Period: {report.get('period', 'Unknown')}
🕐 Generated: {report.get('generated_at', 'Unknown')}

📈 PERFORMANCE OVERVIEW
• Total Predictions: {dashboard.get('total_predictions', 0)}
• Overall Accuracy: {dashboard.get('overall_accuracy', 0):.1f}%
• Successful Predictions: {dashboard.get('successful_predictions', 0)}
• Failed Predictions: {dashboard.get('failed_predictions', 0)}

🎯 PERFORMANCE STATUS
• Accuracy Status: {insights.get('accuracy_status', 'Unknown').upper()}
• Volume Status: {insights.get('volume_status', 'Unknown').upper()}
• Performance Trend: {insights.get('performance_trend', 'Unknown').upper()}

🏆 BEST PERFORMING MODEL
• Model: {insights.get('model_performance', {}).get('best_model', {}).get('name', 'Unknown')}
• Accuracy: {insights.get('model_performance', {}).get('best_model', {}).get('accuracy', 0):.1f}%

⚠️ ALERTS ({len(insights.get('alerts', []))})
"""
            
            for alert in insights.get('alerts', []):
                summary += f"• {alert}\n"
            
            summary += f"""
🔧 RECOMMENDATIONS ({len(report.get('recommendations', []))})
"""
            
            for rec in report.get('recommendations', [])[:5]:  # Show top 5
                summary += f"• {rec}\n"
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Error generating summary text: {str(e)}")
            return "Error generating summary"

def main():
    """Main function for command line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Weekly Performance Reporter")
    parser.add_argument("--weeks", type=int, default=1, help="Number of weeks to analyze")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--summary", "-s", action="store_true", help="Print summary to console")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    reporter = WeeklyPerformanceReporter()
    report = reporter.generate_weekly_report(args.weeks)
    
    if report.get('status') != 'error':
        print("✅ Weekly performance report generated successfully")
        
        if args.summary:
            summary = reporter.generate_summary_text(report)
            print(summary)
    else:
        print(f"❌ Failed to generate report: {report.get('error', 'Unknown error')}")
        sys.exit(1)

if __name__ == "__main__":
    main()
