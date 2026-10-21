"""Read-only provenance and market publication health.

Market capability, historical replay, live calibration and bookmaker
bookability are different facts. An empty legacy ML training table does not
prove the Poisson engine hasn't predicted or been calibrated. Conversely,
historical replay is not proof of a current retrain or bookmaker profit.
No API call here books, generates a prediction or modifies published results.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPLAY_ROOT = ROOT / "data" / "replay"
WAT = timezone(timedelta(hours=1))
PUBLICATION_PRODUCTS = ("banker", "2_odds", "5_odds", "10_odds", "over_1_5")


def _json_file(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _fit_summary(fit: dict | None) -> dict:
    fit = fit or {}
    policy = fit.get("policy") or {}
    groups = fit.get("groups") or {}
    fitted_at = fit.get("fitted_at")
    try:
        fitted_at_utc = datetime.fromtimestamp(
            float(fitted_at), timezone.utc
        ).isoformat() if fitted_at else None
    except (TypeError, ValueError, OSError, OverflowError):
        fitted_at_utc = None
    return {
        "source": "deduplicated settled published legs and rollover days",
        "fitted_at_utc": fitted_at_utc,
        "unique_settled_forecasts": int(fit.get("n") or 0),
        "current_selection_policy": policy.get("version"),
        "current_policy_unique_forecasts": int(
            policy.get("settled_unique_forecasts") or 0),
        "historical_policy_unique_forecasts": int(
            policy.get("historical_unique_forecasts") or 0),
        "groups": {key: {"n": int(v.get("n") or 0)}
                   for key, v in groups.items() if isinstance(v, dict)},
        "status": "AVAILABLE" if fitted_at_utc else "UNAVAILABLE",
    }


def market_health_report(
    *,
    date: str | None = None,
    directory: Path = REPLAY_ROOT,
    fit: dict | None = None,
    card: dict | None = None,
) -> dict:
    from leagues.market_registry import MARKETS
    from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE

    target = date or datetime.now(WAT).date().isoformat()
    if fit is None:
        try:
            from leagues.calibrator import fit_calibration
            fit = fit_calibration()
        except Exception:
            fit = {}
    if card is None:
        try:
            from leagues.picks_db import load_card
            card = load_card(target)
        except Exception:
            card = {}
    fit_state = _fit_summary(fit)
    replay = _json_file(directory / "market_summary.json")
    meta = _json_file(directory / "replay_metadata.json")
    code_revision = hashlib.sha256(
        (ROOT / "leagues" / "historical_replay.py").read_bytes()
    ).hexdigest()[:16]
    replay_matches = bool(meta.get("code_revision") == code_revision)
    markets = {}
    for key, spec in MARKETS.items():
        cell = replay.get(key) or {}
        n = int(cell.get("n") or 0)
        bookmaker_n = int(cell.get("bookmaker_n") or 0)
        group_n = int((fit_state["groups"].get(spec.calibration_group) or {}).get("n") or 0)
        missing = []
        if spec.activation != "ACTIVE":
            missing.append("NOT_ACTIVATED_FOR_PUBLIC")
        if n < 200:
            missing.append("HISTORICAL_REPLAY_MISSING_OR_THIN")
        if not replay_matches:
            missing.append("REPLAY_REVISION_STALE")
        if group_n < 25:
            missing.append("LIVE_MARKET_SETTLEMENT_EVIDENCE_THIN")
        if bookmaker_n == 0:
            missing.append("HISTORICAL_BOOKMAKER_BENCHMARK_MISSING")
        if spec.public_policy != "TRUSTED":
            missing.append("SAFE_TIER_NOT_APPROVED")
        markets[key] = {
            "activation": spec.activation,
            "public_policy": spec.public_policy,
            "builder_enabled": spec.builder,
            "safe_tier_enabled": spec.safe_tier,
            "booking_mapped": bool(spec.sportybet),
            "historical_replay_n": n,
            "historical_ece": cell.get("ece"),
            "historical_bookmaker_n": bookmaker_n,
            "skill_vs_bookmaker": cell.get("skill_vs_bookmaker"),
            "live_settled_calibration_group_n": group_n,
            "blockers": missing,
            "historical_replay_complete": n >= 200 and replay_matches,
            "publication_requires_current_bookmaker_check": True,
        }
    portfolio = (card or {}).get("_portfolio") or {}
    allocation = portfolio.get("tier_supply_diagnostics") or {}
    policy = portfolio.get("publication_policy") or {}
    products = {}
    for key in PUBLICATION_PRODUCTS:
        value = (card or {}).get(key) or {}
        entry = (portfolio.get("products") or {}).get(key) or {}
        products[key] = {
            "selected": bool(value.get("selected")),
            "legs": len(value.get("games") or []),
            "decision": entry.get("decision") or value.get("result_status"),
            "reason": value.get("reason"),
        }
    return {
        "status": "success",
        "publish_date": target,
        "production_mutated": False,
        "live_calibration": fit_state,
        "legacy_training_tables_are_not_current_model_telemetry": True,
        "historical_replay": {
            "generated_at": meta.get("generated_at"),
            "data_through": (meta.get("date_range") or [None, None])[-1],
            "code_revision_matches": replay_matches,
            "source": "chronological historical scored fixtures",
            "does_not_prove_model_retraining": True,
        },
        "publication": {
            "card_found": bool(card),
            "qualified_fixtures": allocation.get("qualified_fixtures"),
            "reserved_fixtures": allocation.get("reserved_fixtures"),
            "remaining_qualified_fixtures": allocation.get("remaining_qualified_fixtures"),
            "policy_rejections": (policy.get("rejections") or {}).get("official") or {},
            "products": products,
            "cross_product_fixture_exposure_limit": (
                portfolio.get("max_official_fixture_exposure")),
        },
        "markets": markets,
        "default_publication_confidence_floor": MIN_PUBLISHABLE_CONFIDENCE,
        "note": ("ACTIVE means modeled/mapped, not automatically bookable. "
                 "A published leg still requires current verified odds, "
                 "conservative model value and product-specific evidence."),
    }
