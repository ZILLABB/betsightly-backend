"""
Parse Best Predictions

This script parses and displays the response from the /api/predictions/best endpoint.
"""

import requests
import json

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

def parse_best_predictions():
    """Parse and display the best predictions."""
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
        print("BEST PREDICTIONS BY CATEGORY")
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
                    print(f"    • {format_prediction(pred)}")
        
        print("\n" + "="*80)
        print("RESPONSE STRUCTURE")
        print("="*80)
        
        # Print the structure of the response
        print("\nCategories in response:", list(data.keys()))
        
        # Check a sample category
        if '2_odds' in data and data['2_odds']:
            sample = data['2_odds'][0]
            print("\nSample prediction structure:")
            print(f"- id: {type(sample.get('id')).__name__}")
            print(f"- category: {type(sample.get('category')).__name__}")
            print(f"- combined_odds: {type(sample.get('combined_odds')).__name__}")
            print(f"- combined_confidence: {type(sample.get('combined_confidence')).__name__}")
            print(f"- rollover_day: {type(sample.get('rollover_day')).__name__}")
            print(f"- predictions: {type(sample.get('predictions')).__name__} (length: {len(sample.get('predictions', []))})")
            
            # Check a sample individual prediction
            if sample.get('predictions'):
                individual = sample['predictions'][0]
                print("\nSample individual prediction structure:")
                print(f"- id: {type(individual.get('id')).__name__}")
                print(f"- fixture_id: {type(individual.get('fixture_id')).__name__}")
                print(f"- prediction_type: {type(individual.get('prediction_type')).__name__}")
                print(f"- odds: {type(individual.get('odds')).__name__}")
                print(f"- confidence: {type(individual.get('confidence')).__name__}")
                
                # Check fixture structure
                if 'fixture' in individual:
                    fixture = individual['fixture']
                    print("\nSample fixture structure:")
                    print(f"- fixture_id: {type(fixture.get('fixture_id')).__name__}")
                    print(f"- date: {type(fixture.get('date')).__name__}")
                    print(f"- league_name: {type(fixture.get('league_name')).__name__}")
                    print(f"- home_team: {type(fixture.get('home_team')).__name__}")
                    print(f"- away_team: {type(fixture.get('away_team')).__name__}")
    
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    parse_best_predictions()
