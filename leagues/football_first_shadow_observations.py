"""Prospective observations for the football-first Match Result shadow model.

Every accepted observation is immutable first-write-wins evidence captured
before kickoff. Historical replay never enters this table.
"""
from __future__ import annotations

import hashlib
import math
import os
import uuid
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, MetaData, String, Table,
    UniqueConstraint, inspect, select,
)
from sqlalchemy.exc import IntegrityError

from database import engine
from leagues import football_first_shadow as shadow

TARGET = "match_result"
PRODUCTION_OVERRIDE_FLAG = "FOOTBALL_FIRST_SHADOW_PRODUCTION_ENABLED"
MIN_PROSPECTIVE_REVIEW = 300

ROBUST_MATCH_RESULT_LEAGUES = {
    "uefa.champions": 2,
    "uefa.europa": 3,
    "conmebol.sudamericana": 11,
    "eng.1": 39,
    "eng.2": 40,
    "fra.1": 61,
    "fra.2": 62,
    "bra.1": 71,
    "ger.1": 78,
    "ned.1": 88,
    "por.1": 94,
    "nor.1": 103,
    "swe.1": 113,
    "den.1": 119,
    "arg.1": 128,
    "ita.1": 135,
    "ita.2": 136,
    "esp.1": 140,
    "esp.2": 141,
    "bel.1": 144,
    "chn.1": 169,
    "sco.1": 179,
    "gre.1": 197,
    "tur.1": 203,
    "aut.1": 218,
    "fin.1": 244,
    "usa.1": 253,
    "mex.1": 262,
    "rou.1": 283,
}

MIXED_MATCH_RESULT_LEAGUES = {
    "conmebol.libertadores": 13,
    "ger.2": 79,
    "jpn.1": 98,
    "pol.1": 106,
    "uefa.europa.conf": 848,
}

metadata = MetaData()
observations = Table(
    "football_first_shadow_observations",
    metadata,
    Column("observation_id", String(36), primary_key=True),
    Column("observation_key", String(64), nullable=False),
    Column("model_version", String(96), nullable=False, index=True),
    Column("feature_version", String(64), nullable=False),
    Column("target", String(32), nullable=False),
    Column("fixture_id", String(128), nullable=False, index=True),
    Column("league_slug", String(80), nullable=False, index=True),
    Column("api_league_id", Integer, nullable=False),
    Column("competition", String(160)),
    Column("home_team", String(180), nullable=False),
    Column("away_team", String(180), nullable=False),
    Column("kickoff", DateTime(timezone=True), nullable=False, index=True),
    Column("observed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("champion_away", Float, nullable=False),
    Column("champion_draw", Float, nullable=False),
    Column("champion_home", Float, nullable=False),
    Column("challenger_away", Float, nullable=False),
    Column("challenger_draw", Float, nullable=False),
    Column("challenger_home", Float, nullable=False),
    Column("home_history", Integer),
    Column("away_history", Integer),
    Column("status", String(24), nullable=False, index=True),
    Column("settled_at", DateTime(timezone=True)),
    Column("home_score", Integer),
    Column("away_score", Integer),
    Column("outcome_class", Integer),
    Column("settlement_source", String(80)),
    UniqueConstraint(
        "observation_key",
        name="uq_football_first_shadow_observation_key",
    ),
)


reviews = Table(
    "football_first_shadow_reviews",
    metadata,
    Column("review_id", String(36), primary_key=True),
    Column("model_version", String(96), nullable=False, index=True),
    Column("evidence_n", Integer, nullable=False),
    Column("evidence_status", String(64), nullable=False),
    Column("decision", String(64), nullable=False, index=True),
    Column("reviewer", String(160)),
    Column("note", String(2000)),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)

REVIEW_DECISIONS = {
    "KEEP_CHAMPION",
    "REJECT_CHALLENGER",
    "APPROVE_FOR_PROMOTION_IMPLEMENTATION",
}

_SETTLEMENT_LOCK = threading.Lock()
_SETTLEMENT_LAST_STARTED = 0.0
SETTLEMENT_COOLDOWN_SECONDS = 15 * 60


def _truthy(name: str) -> bool:
    return str(os.getenv(name, "false")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def collection_allowed() -> tuple[bool, str]:
    if not shadow.enabled():
        return False, "feature_flag_disabled"
    environment = str(os.getenv("ENVIRONMENT", "")).strip().lower()
    if environment == "production" and not _truthy(PRODUCTION_OVERRIDE_FLAG):
        return False, "production_override_disabled"
    return True, "enabled"


def table_exists(db_engine=engine) -> bool:
    try:
        return inspect(db_engine).has_table(observations.name)
    except Exception:
        return False


def ensure_table(db_engine=engine) -> None:
    metadata.create_all(
        db_engine,
        tables=[observations, reviews],
        checkfirst=True,
    )


def _utc(value) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _normalize_three_way(probabilities: dict | None) -> dict | None:
    probabilities = probabilities or {}
    try:
        values = {
            "away_win": float(probabilities["away_win"]),
            "draw": float(probabilities["draw"]),
            "home_win": float(probabilities["home_win"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value < 0 for value in values.values()):
        return None
    total = sum(values.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in values.items()}


def _observation_key(model_version: str, fixture_id: str) -> str:
    raw = f"{model_version}|{TARGET}|{fixture_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def allowed_fixture(fixture: dict) -> tuple[bool, int | None, str]:
    slug = str(fixture.get("league_slug") or "")
    if slug in MIXED_MATCH_RESULT_LEAGUES:
        return False, MIXED_MATCH_RESULT_LEAGUES[slug], "mixed_offline_evidence"
    league_id = ROBUST_MATCH_RESULT_LEAGUES.get(slug)
    if league_id is None:
        return False, None, "not_in_robust_allowlist"
    return True, league_id, "robust_runtime_candidate"


def build_observation(
    fixture: dict,
    champion_model: dict,
    challenger: dict,
    *,
    observed_at: datetime,
) -> tuple[dict | None, str]:
    allowed, league_id, reason = allowed_fixture(fixture)
    if not allowed:
        return None, reason
    if challenger.get("status") != "READY":
        return None, str(challenger.get("status") or "challenger_not_ready").lower()

    fixture_id = str(fixture.get("event_id") or "").strip()
    if not fixture_id:
        return None, "missing_fixture_id"

    kickoff = _utc(fixture.get("commence_time"))
    observed = _utc(observed_at)
    if kickoff is None or observed is None:
        return None, "invalid_time"
    if observed >= kickoff:
        return None, "fixture_started"

    champion = _normalize_three_way(champion_model.get("probabilities"))
    candidate = _normalize_three_way(challenger.get("probabilities"))
    if champion is None:
        return None, "champion_probability_unavailable"
    if candidate is None:
        return None, "challenger_probability_unavailable"

    model_version = str(challenger.get("model_version") or "").strip()
    feature_version = str(challenger.get("feature_version") or "").strip()
    if not model_version or not feature_version:
        return None, "missing_model_provenance"

    home = str((fixture.get("home") or {}).get("name") or "").strip()
    away = str((fixture.get("away") or {}).get("name") or "").strip()
    if not home or not away:
        return None, "missing_team_identity"

    evidence = challenger.get("feature_evidence") or {}
    return {
        "observation_id": str(uuid.uuid4()),
        "observation_key": _observation_key(model_version, fixture_id),
        "model_version": model_version,
        "feature_version": feature_version,
        "target": TARGET,
        "fixture_id": fixture_id,
        "league_slug": str(fixture.get("league_slug") or ""),
        "api_league_id": int(league_id),
        "competition": str(fixture.get("league") or "")[:160] or None,
        "home_team": home[:180],
        "away_team": away[:180],
        "kickoff": kickoff,
        "observed_at": observed,
        "champion_away": champion["away_win"],
        "champion_draw": champion["draw"],
        "champion_home": champion["home_win"],
        "challenger_away": candidate["away_win"],
        "challenger_draw": candidate["draw"],
        "challenger_home": candidate["home_win"],
        "home_history": (
            int(evidence["home_history"])
            if evidence.get("home_history") is not None else None
        ),
        "away_history": (
            int(evidence["away_history"])
            if evidence.get("away_history") is not None else None
        ),
        "status": "pending",
    }, "ready"


def observe_fixture(
    fixture: dict,
    champion_model: dict,
    history,
    *,
    observed_at: datetime | None = None,
    db_engine=engine,
) -> dict:
    allowed, gate_reason = collection_allowed()
    if not allowed:
        return {
            "status": "DISABLED",
            "reason": gate_reason,
            "shadow_only": True,
        }

    challenger = shadow.predict_fixture(fixture, history)
    row, reason = build_observation(
        fixture,
        champion_model,
        challenger,
        observed_at=observed_at or datetime.now(timezone.utc),
    )
    if row is None:
        return {
            "status": "SKIPPED",
            "reason": reason,
            "challenger_status": challenger.get("status"),
            "shadow_only": True,
        }

    ensure_table(db_engine)
    try:
        with db_engine.begin() as conn:
            existing = conn.execute(
                select(observations.c.observation_id).where(
                    observations.c.observation_key == row["observation_key"]
                )
            ).first()
            if existing:
                return {
                    "status": "EXISTS",
                    "reason": "first_write_preserved",
                    "model_version": row["model_version"],
                    "fixture_id": row["fixture_id"],
                    "shadow_only": True,
                }
            conn.execute(observations.insert().values(**row))
    except IntegrityError:
        return {
            "status": "EXISTS",
            "reason": "first_write_preserved",
            "model_version": row["model_version"],
            "fixture_id": row["fixture_id"],
            "shadow_only": True,
        }

    return {
        "status": "RECORDED",
        "model_version": row["model_version"],
        "fixture_id": row["fixture_id"],
        "league_slug": row["league_slug"],
        "observed_at": row["observed_at"].isoformat(),
        "kickoff": row["kickoff"].isoformat(),
        "shadow_only": True,
    }


def settle_pending_observations(
    *,
    now: datetime | None = None,
    limit: int = 250,
    db_engine=engine,
) -> dict:
    if not table_exists(db_engine):
        return {"status": "NO_TABLE", "checked": 0, "settled": 0, "pending": 0}

    current = _utc(now or datetime.now(timezone.utc))
    cutoff = current - timedelta(hours=3)
    with db_engine.begin() as conn:
        rows = conn.execute(
            select(observations)
            .where(
                observations.c.status == "pending",
                observations.c.kickoff <= cutoff,
            )
            .order_by(observations.c.kickoff.asc())
            .limit(max(1, min(1000, int(limit))))
        ).mappings().all()

    if not rows:
        return {"status": "SUCCESS", "checked": 0, "settled": 0, "pending": 0}

    picks = [
        {
            "match_id": row["fixture_id"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "commence_time": _utc(row["kickoff"]).isoformat(),
            "league_slug": row["league_slug"],
        }
        for row in rows
    ]

    from leagues.results_checker import (
        _collect_scores_for_picks,
        _lookup_settlement_score,
    )

    scores, source = _collect_scores_for_picks(picks)
    settled = 0
    unresolved = 0

    with db_engine.begin() as conn:
        for row in rows:
            kickoff = _utc(row["kickoff"])
            match = _lookup_settlement_score(
                scores,
                row["home_team"],
                row["away_team"],
                kickoff.date().isoformat(),
            )
            if not match or match.get("ambiguous"):
                unresolved += 1
                continue

            home_score = int(match["home_score"])
            away_score = int(match["away_score"])
            outcome_class = 2 if home_score > away_score else (1 if home_score == away_score else 0)
            conn.execute(
                observations.update()
                .where(
                    observations.c.observation_id == row["observation_id"],
                    observations.c.status == "pending",
                )
                .values(
                    status="settled",
                    settled_at=current,
                    home_score=home_score,
                    away_score=away_score,
                    outcome_class=outcome_class,
                    settlement_source=source[:80],
                )
            )
            settled += 1

    return {
        "status": "SUCCESS",
        "checked": len(rows),
        "settled": settled,
        "pending": unresolved,
        "source": source,
    }


def start_settlement_async(
    *,
    force: bool = False,
    db_engine=engine,
) -> dict:
    """Run settlement in a daemon thread without blocking predictions."""
    global _SETTLEMENT_LAST_STARTED

    if not table_exists(db_engine):
        return {
            "status": "SKIPPED",
            "reason": "no_observation_table",
            "shadow_only": True,
        }

    now_mono = time.monotonic()
    if (
        not force
        and _SETTLEMENT_LAST_STARTED
        and now_mono - _SETTLEMENT_LAST_STARTED
        < SETTLEMENT_COOLDOWN_SECONDS
    ):
        return {
            "status": "SKIPPED",
            "reason": "cooldown",
            "shadow_only": True,
        }

    if not _SETTLEMENT_LOCK.acquire(blocking=False):
        return {
            "status": "SKIPPED",
            "reason": "already_running",
            "shadow_only": True,
        }

    _SETTLEMENT_LAST_STARTED = now_mono

    def worker():
        try:
            settle_pending_observations(db_engine=db_engine)
        except Exception:
            pass
        finally:
            _SETTLEMENT_LOCK.release()

    thread = threading.Thread(
        target=worker,
        name="football-first-shadow-settlement",
        daemon=True,
    )
    thread.start()

    return {
        "status": "STARTED",
        "shadow_only": True,
    }


def latest_review(*, db_engine=engine) -> dict | None:
    if not table_exists(db_engine):
        return None

    ensure_table(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            select(reviews)
            .order_by(reviews.c.created_at.desc())
            .limit(1)
        ).mappings().first()
    return dict(row) if row else None


def review_packet(*, db_engine=engine) -> dict:
    report = shadow_report(db_engine=db_engine)
    comparison = report.get("comparison") or {}
    review = latest_review(db_engine=db_engine)

    return {
        "status": "success",
        "model": report.get("model"),
        "evidence": {
            "observations": report.get("observations"),
            "comparison": comparison,
            "robust_match_result_leagues": report.get(
                "robust_match_result_leagues"
            ),
            "historical_replay_counts_toward_threshold": False,
        },
        "review_gate": {
            "eligible": (
                comparison.get("status")
                == "ELIGIBLE_FOR_HUMAN_REVIEW"
            ),
            "minimum_settled": MIN_PROSPECTIVE_REVIEW,
            "current_settled": int(comparison.get("n") or 0),
            "remaining_to_minimum": max(
                0,
                MIN_PROSPECTIVE_REVIEW - int(comparison.get("n") or 0),
            ),
            "required_conditions": [
                "settled prospective fixtures >= 300",
                "paired Brier lower 95% confidence bound > 0",
                "challenger log loss <= champion log loss",
                "challenger calibration error <= champion calibration error",
            ],
        },
        "allowed_decisions": sorted(REVIEW_DECISIONS),
        "latest_review": review,
        "promotion_effective": False,
        "automatic_promotion": False,
        "live_adjustment_allowed": False,
    }


def record_review(
    decision: str,
    *,
    reviewer: str | None = None,
    note: str | None = None,
    db_engine=engine,
) -> dict:
    normalized = str(decision or "").strip().upper()
    if normalized not in REVIEW_DECISIONS:
        raise ValueError("invalid_review_decision")

    packet = review_packet(db_engine=db_engine)
    gate = packet["review_gate"]
    comparison = packet["evidence"].get("comparison") or {}
    model = packet.get("model") or {}

    if (
        normalized == "APPROVE_FOR_PROMOTION_IMPLEMENTATION"
        and not gate["eligible"]
    ):
        raise ValueError("promotion_review_gate_not_met")

    ensure_table(db_engine)
    row = {
        "review_id": str(uuid.uuid4()),
        "model_version": str(model.get("model_version") or "unknown"),
        "evidence_n": int(comparison.get("n") or 0),
        "evidence_status": str(
            comparison.get("status") or "NO_PROSPECTIVE_EVIDENCE"
        ),
        "decision": normalized,
        "reviewer": str(reviewer)[:160] if reviewer else None,
        "note": str(note)[:2000] if note else None,
        "created_at": datetime.now(timezone.utc),
    }

    with db_engine.begin() as conn:
        conn.execute(reviews.insert().values(**row))

    return {
        "status": "RECORDED",
        "review": row,
        "promotion_effective": False,
        "automatic_promotion": False,
        "live_adjustment_allowed": False,
        "next_action": (
            "separate_code_review_and_deployment_required"
            if normalized == "APPROVE_FOR_PROMOTION_IMPLEMENTATION"
            else "keep_current_champion"
        ),
    }


def _metrics(rows: list[dict], prefix: str) -> dict:
    if not rows:
        return {"n": 0}

    brier = 0.0
    log_loss = 0.0
    correct = 0
    bins = defaultdict(list)

    for row in rows:
        probabilities = [
            float(row[f"{prefix}_away"]),
            float(row[f"{prefix}_draw"]),
            float(row[f"{prefix}_home"]),
        ]
        outcome = int(row["outcome_class"])
        one_hot = [1.0 if index == outcome else 0.0 for index in range(3)]
        brier += sum(
            (probability - actual) ** 2
            for probability, actual in zip(probabilities, one_hot)
        )
        log_loss += -math.log(max(1e-12, probabilities[outcome]))
        predicted = max(range(3), key=lambda index: probabilities[index])
        correct += int(predicted == outcome)
        confidence = max(probabilities)
        bins[min(9, int(confidence * 10))].append(
            (confidence, int(predicted == outcome))
        )

    n = len(rows)
    ece = sum(
        (len(values) / n)
        * abs(
            sum(confidence for confidence, _ in values) / len(values)
            - sum(actual for _, actual in values) / len(values)
        )
        for values in bins.values()
    )
    return {
        "n": n,
        "accuracy": round(correct / n, 6),
        "brier_multiclass": round(brier / n, 6),
        "log_loss": round(log_loss / n, 6),
        "top_label_ece": round(ece, 6),
    }


def _paired_brier_gain(row: dict) -> float:
    outcome = int(row["outcome_class"])
    champion = [
        float(row["champion_away"]),
        float(row["champion_draw"]),
        float(row["champion_home"]),
    ]
    challenger = [
        float(row["challenger_away"]),
        float(row["challenger_draw"]),
        float(row["challenger_home"]),
    ]
    one_hot = [1.0 if index == outcome else 0.0 for index in range(3)]
    champion_brier = sum(
        (probability - actual) ** 2
        for probability, actual in zip(champion, one_hot)
    )
    challenger_brier = sum(
        (probability - actual) ** 2
        for probability, actual in zip(challenger, one_hot)
    )
    return champion_brier - challenger_brier


def shadow_report(*, db_engine=engine) -> dict:
    model = shadow.status()
    allowed, reason = collection_allowed()

    if not table_exists(db_engine):
        return {
            "status": "success",
            "collection_enabled": allowed,
            "collection_gate": reason,
            "model": model,
            "robust_match_result_leagues": len(ROBUST_MATCH_RESULT_LEAGUES),
            "observations": {"total": 0, "pending": 0, "settled": 0},
            "comparison": {"n": 0, "status": "NO_PROSPECTIVE_EVIDENCE"},
            "automatic_promotion": False,
            "live_adjustment_allowed": False,
        }

    with db_engine.begin() as conn:
        current_version = model.get("model_version")
        query = select(observations)
        if current_version:
            query = query.where(observations.c.model_version == current_version)
        rows = [
            dict(row)
            for row in conn.execute(
                query.order_by(observations.c.observed_at.asc())
            ).mappings().all()
        ]

    settled = [
        row
        for row in rows
        if row.get("status") == "settled" and row.get("outcome_class") in {0, 1, 2}
    ]
    pending = len(rows) - len(settled)
    champion = _metrics(settled, "champion")
    challenger = _metrics(settled, "challenger")
    gains = [_paired_brier_gain(row) for row in settled]

    if gains:
        n = len(gains)
        mean = sum(gains) / n
        variance = sum((value - mean) ** 2 for value in gains) / max(1, n - 1)
        lower_95 = mean - 1.96 * math.sqrt(variance / n)
    else:
        mean = 0.0
        lower_95 = 0.0

    eligible = bool(
        len(settled) >= MIN_PROSPECTIVE_REVIEW
        and lower_95 > 0
        and challenger.get("log_loss", float("inf")) <= champion.get("log_loss", float("inf"))
        and challenger.get("top_label_ece", float("inf")) <= champion.get("top_label_ece", float("inf"))
    )

    by_league = {}
    for slug in sorted({row["league_slug"] for row in settled}):
        subset = [row for row in settled if row["league_slug"] == slug]
        if len(subset) < 30:
            continue
        by_league[slug] = {
            "n": len(subset),
            "champion": _metrics(subset, "champion"),
            "challenger": _metrics(subset, "challenger"),
        }

    started_at = rows[0]["observed_at"].isoformat() if rows else None
    return {
        "status": "success",
        "collection_enabled": allowed,
        "collection_gate": reason,
        "model": model,
        "robust_match_result_leagues": len(ROBUST_MATCH_RESULT_LEAGUES),
        "observations": {
            "total": len(rows),
            "pending": pending,
            "settled": len(settled),
            "prospective_started_at": started_at,
        },
        "comparison": {
            "n": len(settled),
            "minimum_for_human_review": MIN_PROSPECTIVE_REVIEW,
            "champion": champion,
            "challenger": challenger,
            "paired_brier_improvement": round(mean, 6),
            "lower_95pct_brier_improvement": round(lower_95, 6),
            "status": (
                "ELIGIBLE_FOR_HUMAN_REVIEW"
                if eligible
                else (
                    "COLLECTING_PROSPECTIVE_EVIDENCE"
                    if settled
                    else "NO_PROSPECTIVE_EVIDENCE"
                )
            ),
            "by_league": by_league,
        },
        "historical_replay_counts_toward_threshold": False,
        "evidence_progress": {
            "minimum_for_human_review": MIN_PROSPECTIVE_REVIEW,
            "settled": len(settled),
            "remaining": max(
                0,
                MIN_PROSPECTIVE_REVIEW - len(settled),
            ),
            "percent_complete": round(
                min(
                    100.0,
                    100.0 * len(settled) / MIN_PROSPECTIVE_REVIEW,
                ),
                2,
            ),
        },
        "latest_review": latest_review(db_engine=db_engine),
        "automatic_promotion": False,
        "live_adjustment_allowed": False,
    }
