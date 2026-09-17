"""One football opinion per fixture, before any accumulator product rules.

The raw pipeline intentionally produces several markets for one match.  This
module turns that evaluated universe into the small, reusable recommendation
board consumed by public match discovery and, through the canonical candidate
list, by Daily/Builder products.  Classification describes recommendation
strength; it never changes the underlying probability or market ranking.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from leagues.fixture_ranker import canonical_fixture_recommendations
from leagues.engine import kickoff_wat_date
from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE, to_game
from leagues.selection_quality import selection_probability

WAT = timezone(timedelta(hours=1))


def recommendation_classification(pick: dict) -> str:
    """Classify the best available opinion without inventing a new model.

    STRONG is deliberately narrower than "publishable": it requires the
    canonical market policy to call the market trusted as well as clearing the
    existing 65% premium floor.  SUPPORTED can describe a credible developing
    market or a trusted 60-65% opinion.  Everything else remains visible as a
    LEAN but is not eligible for an accumulator merely by existing.
    """
    probability = selection_probability(pick)
    state = pick.get("market_trust_state")
    if not pick.get("market_floor_eligible", True):
        return "LEAN"
    if state == "TRUSTED" and probability >= MIN_PUBLISHABLE_CONFIDENCE:
        return "STRONG"
    if state in {"TRUSTED", "DEVELOPING", "PROVISIONAL"} and probability >= .60:
        return "SUPPORTED"
    return "LEAN"


def _fixture_stub(fixture: dict) -> dict:
    return {
        "match_id": str(fixture.get("match_id") or ""),
        "home_team": (fixture.get("home") or {}).get("name", ""),
        "away_team": (fixture.get("away") or {}).get("name", ""),
        "home_team_logo": (fixture.get("home") or {}).get("logo"),
        "away_team_logo": (fixture.get("away") or {}).get("logo"),
        "league": fixture.get("league", ""),
        "league_slug": fixture.get("league_slug", ""),
        "kickoff": fixture.get("commence_time"),
        "date": fixture.get("commence_time"),
    }


def build_recommendation_board(
    all_picks: list[dict], fixtures: list[dict], *, date: str | None = None,
) -> dict:
    """Return one best public recommendation for each fixture on a WAT date."""
    target_date = date or datetime.now(WAT).date().isoformat()
    target_fixtures = [
        fixture for fixture in fixtures
        if kickoff_wat_date(fixture.get("commence_time")) == target_date
    ]
    fixture_ids = {str(fixture.get("match_id")) for fixture in target_fixtures}
    target_picks = [
        pick for pick in all_picks if str(pick.get("match_id")) in fixture_ids
    ]

    ranked = canonical_fixture_recommendations(
        target_picks, include_all_eligible=True, include_subfloor=True
    )
    by_fixture: dict[str, list[dict]] = {}
    for pick in ranked:
        by_fixture.setdefault(str(pick.get("match_id")), []).append(pick)
    for values in by_fixture.values():
        values.sort(key=lambda pick: int(pick.get("public_rank") or 999))

    raw_counts = Counter(str(pick.get("match_id")) for pick in target_picks)
    recommendations = []
    no_prediction = []
    classification_counts = Counter()
    market_counts = Counter()

    for fixture in sorted(
        target_fixtures, key=lambda item: item.get("commence_time") or ""
    ):
        match_id = str(fixture.get("match_id"))
        candidates = by_fixture.get(match_id, [])
        if not candidates:
            reason = (
                "NO_CANDIDATE_CLEARED_BASE_DATA_AND_SANITY_GATES"
                if not raw_counts[match_id]
                else "NO_CREDIBLE_PUBLIC_MARKET"
            )
            no_prediction.append({**_fixture_stub(fixture), "reason": reason})
            continue

        best = candidates[0]
        classification = recommendation_classification(best)
        probability = selection_probability(best)
        state = best.get("market_trust_state")
        premium_eligible = (
            probability >= MIN_PUBLISHABLE_CONFIDENCE
            and state in {"TRUSTED", "DEVELOPING"}
            and bool(best.get("market_floor_eligible", True))
        )
        classification_counts[classification] += 1
        market_counts[str(best.get("market") or "unknown")] += 1
        recommendations.append({
            "match_id": match_id,
            "classification": classification,
            "premium_eligible": premium_eligible,
            "safe_tier_eligible": bool(best.get("safe_tier_eligible")),
            "best_pick": to_game(best),
            "alternatives": [to_game(pick) for pick in candidates[1:4]],
            "raw_candidate_count": raw_counts[match_id],
            "public_candidate_count": len(candidates),
        })

    analysed = len(target_fixtures)
    recommended = len(recommendations)
    return {
        "status": "success",
        "date": target_date,
        "timezone": "WAT",
        "summary": {
            "fixtures_analysed": analysed,
            "raw_market_candidates": len(target_picks),
            "recommendations": recommended,
            "strong": classification_counts["STRONG"],
            "supported": classification_counts["SUPPORTED"],
            "lean": classification_counts["LEAN"],
            "no_prediction": len(no_prediction),
            "premium_eligible": sum(
                bool(item["premium_eligible"]) for item in recommendations
            ),
            "sportybet_bookable": sum(
                bool(item["best_pick"].get("bookable"))
                for item in recommendations
            ),
        },
        "market_distribution": dict(sorted(market_counts.items())),
        "recommendations": recommendations,
        "no_prediction": no_prediction,
    }
