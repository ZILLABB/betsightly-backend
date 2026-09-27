"""Fetch football-data.co.uk history with explicit row/odds provenance.

Safe default:
    writes data/historical/raw/football_data_uk_matches.csv

It does NOT overwrite data/api-football/matches.csv unless --legacy-output is
explicitly supplied.  The legacy runtime/training CSV therefore remains stable
until a later reviewed migration.
"""
from __future__ import annotations

import argparse
import csv
import io
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
RAW_OUTPUT = (
    ROOT / "data" / "historical" / "raw" / "football_data_uk_matches.csv"
)
LEGACY_OUTPUT = ROOT / "data" / "api-football" / "matches.csv"

TRAINING_COLUMNS = [
    "home_team", "away_team", "date",
    "home_score", "away_score",
    "ht_home_score", "ht_away_score",
    "league_id", "league_name", "country", "league_tier", "season",
    "home_team_id", "away_team_id",
    "avg_odds_home", "avg_odds_draw", "avg_odds_away",
    "avg_odds_over25", "avg_odds_under25",
]
PROVENANCE_COLUMNS = [
    "source_provider", "source_dataset", "source_url", "source_file",
    "source_row_id", "source_league_code", "provenance_quality", "fetched_at",
    "odds_home_source_column", "odds_draw_source_column",
    "odds_away_source_column", "odds_over25_source_column",
    "odds_under25_source_column", "odds_home_snapshot_type",
    "odds_draw_snapshot_type", "odds_away_snapshot_type",
    "odds_over25_snapshot_type", "odds_under25_snapshot_type",
]
CSV_COLUMNS = TRAINING_COLUMNS + PROVENANCE_COLUMNS

HEADERS = {"User-Agent": "Mozilla/5.0 (BetSightly historical warehouse)"}

MAIN_LEAGUES = {
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
MAIN_SEASONS = {
    "1920": 2019, "2021": 2020, "2122": 2021,
    "2223": 2022, "2324": 2023, "2425": 2024, "2526": 2025,
}
RECENT_SEASONS = {
    "2223": 2022, "2324": 2023, "2425": 2024, "2526": 2025,
}
EXTRA_LEAGUES = {
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

# Only an explicit closing-labelled source column earns CLOSING provenance.
CLOSING_COLUMNS = {
    "AvgCH", "AvgCD", "AvgCA", "PSCH", "PSCD", "PSCA",
    "B365CH", "B365CD", "B365CA", "MaxCH", "MaxCD", "MaxCA",
    "AvgC>2.5", "AvgC<2.5", "PC>2.5", "PC<2.5",
    "B365C>2.5", "B365C<2.5",
}


def _download(url: str) -> str | None:
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=30) as response:
            raw = response.read()
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw.decode("latin-1")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"  HTTP {exc.code} for {url}")
        return None
    except URLError as exc:
        print(f"  Network error for {url}: {exc}")
        return None


def _parse_date(value: str) -> str:
    value = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _safe_int(value) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return ""


def _pick(row: dict, columns: list[str]) -> tuple[str, str, str]:
    for column in columns:
        value = str(row.get(column, "") or "").strip()
        if not value:
            continue
        try:
            price = float(value)
        except ValueError:
            continue
        if price <= 1:
            continue
        snapshot = "CLOSING" if column in CLOSING_COLUMNS else "UNSPECIFIED"
        return value, column, snapshot
    return "", "", "MISSING"


def _base_provenance(
    *, url: str, source_file: str, row_id: int, league_code: str, fetched_at: str
) -> dict:
    return {
        "source_provider": "football-data.co.uk",
        "source_dataset": "football-data.co.uk CSV",
        "source_url": url,
        "source_file": source_file,
        "source_row_id": row_id,
        "source_league_code": league_code,
        "provenance_quality": "EXACT_SOURCE_ROW",
        "fetched_at": fetched_at,
    }


def _odds_fields(prefix: str, picked: tuple[str, str, str]) -> dict:
    value, source_column, snapshot = picked
    return {
        f"avg_odds_{prefix}": value,
        f"odds_{prefix}_source_column": source_column,
        f"odds_{prefix}_snapshot_type": snapshot,
    }


def fetch_main_leagues(seasons: dict) -> list[dict]:
    rows: list[dict] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    total = len(MAIN_LEAGUES) * len(seasons)
    count = 0

    for season_code, season_year in sorted(seasons.items()):
        for code, (league_id, league_name, country, tier) in MAIN_LEAGUES.items():
            count += 1
            source_file = f"{season_code}/{code}.csv"
            url = f"https://www.football-data.co.uk/mmz4281/{source_file}"
            print(f"  [{count}/{total}] {league_name} {season_code}...", end=" ")
            text = _download(url)
            if not text:
                print("SKIP")
                continue
            added = 0
            for row_id, raw in enumerate(csv.DictReader(io.StringIO(text))):
                home = str(raw.get("HomeTeam", "") or "").strip()
                away = str(raw.get("AwayTeam", "") or "").strip()
                date = _parse_date(raw.get("Date", ""))
                hs = _safe_int(raw.get("FTHG", ""))
                aws = _safe_int(raw.get("FTAG", ""))
                if not home or not away or not date or hs == "" or aws == "":
                    continue

                # Prefer explicitly closing-labelled columns first.  If they
                # are unavailable, fall back to non-closing/unspecified prices
                # while recording the exact source column and semantics.
                home_pick = _pick(raw, ["AvgCH", "PSCH", "B365CH", "AvgH", "PSH", "B365H"])
                draw_pick = _pick(raw, ["AvgCD", "PSCD", "B365CD", "AvgD", "PSD", "B365D"])
                away_pick = _pick(raw, ["AvgCA", "PSCA", "B365CA", "AvgA", "PSA", "B365A"])
                over_pick = _pick(raw, ["AvgC>2.5", "PC>2.5", "B365C>2.5", "Avg>2.5", "P>2.5", "B365>2.5"])
                under_pick = _pick(raw, ["AvgC<2.5", "PC<2.5", "B365C<2.5", "Avg<2.5", "P<2.5", "B365<2.5"])

                row = {
                    "home_team": home, "away_team": away, "date": date,
                    "home_score": hs, "away_score": aws,
                    "ht_home_score": _safe_int(raw.get("HTHG", "")),
                    "ht_away_score": _safe_int(raw.get("HTAG", "")),
                    "league_id": league_id, "league_name": league_name,
                    "country": country, "league_tier": tier,
                    "season": season_year, "home_team_id": "", "away_team_id": "",
                    **_base_provenance(
                        url=url, source_file=source_file, row_id=row_id,
                        league_code=code, fetched_at=fetched_at,
                    ),
                    **_odds_fields("home", home_pick),
                    **_odds_fields("draw", draw_pick),
                    **_odds_fields("away", away_pick),
                    **_odds_fields("over25", over_pick),
                    **_odds_fields("under25", under_pick),
                }
                rows.append(row)
                added += 1
            print(f"{added} matches")
            time.sleep(0.3)
    return rows


def fetch_extra_leagues(min_season: int = 2019) -> list[dict]:
    rows: list[dict] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    total = len(EXTRA_LEAGUES)
    for count, (code, info) in enumerate(EXTRA_LEAGUES.items(), start=1):
        league_id, league_name, country, tier = info
        source_file = f"new/{code}.csv"
        url = f"https://www.football-data.co.uk/{source_file}"
        print(f"  [{count}/{total}] {league_name} ({code})...", end=" ")
        text = _download(url)
        if not text:
            print("SKIP")
            continue
        added = 0
        for row_id, raw in enumerate(csv.DictReader(io.StringIO(text))):
            season_raw = str(raw.get("Season", "") or "").strip()
            try:
                season = int(season_raw[:4])
            except (ValueError, IndexError):
                continue
            if season < min_season:
                continue
            home = str(raw.get("Home", "") or "").strip()
            away = str(raw.get("Away", "") or "").strip()
            date = _parse_date(raw.get("Date", ""))
            hs = _safe_int(raw.get("HG", ""))
            aws = _safe_int(raw.get("AG", ""))
            if not home or not away or not date or hs == "" or aws == "":
                continue

            home_pick = _pick(raw, ["AvgCH", "PSCH", "B365CH", "MaxCH"])
            draw_pick = _pick(raw, ["AvgCD", "PSCD", "B365CD", "MaxCD"])
            away_pick = _pick(raw, ["AvgCA", "PSCA", "B365CA", "MaxCA"])

            row = {
                "home_team": home, "away_team": away, "date": date,
                "home_score": hs, "away_score": aws,
                "ht_home_score": "", "ht_away_score": "",
                "league_id": league_id, "league_name": league_name,
                "country": country, "league_tier": tier,
                "season": season, "home_team_id": "", "away_team_id": "",
                **_base_provenance(
                    url=url, source_file=source_file, row_id=row_id,
                    league_code=code, fetched_at=fetched_at,
                ),
                **_odds_fields("home", home_pick),
                **_odds_fields("draw", draw_pick),
                **_odds_fields("away", away_pick),
                **_odds_fields("over25", ("", "", "MISSING")),
                **_odds_fields("under25", ("", "", "MISSING")),
            }
            rows.append(row)
            added += 1
        print(f"{added} matches")
        time.sleep(0.3)
    return rows


def _write(rows: list[dict], path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recent", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=RAW_OUTPUT,
        help="Provenance-rich raw output. Defaults outside the legacy runtime path.",
    )
    parser.add_argument(
        "--legacy-output",
        action="store_true",
        help="Also overwrite data/api-football/matches.csv explicitly.",
    )
    args = parser.parse_args()

    seasons = RECENT_SEASONS if args.recent else MAIN_SEASONS
    min_extra = 2022 if args.recent else 2019
    rows = fetch_main_leagues(seasons) + fetch_extra_leagues(min_extra)
    rows.sort(key=lambda row: (row["date"], row["league_id"], row["home_team"], row["away_team"]))

    _write(rows, args.output.resolve(), CSV_COLUMNS)
    print(f"\nWrote provenance-rich raw history: {args.output.resolve()}")
    print(f"Rows: {len(rows):,}")

    if args.legacy_output:
        print(
            "WARNING: --legacy-output explicitly replaces the existing runtime/"
            "training CSV. Review the normalized warehouse before retraining."
        )
        _write(rows, LEGACY_OUTPUT, TRAINING_COLUMNS)
        print(f"Legacy output written: {LEGACY_OUTPUT}")
    else:
        print("Legacy data/api-football/matches.csv was NOT modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
