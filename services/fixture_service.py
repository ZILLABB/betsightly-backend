"""
Fixture Service — fetches today's/tomorrow's fixtures from The Odds API.

Replaces API-Football for live fixtures.  The Odds API returns upcoming
events (matches) for each sport key along with their odds, so we get
fixtures + odds in a single call.

The service:
  1. Fetches upcoming events from The Odds API for all mapped leagues
  2. Resolves team names to match our training data (via TeamNameResolver)
  3. Returns fixtures in the same format the ML pipeline expects
  4. Caches results to avoid repeated API calls within the same day
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from services.team_name_resolver import TeamNameResolver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path("cache/fixtures")
CACHE_TTL_HOURS = 4  # Fixtures don't change as often as odds

# Map our internal league IDs to The Odds API sport keys
LEAGUE_SPORT_KEYS: Dict[int, str] = {
    # ── European top flights ──
    39:  "soccer_epl",
    40:  "soccer_efl_champ",
    61:  "soccer_france_ligue_one",
    62:  "soccer_france_ligue_two",
    78:  "soccer_germany_bundesliga",
    79:  "soccer_germany_bundesliga2",
    135: "soccer_italy_serie_a",
    136: "soccer_italy_serie_b",
    140: "soccer_spain_la_liga",
    141: "soccer_spain_segunda_division",
    94:  "soccer_portugal_primeira_liga",
    88:  "soccer_netherlands_eredivisie",
    144: "soccer_belgium_first_div",
    203: "soccer_turkey_super_league",
    179: "soccer_spl",
    # ── European cups ──
    2:   "soccer_uefa_champs_league",
    3:   "soccer_uefa_europa_league",
    848: "soccer_uefa_europa_conference_league",
    # ── Americas ──
    253: "soccer_usa_mls",
    71:  "soccer_brazil_campeonato",
    128: "soccer_argentina_primera_division",
    262: "soccer_mexico_ligamx",
    265: "soccer_chile_campeonato",
    # ── Copa competitions ──
    13:  "soccer_conmebol_copa_libertadores",
    11:  "soccer_conmebol_copa_sudamericana",
    # ── Nordic / Summer ──
    103: "soccer_norway_eliteserien",
    113: "soccer_sweden_allsvenskan",
    244: "soccer_finland_veikkausliiga",
    119: "soccer_denmark_superliga",
    # ── Asia ──
    98:  "soccer_japan_j_league",
    292: "soccer_korea_kleague1",
    307: "soccer_saudi_professional_league",
    # ── World Cup ──
    1:   "soccer_fifa_world_cup",
}

# Reverse: sport_key -> league_id
SPORT_KEY_TO_LEAGUE: Dict[str, int] = {v: k for k, v in LEAGUE_SPORT_KEYS.items()}

# League metadata (for fixture response)
LEAGUE_META: Dict[int, Dict[str, Any]] = {
    39:  {"name": "Premier League",   "country": "England",   "tier": 1},
    40:  {"name": "Championship",     "country": "England",   "tier": 2},
    61:  {"name": "Ligue 1",          "country": "France",    "tier": 1},
    62:  {"name": "Ligue 2",          "country": "France",    "tier": 2},
    78:  {"name": "Bundesliga",       "country": "Germany",   "tier": 1},
    79:  {"name": "2. Bundesliga",    "country": "Germany",   "tier": 2},
    135: {"name": "Serie A",          "country": "Italy",     "tier": 1},
    136: {"name": "Serie B",          "country": "Italy",     "tier": 2},
    140: {"name": "La Liga",          "country": "Spain",     "tier": 1},
    141: {"name": "Segunda Division", "country": "Spain",     "tier": 2},
    94:  {"name": "Primeira Liga",    "country": "Portugal",  "tier": 1},
    88:  {"name": "Eredivisie",       "country": "Netherlands", "tier": 1},
    144: {"name": "Pro League",       "country": "Belgium",   "tier": 1},
    203: {"name": "Super Lig",        "country": "Turkey",    "tier": 1},
    179: {"name": "Premiership",      "country": "Scotland",  "tier": 1},
    197: {"name": "Super League",     "country": "Greece",    "tier": 1},
    2:   {"name": "Champions League", "country": "Europe",    "tier": 0},
    3:   {"name": "Europa League",    "country": "Europe",    "tier": 0},
    848: {"name": "Conference League", "country": "Europe",   "tier": 0},
    253: {"name": "MLS",              "country": "USA",       "tier": 1},
    71:  {"name": "Serie A",          "country": "Brazil",    "tier": 1},
    128: {"name": "Primera Division", "country": "Argentina", "tier": 1},
    262: {"name": "Liga MX",          "country": "Mexico",    "tier": 1},
    265: {"name": "Primera Division", "country": "Chile",     "tier": 1},
    13:  {"name": "Copa Libertadores", "country": "South America", "tier": 0},
    11:  {"name": "Copa Sudamericana", "country": "South America", "tier": 0},
    103: {"name": "Eliteserien",      "country": "Norway",    "tier": 1},
    113: {"name": "Allsvenskan",      "country": "Sweden",    "tier": 1},
    244: {"name": "Veikkausliiga",    "country": "Finland",   "tier": 1},
    119: {"name": "Superliga",        "country": "Denmark",   "tier": 1},
    98:  {"name": "J1 League",        "country": "Japan",     "tier": 1},
    292: {"name": "K League 1",       "country": "South Korea", "tier": 1},
    307: {"name": "Pro League",       "country": "Saudi Arabia", "tier": 1},
    1:   {"name": "World Cup",        "country": "International", "tier": 0},
}


class FixtureService:
    """Fetches upcoming fixtures from The Odds API with team name resolution."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or ODDS_API_KEY
        self.cache_dir = CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.resolver = TeamNameResolver()
        self.remaining_credits = "?"

        if not self.api_key:
            logger.warning("ODDS_API_KEY not set — fixture fetching disabled")

    def get_daily_fixtures(self, date: str = None) -> List[Dict[str, Any]]:
        """Get fixtures for today (or a specific date).

        Returns fixtures in the format the ML pipeline expects:
        {
            "fixture_id": <int>,
            "home_team": "Man United",      # Resolved to training data name
            "away_team": "Arsenal",
            "league_name": "Premier League",
            "league_id": 39,
            "league_tier": 1,
            "date": "2026-06-08T15:00:00Z",
            "status": "NS",
            "home_team_logo": "",
            "away_team_logo": "",
            "odds": { "home": 2.10, "draw": 3.40, "away": 3.60 }
        }
        """
        if not self.api_key:
            logger.error("Cannot fetch fixtures: no ODDS_API_KEY")
            return []

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        # Check cache first
        cached = self._read_cache(date)
        if cached is not None:
            logger.info(f"Fixture cache hit for {date}: {len(cached)} fixtures")
            return cached

        # Fetch from all active sport keys
        logger.info(f"Fetching fixtures for {date} from The Odds API...")
        all_fixtures = []
        sport_keys_fetched = 0

        # Only fetch from sport keys that are currently active (saves credits)
        active_keys = self._get_active_sport_keys()
        if not active_keys:
            # Fallback: try all mapped keys
            active_keys = set(LEAGUE_SPORT_KEYS.values())

        for sport_key in sorted(active_keys):
            if sport_key not in SPORT_KEY_TO_LEAGUE:
                continue  # Skip non-football or unmapped sports
            fixtures = self._fetch_sport_events(sport_key, date)
            if fixtures:
                all_fixtures.extend(fixtures)
            sport_keys_fetched += 1

        logger.info(
            f"Fetched {len(all_fixtures)} fixtures from {sport_keys_fetched} sport keys "
            f"(credits remaining: {self.remaining_credits})"
        )

        # Cache results
        if all_fixtures:
            self._write_cache(date, all_fixtures)

        return all_fixtures

    def _get_active_sport_keys(self) -> set:
        """Get currently active soccer sport keys (costs 0 credits)."""
        try:
            resp = requests.get(
                f"{ODDS_BASE_URL}/sports/",
                params={"apiKey": self.api_key, "all": "false"},
                timeout=15,
            )
            if resp.status_code != 200:
                return set()
            sports = resp.json()
            active = {s["key"] for s in sports
                      if s.get("group") == "Soccer" and s.get("active")}
            logger.info(f"Active soccer sports: {len(active)}")
            return active
        except Exception as e:
            logger.warning(f"Could not get active sports: {e}")
            return set()

    def _fetch_sport_events(self, sport_key: str, target_date: str) -> List[Dict]:
        """Fetch events for one sport key, filtered to target date window."""
        league_id = SPORT_KEY_TO_LEAGUE.get(sport_key, 0)
        meta = LEAGUE_META.get(league_id, {"name": sport_key, "country": "", "tier": 1})

        try:
            url = f"{ODDS_BASE_URL}/sports/{sport_key}/odds/"
            params = {
                "apiKey": self.api_key,
                "regions": "uk,eu",
                "markets": "h2h,totals",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }

            resp = requests.get(url, params=params, timeout=30)

            # Track credits
            self.remaining_credits = resp.headers.get("x-requests-remaining", "?")

            if resp.status_code in (404, 422):
                return []  # Sport not in season
            if resp.status_code == 429:
                logger.warning("Odds API rate limited!")
                return []
            if resp.status_code == 401:
                logger.error("Odds API: Invalid API key!")
                return []
            if resp.status_code != 200:
                logger.warning(f"Odds API {resp.status_code} for {sport_key}")
                return []

            events = resp.json()
            if not events:
                return []

            # Date window: today + tomorrow (accounts for timezone differences)
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            window_start = target_dt.date()
            window_end = (target_dt + timedelta(days=2)).date()

            fixtures = []
            for event in events:
                commence = event.get("commence_time", "")
                if not commence:
                    continue

                try:
                    event_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                    event_date = event_dt.date()
                except (ValueError, TypeError):
                    continue

                if not (window_start <= event_date <= window_end):
                    continue

                # Resolve team names
                home_raw = event.get("home_team", "")
                away_raw = event.get("away_team", "")
                home_resolved = self.resolver.resolve(home_raw)
                away_resolved = self.resolver.resolve(away_raw)

                home_team = home_resolved or home_raw
                away_team = away_resolved or away_raw

                # Stable fixture ID
                fixture_id = int(hashlib.md5(
                    f"{sport_key}_{home_raw}_{away_raw}_{commence}".encode()
                ).hexdigest()[:8], 16)

                # Extract odds
                odds = self._extract_event_odds(event)

                fixture = {
                    "fixture_id": fixture_id,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_team_raw": home_raw,
                    "away_team_raw": away_raw,
                    "league_name": meta["name"],
                    "league_id": league_id,
                    "league_tier": meta.get("tier", 1),
                    "country": meta.get("country", ""),
                    "date": commence,
                    "status": "NS",
                    "home_team_logo": "",
                    "away_team_logo": "",
                    "odds": odds,
                    "_name_resolved": {
                        "home": home_resolved is not None,
                        "away": away_resolved is not None,
                    },
                }
                fixtures.append(fixture)

            return fixtures

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching {sport_key}")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error for {sport_key}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching {sport_key}: {e}")
            return []

    def _extract_event_odds(self, event: Dict) -> Dict[str, Any]:
        """Extract odds from an Odds API event."""
        odds = {"home": None, "draw": None, "away": None,
                "over_2_5": None, "under_2_5": None, "bookmaker": None}

        bookmakers = event.get("bookmakers", [])
        if not bookmakers:
            return odds

        # Prefer pinnacle (sharpest), then bet365, then first available
        preferred = ["pinnacle", "bet365", "williamhill", "unibet"]
        selected = None
        for pref in preferred:
            for bk in bookmakers:
                if bk.get("key") == pref:
                    selected = bk
                    break
            if selected:
                break
        if not selected:
            selected = bookmakers[0]

        odds["bookmaker"] = selected.get("title", "")

        for market in selected.get("markets", []):
            if market.get("key") == "h2h":
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "")
                    price = outcome.get("price", 0)
                    if name == event.get("home_team"):
                        odds["home"] = price
                    elif name == event.get("away_team"):
                        odds["away"] = price
                    elif name.lower() == "draw":
                        odds["draw"] = price

            elif market.get("key") in ("totals", "alternate_totals"):
                for outcome in market.get("outcomes", []):
                    point = outcome.get("point", 0)
                    if point == 2.5:
                        name = outcome.get("name", "").lower()
                        price = outcome.get("price", 0)
                        if name == "over" and odds["over_2_5"] is None:
                            odds["over_2_5"] = price
                        elif name == "under" and odds["under_2_5"] is None:
                            odds["under_2_5"] = price

        return odds

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def _read_cache(self, date: str) -> Optional[List]:
        path = self.cache_dir / f"fixtures_{date}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            cached_at = datetime.fromisoformat(cached["cached_at"])
            if datetime.now() - cached_at > timedelta(hours=CACHE_TTL_HOURS):
                path.unlink(missing_ok=True)
                return None
            return cached["fixtures"]
        except Exception:
            return None

    def _write_cache(self, date: str, fixtures: List):
        path = self.cache_dir / f"fixtures_{date}.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "cached_at": datetime.now().isoformat(),
                    "date": date,
                    "fixtures": fixtures,
                }, f)
        except Exception as e:
            logger.debug(f"Cache write failed: {e}")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """Test API connection and show credits."""
        if not self.api_key:
            print("ODDS_API_KEY not set")
            return False
        try:
            resp = requests.get(
                f"{ODDS_BASE_URL}/sports/",
                params={"apiKey": self.api_key},
                timeout=15,
            )
            if resp.status_code == 401:
                print("Invalid ODDS_API_KEY")
                return False
            remaining = resp.headers.get("x-requests-remaining", "?")
            used = resp.headers.get("x-requests-used", "?")
            sports = resp.json()
            soccer_sports = [s for s in sports if s.get("group") == "Soccer" and s.get("active")]
            print(f"Connected! {remaining} credits remaining ({used} used)")
            print(f"Active soccer leagues: {len(soccer_sports)}")
            for s in soccer_sports[:10]:
                print(f"  {s['key']}: {s['title']}")
            if len(soccer_sports) > 10:
                print(f"  ... and {len(soccer_sports) - 10} more")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
