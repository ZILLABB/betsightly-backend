"""NBA/private basketball research evidence adapter; no public betting changes.

Research forecasts are immutable pre-tipoff observations. This module never
mixes them with football, never generates basketball picks or SportyBet codes.
WNBA/NCAA/international extensions require verified fixture/model coverage.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from leagues.jev_evidence_contract import _utc, evidence_envelope

ALLOWED_RESEARCH_MARKETS = frozenset({
    "nba_moneyline", "nba_total_over", "nba_total_under",
})
SUPPORTED_COMPETITIONS = frozenset({"NBA"})


def basketball_shadow_envelope(
    forecast: dict[str, Any], observations: list[dict[str, Any]],
    *, as_of: datetime,
) -> dict[str, Any]:
    at = _utc(as_of)
    if at is None:
        raise ValueError("aware pre-tipoff audit time required")
    if forecast.get("competition") not in SUPPORTED_COMPETITIONS:
        return {"status": "unsupported_league", "shadow_only": True,
                "publication_authority": False,
                "reason": "league_model_not_approved_for_jev"}
    if forecast.get("market") not in ALLOWED_RESEARCH_MARKETS:
        return {"status": "unsupported_market", "shadow_only": True,
                "publication_authority": False}
    tip = _utc(forecast.get("tipoff_utc"))
    if tip is None or tip <= at:
        return {"status": "ineligible", "shadow_only": True,
                "publication_authority": False,
                "reason": "missing_or_started_tipoff"}
    if forecast.get("original_pregame_forecast") is not True:
        return {"status": "ineligible", "shadow_only": True,
                "publication_authority": False,
                "reason": "not_original_pre_tipoff_research"}
    if forecast.get("verified_fixture_identity") is not True:
        return {"status": "ineligible", "shadow_only": True,
                "publication_authority": False,
                "reason": "unverified_provider_fixture_identity"}
    pick = {
        "match_id": forecast.get("game_id"),
        "market": forecast["market"],
        "home_team": forecast.get("home_team"),
        "away_team": forecast.get("away_team"),
        "kickoff": tip,
        "selection_probability": forecast.get("original_model_probability"),
        "odds": forecast.get("original_bookmaker_price"),
        "market_trust_state": "PRIVATE_RESEARCH",
    }
    report = evidence_envelope(pick, observations, sport="basketball", as_of=at)
    if report.get("status") == "ready_for_shadow_review":
        report["research_scope"] = "nba_private_only"
        report["football_unchanged"] = True
        report["basketball_publication_unchanged"] = True
        report["betting_code_generated"] = False
    return report


def basketball_research_status() -> dict:
    return {
        "NBA": "shadow_contract_available_but_not_live",
        "WNBA": "coverage_not_yet_accepted",
        "NCAA": "coverage_not_yet_accepted",
        "international": "coverage_not_yet_accepted",
        "publication_authority": False,
        "separate_from_football": True,
    }
