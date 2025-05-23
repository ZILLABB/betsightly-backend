"""
API endpoints for predictions.
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session

from database import get_db
from prediction import Prediction
from services.prediction_service_improved import PredictionService
from services.advanced_prediction_service import AdvancedPredictionService

router = APIRouter()

def _format_rollover_days(rollover_combinations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Format rollover combinations by day.

    Args:
        rollover_combinations: List of rollover combinations

    Returns:
        List of rollover days with predictions
    """
    # Group by day
    days_dict = {}

    for combo in rollover_combinations:
        day = combo.get("day", 1)
        if day not in days_dict:
            days_dict[day] = []
        days_dict[day].append(combo)

    # Format days
    days = []

    for day_num in range(1, 11):  # 10 days
        if day_num in days_dict:
            # Use the best combination for this day
            best_combo = days_dict[day_num][0]
            days.append({
                "day": day_num,
                "predictions": best_combo.get("predictions", []),
                "combined_odds": best_combo.get("combined_odds", 3.0),
                "combined_confidence": best_combo.get("combined_confidence", 0)
            })
        else:
            # Empty day
            days.append({
                "day": day_num,
                "predictions": [],
                "combined_odds": 0,
                "combined_confidence": 0
            })

    return days

@router.get("/categories/", include_in_schema=True)
@router.get("/categories", include_in_schema=False)
def get_prediction_categories(
    db: Session = Depends(get_db),
    date: Optional[date] = None
):
    """
    Get predictions organized by categories (2_odds, 5_odds, 10_odds, rollover).
    This endpoint matches the frontend expectation.
    """
    try:
        prediction_service = PredictionService(db)

        # Get predictions by date
        if date:
            predictions = prediction_service.get_predictions_by_date(
                date=datetime.combine(date, datetime.min.time())
            )
        else:
            predictions = prediction_service.get_predictions_by_date(
                date=datetime.now()
            )

        # Categorize predictions
        categorized_predictions = prediction_service.categorize_predictions(predictions)

        # Format the response to match frontend expectations
        result = {
            "2_odds": [],
            "5_odds": [],
            "10_odds": [],
            "rollover": []
        }

        # Process each category
        for category, category_predictions in categorized_predictions.items():
            if category_predictions:
                # Sort by confidence (highest first)
                sorted_predictions = sorted(
                    category_predictions,
                    key=lambda p: p.confidence or 0,
                    reverse=True
                )

                # Convert to dictionaries and add to result
                for pred in sorted_predictions[:10]:  # Limit to top 10 per category
                    pred_dict = pred.to_dict()
                    pred_dict["category"] = category
                    result[category].append(pred_dict)

        return result

    except Exception as e:
        # Return empty categories if there's an error
        return {
            "2_odds": [],
            "5_odds": [],
            "10_odds": [],
            "rollover": []
        }

@router.get("/", include_in_schema=True)
@router.get("", include_in_schema=False)
def get_predictions(
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    categorized: bool = True,
    best_only: bool = Query(False, description="Return only the best predictions for each category")
):
    """
    Get predictions.

    Args:
        date: Date to get predictions for (default: today)
        categorized: Whether to categorize predictions by odds (default: True)
        best_only: Return only the best predictions for each category (default: False)
    """
    prediction_service = PredictionService(db)

    if date:
        # Get predictions by date
        predictions = prediction_service.get_predictions_by_date(
            date=datetime.combine(date, datetime.min.time())
        )
    else:
        # Get today's predictions
        predictions = prediction_service.get_predictions_by_date(
            date=datetime.now()
        )

    if categorized:
        # Categorize predictions
        categorized_predictions = prediction_service.categorize_predictions(predictions)

        # Create combinations for each category
        result = {
            "categorized": {},
            "predictions": [p.to_dict() for p in predictions]
        }

        # 2 odds combinations (target: 2.0)
        if categorized_predictions["2_odds"]:
            # Sort by confidence (highest first)
            sorted_2_odds = sorted(
                categorized_predictions["2_odds"],
                key=lambda p: p.confidence or 0,
                reverse=True
            )

            if best_only:
                # Use only the top 3 predictions
                best_2_odds = sorted_2_odds[:3]

                # Create a single combination with the best predictions
                combo = {
                    "id": f"2_odds_best_{uuid.uuid4()}",
                    "category": "2_odds",
                    "target_odds": 2.0,
                    "description": "Safe Bets (2 Odds)",
                    "predictions": [p.to_dict() for p in best_2_odds],
                    "combined_odds": 2.0,
                    "combined_confidence": sum(p.confidence or 0 for p in best_2_odds) / len(best_2_odds) if best_2_odds else 0
                }

                result["categorized"]["2_odds"] = [combo]
            else:
                # Create regular combinations
                combinations_2_odds = prediction_service.create_prediction_combinations(
                    categorized_predictions["2_odds"], 2.0
                )

                # Add category information to each combination
                for combo in combinations_2_odds:
                    combo["category"] = "2_odds"
                    combo["target_odds"] = 2.0
                    combo["description"] = "Safe Bets (2 Odds)"

                result["categorized"]["2_odds"] = combinations_2_odds

        # 5 odds combinations (target: 5.0)
        if categorized_predictions["5_odds"]:
            # Sort by confidence (highest first)
            sorted_5_odds = sorted(
                categorized_predictions["5_odds"],
                key=lambda p: p.confidence or 0,
                reverse=True
            )

            if best_only:
                # Use only the top 3 predictions
                best_5_odds = sorted_5_odds[:3]

                # Create a single combination with the best predictions
                combo = {
                    "id": f"5_odds_best_{uuid.uuid4()}",
                    "category": "5_odds",
                    "target_odds": 5.0,
                    "description": "Balanced Risk (5 Odds)",
                    "predictions": [p.to_dict() for p in best_5_odds],
                    "combined_odds": 5.0,
                    "combined_confidence": sum(p.confidence or 0 for p in best_5_odds) / len(best_5_odds) if best_5_odds else 0
                }

                result["categorized"]["5_odds"] = [combo]
            else:
                # Create regular combinations
                combinations_5_odds = prediction_service.create_prediction_combinations(
                    categorized_predictions["5_odds"], 5.0
                )

                # Add category information to each combination
                for combo in combinations_5_odds:
                    combo["category"] = "5_odds"
                    combo["target_odds"] = 5.0
                    combo["description"] = "Balanced Risk (5 Odds)"

                result["categorized"]["5_odds"] = combinations_5_odds

        # 10 odds combinations (target: 10.0)
        if categorized_predictions["10_odds"]:
            # Sort by confidence (highest first)
            sorted_10_odds = sorted(
                categorized_predictions["10_odds"],
                key=lambda p: p.confidence or 0,
                reverse=True
            )

            if best_only:
                # Use only the top 3 predictions
                best_10_odds = sorted_10_odds[:3]

                # Create a single combination with the best predictions
                combo = {
                    "id": f"10_odds_best_{uuid.uuid4()}",
                    "category": "10_odds",
                    "target_odds": 10.0,
                    "description": "High Reward (10 Odds)",
                    "predictions": [p.to_dict() for p in best_10_odds],
                    "combined_odds": 10.0,
                    "combined_confidence": sum(p.confidence or 0 for p in best_10_odds) / len(best_10_odds) if best_10_odds else 0
                }

                result["categorized"]["10_odds"] = [combo]
            else:
                # Create regular combinations
                combinations_10_odds = prediction_service.create_prediction_combinations(
                    categorized_predictions["10_odds"], 10.0
                )

                # Add category information to each combination
                for combo in combinations_10_odds:
                    combo["category"] = "10_odds"
                    combo["target_odds"] = 10.0
                    combo["description"] = "High Reward (10 Odds)"

                result["categorized"]["10_odds"] = combinations_10_odds

        # Rollover predictions (3.0 odds per day)
        if categorized_predictions["rollover"]:
            # Group by rollover day
            rollover_by_day = {}
            for prediction in categorized_predictions["rollover"]:
                day = prediction.rollover_day or 1
                if day not in rollover_by_day:
                    rollover_by_day[day] = []
                rollover_by_day[day].append(prediction)

            # Create combinations for each day
            rollover_combinations = []
            for day, day_predictions in rollover_by_day.items():
                # Sort by confidence (highest first)
                sorted_day_predictions = sorted(
                    day_predictions,
                    key=lambda p: p.confidence or 0,
                    reverse=True
                )

                if best_only and sorted_day_predictions:
                    # Use only the top prediction for this day
                    best_prediction = sorted_day_predictions[0]

                    # Create a combination with the best prediction
                    combo = {
                        "id": f"rollover_day_{day}_best_{uuid.uuid4()}",
                        "day": day,
                        "category": "rollover",
                        "target_odds": 3.0,
                        "description": f"Rollover Day {day}",
                        "predictions": [best_prediction.to_dict()],
                        "combined_odds": best_prediction.odds or 3.0,
                        "combined_confidence": best_prediction.confidence or 0.7
                    }

                    rollover_combinations.append(combo)
                else:
                    # Create regular combinations
                    day_combinations = prediction_service.create_prediction_combinations(
                        day_predictions, 3.0
                    )

                    if day_combinations:
                        best_combo = day_combinations[0]
                        best_combo["day"] = day
                        best_combo["category"] = "rollover"
                        best_combo["target_odds"] = 3.0
                        best_combo["description"] = f"Rollover Day {day}"
                        rollover_combinations.append(best_combo)

            result["categorized"]["rollover"] = rollover_combinations

        return result

    # Return uncategorized predictions
    return [prediction.to_dict() for prediction in predictions]

@router.get("/category/{category}/", include_in_schema=True)
@router.get("/category/{category}", include_in_schema=False)
def get_predictions_by_category(
    category: str,
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    limit: int = Query(10, description="Maximum number of combinations to return"),
    best_only: bool = Query(True, description="Return only the best predictions for this category")
):
    """
    Get predictions by category.

    Args:
        category: Category to get predictions for (2_odds, 5_odds, 10_odds, rollover)
        date: Date to get predictions for (default: today)
        limit: Maximum number of combinations to return (default: 10)
        best_only: Return only the best predictions for this category (default: True)
    """
    prediction_service = PredictionService(db)

    # Validate category
    valid_categories = ["2_odds", "5_odds", "10_odds", "rollover"]
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
        )

    # Get target date
    target_date = datetime.combine(date, datetime.min.time()) if date else datetime.now()

    # Try to get cached prediction combinations from database first
    combinations = prediction_service.get_prediction_combinations_by_category(
        category=category,
        date=target_date,
        limit=limit
    )

    # If no combinations found in database, generate them
    if not combinations:
        # Get predictions by date
        predictions = prediction_service.get_predictions_by_date(date=target_date)

        # Categorize predictions
        categorized_predictions = prediction_service.categorize_predictions(predictions)

        # Get predictions for the requested category
        category_predictions = categorized_predictions.get(category, [])

        if best_only:
            # Sort by confidence (highest first)
            sorted_predictions = sorted(
                category_predictions,
                key=lambda p: p.confidence or 0,
                reverse=True
            )

            # Get the best predictions
            best_predictions = sorted_predictions[:limit]

            # Convert to dictionaries
            result = []
            for pred in best_predictions:
                pred_dict = pred.to_dict()

                # Add category information
                pred_dict["category"] = category

                # Add a description based on the prediction type
                if pred.prediction_type == "btts":
                    pred_dict["description"] = f"Both Teams to Score: {pred.btts_pred}"
                elif pred.prediction_type == "over_2_5":
                    pred_dict["description"] = "Over 2.5 Goals"
                elif pred.prediction_type == "under_2_5":
                    pred_dict["description"] = "Under 2.5 Goals"
                elif pred.prediction_type == "home_win":
                    pred_dict["description"] = f"{pred_dict.get('homeTeam', 'Home Team')} to Win"
                elif pred.prediction_type == "draw":
                    pred_dict["description"] = "Match to End in a Draw"
                elif pred.prediction_type == "away_win":
                    pred_dict["description"] = f"{pred_dict.get('awayTeam', 'Away Team')} to Win"

                result.append(pred_dict)

            return result
        else:
            # Create combinations
            target_odds = {
                "2_odds": 2.0,
                "5_odds": 5.0,
                "10_odds": 10.0,
                "rollover": 3.0
            }

            combinations = prediction_service.create_prediction_combinations(
                category_predictions, target_odds[category]
            )

            # Limit the number of combinations
            combinations = combinations[:limit]

            # Add category information to each combination
            for combo in combinations:
                combo["category"] = category
                combo["target_odds"] = target_odds[category]

                # Add a description based on the category
                if category == "2_odds":
                    combo["description"] = "Safe Bets (2 Odds)"
                elif category == "5_odds":
                    combo["description"] = "Balanced Risk (5 Odds)"
                elif category == "10_odds":
                    combo["description"] = "High Reward (10 Odds)"
                elif category == "rollover":
                    combo["description"] = f"Rollover Day {combo.get('day', 1)}"

            # Store combinations in database for future use
            prediction_service.save_prediction_combinations(combinations, target_date)

    return combinations

@router.get("/best/{category}/", include_in_schema=True)
@router.get("/best/{category}", include_in_schema=False)
def get_best_predictions_by_category(
    category: str,
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    limit: int = Query(3, description="Maximum number of predictions to return")
):
    """
    Get the best predictions for a specific category.

    Args:
        category: Category to get predictions for (2_odds, 5_odds, 10_odds, rollover)
        date: Date to get predictions for (default: today)
        limit: Maximum number of predictions to return (default: 3)
    """
    prediction_service = PredictionService(db)

    # Validate category
    valid_categories = ["2_odds", "5_odds", "10_odds", "rollover"]
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
        )

    # Get predictions by date
    if date:
        predictions = prediction_service.get_predictions_by_date(
            date=datetime.combine(date, datetime.min.time())
        )
    else:
        predictions = prediction_service.get_predictions_by_date(
            date=datetime.now()
        )

    # Categorize predictions
    categorized_predictions = prediction_service.categorize_predictions(predictions)

    # Get predictions for the requested category
    category_predictions = categorized_predictions.get(category, [])

    # Sort by confidence (highest first)
    sorted_predictions = sorted(
        category_predictions,
        key=lambda p: p.confidence or 0,
        reverse=True
    )

    # Get the best predictions
    best_predictions = sorted_predictions[:limit]

    # Convert to dictionaries
    result = []
    for pred in best_predictions:
        pred_dict = pred.to_dict()

        # Add category information
        pred_dict["category"] = category

        # Add a description based on the prediction type
        if pred.prediction_type == "btts":
            pred_dict["description"] = f"Both Teams to Score: {pred.btts_pred}"
        elif pred.prediction_type == "over_2_5":
            pred_dict["description"] = "Over 2.5 Goals"
        elif pred.prediction_type == "under_2_5":
            pred_dict["description"] = "Under 2.5 Goals"
        elif pred.prediction_type == "home_win":
            pred_dict["description"] = f"{pred_dict.get('homeTeam', 'Home Team')} to Win"
        elif pred.prediction_type == "draw":
            pred_dict["description"] = "Match to End in a Draw"
        elif pred.prediction_type == "away_win":
            pred_dict["description"] = f"{pred_dict.get('awayTeam', 'Away Team')} to Win"

        result.append(pred_dict)

    return result

@router.get("/best/", include_in_schema=True)
@router.get("/best", include_in_schema=False)
def get_all_best_predictions(
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    limit_per_category: int = Query(3, description="Maximum number of predictions per category")
):
    """
    Get the best predictions for all categories.

    Args:
        date: Date to get predictions for (default: today)
        limit_per_category: Maximum number of predictions per category (default: 3)
    """
    try:
        prediction_service = PredictionService(db)

        # Get predictions by date
        if date:
            predictions = prediction_service.get_predictions_by_date(
                date=datetime.combine(date, datetime.min.time())
            )
        else:
            predictions = prediction_service.get_predictions_by_date(
                date=datetime.now()
            )

        # Categorize predictions
        categorized_predictions = prediction_service.categorize_predictions(predictions)

        # Get best predictions for each category
        result = {}

        for category in ["2_odds", "5_odds", "10_odds", "rollover"]:
            category_predictions = categorized_predictions.get(category, [])

            # Sort by confidence (highest first)
            sorted_predictions = sorted(
                category_predictions,
                key=lambda p: p.confidence or 0,
                reverse=True
            )

            # Get the best predictions
            best_predictions = sorted_predictions[:limit_per_category]

            # Convert to dictionaries
            category_result = []
            for pred in best_predictions:
                try:
                    pred_dict = pred.to_dict()

                    # Add category information
                    pred_dict["category"] = category

                    # Add a description based on the prediction type
                    if pred.prediction_type == "btts":
                        pred_dict["description"] = f"Both Teams to Score: {pred.btts_pred}"
                    elif pred.prediction_type == "over_2_5":
                        pred_dict["description"] = "Over 2.5 Goals"
                    elif pred.prediction_type == "under_2_5":
                        pred_dict["description"] = "Under 2.5 Goals"
                    elif pred.prediction_type == "home_win":
                        pred_dict["description"] = f"{pred_dict.get('homeTeam', 'Home Team')} to Win"
                    elif pred.prediction_type == "draw":
                        pred_dict["description"] = "Match to End in a Draw"
                    elif pred.prediction_type == "away_win":
                        pred_dict["description"] = f"{pred_dict.get('awayTeam', 'Away Team')} to Win"
                    else:
                        pred_dict["description"] = "Football Prediction"

                    category_result.append(pred_dict)
                except Exception as e:
                    # Skip this prediction if there's an error converting it
                    print(f"Error converting prediction {pred.id}: {e}")
                    continue

            result[category] = category_result

        return result

    except Exception as e:
        # Return empty result if there's an error
        print(f"Error in get_all_best_predictions: {e}")
        return {
            "2_odds": [],
            "5_odds": [],
            "10_odds": [],
            "rollover": []
        }

@router.get("/categories")
def get_all_prediction_categories(
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    limit_per_category: int = Query(5, description="Maximum number of combinations per category")
):
    """
    Get all prediction categories for a specific date.

    Returns a structured response with all categories and their predictions,
    optimized for frontend rendering.

    Args:
        date: Date to get predictions for (default: today)
        limit_per_category: Maximum number of combinations per category (default: 5)
    """
    prediction_service = PredictionService(db)

    # Get target date
    target_date = datetime.combine(date, datetime.min.time()) if date else datetime.now()

    # Get categories
    categories = {}

    for category_name in ["2_odds", "5_odds", "10_odds", "rollover"]:
        # Try to get cached prediction combinations from database first
        combinations = prediction_service.get_prediction_combinations_by_category(
            category=category_name,
            date=target_date,
            limit=limit_per_category
        )

        # If no combinations found in database, generate them
        if not combinations:
            # Get predictions by date
            predictions = prediction_service.get_predictions_by_date(date=target_date)

            # Categorize predictions
            categorized_predictions = prediction_service.categorize_predictions(predictions)

            # Get predictions for the requested category
            category_predictions = categorized_predictions.get(category_name, [])

            # Create combinations
            target_odds = {
                "2_odds": 2.0,
                "5_odds": 5.0,
                "10_odds": 10.0,
                "rollover": 3.0
            }

            combinations = prediction_service.create_prediction_combinations(
                category_predictions, target_odds[category_name]
            )

            # Limit the number of combinations
            combinations = combinations[:limit_per_category]

            # Add category information to each combination
            for combo in combinations:
                combo["category"] = category_name
                combo["target_odds"] = target_odds[category_name]

                # Add a description based on the category
                if category_name == "2_odds":
                    combo["description"] = "Safe Bets (2 Odds)"
                elif category_name == "5_odds":
                    combo["description"] = "Balanced Risk (5 Odds)"
                elif category_name == "10_odds":
                    combo["description"] = "High Reward (10 Odds)"
                elif category_name == "rollover":
                    combo["description"] = f"Rollover Day {combo.get('day', 1)}"

            # Store combinations in database for future use
            prediction_service.save_prediction_combinations(combinations, target_date)

        categories[category_name] = combinations

    # Format response for frontend
    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "categories": {
            "safe_bets": {
                "name": "Safe Bets",
                "description": "Lower odds, higher confidence predictions",
                "target_odds": 2.0,
                "predictions": categories.get("2_odds", [])
            },
            "balanced_bets": {
                "name": "Balanced Risk",
                "description": "Medium odds, balanced risk-reward",
                "target_odds": 5.0,
                "predictions": categories.get("5_odds", [])
            },
            "high_reward": {
                "name": "High Reward",
                "description": "Higher odds, higher potential returns",
                "target_odds": 10.0,
                "predictions": categories.get("10_odds", [])
            },
            "rollover": {
                "name": "10-Day Rollover",
                "description": "Daily predictions for a 10-day rollover strategy",
                "target_odds": 3.0,
                "days": _format_rollover_days(categories.get("rollover", []))
            }
        }
    }

@router.get("/{prediction_id}")
def get_prediction(
    prediction_id: int,
    db: Session = Depends(get_db)
):
    """Get prediction by ID."""
    prediction_service = PredictionService(db)
    prediction = prediction_service.get_prediction_by_id(prediction_id)

    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return prediction

@router.get("/advanced")
def get_advanced_predictions(
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    force_update: bool = Query(False, description="Force update from API instead of using cache")
):
    """
    Get predictions using advanced ML models.

    This endpoint uses more sophisticated ML models (XGBoost, LightGBM, Neural Networks, LSTM)
    instead of the basic ensemble models for more accurate predictions with better confidence calibration.

    Args:
        date: Date to get predictions for (default: today)
        force_update: Whether to force an update from the API (default: False)
    """
    # Initialize the advanced prediction service
    advanced_prediction_service = AdvancedPredictionService(db)

    # Get predictions for the specified date or today
    if date:
        date_str = date.strftime("%Y-%m-%d")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # Get predictions using advanced ML models
    predictions = advanced_prediction_service.get_predictions_for_date(
        date=date_str,
        force_update=force_update
    )

    return predictions

@router.get("/advanced/best/{category}")
def get_advanced_best_predictions_by_category(
    category: str,
    db: Session = Depends(get_db),
    date: Optional[date] = None,
    limit: int = Query(3, description="Maximum number of predictions to return")
):
    """
    Get the best predictions for a specific category using advanced ML models.

    Args:
        category: Category to get predictions for (2_odds, 5_odds, 10_odds)
        date: Date to get predictions for (default: today)
        limit: Maximum number of predictions to return (default: 3)
    """
    # Initialize the advanced prediction service
    advanced_prediction_service = AdvancedPredictionService(db)

    # Validate category
    valid_categories = ["2_odds", "5_odds", "10_odds"]
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
        )

    # Get predictions for the specified date or today
    if date:
        date_str = date.strftime("%Y-%m-%d")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # Get predictions using advanced ML models
    predictions = advanced_prediction_service.get_predictions_for_date(date=date_str)

    # Extract the requested category
    category_predictions = predictions.get("categories", {}).get(category, [])

    # Limit the number of predictions
    limited_predictions = category_predictions[:limit]

    return limited_predictions
