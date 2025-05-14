"""
Generate Predictions

This script generates predictions using our ML model and compares them with bookmaker odds.
It identifies value bets where our model predicts differently than the bookmakers.
"""

import os
import sys
import json
import http.client
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add the parent directory to the path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Try to import our ML model
try:
    from app.ml.ensemble_model import ensemble_model
    from app.ml.feature_engineering import feature_engineer
    ML_MODEL_AVAILABLE = True
except ImportError:
    print("Warning: ML model not available. Using simple heuristic model instead.")
    ML_MODEL_AVAILABLE = False

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PREDICTIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "predictions")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PREDICTIONS_DIR, exist_ok=True)

def fetch_fixtures(date=None):
    """
    Fetch fixtures from API-Football.
    
    Args:
        date: Optional date to fetch fixtures for (format: YYYY-MM-DD)
    """
    print("Fetching fixtures from API-Football...")
    
    conn = http.client.HTTPSConnection("api-football-v1.p.rapidapi.com")
    
    headers = {
        'x-rapidapi-key': "f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73",
        'x-rapidapi-host': "api-football-v1.p.rapidapi.com"
    }
    
    # Determine the date to use
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    # Fetch fixtures for the specified date
    endpoint = f"/v3/fixtures?date={date}"
    
    print(f"Using endpoint: {endpoint}")
    conn.request("GET", endpoint, headers=headers)
    
    res = conn.getresponse()
    data = res.read()
    
    # Parse JSON data
    try:
        json_data = json.loads(data.decode("utf-8"))
        print(f"Successfully fetched fixtures for {date}")
        return json_data
    except json.JSONDecodeError:
        print("Error decoding JSON data")
        print(data.decode("utf-8"))
        return None

def fetch_odds(fixture_id=None, bet_id=1, date=None):
    """
    Fetch odds from API-Football.
    
    Args:
        fixture_id: Optional fixture ID to fetch odds for
        bet_id: Bet type ID (default: 1 for Match Winner)
        date: Optional date to fetch odds for (format: YYYY-MM-DD)
    """
    print(f"Fetching odds for bet type {bet_id} from API-Football...")
    
    conn = http.client.HTTPSConnection("api-football-v1.p.rapidapi.com")
    
    headers = {
        'x-rapidapi-key': "f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73",
        'x-rapidapi-host': "api-football-v1.p.rapidapi.com"
    }
    
    # Determine the endpoint based on parameters
    if fixture_id:
        endpoint = f"/v3/odds?fixture={fixture_id}&bet={bet_id}"
    elif date:
        endpoint = f"/v3/odds?date={date}&bet={bet_id}"
    else:
        # Use today's date
        date = datetime.now().strftime("%Y-%m-%d")
        endpoint = f"/v3/odds?date={date}&bet={bet_id}"
    
    print(f"Using endpoint: {endpoint}")
    conn.request("GET", endpoint, headers=headers)
    
    res = conn.getresponse()
    data = res.read()
    
    # Parse JSON data
    try:
        json_data = json.loads(data.decode("utf-8"))
        print("Successfully fetched odds data")
        return json_data
    except json.JSONDecodeError:
        print("Error decoding JSON data")
        print(data.decode("utf-8"))
        return None

def prepare_fixtures_for_prediction(fixtures_data):
    """
    Prepare fixtures data for prediction.
    
    Args:
        fixtures_data: Fixtures data from API-Football
    
    Returns:
        List of fixtures prepared for prediction
    """
    if not fixtures_data or "response" not in fixtures_data:
        return []
    
    fixtures = fixtures_data["response"]
    
    # Filter fixtures to only include not started matches
    filtered_fixtures = [
        fixture for fixture in fixtures
        if fixture.get("fixture", {}).get("status", {}).get("short") == "NS"  # Not Started
    ]
    
    print(f"Found {len(filtered_fixtures)} not started fixtures")
    
    # Prepare fixtures for prediction
    prepared_fixtures = []
    
    for fixture in filtered_fixtures:
        fixture_id = fixture.get("fixture", {}).get("id")
        league = fixture.get("league", {})
        teams = fixture.get("teams", {})
        
        prepared_fixture = {
            "fixture_id": fixture_id,
            "league": league.get("name"),
            "country": league.get("country"),
            "home_team": teams.get("home", {}).get("name"),
            "away_team": teams.get("away", {}).get("name"),
            "date": fixture.get("fixture", {}).get("date")
        }
        
        prepared_fixtures.append(prepared_fixture)
    
    return prepared_fixtures

def predict_with_ml_model(prepared_fixtures, historical_data=None):
    """
    Generate predictions using our ML model.
    
    Args:
        prepared_fixtures: List of fixtures prepared for prediction
        historical_data: Optional historical data for feature engineering
    
    Returns:
        List of predictions
    """
    if not ML_MODEL_AVAILABLE:
        print("ML model not available. Using simple heuristic model instead.")
        return predict_with_heuristic_model(prepared_fixtures)
    
    print("Generating predictions using ML model...")
    
    predictions = []
    
    for fixture in prepared_fixtures:
        try:
            # Create fixture data in the format expected by the ML model
            fixture_data = {
                "fixture": {
                    "id": fixture["fixture_id"],
                    "date": fixture["date"]
                },
                "league": {
                    "name": fixture["league"],
                    "country": fixture["country"]
                },
                "teams": {
                    "home": {"name": fixture["home_team"]},
                    "away": {"name": fixture["away_team"]}
                }
            }
            
            # Generate prediction using the ML model
            prediction_result = ensemble_model.predict(fixture_data, historical_data)
            
            if prediction_result["status"] == "success":
                # Extract predictions
                ml_predictions = []
                
                for pred in prediction_result["predictions"]:
                    ml_predictions.append({
                        "type": pred["prediction_type"],
                        "prediction": pred["prediction"],
                        "confidence": pred["confidence"],
                        "odds": pred["odds"]
                    })
                
                # Add prediction to the list
                predictions.append({
                    "fixture_id": fixture["fixture_id"],
                    "home_team": fixture["home_team"],
                    "away_team": fixture["away_team"],
                    "league": fixture["league"],
                    "country": fixture["country"],
                    "predictions": ml_predictions
                })
            else:
                print(f"Error generating prediction for fixture {fixture['fixture_id']}: {prediction_result.get('message')}")
        
        except Exception as e:
            print(f"Error generating prediction for fixture {fixture['fixture_id']}: {str(e)}")
    
    return predictions

def predict_with_heuristic_model(prepared_fixtures):
    """
    Generate predictions using a simple heuristic model.
    
    Args:
        prepared_fixtures: List of fixtures prepared for prediction
    
    Returns:
        List of predictions
    """
    print("Generating predictions using heuristic model...")
    
    predictions = []
    
    for fixture in prepared_fixtures:
        # Simple heuristic: home advantage
        home_win_prob = 0.45  # Home advantage
        away_win_prob = 0.30
        draw_prob = 0.25
        
        # Determine most likely outcome
        probs = [home_win_prob, draw_prob, away_win_prob]
        outcomes = ["Home Win", "Draw", "Away Win"]
        prediction = outcomes[probs.index(max(probs))]
        confidence = max(probs) * 100
        
        # Calculate odds (simple formula: odds = 1 / probability)
        odds = round(1 / max(probs), 2)
        
        # Over/Under prediction
        over_prob = 0.55  # Slightly favor over 2.5 goals
        over_confidence = over_prob * 100
        over_odds = round(1 / over_prob, 2)
        
        # BTTS prediction
        btts_prob = 0.60  # Slightly favor both teams to score
        btts_confidence = btts_prob * 100
        btts_odds = round(1 / btts_prob, 2)
        
        # Add prediction to the list
        predictions.append({
            "fixture_id": fixture["fixture_id"],
            "home_team": fixture["home_team"],
            "away_team": fixture["away_team"],
            "league": fixture["league"],
            "country": fixture["country"],
            "predictions": [
                {
                    "type": "Match Result",
                    "prediction": prediction,
                    "confidence": confidence,
                    "odds": odds
                },
                {
                    "type": "Over/Under",
                    "prediction": "Over 2.5",
                    "confidence": over_confidence,
                    "odds": over_odds
                },
                {
                    "type": "BTTS",
                    "prediction": "Yes",
                    "confidence": btts_confidence,
                    "odds": btts_odds
                }
            ]
        })
    
    return predictions

def get_bookmaker_odds(odds_data, bet_id):
    """
    Extract bookmaker odds from odds data.
    
    Args:
        odds_data: Odds data from API-Football
        bet_id: Bet type ID
    
    Returns:
        Dictionary mapping fixture IDs to bookmaker odds
    """
    if not odds_data or "response" not in odds_data:
        return {}
    
    odds = odds_data["response"]
    
    # Extract bookmaker odds
    bookmaker_odds = {}
    
    for odd in odds:
        fixture_id = odd.get("fixture", {}).get("id")
        
        if not fixture_id:
            continue
        
        # Extract bookmakers
        bookmakers = odd.get("bookmakers", [])
        
        if not bookmakers:
            continue
        
        # Use the first bookmaker
        bookmaker = bookmakers[0]
        
        # Extract bets
        bets = bookmaker.get("bets", [])
        
        if not bets:
            continue
        
        # Find the bet with the specified ID
        bet = None
        
        for b in bets:
            if b.get("id") == bet_id or b.get("name") == "Match Winner" and bet_id == 1:
                bet = b
                break
        
        if not bet:
            continue
        
        # Extract values
        values = bet.get("values", [])
        
        if not values:
            continue
        
        # Create a dictionary of values
        value_dict = {}
        
        for value in values:
            value_dict[value.get("value")] = float(value.get("odd"))
        
        # Add to bookmaker odds
        bookmaker_odds[fixture_id] = value_dict
    
    return bookmaker_odds

def compare_predictions_with_odds(predictions, match_winner_odds, over_under_odds, btts_odds):
    """
    Compare our predictions with bookmaker odds to identify value bets.
    
    Args:
        predictions: Our model's predictions
        match_winner_odds: Bookmaker odds for match winner
        over_under_odds: Bookmaker odds for over/under
        btts_odds: Bookmaker odds for both teams to score
    
    Returns:
        List of value bets
    """
    print("Comparing predictions with bookmaker odds...")
    
    value_bets = []
    
    for prediction in predictions:
        fixture_id = prediction["fixture_id"]
        
        # Get bookmaker odds for this fixture
        mw_odds = match_winner_odds.get(fixture_id, {})
        ou_odds = over_under_odds.get(fixture_id, {})
        btts_odds = btts_odds.get(fixture_id, {})
        
        # Check each prediction
        for pred in prediction["predictions"]:
            pred_type = pred["type"]
            pred_value = pred["prediction"]
            our_confidence = pred["confidence"] / 100  # Convert to probability
            our_odds = pred["odds"]
            
            # Compare with bookmaker odds
            if pred_type == "Match Result":
                # Map our prediction to bookmaker's format
                if pred_value == "Home Win":
                    bm_value = "Home"
                elif pred_value == "Draw":
                    bm_value = "Draw"
                else:  # Away Win
                    bm_value = "Away"
                
                # Get bookmaker odds for this prediction
                bm_odds = mw_odds.get(bm_value)
                
                if bm_odds:
                    # Calculate implied probability from bookmaker odds
                    bm_prob = 1 / bm_odds
                    
                    # Calculate edge
                    edge = our_confidence - bm_prob
                    
                    # If our probability is higher than bookmaker's, it's a value bet
                    if edge > 0.05:  # At least 5% edge
                        value_bets.append({
                            "fixture_id": fixture_id,
                            "home_team": prediction["home_team"],
                            "away_team": prediction["away_team"],
                            "league": prediction["league"],
                            "country": prediction["country"],
                            "bet_type": pred_type,
                            "prediction": pred_value,
                            "our_confidence": our_confidence * 100,  # Convert back to percentage
                            "our_odds": our_odds,
                            "bookmaker_odds": bm_odds,
                            "edge": edge * 100  # Convert to percentage
                        })
            
            elif pred_type == "Over/Under":
                # Get bookmaker odds for this prediction
                bm_odds = ou_odds.get(pred_value)
                
                if bm_odds:
                    # Calculate implied probability from bookmaker odds
                    bm_prob = 1 / bm_odds
                    
                    # Calculate edge
                    edge = our_confidence - bm_prob
                    
                    # If our probability is higher than bookmaker's, it's a value bet
                    if edge > 0.05:  # At least 5% edge
                        value_bets.append({
                            "fixture_id": fixture_id,
                            "home_team": prediction["home_team"],
                            "away_team": prediction["away_team"],
                            "league": prediction["league"],
                            "country": prediction["country"],
                            "bet_type": pred_type,
                            "prediction": pred_value,
                            "our_confidence": our_confidence * 100,  # Convert back to percentage
                            "our_odds": our_odds,
                            "bookmaker_odds": bm_odds,
                            "edge": edge * 100  # Convert to percentage
                        })
            
            elif pred_type == "BTTS":
                # Get bookmaker odds for this prediction
                bm_odds = btts_odds.get(pred_value)
                
                if bm_odds:
                    # Calculate implied probability from bookmaker odds
                    bm_prob = 1 / bm_odds
                    
                    # Calculate edge
                    edge = our_confidence - bm_prob
                    
                    # If our probability is higher than bookmaker's, it's a value bet
                    if edge > 0.05:  # At least 5% edge
                        value_bets.append({
                            "fixture_id": fixture_id,
                            "home_team": prediction["home_team"],
                            "away_team": prediction["away_team"],
                            "league": prediction["league"],
                            "country": prediction["country"],
                            "bet_type": pred_type,
                            "prediction": pred_value,
                            "our_confidence": our_confidence * 100,  # Convert back to percentage
                            "our_odds": our_odds,
                            "bookmaker_odds": bm_odds,
                            "edge": edge * 100  # Convert to percentage
                        })
    
    # Sort value bets by edge
    value_bets.sort(key=lambda x: x["edge"], reverse=True)
    
    return value_bets

def display_value_bets(value_bets):
    """
    Display value bets in a readable format.
    
    Args:
        value_bets: List of value bets
    """
    if not value_bets:
        print("No value bets found")
        return
    
    print(f"\nFound {len(value_bets)} value bets:")
    
    for i, bet in enumerate(value_bets):
        print(f"\nValue Bet {i+1}:")
        print(f"  Match: {bet['home_team']} vs {bet['away_team']} ({bet['league']}, {bet['country']})")
        print(f"  Bet Type: {bet['bet_type']}")
        print(f"  Prediction: {bet['prediction']}")
        print(f"  Our Confidence: {bet['our_confidence']:.1f}%")
        print(f"  Our Odds: {bet['our_odds']}")
        print(f"  Bookmaker Odds: {bet['bookmaker_odds']}")
        print(f"  Edge: {bet['edge']:.1f}%")

def save_predictions(predictions, filename):
    """
    Save predictions to a JSON file.
    
    Args:
        predictions: Predictions to save
        filename: Filename to save to
    """
    output_file = os.path.join(PREDICTIONS_DIR, filename)
    
    with open(output_file, "w") as f:
        json.dump(predictions, f, indent=2)
    
    print(f"Predictions saved to {output_file}")

def save_value_bets(value_bets, filename):
    """
    Save value bets to a JSON file.
    
    Args:
        value_bets: Value bets to save
        filename: Filename to save to
    """
    output_file = os.path.join(PREDICTIONS_DIR, filename)
    
    with open(output_file, "w") as f:
        json.dump(value_bets, f, indent=2)
    
    print(f"Value bets saved to {output_file}")

def main():
    """Main function to generate predictions and identify value bets."""
    try:
        # Get today's date
        today = datetime.now().strftime("%Y-%m-%d")
        today_filename = datetime.now().strftime("%Y%m%d")
        
        print(f"Generating predictions for {today}...")
        
        # Fetch fixtures
        fixtures_data = fetch_fixtures(today)
        
        if not fixtures_data:
            print("No fixtures data available")
            return
        
        # Prepare fixtures for prediction
        prepared_fixtures = prepare_fixtures_for_prediction(fixtures_data)
        
        if not prepared_fixtures:
            print("No fixtures to predict")
            return
        
        # Generate predictions
        predictions = predict_with_heuristic_model(prepared_fixtures)
        
        # Save predictions
        save_predictions(predictions, f"predictions_{today_filename}.json")
        
        # Fetch odds for different bet types
        match_winner_odds_data = fetch_odds(bet_id=1, date=today)
        over_under_odds_data = fetch_odds(bet_id=5, date=today)
        btts_odds_data = fetch_odds(bet_id=8, date=today)
        
        # Extract bookmaker odds
        match_winner_odds = get_bookmaker_odds(match_winner_odds_data, 1)
        over_under_odds = get_bookmaker_odds(over_under_odds_data, 5)
        btts_odds = get_bookmaker_odds(btts_odds_data, 8)
        
        # Compare predictions with bookmaker odds
        value_bets = compare_predictions_with_odds(
            predictions, match_winner_odds, over_under_odds, btts_odds
        )
        
        # Display value bets
        display_value_bets(value_bets)
        
        # Save value bets
        save_value_bets(value_bets, f"value_bets_{today_filename}.json")
        
        print("\nPredictions and value bets generated successfully")
    
    except Exception as e:
        print(f"Error generating predictions: {str(e)}")

if __name__ == "__main__":
    main()
