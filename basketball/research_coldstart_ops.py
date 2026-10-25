"""Private NBA opening-week model first-final operational closeout.

No model unpickling, no forecast writes, no new score fetch and no bookmaking.
All statuses derive from immutable original hashes and authoritative local
NBA finals. Previously accepted forecasts are never revised or backfilled.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from basketball.research_coldstart import (
    FILENAME, RESULTS, _read_ledger, _now, audit,
)
from basketball.research_data import read_games
from basketball.research_readiness import _timestamp

NBA_REGULAR_SEASON_TEAM_GAMES = 82
FINAL_GRACE_HOURS = 4


def calendar_anomalies(games, *, season=2026):
    """Flag >82 regular-season rows per club for source classification review.

    Some providers tag additional tournament fixtures as regular season. This
    is an audit, not proof of a bad fixture or authority to delete game rows.
    """
    teams = defaultdict(list)
    for g in games:
        if (g["season"] != season or g["status"] != "final"
            or g["postseason"]):
            continue
        for side in ("home", "away"):
            teams[str(g[f"{side}_id"])].append({
                "game_id": str(g["game_id"]), "date": g["date"],
                "opponent": g["away_name"] if side == "home" else g["home_name"],
                "team": g[f"{side}_name"],
            })
    anomalous = []
    for team_id, records in sorted(teams.items()):
        if len(records) <= NBA_REGULAR_SEASON_TEAM_GAMES:
            continue
        records.sort(key=lambda item: (item["date"], item["game_id"]))
        anomalous.append({
            "team_id": team_id,
            "team_name": records[-1]["team"],
            "completed_season_games": len(records),
            "above_standard_regulation_count": (
                len(records) - NBA_REGULAR_SEASON_TEAM_GAMES),
            "recent_game_samples": records[-4:],
        })
    return {
        "season": season,
        "standard_nba_regular_season_games": NBA_REGULAR_SEASON_TEAM_GAMES,
        "teams_over_standard_count": len(anomalous),
        "anomalies": anomalous[:15],
        "provider_classification_review_needed": bool(anomalous),
        "not_proof_of_corruption": True,
        "automatic_source_mutation": False,
    }


def closeout(home, *, now=None):
    instant = _now(now)
    root = Path(home)
    verified = audit(root, now=instant)
    summary = {
        "status": verified["status"],
        "research_only": True,
        "generated_at": instant.isoformat(),
        "method": verified["method"],
        "forecast_count": verified.get("forecast_count"),
        "verified_settlements": verified.get("verified_settlements"),
        "pending": verified.get("pending"),
        "prospective_paired_metrics": verified.get("prospective_paired_metrics"),
        "last_30_verified": verified.get("last_30_verified"),
        "integrity_errors": verified.get("integrity_errors", []),
        "operational_pending_states": None,
        "upcoming_samples": [],
        "settled_samples": [],
        "verified_directional_correct": None,
        "verified_directional_incorrect": None,
        "overdue_unverified_final_count": None,
        "calendar_quality": None,
        "no_writes": True, "bookmaker_odds_verified": False,
        "public_publishing_enabled": False, "trusted_v1_changed": False,
        "commercial_use_cleared": False,
    }
    if verified["status"] == "integrity_failed":
        return summary
    source = root / "nba_games.jsonl"
    if not source.is_file():
        summary["status"] = "source_missing"
        return summary
    try:
        games = read_games(source)
        forecasts = _read_ledger(root / FILENAME)
        settled = {str(r["game_id"]): r for r in _read_ledger(root / RESULTS)}
    except (ValueError, TypeError, OSError, UnicodeError):
        summary["status"] = "integrity_failed"
        summary["integrity_errors"] = ["invalid_local_source_after_audit"]
        return summary
    by_id = {str(g["game_id"]): g for g in games}
    counts = Counter()
    waiting, done = [], []
    correct = incorrect = 0
    for f in sorted(forecasts, key=lambda row: (row["start_utc"], row["game_id"])):
        ident = str(f["game_id"])
        game = by_id[ident]  # all present and identity-checked by audit()
        kickoff = _timestamp(f["start_utc"])
        label = None
        if ident in settled:
            label = "verified_settled"
            outcome = int(game["home_score"] > game["away_score"])
            correct += int((f["probability_home_win"] >= .5) == bool(outcome))
            incorrect += int((f["probability_home_win"] >= .5) != bool(outcome))
            done.append({
                "game_id": ident, "home": f["home_team"],
                "away": f["away_team"], "tipoff_utc": f["start_utc"],
                "home_win_probability": f["probability_home_win"],
                "actual_home_win": bool(outcome),
                "home_score": game["home_score"],
                "away_score": game["away_score"],
                "settled_at": settled[ident]["settled_at"],
                "result_status": "verified_final",
            })
        elif game["status"] == "final":
            label = "final_available_pending_grade"
        elif kickoff > instant:
            label = "not_started"
        elif instant > kickoff + timedelta(hours=FINAL_GRACE_HOURS):
            label = "overdue_unverified_final"
        else:
            label = "awaiting_final_score"
        counts[label] += 1
        if label != "verified_settled":
            waiting.append({
                "game_id": ident, "home": f["home_team"],
                "away": f["away_team"], "tipoff_utc": f["start_utc"],
                "state": label,
                "verified_final_available": game["status"] == "final",
            })
    summary.update({
        "operational_pending_states": dict(sorted(counts.items())),
        "upcoming_samples": waiting[:16],
        "settled_samples": done[-15:],
        "verified_directional_correct": correct,
        "verified_directional_incorrect": incorrect,
        "overdue_unverified_final_count": counts["overdue_unverified_final"],
        "calendar_quality": calendar_anomalies(games, season=2026),
    })
    return summary
