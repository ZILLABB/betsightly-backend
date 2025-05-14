"""
Fetch Odds by Bet Type

This script fetches odds for a specific bet type from API-Football.
"""

import http.client
import json
import os
from datetime import datetime

def fetch_odds_by_bet(bet_id, date=None):
    """
    Fetch odds for a specific bet type from API-Football.
    
    Args:
        bet_id: Bet type ID
        date: Optional date to fetch odds for (format: YYYY-MM-DD)
    """
    print(f"Fetching odds for bet type {bet_id} from API-Football...")
    
    conn = http.client.HTTPSConnection("api-football-v1.p.rapidapi.com")
    
    headers = {
        'x-rapidapi-key': "f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73",
        'x-rapidapi-host': "api-football-v1.p.rapidapi.com"
    }
    
    # Determine the endpoint based on parameters
    if date:
        endpoint = f"/v3/odds?bet={bet_id}&date={date}"
    else:
        # Use a default date
        endpoint = f"/v3/odds?bet={bet_id}&date=2023-05-13"
    
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

def display_odds(odds_data):
    """Display odds data in a readable format."""
    if not odds_data:
        print("No odds data to display")
        return
    
    # Check API response structure
    if "response" not in odds_data:
        print("Unexpected API response format")
        print(odds_data)
        return
    
    # Extract odds data
    odds = odds_data["response"]
    
    # Print odds count
    print(f"Found {len(odds)} odds results")
    
    # Print odds data
    if len(odds) > 0:
        print("\nOdds Data:")
        
        for i, odd in enumerate(odds[:5]):  # Show first 5 odds
            print(f"\nOdd {i+1}:")
            
            # Print fixture information
            if "fixture" in odd:
                fixture = odd["fixture"]
                print(f"  Fixture ID: {fixture.get('id')}")
                
            if "league" in odd:
                league = odd["league"]
                print(f"  League: {league.get('name')} ({league.get('country')})")
            
            if "teams" in odd:
                teams = odd["teams"]
                print(f"  Teams: {teams.get('home', {}).get('name')} vs {teams.get('away', {}).get('name')}")
            
            # Print bookmakers information
            if "bookmakers" in odd:
                bookmakers = odd["bookmakers"]
                print(f"  Bookmakers ({len(bookmakers)}):")
                
                for j, bookmaker in enumerate(bookmakers[:2]):  # Show first 2 bookmakers
                    print(f"    Bookmaker {j+1}: {bookmaker.get('name')}")
                    
                    # Print bets information
                    if "bets" in bookmaker:
                        bets = bookmaker["bets"]
                        print(f"      Bets ({len(bets)}):")
                        
                        for k, bet in enumerate(bets):
                            print(f"        Bet {k+1}: {bet.get('name')}")
                            
                            # Print values information
                            if "values" in bet:
                                values = bet["values"]
                                print(f"          Values ({len(values)}):")
                                
                                for l, value in enumerate(values):
                                    print(f"            Value {l+1}: {value.get('value')} - Odd: {value.get('odd')}")

def save_data(data, filename):
    """Save data to a JSON file."""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, filename)
    
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"Data saved to {output_file}")

def main():
    """Main function to fetch and display odds for a specific bet type."""
    try:
        # Define bet types to fetch
        bet_types = [
            {"id": 1, "name": "Match Winner"},
            {"id": 5, "name": "Goals Over/Under"},
            {"id": 8, "name": "Both Teams Score"}
        ]
        
        # Get today's date
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Fetch odds for each bet type
        for bet_type in bet_types:
            print("\n" + "="*80)
            print(f"Fetching odds for {bet_type['name']} (ID: {bet_type['id']})")
            print("="*80 + "\n")
            
            # Fetch odds data
            odds_data = fetch_odds_by_bet(bet_type["id"], today)
            
            # Display odds data
            display_odds(odds_data)
            
            # Save odds data
            if odds_data:
                save_data(odds_data, f"odds_{bet_type['id']}_{today.replace('-', '')}.json")
        
        print("\nOdds data fetched successfully")
    
    except Exception as e:
        print(f"Error fetching odds data: {str(e)}")

if __name__ == "__main__":
    main()
