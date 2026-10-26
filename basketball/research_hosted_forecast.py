"""Staging-only NBA opening-week cloud forecast batch (paper research).

Reuses original, historically anchored moneyline/score research models.
Historical seasons are downloaded into disposable memory/storage, and ONLY
genuine signed before-tipoff forecast rows enter the append-only NBA archive.
No public predictions, bookmaker edges, speculative finals or new advanced
score model without the separate archived boxscore inputs.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from basketball.research_coldstart import (
    _json, _now, capture as capture_money, FILENAME as MONEY,
)
from basketball.research_data import write_games
from basketball.research_opening_score import (
    capture as capture_score, FORECASTS as SCORE,
)
from basketball.research_private_bundle import (
    ARCHIVES, MAX_FIXTURES, _digest, export_bundle, inspect_bundle,
)
from basketball.research_private_store import (
    SessionLocal, latest_bundle, import_bundle, hosted_board,
)
from basketball.research_public_data import fetch_public_seasons


def forecast_hosted(*, now=None, season_loader=None, session_factory=None):
    instant = _now(now)
    session = (session_factory or SessionLocal)()
    try:
        prior = latest_bundle(session)
    finally:
        session.close()
    if prior is None:
        raise ValueError("NBA_ARCHIVE_MUST_BE_IMPORTED_FIRST")
    inspect_bundle(prior)
    if len(prior["fixtures"]) >= MAX_FIXTURES:
        return {
            "status": "archive_capacity_reached",
            "max_fixtures": MAX_FIXTURES, "new_forecasts": {},
            "archive_digest": _digest(prior), "research_only": True,
            "not_bookable": True,
        }
    current_year = instant.year + (1 if instant.month >= 7 else 0)
    # Reuse previously checked public schedule normalization.
    dataset, manifests = (season_loader or fetch_public_seasons)(
        [current_year - 1, current_year]
    )
    if len(manifests) != 2:
        raise ValueError("NBA_HISTORICAL_SOURCE_MANIFEST_INCOMPLETE")
    existing = {str(x["game_id"]): x for x in prior["fixtures"]}
    ids = set()
    joined = []
    for row in dataset:
        gid = str(row["game_id"])
        if gid in ids:
            raise ValueError("NBA_PUBLIC_SCHEDULE_DUPLICATE")
        ids.add(gid)
        # Retain all historical signed fixture identities and scores exactly.
        joined.append(existing.get(gid, row))
    for gid, value in existing.items():
        if gid not in ids:
            joined.append(value)
    previous = [g for g in joined if
                g["season"] == current_year - 1 and g["status"] == "final"]
    upcoming = [g for g in joined if
                g["season"] == current_year and g["status"] == "scheduled"
                and not g.get("postseason") and g.get("start_utc")]
    if len(previous) < 200:
        raise ValueError("NBA_PREVIOUS_SEASON_FINAL_SAMPLE_INCOMPLETE")
    if not any(
        instant + timedelta(minutes=10) <
        datetime.fromisoformat(g["start_utc"].replace("Z", "+00:00")) <=
        instant + timedelta(hours=48) for g in upcoming
    ):
        return {
            "status": "no_upcoming_eligible_source_window",
            "new_forecasts": {}, "archive_digest": _digest(prior),
            "research_only": True, "not_bookable": True,
        }

    with TemporaryDirectory(prefix="nba-hosted-forecast-") as folder:
        root = Path(folder)
        write_games(joined, root / "nba_games.jsonl")
        for kind, filename in ARCHIVES.items():
            rows = prior["records"][kind]
            if rows:
                (root / filename).write_text(
                    "".join(_json(x) + "\n" for x in rows),
                    encoding="utf-8",
                )
        before = {
            "moneyline": len(prior["records"]["moneyline"]),
            "original_score": len(prior["records"]["opening_score"]),
        }
        money = capture_money(root, now=instant)
        score = capture_score(root, now=instant)
        if money["status"] == "integrity_failed" or score["status"] == "integrity_failed":
            raise ValueError("NBA_EXISTING_SIGNED_FORECAST_VALIDATION_FAILED")
        # A stale dataset is NEVER labelled as fresh forecast evidence.
        if "source_not_fresh" in (money["status"], score["status"]):
            return {
                "status": "source_not_fresh", "new_forecasts": {},
                "archive_digest": _digest(prior), "research_only": True,
                "not_bookable": True,
            }
        updated = export_bundle(root)
        changed = {
            "moneyline": len(updated["records"]["moneyline"]) - before["moneyline"],
            "original_score": (
                len(updated["records"]["opening_score"]) - before["original_score"]
            ),
            "advanced_score": 0,
        }
        if len(updated["fixtures"]) > MAX_FIXTURES:
            raise ValueError("NBA_ARCHIVE_CAPACITY_REACHED_WITHOUT_OVERWRITE")

    if _digest(updated) == _digest(prior):
        return {
            "status": "no_new_eligible_forecasts", "new_forecasts": changed,
            "archive_digest": _digest(prior), "research_only": True,
            "not_bookable": True,
        }
    stored = import_bundle(updated)
    reread = hosted_board()
    if reread is None or reread.get("archive_digest") != stored["digest"]:
        raise RuntimeError("NBA_HOSTED_FORECAST_READBACK_MISMATCH")
    return {
        "status": "archived_before_tipoff",
        "new_forecasts": changed, "archive_digest": stored["digest"],
        "fixture_count": stored["fixture_count"],
        "research_only": True, "not_bookable": True,
        "advanced_model_recomputed": False,
        "historical_provider_manifest_count": len(manifests),
    }
