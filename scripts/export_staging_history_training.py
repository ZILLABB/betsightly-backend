"""Inspect/export chronological staging historical results for shadow training.

Never trains a champion, modifies official predictions, or touches production.
Without --write-files it only reports counts; dataset features are generated
from verified-date pre-match history, not the match result being predicted.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from sqlalchemy import text

from scripts.prepare_staging_board_once import preflight
from leagues.chronological_training_data import build_examples, chronological_split
from leagues.openfootball_match_history import plausible_season_date


def filter_plausible_season_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Quarantine pre-existing source/date inconsistencies without DB writes."""
    clean = [
        row for row in rows
        if plausible_season_date(
            str(row["season"]),
            row["match_date"] if isinstance(row["match_date"], date)
            else date.fromisoformat(str(row["match_date"])[:10]),
        )
    ]
    return clean, len(rows) - len(clean)


def training_data(*, min_history: int = 3, write_files: bool = False,
                  output_prefix: str = "openfootball_shadow",
                  evaluate: bool = False,
                  evaluate_walkforward: bool = False) -> dict:
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
                SELECT fixture_key, league_slug, season,
                       match_date, home_team, away_team, home_score,
                       away_score, source, source_sha256
                FROM external_historical_results_v1
                WHERE match_date < CURRENT_DATE
                  AND source = 'openfootball/football.json'
                ORDER BY match_date,league_slug,fixture_key
            """)).mappings()
        ]
    # Existing staging imports are immutable. Preserve original rows for
    # audit while excluding inconsistent dates from shadow model training.
    clean, rejected_season_dates = filter_plausible_season_rows(rows)
    prepared = build_examples(clean, min_history=min_history)
    split = chronological_split(prepared["examples"])
    counts = {
        "database": database, "staging_only": True,
        "raw_staging_rows": len(rows),
        "excluded_invalid_season_dates": rejected_season_dates,
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
    if evaluate:
        from leagues.shadow_historical_challenger import evaluate_shadow
        counts["shadow_evaluation"] = evaluate_shadow(
            split["train"], split["holdout"],
        )
    if evaluate_walkforward:
        from leagues.walkforward_shadow_validation import evaluate_walk_forward
        counts["walk_forward_evaluation"] = evaluate_walk_forward(
            prepared["examples"], folds=4, embargo_days=7,
        )
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
    parser.add_argument(
        "--evaluate-shadow", action="store_true",
        help="Train temporary, never-promoted logistic models on chronological data",
    )
    parser.add_argument(
        "--evaluate-walkforward", action="store_true",
        help="Expanding-window four-fold shadow benchmark with 7-day embargo",
    )
    parser.add_argument("--output-prefix", default="openfootball_shadow")
    opts = parser.parse_args()
    print(json.dumps(training_data(
        min_history=opts.min_team_history,
        write_files=opts.write_files,
        output_prefix=opts.output_prefix,
        evaluate=opts.evaluate_shadow,
        evaluate_walkforward=opts.evaluate_walkforward,
    ), sort_keys=True))
