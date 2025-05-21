#!/usr/bin/env python3
"""
Enhanced Data Collection Script

This script collects comprehensive historical data from API-Football and the local database
for training improved ML models.
"""

import os
import sys
import pandas as pd
import numpy as np
import requests
import logging
import json
from datetime import datetime, timedelta
import argparse

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical", "enhanced")
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Collect enhanced historical data for ML training")

    parser.add_argument(
        "--seasons",
        type=str,
        default="2020,2021,2022,2023",
        help="Comma-separated list of seasons to collect data for"
    )

    parser.add_argument(
        "--leagues",
        type=str,
        default="39,140,135,78,61",  # Premier League, La Liga, Serie A, Bundesliga, Ligue 1
        help="Comma-separated list of league IDs to collect data for"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force data collection even if data already exists"
    )

    return parser.parse_args()

def ensure_directory_exists(directory):
    """Ensure a directory exists."""
    os.makedirs(directory, exist_ok=True)

def fetch_fixtures(league_id, season, api_key):
    """
    Fetch fixtures for a league and season from API-Football.

    Args:
        league_id: League ID
        season: Season year
        api_key: API-Football API key

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

    # API endpoint
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"

    # Headers
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com"
    }

    # Parameters
    params = {
        "league": league_id,
        "season": season
    }

    # Make request
    try:
        logger.info(f"Fetching fixtures for league {league_id}, season {season}")
        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            logger.error(f"Error fetching fixtures: {response.status_code}")
            return []

        # Parse response
        data = response.json()
        fixtures = data.get("response", [])

        # Cache response
        cache_data = {
            "data": fixtures,
            "expires_at": (datetime.now() + timedelta(days=30)).timestamp()
        }

        # Ensure cache directory exists
        ensure_directory_exists(CACHE_DIR)

        # Save to cache
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        logger.info(f"Fetched {len(fixtures)} fixtures for league {league_id}, season {season}")
        return fixtures

    except Exception as e:
        logger.error(f"Error fetching fixtures: {str(e)}")
        return []

def fetch_team_statistics(team_id, league_id, season, api_key):
    """
    Fetch team statistics for a season from API-Football.

    Args:
        team_id: Team ID
        league_id: League ID
        season: Season year
        api_key: API-Football API key

    Returns:
        Team statistics
    """
    # Build cache key
    cache_key = f"team_stats_{team_id}_league_{league_id}_season_{season}"
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    # Check cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            # Check if cache is expired (30 days)
            expires_at = cache_data.get("expires_at", 0)
            if expires_at > datetime.now().timestamp():
                logger.info(f"Using cached team statistics for team {team_id}, league {league_id}, season {season}")
                return cache_data.get("data", {})
        except Exception as e:
            logger.error(f"Error reading cache: {str(e)}")

    # API endpoint
    url = "https://api-football-v1.p.rapidapi.com/v3/teams/statistics"

    # Headers
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com"
    }

    # Parameters
    params = {
        "team": team_id,
        "league": league_id,
        "season": season
    }

    # Make request
    try:
        logger.info(f"Fetching team statistics for team {team_id}, league {league_id}, season {season}")
        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            logger.error(f"Error fetching team statistics: {response.status_code}")
            return {}

        # Parse response
        data = response.json()
        stats = data.get("response", {})

        # Cache response
        cache_data = {
            "data": stats,
            "expires_at": (datetime.now() + timedelta(days=30)).timestamp()
        }

        # Ensure cache directory exists
        ensure_directory_exists(CACHE_DIR)

        # Save to cache
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        logger.info(f"Fetched team statistics for team {team_id}, league {league_id}, season {season}")
        return stats

    except Exception as e:
        logger.error(f"Error fetching team statistics: {str(e)}")
        return {}

def fetch_h2h(team1_id, team2_id, api_key):
    """
    Fetch head-to-head statistics for two teams from API-Football.

    Args:
        team1_id: First team ID
        team2_id: Second team ID
        api_key: API-Football API key

    Returns:
        Head-to-head statistics
    """
    # Build cache key
    cache_key = f"h2h_{team1_id}_{team2_id}"
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    # Check cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)

            # Check if cache is expired (7 days)
            expires_at = cache_data.get("expires_at", 0)
            if expires_at > datetime.now().timestamp():
                logger.info(f"Using cached H2H for teams {team1_id} and {team2_id}")
                return cache_data.get("data", [])
        except Exception as e:
            logger.error(f"Error reading cache: {str(e)}")

    # API endpoint
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures/headtohead"

    # Headers
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "api-football-v1.p.rapidapi.com"
    }

    # Parameters
    params = {
        "h2h": f"{team1_id}-{team2_id}",
        "last": 10
    }

    # Make request
    try:
        logger.info(f"Fetching H2H for teams {team1_id} and {team2_id}")
        response = requests.get(url, headers=headers, params=params)

        if response.status_code != 200:
            logger.error(f"Error fetching H2H: {response.status_code}")
            return []

        # Parse response
        data = response.json()
        fixtures = data.get("response", [])

        # Cache response
        cache_data = {
            "data": fixtures,
            "expires_at": (datetime.now() + timedelta(days=7)).timestamp()
        }

        # Ensure cache directory exists
        ensure_directory_exists(CACHE_DIR)

        # Save to cache
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        logger.info(f"Fetched {len(fixtures)} H2H fixtures for teams {team1_id} and {team2_id}")
        return fixtures

    except Exception as e:
        logger.error(f"Error fetching H2H: {str(e)}")
        return []

def extract_enhanced_features(fixtures, api_key):
    """
    Extract enhanced features from fixtures.

    Args:
        fixtures: List of fixtures
        api_key: API-Football API key

    Returns:
        DataFrame with enhanced features
    """
    features_data = []

    for fixture in fixtures:
        # Skip fixtures without scores (not played yet)
        if not fixture.get("goals") or fixture["goals"]["home"] is None or fixture["goals"]["away"] is None:
            continue

        # Basic fixture info
        fixture_id = fixture["fixture"]["id"]
        date = fixture["fixture"]["date"].split("T")[0]
        league_id = fixture["league"]["id"]
        season = fixture["league"]["season"]
        home_team_id = fixture["teams"]["home"]["id"]
        away_team_id = fixture["teams"]["away"]["id"]
        home_team_name = fixture["teams"]["home"]["name"]
        away_team_name = fixture["teams"]["away"]["name"]

        # Match result
        home_goals = fixture["goals"]["home"]
        away_goals = fixture["goals"]["away"]

        if home_goals > away_goals:
            match_result = "H"
        elif home_goals < away_goals:
            match_result = "A"
        else:
            match_result = "D"

        # Over/under 2.5 goals
        total_goals = home_goals + away_goals
        over_2_5 = 1 if total_goals > 2.5 else 0

        # Both teams to score
        btts = 1 if home_goals > 0 and away_goals > 0 else 0

        # Get team statistics
        home_stats = fetch_team_statistics(home_team_id, league_id, season, api_key)
        away_stats = fetch_team_statistics(away_team_id, league_id, season, api_key)

        # Get H2H statistics
        h2h_fixtures = fetch_h2h(home_team_id, away_team_id, api_key)

        # Calculate H2H stats
        h2h_home_wins = 0
        h2h_away_wins = 0
        h2h_draws = 0
        h2h_home_goals = 0
        h2h_away_goals = 0
        h2h_matches = 0

        for h2h_fixture in h2h_fixtures:
            # Skip fixtures without scores
            if not h2h_fixture.get("goals") or h2h_fixture["goals"]["home"] is None or h2h_fixture["goals"]["away"] is None:
                continue

            h2h_matches += 1

            if h2h_fixture["teams"]["home"]["id"] == home_team_id and h2h_fixture["teams"]["away"]["id"] == away_team_id:
                h2h_home_goals += h2h_fixture["goals"]["home"]
                h2h_away_goals += h2h_fixture["goals"]["away"]

                if h2h_fixture["goals"]["home"] > h2h_fixture["goals"]["away"]:
                    h2h_home_wins += 1
                elif h2h_fixture["goals"]["home"] < h2h_fixture["goals"]["away"]:
                    h2h_away_wins += 1
                else:
                    h2h_draws += 1
            elif h2h_fixture["teams"]["home"]["id"] == away_team_id and h2h_fixture["teams"]["away"]["id"] == home_team_id:
                h2h_away_goals += h2h_fixture["goals"]["home"]
                h2h_home_goals += h2h_fixture["goals"]["away"]

                if h2h_fixture["goals"]["home"] > h2h_fixture["goals"]["away"]:
                    h2h_away_wins += 1
                elif h2h_fixture["goals"]["home"] < h2h_fixture["goals"]["away"]:
                    h2h_home_wins += 1
                else:
                    h2h_draws += 1

        # Calculate H2H averages
        h2h_avg_home_goals = h2h_home_goals / max(1, h2h_matches)
        h2h_avg_away_goals = h2h_away_goals / max(1, h2h_matches)

        # Extract home team stats
        home_form_str = home_stats.get("form", "")
        home_form = home_form_str.count("W") / max(1, len(home_form_str)) if home_form_str else 0.5
        home_attack = home_stats.get("goals", {}).get("for", {}).get("average", {}).get("total", 0)
        home_defense = home_stats.get("goals", {}).get("against", {}).get("average", {}).get("total", 0)
        home_clean_sheets = home_stats.get("clean_sheet", {}).get("total", 0)
        home_failed_to_score = home_stats.get("failed_to_score", {}).get("total", 0)
        home_league_position = home_stats.get("league", {}).get("position", 0)

        # Extract away team stats
        away_form_str = away_stats.get("form", "")
        away_form = away_form_str.count("W") / max(1, len(away_form_str)) if away_form_str else 0.5
        away_attack = away_stats.get("goals", {}).get("for", {}).get("average", {}).get("total", 0)
        away_defense = away_stats.get("goals", {}).get("against", {}).get("average", {}).get("total", 0)
        away_clean_sheets = away_stats.get("clean_sheet", {}).get("total", 0)
        away_failed_to_score = away_stats.get("failed_to_score", {}).get("total", 0)
        away_league_position = away_stats.get("league", {}).get("position", 0)

        # Calculate league position difference
        league_position_diff = home_league_position - away_league_position

        # Create feature dictionary
        feature_dict = {
            "match_id": fixture_id,
            "date": date,
            "league_id": league_id,
            "season": season,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_team": home_team_name,
            "away_team": away_team_name,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "match_result": match_result,
            "over_2_5": over_2_5,
            "btts": btts,
            "home_form": home_form,
            "away_form": away_form,
            "home_attack": home_attack,
            "away_attack": away_attack,
            "home_defense": home_defense,
            "away_defense": away_defense,
            "home_clean_sheets": home_clean_sheets,
            "away_clean_sheets": away_clean_sheets,
            "home_failed_to_score": home_failed_to_score,
            "away_failed_to_score": away_failed_to_score,
            "h2h_home_wins": h2h_home_wins,
            "h2h_away_wins": h2h_away_wins,
            "h2h_draws": h2h_draws,
            "h2h_avg_home_goals": h2h_avg_home_goals,
            "h2h_avg_away_goals": h2h_avg_away_goals,
            "league_position_diff": league_position_diff,
            "home_league_position": home_league_position,
            "away_league_position": away_league_position
        }

        features_data.append(feature_dict)

    return pd.DataFrame(features_data)

def main():
    """Main function."""
    # Parse arguments
    args = parse_arguments()

    # Get API key from environment
    api_key = os.environ.get("API_FOOTBALL_KEY", "")
    if not api_key:
        logger.error("API_FOOTBALL_KEY not found in environment variables")
        sys.exit(1)

    # Parse seasons and leagues
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    leagues = [int(l.strip()) for l in args.leagues.split(",")]

    # Ensure directories exist
    ensure_directory_exists(HISTORICAL_DIR)
    ensure_directory_exists(CACHE_DIR)

    # Output file
    output_file = os.path.join(HISTORICAL_DIR, "enhanced_features.parquet")

    # Check if output file exists
    if os.path.exists(output_file) and not args.force:
        logger.info(f"Enhanced features file already exists at {output_file}. Use --force to regenerate.")
        return

    # Collect data for each league and season
    all_features = []

    for league_id in leagues:
        for season in seasons:
            # Fetch fixtures
            fixtures = fetch_fixtures(league_id, season, api_key)

            # Extract features
            features = extract_enhanced_features(fixtures, api_key)

            # Add to list
            all_features.append(features)

    # Combine all features
    if all_features:
        combined_features = pd.concat(all_features, ignore_index=True)

        # Save to parquet
        combined_features.to_parquet(output_file)

        logger.info(f"Saved {len(combined_features)} enhanced features to {output_file}")
    else:
        logger.warning("No features collected")

if __name__ == "__main__":
    main()
