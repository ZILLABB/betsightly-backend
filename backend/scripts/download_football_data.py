"""
Download Football Data

This script downloads historical football match data from the openfootball/football.json GitHub repository.
The data is used to train the machine learning models for predicting match outcomes.
"""

import os
import json
import logging
import requests
import pandas as pd
from typing import Dict, List, Any, Optional
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")
FEATURES_FILE = os.path.join(HISTORICAL_DIR, "features.csv")
RESULTS_FILE = os.path.join(HISTORICAL_DIR, "results.csv")

# GitHub repository URLs
REPO_BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master"
LEAGUES = {
    "en": "English Premier League",
    "es": "Spanish La Liga",
    "de": "German Bundesliga",
    "it": "Italian Serie A",
    "fr": "French Ligue 1"
}
SEASONS = ["2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24"]

def download_league_data(league_code: str, season: str) -> Optional[Dict[str, Any]]:
    """
    Download data for a specific league and season.
    
    Args:
        league_code: League code (e.g., 'en', 'es')
        season: Season (e.g., '2023-24')
    
    Returns:
        Dictionary containing league data or None if download fails
    """
    url = f"{REPO_BASE_URL}/{season}/{league_code}.1.json"
    logger.info(f"Downloading data from {url}")
    
    try:
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Downloaded {len(data.get('matches', []))} matches for {LEAGUES.get(league_code)} {season}")
            return data
        else:
            logger.error(f"Failed to download data: {response.status_code}")
            return None
    
    except Exception as e:
        logger.error(f"Error downloading data: {str(e)}")
        return None

def process_match_data(data: Dict[str, Any], league_code: str, season: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Process match data to extract features and results.
    
    Args:
        data: Dictionary containing league data
        league_code: League code
        season: Season
    
    Returns:
        Tuple of (features, results)
    """
    features = []
    results = []
    
    matches = data.get("matches", [])
    
    for match in matches:
        try:
            # Skip matches without scores
            if "score" not in match or match["score"] is None:
                continue
            
            # Extract basic match info
            match_id = f"{league_code}_{season}_{match['round']}_{match['team1']['name']}_{match['team2']['name']}"
            match_date = match.get("date")
            home_team = match["team1"]["name"]
            away_team = match["team2"]["name"]
            home_goals = match["score"]["ft"][0]
            away_goals = match["score"]["ft"][1]
            
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
            
            # Add to results
            results.append({
                "match_id": match_id,
                "date": match_date,
                "home_team": home_team,
                "away_team": away_team,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "match_result": match_result,
                "over_2_5": over_2_5,
                "btts": btts
            })
            
            # Extract features (in a real implementation, we would extract more features)
            features.append({
                "match_id": match_id,
                "date": match_date,
                "home_team": home_team,
                "away_team": away_team,
                "league": LEAGUES.get(league_code),
                "season": season,
                # Mock features for now
                "home_form": 0.5,
                "away_form": 0.5,
                "home_attack": 0.5,
                "away_attack": 0.5,
                "home_defense": 0.5,
                "away_defense": 0.5,
                "league_position_diff": 0,
                "h2h_home_wins": 0,
                "h2h_away_wins": 0,
                "h2h_draws": 0
            })
        
        except Exception as e:
            logger.error(f"Error processing match: {str(e)}")
    
    return features, results

def main():
    """Main function to download and process football data."""
    # Create directories if they don't exist
    os.makedirs(HISTORICAL_DIR, exist_ok=True)
    
    all_features = []
    all_results = []
    
    # Download and process data for each league and season
    for league_code in LEAGUES.keys():
        for season in SEASONS:
            data = download_league_data(league_code, season)
            
            if data:
                features, results = process_match_data(data, league_code, season)
                all_features.extend(features)
                all_results.extend(results)
    
    # Convert to DataFrames
    features_df = pd.DataFrame(all_features)
    results_df = pd.DataFrame(all_results)
    
    # Save to CSV
    features_df.to_csv(FEATURES_FILE, index=False)
    results_df.to_csv(RESULTS_FILE, index=False)
    
    logger.info(f"Saved {len(features_df)} matches to {FEATURES_FILE} and {RESULTS_FILE}")

if __name__ == "__main__":
    main()
