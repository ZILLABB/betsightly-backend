"""
Fetch Fixtures and Odds

This script fetches fixtures and odds data from API-Football.
"""

import http.client
import json
import os
from datetime import datetime

def fetch_fixtures():
    """Fetch today's fixtures from API-Football."""
    print("Fetching today's fixtures from API-Football...")

    conn = http.client.HTTPSConnection("api-football-v1.p.rapidapi.com")

    headers = {
        'x-rapidapi-key': "f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73",
        'x-rapidapi-host': "api-football-v1.p.rapidapi.com"
    }

    # Get today's date
    today = datetime.now().strftime("%Y-%m-%d")

    # Fetch fixtures for today
    conn.request("GET", f"/v3/fixtures?date={today}", headers=headers)

    res = conn.getresponse()
    data = res.read()

    # Parse JSON data
    try:
        json_data = json.loads(data.decode("utf-8"))
        print(f"Successfully fetched fixtures for {today}")
        return json_data
    except json.JSONDecodeError:
        print("Error decoding JSON data")
        print(data.decode("utf-8"))
        return None

def fetch_odds(fixture_id=None, date=None):
    """
    Fetch odds data from API-Football.

    Args:
        fixture_id: Optional fixture ID to fetch odds for
        date: Optional date to fetch odds for (format: YYYY-MM-DD)
    """
    print("Fetching odds data from API-Football...")

    conn = http.client.HTTPSConnection("api-football-v1.p.rapidapi.com")

    headers = {
        'x-rapidapi-key': "f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73",
        'x-rapidapi-host': "api-football-v1.p.rapidapi.com"
    }

    # Determine the endpoint based on parameters
    if fixture_id:
        endpoint = f"/v3/odds?fixture={fixture_id}"
    elif date:
        endpoint = f"/v3/odds?date={date}"
    else:
        # Default endpoint
        endpoint = "/v3/odds?date=2023-05-13"

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

def display_fixtures(fixtures_data):
    """Display fixtures data in a readable format."""
    if not fixtures_data:
        print("No fixtures data to display")
        return

    # Check API response structure
    if "response" not in fixtures_data:
        print("Unexpected API response format")
        print(fixtures_data)
        return

    # Extract fixtures data
    fixtures = fixtures_data["response"]

    # Print fixtures count
    print(f"Found {len(fixtures)} fixtures for today")

    # Print fixtures data
    print("\nFixtures:")

    for i, fixture in enumerate(fixtures[:10]):  # Show first 10 fixtures
        fixture_data = fixture.get("fixture", {})
        league = fixture.get("league", {})
        teams = fixture.get("teams", {})

        print(f"\nFixture {i+1}:")
        print(f"  ID: {fixture_data.get('id')}")
        print(f"  Date: {fixture_data.get('date')}")
        print(f"  Status: {fixture_data.get('status', {}).get('short')}")
        print(f"  League: {league.get('name')} ({league.get('country')})")
        print(f"  Teams: {teams.get('home', {}).get('name')} vs {teams.get('away', {}).get('name')}")

def display_odds(odds_data):
    """Display odds data in a readable format."""
    if not odds_data:
        print("No odds data to display")
        return

    # Check API response structure for v3 API
    if "response" in odds_data:
        # v3 API format
        odds = odds_data["response"]
        print(f"Found {len(odds)} odds results")

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

                        for k, bet in enumerate(bets[:3]):  # Show first 3 bets
                            print(f"        Bet {k+1}: {bet.get('name')}")

                            # Print values information
                            if "values" in bet:
                                values = bet["values"]
                                print(f"          Values ({len(values)}):")

                                for l, value in enumerate(values):
                                    print(f"            Value {l+1}: {value.get('value')} - Odd: {value.get('odd')}")

        return

    # Check API response structure for v2 API
    if "api" in odds_data:
        # v2 API format
        api_data = odds_data["api"]

        # Print results count
        if "results" in api_data:
            print(f"Found {api_data['results']} odds results")

        # Print odds data
        if "odds" in api_data:
            odds = api_data["odds"]
            print(f"\nOdds Data ({len(odds)} items):")

            for i, odd in enumerate(odds[:5]):  # Show first 5 odds
                print(f"\nOdd {i+1}:")

                # Print fixture information
                if "fixture" in odd:
                    fixture = odd["fixture"]
                    print(f"  Fixture ID: {fixture.get('fixture_id')}")
                    print(f"  League: {fixture.get('league', {}).get('name')}")
                    print(f"  Teams: {fixture.get('homeTeam', {}).get('team_name')} vs {fixture.get('awayTeam', {}).get('team_name')}")
                    print(f"  Date: {fixture.get('event_date')}")

                # Print bookmakers information
                if "bookmakers" in odd:
                    bookmakers = odd["bookmakers"]
                    print(f"  Bookmakers ({len(bookmakers)}):")

                    for j, bookmaker in enumerate(bookmakers[:1]):  # Show first bookmaker
                        print(f"    Bookmaker {j+1}: {bookmaker.get('name')}")

                        # Print bets information
                        if "bets" in bookmaker:
                            bets = bookmaker["bets"]
                            print(f"      Bets ({len(bets)}):")

                            for k, bet in enumerate(bets[:3]):  # Show first 3 bets
                                print(f"        Bet {k+1}: {bet.get('name')}")

                                # Print values information
                                if "values" in bet:
                                    values = bet["values"]
                                    print(f"          Values ({len(values)}):")

                                    for l, value in enumerate(values):
                                        print(f"            Value {l+1}: {value.get('value')} - Odd: {value.get('odd')}")

        return

    # Unknown API format
    print("Unexpected API response format")
    print(odds_data)

def save_data(data, filename):
    """Save data to a JSON file."""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, filename)

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Data saved to {output_file}")

def main():
    """Main function to fetch and display fixtures and odds data."""
    try:
        # Fetch fixtures data
        fixtures_data = fetch_fixtures()

        # Display fixtures data
        display_fixtures(fixtures_data)

        # Save fixtures data
        if fixtures_data:
            today = datetime.now().strftime("%Y%m%d")
            save_data(fixtures_data, f"fixtures_{today}.json")

        print("\n" + "="*80 + "\n")

        # Find a fixture ID to use for odds
        fixture_id = None
        if fixtures_data and "response" in fixtures_data:
            fixtures = fixtures_data["response"]
            for fixture in fixtures:
                # Look for a not started fixture
                if fixture.get("fixture", {}).get("status", {}).get("short") == "NS":
                    fixture_id = fixture.get("fixture", {}).get("id")
                    print(f"Found not started fixture: {fixture_id}")
                    break

            # If no not started fixture, use the first fixture
            if not fixture_id and fixtures:
                fixture_id = fixtures[0].get("fixture", {}).get("id")
                print(f"Using first fixture: {fixture_id}")

        # Fetch odds data for the fixture
        odds_data = fetch_odds(fixture_id)

        # Display odds data
        display_odds(odds_data)

        # Save odds data
        if odds_data:
            today = datetime.now().strftime("%Y%m%d")
            save_data(odds_data, f"odds_{today}.json")

        print("\nData fetched successfully")

    except Exception as e:
        print(f"Error fetching data: {str(e)}")

if __name__ == "__main__":
    main()
