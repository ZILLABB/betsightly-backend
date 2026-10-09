"""Expanding-window historical challenger benchmark with forward-only folds.

Each fold retrains from genuine earlier results and tests a later contiguous
calendar-date block. 7-day train/test embargo is explicit. This is shadow
research, NOT champion comparison, verified SportyBet price value or an
automatic deployment decision.
"""
from __future__ import annotations

from datetime import date, timedelta

MARKET_KEYS = ("match_result", "over_1_5", "over_2_5", "btts_yes")


def walk_forward_windows(
    examples: list[dict], *, folds: int = 4, initial_fraction: float = 0.45,
    embargo_days: int = 7, minimum_training: int = 200,
    minimum_holdout: int = 50,
) -> list[tuple[list[dict], list[dict], dict]]:
    """Chronological train/holdout windows without shared dates or future input."""
    if not 2 <= folds <= 8:
        raise ValueError("folds must be between two and eight")
    if not .3 <= initial_fraction <= .8:
        raise ValueError("initial_fraction must be between .3 and .8")
    if not 0 <= embargo_days <= 30:
        raise ValueError("embargo_days must be between zero and thirty")
    if minimum_training < 1 or minimum_holdout < 1:
        raise ValueError("minimum training and holdout counts must be positive")

    unique_days = sorted({
        date.fromisoformat(str(row["match_date"])[:10]) for row in examples
    })
    earliest_holdout_index = int(len(unique_days) * initial_fraction)
    test_days = unique_days[earliest_holdout_index:]
    if len(test_days) < folds:
        return []

    ordered = sorted(
        examples, key=lambda row: (
            str(row["match_date"]), str(row.get("fixture_key") or ""),
        ),
    )
    results = []
    for fold in range(folds):
        lo = len(test_days) * fold // folds
        hi = len(test_days) * (fold + 1) // folds
        day_from = test_days[lo]
        # End is exclusive, unless this is the last fold.
        day_to = test_days[hi] if hi < len(test_days) else None
        train_max = day_from - timedelta(days=embargo_days)
        training = [
            row for row in ordered
            if date.fromisoformat(str(row["match_date"])[:10]) < train_max
        ]
        holdout = [
            row for row in ordered
            if day_from <= date.fromisoformat(str(row["match_date"])[:10])
            and (day_to is None or
                 date.fromisoformat(str(row["match_date"])[:10]) < day_to)
        ]
        if len(training) < minimum_training or len(holdout) < minimum_holdout:
            continue
        assert max(str(row["match_date"]) for row in training) < min(
            str(row["match_date"]) for row in holdout
        )
        results.append((
            training, holdout,
            {
                "fold_index": fold + 1,
                "train_n": len(training),
                "holdout_n": len(holdout),
                "train_ends": str(training[-1]["match_date"])[:10],
                "test_starts": day_from.isoformat(),
                "test_ends": str(holdout[-1]["match_date"])[:10],
                "embargo_days": embargo_days,
            },
        ))
    return results


def evaluate_walk_forward(
    examples: list[dict], *, folds: int = 4, embargo_days: int = 7,
) -> dict:
    from leagues.shadow_historical_challenger import evaluate_shadow

    windows = walk_forward_windows(
        examples, folds=folds, embargo_days=embargo_days
    )
    history = []
    for training, holdout, metadata in windows:
        result = evaluate_shadow(training, holdout)
        summary = {}
        for market in MARKET_KEYS:
            report = (result.get("baseline_comparison") or {}).get(market) or {}
            if report.get("status") != "SHADOW_EVALUATED":
                summary[market] = {"status": report.get("status", "NOT_EVALUATED")}
                continue
            diagnostic = report["paired_diagnostics"]["overall"]
            summary[market] = {
                "n": diagnostic["n"],
                "challenger_brier": diagnostic["model_brier"],
                "baseline_brier": diagnostic["baseline_brier"],
                "league_conditional_baseline_brier": report[
                    "league_conditional_baseline_brier"
                ],
                "beats_league_conditional_baseline": report[
                    "beats_league_conditional_baseline"
                ],
                "improvement": diagnostic["paired_improvement"],
                "challenger_better": diagnostic["model_better"],
                "nominal_95pct_ci": diagnostic["nominal_95pct_ci"],
            }
        history.append({**metadata, "results": summary})

    totals = {}
    for market in MARKET_KEYS:
        measured = [
            row["results"][market] for row in history
            if row["results"][market].get("n")
        ]
        n = sum(row["n"] for row in measured)
        if not n:
            totals[market] = {"status": "INSUFFICIENT_FOLD_EVIDENCE"}
            continue
        mean_model = sum(row["challenger_brier"] * row["n"]
                         for row in measured) / n
        mean_base = sum(row["baseline_brier"] * row["n"]
                        for row in measured) / n
        mean_league_base = sum(
            row["league_conditional_baseline_brier"] * row["n"]
            for row in measured
        ) / n
        totals[market] = {
            "status": "WALK_FORWARD_EVALUATED",
            "test_matches": n,
            "evaluated_folds": len(measured),
            "winning_folds": sum(
                row["challenger_better"] for row in measured
            ),
            "weighted_challenger_brier": round(mean_model, 6),
            "weighted_baseline_brier": round(mean_base, 6),
            "weighted_league_conditional_baseline_brier": round(
                mean_league_base, 6,
            ),
            "weighted_improvement": round(mean_base - mean_model, 6),
            "weighted_improvement_vs_league_conditional": round(
                mean_league_base - mean_model, 6,
            ),
            "folds_beating_league_conditional_baseline": sum(
                row["beats_league_conditional_baseline"] for row in measured
            ),
            "consistently_better_in_all_folds": all(
                row["challenger_better"] for row in measured
            ) and len(measured) == folds,
            "consistently_beats_league_conditional": all(
                row["beats_league_conditional_baseline"] for row in measured
            ) and len(measured) == folds,
        }

    return {
        "status": "WALK_FORWARD_SHADOW_EVIDENCE_ONLY",
        "requested_folds": folds, "evaluated_folds": len(history),
        "embargo_days": embargo_days,
        "folds": history,
        "markets": totals,
        "champion_model_unchanged": True,
        "production_promotion_authorized": False,
        "no_sportybet_odds_or_clv_comparison": True,
        "source_scores_independently_verified": False,
        "note": (
            "Includes harder train-only league-specific rate baselines, "
            "but no bookmaker price-based edge, production champion comparison, "
            "or independent "
            "result verification has been established."
        ),
    }
