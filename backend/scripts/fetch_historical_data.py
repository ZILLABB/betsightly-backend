"""
Fetch Historical Data

This script fetches historical football match data from API-Football.
The data is used to train the machine learning models for predicting match outcomes.
"""

import os
import json
import logging
import aiohttp
import asyncio
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")
FEATURES_FILE = os.path.join(HISTORICAL_DIR, "features.csv")
RESULTS_FILE = os.path.join(HISTORICAL_DIR, "results.csv")
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

# API-Football configuration
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "f486427076msh6a88663abedebbcp15f9c4jsn3ae4c457ef73")
API_FOOTBALL_HOST = os.getenv("API_FOOTBALL_HOST", "api-football-v1.p.rapidapi.com")
API_FOOTBALL_BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

# Top leagues to fetch data for
LEAGUES = {
    39: "English Premier League",
    140: "Spanish La Liga",
    78: "German Bundesliga",
    135: "Italian Serie A",
    61: "French Ligue 1"
}

# Seasons to fetch data for (last 5 seasons)
SEASONS = ["2019", "2020", "2021", "2022", "2023"]

async def fetch_fixtures_for_league_season(session: aiohttp.ClientSession, league_id: int, season: str) -> List[Dict[str, Any]]:
    """
    Fetch fixtures for a specific league and season.

    Args:
        session: aiohttp ClientSession
        league_id: League ID
        season: Season (e.g., "2023")

    Returns:
        List of fixtures
    """
    # Build cache key
    cache_key = f"fixtures_league_{league_id}_season_{season}"
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    # Check cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            # Check if cache is expired (30 days)
            expires_at = cache_data.get("expires_at", 0)
            if expires_at > datetime.now().timestamp():
                logger.info(f"Using cached fixtures for league {league_id}, season {season}")
                return cache_data.get("data", [])
        except Exception as e:
            logger.error(f"Error reading cache: {str(e)}")

    # Build URL and parameters
    url = f"{API_FOOTBALL_BASE_URL}/fixtures"
    params = {
        "league": league_id,
        "season": season
    }

    headers = {
        "x-rapidapi-key": API_FOOTBALL_KEY,
        "x-rapidapi-host": API_FOOTBALL_HOST
    }

    try:
        # Make request
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                fixtures = data.get("response", [])

                # Cache the response (expires in 30 days)
                cache_data = {
                    "data": fixtures,
                    "expires_at": (datetime.now() + timedelta(days=30)).timestamp()
                }

                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(cache_file, "w") as f:
                    json.dump(cache_data, f)

                logger.info(f"Fetched {len(fixtures)} fixtures for league {league_id}, season {season}")

                # Add a delay to avoid hitting API rate limits
                await asyncio.sleep(1)

                return fixtures
            else:
                logger.error(f"Error fetching fixtures: {response.status}")
                return []
    except Exception as e:
        logger.error(f"Exception fetching fixtures: {str(e)}")
        return []

async def fetch_all_historical_data() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Fetch historical data for all leagues and seasons.
    Implements efficient API usage with rate limiting and caching.

    Returns:
        Tuple of (features, results)
    """
    all_features = []
    all_results = []

    # Check if we already have the data files
    if os.path.exists(FEATURES_FILE) and os.path.exists(RESULTS_FILE):
        logger.info("Historical data files already exist. Checking if they need updating...")

        # Check when the files were last modified
        features_mtime = os.path.getmtime(FEATURES_FILE)
        results_mtime = os.path.getmtime(RESULTS_FILE)
        last_modified = max(features_mtime, results_mtime)

        # If files are less than 7 days old, use them
        if datetime.now().timestamp() - last_modified < 7 * 24 * 60 * 60:
            logger.info("Using existing historical data files (less than 7 days old)")
            features_df = pd.read_csv(FEATURES_FILE)
            results_df = pd.read_csv(RESULTS_FILE)
            return features_df.to_dict('records'), results_df.to_dict('records')

    # Track API calls to avoid hitting rate limits
    api_calls = 0
    max_api_calls = 90  # Leave buffer for free tier (100 calls/day)

    async with aiohttp.ClientSession() as session:
        for league_id, league_name in LEAGUES.items():
            for season in SEASONS:
                # Check if we've hit the API call limit
                if api_calls >= max_api_calls:
                    logger.warning(f"Approaching API call limit ({api_calls}/{max_api_calls}). Stopping data collection.")
                    break

                fixtures = await fetch_fixtures_for_league_season(session, league_id, season)
                api_calls += 1

                # Add a delay between league/season requests to avoid rate limiting
                await asyncio.sleep(2)

                for fixture in fixtures:
                    try:
                        # Skip fixtures without scores or that haven't been played yet
                        if fixture.get("fixture", {}).get("status", {}).get("short") != "FT":
                            continue

                        # Extract basic match info
                        fixture_id = str(fixture.get("fixture", {}).get("id"))
                        match_date = fixture.get("fixture", {}).get("date")
                        home_team = fixture.get("teams", {}).get("home", {}).get("name")
                        away_team = fixture.get("teams", {}).get("away", {}).get("name")
                        home_goals = fixture.get("goals", {}).get("home")
                        away_goals = fixture.get("goals", {}).get("away")

                        # Skip if any essential data is missing
                        if None in [fixture_id, match_date, home_team, away_team, home_goals, away_goals]:
                            continue

                        # Create match result
                        if home_goals > away_goals:
                            match_result = "H"
                        elif home_goals < away_goals:
                            match_result = "A"
                        else:
                            match_result = "D"

                        # Create over/under result
                        over_2_5 = 1 if home_goals + away_goals > 2.5 else 0

                        # Create BTTS result
                        btts = 1 if home_goals > 0 and away_goals > 0 else 0

                        # Extract team statistics
                        home_team_stats = fixture.get("teams", {}).get("home", {})
                        away_team_stats = fixture.get("teams", {}).get("away", {})

                        # Extract league statistics
                        league_stats = fixture.get("league", {})

                        # Create features
                        features = {
                            "match_id": fixture_id,
                            "date": match_date,
                            "home_team": home_team,
                            "away_team": away_team,
                            "league": league_name,
                            "season": season,
                            # Team form (win rate in last 5 matches)
                            "home_form": home_team_stats.get("last_5", {}).get("win", 0) / 5 if "last_5" in home_team_stats else 0.5,
                            "away_form": away_team_stats.get("last_5", {}).get("win", 0) / 5 if "last_5" in away_team_stats else 0.5,
                            # Team attack strength (goals scored per match)
                            "home_attack": home_team_stats.get("goals", {}).get("for", {}).get("average", {}).get("home", 1.5),
                            "away_attack": away_team_stats.get("goals", {}).get("for", {}).get("average", {}).get("away", 1.2),
                            # Team defense strength (goals conceded per match)
                            "home_defense": home_team_stats.get("goals", {}).get("against", {}).get("average", {}).get("home", 1.2),
                            "away_defense": away_team_stats.get("goals", {}).get("against", {}).get("average", {}).get("away", 1.5),
                            # League position difference
                            "league_position_diff": home_team_stats.get("league_position", 10) - away_team_stats.get("league_position", 10),
                            # Head-to-head stats (placeholder values, would need separate API calls)
                            "h2h_home_wins": 0,
                            "h2h_away_wins": 0,
                            "h2h_draws": 0
                        }

                        # Create results
                        results = {
                            "match_id": fixture_id,
                            "date": match_date,
                            "home_team": home_team,
                            "away_team": away_team,
                            "home_goals": home_goals,
                            "away_goals": away_goals,
                            "match_result": match_result,
                            "over_2_5": over_2_5,
                            "btts": btts
                        }

                        all_features.append(features)
                        all_results.append(results)

                    except Exception as e:
                        logger.error(f"Error processing fixture: {str(e)}")

    return all_features, all_results

async def main():
    """Main function to fetch and save historical data."""
    # Create directories if they don't exist
    os.makedirs(HISTORICAL_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    logger.info("Fetching historical football data...")

    # Fetch historical data
    features, results = await fetch_all_historical_data()

    # Convert to DataFrames
    features_df = pd.DataFrame(features)
    results_df = pd.DataFrame(results)

    # Save to CSV
    features_df.to_csv(FEATURES_FILE, index=False)
    results_df.to_csv(RESULTS_FILE, index=False)

    logger.info(f"Saved {len(features_df)} matches to {FEATURES_FILE} and {RESULTS_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
