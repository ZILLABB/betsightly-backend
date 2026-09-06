"""Canonical per-fixture market recommendations shared by public selectors."""
from __future__ import annotations
import os

RANKING_POLICY_VERSION = "fixture-ranked-v1"
SELECTOR_VERSION = "canonical-recommendations-v1"
MARKET_POLICY_VERSION = "market-trust-v1"
TRUSTED_MARKETS = {"over_1_5", "under_3_5", "under_4_5", "home_or_draw", "away_or_draw", "dnb_home", "dnb_away"}
DEVELOPING_MARKETS = {"over_2_5", "home_over_0_5", "away_over_0_5"}
RESTRICTED_MARKETS = {"under_2_5", "home_win", "away_win", "draw", "btts_yes", "btts_no", "home_over_1_5", "away_over_1_5"}
DISABLED_PUBLIC_MARKETS = {"under_1_5", "over_3_5", "home_or_away"}
TEAM_TO_SCORE = {"home_over_0_5", "away_over_0_5"}

def _policy_state(pick: dict) -> str:
    market = pick.get("market")
    evidence = (pick.get("trust") or {}).get("evidence_state")
    if market in DISABLED_PUBLIC_MARKETS: return "DISABLED"
    if market in RESTRICTED_MARKETS or evidence in {"SHADOW", "REJECTED"}: return "RESTRICTED"
    if market in DEVELOPING_MARKETS: return "DEVELOPING"
    return "TRUSTED" if market in TRUSTED_MARKETS else "PROVISIONAL"

def _team_score_supported(pick: dict) -> bool:
    if pick.get("market") not in TEAM_TO_SCORE: return True
    goals = (pick.get("_model") or {}).get("expected_goals") or {}
    key = "home" if pick["market"] == "home_over_0_5" else "away"
    return (float(goals.get(key) or 0) >= 1.20 and float(pick.get("confidence") or 0) >= .72
            and bool(pick.get("odds_are_real")))

def _quality(pick: dict) -> tuple[float, list[str]]:
    trust = pick.get("trust") or {}
    probability = float(trust.get("evidence_adjusted_probability") or pick.get("evidence_adjusted_probability") or pick.get("confidence") or 0)
    score, reasons = probability * 100, ["CALIBRATED"]
    if pick.get("odds_are_real"): reasons.append("REAL_ODDS")
    else: score -= 3; reasons.append("ESTIMATED_ODDS_PENALTY")
    implied = pick.get("market_implied_probability")
    if implied is not None:
        gap = abs(float(pick.get("confidence") or 0) - float(implied)); score -= min(18, gap * 55)
        reasons.append("MODEL_MARKET_AGREEMENT" if gap <= .08 else "BOOKMAKER_DISAGREEMENT")
    ml = pick.get("ml_confidence")
    if ml is not None:
        gap = abs(float(pick.get("confidence") or 0) - float(ml)); score -= min(12, gap * 45)
        reasons.append("ML_AGREEMENT" if gap <= .08 else "ML_DISAGREEMENT")
    state = _policy_state(pick)
    score -= {"TRUSTED": 0, "DEVELOPING": 8, "PROVISIONAL": 12, "RESTRICTED": 30, "DISABLED": 100}[state]
    if pick.get("bookable"): score += .5
    if not _team_score_supported(pick): score -= 40; reasons.append("TEAM_TO_SCORE_SUPPORT_MISSING")
    return round(score, 3), reasons

def canonical_fixture_recommendations(picks: list[dict], *, safe_only: bool = False) -> list[dict]:
    """Rank football quality before price usefulness; keep rank 1/close rank 2."""
    if os.getenv("FIXTURE_RANKED_SELECTOR", "1").lower() in {"0", "false", "off"}: return picks
    fixtures: dict[str, list[dict]] = {}
    for pick in picks: fixtures.setdefault(str(pick.get("match_id")), []).append(pick)
    selected = []
    for fixture_picks in fixtures.values():
        ranked = []
        for original in fixture_picks:
            pick = dict(original); score, reasons = _quality(pick)
            pick.update(quality_score=score, market_trust_state=_policy_state(pick), selection_reason_codes=reasons)
            ranked.append(pick)
        ranked.sort(key=lambda p: (-p["quality_score"], -float(p.get("confidence") or 0)))
        top = ranked[0]
        alternatives = [{
            "market": candidate.get("market"), "fixture_rank": rank,
            "quality_score": candidate["quality_score"],
            "confidence": candidate.get("confidence"),
            "trust_state": candidate["market_trust_state"],
        } for rank, candidate in enumerate(ranked[:4], 1)]
        lower = float((top.get("trust") or {}).get("lower_reliability_bound") or top.get("confidence") or 0)
        allowed_gap = min(10.0, max(4.0, (float(top.get("confidence") or 0) - lower) * 100))
        for index, pick in enumerate(ranked, 1):
            gap = round(top["quality_score"] - pick["quality_score"], 3)
            pick.update(fixture_rank=index, ranking_policy_version=RANKING_POLICY_VERSION,
                        selector_version=SELECTOR_VERSION, market_policy_version=MARKET_POLICY_VERSION,
                        best_market=top.get("market"), best_market_quality_score=top["quality_score"], quality_gap_from_best=gap)
            if index > 2 or (index == 2 and gap > allowed_gap): continue
            if pick["market_trust_state"] in {"RESTRICTED", "DISABLED"}: continue
            if safe_only and pick["market_trust_state"] != "TRUSTED": continue
            if not _team_score_supported(pick): continue
            pick["selection_reason_codes"] += [f"FIXTURE_RANK_{index}"]
            pick["fixture_alternatives"] = alternatives
            selected.append(pick)
    return selected
