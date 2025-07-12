"""
Display Current Predictions

This script displays the current predictions being served by the API in a readable format.
"""

import requests
import json
from datetime import datetime

def format_prediction(pred):
    """Format a prediction into a readable string."""
    fixture = pred.get('fixture', {})
    home_team = fixture.get('home_team', 'Unknown')
    away_team = fixture.get('away_team', 'Unknown')
    league_name = fixture.get('league_name', 'Unknown League')
    
    prediction_type = pred.get('prediction_type', 'Unknown')
    odds = pred.get('odds', 'Unknown')
    confidence = pred.get('confidence', 0)
    
    prediction_text = ''
    if prediction_type == 'match_result':
        match_result = pred.get('match_result_pred', '')
        if match_result == 'home':
            prediction_text = f"{home_team} to win"
        elif match_result == 'draw':
            prediction_text = "Draw"
        elif match_result == 'away':
            prediction_text = f"{away_team} to win"
    elif prediction_type == 'over_under':
        over_under = pred.get('over_under_pred', '')
        prediction_text = f"{'Over' if over_under == 'over' else 'Under'} 2.5 goals"
    elif prediction_type == 'btts':
        btts = pred.get('btts_pred', '')
        prediction_text = f"BTTS: {'Yes' if btts == 'yes' else 'No'}"
    
    return {
        "match": f"{home_team} vs {away_team}",
        "league": league_name,
        "prediction": prediction_text,
        "odds": odds,
        "confidence": confidence
    }

def display_current_predictions():
    """Display the current predictions being served by the API."""
    try:
        # Get the best predictions
        response = requests.get('http://localhost:8000/api/predictions/best')
        data = response.json()
        
        # Define category names
        category_names = {
            '2_odds': 'SAFE BETS',
            '5_odds': 'BALANCED RISK',
            '10_odds': 'HIGH REWARD',
            'rollover': 'DAILY ROLLOVER'
        }
        
        print("\n" + "="*80)
        print("CURRENT PREDICTIONS")
        print("="*80)
        
        # Process each category
        for category_key, predictions in data.items():
            category_name = category_names.get(category_key, category_key.upper())
            print(f"\n{category_name} ({category_key}):")
            
            if not predictions:
                print("  No predictions in this category")
                continue
            
            # Get the best prediction
            prediction = predictions[0]
            
            # Print prediction details
            print(f"  Combined Odds: {prediction.get('combined_odds', 0):.2f}")
            print(f"  Combined Confidence: {prediction.get('combined_confidence', 0)*100:.0f}%")
            
            if category_key == 'rollover' and prediction.get('rollover_day') is not None:
                print(f"  Rollover Day: {prediction.get('rollover_day')}")
            
            # Print individual predictions
            individual_predictions = prediction.get('predictions', [])
            print(f"  Number of Predictions: {len(individual_predictions)}")
            
            if individual_predictions:
                print("  Predictions:")
                for pred in individual_predictions:
                    formatted = format_prediction(pred)
                    print(f"    • {formatted['match']} ({formatted['league']})")
                    print(f"      {formatted['prediction']} (Odds: {formatted['odds']:.2f}, Confidence: {formatted['confidence']*100:.0f}%)")
        
        print("\n" + "="*80)
        print("PREDICTION DETAILS")
        print("="*80)
        
        # Print detailed information about each prediction
        for category_key, predictions in data.items():
            if not predictions:
                continue
            
            prediction = predictions[0]
            individual_predictions = prediction.get('predictions', [])
            
            for pred in individual_predictions:
                fixture = pred.get('fixture', {})
                
                print(f"\nMatch: {fixture.get('home_team')} vs {fixture.get('away_team')}")
                print(f"League: {fixture.get('league_name')}")
                print(f"Date: {fixture.get('date')}")
                
                prediction_type = pred.get('prediction_type')
                
                if prediction_type == 'match_result':
                    result = pred.get('match_result_pred')
                    home_win = pred.get('home_win_pred', 0) * 100
                    draw = pred.get('draw_pred', 0) * 100
                    away_win = pred.get('away_win_pred', 0) * 100
                    
                    print(f"Prediction Type: Match Result")
                    print(f"Prediction: {result.capitalize() if result else 'Unknown'}")
                    print(f"Home Win: {home_win:.0f}%")
                    print(f"Draw: {draw:.0f}%")
                    print(f"Away Win: {away_win:.0f}%")
                
                elif prediction_type == 'over_under':
                    result = pred.get('over_under_pred')
                    over = pred.get('over_2_5_pred', 0) * 100
                    under = pred.get('under_2_5_pred', 0) * 100
                    
                    print(f"Prediction Type: Over/Under 2.5 Goals")
                    print(f"Prediction: {result.capitalize() if result else 'Unknown'}")
                    print(f"Over 2.5: {over:.0f}%")
                    print(f"Under 2.5: {under:.0f}%")
                
                elif prediction_type == 'btts':
                    result = pred.get('btts_pred')
                    yes = pred.get('btts_yes_pred', 0) * 100
                    no = pred.get('btts_no_pred', 0) * 100
                    
                    print(f"Prediction Type: Both Teams to Score")
                    print(f"Prediction: {result.capitalize() if result else 'Unknown'}")
                    print(f"Yes: {yes:.0f}%")
                    print(f"No: {no:.0f}%")
                
                print(f"Odds: {pred.get('odds')}")
                print(f"Confidence: {pred.get('confidence', 0)*100:.0f}%")
                print(f"Category: {category_names.get(category_key)}")
    
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    display_current_predictions()
