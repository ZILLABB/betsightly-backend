"""Private NBA immutable research bundle: local exporter and server verifier.

NBA files are copied exactly, retaining the original SHA256/UTC timestamps.
The provider source rows are restricted to the archived fixture IDs, not the
historical training data. SHA hashes provide change detection, not independent
proof of when a record was originally written; private admin auth still applies.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from basketball.research_admin_board import board_from_home
from basketball.research_coldstart import _json, _read_ledger
from basketball.research_data import read_games, write_games
from basketball.research_coldstart import FILENAME as MONEY, RESULTS as MONEY_FINALS
from basketball.research_opening_score import FORECASTS as SCORE, FINALS as SCORE_FINALS
from basketball.research_early_advanced_ops import (
    FORECASTS as ADVANCED, FINALS as ADVANCED_FINALS,
)

VERSION = "betsightly-nba-private-archive-v1"
MAX_BYTES = 750_000
MAX_FIXTURES = 120
ARCHIVES = {
    "moneyline": MONEY, "opening_score": SCORE, "early_advanced": ADVANCED,
    "moneyline_finals": MONEY_FINALS, "opening_score_finals": SCORE_FINALS,
    "early_advanced_finals": ADVANCED_FINALS,
}
FORECAST_KINDS = ("moneyline", "opening_score", "early_advanced")
FINAL_KINDS = ("moneyline_finals", "opening_score_finals",
               "early_advanced_finals")


def _digest(bundle):
    return hashlib.sha256(_json(bundle).encode("utf-8")).hexdigest()


def export_bundle(home):
    """Construct a portable copy of genuine local, originally archived rows."""
    root = Path(home)
    board = board_from_home(root)
    if board["status"] != "recorded_research_only":
        raise ValueError("Only integrity-verified NBA research can be exported")
    ledgers = {key: _read_ledger(root / name)
               for key, name in ARCHIVES.items()}
    ids = {str(g["game_id"]) for kind in FORECAST_KINDS
           for g in ledgers[kind]}
    if not ids or len(ids) > MAX_FIXTURES:
        raise ValueError("NBA evidence cohort is empty or exceeds import limit")
    games = [g for g in read_games(root / "nba_games.jsonl")
             if str(g["game_id"]) in ids]
    if len(games) != len(ids):
        raise ValueError("Missing verified source NBA fixture")
    output = {
        "version": VERSION, "fixtures": games,
        "records": ledgers, "research_only": True,
    }
    if len(_json(output).encode("utf-8")) > MAX_BYTES:
        raise ValueError("NBA research archive exceeds per-import byte limit")
    return output


def _validated_records(value, *, kind):
    if not isinstance(value, list) or len(value) > MAX_FIXTURES:
        raise ValueError("NBA archive ledger count invalid: " + kind)
    seen = set()
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("game_id"), str):
            raise ValueError("NBA signed record has invalid identity")
        gid = row["game_id"]
        if gid in seen:
            raise ValueError("NBA archive contains duplicate ledger fixture")
        seen.add(gid)
    return seen


def inspect_bundle(bundle):
    """Verify original hashes, timestamp guards and across-model identities.

    No database writes. The synthetic temporary directory exists only during
    validation and is not served by either the admin API or football routes.
    """
    if not isinstance(bundle, dict) or set(bundle) != {
        "version", "fixtures", "records", "research_only"
    } or bundle["version"] != VERSION or bundle["research_only"] is not True:
        raise ValueError("Unsupported private NBA archive schema")
    if len(_json(bundle).encode("utf-8")) > MAX_BYTES:
        raise ValueError("NBA research archive exceeds upload size limit")
    games = bundle["fixtures"]
    items = bundle["records"]
    if not isinstance(games, list) or not 1 <= len(games) <= MAX_FIXTURES:
        raise ValueError("NBA archive fixture count invalid")
    if not isinstance(items, dict) or set(items) != set(ARCHIVES):
        raise ValueError("NBA archive ledger set incomplete")
    game_ids = [str(g.get("game_id")) for g in games
                if isinstance(g, dict)]
    if len(game_ids) != len(games) or len(set(game_ids)) != len(game_ids):
        raise ValueError("NBA archive game IDs invalid")
    saved_ids = set()
    for kind in ARCHIVES:
        ids = _validated_records(items[kind], kind=kind)
        if kind in FORECAST_KINDS:
            saved_ids.update(ids)
        else:
            if not ids.issubset(_validated_records(
                items[kind[:-7]], kind=kind[:-7]
            )):
                raise ValueError("NBA final references an unsaved forecast")
    if not saved_ids or set(game_ids) != saved_ids:
        raise ValueError("NBA archive must include exactly forecasted fixtures")
    with tempfile.TemporaryDirectory(prefix="nba-archive-verify-") as folder:
        root = Path(folder)
        write_games(games, root / "nba_games.jsonl")
        for kind, filename in ARCHIVES.items():
            if items[kind]:
                (root / filename).write_text(
                    "".join(_json(row) + "\n" for row in items[kind]),
                    encoding="utf-8"
                )
        board = board_from_home(root)
        if board["status"] != "recorded_research_only":
            raise ValueError("NBA archive contains invalid signed predictions")
        if board["summary"]["fixtures"] != len(games):
            raise ValueError("NBA archive fixture counts did not reconcile")
        return board


def unchanged_prior(prior, latest):
    """Reject deletions, rewrites, removed finals and provider score conflicts.

    New games, genuinely later verified finals and source freshness changes
    are allowed; original forecast SHA256 records are append-only.
    """
    if prior is None:
        return
    old = prior["records"]
    new = latest["records"]
    for key in ARCHIVES:
        next_items = {r["game_id"]: r for r in new[key]}
        for row in old[key]:
            if next_items.get(row["game_id"]) != row:
                raise ValueError("NBA archive may not overwrite or delete signed records")
    by_id = {str(g["game_id"]): g for g in latest["fixtures"]}
    for previous in prior["fixtures"]:
        updated = by_id.get(str(previous["game_id"]))
        if updated is None:
            raise ValueError("NBA archive may not remove a source fixture")
        for field in ("date", "season", "home_id", "away_id", "start_utc"):
            if previous[field] != updated[field]:
                raise ValueError("NBA fixture identity or kickoff cannot be rewritten")
        if previous["status"] == "final":
            if (updated["status"] != "final" or
                updated["home_score"] != previous["home_score"] or
                updated["away_score"] != previous["away_score"]):
                raise ValueError("NBA verified source final cannot be rewritten")


def report_from_bundle(bundle):
    """Read-only dashboard data, independently reverified on each request."""
    return inspect_bundle(bundle)
