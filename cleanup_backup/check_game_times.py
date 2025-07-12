"""
Check Game Times in API Response

This script checks if the game times are included in the API response.
"""

import requests
import json
from datetime import datetime

def check_game_times():
    """Check if game times are included in the API response."""
    try:
        # Get the best predictions
        response = requests.get('http://localhost:8000/api/predictions/best')
        data = response.json()
        
        print("\n" + "="*80)
        print("CHECKING GAME TIMES IN API RESPONSE")
        print("="*80)
        
        # Check if any category has predictions
        has_predictions = False
        for category, predictions in data.items():
            if predictions and len(predictions) > 0 and 'predictions' in predictions[0]:
                has_predictions = True
                sample_prediction = predictions[0]['predictions'][0]
                if 'fixture' in sample_prediction:
                    fixture = sample_prediction['fixture']
                    print(f"\nSample fixture from {category}:")
                    print(f"  Fixture ID: {fixture.get('fixture_id')}")
                    print(f"  Home Team: {fixture.get('home_team')}")
                    print(f"  Away Team: {fixture.get('away_team')}")
                    print(f"  League: {fixture.get('league_name')}")
                    
                    # Check if date/time is included
                    if 'date' in fixture:
                        date_str = fixture.get('date')
                        print(f"  Date/Time: {date_str}")
                        
                        # Try to parse the date
                        try:
                            date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            print(f"  Parsed Date: {date_obj}")
                            print(f"  Time: {date_obj.strftime('%H:%M')}")
                        except Exception as e:
                            print(f"  Error parsing date: {str(e)}")
                    else:
                        print("  Date/Time: Not included in the response")
                    
                    # Print all fixture fields
                    print("\nAll fixture fields:")
                    for key, value in fixture.items():
                        print(f"  {key}: {value}")
                    
                    break
        
        if not has_predictions:
            print("No predictions found in the API response")
        
        # Check the categories endpoint
        print("\n" + "="*80)
        print("CHECKING GAME TIMES IN CATEGORIES ENDPOINT")
        print("="*80)
        
        response = requests.get('http://localhost:8000/api/predictions/categories')
        data = response.json()
        
        if 'categories' in data:
            categories = data['categories']
            for category_key, category in categories.items():
                if 'predictions' in category and category['predictions']:
                    for prediction in category['predictions']:
                        if 'predictions' in prediction and prediction['predictions']:
                            sample_prediction = prediction['predictions'][0]
                            if 'fixture' in sample_prediction:
                                fixture = sample_prediction['fixture']
                                print(f"\nSample fixture from {category_key}:")
                                print(f"  Fixture ID: {fixture.get('fixture_id')}")
                                print(f"  Home Team: {fixture.get('home_team')}")
                                print(f"  Away Team: {fixture.get('away_team')}")
                                print(f"  League: {fixture.get('league_name')}")
                                
                                # Check if date/time is included
                                if 'date' in fixture:
                                    date_str = fixture.get('date')
                                    print(f"  Date/Time: {date_str}")
                                    
                                    # Try to parse the date
                                    try:
                                        date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                                        print(f"  Parsed Date: {date_obj}")
                                        print(f"  Time: {date_obj.strftime('%H:%M')}")
                                    except Exception as e:
                                        print(f"  Error parsing date: {str(e)}")
                                else:
                                    print("  Date/Time: Not included in the response")
                                
                                break
                    break
        
        # Check if we need to modify the API to include game times
        print("\n" + "="*80)
        print("CONCLUSION")
        print("="*80)
        
        if 'date' in fixture:
            print("Game times ARE included in the API response.")
            print("The frontend can access the game time using the 'date' field in the fixture object.")
            print("Example: fixture.date")
        else:
            print("Game times are NOT included in the API response.")
            print("We need to modify the API to include game times.")
    
    except Exception as e:
        print(f"Error checking game times: {str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    check_game_times()
