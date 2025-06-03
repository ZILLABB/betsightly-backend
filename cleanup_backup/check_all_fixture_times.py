"""
Check All Fixture Times

This script checks if all fixtures have the correct time information.
"""

import requests
import json
from datetime import datetime

def check_all_fixture_times():
    """Check if all fixtures have the correct time information."""
    try:
        # Get the best predictions
        response = requests.get('http://localhost:8000/api/predictions/best')
        data = response.json()
        
        print("\n" + "="*80)
        print("CHECKING ALL FIXTURE TIMES")
        print("="*80)
        
        # Track all fixtures
        all_fixtures = []
        
        # Process each category
        for category, predictions in data.items():
            if predictions and len(predictions) > 0 and 'predictions' in predictions[0]:
                for prediction in predictions[0]['predictions']:
                    if 'fixture' in prediction:
                        fixture = prediction['fixture']
                        all_fixtures.append(fixture)
        
        print(f"Found {len(all_fixtures)} fixtures in the API response")
        
        # Check each fixture for time information
        fixtures_with_time = 0
        fixtures_without_time = 0
        
        for fixture in all_fixtures:
            if 'date' in fixture and fixture['date']:
                fixtures_with_time += 1
            else:
                fixtures_without_time += 1
                print(f"Fixture without time: {fixture.get('home_team')} vs {fixture.get('away_team')}")
        
        print(f"\nFixtures with time: {fixtures_with_time}")
        print(f"Fixtures without time: {fixtures_without_time}")
        
        # Print all fixtures with their times
        print("\nAll fixtures with their times:")
        for fixture in all_fixtures:
            home_team = fixture.get('home_team', 'Unknown')
            away_team = fixture.get('away_team', 'Unknown')
            league = fixture.get('league_name', 'Unknown')
            
            if 'date' in fixture and fixture['date']:
                date_str = fixture.get('date')
                try:
                    date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    time_str = date_obj.strftime('%H:%M')
                    print(f"  {home_team} vs {away_team} ({league}): {time_str}")
                except Exception as e:
                    print(f"  {home_team} vs {away_team} ({league}): Error parsing date: {date_str}")
            else:
                print(f"  {home_team} vs {away_team} ({league}): No time information")
        
        # Check if we need to modify the API to include game times
        print("\n" + "="*80)
        print("CONCLUSION")
        print("="*80)
        
        if fixtures_without_time == 0:
            print("All fixtures have time information included in the API response.")
            print("The frontend can access the game time using the 'date' field in the fixture object.")
            print("Example: fixture.date")
        else:
            print(f"{fixtures_without_time} fixtures are missing time information.")
            print("We need to modify the API to ensure all fixtures have time information.")
    
    except Exception as e:
        print(f"Error checking fixture times: {str(e)}")
        import traceback
        print(traceback.format_exc())

if __name__ == "__main__":
    check_all_fixture_times()
