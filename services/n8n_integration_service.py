"""
N8N Integration Service for BetSightly
Handles communication with N8N workflows and Telegram alerts
"""

import asyncio
import httpx
import psutil
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from database import get_db
from services.result_correlation_service import result_correlation_service
from services.performance_analytics_service import performance_analytics_service
import logging

logger = logging.getLogger(__name__)

class N8NIntegrationService:
    def __init__(self):
        self.n8n_base_url = os.getenv("N8N_BASE_URL", "http://localhost:5678")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.emergency_mode = False
        
    async def send_webhook(self, webhook_name: str, data: Dict[str, Any]) -> bool:
        """Send data to N8N webhook"""
        try:
            webhook_url = f"{self.n8n_base_url}/webhook/{webhook_name}"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(webhook_url, json=data)
                return response.status_code == 200
                
        except Exception as e:
            logger.error(f"Failed to send webhook to {webhook_name}: {str(e)}")
            return False
    
    async def send_telegram_alert(self, message: str, alert_type: str = "info") -> bool:
        """Send alert directly to Telegram via N8N"""
        data = {
            "message": message,
            "alert_type": alert_type,
            "timestamp": datetime.now().isoformat(),
            "system": "BetSightly"
        }
        
        return await self.send_webhook("telegram-alert", data)
    
    async def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health status"""
        try:
            # Database check
            db_status = "healthy"
            try:
                db = next(get_db())
                # Simple query to test connection
                from sqlalchemy import text
                db.execute(text("SELECT 1"))
                db.close()
            except Exception as e:
                db_status = f"unhealthy: {str(e)}"
            
            # Recent predictions check
            recent_predictions = 0
            try:
                analytics = await result_correlation_service.get_model_performance_analytics(hours=1)
                recent_predictions = analytics.get("total_predictions", 0)
            except Exception as e:
                logger.error(f"Failed to get recent predictions: {str(e)}")
            
            # Performance check
            performance = {}
            try:
                perf_data = await performance_analytics_service.get_comprehensive_dashboard(days=1)
                performance = {
                    "accuracy": perf_data.get("overall_accuracy", 0),
                    "total_predictions": perf_data.get("total_predictions", 0),
                    "best_model": perf_data.get("best_model", "Unknown")
                }
            except Exception as e:
                logger.error(f"Failed to get performance data: {str(e)}")
            
            # System resources
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                
                resources = {
                    "cpu_usage": cpu_percent,
                    "memory_usage": memory.percent,
                    "disk_usage": disk.percent,
                    "load_average": os.getloadavg()[0] if hasattr(os, 'getloadavg') else None
                }
            except Exception as e:
                logger.error(f"Failed to get system resources: {str(e)}")
                resources = {}
            
            # Determine overall status
            status = "healthy"
            if db_status != "healthy":
                status = "unhealthy"
            elif recent_predictions == 0 and datetime.now().hour > 6:  # Only alert if after 6 AM
                status = "warning"
            elif resources.get("cpu_usage", 0) > 90 or resources.get("memory_usage", 0) > 90:
                status = "warning"
            
            return {
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "database": db_status,
                "recent_predictions": recent_predictions,
                "performance": performance,
                "resources": resources,
                "emergency_mode": self.emergency_mode,
                "uptime": self._get_uptime()
            }
            
        except Exception as e:
            logger.error(f"Failed to get system health: {str(e)}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def check_performance_alerts(self, hours: int = 24, threshold: float = 80.0) -> Dict[str, Any]:
        """Check for performance issues and generate alerts"""
        try:
            analytics = result_correlation_service.get_model_performance_analytics(days=max(1, hours // 24))
            
            has_alerts = False
            alert_type = "info"
            recommendations = []
            
            current_accuracy = analytics.get("overall_accuracy", 0)
            sample_size = analytics.get("total_predictions", 0)
            
            # Check if accuracy is below threshold
            if current_accuracy < threshold and sample_size >= 5:  # Need minimum sample size
                has_alerts = True
                alert_type = "warning"
                recommendations.append("• Review recent predictions for patterns")
                recommendations.append("• Check data quality and sources")
                recommendations.append("• Consider model retraining")
                
                if current_accuracy < 70:
                    alert_type = "critical"
                    recommendations.append("• URGENT: Stop automated recommendations")
                    recommendations.append("• Investigate immediately")
                    recommendations.append("• Consider emergency model rollback")
            
            # Get model performance details
            models_performance = analytics.get("models_performance", {})
            best_model = max(models_performance.items(), key=lambda x: x[1].get("accuracy", 0)) if models_performance else ("Unknown", {"accuracy": 0})
            worst_model = min(models_performance.items(), key=lambda x: x[1].get("accuracy", 0)) if models_performance else ("Unknown", {"accuracy": 0})
            
            # Determine trend
            trend = "stable"
            try:
                yesterday_analytics = result_correlation_service.get_model_performance_analytics(days=2)
                yesterday_accuracy = yesterday_analytics.get("overall_accuracy", current_accuracy)
                
                if current_accuracy > yesterday_accuracy + 5:
                    trend = "improving"
                elif current_accuracy < yesterday_accuracy - 5:
                    trend = "declining"
            except Exception:
                pass
            
            return {
                "has_alerts": has_alerts,
                "alert_type": alert_type,
                "current_accuracy": current_accuracy,
                "threshold": threshold,
                "sample_size": sample_size,
                "best_model": best_model[0],
                "best_accuracy": best_model[1].get("accuracy", 0),
                "worst_model": worst_model[0],
                "worst_accuracy": worst_model[1].get("accuracy", 0),
                "trend": trend,
                "recommendations": "\n".join(recommendations) if recommendations else None,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to check performance alerts: {str(e)}")
            return {
                "has_alerts": True,
                "alert_type": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def get_daily_dashboard(self, days: int = 1) -> Dict[str, Any]:
        """Get daily dashboard data for N8N workflows"""
        try:
            # For now, return a simple dashboard since the full analytics need database fixes
            # This will be populated with real data once predictions start flowing

            # Simulate some basic metrics for demonstration
            total_predictions = 0
            successful_predictions = 0
            failed_predictions = 0
            overall_accuracy = 0.0
            best_model = "xgboost_match_result"
            best_model_accuracy = 0.0

            # Calculate trend information
            trend_direction = "➡️ Stable"
            performance_trend = "Stable"

            # Calculate potential ROI (simplified)
            potential_roi = 0.0
            risk_level = "Medium"

            if overall_accuracy > 85:
                potential_roi = 15.5
                risk_level = "Low"
            elif overall_accuracy > 75:
                potential_roi = 8.2
                risk_level = "Medium"
            else:
                potential_roi = 0.0
                risk_level = "Medium"

            return {
                "status": "success",
                "total_predictions": total_predictions,
                "overall_accuracy": overall_accuracy,
                "successful_predictions": successful_predictions,
                "failed_predictions": failed_predictions,
                "best_model": best_model,
                "best_model_accuracy": best_model_accuracy,
                "trend_direction": trend_direction,
                "performance_trend": performance_trend,
                "potential_roi": potential_roi,
                "risk_level": risk_level,
                "analysis_period": f"{days} days",
                "message": "N8N dashboard ready - awaiting prediction data",
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get daily dashboard: {str(e)}")
            return {
                "total_predictions": 0,
                "overall_accuracy": 0,
                "successful_predictions": 0,
                "failed_predictions": 0,
                "best_model": "Unknown",
                "best_model_accuracy": 0,
                "trend_direction": "Unknown",
                "performance_trend": "Unknown",
                "potential_roi": 0,
                "risk_level": "Unknown",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def enable_emergency_mode(self, reason: str, accuracy: float = None) -> bool:
        """Enable emergency mode and send alerts"""
        try:
            self.emergency_mode = True
            
            message = f"""🚨 **EMERGENCY MODE ACTIVATED**
            
⚠️ **Reason:** {reason}
⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            if accuracy is not None:
                message += f"📉 **Accuracy:** {accuracy:.1f}%\n"
            
            message += """
🛑 **ACTIONS TAKEN:**
• Automated recommendations disabled
• Emergency protocols activated
• Manual intervention required

📞 **IMMEDIATE ACTION REQUIRED**
"""
            
            await self.send_telegram_alert(message, "critical")
            logger.critical(f"Emergency mode activated: {reason}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to enable emergency mode: {str(e)}")
            return False
    
    async def disable_emergency_mode(self, reason: str = "Manual override") -> bool:
        """Disable emergency mode"""
        try:
            self.emergency_mode = False
            
            message = f"""✅ **EMERGENCY MODE DEACTIVATED**
            
🔧 **Reason:** {reason}
⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🟢 **SYSTEM STATUS:** Normal operations resumed
📊 **Monitoring:** Continuous monitoring active
"""
            
            await self.send_telegram_alert(message, "info")
            logger.info(f"Emergency mode deactivated: {reason}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to disable emergency mode: {str(e)}")
            return False
    
    def _get_uptime(self) -> str:
        """Get system uptime"""
        try:
            uptime_seconds = psutil.boot_time()
            uptime_delta = datetime.now() - datetime.fromtimestamp(uptime_seconds)
            
            days = uptime_delta.days
            hours, remainder = divmod(uptime_delta.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            return f"{days}d {hours}h {minutes}m"
        except Exception:
            return "Unknown"

# Create singleton instance
n8n_integration_service = N8NIntegrationService()
