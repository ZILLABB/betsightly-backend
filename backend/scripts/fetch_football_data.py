#!/usr/bin/env python3
"""
Fetch fixtures from football-data.org and generate predictions.

This script fetches fixtures from the football-data.org API and generates predictions
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
import argparse

# Add parent directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(backend_dir)
os.chdir(backend_dir)  # Change to backend directory to ensure .env is found

# Set up logging
log_dir = os.path.join(backend_dir, "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"football_data_{datetime.now().strftime('%Y-%m-%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Football-Data.org constants
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
FOOTBALL_DATA_KEY = "f9ed94ba8dde4a57b742ce7075057310"
FOOTBALL_DATA_HEADERS = {
    "X-Auth-Token": FOOTBALL_DATA_KEY
}

# Competition IDs for major leagues
COMPETITIONS = {
    "PL": "Premier League (England)",
    "PD": "La Liga (Spain)",
    "SA": "Serie A (Italy)",
    "BL1": "Bundesliga (Germany)",
    "FL1": "Ligue 1 (France)",
    "CL": "Champions League",
    "EC": "European Championship",
    "WC": "World Cup"
}

# Data directories
DATA_DIR = os.path.join(backend_dir, "data")
FIXTURES_DIR = os.path.join(DATA_DIR, "fixtures")
os.makedirs(FIXTURES_DIR, exist_ok=True)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Fetch fixtures from football-data.org")
    
    parser.add_argument(
        "--date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date for fixtures (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--competitions",
        type=str,
        default="PL,PD,SA,BL1,FL1",
        help="Comma-separated list of competition codes"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force fetching fixtures from API even if cached"
    )
    
    return parser.parse_args()

def fetch_matches(date_str=None, competitions=None, force=False):
    """
    Fetch matches from football-data.org.
    
    Args:
        date_str: Date string in YYYY-MM-DD format (default: today)
        competitions: List of competition codes to fetch (default: major leagues)
        force: Force fetching from API even if cached
        
    Returns:
        List of matches
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        
    if competitions is None:
        # Default to major leagues
        competitions = ["PL", "PD", "SA", "BL1", "FL1"]
    
    logger.info(f"Fetching matches for {date_str}")
    
    # Check if we have cached matches for this date
    cache_file = os.path.join(FIXTURES_DIR, f"football_data_{date_str}.json")
    if os.path.exists(cache_file) and not force:
        logger.info(f"Loading matches from cache: {cache_file}")
        with open(cache_file, "r") as f:
            return json.load(f)
    
    all_matches = []
    
    # Fetch matches for each competition
    for competition in competitions:
        logger.info(f"Fetching matches for competition {competition}")
        
        # Build API URL for matches
        url = f"{FOOTBALL_DATA_BASE_URL}/competitions/{competition}/matches"
        params = {
            "dateFrom": date_str,
            "dateTo": date_str
        }
        
        try:
            # Add delay to avoid rate limiting
            time.sleep(1)
            
            # Make API request
            response = requests.get(url, headers=FOOTBALL_DATA_HEADERS, params=params)
            
            # Check response
            if response.status_code == 429:
                logger.error("API RATE LIMIT EXCEEDED. Please try again later.")
                return []
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch matches for competition {competition}: {response.status_code}")
                logger.warning(f"Response: {response.text}")
                continue
            
            # Parse response
            data = response.json()
            
            # Check if response contains matches
            if "matches" not in data or not data["matches"]:
                logger.warning(f"No matches found for competition {competition} on {date_str}")
                continue
            
            # Add matches to list
            matches = data["matches"]
            logger.info(f"Found {len(matches)} matches for competition {competition}")
            
            # Add competition name to each match
            for match in matches:
                match["competitionName"] = COMPETITIONS.get(competition, competition)
            
            all_matches.extend(matches)
            
        except Exception as e:
            logger.error(f"Error fetching matches for competition {competition}: {str(e)}")
            logger.error(traceback.format_exc())
    
    # Save matches to cache
    if all_matches:
        logger.info(f"Saving {len(all_matches)} matches to cache: {cache_file}")
        with open(cache_file, "w") as f:
            json.dump(all_matches, f, indent=2)
    else:
        logger.warning(f"No matches found for {date_str}")
    
    return all_matches

def print_matches(matches):
    """Print matches in a readable format."""
    if not matches:
        print("No matches found.")
        return
    
    print(f"\nFound {len(matches)} matches:\n")
    
    # Group matches by competition
    matches_by_competition = {}
    for match in matches:
        competition_name = match.get("competitionName", match["competition"]["name"])
        if competition_name not in matches_by_competition:
            matches_by_competition[competition_name] = []
        matches_by_competition[competition_name].append(match)
    
    # Print matches by competition
    for competition_name, competition_matches in matches_by_competition.items():
        print(f"\n{competition_name} ({len(competition_matches)} matches):")
        print("-" * 50)
        
        for match in competition_matches:
            home_team = match["homeTeam"]["name"]
            away_team = match["awayTeam"]["name"]
            
            # Parse match date
            match_date = datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
            match_time = match_date.strftime("%H:%M")
            
            # Get match status
            status = match["status"]
            
            # Get score if available
            score_str = ""
            if status != "SCHEDULED" and "score" in match:
                home_score = match["score"]["fullTime"]["home"]
                away_score = match["score"]["fullTime"]["away"]
                if home_score is not None and away_score is not None:
                    score_str = f" ({home_score} - {away_score})"
            
            print(f"{match_time} - {home_team} vs {away_team}{score_str} - {status}")
    
    print("\n")

def main():
    """Main function."""
    try:
        # Parse command line arguments
        args = parse_arguments()
        
        # Fetch matches
        matches = fetch_matches(args.date, args.competitions.split(","), args.force)
        
        # Print matches
        print_matches(matches)
        
        # Return success
        return 0
        
    except Exception as e:
        logger.error(f"Error in main function: {str(e)}")
        logger.error(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())
