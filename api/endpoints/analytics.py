#!/usr/bin/env python3
"""
Analytics API Endpoints - Performance Tracking & Model Analytics

Provides endpoints for:
1. Model performance analytics
2. Prediction accuracy tracking
3. Best model identification
4. Performance trends
5. Correlation reports
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from services.result_correlation_service import result_correlation_service
from services.performance_analytics_service import performance_analytics_service
from scripts.daily_result_correlation import DailyResultCorrelation

# Create router
router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Initialize services
daily_correlation = DailyResultCorrelation()

@router.get("/dashboard")
def get_performance_dashboard(
    days: int = Query(30, description="Number of days to analyze", ge=1, le=365)
):
    """Get comprehensive performance dashboard."""
    try:
        dashboard = performance_analytics_service.get_comprehensive_dashboard(days)

        if dashboard.get('status') != 'success':
            raise HTTPException(status_code=404, detail=dashboard.get('error', 'No data available'))

        return JSONResponse(content=dashboard)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating dashboard: {str(e)}")

@router.get("/model-performance")
def get_model_performance(
    days: int = Query(30, description="Number of days to analyze", ge=1, le=365)
):
    """Get detailed model performance analytics."""
    try:
        analytics = result_correlation_service.get_model_performance_analytics(days)

        if analytics.get('status') != 'success':
            raise HTTPException(status_code=404, detail=analytics.get('error', 'No performance data available'))

        return JSONResponse(content=analytics)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting model performance: {str(e)}")

@router.get("/best-models")
def get_best_models(
    days: int = Query(30, description="Number of days to analyze", ge=1, le=365),
    limit: int = Query(10, description="Number of top models to return", ge=1, le=50)
):
    """Get best performing models over time."""
    try:
        best_models = result_correlation_service.get_best_models_over_time(days)

        if best_models.get('status') != 'success':
            raise HTTPException(status_code=404, detail=best_models.get('error', 'No model data available'))

        # Limit results
        weighted_rankings = best_models.get('weighted_rankings', [])[:limit]
        best_models['weighted_rankings'] = weighted_rankings

        return JSONResponse(content=best_models)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting best models: {str(e)}")

@router.get("/trends")
def get_performance_trends(
    days: int = Query(30, description="Number of days to analyze", ge=7, le=365)
):
    """Get performance trends over time."""
    try:
        dashboard = performance_analytics_service.get_comprehensive_dashboard(days)

        if dashboard.get('status') != 'success':
            raise HTTPException(status_code=404, detail="No trend data available")

        trends = dashboard.get('trends', {})

        if trends.get('status') != 'success':
            raise HTTPException(status_code=404, detail="No trend data available")

        return JSONResponse(content=trends)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting trends: {str(e)}")

@router.get("/category-performance")
def get_category_performance(
    days: int = Query(30, description="Number of days to analyze", ge=1, le=365)
):
    """Get performance by prediction category (2_odds, 5_odds, etc.)."""
    try:
        dashboard = performance_analytics_service.get_comprehensive_dashboard(days)

        if dashboard.get('status') != 'success':
            raise HTTPException(status_code=404, detail="No category data available")
        
        category_performance = dashboard.get('category_performance', {})
        
        return JSONResponse(content=category_performance)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting category performance: {str(e)}")

@router.get("/league-performance")
def get_league_performance(
    days: int = Query(30, description="Number of days to analyze", ge=1, le=365)
):
    """Get performance by league."""
    try:
        dashboard = performance_analytics_service.get_comprehensive_dashboard(days)
        
        if dashboard.get('status') != 'success':
            raise HTTPException(status_code=404, detail="No league data available")
        
        league_performance = dashboard.get('league_performance', {})
        
        return JSONResponse(content=league_performance)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting league performance: {str(e)}")

@router.post("/correlate-results")
def correlate_results(
    date: str = Query(..., description="Date to correlate (YYYY-MM-DD)")
):
    """Manually trigger result correlation for a specific date."""
    try:
        # Validate date format
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        result = result_correlation_service.fetch_and_correlate_results(date)
        
        return JSONResponse(content=result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error correlating results: {str(e)}")

@router.get("/daily-report")
def get_daily_report(
    date: str = Query(None, description="Date for report (YYYY-MM-DD). Defaults to yesterday")
):
    """Get daily correlation report."""
    try:
        if not date:
            # Default to yesterday
            yesterday = datetime.now() - timedelta(days=1)
            date = yesterday.strftime('%Y-%m-%d')
        
        # Validate date format
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        result = daily_correlation.run_daily_correlation(date)
        
        return JSONResponse(content=result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting daily report: {str(e)}")

@router.get("/weekly-summary")
def get_weekly_summary():
    """Get weekly performance summary."""
    try:
        summary = daily_correlation.run_weekly_summary()
        
        return JSONResponse(content=summary)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting weekly summary: {str(e)}")

@router.get("/model-comparison")
def compare_models(
    models: str = Query(..., description="Comma-separated list of model names to compare"),
    days: int = Query(30, description="Number of days to analyze", ge=1, le=365)
):
    """Compare specific models head-to-head."""
    try:
        model_list = [model.strip() for model in models.split(',')]
        
        if len(model_list) < 2:
            raise HTTPException(status_code=400, detail="At least 2 models required for comparison")
        
        comparison = performance_analytics_service.get_model_comparison(model_list, days)
        
        return JSONResponse(content=comparison)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing models: {str(e)}")

@router.get("/performance-prediction")
def predict_performance(
    days_ahead: int = Query(7, description="Number of days ahead to predict", ge=1, le=30)
):
    """Predict future performance based on trends."""
    try:
        prediction = performance_analytics_service.predict_future_performance(days_ahead)
        
        return JSONResponse(content=prediction)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error predicting performance: {str(e)}")

@router.get("/recommendations")
def get_recommendations(
    days: int = Query(30, description="Number of days to analyze", ge=1, le=365)
):
    """Get actionable recommendations based on performance data."""
    try:
        dashboard = performance_analytics_service.get_comprehensive_dashboard(days)
        
        if dashboard.get('status') != 'success':
            raise HTTPException(status_code=404, detail="No data available for recommendations")
        
        recommendations = dashboard.get('recommendations', {})
        
        return JSONResponse(content={
            "status": "success",
            "period_days": days,
            "recommendations": recommendations,
            "generated_at": datetime.now().isoformat()
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting recommendations: {str(e)}")

@router.get("/accuracy-history")
def get_accuracy_history(
    days: int = Query(30, description="Number of days to analyze", ge=7, le=365),
    model: str = Query(None, description="Specific model to analyze (optional)")
):
    """Get accuracy history over time."""
    try:
        dashboard = performance_analytics_service.get_comprehensive_dashboard(days)
        
        if dashboard.get('status') != 'success':
            raise HTTPException(status_code=404, detail="No accuracy data available")
        
        trends = dashboard.get('trends', {})
        
        if trends.get('status') != 'success':
            raise HTTPException(status_code=404, detail="No trend data available")
        
        daily_data = trends.get('daily_data', {})
        
        result = {
            "status": "success",
            "period_days": days,
            "model_filter": model,
            "daily_accuracy": daily_data,
            "trend_analysis": trends.get('trend_analysis', {}),
            "generated_at": datetime.now().isoformat()
        }
        
        return JSONResponse(content=result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting accuracy history: {str(e)}")

@router.get("/alerts")
def get_performance_alerts(
    days: int = Query(7, description="Number of days to analyze", ge=1, le=30)
):
    """Get current performance alerts."""
    try:
        # Get recent analytics
        analytics = performance_analytics_service.get_comprehensive_dashboard(days)
        
        if analytics.get('status') != 'success':
            return JSONResponse(content={"status": "no_data", "alerts": []})
        
        # Check for alerts
        alerts = daily_correlation._check_performance_alerts(analytics)
        
        return JSONResponse(content={
            "status": "success",
            "period_days": days,
            "alerts": alerts,
            "alert_count": len(alerts),
            "generated_at": datetime.now().isoformat()
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting alerts: {str(e)}")

@router.get("/health")
def get_analytics_health():
    """Get health status of analytics system."""
    try:
        # Check if services are working
        health_status = {
            "status": "healthy",
            "services": {
                "result_correlation": "healthy",
                "performance_analytics": "healthy",
                "daily_correlation": "healthy"
            },
            "last_check": datetime.now().isoformat()
        }
        
        # Test basic functionality
        try:
            # Test correlation service
            test_analytics = result_correlation_service.get_model_performance_analytics(1)
            if test_analytics.get('status') == 'error':
                health_status["services"]["result_correlation"] = "error"
                health_status["status"] = "degraded"
        except:
            health_status["services"]["result_correlation"] = "error"
            health_status["status"] = "degraded"
        
        try:
            # Test analytics service
            test_dashboard = performance_analytics_service.get_comprehensive_dashboard(1)
            if test_dashboard.get('status') == 'error':
                health_status["services"]["performance_analytics"] = "error"
                health_status["status"] = "degraded"
        except:
            health_status["services"]["performance_analytics"] = "error"
            health_status["status"] = "degraded"
        
        return JSONResponse(content=health_status)
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "unhealthy",
                "error": str(e),
                "last_check": datetime.now().isoformat()
            }
        )
