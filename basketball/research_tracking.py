"""Immutable paper-forecast archive and verified final-score comparison.

These records are local-only, not bookmaker tickets. No odds, returns,
staking, publication or real-money settlement is supported here.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path


def write_paper_archive(predictions: list[dict], output: str | Path) -> dict:
    """Create an exclusive (never overwrite) record of pregame forecasts."""
    if not predictions:
        raise ValueError("No eligible pregame forecasts to archive")
    date_set = {p["date"] for p in predictions}
    model_set = {p["model_version"] for p in predictions}
    timestamps = {p["generated_at"] for p in predictions}
    if len(date_set) != 1 or len(model_set) != 1 or len(timestamps) != 1:
        raise ValueError("Mixed forecast batches are not permitted")
    when = datetime.fromisoformat(next(iter(timestamps)))
    if when.tzinfo is None:
        raise ValueError("An explicit UTC forecast timestamp is required")
    for p in predictions:
        kickoff = datetime.fromisoformat(str(p["start_utc"]).replace("Z", "+00:00"))
        if kickoff.tzinfo is None or kickoff <= when:
            raise ValueError("Prediction cannot be archived after tipoff")
        if (p["booking_code"] is not None or not p["research_only"] or
                not p["not_for_betting"] or p["bookmaker_odds_verified"]):
            raise ValueError("Only private nonbookable forecasts can be archived")
        if not 0 <= p["home_win_probability"] <= 1:
            raise ValueError("Invalid probability")
    payload = {
        "kind": "betsightly_nba_paper_v1", "date": next(iter(date_set)),
        "model": next(iter(model_set)), "generated_at": when.isoformat(),
        "publishing_enabled": False, "booking_enabled": False,
        "predictions": sorted(predictions, key=lambda p: p["game_id"]),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids silently changing predictions after scores arrive.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    return {"path": str(path), "sha256": payload["sha256"],
            "forecast_count": len(predictions), "research_only": True}


def score_paper_archive(archive_path: str | Path, games: list[dict]) -> dict:
    """Use only verified NBA final scores, never an inferred outcome."""
    with Path(archive_path).open(encoding="utf-8") as stream:
        archive = json.load(stream)
    if archive.get("kind") != "betsightly_nba_paper_v1":
        raise ValueError("Unrecognized NBA paper archive")
    payload = {key: value for key, value in archive.items() if key != "sha256"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(canonical.encode()).hexdigest() != archive.get("sha256"):
        raise ValueError("Paper archive checksum mismatch")
    if archive.get("publishing_enabled") or archive.get("booking_enabled"):
        raise ValueError("This is not an offline paper record")
    by_id = {g["game_id"]: g for g in games}
    settled = []
    pending = 0
    for p in archive["predictions"]:
        if not p["research_only"] or not p["not_for_betting"]:
            raise ValueError("Live forecast was mixed into private archive")
        kickoff = datetime.fromisoformat(str(p["start_utc"]).replace("Z", "+00:00"))
        generation = datetime.fromisoformat(p["generated_at"])
        if kickoff.tzinfo is None or generation.tzinfo is None or kickoff <= generation:
            raise ValueError("Forecast was not genuinely recorded pregame")
        game = by_id.get(p["game_id"])
        if (not game or game["status"] != "final"):
            pending += 1
            continue
        if (game["date"] != p["date"] or game["home_id"] != p["home_team_id"]
                or game["away_id"] != p["away_team_id"]):
            raise ValueError("Paper record and final scoreboard do not match")
        actual = int(game["home_score"] > game["away_score"])
        prob = float(p["home_win_probability"])
        settled.append((actual, prob))
    result = {
        "kind": "nba_private_paper_score_v1", "date": archive["date"],
        "paper_sha256": archive["sha256"], "count": len(archive["predictions"]),
        "settled": len(settled), "pending": pending, "research_only": True,
        "bookmaker_roi": None, "no_wagering": True,
    }
    if settled:
        eps = 1e-12
        result["accuracy"] = round(sum(int((p >= .5) == y) for y, p in settled) /
                                   len(settled), 5)
        result["brier"] = round(sum((p - y) ** 2 for y, p in settled) /
                                len(settled), 5)
        result["log_loss"] = round(sum(
            -(y * math.log(max(eps, min(1-eps, p))) +
              (1-y) * math.log(max(eps, min(1-eps, 1-p))))
            for y, p in settled) / len(settled), 5)
    return result
