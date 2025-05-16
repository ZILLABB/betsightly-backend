"""
Feature Engineering

This module contains the feature engineering class for football match prediction.
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging
import joblib
from typing import Dict, List, Tuple, Any, Union

from app.utils.common import ensure_directory_exists
from app.utils.config import settings

# Set up logging
logger = logging.getLogger(__name__)

class FootballFeatureEngineer:
    """
    Feature engineering for football match prediction.
    """
    
    def __init__(self):
        """Initialize the feature engineer."""
        self.historical_data = None
        self.cache = {}
        self.cache_expiry = {}
        self.cache_dir = settings.ml.CACHE_DIR
        self.cache_file = os.path.join(self.cache_dir, "feature_cache.joblib")
        self.cache_expiry_hours = settings.ml.FEATURE_CACHE_EXPIRY
        
        # Load cache if it exists
        self._load_cache()
    
    def set_historical_data(self, historical_data: pd.DataFrame):
        """
        Set the historical data.
        
        Args:
            historical_data: DataFrame with historical match data
        """
        self.historical_data = historical_data
    
    def engineer_features(self, fixture: Dict[str, Any]) -> pd.DataFrame:
        """
        Engineer features for a fixture.
        
        Args:
            fixture: Fixture data
            
        Returns:
            DataFrame with engineered features
        """
        try:
            # Check if we have historical data
            if self.historical_data is None:
                logger.error("Historical data not set")
                return pd.DataFrame()
            
            # Extract fixture data
            fixture_id = fixture["fixture"]["id"]
            home_team = fixture["teams"]["home"]["name"]
            away_team = fixture["teams"]["away"]["name"]
            
            # Check if features are in cache
            cache_key = f"{fixture_id}_{home_team}_{away_team}"
            cached_features = self._get_from_cache(cache_key)
            
            if cached_features is not None:
                return cached_features
            
            # Create features DataFrame
            features = pd.DataFrame({
                "home_team": [home_team],
                "away_team": [away_team]
            })
            
            # Add team form
            home_form = self._calculate_team_form(home_team)
            away_form = self._calculate_team_form(away_team)
            
            features["home_form"] = home_form
            features["away_form"] = away_form
            
            # Add team attack and defense
            home_attack, home_defense = self._calculate_team_attack_defense(home_team)
            away_attack, away_defense = self._calculate_team_attack_defense(away_team)
            
            features["home_attack"] = home_attack
            features["home_defense"] = home_defense
            features["away_attack"] = away_attack
            features["away_defense"] = away_defense
            
            # Add head-to-head stats
            h2h_home_wins, h2h_away_wins, h2h_draws = self._calculate_h2h_stats(home_team, away_team)
            
            features["h2h_home_wins"] = h2h_home_wins
            features["h2h_away_wins"] = h2h_away_wins
            features["h2h_draws"] = h2h_draws
            
            # Add league position difference
            league_position_diff = self._calculate_league_position_diff(home_team, away_team)
            
            features["league_position_diff"] = league_position_diff
            
            # Add to cache
            self._add_to_cache(cache_key, features)
            
            return features
        
        except Exception as e:
            logger.error(f"Error engineering features: {str(e)}")
            return pd.DataFrame()
    
    def _calculate_team_form(self, team_name: str) -> float:
        """
        Calculate team form (win rate in last 10 matches).
        
        Args:
            team_name: Team name
            
        Returns:
            Form score (0.0 to 1.0)
        """
        try:
            # Check if we have historical data
            if self.historical_data is None:
                return 0.5
            
            # Get last 10 matches
            team_matches = self.historical_data[
                (self.historical_data["home_team"] == team_name) |
                (self.historical_data["away_team"] == team_name)
            ].tail(10)
            
            # Calculate win rate
            if len(team_matches) == 0:
                return 0.5
            
            wins = 0
            
            for _, match in team_matches.iterrows():
                if match["home_team"] == team_name and match["home_score"] > match["away_score"]:
                    wins += 1
                elif match["away_team"] == team_name and match["away_score"] > match["home_score"]:
                    wins += 1
            
            return wins / len(team_matches)
        
        except Exception as e:
            logger.error(f"Error calculating team form: {str(e)}")
            return 0.5
    
    def _calculate_team_attack_defense(self, team_name: str) -> Tuple[float, float]:
        """
        Calculate team attack and defense scores.
        
        Args:
            team_name: Team name
            
        Returns:
            Tuple of (attack_score, defense_score)
        """
        try:
            # Check if we have historical data
            if self.historical_data is None:
                return 0.5, 0.5
            
            # Get last 10 matches
            team_matches = self.historical_data[
                (self.historical_data["home_team"] == team_name) |
                (self.historical_data["away_team"] == team_name)
            ].tail(10)
            
            # Calculate attack and defense
            if len(team_matches) == 0:
                return 0.5, 0.5
            
            goals_scored = 0
            goals_conceded = 0
            
            for _, match in team_matches.iterrows():
                if match["home_team"] == team_name:
                    goals_scored += match["home_score"]
                    goals_conceded += match["away_score"]
                else:
                    goals_scored += match["away_score"]
                    goals_conceded += match["home_score"]
            
            # Normalize to 0.0-1.0 range
            attack_score = min(1.0, goals_scored / (len(team_matches) * 2.5))
            defense_score = max(0.0, 1.0 - (goals_conceded / (len(team_matches) * 2.5)))
            
            return attack_score, defense_score
        
        except Exception as e:
            logger.error(f"Error calculating team attack/defense: {str(e)}")
            return 0.5, 0.5
    
    def _calculate_h2h_stats(self, home_team: str, away_team: str) -> Tuple[int, int, int]:
        """
        Calculate head-to-head stats.
        
        Args:
            home_team: Home team name
            away_team: Away team name
            
        Returns:
            Tuple of (home_wins, away_wins, draws)
        """
        try:
            # Check if we have historical data
            if self.historical_data is None:
                return 0, 0, 0
            
            # Get head-to-head matches
            h2h_matches = self.historical_data[
                ((self.historical_data["home_team"] == home_team) & (self.historical_data["away_team"] == away_team)) |
                ((self.historical_data["home_team"] == away_team) & (self.historical_data["away_team"] == home_team))
            ]
            
            # Calculate stats
            if len(h2h_matches) == 0:
                return 0, 0, 0
            
            home_wins = 0
            away_wins = 0
            draws = 0
            
            for _, match in h2h_matches.iterrows():
                if match["home_team"] == home_team and match["home_score"] > match["away_score"]:
                    home_wins += 1
                elif match["home_team"] == away_team and match["home_score"] > match["away_score"]:
                    away_wins += 1
                elif match["away_team"] == home_team and match["away_score"] > match["home_score"]:
                    home_wins += 1
                elif match["away_team"] == away_team and match["away_score"] > match["home_score"]:
                    away_wins += 1
                else:
                    draws += 1
            
            return home_wins, away_wins, draws
        
        except Exception as e:
            logger.error(f"Error calculating h2h stats: {str(e)}")
            return 0, 0, 0
    
    def _calculate_league_position_diff(self, home_team: str, away_team: str) -> int:
        """
        Calculate league position difference.
        
        Args:
            home_team: Home team name
            away_team: Away team name
            
        Returns:
            League position difference (home - away)
        """
        # This is a placeholder - in a real implementation, we would
        # calculate the actual league positions
        return 0
    
    def _get_from_cache(self, key: str) -> Union[pd.DataFrame, None]:
        """
        Get features from cache.
        
        Args:
            key: Cache key
            
        Returns:
            DataFrame with features or None if not in cache
        """
        # Check if key is in cache
        if key not in self.cache:
            return None
        
        # Check if cache is expired
        if key in self.cache_expiry:
            expiry_time = self.cache_expiry[key]
            
            if datetime.now() > expiry_time:
                # Remove from cache
                del self.cache[key]
                del self.cache_expiry[key]
                
                return None
        
        return self.cache[key]
    
    def _add_to_cache(self, key: str, features: pd.DataFrame):
        """
        Add features to cache.
        
        Args:
            key: Cache key
            features: DataFrame with features
        """
        # Add to cache
        self.cache[key] = features
        
        # Set expiry time
        expiry_time = datetime.now() + timedelta(hours=self.cache_expiry_hours)
        self.cache_expiry[key] = expiry_time
        
        # Save cache
        self._save_cache()
    
    def _save_cache(self):
        """Save cache to disk."""
        try:
            # Ensure directory exists
            ensure_directory_exists(self.cache_dir)
            
            # Save cache
            cache_data = {
                "cache": self.cache,
                "cache_expiry": self.cache_expiry
            }
            
            joblib.dump(cache_data, self.cache_file)
        
        except Exception as e:
            logger.error(f"Error saving cache: {str(e)}")
    
    def _load_cache(self):
        """Load cache from disk."""
        try:
            # Check if cache file exists
            if not os.path.exists(self.cache_file):
                return
            
            # Load cache
            cache_data = joblib.load(self.cache_file)
            
            self.cache = cache_data.get("cache", {})
            self.cache_expiry = cache_data.get("cache_expiry", {})
            
            # Remove expired items
            now = datetime.now()
            
            for key in list(self.cache_expiry.keys()):
                if now > self.cache_expiry[key]:
                    if key in self.cache:
                        del self.cache[key]
                    
                    del self.cache_expiry[key]
        
        except Exception as e:
            logger.error(f"Error loading cache: {str(e)}")
            self.cache = {}
            self.cache_expiry = {}
