"""
Accumulator API Endpoints
Provides accumulator bets that combine multiple games to reach target odds.
"""

import logging
import json
from datetime import datetime, date
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from services.daily_predictions_service import DailyPrediction, DailyPredictionSummary
from services.accumulator_builder import AccumulatorBuilder, format_accumulator_for_display

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/today")
def get_todays_accumulators(db: Session = Depends(get_db)):
    """
    Get today's accumulator bets from database.
    
    Returns:
        Accumulator combinations that reach target odds (2x, 5x, 10x, rollover)
    """
    try:
        today = datetime.now().date()
        
        # Get summary to check if predictions exist
        summary = db.query(DailyPredictionSummary).filter(
            DailyPredictionSummary.prediction_date == today
        ).first()
        
        if not summary or summary.generation_status != "completed":
            return {
                "status": "no_accumulators",
                "date": today.isoformat(),
                "message": "No accumulators available. Generate predictions first.",
                "accumulators": {}
            }
        
        # Get all predictions for today
        predictions = db.query(DailyPrediction).filter(
            DailyPrediction.prediction_date == today
        ).all()
        
        if not predictions:
            return {
                "status": "no_predictions",
                "date": today.isoformat(),
                "message": "No predictions found for today",
                "accumulators": {}
            }
        
        # Extract accumulator data from first prediction (they all have the same accumulator info)
        first_prediction = predictions[0]
        accumulators = {}
        
        # Get accumulator data from betting categories
        categories = ['2_odds', '5_odds', '10_odds', 'over_1_5', 'rollover']
        for category in categories:
            category_data = getattr(first_prediction, f'betting_{category}', '{}')
            if category_data:
                try:
                    accumulator_data = json.loads(category_data)
                    if accumulator_data.get('selected', False):
                        # Format accumulator for frontend
                        accumulators[category] = {
                            'selected': True,
                            'category': category,
                            'total_odds': accumulator_data.get('total_odds', 0),
                            'num_games': accumulator_data.get('num_games', 0),
                            'average_confidence': accumulator_data.get('average_confidence', 0),
                            'risk_level': accumulator_data.get('risk_level', 'UNKNOWN'),
                            'games': accumulator_data.get('games', []),
                            'recommendation': accumulator_data.get('recommendation', 'UNKNOWN')
                        }
                    else:
                        accumulators[category] = {
                            'selected': False,
                            'category': category,
                            'reason': accumulator_data.get('reason', 'Not available'),
                            'recommendation': 'EXCLUDE'
                        }
                except json.JSONDecodeError:
                    accumulators[category] = {
                        'selected': False,
                        'category': category,
                        'reason': 'Data parsing error',
                        'recommendation': 'EXCLUDE'
                    }
        
        # Generate summary
        selected_count = sum(1 for acc in accumulators.values() if acc.get('selected', False))
        total_games = sum(acc.get('num_games', 0) for acc in accumulators.values() if acc.get('selected', False))
        
        return {
            "status": "success",
            "date": today.isoformat(),
            "source": "database",
            "accumulators": accumulators,
            "summary": {
                "total_categories": len(categories),
                "categories_with_accumulators": selected_count,
                "total_games_in_accumulators": total_games,
                "success_rate": f"{(selected_count/len(categories)*100):.1f}%"
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting today's accumulators: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/2-odds")
def get_2_odds_accumulator(db: Session = Depends(get_db)):
    """
    Get 2-odds accumulator (target: ~2x total odds).

    Returns:
        2-odds accumulator details with games and total odds
    """
    return _get_category_accumulator("2_odds", db)

@router.get("/5-odds")
def get_5_odds_accumulator(db: Session = Depends(get_db)):
    """
    Get 5-odds accumulator (target: ~5x total odds).

    Returns:
        5-odds accumulator details with games and total odds
    """
    return _get_category_accumulator("5_odds", db)

@router.get("/10-odds")
def get_10_odds_accumulator(db: Session = Depends(get_db)):
    """
    Get 10-odds accumulator (target: ~10x total odds).

    Returns:
        10-odds accumulator details with games and total odds
    """
    return _get_category_accumulator("10_odds", db)

@router.get("/rollover")
def get_rollover_accumulator(db: Session = Depends(get_db)):
    """
    Get rollover accumulator (conservative accumulator for next day).

    Returns:
        Rollover accumulator details with games and total odds
    """
    return _get_category_accumulator("rollover", db)

def _get_category_accumulator(category: str, db: Session):
    """
    Internal function to get specific accumulator category details.

    Args:
        category: Accumulator category (2_odds, 5_odds, 10_odds, rollover)
        db: Database session

    Returns:
        Detailed accumulator information for the category
    """
    try:
        today = datetime.now().date()

        # Get predictions
        predictions = db.query(DailyPrediction).filter(
            DailyPrediction.prediction_date == today
        ).all()

        if not predictions:
            return {
                "status": "no_predictions",
                "category": category,
                "date": today.isoformat(),
                "message": "No predictions found for today",
                "accumulator": None
            }

        # Get accumulator data for the category
        first_prediction = predictions[0]
        category_data = getattr(first_prediction, f'betting_{category}', '{}')

        if not category_data:
            return {
                "status": "no_data",
                "category": category,
                "date": today.isoformat(),
                "message": f"No accumulator data found for {category}",
                "accumulator": None
            }

        try:
            accumulator_data = json.loads(category_data)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "category": category,
                "message": "Error parsing accumulator data",
                "accumulator": None
            }

        if not accumulator_data.get('selected', False):
            return {
                "status": "not_selected",
                "category": category,
                "date": today.isoformat(),
                "reason": accumulator_data.get('reason', 'Not available'),
                "recommendation": "EXCLUDE",
                "accumulator": None
            }

        # Format detailed response
        return {
            "status": "success",
            "category": category,
            "date": today.isoformat(),
            "source": "database",
            "accumulator": {
                'selected': True,
                'total_odds': accumulator_data.get('total_odds', 0),
                'num_games': accumulator_data.get('num_games', 0),
                'average_confidence': accumulator_data.get('average_confidence', 0),
                'risk_level': accumulator_data.get('risk_level', 'UNKNOWN'),
                'target_range': accumulator_data.get('target_range', 'Unknown'),
                'games': accumulator_data.get('games', []),
                'recommendation': accumulator_data.get('recommendation', 'UNKNOWN')
            }
        }

    except Exception as e:
        logger.error(f"Error getting category accumulator: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/summary")
def get_accumulator_summary(db: Session = Depends(get_db)):
    """
    Get summary of all accumulator categories.
    
    Returns:
        Summary statistics for all accumulator categories
    """
    try:
        today = datetime.now().date()
        
        # Get summary
        summary = db.query(DailyPredictionSummary).filter(
            DailyPredictionSummary.prediction_date == today
        ).first()
        
        if not summary:
            return {
                "status": "no_data",
                "date": today.isoformat(),
                "message": "No accumulator data available"
            }
        
        return {
            "status": "success",
            "date": today.isoformat(),
            "summary": {
                "prediction_date": summary.prediction_date.isoformat(),
                "total_fixtures_analyzed": summary.total_fixtures,
                "upcoming_fixtures": summary.upcoming_fixtures,
                "predictions_generated": summary.predictions_generated,
                "accumulator_categories": {
                    "2_odds": summary.betting_2_odds_count > 0,
                    "5_odds": summary.betting_5_odds_count > 0,
                    "10_odds": summary.betting_10_odds_count > 0,
                    "over_1_5": summary.betting_over_1_5_count > 0,
                    "rollover": summary.betting_rollover_count > 0
                },
                "generation_status": summary.generation_status,
                "generation_time": summary.generation_time.isoformat() if summary.generation_time else None
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting accumulator summary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.post("/rebuild")
def rebuild_accumulators(
    target_date: str = Query(None, description="Date in YYYY-MM-DD format (default: today)"),
    db: Session = Depends(get_db)
):
    """
    Rebuild accumulators for a specific date (admin function).
    
    Args:
        target_date: Date to rebuild accumulators for
        
    Returns:
        Rebuild status
    """
    try:
        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        prediction_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        
        # Get existing predictions
        predictions = db.query(DailyPrediction).filter(
            DailyPrediction.prediction_date == prediction_date
        ).all()
        
        if not predictions:
            raise HTTPException(status_code=404, detail="No predictions found for this date")
        
        # Convert to format expected by accumulator builder
        prediction_data = []
        for pred in predictions:
            prediction_result = {
                'fixture_info': {
                    'fixture_id': pred.fixture_id,
                    'home_team': pred.home_team,
                    'away_team': pred.away_team,
                    'league': pred.league_name,
                    'date': pred.fixture_date.isoformat(),
                    'status': pred.fixture_status
                },
                'ml_predictions': json.loads(pred.ml_predictions),
                'model_summary': {
                    'total_predictions': pred.total_models_used
                }
            }
            prediction_data.append(prediction_result)
        
        # Rebuild accumulators
        accumulator_builder = AccumulatorBuilder()
        accumulator_result = accumulator_builder.build_accumulators(prediction_data)
        accumulators = accumulator_result.get('accumulators', {})
        
        # Update database with new accumulator data
        for pred in predictions:
            pred.betting_2_odds = json.dumps(accumulators.get('2_odds', {}))
            pred.betting_5_odds = json.dumps(accumulators.get('5_odds', {}))
            pred.betting_10_odds = json.dumps(accumulators.get('10_odds', {}))
            pred.betting_over_1_5 = json.dumps(accumulators.get('over_1_5', {}))
            pred.betting_rollover = json.dumps(accumulators.get('rollover', {}))
            pred.updated_at = datetime.utcnow()
        
        db.commit()
        
        return {
            "status": "success",
            "date": target_date,
            "message": "Accumulators rebuilt successfully",
            "result": accumulator_result
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rebuilding accumulators: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
