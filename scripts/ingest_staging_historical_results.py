"""Import verified CC0 match results into the isolated staging history warehouse.

Default is dry-run. --write-staging is required for database writes; the
connected DB name must be betsightly_db_staging. No official predictions,
trained model versions, booking codes, settlements or production DB are touched.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from sqlalchemy import text

from scripts.prepare_staging_board_once import preflight
from leagues.openfootball_match_history import LEAGUES, fetch_results

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS external_historical_results_v1 (
 fixture_key VARCHAR(64) PRIMARY KEY,
 league_slug VARCHAR(40) NOT NULL,
 season VARCHAR(12) NOT NULL,
 match_date DATE NOT NULL,
 home_team VARCHAR(180) NOT NULL,
 away_team VARCHAR(180) NOT NULL,
 home_score SMALLINT NOT NULL CHECK (home_score BETWEEN 0 AND 30),
 away_score SMALLINT NOT NULL CHECK (away_score BETWEEN 0 AND 30),
 source VARCHAR(100) NOT NULL,
 source_license VARCHAR(30) NOT NULL,
 source_file VARCHAR(160) NOT NULL,
 source_sha256 VARCHAR(64) NOT NULL,
 imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""
INSERT_SQL = text("""
INSERT INTO external_historical_results_v1
(fixture_key,league_slug,season,match_date,home_team,away_team,
 home_score,away_score,source,source_license,source_file,source_sha256)
VALUES
(:fixture_key,:league_slug,:season,:match_date,:home_team,:away_team,
 :home_score,:away_score,:source,:source_license,:source_file,:source_sha256)
ON CONFLICT (fixture_key) DO NOTHING
""")


def seasons_to_import(years: int, *, today=None) -> list[str]:
    if not 1 <= years <= 8:
        raise ValueError("Years must be between one and eight")
    today = today or datetime.now(timezone.utc).date()
    # Current northern-hemisphere season starts in August. This includes
    # finished rows from the current season but never future/unfinished games.
    current_start = today.year if today.month >= 8 else today.year - 1
    return [
        f"{y}-{(y + 1) % 100:02d}"
        for y in range(current_start - years + 1, current_start + 1)
    ]


def ingest(*, leagues: list[str], years: int = 4,
           write_staging: bool = False, revision: str = "master") -> dict:
    db = preflight()
    unique_slugs = sorted(set(leagues))
    if not unique_slugs or any(slug not in LEAGUES for slug in unique_slugs):
        raise ValueError("Select at least one verified OpenFootball league")
    seasons = seasons_to_import(years)
    if len(unique_slugs) * len(seasons) > 200:
        raise ValueError("Bounded ingestion allows at most 200 source files")

    from database import engine
    if write_staging:
        with engine.begin() as conn:
            conn.execute(text(SCHEMA_SQL))
    sources = []
    failed = []
    seen_total = imported = 0
    for season in seasons:
        for slug in unique_slugs:
            try:
                rows, report = fetch_results(slug, season, revision=revision)
            except Exception as exc:
                failed.append({
                    "league": slug, "season": season,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:250],
                })
                continue

            seen_total += len(rows)
            if rows and write_staging:
                with engine.begin() as conn:
                    # Existing results are immutable. One duplicated row
                    # cannot overwrite an older, potentially settled score.
                    for start in range(0, len(rows), 250):
                        result = conn.execute(INSERT_SQL, rows[start:start + 250])
                        imported += max(0, result.rowcount or 0)
            sources.append(report)
    return {
        "database": db, "source": "openfootball/football.json",
        "source_license": "CC0-1.0", "source_revision": revision,
        "dry_run": not write_staging, "production_unchanged": True,
        "publication_changed": False, "champion_model_unchanged": True,
        "requested_sources": len(unique_slugs) * len(seasons),
        "source_successes": len(sources), "source_failures": failed,
        "total_verified_completed_match_rows": seen_total,
        "new_rows_written_staging": imported,
        "sources": sources,
        "training_use": (
            "Historical evidence and chronological shadow training only; "
            "do not use post-kickoff results as pre-kickoff features."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=4)
    parser.add_argument(
        "--leagues", default=",".join(LEAGUES),
        help="Comma-separated internal league slugs, e.g. eng.1,eng.2,fra.1",
    )
    parser.add_argument("--revision", default="master")
    parser.add_argument(
        "--write-staging", action="store_true",
        help="Explicitly write verified matches to the staging history warehouse",
    )
    args = parser.parse_args()
    print(json.dumps(ingest(
        leagues=[slug.strip() for slug in args.leagues.split(",") if slug.strip()],
        years=args.years, write_staging=args.write_staging,
        revision=args.revision,
    ), sort_keys=True, default=str))
