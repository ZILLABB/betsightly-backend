"""Immutable, compact decision-board archive and read-only quality analytics.

The archive stores what the selector knew at generation time.  It is not a
second prediction or settlement engine: replay reads these bytes only and
settlement remains owned by ``results_checker``/the published records.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, LargeBinary, MetaData, String, Table,
    Text, UniqueConstraint, select,
)

from database import engine, pool_status
from leagues.policy_version import PUBLISHED_SELECTION_POLICY_VERSION

logger = logging.getLogger(__name__)
metadata = MetaData()

board_snapshots = Table(
    "prediction_board_snapshots", metadata,
    Column("snapshot_id", String(64), primary_key=True),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("publication_date", String(10), nullable=False, index=True),
    Column("coverage_start", DateTime(timezone=True)),
    Column("coverage_end", DateTime(timezone=True)),
    Column("requested_horizon", Integer, nullable=False),
    Column("provider_state", String(24), nullable=False),
    Column("fixture_count", Integer, nullable=False),
    Column("candidate_count", Integer, nullable=False),
    Column("policy_version", String(64), nullable=False),
    Column("calibration_version", String(64)),
    Column("evidence_version", String(64)),
    Column("payload_sha256", String(64), nullable=False),
    Column("payload_bytes", Integer, nullable=False),
    Column("payload", LargeBinary, nullable=False),
    UniqueConstraint("payload_sha256", "policy_version",
                     name="uq_board_payload_policy"),
)

product_decisions = Table(
    "prediction_product_decisions", metadata,
    Column("decision_id", String(36), primary_key=True),
    Column("snapshot_id", String(64), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("publication_date", String(10), nullable=False, index=True),
    Column("product", String(32), nullable=False),
    Column("target_odds", Float),
    Column("status", String(40), nullable=False),
    Column("independent_payload", Text, nullable=False),
    Column("final_payload", Text, nullable=False),
    Column("diagnostics_payload", Text, nullable=False),
    UniqueConstraint("snapshot_id", "publication_date", "product",
                     name="uq_product_snapshot_date"),
)

builder_edit_events = Table(
    "builder_edit_events", metadata,
    Column("event_id", String(36), primary_key=True),
    Column("run_id", String(36), nullable=False, index=True),
    Column("snapshot_id", String(64), index=True),
    Column("request_id", String(64), nullable=False),
    Column("revision_before", Integer),
    Column("revision_after", Integer, nullable=False),
    Column("action", String(40), nullable=False),
    Column("fixture_id", String(128)),
    Column("selection_id", String(128)),
    Column("replacement_selection_id", String(128)),
    Column("requested_target", Float),
    Column("achieved_before", Float),
    Column("achieved_after", Float),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("run_id", "request_id", name="uq_builder_edit_request"),
)


def ensure_tables() -> None:
    metadata.create_all(engine, checkfirst=True)


def _json(value) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _iso(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def _compact_candidate(pick: dict) -> dict:
    fixture = pick.get("_fixture") or {}
    model = pick.get("_model") or {}
    expected = model.get("expected_goals") or {}
    trust = pick.get("trust") or {}
    availability = pick.get("sportybet_availability") or {}
    rejection = (pick.get("rejection_reasons") or
                 trust.get("rejection_reasons") or [])
    return {
        "fixture_id": str(pick.get("match_id") or ""),
        "league": fixture.get("league"), "league_slug": fixture.get("league_slug"),
        "kickoff": fixture.get("commence_time"),
        "home": (fixture.get("home") or {}).get("name"),
        "away": (fixture.get("away") or {}).get("name"),
        "market": pick.get("market"), "selection": pick.get("prediction"),
        "market_group": pick.get("market_group"),
        "raw_probability": pick.get("raw_confidence"),
        "calibrated_probability": pick.get("confidence"),
        "evidence_adjusted_probability": pick.get("evidence_adjusted_probability"),
        "conservative_probability": pick.get("selection_probability"),
        "lower_reliability_bound": pick.get("lower_reliability_bound") or trust.get("lower_reliability_bound"),
        "trust_score": trust.get("trust_score"),
        "trust_grade": trust.get("trust_grade"),
        "evidence_state": pick.get("market_trust_state") or trust.get("evidence_state"),
        "odds": pick.get("odds"),
        "odds_source": pick.get("odds_provider") if pick.get("odds_are_real") else "estimated",
        "bookmaker_implied_probability": pick.get("market_implied_probability"),
        "model_bookmaker_gap": trust.get("model_market_disagreement"),
        "ml_probability": pick.get("ml_confidence"),
        "bookable": bool(pick.get("bookable")),
        "sportybet_mapping_state": availability.get("status"),
        "model_rank": pick.get("model_rank"), "public_rank": pick.get("public_rank"),
        "quality_score": pick.get("quality_score"),
        "premium_eligible": bool(pick.get("premium_eligible") or pick.get("market_floor_eligible")),
        "safe_tier_eligible": bool(pick.get("safe_tier_eligible")),
        "rejection_reasons": list(rejection),
        "reason_codes": list(pick.get("selection_reason_codes") or []),
        "calibration_group": pick.get("calibration_group"),
        "calibration_sample": pick.get("calibration_sample"),
        "expected_home_goals": expected.get("home"),
        "expected_away_goals": expected.get("away"),
        "expected_total_goals": expected.get("total"),
        "classification": pick.get("quality_classification"),
    }


def archive_board(picks: list[dict], fixtures: list[dict], *, horizon: int,
                  provider: dict | None = None, calibration: dict | None = None,
                  generated_at: datetime | None = None) -> str | None:
    """Persist once and annotate in-memory picks with the immutable identity.

    Failure is deliberately non-fatal: the public prediction can proceed, but
    a structured error makes the evidence gap operationally visible.
    """
    if not picks and not fixtures:
        return None
    started = datetime.now(timezone.utc)
    try:
        ensure_tables()
        from leagues.fixture_ranker import (
            _base_quality, _evidence, _policy_state,
            canonical_fixture_recommendations,
        )
        from leagues.leg_trust import evaluate_leg_trust
        from leagues.selection_quality import attach_selection_quality
        evaluated = canonical_fixture_recommendations(
            [dict(p) for p in picks], include_all_eligible=True,
            include_subfloor=True,
        )
        ranked = {(str(p.get("match_id")), p.get("market")): p for p in evaluated}
        compact = []
        for original in picks:
            enriched = dict(original)
            enriched.update(ranked.get((str(original.get("match_id")),
                                        original.get("market")), {}))
            if not enriched.get("trust"):
                enriched["trust"] = evaluate_leg_trust(enriched)
            evidence = _evidence(enriched)
            attach_selection_quality(enriched)
            score, reasons = _base_quality(enriched, evidence)
            enriched.setdefault("quality_score", score)
            enriched.setdefault("selection_reason_codes", reasons)
            state = enriched.setdefault("market_trust_state",
                                        _policy_state(enriched, evidence))
            if not enriched.get("public_rank"):
                rejected = list((enriched.get("trust") or {}).get(
                    "rejection_reasons") or [])
                if state in {"RESTRICTED", "DISABLED"}:
                    rejected.append(f"market_{state.lower()}")
                if not enriched.get("market_floor_eligible", True):
                    rejected.append("premium_floor")
                enriched["rejection_reasons"] = sorted(set(rejected))
            compact.append(_compact_candidate(enriched))
        compact.sort(key=lambda p: (p["kickoff"] or "", p["fixture_id"],
                                    p["market"] or ""))
        now = generated_at or started
        publication_date = now.astimezone(timezone.utc).date().isoformat()
        provider = provider or {}
        provider_state = "complete" if provider.get("complete", True) else "degraded"
        payload_obj = {
            "schema": 1,
            "metadata": {
                "publication_date": publication_date,
                "requested_horizon": int(horizon),
                "provider_state": provider_state,
                "provider_snapshot": provider.get("snapshot_id") or provider.get("version"),
                "policy_version": PUBLISHED_SELECTION_POLICY_VERSION,
                "calibration_version": (calibration or {}).get("version"),
                "evidence_version": "fixture-ranked-evidence-v1",
            },
            "candidates": compact,
        }
        raw = _json(payload_obj).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        snapshot_id = digest
        blob = gzip.compress(raw, compresslevel=6)
        times = sorted(
            str(f.get("commence_time")) for f in fixtures if f.get("commence_time")
        )
        row = {
            "snapshot_id": snapshot_id, "generated_at": now,
            "publication_date": publication_date,
            "coverage_start": datetime.fromisoformat(times[0].replace("Z", "+00:00")) if times else None,
            "coverage_end": datetime.fromisoformat(times[-1].replace("Z", "+00:00")) if times else None,
            "requested_horizon": int(horizon), "provider_state": provider_state,
            "fixture_count": len(fixtures), "candidate_count": len(compact),
            "policy_version": PUBLISHED_SELECTION_POLICY_VERSION,
            "calibration_version": str((calibration or {}).get("version") or "unknown")[:64],
            "evidence_version": "fixture-ranked-evidence-v1",
            "payload_sha256": digest, "payload_bytes": len(blob), "payload": blob,
        }
        with engine.begin() as conn:
            if not conn.execute(select(board_snapshots.c.snapshot_id).where(
                    board_snapshots.c.snapshot_id == snapshot_id)).first():
                conn.execute(board_snapshots.insert().values(**row))
        for pick in picks:
            pick["_board_snapshot_id"] = snapshot_id
        logger.info("decision_snapshot %s", _json({
            "snapshot_id": snapshot_id[:12], "fixtures": len(fixtures),
            "candidates": len(compact), "bytes": len(blob),
            "elapsed_ms": round((datetime.now(timezone.utc)-started).total_seconds()*1000, 1),
            "pool": pool_status(),
        }))
        return snapshot_id
    except Exception as exc:
        logger.error("decision_snapshot_failed type=%s", type(exc).__name__, exc_info=True)
        return None


def load_board(snapshot_id: str) -> dict:
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(select(board_snapshots).where(
            board_snapshots.c.snapshot_id == snapshot_id)).mappings().one()
    return json.loads(gzip.decompress(row["payload"]).decode("utf-8"))


def record_daily(snapshot_id: str | None, publication_date: str,
                 products: dict[str, tuple], final: dict,
                 diagnostics: dict) -> None:
    if not snapshot_id:
        return
    try:
        ensure_tables()
        now = datetime.now(timezone.utc)
        with engine.begin() as conn:
            for name, independent in products.items():
                final_product = final.get(name) or {}
                status = str(final_product.get("result_status") or "UNKNOWN")
                row = {
                    "decision_id": str(uuid.uuid4()), "snapshot_id": snapshot_id,
                    "created_at": now, "publication_date": publication_date,
                    "product": name, "target_odds": (final_product.get("booking_rule") or {}).get("target"),
                    "status": status,
                    "independent_payload": _json({
                        "selection_ids": [p.get("selection_id") or f'{p.get("match_id")}:{p.get("market")}' for p in independent[0]],
                        "odds": independent[1], "joint_probability": independent[2],
                    }),
                    "final_payload": _json(final_product),
                    "diagnostics_payload": _json((diagnostics.get("products") or {}).get(name, {})),
                }
                exists = conn.execute(select(product_decisions.c.decision_id).where(
                    product_decisions.c.snapshot_id == snapshot_id,
                    product_decisions.c.publication_date == publication_date,
                    product_decisions.c.product == name,
                )).first()
                if not exists:
                    conn.execute(product_decisions.insert().values(**row))
    except Exception:
        logger.error("daily_decision_archive_failed", exc_info=True)


def record_builder_event(*, run_id: str, snapshot_id: str | None,
                         request_id: str, revision_before: int | None,
                         revision_after: int, action: str,
                         action_target: dict | None, requested_target: float,
                         achieved_before: float | None,
                         achieved_after: float | None) -> None:
    try:
        ensure_tables()
        target = action_target or {}
        with engine.begin() as conn:
            if conn.execute(select(builder_edit_events.c.event_id).where(
                    builder_edit_events.c.run_id == run_id,
                    builder_edit_events.c.request_id == request_id)).first():
                return
            conn.execute(builder_edit_events.insert().values(
                event_id=str(uuid.uuid4()), run_id=run_id,
                snapshot_id=snapshot_id, request_id=request_id,
                revision_before=revision_before, revision_after=revision_after,
                action=str(action)[:40], fixture_id=str(target.get("fixture_id") or "")[:128] or None,
                selection_id=str(target.get("selection_id") or "")[:128] or None,
                replacement_selection_id=str(target.get("replacement_selection_id") or "")[:128] or None,
                requested_target=float(requested_target), achieved_before=achieved_before,
                achieved_after=achieved_after, created_at=datetime.now(timezone.utc),
            ))
    except Exception:
        logger.error("builder_edit_archive_failed", exc_info=True)


def replay(snapshot_id: str, policy: str = "CURRENT_POLICY") -> dict:
    """Deterministic provider-isolated replay input for current/shadow policy."""
    if policy not in {"CURRENT_POLICY", "SHADOW_POLICY"}:
        raise ValueError("unsupported_policy")
    board = load_board(snapshot_id)
    candidates = board.get("candidates") or []
    recommendations = {}
    for candidate in candidates:
        if candidate.get("public_rank") == 1:
            recommendations[candidate["fixture_id"]] = candidate
    return {"status": "shadow" if policy == "SHADOW_POLICY" else "success",
            "publishable": False, "bookable": False, "settle_officially": False,
            "snapshot_id": snapshot_id, "policy": policy,
            "candidate_count": len(candidates),
            "recommendations": list(recommendations.values())}


def quality_report(limit: int = 30) -> dict:
    """Read-only readiness report; outcome metrics appear only when linked data exists."""
    ensure_tables()
    limit = max(1, min(180, int(limit)))
    with engine.begin() as conn:
        rows = conn.execute(select(board_snapshots).order_by(
            board_snapshots.c.generated_at.desc()).limit(limit)).mappings().all()
        decisions = conn.execute(select(product_decisions)).mappings().all()
        edits = conn.execute(select(builder_edit_events)).mappings().all()
    markets = Counter(); ranks = Counter(); grades = Counter(); confidence = Counter(); disagreement = Counter()
    total_candidates = 0
    for row in rows:
        candidates = json.loads(gzip.decompress(row["payload"]).decode("utf-8")).get("candidates", [])
        total_candidates += len(candidates)
        for c in candidates:
            markets[c.get("market") or "unknown"] += 1
            ranks[str(c.get("public_rank") or "ineligible")] += 1
            grades[c.get("classification") or c.get("trust_grade") or "unknown"] += 1
            p = float(c.get("calibrated_probability") or 0)
            confidence[f"{int(p*20)*5:02d}-{int(p*20)*5+4:02d}"] += 1
            gap = abs(float(c.get("model_bookmaker_gap") or 0))
            disagreement["20+" if gap >= .20 else "15-20" if gap >= .15 else "10-15" if gap >= .10 else "5-10" if gap >= .05 else "0-5"] += 1
    settled = _settled_quality_metrics()
    return {
        "status": "success", "read_only": True,
        "board": {"snapshots": len(rows), "candidates": total_candidates,
                  "fixtures": sum(int(r["fixture_count"]) for r in rows),
                  "compressed_bytes": sum(int(r["payload_bytes"]) for r in rows)},
        "markets": {"archive_counts": dict(markets),
                    "settled": settled["markets"]},
        "ranking": {"archive_counts": dict(ranks),
                    "settled": settled["ranks"]},
        "strength": dict(grades), "confidence_bands": dict(confidence),
        "bookmaker_disagreement": dict(disagreement),
        "daily": {"decisions": len(decisions)},
        "builder": {"edit_events": len(edits), "actions": dict(Counter(r["action"] for r in edits))},
        "policies": {"current": PUBLISHED_SELECTION_POLICY_VERSION,
                     "replay_ready": bool(rows), "adaptive_trust_enabled": False},
        "readiness": "thin" if len(rows) < 14 else "early" if len(rows) < 30 else "provisional",
        "minimum_policy_comparison_snapshots": 30,
        "settled_evidence": {
            "legs": settled["legs"],
            "strength": settled["strength"],
            "league_market": settled["league_market"],
            "confidence_bands": settled["confidence_bands"],
            "bookmaker_disagreement": settled["bookmaker_disagreement"],
            "ml_disagreement": settled["ml_disagreement"],
            "lower_bound": settled["lower_bound"],
            "price_roi_policy": "exact SportyBet prices only; estimated ROI excluded",
        },
    }


def _settled_quality_metrics() -> dict:
    """Aggregate official settled legs once; never treat a slip result as a leg."""
    try:
        from leagues.picks_db import get_history
        slips = get_history(limit_days=3650)
    except Exception:
        slips = []
    seen = set()
    groups = {name: defaultdict(list) for name in (
        "markets", "ranks", "strength", "league_market",
        "confidence_bands", "bookmaker_disagreement", "ml_disagreement",
        "lower_bound",
    )}
    for slip in slips:
        product = str(slip.get("category") or slip.get("product") or "unknown")
        for leg in slip.get("picks") or []:
            status = str(leg.get("status") or "").lower()
            if status not in {"won", "lost"}:
                continue
            identity = (product, leg.get("board_snapshot_id"),
                        leg.get("match_id"), leg.get("market"))
            if identity in seen:
                continue
            seen.add(identity)
            outcome = 1.0 if status == "won" else 0.0
            probability = float(leg.get("confidence") or 0)
            if not 0 < probability < 1:
                continue
            item = (probability, outcome, leg)
            groups["markets"][str(leg.get("market") or "unknown")].append(item)
            groups["ranks"][str(leg.get("public_rank") or leg.get("fixture_rank") or "unknown")].append(item)
            groups["strength"][str(leg.get("quality_classification") or "unknown")].append(item)
            groups["league_market"][f'{leg.get("league") or "unknown"} × {leg.get("market") or "unknown"}'].append(item)
            start = min(85, int(probability * 20) * 5)
            groups["confidence_bands"][f"{start:02d}+" if start == 85 else f"{start:02d}-{start+4:02d}"].append(item)
            gap = abs(float(leg.get("bookmaker_disagreement") or 0))
            groups["bookmaker_disagreement"][_gap_bucket(gap)].append(item)
            ml = leg.get("ml_confidence")
            ml_gap = abs(probability - float(ml)) if ml is not None else -1
            groups["ml_disagreement"]["unavailable" if ml_gap < 0 else _gap_bucket(ml_gap)].append(item)
            lower = leg.get("lower_reliability_bound")
            groups["lower_bound"]["available" if lower is not None else "unavailable"].append(item)

    def summarize(cells):
        result = {}
        for key, values in cells.items():
            n = len(values)
            promised = sum(v[0] for v in values) / n
            actual = sum(v[1] for v in values) / n
            result[key] = {
                "n": n, "readiness": _readiness(n),
                "mean_probability": round(promised, 4),
                "hit_rate": round(actual, 4),
                "bias": round(promised - actual, 4),
                "brier": round(sum((v[0] - v[1]) ** 2 for v in values) / n, 4),
            }
        return result
    return {"legs": len(seen), **{key: summarize(value)
                                   for key, value in groups.items()}}


def _gap_bucket(gap: float) -> str:
    return ("20+" if gap >= .20 else "15-20" if gap >= .15 else
            "10-15" if gap >= .10 else "5-10" if gap >= .05 else "0-5")


def _readiness(n: int) -> str:
    return ("thin" if n < 15 else "early" if n < 30 else
            "provisional" if n < 75 else "usable" if n < 150 else
            "strong" if n < 300 else "mature")
