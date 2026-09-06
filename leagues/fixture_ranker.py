"""Canonical per-fixture market recommendations shared by public selectors."""
from __future__ import annotations

import math
import os

RANKING_POLICY_VERSION = "fixture-ranked-v1.1"
SELECTOR_VERSION = "canonical-recommendations-v1.1"
MARKET_POLICY_VERSION = "market-trust-v1.1"

TRUSTED_MARKETS = {"over_1_5", "under_3_5", "under_4_5", "home_or_draw",
                   "away_or_draw", "dnb_home", "dnb_away"}
EVIDENCE_ELIGIBLE_WINS = {"home_win", "away_win"}
DEVELOPING_MARKETS = {"over_2_5", "home_over_0_5", "away_over_0_5"}
RESTRICTED_MARKETS = {"under_2_5", "draw", "btts_yes", "btts_no",
                      "home_over_1_5", "away_over_1_5"}
DISABLED_PUBLIC_MARKETS = {"under_1_5", "over_3_5", "home_or_away"}
TEAM_TO_SCORE = {"home_over_0_5", "away_over_0_5"}


def _evidence(pick: dict) -> dict:
    trust = pick.get("trust") or {}
    if trust.get("evidence_state"):
        return {
            "state": trust["evidence_state"],
            "evidence_strength": trust.get("evidence_strength", 0.7),
            "lower_reliability_bound": trust.get("lower_reliability_bound"),
            "evidence_adjusted_probability": trust.get("evidence_adjusted_probability"),
        }
    try:
        from leagues.evidence_fusion import fused_market_evidence
        fixture = pick.get("_fixture") or {}
        return fused_market_evidence(pick.get("market", ""), float(pick.get("confidence") or 0),
                                     fixture.get("league"), pick.get("calibration_evidence"))
    except Exception:
        return {}


def _straight_win_supported(pick: dict, evidence: dict) -> bool:
    if pick.get("market") not in EVIDENCE_ELIGIBLE_WINS:
        return True
    confidence = float(pick.get("confidence") or 0)
    implied = pick.get("market_implied_probability")
    ml = pick.get("ml_confidence")
    return (
        bool(pick.get("odds_are_real"))
        and confidence >= .64
        and evidence.get("state") in {"SUPPORTED", "PROVEN"}
        and implied is not None
        and abs(confidence - float(implied)) <= .12
        and (ml is None or abs(confidence - float(ml)) <= .12)
        and float(pick.get("expected_value") or 0) <= .12
    )


def _team_score_supported(pick: dict, evidence: dict) -> bool:
    if pick.get("market") not in TEAM_TO_SCORE:
        return True
    goals = (pick.get("_model") or {}).get("expected_goals") or {}
    key = "home" if pick["market"] == "home_over_0_5" else "away"
    return (float(goals.get(key) or 0) >= 1.20
            and float(pick.get("confidence") or 0) >= .72
            and bool(pick.get("odds_are_real"))
            and evidence.get("state") in {"SUPPORTED", "PROVEN"})


def _policy_state(pick: dict, evidence: dict) -> str:
    market = pick.get("market")
    if market in DISABLED_PUBLIC_MARKETS:
        return "DISABLED"
    if market in RESTRICTED_MARKETS or evidence.get("state") in {"SHADOW", "REJECTED"}:
        return "RESTRICTED"
    if market in EVIDENCE_ELIGIBLE_WINS:
        return "TRUSTED" if _straight_win_supported(pick, evidence) else "RESTRICTED"
    if market in DEVELOPING_MARKETS:
        return "DEVELOPING" if _team_score_supported(pick, evidence) else "RESTRICTED"
    return "TRUSTED" if market in TRUSTED_MARKETS else "PROVISIONAL"


def _base_quality(pick: dict, evidence: dict) -> tuple[float, list[str]]:
    """Comparable wager quality; probability matters but is not the whole score."""
    probability = float(evidence.get("evidence_adjusted_probability")
                        or pick.get("evidence_adjusted_probability")
                        or pick.get("confidence") or 0)
    # A 70% probability weight prevents naturally high-base-rate safety markets
    # from automatically dominating useful, well-priced straight outcomes.
    score = probability * 70
    reasons = ["CALIBRATED"]
    strength = float(evidence.get("evidence_strength") or 0)
    score += min(8.0, strength * 8)
    odds = max(1.0001, float(pick.get("odds") or 1.0001))
    score += min(5.0, math.log(odds) * 10)
    ev = max(-.15, min(.15, float(pick.get("expected_value") or 0)))
    score += ev * 20
    if pick.get("odds_are_real"):
        reasons.append("REAL_ODDS")
    else:
        score -= 3
        reasons.append("ESTIMATED_ODDS_PENALTY")
    implied = pick.get("market_implied_probability")
    if implied is not None:
        gap = abs(float(pick.get("confidence") or 0) - float(implied))
        score -= min(18, gap * 55)
        reasons.append("MODEL_MARKET_AGREEMENT" if gap <= .08 else "BOOKMAKER_DISAGREEMENT")
    ml = pick.get("ml_confidence")
    if ml is not None:
        gap = abs(float(pick.get("confidence") or 0) - float(ml))
        score -= min(8, gap * 30)  # ML has limited held-out skill: corroboration, not command.
        reasons.append("ML_AGREEMENT" if gap <= .08 else "ML_DISAGREEMENT")
    return round(score, 3), reasons


def _public_eligible(pick: dict, *, safe_only: bool) -> tuple[bool, str | None]:
    state = pick["market_trust_state"]
    if state in {"RESTRICTED", "DISABLED"}:
        return False, f"MARKET_{state}"
    if safe_only and state != "TRUSTED":
        return False, "SAFE_TIER_REQUIRES_TRUSTED"
    return True, None


def canonical_fixture_recommendations(picks: list[dict], *, safe_only: bool = False) -> list[dict]:
    """Model-rank everything, then recompute public rank among eligible markets."""
    if os.getenv("FIXTURE_RANKED_SELECTOR", "1").lower() in {"0", "false", "off"}:
        return picks
    fixtures: dict[str, list[dict]] = {}
    for pick in picks:
        fixtures.setdefault(str(pick.get("match_id")), []).append(pick)
    selected = []
    for fixture_picks in fixtures.values():
        modeled = []
        for original in fixture_picks:
            pick = dict(original)
            evidence = _evidence(pick)
            score, reasons = _base_quality(pick, evidence)
            state = _policy_state(pick, evidence)
            policy_penalty = {
                "DEVELOPING": 8.0,
                "PROVISIONAL": 12.0,
            }.get(state, 0.0)
            pick.update(model_quality_score=score,
                        quality_score=round(score - policy_penalty, 3),
                        market_trust_state=state, selection_reason_codes=reasons,
                        evidence_strength=evidence.get("evidence_strength"),
                        evidence_adjusted_probability=(
                            evidence.get("evidence_adjusted_probability")
                            or pick.get("evidence_adjusted_probability")
                        ),
                        lower_reliability_bound=(
                            evidence.get("lower_reliability_bound")
                            or pick.get("lower_reliability_bound")
                        ))
            modeled.append(pick)
        modeled.sort(key=lambda p: (-p["model_quality_score"], -float(p.get("confidence") or 0)))
        best_model = modeled[0]
        for model_rank, pick in enumerate(modeled, 1):
            pick["model_rank"] = model_rank
            pick["model_quality_gap"] = round(best_model["model_quality_score"] - pick["model_quality_score"], 3)

        eligible = []
        rejected = []
        for pick in modeled:
            ok, reason = _public_eligible(pick, safe_only=safe_only)
            if ok:
                eligible.append(pick)
            else:
                rejected.append({"market": pick.get("market"), "model_rank": pick["model_rank"],
                                 "quality_score": pick["quality_score"], "reason": reason})
        eligible.sort(key=lambda p: (-round(p["quality_score"] * 2) / 2,
                                     not bool(p.get("bookable")), -p["quality_score"]))
        if not eligible:
            continue
        best_public = eligible[0]
        lower = float((best_public.get("trust") or {}).get("lower_reliability_bound")
                      or best_public.get("confidence") or 0)
        allowed_gap = min(10.0, max(4.0, (float(best_public.get("confidence") or 0) - lower) * 100))
        alternatives = [{"market": p.get("market"), "model_rank": p["model_rank"],
                         "public_rank": rank, "quality_score": p["quality_score"],
                         "confidence": p.get("confidence"), "trust_state": p["market_trust_state"]}
                        for rank, p in enumerate(eligible[:4], 1)]
        for public_rank, pick in enumerate(eligible, 1):
            public_gap = round(best_public["quality_score"] - pick["quality_score"], 3)
            pick.update(public_rank=public_rank, fixture_rank=public_rank,
                        ranking_policy_version=RANKING_POLICY_VERSION,
                        selector_version=SELECTOR_VERSION, market_policy_version=MARKET_POLICY_VERSION,
                        best_model_market=best_model.get("market"), best_public_market=best_public.get("market"),
                        best_market=best_public.get("market"), public_quality_gap=public_gap,
                        quality_gap_from_best=public_gap, fixture_alternatives=alternatives,
                        rejected_fixture_alternatives=rejected[:4])
            if public_rank > 2 or (public_rank == 2 and public_gap > allowed_gap):
                continue
            pick["selection_reason_codes"] += [f"PUBLIC_RANK_{public_rank}"]
            selected.append(pick)
    return selected
