"""
Fetch historical match data from football-data.co.uk (FREE, no API key).

Replaces the API-Football-based fetch_history.py which required a paid/
rate-limited API.  football-data.co.uk provides:
  - Main European leagues: rich CSVs with match stats + betting odds
  - Extra leagues (Americas, Nordic, Asia): simpler CSVs with results + odds
  - Data from 2012 through the current season, updated weekly

Output:  data/api-football/matches.csv   (same schema the ML pipeline expects)

Usage:
    py scripts/fetch_history_fdc.py          # fetch everything
    py scripts/fetch_history_fdc.py --recent  # only 2022+ seasons
"""

import csv
import io
import os
import sys
import argparse
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# Output (same location the ML pipeline reads from)
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path("data/api-football")
OUTPUT_CSV = OUTPUT_DIR / "matches.csv"

CSV_COLUMNS = [
    "home_team", "away_team", "date",
    "home_score", "away_score",
    "ht_home_score", "ht_away_score",
    "league_id", "league_name", "country", "league_tier", "season",
    "home_team_id", "away_team_id",
    # NEW — historical bookmaker odds (average closing odds)
    "avg_odds_home", "avg_odds_draw", "avg_odds_away",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (BetSightly ML pipeline)"}

# ---------------------------------------------------------------------------
# Main European leagues  —  mmz4281/<season>/<code>.csv
# Rich format: HomeTeam, AwayTeam, FTHG, FTAG, HTHG, HTAG, + many odds cols
# ---------------------------------------------------------------------------
MAIN_LEAGUES = {
    # code: (league_id, league_name, country, tier)
    #   league_id kept consistent with API-Football IDs where possible
    "E0":  (39,  "Premier League",   "England",       1),
    "E1":  (40,  "Championship",     "England",       2),
    "SC0": (179, "Premiership",      "Scotland",      1),
    "D1":  (78,  "Bundesliga",       "Germany",       1),
    "D2":  (79,  "2. Bundesliga",    "Germany",       2),
    "I1":  (135, "Serie A",          "Italy",         1),
    "I2":  (136, "Serie B",          "Italy",         2),
    "SP1": (140, "La Liga",          "Spain",         1),
    "SP2": (141, "Segunda Division", "Spain",         2),
    "F1":  (61,  "Ligue 1",          "France",        1),
    "F2":  (62,  "Ligue 2",          "France",        2),
    "N1":  (88,  "Eredivisie",       "Netherlands",   1),
    "B1":  (144, "Pro League",       "Belgium",       1),
    "T1":  (203, "Super Lig",        "Turkey",        1),
    "P1":  (94,  "Primeira Liga",    "Portugal",      1),
    "G1":  (197, "Super League",     "Greece",        1),
}

# Season codes for main leagues: "2223" = 2022/23 season
MAIN_SEASONS = {
    "1920": 2019, "2021": 2020, "2122": 2021,
    "2223": 2022, "2324": 2023, "2425": 2024, "2526": 2025,
}

# When --recent is passed, only fetch these
RECENT_SEASONS = {"2223": 2022, "2324": 2023, "2425": 2024, "2526": 2025}

# ---------------------------------------------------------------------------
# Extra leagues  —  new/<COUNTRY>.csv  (single file per country, all seasons)
# Simpler format: Home, Away, HG, AG, + some odds cols
# ---------------------------------------------------------------------------
EXTRA_LEAGUES = {
    # country_code: (league_id, league_name, country, tier)
    "USA": (253, "MLS",              "USA",           1),
    "BRA": (71,  "Serie A",          "Brazil",        1),
    "ARG": (128, "Primera Division", "Argentina",     1),
    "MEX": (262, "Liga MX",          "Mexico",        1),
    "NOR": (103, "Eliteserien",      "Norway",        1),
    "SWE": (113, "Allsvenskan",      "Sweden",        1),
    "FIN": (244, "Veikkausliiga",    "Finland",       1),
    "DNK": (119, "Superliga",        "Denmark",       1),
    "JPN": (98,  "J1 League",        "Japan",         1),
    "AUT": (218, "Bundesliga",       "Austria",       1),
    "SWI": (207, "Super League",     "Switzerland",   1),
    "POL": (106, "Ekstraklasa",      "Poland",        1),
    "ROU": (283, "Liga I",           "Romania",       1),
    "CHN": (169, "Super League",     "China",         1),
}


def _download(url: str) -> str | None:
    """Download a URL, return text or None on failure."""
    req = Request(url, headers=HEADERS)
    try:
        resp = urlopen(req, timeout=30)
        raw = resp.read()
        # Try utf-8 first, fall back to latin-1
        try:
            return raw.decode("utf-8-sig")  # handles BOM
        except UnicodeDecodeError:
            return raw.decode("latin-1")
    except HTTPError as e:
        if e.code == 404:
            return None
        print(f"  HTTP {e.code} for {url}")
        return None
    except URLError as e:
        print(f"  Network error for {url}: {e}")
        return None


def _parse_date(date_str: str) -> str:
    """Convert DD/MM/YYYY to YYYY-MM-DD."""
    try:
        dt = datetime.strptime(date_str.strip(), "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _safe_int(val) -> str:
    """Convert to int string, or empty string."""
    try:
        return str(int(val))
    except (ValueError, TypeError):
        return ""


def _pick_odds(row: dict, prefix_h: list, prefix_d: list, prefix_a: list) -> tuple:
    """Pick the best available odds from a row, trying multiple column names."""
    def _first(keys):
        for k in keys:
            v = row.get(k, "").strip()
            if v:
                try:
                    float(v)
                    return v
                except ValueError:
                    continue
        return ""
    return _first(prefix_h), _first(prefix_d), _first(prefix_a)


def fetch_main_leagues(seasons: dict) -> list:
    """Fetch main European league CSVs."""
    all_rows = []
    total = len(MAIN_LEAGUES) * len(seasons)
    count = 0

    for season_code, season_year in sorted(seasons.items()):
        for code, (league_id, league_name, country, tier) in MAIN_LEAGUES.items():
            count += 1
            url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{code}.csv"
            print(f"  [{count}/{total}] {league_name} {season_code}...", end=" ")

            text = _download(url)
            if not text:
                print("SKIP (not found)")
                continue

            reader = csv.DictReader(io.StringIO(text))
            rows_added = 0
            for r in reader:
                home = r.get("HomeTeam", "").strip()
                away = r.get("AwayTeam", "").strip()
                if not home or not away:
                    continue

                date_str = _parse_date(r.get("Date", ""))
                if not date_str:
                    continue

                home_score = _safe_int(r.get("FTHG", ""))
                away_score = _safe_int(r.get("FTAG", ""))
                if not home_score or not away_score:
                    continue

                # Odds: prefer Avg, then Pinnacle, then Bet365
                oh, od, oa = _pick_odds(
                    r,
                    ["AvgH", "AvgCH", "PSH", "PSCH", "B365H", "B365CH"],
                    ["AvgD", "AvgCD", "PSD", "PSCD", "B365D", "B365CD"],
                    ["AvgA", "AvgCA", "PSA", "PSCA", "B365A", "B365CA"],
                )

                all_rows.append({
                    "home_team":      home,
                    "away_team":      away,
                    "date":           date_str,
                    "home_score":     home_score,
                    "away_score":     away_score,
                    "ht_home_score":  _safe_int(r.get("HTHG", "")),
                    "ht_away_score":  _safe_int(r.get("HTAG", "")),
                    "league_id":      league_id,
                    "league_name":    league_name,
                    "country":        country,
                    "league_tier":    tier,
                    "season":         season_year,
                    "home_team_id":   "",
                    "away_team_id":   "",
                    "avg_odds_home":  oh,
                    "avg_odds_draw":  od,
                    "avg_odds_away":  oa,
                })
                rows_added += 1

            print(f"{rows_added} matches")
            time.sleep(0.3)  # be polite

    return all_rows


def fetch_extra_leagues(min_season: int = 2019) -> list:
    """Fetch extra league CSVs (one file per country, all seasons)."""
    all_rows = []
    count = 0
    total = len(EXTRA_LEAGUES)

    for country_code, (league_id, league_name, country, tier) in EXTRA_LEAGUES.items():
        count += 1
        url = f"https://www.football-data.co.uk/new/{country_code}.csv"
        print(f"  [{count}/{total}] {league_name} ({country_code})...", end=" ")

        text = _download(url)
        if not text:
            print("SKIP (not found)")
            continue

        reader = csv.DictReader(io.StringIO(text))
        rows_added = 0
        for r in reader:
            # Filter by season
            season_raw = r.get("Season", "").strip()
            try:
                # Season can be "2023" or "2023/2024"
                season_year = int(season_raw[:4])
            except (ValueError, IndexError):
                continue

            if season_year < min_season:
                continue

            home = r.get("Home", "").strip()
            away = r.get("Away", "").strip()
            if not home or not away:
                continue

            date_str = _parse_date(r.get("Date", ""))
            if not date_str:
                continue

            home_score = _safe_int(r.get("HG", ""))
            away_score = _safe_int(r.get("AG", ""))
            if not home_score or not away_score:
                continue

            # Odds: prefer Avg, then Pinnacle, then Bet365
            oh, od, oa = _pick_odds(
                r,
                ["AvgCH", "PSCH", "B365CH", "MaxCH"],
                ["AvgCD", "PSCD", "B365CD", "MaxCD"],
                ["AvgCA", "PSCA", "B365CA", "MaxCA"],
            )

            all_rows.append({
                "home_team":      home,
                "away_team":      away,
                "date":           date_str,
                "home_score":     home_score,
                "away_score":     away_score,
                "ht_home_score":  "",
                "ht_away_score":  "",
                "league_id":      league_id,
                "league_name":    league_name,
                "country":        country,
                "league_tier":    tier,
                "season":         season_year,
                "home_team_id":   "",
                "away_team_id":   "",
                "avg_odds_home":  oh,
                "avg_odds_draw":  od,
                "avg_odds_away":  oa,
            })
            rows_added += 1

        print(f"{rows_added} matches")
        time.sleep(0.3)

    return all_rows


def main():
    parser = argparse.ArgumentParser(description="Fetch historical data from football-data.co.uk")
    parser.add_argument("--recent", action="store_true",
                        help="Only fetch 2022+ seasons (faster)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    seasons = RECENT_SEASONS if args.recent else MAIN_SEASONS
    min_extra = 2022 if args.recent else 2019

    print("=" * 60)
    print("  football-data.co.uk Historical Data Fetcher")
    print("  No API key required — free CSV downloads")
    print(f"  Seasons: {'2022+' if args.recent else '2019+'}")
    print("=" * 60)

    # Fetch main European leagues
    print(f"\n📋 Main European leagues ({len(MAIN_LEAGUES)} leagues × {len(seasons)} seasons):")
    main_rows = fetch_main_leagues(seasons)
    print(f"  → {len(main_rows):,} matches from main leagues")

    # Fetch extra leagues
    print(f"\n📋 Extra leagues ({len(EXTRA_LEAGUES)} countries, {min_extra}+ seasons):")
    extra_rows = fetch_extra_leagues(min_season=min_extra)
    print(f"  → {len(extra_rows):,} matches from extra leagues")

    # Combine and write
    all_rows = main_rows + extra_rows

    # Sort by date
    all_rows.sort(key=lambda r: r["date"])

    # Write CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    # Summary
    leagues = set(r["league_name"] for r in all_rows)
    countries = set(r["country"] for r in all_rows)
    seasons_found = sorted(set(r["season"] for r in all_rows))
    odds_count = sum(1 for r in all_rows if r["avg_odds_home"])

    print(f"\n{'=' * 60}")
    print(f"  ✅ Done!")
    print(f"  📁 {OUTPUT_CSV}")
    print(f"  📊 {len(all_rows):,} total matches")
    print(f"  🏆 {len(leagues)} leagues across {len(countries)} countries")
    print(f"  📅 Seasons: {seasons_found[0]}–{seasons_found[-1]}")
    print(f"  💰 {odds_count:,} matches with historical odds ({odds_count*100//len(all_rows)}%)")
    print(f"{'=' * 60}")
    print(f"\nNext step: py scripts/retrain_models.py")


if __name__ == "__main__":
    main()
