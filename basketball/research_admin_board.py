"""Read-only private NBA board from SAVED, hashed pregame experiments.

The board only lists observed predictions. It never generates predictions,
opens betting markets or changes football/published records.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

from basketball.research_coldstart import (
    FILENAME as MONEY_FILE, RESULTS as MONEY_FINALS,
    _read_ledger, _now, audit as audit_money,
)
from basketball.research_opening_score import (
    FORECASTS as SCORE_FILE, FINALS as SCORE_FINALS,
    audit as audit_score,
)
from basketball.research_early_advanced_ops import (
    FORECASTS as ADVANCED_FILE, FINALS as ADVANCED_FINALS,
    audit as audit_advanced,
)
from basketball.research_data import read_games
from basketball.research_readiness import _timestamp

WAT = timezone(timedelta(hours=1))


def _map(rows):
    mapped = {}
    for row in rows:
        gid = str(row["game_id"])
        if gid in mapped:
            raise ValueError("Duplicate archived NBA fixture: " + gid)
        mapped[gid] = row
    return mapped


def board_from_home(home, *, now=None):
    """Verify ledgers and join by stable fixture IDs; fail closed on corruption.

    Readiness is intentionally separated from security: local files cannot
    simply be copied from an admin browser and public API is never involved.
    """
    root = Path(home)
    instant = _now(now)
    if not (root / "nba_games.jsonl").is_file():
        return {
            "status": "data_not_configured", "games": [], "summary": {},
            "research_only": True, "private": True, "no_writes": True,
            "bookmaker_verified": False,
        }
    reports = {
        "moneyline": audit_money(root, now=instant),
        "original_score": audit_score(root, now=instant),
        "advanced_score": audit_advanced(root, now=instant),
    }
    if any(r.get("status") == "integrity_failed" for r in reports.values()):
        return {
            "status": "integrity_failed", "games": [], "summary": {},
            "failed_models": [k for k, v in reports.items()
                              if v.get("status") == "integrity_failed"],
            "research_only": True, "private": True, "no_writes": True,
            "bookmaker_verified": False,
        }
    source = _map(read_games(root / "nba_games.jsonl"))
    archive = {
        "moneyline": _map(_read_ledger(root / MONEY_FILE)),
        "original_score": _map(_read_ledger(root / SCORE_FILE)),
        "advanced_score": _map(_read_ledger(root / ADVANCED_FILE)),
    }
    closed = {
        "moneyline": _map(_read_ledger(root / MONEY_FINALS)),
        "original_score": _map(_read_ledger(root / SCORE_FINALS)),
        "advanced_score": _map(_read_ledger(root / ADVANCED_FINALS)),
    }
    ids = set().union(*(set(v) for v in archive.values()))
    games = []
    for gid in ids:
        g = source.get(gid)
        if not g:
            raise ValueError("NBA fixture not found in verified source")
        m, s, a = (archive[k].get(gid) for k in (
            "moneyline", "original_score", "advanced_score"))
        tip = _timestamp(g["start_utc"])
        if tip is None:
            raise ValueError("Unknown NBA fixture kickoff")
        for row in (m, s, a):
            if row is None:
                continue
            if any(str(row[key]) != str(g[key]) for key in (
                "home_id", "away_id", "season", "date")):
                raise ValueError("NBA archived fixture identity mismatch")
            if _timestamp(row["start_utc"]) != tip:
                raise ValueError("NBA archived kickoff mismatch")
        settled_models = {
            k: gid in val for k, val in closed.items()
        }
        if g["status"] == "final" and any(
            gid in archive[k] and not settled_models[k] for k in archive
        ):
            state = "final_pending_grade"
        elif g["status"] == "final" and any(settled_models.values()):
            state = "verified_settled"
        elif tip > instant:
            state = "upcoming"
        else:
            state = "awaiting_verified_final"
        home_p = m.get("probability_home_win") if m else None
        games.append({
            "game_id": gid, "date": g["date"],
            "tipoff_utc": tip.isoformat(),
            "tipoff_wat": tip.astimezone(WAT).isoformat(),
            "home_team": g["home_name"], "away_team": g["away_name"],
            "status": state,
            "actual_home_score": g["home_score"] if g["status"] == "final"
                and any(settled_models.values()) else None,
            "actual_away_score": g["away_score"] if g["status"] == "final"
                and any(settled_models.values()) else None,
            "home_win_probability": home_p,
            "projected_home_points": s["predicted_home_points"] if s else None,
            "projected_away_points": s["predicted_away_points"] if s else None,
            "projected_total": s["predicted_total"] if s else None,
            "projected_home_margin": s["predicted_home_margin"] if s else None,
            "advanced_total": a["predicted_total"] if a else None,
            "advanced_home_margin": a["predicted_home_margin"] if a else None,
            "recorded_models": {k: gid in val for k, val in archive.items()},
            "settled_models": settled_models,
            "bookmaker_market_verified": False,
            "sportybet_code": None,
        })
    games.sort(key=lambda g: (g["tipoff_utc"], g["game_id"]))
    counts = {k: len(v) for k, v in archive.items()}
    settled = {k: len(v) for k, v in closed.items()}
    return {
        "status": "recorded_research_only",
        "generated_at": instant.isoformat(),
        "summary": {
            "fixtures": len(games), "forecasts": counts,
            "verified_settlements": settled,
            "pending_fixtures": sum(x["status"] != "verified_settled"
                                    for x in games),
        },
        "games": games, "research_only": True,
        "private": True, "no_writes": True,
        "model_promotion_approved": False,
        "bookmaker_verified": False, "booking_codes_available": False,
        "commercial_data_rights_cleared": False,
    }
