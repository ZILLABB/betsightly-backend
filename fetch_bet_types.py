"""
Fetch Bet Types

This script fetches the available bet types from API-Football.
"""

import http.client
import json
import os

def fetch_bet_types():
    """Fetch available bet types from API-Football."""
    print("Fetching available bet types from API-Football...")
    
    conn = http.client.HTTPSConnection("api-football-v1.p.rapidapi.com")
    
    headers = {
        'x-rapidapi-key': "f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73",
        'x-rapidapi-host': "api-football-v1.p.rapidapi.com"
    }
    
    conn.request("GET", "/v3/odds/bets", headers=headers)
    
    res = conn.getresponse()
    data = res.read()
    
    # Parse JSON data
    try:
        json_data = json.loads(data.decode("utf-8"))
        print("Successfully fetched bet types")
        return json_data
    except json.JSONDecodeError:
        print("Error decoding JSON data")
        print(data.decode("utf-8"))
        return None

def display_bet_types(bet_types_data):
    """Display bet types data in a readable format."""
    if not bet_types_data:
        print("No bet types data to display")
        return
    
    # Check API response structure
    if "response" not in bet_types_data:
        print("Unexpected API response format")
        print(bet_types_data)
        return
    
    # Extract bet types data
    bet_types = bet_types_data["response"]
    
    # Print bet types count
    print(f"Found {len(bet_types)} bet types")
    
    # Print bet types data
    print("\nBet Types:")
    
    for i, bet_type in enumerate(bet_types):
        print(f"{i+1}. ID: {bet_type.get('id')} - Name: {bet_type.get('name')}")

def save_data(data, filename):
    """Save data to a JSON file."""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(output_dir, exist_ok=True)
    
    output_file = os.path.join(output_dir, filename)
    
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"Data saved to {output_file}")

def main():
    """Main function to fetch and display bet types."""
    try:
        # Fetch bet types data
        bet_types_data = fetch_bet_types()
        
        # Display bet types data
        display_bet_types(bet_types_data)
        
        # Save bet types data
        if bet_types_data:
            save_data(bet_types_data, "bet_types.json")
        
        print("\nBet types data fetched successfully")
    
    except Exception as e:
        print(f"Error fetching bet types data: {str(e)}")

if __name__ == "__main__":
    main()
