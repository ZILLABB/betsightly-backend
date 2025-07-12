"""
N8N Integration API Endpoints
Provides endpoints for N8N workflows and system monitoring
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime

from database import get_db
from services.n8n_integration_service import n8n_integration_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/n8n", tags=["N8N Integration"])

class EmergencyModeRequest(BaseModel):
    enabled: bool
    reason: str
    accuracy: Optional[float] = None

class WebhookData(BaseModel):
    message: str
    alert_type: str = "info"
    data: Optional[Dict[str, Any]] = None

@router.get("/health")
async def get_system_health():
    """
    Get comprehensive system health status for N8N monitoring
    
    Returns detailed health information including:
    - Database status
    - Recent predictions count
    - Performance metrics
    - System resources
    - Emergency mode status
    """
    try:
        health_data = await n8n_integration_service.get_system_health()
        return health_data
    except Exception as e:
        logger.error(f"Failed to get system health: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/performance-check")
async def check_performance(
    hours: int = 24,
    threshold: float = 80.0
):
    """
    Check system performance and generate alerts
    
    Args:
        hours: Number of hours to analyze (default: 24)
        threshold: Accuracy threshold for alerts (default: 80%)
    
    Returns performance analysis with alert information
    """
    try:
        performance_data = await n8n_integration_service.check_performance_alerts(
            hours=hours, 
            threshold=threshold
        )
        return performance_data
    except Exception as e:
        logger.error(f"Failed to check performance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard")
async def get_dashboard_data(days: int = 1):
    """
    Get dashboard data for N8N workflows
    
    Args:
        days: Number of days to analyze (default: 1)
    
    Returns comprehensive dashboard data including trends and ROI
    """
    try:
        dashboard_data = await n8n_integration_service.get_daily_dashboard(days=days)
        return dashboard_data
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/emergency-mode")
async def set_emergency_mode(request: EmergencyModeRequest):
    """
    Enable or disable emergency mode
    
    Emergency mode disables automated recommendations and sends alerts
    """
    try:
        if request.enabled:
            success = await n8n_integration_service.enable_emergency_mode(
                reason=request.reason,
                accuracy=request.accuracy
            )
        else:
            success = await n8n_integration_service.disable_emergency_mode(
                reason=request.reason
            )
        
        if success:
            return {
                "success": True,
                "emergency_mode": request.enabled,
                "reason": request.reason,
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update emergency mode")
            
    except Exception as e:
        logger.error(f"Failed to set emergency mode: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/emergency-mode")
async def get_emergency_mode():
    """Get current emergency mode status"""
    try:
        return {
            "emergency_mode": n8n_integration_service.emergency_mode,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get emergency mode status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook/{webhook_name}")
async def send_webhook(webhook_name: str, data: Dict[str, Any]):
    """
    Send data to N8N webhook
    
    Args:
        webhook_name: Name of the N8N webhook
        data: Data to send to the webhook
    """
    try:
        success = await n8n_integration_service.send_webhook(webhook_name, data)
        
        if success:
            return {
                "success": True,
                "webhook": webhook_name,
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to send webhook")
            
    except Exception as e:
        logger.error(f"Failed to send webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/telegram-alert")
async def send_telegram_alert(data: WebhookData):
    """
    Send alert to Telegram via N8N
    
    Args:
        data: Alert data including message and type
    """
    try:
        success = await n8n_integration_service.send_telegram_alert(
            message=data.message,
            alert_type=data.alert_type
        )
        
        if success:
            return {
                "success": True,
                "message": "Alert sent successfully",
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to send Telegram alert")
            
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/system/resources")
async def get_system_resources():
    """
    Get detailed system resource usage
    
    Returns CPU, memory, disk usage and load average
    """
    try:
        import psutil
        import os
        
        # Get system resources
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        resources = {
            "cpu_usage": cpu_percent,
            "memory_usage": memory.percent,
            "memory_total": memory.total,
            "memory_available": memory.available,
            "disk_usage": disk.percent,
            "disk_total": disk.total,
            "disk_free": disk.free,
            "load_average": os.getloadavg()[0] if hasattr(os, 'getloadavg') else None,
            "timestamp": datetime.now().isoformat()
        }
        
        return resources
        
    except Exception as e:
        logger.error(f"Failed to get system resources: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/system/pipeline-status")
async def get_pipeline_status():
    """
    Get data pipeline status for monitoring
    
    Returns information about data fetching, processing, and prediction generation
    """
    try:
        from services.result_correlation_service import result_correlation_service
        
        # Check recent activity
        recent_predictions = await result_correlation_service.get_model_performance_analytics(hours=1)
        
        # Check data freshness
        last_update = datetime.now()  # This would come from your data pipeline
        
        # Determine pipeline status
        predictions_count = recent_predictions.get("total_predictions", 0)
        
        if predictions_count > 0:
            status = "active"
        elif datetime.now().hour < 6:  # Early morning - expected low activity
            status = "idle"
        else:
            status = "inactive"
        
        return {
            "status": status,
            "recent_predictions": predictions_count,
            "last_update": last_update.isoformat(),
            "pipeline_health": "healthy" if status in ["active", "idle"] else "warning",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get pipeline status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/system/metrics")
async def get_system_metrics():
    """
    Get comprehensive system metrics for monitoring dashboards
    
    Returns detailed metrics including performance, resources, and health
    """
    try:
        # Get all system data
        health = await n8n_integration_service.get_system_health()
        performance = await n8n_integration_service.check_performance_alerts()
        
        # Combine into comprehensive metrics
        metrics = {
            "system_health": health,
            "performance_alerts": performance,
            "emergency_mode": n8n_integration_service.emergency_mode,
            "timestamp": datetime.now().isoformat(),
            "uptime": health.get("uptime", "Unknown"),
            "overall_status": health.get("status", "unknown")
        }
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to get system metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-alert")
async def test_alert():
    """
    Send a test alert to verify N8N and Telegram integration
    """
    try:
        test_message = f"""🧪 **Test Alert from BetSightly**

⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔧 **Type:** System Test
✅ **Status:** N8N Integration Working

This is a test message to verify that the N8N and Telegram integration is working correctly.

🚀 **System Status:** All systems operational
📊 **Integration:** N8N ↔️ BetSightly ↔️ Telegram
"""
        
        success = await n8n_integration_service.send_telegram_alert(test_message, "test")
        
        if success:
            return {
                "success": True,
                "message": "Test alert sent successfully",
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to send test alert")
            
    except Exception as e:
        logger.error(f"Failed to send test alert: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
