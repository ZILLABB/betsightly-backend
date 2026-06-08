"""
Team Name Resolver — maps external API team names to our training data names.

The ML pipeline does EXACT string lookups in matches.csv, so incoming fixture
names must match precisely.  This module handles the mismatch between:
  - The Odds API names  (e.g., "Manchester United", "Atletico Madrid")
  - football-data.co.uk names (e.g., "Man United", "Ath Madrid")

Strategy:
  1. Build a lookup of all known team names from matches.csv (loaded once)
  2. Try exact match first (fast path)
  3. Try a static alias table for known tricky names
  4. Fall back to fuzzy matching (word overlap + substring)
  5. Cache resolved names for the session (same fixture source won't change names)
"""

import csv
import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

MATCHES_CSV = Path("data/api-football/matches.csv")

# ---------------------------------------------------------------------------
# Static alias table: Odds API name -> football-data.co.uk name
# This handles abbreviations and style differences that fuzzy matching can't.
# ---------------------------------------------------------------------------
ALIASES: Dict[str, str] = {
    # ── England ──
    "manchester united": "Man United",
    "manchester city": "Man City",
    "nottingham forest": "Nott'm Forest",
    "wolverhampton wanderers": "Wolves",
    "wolverhampton": "Wolves",
    "newcastle united": "Newcastle",
    "tottenham hotspur": "Tottenham",
    "tottenham": "Tottenham",
    "west ham united": "West Ham",
    "leicester city": "Leicester",
    "afc bournemouth": "Bournemouth",
    "brighton and hove albion": "Brighton",
    "brighton & hove albion": "Brighton",
    "ipswich town": "Ipswich",
    "sheffield united": "Sheffield United",
    "luton town": "Luton",
    "leeds united": "Leeds",
    "sunderland afc": "Sunderland",
    # ── Spain ──
    "atletico madrid": "Ath Madrid",
    "atletico de madrid": "Ath Madrid",
    "athletic bilbao": "Ath Bilbao",
    "athletic club": "Ath Bilbao",
    "real betis": "Betis",
    "real sociedad": "Sociedad",
    "celta vigo": "Celta",
    "celta de vigo": "Celta",
    "deportivo alaves": "Alaves",
    "rayo vallecano": "Vallecano",
    "ca osasuna": "Osasuna",
    "real valladolid": "Valladolid",
    "cd leganes": "Leganes",
    "girona fc": "Girona",
    "getafe cf": "Getafe",
    "valencia cf": "Valencia",
    "villarreal cf": "Villarreal",
    "real mallorca": "Mallorca",
    "ud las palmas": "Las Palmas",
    "sevilla fc": "Sevilla",
    "espanyol barcelona": "Espanol",
    "rcd espanyol": "Espanol",
    "cadiz cf": "Cadiz",
    "almeria": "Almeria",
    # ── Germany ──
    "eintracht frankfurt": "Ein Frankfurt",
    "borussia dortmund": "Dortmund",
    "bayer leverkusen": "Leverkusen",
    "borussia monchengladbach": "M'gladbach",
    "borussia moenchengladbach": "M'gladbach",
    "borussia m'gladbach": "M'gladbach",
    "rb leipzig": "RB Leipzig",
    "rasenballsport leipzig": "RB Leipzig",
    "vfb stuttgart": "Stuttgart",
    "fc cologne": "FC Koln",
    "1. fc koln": "FC Koln",
    "fc koeln": "FC Koln",
    "1. fc köln": "FC Koln",
    "bayern munich": "Bayern Munich",
    "fc bayern munich": "Bayern Munich",
    "sc freiburg": "Freiburg",
    "tsg hoffenheim": "Hoffenheim",
    "vfl wolfsburg": "Wolfsburg",
    "fc augsburg": "Augsburg",
    "1. fc heidenheim": "Heidenheim",
    "1. fc union berlin": "Union Berlin",
    "fc union berlin": "Union Berlin",
    "werder bremen": "Werder Bremen",
    "sv darmstadt 98": "Darmstadt",
    "vfl bochum": "Bochum",
    "mainz 05": "Mainz",
    "fsv mainz 05": "Mainz",
    "1. fsv mainz 05": "Mainz",
    "hertha berlin": "Hertha",
    "hertha bsc": "Hertha",
    "fc st. pauli": "St Pauli",
    "holstein kiel": "Holstein Kiel",
    # ── Italy ──
    "ac milan": "Milan",
    "inter milan": "Inter",
    "internazionale": "Inter",
    "fc internazionale": "Inter",
    "as roma": "Roma",
    "ss lazio": "Lazio",
    "ssc napoli": "Napoli",
    "juventus fc": "Juventus",
    "atalanta bc": "Atalanta",
    "us lecce": "Lecce",
    "us salernitana 1919": "Salernitana",
    "hellas verona": "Verona",
    "acf fiorentina": "Fiorentina",
    "torino fc": "Torino",
    "udinese calcio": "Udinese",
    "genoa cfc": "Genoa",
    "empoli fc": "Empoli",
    "us sassuolo calcio": "Sassuolo",
    "frosinone calcio": "Frosinone",
    "cagliari calcio": "Cagliari",
    "bologna fc": "Bologna",
    "como 1907": "Como",
    "ac monza": "Monza",
    "parma calcio 1913": "Parma",
    "venezia fc": "Venezia",
    # ── France ──
    "paris saint-germain": "Paris SG",
    "paris saint germain": "Paris SG",
    "paris sg": "Paris SG",
    "psg": "Paris SG",
    "olympique marseille": "Marseille",
    "olympique lyon": "Lyon",
    "olympique lyonnais": "Lyon",
    "as monaco": "Monaco",
    "stade rennais": "Rennes",
    "rc lens": "Lens",
    "losc lille": "Lille",
    "ogc nice": "Nice",
    "rc strasbourg alsace": "Strasbourg",
    "fc nantes": "Nantes",
    "stade brestois 29": "Brest",
    "stade de reims": "Reims",
    "toulouse fc": "Toulouse",
    "montpellier hsc": "Montpellier",
    "fc lorient": "Lorient",
    "clermont foot": "Clermont",
    "le havre ac": "Le Havre",
    "angers sco": "Angers",
    "as saint-etienne": "St Etienne",
    "aj auxerre": "Auxerre",
    # ── Portugal ──
    "fc porto": "Porto",
    "sl benfica": "Benfica",
    "sporting cp": "Sp Lisbon",
    "sporting lisbon": "Sp Lisbon",
    "sc braga": "Braga",
    "vitoria guimaraes": "Guimaraes",
    # ── Netherlands ──
    "ajax amsterdam": "Ajax",
    "psv eindhoven": "PSV Eindhoven",
    "feyenoord rotterdam": "Feyenoord",
    "az alkmaar": "AZ Alkmaar",
    "fc twente": "Twente",
    "fc utrecht": "Utrecht",
    # ── Scotland ──
    "celtic fc": "Celtic",
    "rangers fc": "Rangers",
    "heart of midlothian": "Hearts",
    "hearts": "Hearts",
    "hibernian fc": "Hibernian",
    "aberdeen fc": "Aberdeen",
    "dundee fc": "Dundee",
    "dundee united": "Dundee Utd",
    "motherwell fc": "Motherwell",
    "st mirren": "St Mirren",
    "st johnstone": "St Johnstone",
    "kilmarnock fc": "Kilmarnock",
    "ross county": "Ross County",
    "livingston fc": "Livingston",
    # ── Turkey ──
    "galatasaray sk": "Galatasaray",
    "fenerbahce sk": "Fenerbahce",
    "besiktas jk": "Besiktas",
    "trabzonspor": "Trabzonspor",
    # ── USA (MLS) ──
    "atlanta united fc": "Atlanta Utd",
    "atlanta united": "Atlanta Utd",
    "inter miami cf": "Inter Miami",
    "inter miami": "Inter Miami",
    "la galaxy": "Los Angeles Galaxy",
    "los angeles fc": "Los Angeles FC",
    "new york city fc": "New York City",
    "new york red bulls": "New York Red Bulls",
    "fc cincinnati": "FC Cincinnati",
    "fc dallas": "FC Dallas",
    "sporting kansas city": "Sporting Kansas City",
    "minnesota united fc": "Minnesota Utd",
    "minnesota united": "Minnesota Utd",
    "nashville sc": "Nashville",
    "austin fc": "Austin FC",
    "portland timbers": "Portland Timbers",
    "seattle sounders fc": "Seattle Sounders",
    "seattle sounders": "Seattle Sounders",
    "charlotte fc": "Charlotte",
    "st. louis city sc": "St Louis City",
    "st louis city sc": "St Louis City",
    "real salt lake": "Real Salt Lake",
    "columbus crew": "Columbus Crew",
    "cf montreal": "CF Montreal",
    "cf montréal": "CF Montreal",
    "chicago fire fc": "Chicago Fire",
    "d.c. united": "DC United",
    "dc united": "DC United",
    "houston dynamo fc": "Houston Dynamo",
    "houston dynamo": "Houston Dynamo",
    "new england revolution": "New England",
    "orlando city sc": "Orlando City",
    "orlando city": "Orlando City",
    "philadelphia union": "Philadelphia",
    "san jose earthquakes": "San Jose Earthquakes",
    "toronto fc": "Toronto FC",
    "vancouver whitecaps fc": "Vancouver Whitecaps",
    "vancouver whitecaps": "Vancouver Whitecaps",
    "colorado rapids": "Colorado Rapids",
    # ── Brazil ──
    "atletico mineiro": "Atletico-MG",
    "atlético mineiro": "Atletico-MG",
    "atletico paranaense": "Athletico-PR",
    "atlético paranaense": "Athletico-PR",
    "athletico paranaense": "Athletico-PR",
    "atletico goianiense": "Atletico GO",
    "botafogo fr": "Botafogo RJ",
    "botafogo": "Botafogo RJ",
    "flamengo": "Flamengo RJ",
    "cr flamengo": "Flamengo RJ",
    "fluminense fc": "Fluminense",
    "sao paulo fc": "Sao Paulo",
    "são paulo": "Sao Paulo",
    "sc corinthians": "Corinthians",
    "se palmeiras": "Palmeiras",
    "santos fc": "Santos",
    "gremio": "Gremio",
    "grêmio": "Gremio",
    "sport recife": "Sport Recife",
    "red bull bragantino": "Bragantino",
    "rb bragantino": "Bragantino",
    "america mineiro": "America MG",
    "américa mineiro": "America MG",
    "sc internacional": "Internacional",
    "internacional": "Internacional",
    "cruzeiro": "Cruzeiro",
    "fortaleza ec": "Fortaleza",
    "fortaleza": "Fortaleza",
    "ec bahia": "Bahia",
    "bahia": "Bahia",
    "cuiaba": "Cuiaba",
    "cuiabá": "Cuiaba",
    "goias": "Goias",
    "goiás": "Goias",
    "juventude": "Juventude",
    "coritiba fc": "Coritiba",
    "cr vasco da gama": "Vasco",
    "vasco da gama": "Vasco",
    # ── Argentina ──
    "boca juniors": "Boca Juniors",
    "river plate": "River Plate",
    "racing club": "Racing Club",
    "independiente": "Independiente",
    "san lorenzo": "San Lorenzo",
    "estudiantes de la plata": "Estudiantes LP",
    "velez sarsfield": "Velez Sarsfield",
    "vélez sarsfield": "Velez Sarsfield",
    "newells old boys": "Newells Old Boys",
    "newell's old boys": "Newells Old Boys",
    "rosario central": "Rosario Central",
    "argentinos juniors": "Argentinos Jrs",
    # ── Norway ──
    "rosenborg bk": "Rosenborg",
    "bodo/glimt": "Bodo Glimt",
    "bodø/glimt": "Bodo Glimt",
    "molde fk": "Molde",
    "sk brann": "Brann",
    "viking fk": "Viking",
    "valerenga": "Valerenga",
    "vålerenga": "Valerenga",
    "lillestrom": "Lillestrom",
    "lillestrøm": "Lillestrom",
    "stromsgodset": "Stromsgodset",
    "strømsgodset": "Stromsgodset",
    # ── Sweden ──
    "malmo ff": "Malmo FF",
    "malmö ff": "Malmo FF",
    "aik stockholm": "AIK",
    "djurgardens if": "Djurgarden",
    "djurgårdens if": "Djurgarden",
    "if elfsborg": "Elfsborg",
    "hammarby if": "Hammarby",
    "ik sirius": "Sirius",
    # ── Denmark ──
    "fc copenhagen": "FC Copenhagen",
    "fc midtjylland": "FC Midtjylland",
    "brondby if": "Brondby",
    "brøndby if": "Brondby",
    "aarhus gf": "Aarhus",
    # ── Japan ──
    "kawasaki frontale": "Kawasaki Frontale",
    "yokohama f. marinos": "Yokohama F Marinos",
    "yokohama f marinos": "Yokohama F Marinos",
    "urawa red diamonds": "Urawa Reds",
    "urawa reds": "Urawa Reds",
    "vissel kobe": "Vissel Kobe",
    "kashima antlers": "Kashima Antlers",
    "fc tokyo": "FC Tokyo",
    # ── Belgium ──
    "club brugge kv": "Club Brugge",
    "club brugge": "Club Brugge",
    "rsc anderlecht": "Anderlecht",
    "krc genk": "Genk",
    "royal antwerp fc": "Antwerp",
    "standard liege": "Standard",
    "standard liège": "Standard",
    "r. charleroi s.c.": "Charleroi",
    "sporting charleroi": "Charleroi",
    "oh leuven": "OH Leuven",
    "union saint-gilloise": "Union St. Gilloise",
    "union st. gilloise": "Union St. Gilloise",
    "union st.-gilloise": "Union St. Gilloise",
    "cercle brugge": "Cercle Brugge",
    # ── Greece ──
    "olympiacos piraeus": "Olympiakos",
    "olympiacos": "Olympiakos",
    "panathinaikos fc": "Panathinaikos",
    "paok thessaloniki": "PAOK",
    "paok": "PAOK",
    "aek athens": "AEK Athens",
    "aris thessaloniki": "Aris",
    # ── football-data.org Brazilian names ──
    "ca mineiro": "Atletico-MG",
    "sc corinthians paulista": "Corinthians",
    "coritiba fbc": "Coritiba",
    "mirassol fc": "Mirassol",
    "clube do remo": "Remo",
    "chapecoense af": "Chapecoense",
    "grêmio fbpa": "Gremio",
    "cruzeiro ec": "Cruzeiro",
}

# Lowercase the keys for fast lookup
ALIASES = {k.lower(): v for k, v in ALIASES.items()}

# National team names — these should NOT fuzzy-match to club teams.
# When the resolver sees one of these, it returns None (no match) rather
# than accidentally matching "England" → "New England Revolution", etc.
NATIONAL_TEAMS = {
    "england", "france", "spain", "italy", "germany", "brazil", "argentina",
    "portugal", "netherlands", "belgium", "scotland", "turkey", "greece",
    "switzerland", "austria", "sweden", "norway", "denmark", "finland",
    "poland", "romania", "czech republic", "czechia", "croatia", "serbia",
    "ukraine", "hungary", "ireland", "wales", "northern ireland",
    "united states", "usa", "canada", "mexico", "japan", "south korea",
    "australia", "qatar", "saudi arabia", "morocco", "south africa",
    "nigeria", "senegal", "cameroon", "ghana", "egypt", "tunisia",
    "colombia", "chile", "peru", "uruguay", "paraguay", "ecuador",
    "costa rica", "panama", "haiti", "jamaica",
    "bosnia-herzegovina", "bosnia and herzegovina", "north macedonia",
    "montenegro", "iceland", "albania", "slovakia", "slovenia",
    "curaçao", "curacao", "new zealand", "iran", "china", "india",
    "indonesia", "thailand", "vietnam",
}


class TeamNameResolver:
    """Resolves external API team names to training data names."""

    def __init__(self, csv_path: Path = MATCHES_CSV):
        self._known_teams: Set[str] = set()
        self._teams_lower: Dict[str, str] = {}  # lowercase -> original
        self._cache: Dict[str, Optional[str]] = {}  # resolved names cache
        self._load_teams(csv_path)

    def _load_teams(self, csv_path: Path):
        """Load all unique team names from matches.csv."""
        if not csv_path.exists():
            logger.warning(f"Cannot load teams: {csv_path} not found")
            return

        try:
            with open(csv_path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    self._known_teams.add(r["home_team"])
                    self._known_teams.add(r["away_team"])

            # Build lowercase lookup
            for team in self._known_teams:
                self._teams_lower[team.lower()] = team

            logger.info(f"TeamNameResolver: loaded {len(self._known_teams)} team names")
        except Exception as e:
            logger.error(f"Failed to load team names: {e}")

    def resolve(self, name: str) -> Optional[str]:
        """Resolve an external team name to our training data name.

        Returns the matched name, or None if no confident match found.
        """
        if not name:
            return None

        # Check cache
        cache_key = name.lower().strip()
        if cache_key in self._cache:
            return self._cache[cache_key]

        resolved = self._do_resolve(name)
        self._cache[cache_key] = resolved
        return resolved

    def _do_resolve(self, name: str) -> Optional[str]:
        """Internal resolution logic."""
        clean = name.strip()
        lower = clean.lower()

        # 0. National team guard — don't fuzzy-match country names to clubs
        if lower in NATIONAL_TEAMS:
            logger.debug(f"National team detected: '{name}' — skipping (club data only)")
            return None

        # 1. Exact match
        if clean in self._known_teams:
            return clean

        # 2. Case-insensitive exact match
        if lower in self._teams_lower:
            return self._teams_lower[lower]

        # 3. Static alias table
        if lower in ALIASES:
            alias = ALIASES[lower]
            # Verify it's actually in our data
            if alias in self._known_teams:
                return alias
            # Try case-insensitive
            if alias.lower() in self._teams_lower:
                return self._teams_lower[alias.lower()]

        # 4. Try stripping common suffixes/prefixes
        stripped = self._strip_noise(lower)
        if stripped in self._teams_lower:
            return self._teams_lower[stripped]

        # 5. Fuzzy match — word overlap
        best_score = 0.0
        best_match = None

        for known_lower, known_original in self._teams_lower.items():
            score = self._similarity(lower, known_lower)
            if score > best_score:
                best_score = score
                best_match = known_original

        # Only accept high-confidence fuzzy matches
        if best_score >= 0.75:
            logger.debug(f"Fuzzy resolved: '{name}' → '{best_match}' (score={best_score:.2f})")
            return best_match

        # 6. SequenceMatcher as last resort (catches typos, small variations)
        best_ratio = 0.0
        best_seq = None
        for known_lower, known_original in self._teams_lower.items():
            ratio = SequenceMatcher(None, lower, known_lower).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_seq = known_original

        if best_ratio >= 0.80:
            logger.debug(f"Seq resolved: '{name}' → '{best_seq}' (ratio={best_ratio:.2f})")
            return best_seq

        logger.warning(f"Could not resolve team name: '{name}'")
        return None

    @staticmethod
    def _strip_noise(name: str) -> str:
        """Strip common prefixes/suffixes."""
        noise_suffixes = [" fc", " cf", " sc", " ac", " afc", " bk", " fk",
                          " if", " sk", " ff"]
        noise_prefixes = ["fc ", "cf ", "sc ", "ac ", "afc "]

        for suffix in noise_suffixes:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break

        for prefix in noise_prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break

        return name.strip()

    @staticmethod
    def _similarity(name1: str, name2: str) -> float:
        """Word-overlap similarity."""
        words1 = set(name1.split())
        words2 = set(name2.split())

        # Remove noise words
        noise = {"fc", "cf", "sc", "ac", "as", "us", "ss", "sv", "vfb", "vfl",
                 "tsg", "rb", "rcd", "ud", "cd", "sd", "fk", "bk", "if", "sk",
                 "1.", "de", "la", "le", "el"}
        words1 = words1 - noise
        words2 = words2 - noise

        if not words1 or not words2:
            return 0.3

        overlap = words1 & words2
        if overlap:
            return len(overlap) / min(len(words1), len(words2))

        # Substring check (e.g., "man" in "manchester")
        for w1 in words1:
            if len(w1) < 3:
                continue
            for w2 in words2:
                if len(w2) < 3:
                    continue
                if w1 in w2 or w2 in w1:
                    return 0.6

        return 0.0

    def get_known_teams(self) -> Set[str]:
        """Get all known team names."""
        return self._known_teams.copy()

    def stats(self) -> Dict:
        """Get resolver statistics."""
        return {
            "known_teams": len(self._known_teams),
            "aliases": len(ALIASES),
            "cached_resolutions": len(self._cache),
        }
