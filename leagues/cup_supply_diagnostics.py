"""Explain domestic cup attrition without relaxing publication policy.

Only aggregated, non-personal figures reach the daily-card diagnostics. A
football cup may be properly scheduled but fail model, price, verified
competition history or market admission. Counting fixture candidates is NOT
equivalent to counting exactly bookable policy-qualified betting legs.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from leagues.competition_registry import competition_for


def _slug(pick: dict) -> str:
    fixture = pick.get("_fixture") or {}
    return str(fixture.get("league_slug") or pick.get("league_slug") or "")


def _domestic_cup(pick: dict) -> str | None:
    slug = _slug(pick)
    meta = competition_for(slug)
    return slug if meta and meta.competition_type == "DOMESTIC_CUP" else None


def _fixture_id(pick: dict) -> str:
    return str(pick.get("match_id") or (pick.get("_fixture") or {}).get("event_id") or "")


def domestic_cup_supply(
    future_picks: list[dict],
    day_picks: list[dict],
    official_allowed: list[dict],
    official_rejected: list[dict],
    *,
    minimum_cup_history: int = 20,
) -> dict:
    """Aggregate cup fixture/market health at each admission stage.

    Raw candidate counts span several days, while the day/current cutoff is
    reflected by day_picks. Rejection reasons are per selection and may
    overlap. Never infer that one rejection reason explains all other failures.
    """
    by_slug: dict[str, dict] = {}

    def row(slug: str) -> dict:
        if slug not in by_slug:
            by_slug[slug] = {
                "future_fixtures": set(), "daily_fixtures": set(),
                "future_selections": 0, "daily_selections": 0,
                "real_prices": set(), "bookable_fixtures": set(),
                "history_qualified_fixtures": set(), "sparse_history_fixtures": set(),
                "allowed_fixtures": set(), "allowed_selections": 0,
                "rejection_reasons": Counter(), "booking_failures": Counter(),
            }
        return by_slug[slug]

    for pick in future_picks:
        if not isinstance(pick, dict):
            continue
        slug = _domestic_cup(pick)
        if slug is None:
            continue
        item = row(slug)
        item["future_selections"] += 1
        if _fixture_id(pick):
            item["future_fixtures"].add(_fixture_id(pick))

    for pick in day_picks:
        if not isinstance(pick, dict):
            continue
        slug = _domestic_cup(pick)
        if slug is None:
            continue
        item = row(slug)
        item["daily_selections"] += 1
        fid = _fixture_id(pick)
        if fid:
            item["daily_fixtures"].add(fid)
            if pick.get("odds_are_real"):
                item["real_prices"].add(fid)
            if pick.get("bookable"):
                item["bookable_fixtures"].add(fid)
            sample = pick.get("competition_historical_sample")
            if sample is None:
                sample = (pick.get("_fixture") or {}).get("competition_historical_sample")
            try:
                sample = max(0, int(sample or 0))
            except (TypeError, ValueError):
                sample = 0
            if sample >= minimum_cup_history:
                item["history_qualified_fixtures"].add(fid)
            else:
                item["sparse_history_fixtures"].add(fid)
        if not pick.get("bookable"):
            availability = pick.get("sportybet_availability") or {}
            failure = str(availability.get("status") or "UNBOOKABLE")[:64]
            item["booking_failures"][failure] += 1

    # Official rejected selections have no league field. Match the exact
    # identity to the already-canonicalized, same-day selection, never guess.
    cup_index = defaultdict(set)
    for pick in day_picks:
        slug = _domestic_cup(pick) if isinstance(pick, dict) else None
        if slug is not None:
            cup_index[(_fixture_id(pick), str(pick.get("market") or ""))].add(slug)
    for rejected in official_rejected:
        if not isinstance(rejected, dict):
            continue
        key = (str(rejected.get("match_id") or ""),
               str(rejected.get("market") or ""))
        slugs = cup_index.get(key) or set()
        if len(slugs) == 1:
            by_slug[next(iter(slugs))]["rejection_reasons"].update(
                str(x) for x in (rejected.get("reasons") or [])
            )
    for pick in official_allowed:
        slug = _domestic_cup(pick) if isinstance(pick, dict) else None
        if slug is None:
            continue
        item = row(slug)
        item["allowed_selections"] += 1
        if _fixture_id(pick):
            item["allowed_fixtures"].add(_fixture_id(pick))

    serialized = {}
    for slug, item in sorted(by_slug.items()):
        serialized[slug] = {
            "future_fixtures": len(item["future_fixtures"]),
            "future_selections": item["future_selections"],
            "daily_fixtures": len(item["daily_fixtures"]),
            "daily_canonical_selections": item["daily_selections"],
            "daily_real_price_fixtures": len(item["real_prices"]),
            "daily_bookable_fixtures": len(item["bookable_fixtures"]),
            "daily_competition_history_ge_20_fixtures":
                len(item["history_qualified_fixtures"]),
            "daily_competition_history_lt_20_fixtures":
                len(item["sparse_history_fixtures"]),
            "official_allowed_selections": item["allowed_selections"],
            "official_allowed_fixtures": len(item["allowed_fixtures"]),
            "rejection_reasons": dict(sorted(item["rejection_reasons"].items())),
            "bookmaker_unavailable_reasons":
                dict(sorted(item["booking_failures"].items())),
        }
    return {
        "status": "diagnostics_only",
        "policy_changed": False,
        "market_thresholds_relaxed": False,
        "counts_are_selection_and_fixture_specific": True,
        "historical_sample_threshold": minimum_cup_history,
        "note": ("Future fixtures may extend beyond the daily card. "
                 "Reasons may overlap and are not disjoint rejection rates. "
                 "A bookmaker price is not proof of positive model value."),
        "competitions": serialized,
        "total_future_cup_fixtures":
            sum(x["future_fixtures"] for x in serialized.values()),
        "total_day_cup_fixtures":
            sum(x["daily_fixtures"] for x in serialized.values()),
        "total_official_cup_legs":
            sum(x["official_allowed_selections"] for x in serialized.values()),
    }
