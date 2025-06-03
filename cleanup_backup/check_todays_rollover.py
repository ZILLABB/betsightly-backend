"""
Check Today's Rollover Prediction

This script checks the rollover category to find today's rollover prediction.
"""

import requests
import json
from datetime import datetime

def format_prediction(pred):
    """Format a prediction into a readable string."""
    fixture = pred.get('fixture', {})
    home_team = fixture.get('home_team', 'Unknown')
    away_team = fixture.get('away_team', 'Unknown')
    
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
    
    return f"{home_team} vs {away_team}: {prediction_text} (Odds: {odds}, Confidence: {confidence*100:.0f}%)"

def check_todays_rollover():
    """Check today's rollover prediction."""
    try:
        # Get the categories response
        response = requests.get('http://localhost:8000/api/predictions/categories')
        data = response.json()
        
        print("\n" + "="*80)
        print("TODAY'S ROLLOVER PREDICTION")
        print("="*80)
        
        # Get the rollover category
        categories = data.get('categories', {})
        rollover = categories.get('rollover', {})
        
        print(f"Date: {data.get('date', 'Not provided')}")
        print(f"Rollover Name: {rollover.get('name', 'Not provided')}")
        print(f"Description: {rollover.get('description', 'Not provided')}")
        print(f"Target Odds: {rollover.get('target_odds', 'Not provided')}")
        
        # Check if there are days in the rollover
        days = rollover.get('days', [])
        if not days:
            print("\nNo rollover days found.")
            
            # Check if there are predictions directly in the rollover
            predictions = rollover.get('predictions', [])
            if predictions:
                print(f"\nFound {len(predictions)} predictions in rollover:")
                for i, prediction in enumerate(predictions):
                    print(f"\nPrediction {i+1}:")
                    print(f"- Combined Odds: {prediction.get('combined_odds', 'Not provided')}")
                    print(f"- Combined Confidence: {prediction.get('combined_confidence', 0)*100:.0f}%")
                    print(f"- Rollover Day: {prediction.get('rollover_day', 'Not provided')}")
                    
                    individual_predictions = prediction.get('predictions', [])
                    if individual_predictions:
                        print("- Matches:")
                        for pred in individual_predictions:
                            print(f"  • {format_prediction(pred)}")
                    else:
                        print("- No matches found.")
            else:
                print("\nNo rollover predictions found.")
            
            # Check if there are any predictions in the best rollover endpoint
            try:
                best_response = requests.get('http://localhost:8000/api/predictions/best/rollover')
                best_data = best_response.json()
                
                print("\nBest Rollover Endpoint:")
                if 'predictions' in best_data and best_data['predictions']:
                    predictions = best_data['predictions']
                    print(f"Found {len(predictions)} predictions:")
                    for i, prediction in enumerate(predictions):
                        print(f"\nPrediction {i+1}:")
                        print(f"- Combined Odds: {prediction.get('combined_odds', 'Not provided')}")
                        print(f"- Combined Confidence: {prediction.get('combined_confidence', 0)*100:.0f}%")
                        print(f"- Rollover Day: {prediction.get('rollover_day', 'Not provided')}")
                        
                        individual_predictions = prediction.get('predictions', [])
                        if individual_predictions:
                            print("- Matches:")
                            for pred in individual_predictions:
                                print(f"  • {format_prediction(pred)}")
                        else:
                            print("- No matches found.")
                else:
                    print("No predictions found.")
            except Exception as e:
                print(f"Error checking best rollover endpoint: {str(e)}")
            
            return
        
        print(f"\nFound {len(days)} rollover days:")
        
        # Find today's rollover prediction
        today = datetime.now().day
        today_index = (today - 1) % len(days)  # Use modulo to cycle through days
        
        for i, day in enumerate(days):
            day_number = day.get('day', i+1)
            is_today = i == today_index
            
            print(f"\nDay {day_number}{' (TODAY)' if is_today else ''}:")
            print(f"- Combined Odds: {day.get('combined_odds', 'Not provided')}")
            
            predictions = day.get('predictions', [])
            if predictions:
                print(f"- Found {len(predictions)} matches:")
                for pred in predictions:
                    home_team = pred.get('home_team', 'Unknown')
                    away_team = pred.get('away_team', 'Unknown')
                    prediction_text = pred.get('prediction_text', 'Unknown')
                    odds = pred.get('odds', 'Unknown')
                    
                    print(f"  • {home_team} vs {away_team}: {prediction_text} (Odds: {odds})")
            else:
                print("- No matches found for this day.")
        
        # Print today's rollover prediction
        today_day = days[today_index]
        print("\n" + "="*80)
        print(f"TODAY'S ROLLOVER PREDICTION (Day {today_day.get('day', today_index+1)})")
        print("="*80)
        
        predictions = today_day.get('predictions', [])
        if predictions:
            print(f"Combined Odds: {today_day.get('combined_odds', 'Not provided')}")
            print("Matches:")
            for pred in predictions:
                home_team = pred.get('home_team', 'Unknown')
                away_team = pred.get('away_team', 'Unknown')
                prediction_text = pred.get('prediction_text', 'Unknown')
                odds = pred.get('odds', 'Unknown')
                
                print(f"- {home_team} vs {away_team}: {prediction_text} (Odds: {odds})")
        else:
            print("No matches found for today's rollover prediction.")
    
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    check_todays_rollover()
