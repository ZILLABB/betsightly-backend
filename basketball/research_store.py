"""Persistent, local-only NBA paper-test ledger.

SQLite lives under git-ignored data/basketball/research. Predictions are
insert-once, settlements are inserted-once, and source game IDs are validated.
The public backend is never connected to this ledger.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from basketball.research_tracking import score_paper_archive

DEFAULT_DB = Path("data/basketball/research/nba_paper.sqlite")


def _utc(value: str) -> datetime:
    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return timestamp.astimezone(timezone.utc)


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def open_ledger(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=15000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS forecasts(
            game_id TEXT PRIMARY KEY,
            fixture_date TEXT NOT NULL,
            start_utc TEXT NOT NULL,
            created_at TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_team_id TEXT NOT NULL,
            away_team_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            home_win_probability REAL NOT NULL CHECK(home_win_probability BETWEEN 0 AND 1),
            raw_json TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            inserted_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settlements(
            game_id TEXT PRIMARY KEY REFERENCES forecasts(game_id) ON DELETE RESTRICT,
            home_score INTEGER NOT NULL CHECK(home_score >= 0),
            away_score INTEGER NOT NULL CHECK(away_score >= 0),
            home_won INTEGER NOT NULL CHECK(home_won IN (0,1)),
            recorded_at TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL
        );
    """)
    return connection


def log_event(connection: sqlite3.Connection, kind: str, message: str) -> None:
    with connection:
        connection.execute(
            "INSERT INTO research_events(occurred_at,kind,message) VALUES (?,?,?)",
            (datetime.now(timezone.utc).isoformat(), kind, message[:500]),
        )


def save_forecasts(connection: sqlite3.Connection,
                   predictions: list[dict]) -> dict:
    """Insert pregame paper forecasts once; never update a previously saved pick."""
    inserted = skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    with connection:
        for item in predictions:
            if (item.get("research_only") is not True or
                    item.get("not_for_betting") is not True or
                    item.get("bookmaker_odds_verified") is not False or
                    item.get("booking_code") is not None):
                raise ValueError("A bookmaker-enabled or public prediction is forbidden")
            created = _utc(item["generated_at"])
            kickoff = _utc(item["start_utc"])
            if kickoff <= created:
                raise ValueError("Refusing an after-tipoff forecast")
            if created > datetime.now(timezone.utc):
                raise ValueError("Refusing a forecast timestamp in the future")
            p = float(item["home_win_probability"])
            if not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError("Nonfinite or out-of-range win probability")
            if abs(p + float(item["away_win_probability"]) - 1) > 0.00002:
                raise ValueError("Probabilities must sum to one")
            for key in ("game_id", "home_team_id", "away_team_id",
                        "home_team", "away_team", "model_version", "date"):
                if not str(item.get(key, "")).strip():
                    raise ValueError(f"Missing {key} for paper prediction")
            game_id = str(item["game_id"])
            serialized = _canonical(item)
            digest = hashlib.sha256(serialized.encode()).hexdigest()
            saved = connection.execute(
                "SELECT sha256 FROM forecasts WHERE game_id=?", (game_id,)
            ).fetchone()
            if saved:
                if saved["sha256"] != digest:
                    raise ValueError(
                        f"Forecast for {game_id} already exists and cannot be changed"
                    )
                skipped += 1
                continue
            connection.execute(
                """INSERT INTO forecasts(
                    game_id, fixture_date, start_utc, created_at, home_team,
                    away_team, home_team_id, away_team_id, model_version,
                    home_win_probability, raw_json, sha256, inserted_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (game_id, item["date"], kickoff.isoformat(),
                 created.isoformat(), item["home_team"], item["away_team"],
                 str(item["home_team_id"]), str(item["away_team_id"]),
                 item["model_version"], p, serialized, digest, now),
            )
            inserted += 1
    return {"inserted": inserted, "unchanged": skipped,
            "total_supplied": len(predictions), "research_only": True}


def settle_forecasts(connection: sqlite3.Connection, games: list[dict]) -> dict:
    """Only actual final scores settle matches with exact fixture identity."""
    by_id = {str(game["game_id"]): game for game in games}
    added = pending = already = 0
    with connection:
        rows = connection.execute("""
            SELECT f.*, s.game_id AS settlement_id
              FROM forecasts f LEFT JOIN settlements s USING(game_id)
             ORDER BY f.fixture_date, f.game_id
        """).fetchall()
        for row in rows:
            source = by_id.get(row["game_id"])
            if source is None or source["status"] != "final":
                if row["settlement_id"] is None:
                    pending += 1
                continue
            if (str(source["home_id"]) != row["home_team_id"] or
                    str(source["away_id"]) != row["away_team_id"] or
                    source["date"] != row["fixture_date"]):
                raise ValueError(f"Scoreboard fixture identity changed: {row['game_id']}")
            hs, vs = source["home_score"], source["away_score"]
            if not isinstance(hs, int) or not isinstance(vs, int) or hs == vs:
                raise ValueError("Missing, tied, or invalid NBA final scores")
            if row["settlement_id"] is not None:
                previous = connection.execute(
                    "SELECT home_score,away_score FROM settlements WHERE game_id=?",
                    (row["game_id"],),
                ).fetchone()
                if (previous["home_score"], previous["away_score"]) != (hs, vs):
                    raise ValueError(f"Final result changed after settlement: {row['game_id']}")
                already += 1
                continue
            connection.execute(
                """INSERT INTO settlements(game_id,home_score,away_score,
                    home_won,recorded_at,source) VALUES (?,?,?,?,?,?)""",
                (row["game_id"], hs, vs, int(hs > vs),
                 datetime.now(timezone.utc).isoformat(), source["source"]),
            )
            added += 1
    return {"newly_settled": added, "already_settled": already,
            "pending": pending, "research_only": True}


def performance_report(connection: sqlite3.Connection) -> dict:
    stats = connection.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN s.game_id IS NULL THEN 1 ELSE 0 END) AS pending
          FROM forecasts f LEFT JOIN settlements s ON f.game_id=s.game_id
    """).fetchone()
    rows = connection.execute("""
        SELECT f.home_win_probability AS p, s.home_won AS y
          FROM forecasts f JOIN settlements s ON f.game_id=s.game_id
         ORDER BY f.fixture_date, f.game_id
    """).fetchall()
    count = len(rows)
    result = {
        "status": "research_only", "market": "nba_moneyline",
        "forecast_count": stats["total"] or 0,
        "settled": count, "pending": stats["pending"] or 0,
        "bookmaker_odds_verified": False, "betting_roi": None,
    }
    if count:
        eps = 1e-12
        result.update({
            "accuracy": round(sum(int((r["p"] >= .5) == r["y"]) for r in rows) / count, 5),
            "brier": round(sum((r["p"] - r["y"]) ** 2 for r in rows) / count, 5),
            "log_loss": round(-sum(
                r["y"] * math.log(max(eps, min(1-eps, r["p"]))) +
                (1-r["y"]) * math.log(max(eps, min(1-eps, 1-r["p"])))
                for r in rows
            ) / count, 5),
        })
    return result


def list_forecasts(connection: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = connection.execute("""
        SELECT f.game_id,f.fixture_date,f.start_utc,f.created_at,
               f.home_team,f.away_team,f.model_version,
               f.home_win_probability, f.sha256, s.home_score,
               s.away_score, s.home_won, s.recorded_at
          FROM forecasts f LEFT JOIN settlements s ON f.game_id=s.game_id
         ORDER BY f.start_utc DESC LIMIT ?
    """, (min(1000, max(1, int(limit))),)).fetchall()
    return [dict(row) for row in rows]


def latest_events(connection: sqlite3.Connection, limit: int = 25) -> list[dict]:
    rows = connection.execute(
        "SELECT occurred_at,kind,message FROM research_events ORDER BY id DESC LIMIT ?",
        (min(100, max(1, int(limit))),),
    ).fetchall()
    return [dict(row) for row in rows]
