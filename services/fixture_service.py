"""
Fixture Service — fetches today's/tomorrow's fixtures.

Two-tier strategy to minimise Odds API credit usage:
  1. **football-data.org** (FREE, 0 credits) — primary source for fixtures
  2. **The Odds API** (costs credits) — fallback, and the ONLY source for odds

Credit budget (free tier = 500/month):
  - Priority mode (default): only 6-8 sport keys → 6-8 credits per cycle
  - Full mode: all active sport keys → ~30 credits per cycle
  - With priority mode + 12h cache → ~8 credits/day → 62 days of headroom

Caching: file-based with 12-hour TTL.  On Render the filesystem is
ephemeral, so after a deploy the first request will refetch (once).
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

FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_KEY", "")
FOOTBALL_DATA_URL = "https://api.football-data.org/v4"

CACHE_DIR = Path("cache/fixtures")
CACHE_TTL_HOURS = 12  # Fixtures don't change often — 12h is safe

# ---------------------------------------------------------------------------
# Priority leagues — fetched first (low credit cost, high value)
# These are the leagues most likely to have games + most popular for betting
# ---------------------------------------------------------------------------
PRIORITY_SPORT_KEYS = [
    "soccer_epl",                   # Premier League
    "soccer_spain_la_liga",          # La Liga
    "soccer_germany_bundesliga",     # Bundesliga
    "soccer_italy_serie_a",          # Serie A
    "soccer_france_ligue_one",       # Ligue 1
    "soccer_usa_mls",               # MLS (summer league)
    "soccer_brazil_campeonato",      # Brasileirão (year-round)
    "soccer_uefa_champs_league",     # Champions League
]

# Secondary leagues — only fetched in full mode
SECONDARY_SPORT_KEYS = [
    "soccer_efl_champ",
    "soccer_france_ligue_two",
    "soccer_germany_bundesliga2",
    "soccer_italy_serie_b",
    "soccer_spain_segunda_division",
    "soccer_portugal_primeira_liga",
    "soccer_netherlands_eredivisie",
    "soccer_belgium_first_div",
    "soccer_turkey_super_league",
    "soccer_spl",
    "soccer_argentina_primera_division",
    "soccer_mexico_ligamx",
    "soccer_chile_campeonato",
    "soccer_conmebol_copa_libertadores",
    "soccer_conmebol_copa_sudamericana",
    "soccer_norway_eliteserien",
    "soccer_sweden_allsvenskan",
    "soccer_finland_veikkausliiga",
    "soccer_denmark_superliga",
    "soccer_japan_j_league",
    "soccer_korea_kleague1",
    "soccer_saudi_professional_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_fifa_world_cup",
]

# Map our internal league IDs to The Odds API sport keys
LEAGUE_SPORT_KEYS: Dict[int, str] = {
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
    2:   "soccer_uefa_champs_league",
    3:   "soccer_uefa_europa_league",
    848: "soccer_uefa_europa_conference_league",
    253: "soccer_usa_mls",
    71:  "soccer_brazil_campeonato",
    128: "soccer_argentina_primera_division",
    262: "soccer_mexico_ligamx",
    265: "soccer_chile_campeonato",
    13:  "soccer_conmebol_copa_libertadores",
    11:  "soccer_conmebol_copa_sudamericana",
    103: "soccer_norway_eliteserien",
    113: "soccer_sweden_allsvenskan",
    244: "soccer_finland_veikkausliiga",
    119: "soccer_denmark_superliga",
    98:  "soccer_japan_j_league",
    292: "soccer_korea_kleague1",
    307: "soccer_saudi_professional_league",
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

# football-data.org competition codes → our league IDs
FDO_COMPETITION_MAP = {
    "PL":  39,   # Premier League
    "ELC": 40,   # Championship
    "BL1": 78,   # Bundesliga
    "PD":  140,  # La Liga
    "SA":  135,  # Serie A
    "FL1": 61,   # Ligue 1
    "DED": 88,   # Eredivisie
    "PPL": 94,   # Primeira Liga
    "CL":  2,    # Champions League
    "EL":  3,    # Europa League
    "CLI": 848,  # Conference League
    "BSA": 71,   # Brasileirao
    "WC":  1,    # World Cup
    "EC":  4,    # European Championship
}


class FixtureService:
    """Fetches upcoming fixtures with team name resolution.

    Tries football-data.org first (free), falls back to The Odds API.
    """

    def __init__(self, api_key: str = None):
        self.odds_api_key = api_key or ODDS_API_KEY
        self.fdo_api_key = FOOTBALL_DATA_KEY
        self.cache_dir = CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.resolver = TeamNameResolver()
        self.remaining_credits = "?"
        self._credits_checked = False

        if not self.odds_api_key and not self.fdo_api_key:
            logger.warning("No fixture API keys set (ODDS_API_KEY / FOOTBALL_DATA_KEY)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_daily_fixtures(self, date: str = None, mode: str = "priority") -> List[Dict[str, Any]]:
        """Get fixtures for today (or a specific date).

        Args:
            date: YYYY-MM-DD (default: today)
            mode: "priority" (6-8 credits) or "full" (all leagues, ~30 credits)

        Returns list of fixtures in standard format for the ML pipeline.
        """
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        # Check cache first (survives within same Render instance)
        cached = self._read_cache(date)
        if cached is not None:
            logger.info(f"Fixture cache hit for {date}: {len(cached)} fixtures")
            return cached

        logger.info(f"Fetching fixtures for {date} (mode={mode})...")
        all_fixtures = []

        # --- Tier 1: football-data.org (FREE, 0 credits) ---
        if self.fdo_api_key:
            fdo_fixtures = self._fetch_from_football_data_org(date)
            if fdo_fixtures:
                all_fixtures.extend(fdo_fixtures)
                logger.info(f"football-data.org: {len(fdo_fixtures)} fixtures (FREE)")

        # --- Tier 2: The Odds API (costs credits, but has odds) ---
        if self.odds_api_key:
            # Only fetch sport keys that are actually active (0 credits)
            active_keys = self._get_active_sport_keys()

            # Decide which keys to fetch based on mode
            if mode == "priority":
                keys_to_fetch = [k for k in PRIORITY_SPORT_KEYS if k in active_keys]
            else:
                keys_to_fetch = [k for k in (PRIORITY_SPORT_KEYS + SECONDARY_SPORT_KEYS)
                                 if k in active_keys]

            # Skip keys where we already have fixtures from football-data.org
            fdo_league_ids = {f["league_id"] for f in all_fixtures}
            keys_to_fetch = [
                k for k in keys_to_fetch
                if SPORT_KEY_TO_LEAGUE.get(k, 0) not in fdo_league_ids
            ]

            if keys_to_fetch:
                logger.info(
                    f"Odds API: fetching {len(keys_to_fetch)} sport keys "
                    f"(skipped {len(fdo_league_ids)} leagues already from football-data.org)"
                )
                for sport_key in keys_to_fetch:
                    if sport_key not in SPORT_KEY_TO_LEAGUE:
                        continue
                    fixtures = self._fetch_sport_events(sport_key, date)
                    if fixtures:
                        all_fixtures.extend(fixtures)
            else:
                logger.info("All priority leagues already covered by football-data.org")

        if not all_fixtures:
            logger.warning(f"No fixtures found for {date}")
            # Log diagnostics
            if not self.odds_api_key and not self.fdo_api_key:
                logger.error("No API keys set! Set ODDS_API_KEY or FOOTBALL_DATA_KEY")
            elif not self.odds_api_key:
                logger.info("Only football-data.org configured (no Odds API)")
            elif not self.fdo_api_key:
                logger.info("Only Odds API configured (no football-data.org)")

        logger.info(
            f"Total: {len(all_fixtures)} fixtures "
            f"(Odds API credits remaining: {self.remaining_credits})"
        )

        # Cache results
        if all_fixtures:
            self._write_cache(date, all_fixtures)

        return all_fixtures

    # ------------------------------------------------------------------
    # football-data.org (FREE)
    # ------------------------------------------------------------------

    def _fetch_from_football_data_org(self, target_date: str) -> List[Dict]:
        """Fetch today's matches from football-data.org (FREE, no credits).

        Free tier covers: PL, BL1, PD, SA, FL1, ELC, DED, PPL, CL, EL, BSA, WC
        Rate limit: 10 requests/minute
        """
        if not self.fdo_api_key:
            return []

        try:
            headers = {"X-Auth-Token": self.fdo_api_key}
            # Fetch matches for target date + next day (timezone coverage)
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            end_dt = target_dt + timedelta(days=1)
            params = {
                "dateFrom": target_date,
                "dateTo": end_dt.strftime("%Y-%m-%d"),
            }

            resp = requests.get(
                f"{FOOTBALL_DATA_URL}/matches",
                headers=headers,
                params=params,
                timeout=20,
            )

            if resp.status_code == 429:
                logger.warning("football-data.org rate limited — will use Odds API")
                return []
            if resp.status_code == 403:
                logger.warning("football-data.org: invalid API key or restricted")
                return []
            if resp.status_code != 200:
                logger.warning(f"football-data.org HTTP {resp.status_code}")
                return []

            data = resp.json()
            matches = data.get("matches", [])
            if not matches:
                return []

            fixtures = []
            for match in matches:
                # Only take scheduled/timed matches (not finished)
                status = match.get("status", "")
                if status in ("FINISHED", "IN_PLAY", "PAUSED", "SUSPENDED", "POSTPONED", "CANCELLED"):
                    continue

                comp = match.get("competition", {})
                comp_code = comp.get("code", "")
                league_id = FDO_COMPETITION_MAP.get(comp_code, 0)
                meta = LEAGUE_META.get(league_id, {
                    "name": comp.get("name", "Unknown"),
                    "country": match.get("area", {}).get("name", ""),
                    "tier": 1,
                })

                home_raw = match.get("homeTeam", {}).get("name", "Unknown")
                away_raw = match.get("awayTeam", {}).get("name", "Unknown")

                # Resolve team names to match training data
                home_resolved = self.resolver.resolve(home_raw)
                away_resolved = self.resolver.resolve(away_raw)
                home_team = home_resolved or home_raw
                away_team = away_resolved or away_raw

                commence = match.get("utcDate", "")

                # Stable fixture ID
                fixture_id = int(hashlib.md5(
                    f"fdo_{home_raw}_{away_raw}_{commence}".encode()
                ).hexdigest()[:8], 16)

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
                    "odds": {"home": None, "draw": None, "away": None,
                             "over_2_5": None, "under_2_5": None, "bookmaker": None},
                    "source": "football-data.org",
                    "_name_resolved": {
                        "home": home_resolved is not None,
                        "away": away_resolved is not None,
                    },
                }
                fixtures.append(fixture)

            logger.info(f"football-data.org: {len(fixtures)} upcoming fixtures from {len(matches)} total matches")
            return fixtures

        except requests.exceptions.Timeout:
            logger.warning("football-data.org timeout")
            return []
        except Exception as e:
            logger.error(f"football-data.org error: {e}")
            return []

    # ------------------------------------------------------------------
    # The Odds API (costs credits)
    # ------------------------------------------------------------------

    def _get_active_sport_keys(self) -> set:
        """Get currently active soccer sport keys (costs 0 credits)."""
        try:
            resp = requests.get(
                f"{ODDS_BASE_URL}/sports/",
                params={"apiKey": self.odds_api_key, "all": "false"},
                timeout=15,
            )
            if resp.status_code != 200:
                return set()

            # Track credits from this free call
            self.remaining_credits = resp.headers.get("x-requests-remaining", "?")
            self._credits_checked = True

            sports = resp.json()
            active = {s["key"] for s in sports
                      if s.get("group") == "Soccer" and s.get("active")}
            logger.info(f"Active soccer sports: {len(active)} (credits: {self.remaining_credits})")
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
                "apiKey": self.odds_api_key,
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
                    "source": "odds-api",
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
        has_any = False

        # Test football-data.org
        if self.fdo_api_key:
            try:
                resp = requests.get(
                    f"{FOOTBALL_DATA_URL}/competitions",
                    headers={"X-Auth-Token": self.fdo_api_key},
                    timeout=15,
                )
                if resp.status_code == 200:
                    comps = resp.json().get("competitions", [])
                    print(f"football-data.org: Connected! {len(comps)} competitions available")
                    has_any = True
                else:
                    print(f"football-data.org: HTTP {resp.status_code}")
            except Exception as e:
                print(f"football-data.org: {e}")

        # Test Odds API
        if self.odds_api_key:
            try:
                resp = requests.get(
                    f"{ODDS_BASE_URL}/sports/",
                    params={"apiKey": self.odds_api_key},
                    timeout=15,
                )
                if resp.status_code == 401:
                    print("Odds API: Invalid API key")
                elif resp.status_code == 200:
                    remaining = resp.headers.get("x-requests-remaining", "?")
                    used = resp.headers.get("x-requests-used", "?")
                    self.remaining_credits = remaining
                    sports = resp.json()
                    soccer_sports = [s for s in sports if s.get("group") == "Soccer" and s.get("active")]
                    print(f"Odds API: Connected! {remaining} credits remaining ({used} used)")
                    print(f"Active soccer: {len(soccer_sports)} leagues")
                    for s in soccer_sports[:10]:
                        print(f"  {s['key']}: {s['title']}")
                    if len(soccer_sports) > 10:
                        print(f"  ... and {len(soccer_sports) - 10} more")
                    has_any = True
            except Exception as e:
                print(f"Odds API: {e}")

        if not has_any:
            if not self.odds_api_key and not self.fdo_api_key:
                print("No API keys set! Set ODDS_API_KEY and/or FOOTBALL_DATA_KEY")
            return False

        return has_any

    def get_credit_status(self) -> Dict[str, Any]:
        """Check Odds API credit status without spending credits."""
        if not self.odds_api_key:
            return {"has_key": False, "remaining": 0, "used": 0}
        try:
            resp = requests.get(
                f"{ODDS_BASE_URL}/sports/",
                params={"apiKey": self.odds_api_key},
                timeout=15,
            )
            remaining = resp.headers.get("x-requests-remaining", "0")
            used = resp.headers.get("x-requests-used", "0")
            self.remaining_credits = remaining
            return {
                "has_key": True,
                "remaining": int(remaining) if remaining.isdigit() else 0,
                "used": int(used) if used.isdigit() else 0,
            }
        except Exception:
            return {"has_key": True, "remaining": -1, "used": -1}
