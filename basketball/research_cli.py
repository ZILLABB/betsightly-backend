"""Explicit offline NBA research commands. Never imports FastAPI or publishers.

Usage:
  python -m basketball.research_cli fetch --seasons 2022 2023 2024 2025
  python -m basketball.research_cli report
  python -m basketball.research_cli train
  python -m basketball.research_cli paper --date 2026-10-25
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from basketball.research_data import fetch_seasons, read_games, write_games
from basketball.research_public_data import DEFAULT_SEASONS, fetch_public_seasons
from basketball.research_features import quality_report
from basketball.research_model import paper_forecasts, train_offline
from basketball.research_tracking import score_paper_archive, write_paper_archive

DEFAULT_DATA = Path("data/basketball/research/nba_games.jsonl")
DEFAULT_MODEL = Path("data/basketball/research/nba_moneyline.joblib")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline-only NBA research (not betting)")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="Download NBA regular-season games")
    fetch.add_argument("--seasons", type=int, nargs="+", required=True)
    fetch.add_argument("--output", type=Path, default=DEFAULT_DATA)
    fetch.add_argument("--max-pages", type=int, default=1000)

    public = commands.add_parser("fetch-public", help="Download keyless public historical NBA schedules")
    public.add_argument("--seasons", type=int, nargs="+", default=list(DEFAULT_SEASONS))
    public.add_argument("--output", type=Path, default=DEFAULT_DATA)
    public.add_argument("--manifest", type=Path,
                        default=Path("data/basketball/research/source_manifest.json"))

    report = commands.add_parser("report", help="Check real dataset coverage")
    report.add_argument("--data", type=Path, default=DEFAULT_DATA)

    train = commands.add_parser("train", help="Train and chronologically backtest")
    train.add_argument("--data", type=Path, default=DEFAULT_DATA)
    train.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    train.add_argument("--min-games", type=int, default=300)

    paper = commands.add_parser("paper", help="Private non-bookable forecast")
    paper.add_argument("--data", type=Path, default=DEFAULT_DATA)
    paper.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    paper.add_argument("--date", required=True, help="NBA provider date YYYY-MM-DD")
    paper.add_argument("--output", type=Path, help="Optional private JSON file")

    score = commands.add_parser("score", help="Verify archived paper picks with final scores")
    score.add_argument("--data", type=Path, default=DEFAULT_DATA)
    score.add_argument("--archive", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fetch":
        key = os.getenv("BALLDONTLIE_API_KEY", "")
        games = fetch_seasons(args.seasons, key, max_pages=args.max_pages)
        count = write_games(games, args.output)
        result = {"status": "complete", "downloaded": count, "path": str(args.output),
                  "research_only": True}
    elif args.command == "fetch-public":
        games, manifest = fetch_public_seasons(args.seasons)
        count = write_games(games, args.output)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n",
                                 encoding="utf-8")
        result = {"status": "complete", "downloaded": count,
                  "path": str(args.output), "source_manifest": str(args.manifest),
                  "seasons": len(manifest), "research_only": True}
    elif args.command == "report":
        result = quality_report(read_games(args.data))
    elif args.command == "train":
        if args.min_games < 300:
            raise ValueError("At least 300 real, eligible game rows required")
        result = train_offline(read_games(args.data), args.model,
                               min_games=args.min_games)
    elif args.command == "paper":
        predictions = paper_forecasts(read_games(args.data), args.model, args.date)
        result = {"status": "research_only", "date": args.date,
                  "market": "nba_moneyline", "bookable": False,
                  "predictions": predictions}
        if predictions:
            archive_path = args.output or (
                Path("data/basketball/research/papers") / (args.date + ".json")
            )
            result["archive"] = write_paper_archive(predictions, archive_path)
    elif args.command == "score":
        result = score_paper_archive(args.archive, read_games(args.data))
    else:
        raise AssertionError("Unknown command")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
