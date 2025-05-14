"""
API-Football Client

This module provides a client for accessing football data from the API-Football API.
It implements efficient caching and database storage to minimize API calls.
"""

import os
import json
import logging
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

from sqlalchemy.orm import Session
from app.database.models.fixture import Fixture
from app.config import settings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class APIFootballClient:
    """
    Client for accessing football data from API-Football.

    Features:
    - Fetches fixtures for a specific date
    - Fetches team statistics
    - Implements database caching to minimize API calls
    - Handles API rate limits
    - Saves data to database for persistence
    """

    def __init__(self):
        """Initialize the API-Football client."""
        self.base_url = settings.API_FOOTBALL_BASE_URL
        self.api_key = settings.API_FOOTBALL_KEY
        self.api_host = settings.API_FOOTBALL_HOST
        self.headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.api_host
        }
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), settings.CACHE_DIR)
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Track API calls to avoid hitting rate limits
        self.api_calls = 0
        self.api_call_reset = datetime.now() + timedelta(days=1)  # Reset counter daily

    async def get_fixtures(self, db: Session, date: str = None, league_id: int = None, team_id: int = None, force_update: bool = False) -> List[Dict[str, Any]]:
        """
        Get fixtures for a specific date, league, or team.
        Prioritizes database lookup before making API calls.

        Args:
            db: Database session
            date: Date in format YYYY-MM-DD (default: today)
            league_id: League ID
            team_id: Team ID
            force_update: Whether to force an update from the API

        Returns:
            List of fixtures
        """
        # Set default date to today if not provided
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        # Check if we need to reset API call counter
        if datetime.now() > self.api_call_reset:
            self.api_calls = 0
            self.api_call_reset = datetime.now() + timedelta(days=1)

        # First, try to get fixtures from database
        if not force_update:
            fixtures_from_db = self._get_fixtures_from_db(db, date, league_id, team_id)
            if fixtures_from_db:
                logger.info(f"Using fixtures from database for {date}")
                return fixtures_from_db

        # If not in database or force update, check file cache
        cache_key = f"fixtures_{date}"
        if league_id:
            cache_key += f"_league_{league_id}"
        if team_id:
            cache_key += f"_team_{team_id}"

        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        
        if not force_update and os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cache_data = json.load(f)
                
                # Check if cache is expired (1 day for fixtures)
                expires_at = cache_data.get("expires_at", 0)
                if expires_at > datetime.now().timestamp():
                    logger.info(f"Using cached fixtures for {date}")
                    fixtures = cache_data.get("data", [])
                    
                    # Save to database for future queries
                    await self.save_fixtures_to_db(fixtures, db)
                    
                    return fixtures
            except Exception as e:
                logger.error(f"Error reading cache: {str(e)}")

        # Check API call limit (100 calls per day for free tier)
        if self.api_calls >= 95:  # Leave some buffer
            logger.warning("API call limit approaching, using fallback data")
            return self._get_fallback_fixtures(date)

        # Build URL and parameters
        url = f"{self.base_url}/fixtures"
        params = {}
        if date:
            params["date"] = date
        if league_id:
            params["league"] = league_id
        if team_id:
            params["team"] = team_id

        # Make request
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    # Increment API call counter
                    self.api_calls += 1
                    
                    if response.status == 200:
                        data = await response.json()
                        fixtures = data.get("response", [])
                        
                        # Cache the response (expires in 1 day for fixtures)
                        cache_data = {
                            "data": fixtures,
                            "expires_at": (datetime.now() + timedelta(days=1)).timestamp()
                        }
                        
                        with open(cache_file, "w") as f:
                            json.dump(cache_data, f)
                        
                        logger.info(f"Fetched {len(fixtures)} fixtures for {date}")
                        
                        # Save to database for future queries
                        await self.save_fixtures_to_db(fixtures, db)
                        
                        return fixtures
                    else:
                        logger.error(f"Error fetching fixtures: {response.status}")
                        return self._get_fallback_fixtures(date)
        except Exception as e:
            logger.error(f"Exception fetching fixtures: {str(e)}")
            return self._get_fallback_fixtures(date)

    def _get_fixtures_from_db(self, db: Session, date: str, league_id: int = None, team_id: int = None) -> List[Dict[str, Any]]:
        """
        Get fixtures from the database.

        Args:
            db: Database session
            date: Date in format YYYY-MM-DD
            league_id: League ID
            team_id: Team ID

        Returns:
            List of fixtures
        """
        try:
            # Query fixtures from database
            query = db.query(Fixture).filter(Fixture.match_date.like(f"{date}%"))
            
            if league_id:
                # This would need a league_id column in the Fixture model
                # For now, we'll filter in Python
                fixtures = query.all()
                fixtures = [f for f in fixtures if f.additional_data.get("league", {}).get("id") == league_id]
            elif team_id:
                # This would need team_id columns in the Fixture model
                # For now, we'll filter in Python
                fixtures = query.all()
                fixtures = [f for f in fixtures if 
                           f.additional_data.get("teams", {}).get("home", {}).get("id") == team_id or
                           f.additional_data.get("teams", {}).get("away", {}).get("id") == team_id]
            else:
                fixtures = query.all()
            
            # Check if we have fixtures for this date
            if fixtures:
                # Convert to API format
                return [f.additional_data for f in fixtures]
            
            return []
        
        except Exception as e:
            logger.error(f"Error getting fixtures from database: {str(e)}")
            return []

    def _get_fallback_fixtures(self, date: str) -> List[Dict[str, Any]]:
        """
        Get fallback fixtures when API calls are limited.

        Args:
            date: Date in format YYYY-MM-DD

        Returns:
            List of fallback fixtures
        """
        # In a real implementation, this would return some default fixtures
        # For now, return an empty list
        logger.warning(f"Using fallback fixtures for {date}")
        return []

    async def save_fixtures_to_db(self, fixtures: List[Dict[str, Any]], db: Session) -> List[Fixture]:
        """
        Save fixtures to the database.

        Args:
            fixtures: List of fixtures from API
            db: Database session

        Returns:
            List of Fixture objects
        """
        fixture_objects = []
        
        for fixture_data in fixtures:
            try:
                # Extract fixture data
                fixture_id = str(fixture_data.get("fixture", {}).get("id"))
                league = fixture_data.get("league", {}).get("name")
                match_date = fixture_data.get("fixture", {}).get("date")
                home_team = fixture_data.get("teams", {}).get("home", {}).get("name")
                away_team = fixture_data.get("teams", {}).get("away", {}).get("name")
                status = fixture_data.get("fixture", {}).get("status", {}).get("short")
                
                # Check if fixture already exists
                existing_fixture = db.query(Fixture).filter(Fixture.external_id == fixture_id).first()
                
                if existing_fixture:
                    # Update existing fixture
                    existing_fixture.status = status
                    existing_fixture.updated_at = datetime.utcnow()
                    existing_fixture.additional_data = fixture_data
                    fixture_objects.append(existing_fixture)
                else:
                    # Create new fixture
                    new_fixture = Fixture(
                        external_id=fixture_id,
                        home_team=home_team,
                        away_team=away_team,
                        league=league,
                        match_date=match_date,
                        status=status,
                        source="api-football",
                        additional_data=fixture_data
                    )
                    db.add(new_fixture)
                    fixture_objects.append(new_fixture)
            
            except Exception as e:
                logger.error(f"Error saving fixture to database: {str(e)}")
        
        # Commit changes
        db.commit()
        
        logger.info(f"Saved {len(fixture_objects)} fixtures to database")
        return fixture_objects

    async def get_team_statistics(self, db: Session, team_id: int, league_id: int, season: str) -> Dict[str, Any]:
        """
        Get team statistics for a specific team, league, and season.
        Implements caching to minimize API calls.

        Args:
            db: Database session
            team_id: Team ID
            league_id: League ID
            season: Season (e.g., "2023")

        Returns:
            Team statistics
        """
        # Build cache key
        cache_key = f"team_stats_{team_id}_{league_id}_{season}"
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        
        # Check cache
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cache_data = json.load(f)
                
                # Check if cache is expired (7 days for team stats)
                expires_at = cache_data.get("expires_at", 0)
                if expires_at > datetime.now().timestamp():
                    logger.info(f"Using cached team statistics for team {team_id}")
                    return cache_data.get("data", {})
            except Exception as e:
                logger.error(f"Error reading cache: {str(e)}")
        
        # Check API call limit
        if self.api_calls >= 95:  # Leave some buffer
            logger.warning("API call limit approaching, using fallback data")
            return {}

        # Build URL and parameters
        url = f"{self.base_url}/teams/statistics"
        params = {
            "team": team_id,
            "league": league_id,
            "season": season
        }

        # Make request
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    # Increment API call counter
                    self.api_calls += 1
                    
                    if response.status == 200:
                        data = await response.json()
                        stats = data.get("response", {})
                        
                        # Cache the response (expires in 7 days for team stats)
                        cache_data = {
                            "data": stats,
                            "expires_at": (datetime.now() + timedelta(days=7)).timestamp()
                        }
                        
                        with open(cache_file, "w") as f:
                            json.dump(cache_data, f)
                        
                        logger.info(f"Fetched statistics for team {team_id}")
                        return stats
                    else:
                        logger.error(f"Error fetching team statistics: {response.status}")
                        return {}
        except Exception as e:
            logger.error(f"Exception fetching team statistics: {str(e)}")
            return {}

# Create a singleton instance
api_football_client = APIFootballClient()
