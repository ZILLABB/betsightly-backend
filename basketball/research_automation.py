"""Stage 2E: local-only NBA task orchestration and reliability monitoring.

A shared OS advisory lock serializes scheduled pregame, full and score runs.
The process remains research-only: no bookmakers, external account access,
public publishing, or altered previous forecasts.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

from basketball.research_data import read_games, write_games
from basketball.research_public_data import fetch_public_seasons
from basketball.research_scoreboard import preserve_older_verified_finals
from basketball.research_score_only import settle_once
from basketball.research_cycle import run_cycle
from basketball.research_operations import operations_from_home

MODES = ("pregame", "score", "full")
RETRY_DELAYS = (0, 2)  # strictly bounded; no denial-of-service retry loops
STALE_HOURS = {"pregame": 3, "score": 3, "full": 30}


@contextmanager
def exclusive_local_run(home: str | Path):
    """Cross-process kernel lock, released by OS even after abnormal exit.

    All scheduled entrypoints use this exact lock file; overlapping task
    invocations are skipped, never run concurrently.
    """
    root = Path(home)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "automation.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BlockingIOError("Another NBA research task is active") from exc
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                raise BlockingIOError("Another NBA research task is active") from exc
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _retried(operation, *, sleeper=time.sleep):
    """Retry network failures only; never retry schema or identity errors."""
    failure = None
    for i, delay in enumerate(RETRY_DELAYS):
        if delay:
            sleeper(delay)
        try:
            return operation(), i + 1
        except (RuntimeError, HTTPError, URLError, ConnectionError,
                TimeoutError) as exc:
            failure = exc
    raise RuntimeError("NBA data refresh failed after bounded retry") from failure


def _current_season(now: datetime) -> int:
    # ESPN season year is the calendar year when the NBA Finals are played.
    return now.year + 1 if now.month >= 7 else now.year


def refresh_current_season(home: str | Path, *, now: datetime,
                           fetcher=fetch_public_seasons,
                           sleeper=time.sleep) -> dict:
    """Refresh just the current regular-season ESPN release, preserve all finals.

    Require sufficient future fixture preservation so a corrupt or truncated
    replacement cannot silently erase the local calendar or settle history.
    """
    root = Path(home)
    target = root / "nba_games.jsonl"
    existing = read_games(target)
    season = _current_season(now)
    fetched, attempts = _retried(
        lambda: fetcher([season]), sleeper=sleeper)
    new, manifest = fetched
    if not isinstance(manifest, list) or len(manifest) != 1:
        raise ValueError("Current NBA season source provenance incomplete")
    current = [g for g in new if g["season"] == season]
    if not current or any(g["season"] != season for g in new):
        raise ValueError("NBA current-season release identity mismatch")
    old_current = [g for g in existing if g["season"] == season]
    fresh_ids = {str(g["game_id"]) for g in current}
    # A provider drop of existing current-season fixtures is unsafe. Score
    # verification cannot reconstitute absent valid pregame candidates.
    missing_ids = {str(g["game_id"]) for g in old_current} - fresh_ids
    if missing_ids:
        raise ValueError(
            "Current-season source lost local fixtures; refusing replacement"
        )
    reconciled, kept = preserve_older_verified_finals(current, old_current)
    earlier = [g for g in existing if g["season"] != season]
    combined = earlier + reconciled
    # commit only after independent source validation and identity checks
    write_games(combined, target)
    _atomic_json(root / "current_season_refresh.json", {
        "season": season,
        "retrieved_at": now.isoformat(),
        "source": "sportsdataverse:espn_nba_schedules:v1",
        "source_manifest": manifest,
        "attempts": attempts, "games_current_season": len(reconciled),
        "verified_finals_preserved": kept,
        "research_only": True,
    })
    return {
        "season": season, "attempts": attempts,
        "current_fixtures": len(reconciled),
        "preserved_verified_finals": kept,
        "total_fixtures": len(combined),
    }


def _safe_error(exc: BaseException) -> str:
    # Never log arbitrary full URLs, HTML, authorization or response bodies.
    if isinstance(exc, BlockingIOError):
        return "NBA_TASK_ALREADY_RUNNING"
    if isinstance(exc, RuntimeError) and "refresh failed after bounded retry" in str(exc):
        return "NBA_SOURCE_UNAVAILABLE_AFTER_RETRY"
    if isinstance(exc, RuntimeError) and str(exc).startswith(
        "NBA injury archive needs the IANA timezone database"
    ):
        return "NBA_TZDATA_MISSING"
    return type(exc).__name__


def _mode_file(root: Path, mode: str) -> Path:
    if mode not in MODES:
        raise ValueError("Unsupported NBA automation mode")
    return root / ("automation_" + mode + ".json")


def _snapshot(mode: str, now: datetime, status: str,
              *, details: dict | None = None) -> dict:
    return {
        "mode": mode, "status": status, "checked_at": now.isoformat(),
        "details": details or {},
        "research_only": True, "public_publishing_enabled": False,
    }


def _advanced_sidecar(root: Path, now: datetime) -> dict:
    """Auxiliary source snapshots are separate from the trusted v1 ledger."""
    from basketball.research_injury_reports import capture_injury
    from basketball.research_advanced_model import run_shadow
    outcome = {}
    try:
        injury = capture_injury(root, now=now)
        outcome["injury"] = {
            "status": injury["status"], "published_at": injury["published_at"],
            "parsed_player_rows": injury["player_rows"],
            "extract_status": injury["extraction"]["status"],
        }
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        outcome["injury"] = {"status": "unavailable", "error": _safe_error(exc)}
    # Collect truly forward opening-week shadow evidence even if advanced
    # parquet releases lag. Kept separate from trusted v1 and its calibration.
    try:
        from basketball.research_coldstart import cycle as coldstart_cycle
        outcome["coldstart"] = coldstart_cycle(root, now=now)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        outcome["coldstart"] = {
            "status": "unavailable", "error": _safe_error(exc),
            "created": 0, "new_settlements": 0,
        }
    # Full-game totals, home margin and team points need independent
    # before-tipoff verification. This never scores sportsbook prices.
    try:
        from basketball.research_opening_score import cycle as score_projection_cycle
        outcome["opening_score"] = score_projection_cycle(root, now=now)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        outcome["opening_score"] = {
            "status": "unavailable", "error": _safe_error(exc),
            "created": 0, "new_settlements": 0,
        }
    candidate = root / "advanced" / "shadow_model.joblib"
    if not candidate.is_file():
        outcome["shadow"] = {"status": "not_configured"}
        return outcome
    try:
        # Refresh the current season at most every eight hours. The
        # advance data is optional and unavailable historical snapshots
        # do not modify previous v1/private research data.
        from basketball.research_current_advanced_v4 import refresh_current_advanced
        year = _current_season(now)
        manifest = root / "advanced" / f"team_{year}.manifest.json"
        stale = True
        if manifest.is_file():
            try:
                state = json.loads(manifest.read_text(encoding="utf-8"))
                when = datetime.fromisoformat(state["provenance_checked_at"])
                stale = (now - when.astimezone(timezone.utc)).total_seconds() >= 8*3600
            except (OSError, ValueError, KeyError, TypeError):
                stale = True
        if stale:
            try:
                fetched = refresh_current_advanced(home=root, season=year, now=now)
                outcome["advanced_refresh"] = {
                    "status": fetched["status"], "assets": fetched["assets"],
                }
            except (RuntimeError, ValueError, OSError) as exc:
                outcome["advanced_refresh"] = {
                    "status": "unavailable", "error": _safe_error(exc),
                }
        from basketball.research_injury_identity_v4 import injury_crosswalk
        outcome["injury_identity"] = injury_crosswalk(root, as_of=now)
        shadow = run_shadow(root, now=now)
        outcome["shadow"] = {
            "status": shadow["status"],
            "new_forecasts": shadow.get("created", 0),
            "settled": shadow.get("settled", 0),
        }
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        outcome["shadow"] = {"status": "unavailable", "error": _safe_error(exc)}
    return outcome


def run_automation(*, home: str | Path = Path("data/basketball/research"),
                   mode: str, now: datetime | None = None,
                   season_fetcher=fetch_public_seasons,
                   score_runner=settle_once, cycle_runner=run_cycle,
                   sleeper=time.sleep,
                   with_advanced: bool = False) -> dict:
    """Synchronous scheduled run; returns explicit succeeded/degraded/failed.

    Any previous verified final remains monotonic. An unsuccessful source
    refresh will *not* create fresh prospective picks from stale data.
    """
    if mode not in MODES:
        raise ValueError("Unsupported NBA automation mode")
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("NBA automation clock must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    root = Path(home)
    try:
        with exclusive_local_run(root):
            try:
                if mode == "score":
                    result = score_runner(home=root, now=timestamp)
                    # Hourly verification can settle a separate already
                    # captured cold-start shadow without fabricating forecasts.
                    try:
                        from basketball.research_coldstart import settle as settle_coldstart
                        result["coldstart_settlement"] = settle_coldstart(
                            root, now=timestamp)
                    except (ValueError, TypeError, OSError, RuntimeError) as exc:
                        result["coldstart_settlement"] = {
                            "status": "unavailable", "error": _safe_error(exc),
                            "new_settlements": 0,
                        }
                    try:
                        from basketball.research_opening_score import settle as settle_points
                        result["opening_score_settlement"] = settle_points(
                            root, now=timestamp)
                    except (ValueError, TypeError, OSError, RuntimeError) as exc:
                        result["opening_score_settlement"] = {
                            "status": "unavailable", "error": _safe_error(exc),
                            "new_settlements": 0,
                        }
                    score = result["scoreboard"]
                    status = "degraded" if score["status"] == "partial" else (
                        "idle" if score["status"] == "idle" else "succeeded")
                elif mode == "full":
                    result, retries = _retried(
                        lambda: cycle_runner(home=root, now=timestamp,
                                             days_ahead=2),
                        sleeper=sleeper)
                    result = {**result, "source_attempts": retries}
                    score = result["scoreboard"]
                    status = "degraded" if score["status"] == "partial" else "succeeded"
                else:
                    refresh = refresh_current_season(
                        root, now=timestamp, fetcher=season_fetcher,
                        sleeper=sleeper)
                    # Score settlement updates saved final history, then the
                    # original offline-cycle model generates *new* eligible
                    # private forecasts without re-fetching 11 seasons.
                    score_result = score_runner(home=root, now=timestamp)
                    result = cycle_runner(
                        home=root, now=timestamp, offline=True, days_ahead=2)
                    result = {
                        "refresh": refresh,
                        "scoreboard": score_result["scoreboard"],
                        "settlement": score_result["settlement"],
                        "new_forecasts": result["new_forecasts"],
                        "eligible_forecasts": result["eligible_forecasts"],
                        "readiness": result["readiness"],
                        "models_retrained": (
                            result["model_retrained"] or
                            result["score_models_retrained"]
                        ),
                    }
                    if with_advanced:
                        # Optional, non-critical sidecar: never let an
                        # independent public injury PDF or parquet outage
                        # block the original verified v1 pregame pipeline.
                        result["advanced_sidecar"] = _advanced_sidecar(root, timestamp)
                    status = (
                        "degraded" if score_result["scoreboard"]["status"] ==
                        "partial" else "succeeded"
                    )
                health = _snapshot(mode, timestamp, status, details={
                    "new_forecasts": result.get("new_forecasts", 0),
                    "new_settlements": result.get("settlement", {}).get(
                        "newly_settled", 0),
                    "source_attempts": result.get("source_attempts",
                                     result.get("refresh", {}).get("attempts")),
                    "scoreboard_status": result.get("scoreboard", {}).get(
                        "status"),
                    "advanced_sidecar": result.get("advanced_sidecar"),
                })
                _atomic_json(_mode_file(root, mode), health)
                return {"status": status, "mode": mode, "run": result,
                        "health": health, "local_only": True,
                        "public_publishing_enabled": False}
            except Exception as exc:
                health = _snapshot(mode, timestamp, "failed",
                                   details={"error": _safe_error(exc)})
                _atomic_json(_mode_file(root, mode), health)
                return {"status": "failed", "mode": mode,
                        "health": health, "local_only": True,
                        "public_publishing_enabled": False}
    except BlockingIOError:
        return {"status": "busy", "mode": mode,
                "reason": "NBA_TASK_ALREADY_RUNNING", "local_only": True,
                "public_publishing_enabled": False}


def reliability_from_home(home: str | Path, *,
                          now: datetime | None = None) -> dict:
    """Read-only schedule health. Missing task receipt is 'not_observed'."""
    root = Path(home)
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("NBA task health clock must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    tasks = {}
    for mode in MODES:
        path = _mode_file(root, mode)
        if not path.is_file():
            tasks[mode] = {"status": "not_observed", "age_hours": None}
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(record, dict) or record.get("mode") != mode or
                    record.get("research_only") is not True):
                raise ValueError("Invalid private task health record")
            last = datetime.fromisoformat(record["checked_at"])
            if last.tzinfo is None or last.utcoffset() is None:
                raise ValueError("Missing timezone in health record")
            age = (instant-last.astimezone(timezone.utc)).total_seconds()/3600
            status = (
                "clock_skew" if age < -5/60 else
                "stale" if age > STALE_HOURS[mode] else
                record["status"]
            )
            tasks[mode] = {
                "status": status, "last_result": record["status"],
                "age_hours": round(age, 2),
                "last_seen_at": last.astimezone(timezone.utc).isoformat(),
                "details": record.get("details") or {},
            }
        except (ValueError, TypeError, KeyError, OSError, OverflowError):
            tasks[mode] = {"status": "invalid", "age_hours": None}
    # Windows wrappers have their own receipts. A task can return exit 0
    # because a shared lock was busy; in that case automation_score.json
    # correctly remains unchanged. Also, a later manual success must NOT
    # hide an earlier scheduled failure. These separate facts are needed.
    scheduled_issues = []
    for mode in ("pregame", "score"):
        attempt_path = root / f"scheduled_{mode}_attempt.json"
        if not attempt_path.is_file():
            tasks[mode]["scheduled_attempt"] = {"status": "not_observed"}
            continue
        try:
            attempt = json.loads(attempt_path.read_text(encoding="utf-8-sig"))
            if (not isinstance(attempt, dict) or
                    attempt.get("mode") != mode or
                    attempt.get("scheduling") != "windows_task_runner" or
                    attempt.get("local_only") is not True):
                raise ValueError("Invalid scheduled task attempt")
            started = datetime.fromisoformat(attempt["started_at"])
            finished = datetime.fromisoformat(attempt["finished_at"])
            if (started.tzinfo is None or finished.tzinfo is None or
                    started > finished or finished > instant + timedelta(minutes=5)):
                raise ValueError("Invalid scheduler attempt clock")
            elapsed = (instant - finished.astimezone(timezone.utc)).total_seconds()/3600
            raw_status = str(attempt["status"])
            exit_code = int(attempt["process_exit_code"])
            if raw_status not in ("succeeded", "idle", "busy", "degraded",
                                  "failed", "unparsed_output"):
                raise ValueError("Unexpected scheduler attempt result")
            tasks[mode]["scheduled_attempt"] = {
                "status": raw_status,
                "finished_at": finished.astimezone(timezone.utc).isoformat(),
                "age_hours": round(elapsed, 2),
                "exit_code": exit_code,
                "performed_research": raw_status not in ("busy", "failed",
                                                         "unparsed_output"),
            }
            if exit_code != 0 or raw_status in ("failed", "degraded", "unparsed_output"):
                scheduled_issues.append(f"{mode}:scheduled_{raw_status}")
            elif raw_status == "busy":
                tasks[mode]["scheduled_attempt"]["note"] = (
                    "Skipped due to active NBA job; regular research receipt unchanged"
                )
        except (ValueError, TypeError, KeyError, OSError, OverflowError):
            tasks[mode]["scheduled_attempt"] = {"status": "invalid"}
            scheduled_issues.append(f"{mode}:scheduled_invalid")
    # Optional advanced feeds must never make the base paper task failed,
    # but a partially published box-score release deserves explicit
    # operator visibility rather than disappearing behind 'issues': [].
    advisories = []
    pregame_sidecar=(tasks.get("pregame") or {}).get("details",{}).get(
        "advanced_sidecar"
    ) or {}
    current_feed=pregame_sidecar.get("advanced_refresh") or {}
    if current_feed.get("status") in ("partial","blocked"):
        advisories.append("pregame:advanced_source_"+current_feed["status"])
    return {
        "status": "research_only",
        "generated_at": instant.isoformat(),
        "tasks": tasks,
        "issues": [
            mode + ":" + tasks[mode]["status"]
            for mode in MODES
            if tasks[mode]["status"] in ("degraded", "failed",
                                         "stale", "clock_skew", "invalid")
        ] + scheduled_issues,
        "advisories": advisories,
        "local_only": True, "no_writes": True,
        "public_publishing_enabled": False,
    }
