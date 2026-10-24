"""Read-only NBA result-source diagnostics, without settlement or file writes."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from basketball.research_data import read_games
from basketball.research_scoreboard import (
    _utc, download_scoreboard, parse_scoreboard, selected_dates, verify_finals,
)


def _now(when: datetime | None) -> datetime:
    instant = when or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("NBA diagnostic clock must be timezone-aware")
    return instant.astimezone(timezone.utc)


def inspect_recent(games: list[dict], *, now: datetime | None = None,
                   lookback_days: int = 7) -> dict:
    """Inspect score state, including whether earlier runs saved real finals."""
    if not 1 <= lookback_days <= 14:
        raise ValueError("NBA diagnostic lookback must be 1–14 days")
    instant = _now(now)
    lower = instant - timedelta(days=lookback_days)
    recent = [
        g for g in games if
        (start := _utc(g.get("start_utc"))) is not None and
        lower <= start <= instant
    ]
    recent.sort(key=lambda g: (g["start_utc"], str(g["game_id"])), reverse=True)
    finals = [g for g in recent if g["status"] == "final"]
    unfinished = [g for g in recent if g["status"] != "final"]
    sources = Counter(g.get("source", "unknown") for g in finals)
    return {
        "status": "research_only",
        "generated_at": instant.isoformat(),
        "lookback_days": lookback_days,
        "started_games": len(recent),
        "completed_finals": len(finals),
        "started_without_final": len(unfinished),
        "finals_by_source": dict(sorted(sources.items())),
        "dates_awaiting_result": selected_dates(games, instant),
        "recent_finals": [{
            "game_id": g["game_id"], "date": g["date"],
            "home_team": g["home_name"], "away_team": g["away_name"],
            "home_score": g["home_score"], "away_score": g["away_score"],
            "source": g["source"],
            "provider_game_id": g.get("verification_provider_game_id"),
        } for g in finals[:12]],
        "unverified_fixtures": [{
            "game_id": g["game_id"], "date": g["date"],
            "home_team": g["home_name"], "away_team": g["away_name"],
            "status": g["status"], "start_utc": g["start_utc"],
        } for g in unfinished[:12]],
        "local_only": True, "public_publishing_enabled": False,
    }


def inspect_home(home: str | Path, *, now: datetime | None = None) -> dict:
    """Zero network, zero writes. Read the current verified local snapshot."""
    return inspect_recent(read_games(Path(home) / "nba_games.jsonl"), now=now)


def probe_source(home: str | Path, *, day: str | None = None,
                 now: datetime | None = None,
                 espn_loader=None, nba_loader=None) -> dict:
    """Probe a known fixture date without saving, settling or retraining.

    Provider responses are checked against the actual LOCAL verified game
    identities. Probe success means at least one matched FINAL, not just 200.
    """
    instant = _now(now)
    games = read_games(Path(home) / "nba_games.jsonl")
    recent = inspect_recent(games, now=instant, lookback_days=14)
    if day is None:
        finals = [g for g in games if g["status"] == "final" and
                  _utc(g.get("start_utc")) is not None and
                  instant - timedelta(days=14) <= _utc(g["start_utc"]) <= instant]
        if not finals:
            return {
                "status": "no_recent_final_to_probe",
                "provider_checked": False, "results": {},
                "research_only": True, "no_writes": True,
            }
        most_recent = max(finals, key=lambda g: _utc(g["start_utc"]))
        day = most_recent["date"]
    target = date.fromisoformat(day)
    if not instant.date() - timedelta(days=14) <= target <= instant.date():
        raise ValueError("Probe date must be within the last 14 days")
    selected = [g for g in games if g["date"] == day]
    if not selected:
        raise ValueError("No locally identified NBA games on this date")

    result = {}
    try:
        payload = (espn_loader or download_scoreboard)(day)
        finals = parse_scoreboard(payload, retrieved_at=instant.isoformat())
        # verify_finals checks exact event id, home/away team ids and UTC start;
        # its returned mutated list is discarded, NEVER written.
        _, receipt = verify_finals(selected, finals)
        matches = receipt["already_final"] + receipt["verified_new_finals"]
        result["espn"] = {
            "status": "verified_match" if matches else "no_exact_final_match",
            "returned_final_events": len(finals),
            "exact_final_matches": matches,
        }
    except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
        result["espn"] = {
            "status": "error", "detail": str(exc)[:160]
            if isinstance(exc, RuntimeError) else type(exc).__name__,
        }

    try:
        from basketball.research_nba_cdn import (
            download_nba_cdn, match_nba_cdn_finals,
        )
        payload = (nba_loader or download_nba_cdn)(day)
        matched = match_nba_cdn_finals(
            payload, day, selected, retrieved_at=instant.isoformat())
        _, receipt = verify_finals(selected, matched)
        matches = receipt["already_final"] + receipt["verified_new_finals"]
        result["nba_official"] = {
            "status": "verified_match" if matches else "no_exact_final_match",
            "exact_final_matches": matches,
            "note": "Current NBA scoreboard day only, not a historical API",
        }
    except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
        result["nba_official"] = {
            "status": "unavailable_for_date", "detail": str(exc)[:160]
            if isinstance(exc, RuntimeError) else type(exc).__name__,
        }

    good = any(r["status"] == "verified_match" for r in result.values())
    return {
        "status": "verified" if good else "unverified",
        "date": day, "local_fixtures": len(selected),
        "local_recent_finals": recent["completed_finals"],
        "provider_checked": True, "results": result,
        "research_only": True, "no_writes": True,
    }
