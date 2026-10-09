"""Inspect/export chronological staging historical results for shadow training.

Never trains a champion, modifies official predictions, or touches production.
Without --write-files it only reports counts; dataset features are generated
from verified-date pre-match history, not the match result being predicted.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import text

from scripts.prepare_staging_board_once import preflight
from leagues.chronological_training_data import build_examples, chronological_split


def training_data(*, min_history: int = 3, write_files: bool = False,
                  output_prefix: str = "openfootball_shadow") -> dict:
    database = preflight()
    from database import engine
    with engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT to_regclass('public.external_historical_results_v1')"
        )).scalar()
        if exists is None:
            raise RuntimeError(
                "No staging history warehouse. Run "
                "python -m scripts.ingest_staging_historical_results "
                "--write-staging first."
            )
        rows = [
            dict(row) for row in conn.execute(text("""
                SELECT fixture_key, league_slug,
                       match_date, home_team, away_team, home_score,
                       away_score, source, source_sha256
                FROM external_historical_results_v1
                WHERE match_date < CURRENT_DATE
                  AND source = 'openfootball/football.json'
                ORDER BY match_date,league_slug,fixture_key
            """)).mappings()
        ]
    prepared = build_examples(rows, min_history=min_history)
    split = chronological_split(prepared["examples"])
    counts = {
        "database": database, "staging_only": True,
        "historical_result_rows": prepared["total_deduplicated_results"],
        "examples_with_pre_match_evidence": len(prepared["examples"]),
        "excluded": prepared["skipped"],
        "train_examples": len(split["train"]),
        "holdout_examples": len(split["holdout"]),
        "holdout_cutoff_date": split["cutoff_date"],
        "feature_policy": prepared["feature_policy"],
        "source_requires_independent_score_verification": True,
        "champion_model_unchanged": True,
        "production_unchanged": True,
        "files_written": [],
    }
    if write_files:
        prefix = Path(output_prefix)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        for name in ("train", "holdout"):
            path = prefix.parent / (prefix.name + f"_{name}.jsonl")
            with path.open("w", encoding="utf-8") as out:
                for record in split[name]:
                    out.write(json.dumps(record, sort_keys=True) + "\n")
            counts["files_written"].append(str(path))
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-team-history", type=int, default=3)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--output-prefix", default="openfootball_shadow")
    opts = parser.parse_args()
    print(json.dumps(training_data(
        min_history=opts.min_team_history,
        write_files=opts.write_files,
        output_prefix=opts.output_prefix,
    ), sort_keys=True))
