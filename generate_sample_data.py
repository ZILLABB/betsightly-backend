"""
Generate Sample Data

This script generates sample data for testing the Football Betting Assistant.
It creates sample historical match data and saves it to CSV files.
"""

import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
import random

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
HISTORICAL_DIR = os.path.join(DATA_DIR, "historical")
FEATURES_FILE = os.path.join(HISTORICAL_DIR, "features.csv")
RESULTS_FILE = os.path.join(HISTORICAL_DIR, "results.csv")

# Sample teams for each league
TEAMS = {
    "English Premier League": [
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", 
        "Chelsea", "Crystal Palace", "Everton", "Fulham", "Liverpool", 
        "Manchester City", "Manchester United", "Newcastle", "Nottingham Forest", 
        "Sheffield United", "Tottenham", "West Ham", "Wolves"
    ],
    "Spanish La Liga": [
        "Athletic Bilbao", "Atletico Madrid", "Barcelona", "Celta Vigo", "Getafe", 
        "Girona", "Mallorca", "Osasuna", "Real Betis", "Real Madrid", 
        "Real Sociedad", "Sevilla", "Valencia", "Villarreal"
    ],
    "German Bundesliga": [
        "Bayern Munich", "Borussia Dortmund", "RB Leipzig", "Bayer Leverkusen", 
        "Eintracht Frankfurt", "Wolfsburg", "Borussia Monchengladbach", "Werder Bremen", 
        "Hoffenheim", "Freiburg", "Mainz", "Augsburg", "Cologne", "Union Berlin"
    ],
    "Italian Serie A": [
        "AC Milan", "Inter Milan", "Juventus", "Napoli", "Roma", "Lazio", 
        "Atalanta", "Fiorentina", "Bologna", "Torino", "Verona", "Udinese", 
        "Sassuolo", "Empoli", "Monza", "Salernitana"
    ],
    "French Ligue 1": [
        "PSG", "Marseille", "Monaco", "Lyon", "Lille", "Rennes", 
        "Nice", "Lens", "Strasbourg", "Reims", "Montpellier", "Nantes", 
        "Brest", "Toulouse", "Clermont Foot", "Metz"
    ]
}

# Leagues
LEAGUES = list(TEAMS.keys())

# Seasons
SEASONS = ["2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24"]

def generate_match(league: str, season: str, match_id: int) -> tuple:
    """
    Generate a sample match.
    
    Args:
        league: League name
        season: Season
        match_id: Match ID
    
    Returns:
        Tuple of (features, results)
    """
    # Get teams for the league
    teams = TEAMS[league]
    
    # Select home and away teams
    home_team = random.choice(teams)
    away_team = random.choice([t for t in teams if t != home_team])
    
    # Generate match date
    season_start_year = int(season.split("-")[0])
    start_date = datetime(season_start_year, 8, 1)
    end_date = datetime(season_start_year + 1, 5, 31)
    match_date = start_date + timedelta(days=random.randint(0, (end_date - start_date).days))
    
    # Generate match ID
    match_id = f"{league}_{season}_{match_id}_{home_team}_{away_team}"
    
    # Generate team strengths
    home_attack = random.uniform(0.3, 0.9)
    home_defense = random.uniform(0.3, 0.9)
    away_attack = random.uniform(0.3, 0.9)
    away_defense = random.uniform(0.3, 0.9)
    
    # Generate form
    home_form = random.uniform(0.3, 0.9)
    away_form = random.uniform(0.3, 0.9)
    
    # Generate league position difference
    league_position_diff = random.randint(-17, 17)
    
    # Generate head-to-head stats
    h2h_home_wins = random.randint(0, 5)
    h2h_away_wins = random.randint(0, 5)
    h2h_draws = random.randint(0, 5)
    
    # Generate match result
    home_win_prob = (home_attack * away_defense * home_form * 1.1) / 2
    away_win_prob = (away_attack * home_defense * away_form) / 2
    draw_prob = 1 - home_win_prob - away_win_prob
    
    result_probs = [home_win_prob, draw_prob, away_win_prob]
    result_idx = np.random.choice(3, p=result_probs / np.sum(result_probs))
    
    if result_idx == 0:
        match_result = "H"
        home_goals = random.randint(1, 4)
        away_goals = random.randint(0, home_goals - 1)
    elif result_idx == 1:
        match_result = "D"
        home_goals = random.randint(0, 3)
        away_goals = home_goals
    else:
        match_result = "A"
        away_goals = random.randint(1, 4)
        home_goals = random.randint(0, away_goals - 1)
    
    # Generate over/under and BTTS
    over_2_5 = 1 if home_goals + away_goals > 2.5 else 0
    btts = 1 if home_goals > 0 and away_goals > 0 else 0
    
    # Create features dictionary
    features = {
        "match_id": match_id,
        "date": match_date.strftime("%Y-%m-%d"),
        "home_team": home_team,
        "away_team": away_team,
        "league": league,
        "season": season,
        "home_form": home_form,
        "away_form": away_form,
        "home_attack": home_attack,
        "away_attack": away_attack,
        "home_defense": home_defense,
        "away_defense": away_defense,
        "league_position_diff": league_position_diff,
        "h2h_home_wins": h2h_home_wins,
        "h2h_away_wins": h2h_away_wins,
        "h2h_draws": h2h_draws
    }
    
    # Create results dictionary
    results = {
        "match_id": match_id,
        "date": match_date.strftime("%Y-%m-%d"),
        "home_team": home_team,
        "away_team": away_team,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "match_result": match_result,
        "over_2_5": over_2_5,
        "btts": btts
    }
    
    return features, results

def main():
    """Main function to generate sample data."""
    # Create directories if they don't exist
    os.makedirs(HISTORICAL_DIR, exist_ok=True)
    
    # Generate sample data
    all_features = []
    all_results = []
    
    match_id = 1
    
    for league in LEAGUES:
        for season in SEASONS:
            # Generate 100 matches per league per season
            for _ in range(100):
                features, results = generate_match(league, season, match_id)
                all_features.append(features)
                all_results.append(results)
                match_id += 1
    
    # Convert to DataFrames
    features_df = pd.DataFrame(all_features)
    results_df = pd.DataFrame(all_results)
    
    # Save to CSV
    features_df.to_csv(FEATURES_FILE, index=False)
    results_df.to_csv(RESULTS_FILE, index=False)
    
    logger.info(f"Generated {len(features_df)} sample matches")
    logger.info(f"Saved to {FEATURES_FILE} and {RESULTS_FILE}")

if __name__ == "__main__":
    main()
