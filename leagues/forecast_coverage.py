"""Read-only forecast-versus-publication coverage funnel for an exact WAT day.

The model forecasts all its supported markets per modelled fixture, while
build_picks and official publication intentionally approve a much smaller
subset. Do not mistake a model forecast for an actionable betting selection.
"""
from __future__ import annotations

from collections import Counter

from leagues.engine import kickoff_wat_date
from leagues.publication_policy import evaluate_leg
from leagues.fixture_ranker import canonical_fixture_recommendations
from leagues.model_value_diagnostics import summarize_value

PRODUCTS = ("banker", "2_odds", "5_odds", "10_odds", "over_1_5", "rollover")


def coverage_funnel(fixtures: list[dict], picks: list[dict], *, date: str) -> dict:
    """No provider calls, model re-runs, writes, or publication side effects."""
    dated = [
        fx for fx in fixtures
        if kickoff_wat_date(fx.get("commence_time")) == date
    ]
    fixture_by_id = {
        str(fx.get("match_id")): fx for fx in dated
        if fx.get("match_id")
    }
    dated_picks = [
        pick for pick in picks
        if str(pick.get("match_id")) in fixture_by_id
    ]

    modelled = []
    missing_model = []
    basic_predictions = 0
    for fid, fx in fixture_by_id.items():
        model = fx.get("_model") or {}
        probabilities = model.get("probabilities") or {}
        # 1X2 is the minimum coherent model opinion, regardless of whether
        # any market is trusted or priced for wagering.
        has_1x2 = all(
            isinstance(probabilities.get(market), (int, float))
            for market in ("home_win", "draw", "away_win")
        )
        if has_1x2:
            basic_predictions += 1
            modelled.append(fid)
        else:
            missing_model.append(fid)

    by_fixture = Counter(str(p.get("match_id")) for p in dated_picks)
    candidates_with_real_prices = [
        p for p in dated_picks if p.get("odds_are_real")
    ]
    candidates_with_exact_bookability = [
        p for p in dated_picks
        if p.get("bookable") and p.get("odds_are_real")
    ]
    ranked_picks = canonical_fixture_recommendations(
        dated_picks, include_all_eligible=True, include_subfloor=True
    )
    eligible_by_product = {}
    for product in PRODUCTS:
        reasons = Counter()
        qualified_ids = set()
        qualified_legs = 0
        for pick in ranked_picks:
            decision = evaluate_leg(pick, product)
            if decision["allowed"]:
                qualified_legs += 1
                qualified_ids.add(str(pick["match_id"]))
            else:
                reasons.update(decision["reasons"])
        eligible_by_product[product] = {
            "approved_legs": qualified_legs,
            "approved_unique_fixtures": len(qualified_ids),
            "rejection_reasons": dict(sorted(reasons.items())),
            "note": "Pre-allocation supply only; not a generated/verified booking code.",
        }

    return {
        "date": date,
        "timezone": "Africa/Lagos",
        "pipeline_stage": "prepared_snapshot_read_only",
        "fixtures_modelled": len(modelled),
        "fixtures_without_coherent_1x2": len(missing_model),
        "fixture_count": len(fixture_by_id),
        "match_result_forecasts": basic_predictions,
        "fixtures_with_any_filtered_candidate": len(by_fixture),
        "fixtures_without_any_filtered_candidate": sum(
            fid not in by_fixture for fid in fixture_by_id
        ),
        "filtered_candidate_legs": len(dated_picks),
        "ranked_candidate_legs": len(ranked_picks),
        "model_value_diagnostics": summarize_value(ranked_picks),
        "real_price_candidate_legs": len(candidates_with_real_prices),
        "real_price_and_exact_bookable_legs": len(
            candidates_with_exact_bookability
        ),
        "eligible_by_product": eligible_by_product,
        "missing_forecast_match_ids": missing_model[:20],
        "publication_changed": False,
        "booking_codes_created": False,
        "explanation": (
            "Model probability is a forecast, not a recommendation. "
            "Official approval also requires trusted settled evidence, "
            "calibration, positive conservative return and exact real "
            "SportyBet bookability. Rejection counts overlap."
        ),
    }
