"""
APIFootball.com integration service for fetching football fixtures and data.
Temporary service for testing before potential permanent integration.
"""

import os
import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class APIFootballService:
    """Service for integrating with APIFootball.com API."""
    
    def __init__(self, api_key: str = None):
        """
        Initialize APIFootball service.
        
        Args:
            api_key: APIFootball.com API key
        """
        self.api_key = api_key or os.getenv("APIFOOTBALL_API_KEY", "")
        self.base_url = "https://apiv3.apifootball.com"
        self.timeout = 30
        
        if not self.api_key:
            logger.warning("⚠️  APIFootball API key not configured")
    
    def get_historical_matches(self, from_date: str, to_date: str, league_id: str = None) -> List[Dict[str, Any]]:
        """
        Get historical matches for training data.

        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            league_id: Optional league ID to filter results

        Returns:
            List of historical match dictionaries
        """
        try:
            logger.info(f"🔍 Fetching historical matches from {from_date} to {to_date}")

            url = f"{self.base_url}/"
            params = {
                "action": "get_events",
                "from": from_date,
                "to": to_date,
                "APIkey": self.api_key
            }

            if league_id:
                params["league_id"] = league_id
                logger.info(f"   📋 Filtering for league ID: {league_id}")

            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict) and "error" in data:
                logger.error(f"❌ APIFootball error: {data['error']}")
                return []

            matches = data if isinstance(data, list) else []

            # Filter for finished matches only (for training data)
            finished_matches = []
            finished_statuses = ['Finished', 'FT', 'AET', 'PEN']

            for match in matches:
                status = match.get('match_status', '')
                if status in finished_statuses:
                    # Ensure we have score data
                    home_score = match.get('match_hometeam_score', '')
                    away_score = match.get('match_awayteam_score', '')

                    if home_score != '' and away_score != '':
                        finished_matches.append(match)

            logger.info(f"✅ Retrieved {len(finished_matches)} finished matches from APIFootball.com")
            return self._convert_fixtures_to_standard_format(finished_matches)

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Network error fetching historical matches: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"❌ Error fetching historical matches: {str(e)}")
            return []

    def get_historical_matches(self, from_date: str, to_date: str, league_id: str = None) -> List[Dict[str, Any]]:
        """
        Get historical matches for training data.

        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            league_id: Optional league ID to filter results

        Returns:
            List of historical match dictionaries with scores
        """
        try:
            logger.info(f"🔍 Fetching historical matches from {from_date} to {to_date}")

            url = f"{self.base_url}/"
            params = {
                "action": "get_events",
                "from": from_date,
                "to": to_date,
                "APIkey": self.api_key
            }

            if league_id:
                params["league_id"] = league_id
                logger.info(f"   📋 Filtering for league ID: {league_id}")

            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict) and "error" in data:
                logger.error(f"❌ APIFootball error: {data['error']}")
                return []

            matches = data if isinstance(data, list) else []

            # Filter for finished matches only (for training data)
            finished_matches = []
            finished_statuses = ['Finished', 'FT', 'AET', 'PEN']

            for match in matches:
                status = match.get('match_status', '')
                if status in finished_statuses:
                    # Ensure we have score data
                    home_score = match.get('match_hometeam_score', '')
                    away_score = match.get('match_awayteam_score', '')

                    if home_score != '' and away_score != '' and home_score.isdigit() and away_score.isdigit():
                        finished_matches.append(match)

            logger.info(f"✅ Retrieved {len(finished_matches)} finished matches from APIFootball.com")
            return self._convert_historical_to_training_format(finished_matches)

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Network error fetching historical matches: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"❌ Error fetching historical matches: {str(e)}")
            return []

    def get_daily_fixtures(self, date: str = None) -> List[Dict[str, Any]]:
        """
        Get fixtures for a specific date.
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            List of fixture dictionaries
        """
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
            
        try:
            logger.info(f"🌐 Fetching fixtures from APIFootball.com for {date}")
            
            # APIFootball.com endpoint for fixtures by date
            url = f"{self.base_url}/"
            params = {
                "action": "get_events",
                "from": date,
                "to": date,
                "APIkey": self.api_key
            }
            
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            # APIFootball returns data directly as array or with error
            if isinstance(data, dict) and "error" in data:
                logger.error(f"❌ APIFootball error: {data['error']}")
                return []
            
            fixtures = data if isinstance(data, list) else []
            logger.info(f"✅ Fetched {len(fixtures)} fixtures from APIFootball.com")
            
            # Convert to standardized format
            return self._convert_fixtures_to_standard_format(fixtures)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Network error fetching fixtures: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"❌ Error fetching fixtures from APIFootball: {str(e)}")
            return []
    
    def get_fixtures_by_league(self, league_id: str, date: str = None) -> List[Dict[str, Any]]:
        """
        Get fixtures for a specific league.
        
        Args:
            league_id: League ID (e.g., "152" for Premier League)
            date: Date in YYYY-MM-DD format
            
        Returns:
            List of fixture dictionaries
        """
        try:
            logger.info(f"🌐 Fetching league {league_id} fixtures from APIFootball.com")
            
            url = f"{self.base_url}/"
            params = {
                "action": "get_events",
                "league_id": league_id,
                "APIkey": self.api_key
            }
            
            if date:
                params.update({"from": date, "to": date})
            
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            if isinstance(data, dict) and "error" in data:
                logger.error(f"❌ APIFootball error: {data['error']}")
                return []
            
            fixtures = data if isinstance(data, list) else []
            logger.info(f"✅ Fetched {len(fixtures)} league fixtures from APIFootball.com")
            
            return self._convert_fixtures_to_standard_format(fixtures)
            
        except Exception as e:
            logger.error(f"❌ Error fetching league fixtures: {str(e)}")
            return []
    
    def get_live_fixtures(self) -> List[Dict[str, Any]]:
        """
        Get currently live fixtures.
        
        Returns:
            List of live fixture dictionaries
        """
        try:
            logger.info("🔴 Fetching live fixtures from APIFootball.com")
            
            url = f"{self.base_url}/"
            params = {
                "action": "get_events",
                "match_live": "1",
                "APIkey": self.api_key
            }
            
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            if isinstance(data, dict) and "error" in data:
                logger.error(f"❌ APIFootball error: {data['error']}")
                return []
            
            fixtures = data if isinstance(data, list) else []
            logger.info(f"✅ Fetched {len(fixtures)} live fixtures from APIFootball.com")
            
            return self._convert_fixtures_to_standard_format(fixtures)
            
        except Exception as e:
            logger.error(f"❌ Error fetching live fixtures: {str(e)}")
            return []
    
    def get_leagues(self) -> List[Dict[str, Any]]:
        """
        Get available leagues.
        
        Returns:
            List of league dictionaries
        """
        try:
            logger.info("📋 Fetching leagues from APIFootball.com")
            
            url = f"{self.base_url}/"
            params = {
                "action": "get_leagues",
                "APIkey": self.api_key
            }
            
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            if isinstance(data, dict) and "error" in data:
                logger.error(f"❌ APIFootball error: {data['error']}")
                return []
            
            leagues = data if isinstance(data, list) else []
            logger.info(f"✅ Fetched {len(leagues)} leagues from APIFootball.com")
            
            return leagues
            
        except Exception as e:
            logger.error(f"❌ Error fetching leagues: {str(e)}")
            return []
    
    def _convert_fixtures_to_standard_format(self, fixtures: List[Dict]) -> List[Dict[str, Any]]:
        """
        Convert APIFootball fixtures to standardized format.
        
        Args:
            fixtures: Raw fixtures from APIFootball API
            
        Returns:
            Standardized fixture format
        """
        standardized_fixtures = []
        
        for fixture in fixtures:
            try:
                # Parse date
                match_date = fixture.get("match_date", "")
                match_time = fixture.get("match_time", "")
                
                # Combine date and time
                if match_date and match_time:
                    datetime_str = f"{match_date} {match_time}"
                    try:
                        parsed_date = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                    except ValueError:
                        parsed_date = datetime.now()
                else:
                    parsed_date = datetime.now()
                
                standardized_fixture = {
                    "fixture_id": int(fixture.get("match_id", 0)),
                    "date": parsed_date.isoformat(),
                    "league_id": int(fixture.get("league_id", 0)),
                    "league_name": fixture.get("league_name", "Unknown League"),
                    "home_team_id": int(fixture.get("match_hometeam_id", 0)),
                    "home_team": fixture.get("match_hometeam_name", "Unknown Home"),
                    "away_team_id": int(fixture.get("match_awayteam_id", 0)),
                    "away_team": fixture.get("match_awayteam_name", "Unknown Away"),
                    "home_odds": float(fixture.get("match_hometeam_score", 0)),
                    "draw_odds": 0.0,  # APIFootball doesn't provide odds in basic plan
                    "away_odds": float(fixture.get("match_awayteam_score", 0)),
                    "status": fixture.get("match_status", ""),
                    "round": fixture.get("match_round", ""),
                    "season": fixture.get("league_season", ""),
                    # Additional APIFootball specific fields
                    "country_name": fixture.get("country_name", ""),
                    "league_logo": fixture.get("league_logo", ""),
                    "home_team_logo": fixture.get("team_home_badge", ""),
                    "away_team_logo": fixture.get("team_away_badge", ""),
                }
                
                standardized_fixtures.append(standardized_fixture)
                
            except Exception as e:
                logger.warning(f"⚠️  Error converting fixture {fixture.get('match_id', 'unknown')}: {str(e)}")
                continue
        
        return standardized_fixtures

    def _convert_historical_to_training_format(self, matches: List[Dict]) -> List[Dict[str, Any]]:
        """
        Convert APIFootball historical matches to training data format.

        Args:
            matches: Raw historical matches from APIFootball API

        Returns:
            Training data format with match results and statistics
        """
        training_data = []

        for match in matches:
            try:
                # Parse scores
                home_score = int(match.get("match_hometeam_score", 0))
                away_score = int(match.get("match_awayteam_score", 0))
                total_goals = home_score + away_score

                # Parse date
                match_date = match.get("match_date", "")
                match_time = match.get("match_time", "")

                if match_date and match_time:
                    datetime_str = f"{match_date} {match_time}"
                    try:
                        parsed_date = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
                    except ValueError:
                        parsed_date = datetime.now()
                else:
                    parsed_date = datetime.now()

                # Create training record
                training_record = {
                    # Basic match info
                    "match_id": int(match.get("match_id", 0)),
                    "date": parsed_date.isoformat(),
                    "league_id": int(match.get("league_id", 0)),
                    "league_name": match.get("league_name", "Unknown League"),
                    "country_name": match.get("country_name", "Unknown"),

                    # Team info
                    "home_team_id": int(match.get("match_hometeam_id", 0)),
                    "home_team": match.get("match_hometeam_name", "Unknown Home"),
                    "away_team_id": int(match.get("match_awayteam_id", 0)),
                    "away_team": match.get("match_awayteam_name", "Unknown Away"),

                    # Match results (target variables)
                    "home_score": home_score,
                    "away_score": away_score,
                    "total_goals": total_goals,

                    # Match result outcomes
                    "match_result": "home_win" if home_score > away_score else
                                   "away_win" if away_score > home_score else "draw",

                    # Over/Under outcomes
                    "over_1_5": 1 if total_goals > 1.5 else 0,
                    "over_2_5": 1 if total_goals > 2.5 else 0,
                    "over_3_5": 1 if total_goals > 3.5 else 0,

                    # BTTS (Both Teams To Score)
                    "btts": 1 if home_score > 0 and away_score > 0 else 0,

                    # Clean sheets
                    "clean_sheet_home": 1 if away_score == 0 else 0,
                    "clean_sheet_away": 1 if home_score == 0 else 0,

                    # Win to nil
                    "win_to_nil_home": 1 if home_score > away_score and away_score == 0 else 0,
                    "win_to_nil_away": 1 if away_score > home_score and home_score == 0 else 0,

                    # Additional match info
                    "season": match.get("league_year", "Unknown"),
                    "round": match.get("match_round", ""),
                    "stadium": match.get("match_stadium", ""),

                    # Halftime scores if available
                    "home_ht_score": int(match.get("match_hometeam_halftime_score", 0)) if match.get("match_hometeam_halftime_score", "").isdigit() else 0,
                    "away_ht_score": int(match.get("match_awayteam_halftime_score", 0)) if match.get("match_awayteam_halftime_score", "").isdigit() else 0,
                }

                training_data.append(training_record)

            except Exception as e:
                logger.warning(f"⚠️  Error converting historical match {match.get('match_id', 'unknown')}: {str(e)}")
                continue

        return training_data
    
    def test_connection(self) -> bool:
        """
        Test the API connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info("🔍 Testing APIFootball.com connection...")
            
            url = f"{self.base_url}/"
            params = {
                "action": "get_leagues",
                "APIkey": self.api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if isinstance(data, dict) and "error" in data:
                logger.error(f"❌ APIFootball connection test failed: {data['error']}")
                return False
            
            logger.info("✅ APIFootball.com connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"❌ APIFootball connection test failed: {str(e)}")
            return False


# Convenience function for quick access
def get_apifootball_service() -> APIFootballService:
    """Get configured APIFootball service instance."""
    return APIFootballService()


# Test function
def test_apifootball_integration():
    """Test the APIFootball integration."""
    service = get_apifootball_service()
    
    print("🔍 Testing APIFootball.com integration...")
    
    # Test connection
    if not service.test_connection():
        print("❌ Connection test failed")
        return False
    
    # Test getting today's fixtures
    fixtures = service.get_daily_fixtures()
    print(f"📅 Found {len(fixtures)} fixtures for today")
    
    if fixtures:
        print("📋 Sample fixture:")
        print(f"   {fixtures[0]['home_team']} vs {fixtures[0]['away_team']}")
        print(f"   League: {fixtures[0]['league_name']}")
        print(f"   Date: {fixtures[0]['date']}")
    
    # Test getting leagues
    leagues = service.get_leagues()
    print(f"🏆 Found {len(leagues)} leagues")
    
    if leagues:
        print("📋 Sample leagues:")
        for league in leagues[:5]:
            print(f"   {league.get('league_name', 'Unknown')} ({league.get('country_name', 'Unknown')})")
    
    return True


if __name__ == "__main__":
    test_apifootball_integration()
