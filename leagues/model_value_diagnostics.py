"""Read-only explanation of model return, before and after evidence shrinkage."""
from collections import Counter

from leagues.selection_quality import risk_adjusted_return


def _raw_return(pick):
    odds = float(pick.get("odds") or 1)
    probability = float(pick.get("confidence") or 0)
    if pick.get("market") in {"dnb_home", "dnb_away"}:
        draw = ((pick.get("_model") or {}).get("probabilities") or {}).get("draw")
        if draw is not None:
            draw = max(0.0, min(1.0, float(draw)))
            return probability * (1 - draw) * odds + draw
    return probability * odds


def summarize_value(picks: list[dict]) -> dict:
    """Analyze priced selections, never decide which ones to publish."""
    counts = Counter()
    by_market: dict[str, Counter] = {}
    mismatches = []
    for pick in picks:
        market = str(pick.get("market") or "unknown")
        current = by_market.setdefault(market, Counter())
        current["candidates"] += 1
        counts["candidates"] += 1
        if not (pick.get("bookable") and pick.get("odds_are_real")):
            counts["without_exact_real_price"] += 1
            current["without_exact_real_price"] += 1
            continue
        counts["real_bookable"] += 1
        current["real_bookable"] += 1
        raw = _raw_return(pick)
        conservative = risk_adjusted_return(pick)
        if raw >= 1.0:
            counts["raw_return_ge_one"] += 1
            current["raw_return_ge_one"] += 1
        if conservative >= 1.0:
            counts["conservative_return_ge_one"] += 1
            current["conservative_return_ge_one"] += 1
        if raw >= 1.0 and conservative < 1.0:
            counts["positive_to_negative_after_evidence"] += 1
            current["positive_to_negative_after_evidence"] += 1
        if raw < 1.0 and conservative < 1.0:
            counts["negative_before_and_after_evidence"] += 1
            current["negative_before_and_after_evidence"] += 1

        stored = pick.get("risk_adjusted_return")
        if stored is not None:
            try:
                difference = abs(float(stored) - conservative)
            except (ValueError, TypeError):
                difference = float("inf")
            if difference > .005:
                counts["stored_return_mismatches"] += 1
                if len(mismatches) < 10:
                    mismatches.append({
                        "match_id": str(pick.get("match_id") or ""),
                        "market": market,
                        "stored": stored,
                        "recomputed": conservative,
                    })
    return {
        "counts": dict(sorted(counts.items())),
        "by_market": {
            key: dict(sorted(value.items()))
            for key, value in sorted(by_market.items())
        },
        "stored_return_mismatch_samples": mismatches,
        "production_unchanged": True,
        "note": (
            "Model returns are estimated, not realized profit. "
            "Raw uses calibrated confidence; conservative uses "
            "evidence-adjusted probability. The two are intentionally "
            "different. This report never relaxes publication gates."
        ),
    }
