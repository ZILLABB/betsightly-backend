#!/usr/bin/env python3
"""
Fetch fixtures from API-Football and generate predictions.

This script fetches fixtures from the API-Football API and generates predictions
using the trained machine learning models.
"""

import os
import sys
import json
import pandas as pd
import requests
from datetime import datetime, timedelta
import logging
import time
import traceback

# Add parent directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)
os.chdir(backend_dir)  # Change to backend directory to ensure .env is found

# Set up logging
log_dir = os.path.join(backend_dir, "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"fixtures_{datetime.now().strftime('%Y-%m-%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# API-Football constants
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
API_FOOTBALL_KEY = "bbfc08f4961fb2ef3476a129b8cb1cd9"
API_FOOTBALL_HEADERS = {
    "x-rapidapi-host": "v3.football.api-sports.io",
    "x-rapidapi-key": API_FOOTBALL_KEY
}

# Data directories
DATA_DIR = os.path.join(backend_dir, "data")
FIXTURES_DIR = os.path.join(DATA_DIR, "fixtures")
os.makedirs(FIXTURES_DIR, exist_ok=True)

def fetch_fixtures(date_str=None, league_ids=None):
    """
    Fetch fixtures from API-Football.
    
    Args:
        date_str: Date string in YYYY-MM-DD format (default: today)
        league_ids: List of league IDs to fetch (default: major leagues)
        
    Returns:
        List of fixtures
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        
    if league_ids is None:
        # Default to major leagues
        league_ids = [39, 140, 61, 78, 135, 2, 3, 4, 5, 6]
    
    logger.info(f"Fetching fixtures for {date_str}")
    
    # Check if we have cached fixtures for this date
    cache_file = os.path.join(FIXTURES_DIR, f"fixtures_{date_str}.json")
    if os.path.exists(cache_file):
        logger.info(f"Loading fixtures from cache: {cache_file}")
        with open(cache_file, "r") as f:
            return json.load(f)
    
    all_fixtures = []
    
    # Fetch fixtures for each league
    for league_id in league_ids:
        logger.info(f"Fetching fixtures for league {league_id}")
        
        # Build API URL
        url = f"{API_FOOTBALL_BASE_URL}/fixtures"
        params = {
            "date": date_str,
            "league": league_id
        }
        
        try:
            # Add delay to avoid rate limiting
            time.sleep(1)
            
            # Make API request
            response = requests.get(url, headers=API_FOOTBALL_HEADERS, params=params)
            
            # Check for rate limiting
            if response.status_code == 429:
                logger.error("API RATE LIMIT EXCEEDED. Please try again after the rate limit resets.")
                # Print rate limit headers if available
                if 'x-ratelimit-remaining' in response.headers:
                    logger.error(f"Rate limit remaining: {response.headers.get('x-ratelimit-remaining', 'unknown')}")
                if 'x-ratelimit-reset' in response.headers:
                    logger.error(f"Rate limit resets at: {response.headers.get('x-ratelimit-reset', 'unknown')}")
                return []
            
            # Check response
            if response.status_code != 200:
                logger.warning(f"Failed to fetch fixtures for league {league_id}: {response.status_code}")
                logger.warning(f"Response: {response.text}")
                continue
            
            # Parse response
            data = response.json()
            
            # Check if response contains fixtures
            if "response" not in data or not data["response"]:
                logger.warning(f"No fixtures found for league {league_id} on {date_str}")
                continue
            
            # Add fixtures to list
            fixtures = data["response"]
            logger.info(f"Found {len(fixtures)} fixtures for league {league_id}")
            all_fixtures.extend(fixtures)
            
        except Exception as e:
            logger.error(f"Error fetching fixtures for league {league_id}: {str(e)}")
            logger.error(traceback.format_exc())
    
    # Save fixtures to cache
    if all_fixtures:
        logger.info(f"Saving {len(all_fixtures)} fixtures to cache: {cache_file}")
        with open(cache_file, "w") as f:
            json.dump(all_fixtures, f, indent=2)
    else:
        logger.warning(f"No fixtures found for {date_str}")
    
    return all_fixtures

def print_fixtures(fixtures):
    """Print fixtures in a readable format."""
    if not fixtures:
        print("No fixtures found.")
        return
    
    print(f"\nFound {len(fixtures)} fixtures:\n")
    
    # Group fixtures by league
    fixtures_by_league = {}
    for fixture in fixtures:
        league_name = fixture["league"]["name"]
        if league_name not in fixtures_by_league:
            fixtures_by_league[league_name] = []
        fixtures_by_league[league_name].append(fixture)
    
    # Print fixtures by league
    for league_name, league_fixtures in fixtures_by_league.items():
        print(f"\n{league_name} ({len(league_fixtures)} matches):")
        print("-" * 50)
        
        for fixture in league_fixtures:
            home_team = fixture["teams"]["home"]["name"]
            away_team = fixture["teams"]["away"]["name"]
            fixture_date = datetime.fromisoformat(fixture["fixture"]["date"].replace("Z", "+00:00"))
            fixture_time = fixture_date.strftime("%H:%M")
            
            print(f"{fixture_time} - {home_team} vs {away_team}")
    
    print("\n")

def main():
    """Main function."""
    try:
        # Get date from command line arguments
        if len(sys.argv) > 1:
            date_str = sys.argv[1]
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        # Fetch fixtures
        fixtures = fetch_fixtures(date_str)
        
        # Print fixtures
        print_fixtures(fixtures)
        
        # Return success
        return 0
        
    except Exception as e:
        logger.error(f"Error in main function: {str(e)}")
        logger.error(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())
