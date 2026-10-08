"""Read-only quality-qualified fixture dates after a thin official day.

This is a PREVIEW of future match-day inventory, not an alternative official
publication. It must not save cards, settle slips, fetch providers, generate
SportyBet codes, or overwrite the immutable Today result.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from leagues.availability import BOOKING_BUFFER
from leagues.publication_policy import filter_official_candidates, rejection_summary


def next_available_quality_board(
    picks: list[dict],
    *,
    now: datetime | None = None,
    horizon_days: int = 6,
    min_unique_fixtures: int = 3,
    preview_limit: int = 25,
) -> dict:
    """Find first FUTURE WAT date with enough official-quality unique matches.

    'Qualified' means a selection passes the existing Publication Contract V1,
    not simply that its fixture appears on ESPN or has a SportyBet price.
    The returned selections have NOT been individually booked or read back;
    no code/actionable status is exposed.
    """
    from leagues.engine import kickoff_wat_date
    from leagues.fixture_ranker import canonical_fixture_recommendations
    from leagues.picks import to_game
    from leagues.selection_quality import selection_probability

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    wat_date = (instant + timedelta(hours=1)).date()
    booking_boundary = instant + BOOKING_BUFFER
    days = max(1, min(7, int(horizon_days)))
    minimum = max(1, int(min_unique_fixtures))
    preview_limit = max(1, min(50, int(preview_limit)))

    grouped: dict[str, list[dict]] = {}
    for pick in picks:
        raw = (pick.get("_fixture") or {}).get("commence_time")
        if not raw:
            continue
        try:
            kickoff = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                continue
            kickoff = kickoff.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if kickoff < booking_boundary:
            continue
        day = kickoff_wat_date(raw)
        grouped.setdefault(day, []).append(pick)

    evaluated_dates = []
    best = None
    for offset in range(1, days + 1):
        day = (wat_date + timedelta(days=offset)).isoformat()
        raw = grouped.get(day, [])
        ranked = canonical_fixture_recommendations(raw) if raw else []
        qualified, rejected = filter_official_candidates(ranked, "5_odds")
        # One opinion per fixture to represent usable supply truthfully,
        # without counting several correlated markets as separate games.
        unique: dict[str, dict] = {}
        for pick in sorted(
            qualified,
            key=lambda p: (-selection_probability(p), str(p.get("match_id") or "")),
        ):
            fixture_id = str(pick.get("match_id") or "")
            if fixture_id and fixture_id not in unique:
                unique[fixture_id] = pick

        row = {
            "fixture_date_wat": day,
            "raw_fixture_count": len({str(p.get("match_id")) for p in raw}),
            "ranked_selection_count": len(ranked),
            "qualified_selection_count": len(qualified),
            "qualified_unique_fixture_count": len(unique),
            "rejection_reasons": rejection_summary(rejected),
        }
        evaluated_dates.append(row)
        if best is None and len(unique) >= minimum:
            chosen = list(unique.values())[:preview_limit]
            best = {
                "fixture_target_date": day,
                "qualified_unique_fixture_count": len(unique),
                "candidates": [to_game(p) for p in chosen],
            }

    return {
        "status": "success",
        "publication_date_wat": wat_date.isoformat(),
        "available": best is not None,
        "preview_only": True,
        "official_publication": False,
        "bookable_code_verified": False,
        "actionable": False,
        "reason": (
            "Next fixture date with sufficient verified model-quality candidates."
            if best else
            "No future fixture date in this prepared window meets the quality requirement."
        ),
        "minimum_qualified_fixtures": minimum,
        "evaluated_dates": evaluated_dates,
        "next_available": best,
    }
