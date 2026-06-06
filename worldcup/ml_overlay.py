"""
ML overlay for club predictions.

Uses the ELO rating registry (loaded on production from
models/api_football/elo_ratings.json) to compute an independent
match-outcome probability. This is the "second opinion" that
confirms or disagrees with the bookmaker's implied probability.

When ML and bookmaker agree on the safest pick, confidence is
boosted. When they disagree, we either lower confidence or skip.

Pure addition — does not modify any existing endpoint or pipeline.
"""

import json
import logging
import math
import unicodedata
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Cache: load ELO once and reuse
_ELO_CACHE: Optional[Dict[str, Any]] = None


def _normalize(name: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace, drop common prefixes."""
    if not name:
        return ""
    # Strip diacritics: "Almería" -> "Almeria", "Castellón" -> "Castellon"
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower().strip()
    # Drop common club prefixes/suffixes
    for token in ["fc ", "cd ", "cf ", "sc ", "ac ", "as ", "ss ", "rc ", "ud ",
                  "ca ", "real ", "club ", "deportivo ", "athletic ", "1. fc "]:
        if n.startswith(token):
            n = n[len(token):]
    # Drop trailing
    for token in [" fc", " cf", " sc", " ii", " (chi)", " (arg)"]:
        if n.endswith(token):
            n = n[: -len(token)]
    # Collapse multi-space
    return " ".join(n.split())


def _load_elo() -> Optional[Dict[str, Any]]:
    """Load ELO registry once. Returns None if not available."""
    global _ELO_CACHE
    if _ELO_CACHE is not None:
        return _ELO_CACHE

    elo_path = Path(__file__).resolve().parent.parent / "models" / "api_football" / "elo_ratings.json"
    if not elo_path.exists():
        logger.warning("ELO registry not found — ML overlay disabled")
        _ELO_CACHE = {"ratings": {}, "normalized": {}, "home_advantage": 100, "default_rating": 1500}
        return _ELO_CACHE

    try:
        with open(elo_path) as f:
            data = json.load(f)
        ratings = data.get("ratings", {})
        # Pre-build normalized index for fast fuzzy lookup
        normalized = {_normalize(name): rating for name, rating in ratings.items()}
        _ELO_CACHE = {
            "ratings": ratings,
            "normalized": normalized,
            "home_advantage": data.get("home_advantage", 100),
            "default_rating": data.get("default_rating", 1500),
        }
        logger.info(f"ML overlay: loaded {len(ratings)} ELO ratings ({len(normalized)} normalized index entries)")
        return _ELO_CACHE
    except Exception as e:
        logger.error(f"Failed to load ELO: {e}")
        _ELO_CACHE = {"ratings": {}, "normalized": {}, "home_advantage": 100, "default_rating": 1500}
        return _ELO_CACHE


def get_team_rating(team: str, allow_default: bool = False) -> Optional[float]:
    """
    Get a team's ELO rating using strict normalized-name lookup.
    Returns None if not in registry (so the caller can skip ML overlay
    for unknown teams rather than match to a wrong team).

    No substring/fuzzy fallback — false positives cause wrong "ML
    disagreements" that drop legitimately safe picks.
    """
    elo = _load_elo()
    if not elo or not team:
        return None

    # 1. Exact match
    if team in elo["ratings"]:
        return elo["ratings"][team]

    # 2. Normalized match (diacritic-stripped, prefix-stripped)
    norm = _normalize(team)
    if norm and norm in elo.get("normalized", {}):
        return elo["normalized"][norm]

    return elo["default_rating"] if allow_default else None


def is_known_team(team: str) -> bool:
    """True if team is in the ELO registry (exact or normalized match)."""
    return get_team_rating(team, allow_default=False) is not None


def elo_probabilities(home_team: str, away_team: str) -> Optional[Dict[str, float]]:
    """
    Compute match outcome probabilities from ELO ratings.

    Returns None if either team is unknown (so caller can skip overlay).
    Otherwise returns {"home_win": x, "draw": y, "away_win": z}.
    """
    elo = _load_elo()
    if not elo:
        return None

    home_rating = get_team_rating(home_team)
    away_rating = get_team_rating(away_team)

    if home_rating is None or away_rating is None:
        return None

    home_advantage = elo.get("home_advantage", 100)
    elo_diff = (home_rating + home_advantage) - away_rating

    # Standard ELO expected score (0..1)
    expected = 1.0 / (1.0 + math.pow(10, -elo_diff / 400.0))

    # Empirical football draw rate: ~28% in close matches, ~10% in lopsided
    # Linear taper based on |elo_diff|
    draw_prob = max(0.10, min(0.30, 0.30 - abs(elo_diff) / 1500.0))

    # expected_score ≈ p_home + 0.5 * p_draw → solve for p_home
    p_home = max(0.05, expected - 0.5 * draw_prob)
    p_away = max(0.05, 1.0 - p_home - draw_prob)

    total = p_home + draw_prob + p_away
    return {
        "home_win": round(p_home / total, 4),
        "draw": round(draw_prob / total, 4),
        "away_win": round(p_away / total, 4),
    }


def check_agreement(
    bookmaker_probs: Dict[str, float],
    pick_key: str,
    home_team: str,
    away_team: str,
    threshold: float = 0.10,
) -> Dict[str, Any]:
    """
    Compare bookmaker probability for the picked outcome with ELO's.

    Returns a dict with:
    - ml_available (bool)
    - ml_probabilities (dict or None)
    - ml_prob_for_pick (float or None)  — what ML says about THIS specific pick
    - bookmaker_prob_for_pick (float)
    - diff (float)                        — abs difference
    - agreement (str)                     — 'agree' | 'mild_disagree' | 'strong_disagree' | 'n/a'

    Picks where agreement == 'agree' should be promoted.
    Picks where agreement == 'strong_disagree' should be skipped or demoted.
    """
    # Derive bookmaker probability for compound picks (double chance)
    # to match the same key space we'll use for ML
    def _bk_prob_for(key: str) -> float:
        if key in bookmaker_probs:
            return bookmaker_probs.get(key) or 0
        if key == "home_or_draw":
            return (bookmaker_probs.get("home_win") or 0) + (bookmaker_probs.get("draw") or 0)
        if key == "away_or_draw":
            return (bookmaker_probs.get("away_win") or 0) + (bookmaker_probs.get("draw") or 0)
        return 0

    result = {
        "ml_available": False,
        "ml_probabilities": None,
        "ml_prob_for_pick": None,
        "bookmaker_prob_for_pick": round(_bk_prob_for(pick_key), 4),
        "diff": None,
        "agreement": "n/a",
    }

    ml_probs = elo_probabilities(home_team, away_team)
    if not ml_probs:
        return result

    result["ml_available"] = True
    result["ml_probabilities"] = ml_probs

    # Map pick to ELO output
    if pick_key in ml_probs:
        ml_prob = ml_probs[pick_key]
    elif pick_key == "home_or_draw":
        ml_prob = ml_probs["home_win"] + ml_probs["draw"]
    elif pick_key == "away_or_draw":
        ml_prob = ml_probs["away_win"] + ml_probs["draw"]
    else:
        # Goals markets — ELO doesn't predict goals; skip
        return result

    result["ml_prob_for_pick"] = round(ml_prob, 4)
    bk_prob = result["bookmaker_prob_for_pick"] or 0
    diff = abs(ml_prob - bk_prob)
    result["diff"] = round(diff, 4)

    if diff <= threshold:
        result["agreement"] = "agree"
    elif diff <= threshold * 2:
        result["agreement"] = "mild_disagree"
    else:
        result["agreement"] = "strong_disagree"

    return result
