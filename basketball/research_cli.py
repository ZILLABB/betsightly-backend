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

    markets = commands.add_parser(
        "train-markets", help="Offline total-points and point-margin benchmarks")
    markets.add_argument("--data", type=Path, default=DEFAULT_DATA)
    markets.add_argument("--model", type=Path,
                         default=Path("data/basketball/research/nba_scores.joblib"))

    paper = commands.add_parser("paper", help="Private non-bookable forecast")
    paper.add_argument("--data", type=Path, default=DEFAULT_DATA)
    paper.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    paper.add_argument("--date", required=True, help="NBA provider date YYYY-MM-DD")
    paper.add_argument("--output", type=Path, help="Optional private JSON file")

    score = commands.add_parser("score", help="Verify archived paper picks with final scores")
    score.add_argument("--data", type=Path, default=DEFAULT_DATA)
    score.add_argument("--archive", type=Path, required=True)

    cycle = commands.add_parser("cycle", help="Local-only full refresh and paper-test cycle")
    cycle.add_argument("--home", type=Path,
                       default=Path("data/basketball/research"))
    cycle.add_argument("--date", help="First NBA fixture date; defaults to UTC today")
    cycle.add_argument("--days-ahead", type=int, default=2)
    cycle.add_argument("--seasons", nargs="+", type=int)
    cycle.add_argument("--offline", action="store_true",
                       help="Use current local snapshot, no network")
    cycle.add_argument("--retrain", action="store_true",
                       help="Explicitly refresh the prospective model only")

    readiness = commands.add_parser(
        "readiness", help="Read-only source health and upcoming fixture blockers")
    readiness.add_argument("--home", type=Path,
                           default=Path("data/basketball/research"))
    readiness.add_argument("--days-ahead", type=int, default=7)

    settlement = commands.add_parser(
        "settle", help="Lightweight verified final-score refresh; no retraining")
    settlement.add_argument("--home", type=Path,
                            default=Path("data/basketball/research"))
    settlement.add_argument("--offline", action="store_true")

    diagnose = commands.add_parser(
        "diagnose-scores", help="Read-only local NBA scores and provider provenance")
    diagnose.add_argument("--home", type=Path,
                          default=Path("data/basketball/research"))
    probe = commands.add_parser(
        "probe-scores", help="Check real final-score providers without modifying data")
    probe.add_argument("--home", type=Path,
                       default=Path("data/basketball/research"))
    probe.add_argument("--date", help="Local provider game date; last 14 days")

    automate = commands.add_parser(
        "automate", help="Serialized scheduled NBA score/pregame/daily run")
    automate.add_argument("--mode", required=True,
                          choices=("score", "pregame", "full"))
    automate.add_argument("--home", type=Path,
                          default=Path("data/basketball/research"))
    automate.add_argument(
        "--advanced", action="store_true",
        help="Optional official injury and boxscore shadow sidecar; does not block v1"
    )
    reliability = commands.add_parser(
        "reliability", help="Read-only local scheduled run receipts and age")
    reliability.add_argument("--home", type=Path,
                             default=Path("data/basketball/research"))

    audit_v2 = commands.add_parser(
        "audit-data", help="Read-only NBA source coverage and rejected rows audit")
    audit_v2.add_argument("--home", type=Path,
                          default=Path("data/basketball/research"))

    benchmark = commands.add_parser(
        "benchmark-v2", help="Offline equal-cohort candidate vs immutable v1")
    benchmark.add_argument("--home", type=Path,
                           default=Path("data/basketball/research"))

    advanced_fetch = commands.add_parser(
        "fetch-advanced", help="Validated current/historical ESPN NBA team/player box scores")
    advanced_fetch.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))
    advanced_fetch.add_argument("--seasons", nargs="+", type=int, required=True)
    advanced_fetch.add_argument("--kinds", nargs="+",
        choices=("team","player"), default=["team","player"])

    advanced_report = commands.add_parser(
        "advanced-report", help="Read-only verified advanced NBA data coverage")
    advanced_report.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    advanced_model = commands.add_parser(
        "advanced-build", help="Fit isolated advanced candidate; v1 remains immutable")
    advanced_model.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    shadow = commands.add_parser(
        "advanced-shadow", help="Record independent verified before-tipoff shadow forecasts")
    shadow.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    injury = commands.add_parser(
        "capture-injury", help="Archive official timestamped NBA injury PDF")
    injury.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))
    injury.add_argument("--date", help="Official publication date YYYY-MM-DD (ET)")

    injury_state = commands.add_parser(
        "injury-status", help="Read-only official injury archive completeness")
    injury_state.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    current_data = commands.add_parser(
        "refresh-current-advanced",
        help="Per-source 2027 NBA advanced refresh with explicit partial availability")
    current_data.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    injury_identity = commands.add_parser(
        "injury-identity", help="Read-only exact current-season NBA player crosswalk")
    injury_identity.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    markets_v4 = commands.add_parser(
        "market-evaluation", help="Read-only full-game forward market probability evaluation")
    markets_v4.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    bootstrap = commands.add_parser(
        "stage4-bootstrap", help="One private locked setup of verified advanced NBA sources and shadow lab")
    bootstrap.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    stage4 = commands.add_parser(
        "stage4-report", help="Read-only Stage 4 NBA source, model and market readiness")
    stage4.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    operations = commands.add_parser(
        "operations", help="Read-only first forecast and settlement lifecycle status")
    operations.add_argument("--home", type=Path,
                            default=Path("data/basketball/research"))

    wave1 = commands.add_parser(
        "wave1-report", help="One read-only NBA data, pregame and settlement health report")
    wave1.add_argument("--home", type=Path,
                       default=Path("data/basketball/research"))

    wave2 = commands.add_parser(
        "wave2-report", help="Read-only NBA advanced and market forward audit")
    wave2.add_argument("--home", type=Path,
                       default=Path("data/basketball/research"))

    regime = commands.add_parser(
        "opening-score-regime",
        help="Read-only scoring-level drift hypotheses; 2025 selection, 2026 diagnostic")
    regime.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    challenger = commands.add_parser(
        "opening-score-challenge",
        help="Read-only 2025 development score hypotheses and 2026 comparison")
    challenger.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    scores_benchmark = commands.add_parser(
        "opening-score-backtest",
        help="Historical opening-week points/margin/team-score paired MAE benchmarks")
    scores_benchmark.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    scores_status = commands.add_parser(
        "opening-score-report",
        help="Read-only real pregame score forecasts and settled MAE, no odds")
    scores_status.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    scores_cycle = commands.add_parser(
        "opening-score-cycle",
        help="Lock and capture separate genuine opening-week points forecasts")
    scores_cycle.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    cold_benchmark = commands.add_parser(
        "coldstart-backtest",
        help="Retrospective opening-week moneyline candidate vs naive home baseline")
    cold_benchmark.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    cup = commands.add_parser(
        "cup-source-audit",
        help="Read-only official nonstandings Cup classification and upcoming forecast sensitivity")
    cup.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    cold_closeout = commands.add_parser(
        "coldstart-closeout",
        help="Read-only pregame/settlement queue and NBA source calendar anomalies")
    cold_closeout.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    cold_ready = commands.add_parser(
        "coldstart-readiness",
        help="Read-only upcoming 48h eligibility for early-season shadow")
    cold_ready.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    cold_status = commands.add_parser(
        "coldstart-report",
        help="Read-only hashed early-season forward observations (never official v1)")
    cold_status.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    cold_cycle = commands.add_parser(
        "coldstart-cycle",
        help="Lock and record before-tipoff opening-week shadow forecasts/settlements")
    cold_cycle.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    advanced_gaps = commands.add_parser(
        "advanced-gaps",
        help="Read-only game-ID diagnostic for delayed current NBA team/player data")
    advanced_gaps.add_argument("--home", type=Path,
        default=Path("data/basketball/research"))

    prospective = commands.add_parser(
        "prospective", help="Read-only real pregame NBA paper evaluation")
    prospective.add_argument("--db", type=Path,
                             default=Path("data/basketball/research/nba_paper.sqlite"))

    ledger = commands.add_parser("ledger", help="Local research ledger performance")
    ledger.add_argument("--home", type=Path,
                        default=Path("data/basketball/research"))

    dashboard = commands.add_parser("dashboard",
                                    help="Read-only Atlantic view (localhost only)")
    dashboard.add_argument("--db", type=Path,
                           default=Path("data/basketball/research/nba_paper.sqlite"))
    dashboard.add_argument("--port", type=int, default=8767)

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
    elif args.command == "train-markets":
        from basketball.research_market_models import train_score_baselines
        result = train_score_baselines(read_games(args.data), args.model)
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
    elif args.command == "cycle":
        from basketball.research_cycle import run_cycle
        result = run_cycle(home=args.home, start_date=args.date,
                           days_ahead=args.days_ahead, seasons=args.seasons,
                           offline=args.offline, retrain=args.retrain)
    elif args.command == "readiness":
        from basketball.research_readiness import readiness_from_home
        result = readiness_from_home(args.home, days_ahead=args.days_ahead)
    elif args.command == "settle":
        from basketball.research_score_only import settle_once
        result = settle_once(home=args.home, offline=args.offline)
    elif args.command == "diagnose-scores":
        from basketball.research_score_diagnostics import inspect_home
        result = inspect_home(args.home)
    elif args.command == "probe-scores":
        from basketball.research_score_diagnostics import probe_source
        result = probe_source(args.home, day=args.date)
    elif args.command == "automate":
        from basketball.research_automation import run_automation
        result = run_automation(home=args.home, mode=args.mode,
                                with_advanced=(args.advanced or
                                               args.mode == "pregame"))
        print(json.dumps(result, indent=2, default=str))
        return 2 if result["status"] in ("degraded", "failed") else 0
    elif args.command == "reliability":
        from basketball.research_automation import reliability_from_home
        result = reliability_from_home(args.home)
    elif args.command == "audit-data":
        from basketball.research_quality_v2 import audit_home
        result = audit_home(args.home)
    elif args.command == "benchmark-v2":
        from basketball.research_candidate_v2 import write_candidate_report
        root = Path(args.home)
        result = write_candidate_report(
            read_games(root / "nba_games.jsonl"),
            root / "candidate_v2_benchmark.json"
        )
    elif args.command == "fetch-advanced":
        from basketball.research_advanced_data import fetch_advanced
        result = fetch_advanced(home=args.home, seasons=args.seasons,
                                kinds=tuple(args.kinds))
    elif args.command == "advanced-report":
        from basketball.research_advanced_data import advanced_coverage
        from basketball.research_advanced_features import from_home
        result = advanced_coverage(args.home)
        _, features = from_home(args.home)
        result["pregame_feature_readiness"] = features
    elif args.command == "advanced-build":
        from basketball.research_advanced_model import build_candidate
        result = build_candidate(args.home)
    elif args.command == "advanced-shadow":
        from basketball.research_advanced_model import run_shadow
        result = run_shadow(args.home)
    elif args.command == "capture-injury":
        from basketball.research_injury_reports import capture_injury
        result = capture_injury(args.home, day=args.date)
    elif args.command == "injury-status":
        from basketball.research_injury_reports import injury_status
        result = injury_status(args.home)
    elif args.command == "refresh-current-advanced":
        from basketball.research_current_advanced_v4 import refresh_current_advanced
        result = refresh_current_advanced(args.home, season=2027)
    elif args.command == "injury-identity":
        from basketball.research_injury_identity_v4 import injury_crosswalk
        result = injury_crosswalk(args.home)
    elif args.command == "market-evaluation":
        from basketball.research_markets_v4 import market_report_from_home
        result = market_report_from_home(args.home)
    elif args.command == "stage4-bootstrap":
        from basketball.research_stage4_setup import bootstrap_stage4
        result = bootstrap_stage4(args.home)
    elif args.command == "stage4-report":
        from basketball.research_stage4_operations import stage4_report
        result = stage4_report(args.home)
    elif args.command == "operations":
        from basketball.research_operations import operations_from_home
        result = operations_from_home(args.home)
    elif args.command == "wave1-report":
        from basketball.research_wave1_report import wave1_report
        result = wave1_report(args.home)
    elif args.command == "wave2-report":
        from basketball.research_wave2_report import wave2_report
        result = wave2_report(args.home)
        print(json.dumps(result, indent=2, default=str))
        return 2 if result["status"] == "integrity_failed" else 0
    elif args.command == "opening-score-regime":
        from basketball.research_score_regime import examine
        result = examine(read_games(args.home / "nba_games.jsonl"))
    elif args.command == "opening-score-challenge":
        from basketball.research_score_challenger import challenge
        result = challenge(read_games(args.home / "nba_games.jsonl"))
    elif args.command == "opening-score-backtest":
        from basketball.research_opening_score import benchmark
        result = benchmark(read_games(args.home / "nba_games.jsonl"))
    elif args.command == "opening-score-report":
        from basketball.research_opening_score import audit
        result = audit(args.home)
        print(json.dumps(result, indent=2, default=str))
        return 2 if result["status"] == "integrity_failed" else 0
    elif args.command == "opening-score-cycle":
        from basketball.research_automation import exclusive_local_run
        from basketball.research_opening_score import cycle
        with exclusive_local_run(args.home):
            result = cycle(args.home)
        print(json.dumps(result, indent=2, default=str))
        return 2 if result["status"] in ("integrity_failed", "source_not_fresh") else 0
    elif args.command == "coldstart-backtest":
        from basketball.research_coldstart import benchmark
        result = benchmark(read_games(args.home / "nba_games.jsonl"))
    elif args.command == "cup-source-audit":
        from basketball.research_cup_classification import from_home
        result = from_home(args.home)
        print(json.dumps(result, indent=2, default=str))
        return 2 if result["status"] in ("integrity_blocked", "source_missing") else 0
    elif args.command == "coldstart-closeout":
        from basketball.research_coldstart_ops import closeout
        result = closeout(args.home)
        print(json.dumps(result, indent=2, default=str))
        return 2 if result["status"] == "integrity_failed" else 0
    elif args.command == "coldstart-readiness":
        from basketball.research_coldstart import readiness
        result = readiness(args.home)
    elif args.command == "coldstart-report":
        from basketball.research_coldstart import audit
        result = audit(args.home)
        print(json.dumps(result, indent=2, default=str))
        return 2 if result["status"] == "integrity_failed" else 0
    elif args.command == "coldstart-cycle":
        from basketball.research_automation import exclusive_local_run
        from basketball.research_coldstart import cycle
        with exclusive_local_run(args.home):
            result = cycle(args.home)
        print(json.dumps(result, indent=2, default=str))
        return 2 if result["status"] in ("integrity_failed", "source_not_fresh") else 0
    elif args.command == "advanced-gaps":
        from basketball.research_advanced_gaps import report
        result = report(args.home)
    elif args.command == "prospective":
        from basketball.research_prospective import prospective_report
        result = prospective_report(args.db)
    elif args.command == "ledger":
        from basketball.research_cycle import ledger_report
        result = ledger_report(home=args.home)
    elif args.command == "dashboard":
        from basketball.research_dashboard import serve_dashboard
        serve_dashboard(db_path=args.db, port=args.port)
        return 0
    else:
        raise AssertionError("Unknown command")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
