"""Read-only explanation of BetSightly's current market and ticket readiness.

Do not confuse a model probability, a historical replay, live calibration,
and permission to publish. This powers admin diagnostics only: it does not
generate, train, book, edit a daily card or promote any market.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from leagues.market_registry import MARKETS

WAT = timezone(timedelta(hours=1))
WATCH_MARKETS = (
    "over_0_5", "over_1_5", "over_2_5",
    "home_over_0_5", "away_over_0_5",
    "home_over_1_5", "away_over_1_5",
    "btts_yes", "btts_no", "under_4_5",
)
CATEGORIES = ("banker", "2_odds", "5_odds", "10_odds", "over_1_5")


def _count_readonly(table: str) -> int | None:
    """Fixed table names only; absent or unmigrated telemetry is not invented."""
    if table not in {"model_training_runs", "prediction_accuracy",
                     "prediction_outcomes"}:
        raise ValueError("Unsupported telemetry table")
    try:
        from sqlalchemy import text
        from database import SessionLocal

        db = SessionLocal()
        try:
            return int(db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
        finally:
            db.close()
    except Exception:
        return None


def market_readiness_snapshot(*, day: str | None = None,
                              card: dict | None = None,
                              replay_lookup=None,
                              include_db_telemetry: bool = True) -> dict[str, Any]:
    """Return truthful snapshot with no side effects or publication decisions."""
    from leagues.picks_db import load_card
    from leagues.replay_evidence import market_evidence

    date = day or datetime.now(WAT).date().isoformat()
    latest = card if card is not None else load_card(date)
    replay_lookup = replay_lookup or market_evidence
    portfolio = ((latest or {}).get("_portfolio") or {})
    supply = portfolio.get("tier_supply_diagnostics") or {}
    rejections = ((portfolio.get("publication_policy") or {})
                  .get("rejections") or {}).get("official") or {}
    rows = []
    for key in WATCH_MARKETS:
        spec = MARKETS[key]
        try:
            replay = replay_lookup(key) or {}
        except (OSError, ValueError, TypeError):
            replay = {}
        n = replay.get("n")
        n = int(n) if n is not None else None
        rows.append({
            "market": key,
            "label": spec.label,
            "policy": spec.public_policy,
            "activation": spec.activation,
            "candidate_generation": spec.candidate_generation,
            "bookmaker_mapped": bool(spec.sportybet),
            "historical_replay_observations": n,
            "historical_replay_missing": n is None,
            # Brier/calibration here is from old replay, NOT live performance.
            "historical_calibration_error": replay.get("calibration_error"),
            "historical_bookmaker_n": replay.get("bookmaker_n"),
            "historical_skill_vs_bookmaker": replay.get("skill_vs_bookmaker"),
            "historical_replay_is_not_training": True,
        })
    products = {}
    for key in CATEGORIES:
        tier = ((latest or {}).get(key) or {})
        products[key] = {
            "selected": bool(tier.get("selected")),
            "leg_count": len(tier.get("games") or []),
            "published_odds": tier.get("total_odds") if tier.get("selected") else None,
        }
    telemetry = {}
    if include_db_telemetry:
        telemetry = {
            table: _count_readonly(table)
            for table in ("model_training_runs", "prediction_accuracy",
                          "prediction_outcomes")
        }
    return {
        "date": date,
        "published_card_available": bool(latest),
        "qualified_fixtures": supply.get("qualified_fixtures"),
        "qualified_selections": supply.get("qualified_selections"),
        "reserved_fixtures": supply.get("reserved_fixtures"),
        "remaining_qualified_fixtures": supply.get("remaining_qualified_fixtures"),
        "tier_supply": supply.get("products") or {},
        "rejections": rejections,
        "products": products,
        "markets": rows,
        "telemetry_counts": telemetry,
        "warnings": [
            "A developing market can be modeled without passing bookmaker and publishing checks.",
            "Replay is historical research, not a current model-training run or live calibration measurement.",
            "Rejection counts can overlap: one candidate may fail more than one check.",
            "No-repeat fixture exposure can deplete other tiers even when the individual picks were qualified.",
        ],
        "read_only": True,
    }
