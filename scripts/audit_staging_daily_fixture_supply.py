"""Read-only staging provenance: why hundreds of bookable fixtures are absent.

Produces per-WAT-day ESPN/BetSightly vs SportyBet exact-ID coverage and the
latest prepared board's official per-market rejection counts. It does not
fetch provider pages, build a model, create booking codes or publish slips.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from scripts.prepare_staging_board_once import preflight
from scripts.preview_staging_official_card import diagnose_supply

WAT = timezone(timedelta(hours=1))


def inventory_for_day(
    board: dict, fixtures: list[dict], target_wat_date: str,
) -> dict:
    from leagues import sportybet
    from leagues.availability import parse_kickoff

    registered_ids = set()
    espn_count = 0
    for fx in fixtures:
        kickoff = parse_kickoff(fx.get("commence_time"))
        if not kickoff or kickoff.astimezone(WAT).date().isoformat() != target_wat_date:
            continue
        espn_count += 1
        event_id = ((fx.get("odds") or {}).get("sportybet_event_id"))
        if event_id:
            registered_ids.add(str(event_id))

    counted = Counter()
    missing_by_competition = Counter()
    examples = {}
    seen = set()
    for _, entry in sportybet._board_entries(board):
        event_id = str(entry.get("event_id") or "")
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        try:
            kickoff = datetime.fromtimestamp(
                float(entry.get("kickoff_ms")) / 1000, tz=timezone.utc
            )
        except (TypeError, ValueError, OverflowError, OSError):
            counted["invalid_kickoff"] += 1
            continue
        if kickoff.astimezone(WAT).date().isoformat() != target_wat_date:
            continue

        counted["sportybet_total"] += 1
        priced = bool(entry.get("prices"))
        if priced:
            counted["priced"] += 1
        if event_id in registered_ids:
            counted["already_modelled_from_espn"] += 1
            continue
        counted["sportybet_only"] += 1
        mapping = sportybet.registry_competition_match(
            str(entry.get("competition") or ""),
            tournament_id=entry.get("sportybet_tournament_id"),
            category_id=entry.get("sportybet_category_id"),
        )
        if mapping.get("status") != "MAPPED_EXACT":
            counted["unmapped_competition"] += 1
            key = (
                str(entry.get("sportybet_category") or ""),
                str(entry.get("competition") or ""),
                str(entry.get("sportybet_tournament_id") or ""),
                str(entry.get("sportybet_category_id") or ""),
            )
            missing_by_competition[key] += 1
            continue
        counted["mapped_sportybet_only"] += 1
        if entry.get("home_squad") or entry.get("away_squad"):
            counted["mapped_unsupported_squad"] += 1
            continue
        if not priced:
            counted["mapped_unpriced"] += 1
            continue
        counted["mapped_senior_priced"] += 1
        slug = str(mapping.get("league_slug") or "")
        examples[slug] = examples.get(slug, 0) + 1

    return {
        "target_wat_date": target_wat_date,
        "modelled_espn_fixtures": espn_count,
        "sportybet_fixture_count": counted["sportybet_total"],
        "sportybet_priced_count": counted["priced"],
        "already_modelled_with_exact_sportybet_event_id": counted[
            "already_modelled_from_espn"
        ],
        "sportybet_only_fixture_count": counted["sportybet_only"],
        "sportybet_only_unmapped_competition": counted["unmapped_competition"],
        "sportybet_only_exact_competition_map": counted[
            "mapped_sportybet_only"
        ],
        "sportybet_only_mapped_senior_priced": counted["mapped_senior_priced"],
        "sportybet_only_mapped_unsupported_squad": counted[
            "mapped_unsupported_squad"
        ],
        "sportybet_only_mapped_unpriced": counted["mapped_unpriced"],
        "potential_history_ready_leagues": dict(sorted(examples.items())),
        "top_unmapped_competitions": [
            {
                "sportybet_category": category,
                "competition": name,
                "sportybet_tournament_id": tid,
                "sportybet_category_id": cid,
                "fixture_count": count,
            }
            for (category, name, tid, cid), count
            in missing_by_competition.most_common(25)
        ],
        "note": (
            "Mapped/senior/priced is NOT evidence of calibrated probability, "
            "safe publication, valid team history or actual booking-code readback."
        ),
    }


def historical_coverage_from_staging(
    board: dict, date_wat: str, fixtures: list[dict],
) -> dict:
    """Read only the isolated, optional external training warehouse."""
    from database import engine as db_engine
    from sqlalchemy import text as sql_text
    with db_engine.connect() as conn:
        table = conn.execute(sql_text(
            "SELECT to_regclass('public.external_historical_results_v1')"
        )).scalar()
        if table is None:
            return {"status": "HISTORY_NOT_INGESTED"}
        rows = [dict(row) for row in conn.execute(sql_text("""
            SELECT fixture_key, league_slug, match_date,
                   home_team, away_team
            FROM external_historical_results_v1
            WHERE match_date >= CAST(:date AS date) - INTERVAL '365 days'
              AND match_date < CAST(:date AS date)
        """), {"date": date_wat}).mappings()]
    from leagues.staging_source_history_coverage import compare_coverage
    return {
        "status": "ANALYZED",
        **compare_coverage(
            board, rows, date_wat,
            existing_event_ids=frozenset(
                str((fixture.get("odds") or {}).get("sportybet_event_id"))
                for fixture in fixtures
                if (fixture.get("odds") or {}).get("sportybet_event_id")
            ),
        ),
    }


def audit(target_wat_date: str, *, refresh_if_stale: bool = False) -> dict:
    database = preflight()
    requested = date.fromisoformat(target_wat_date)
    today = datetime.now(WAT).date()
    if requested < today or requested > today + timedelta(days=6):
        raise ValueError("Requested WAT date must be in current seven-day board")

    from leagues import sportybet
    from leagues.engine import prepared_board
    picks, fixtures, prepared = prepared_board(days_ahead=7)
    refreshed = False
    if not prepared.get("ready") or prepared.get("stale"):
        if not refresh_if_stale:
            raise RuntimeError(
                "Prepared staging board is missing/stale "
                f"(age_seconds={prepared.get('age_seconds')}). "
                "Run python -m scripts.prepare_staging_board_once or "
                "explicitly specify --refresh-if-stale."
            )
        # Explicit CLI permission only. prepare_once repeats the staging
        # environment, disabled-jobs and *actual DB identity* safety guards.
        from scripts.prepare_staging_board_once import prepare_once
        prepare_once()
        refreshed = True
        picks, fixtures, prepared = prepared_board(days_ahead=7)
        if not prepared.get("ready") or prepared.get("stale"):
            raise RuntimeError(
                "Staging board remains unusable after explicit refresh"
            )

    # Read the existing persisted SportyBet cache. Never call fetch_board(),
    # which may silently trigger a new provider request.
    cache = sportybet._db_get("sportybet_board") or {}
    if not cache.get("fixtures") or not (cache.get("metadata") or {}).get("is_complete"):
        raise RuntimeError("SportyBet cache missing or incomplete")
    sportsbook = sportybet._snapshot(cache["fixtures"], cache["metadata"])
    now = datetime.now(timezone.utc)
    cover = inventory_for_day(sportsbook, fixtures, target_wat_date)
    provider = prepared.get("provider") or {}
    shadow = provider.get("sportybet_shadow_supplemental") or {}
    supply = diagnose_supply(picks, target_wat_date, now)
    from leagues.forecast_coverage import coverage_funnel
    forecast = coverage_funnel(fixtures, picks, date=target_wat_date)

    historical_coverage = historical_coverage_from_staging(
        sportsbook, target_wat_date, fixtures,
    )
    return {
        "database": database,
        "target_wat_date": target_wat_date,
        "read_only": not refreshed,
        "board_refreshed": refreshed,
        "publication_changed": False,
        "booking_codes_created": False,
        "prepared_snapshot": prepared.get("board_snapshot_id"),
        "prepared_board_age_seconds": prepared.get("age_seconds"),
        "sportybet_cache_snapshot": (cache.get("metadata") or {}).get("snapshot_id"),
        "per_day_fixture_inventory": cover,
        "official_target_day_eligibility": supply,
        "forecast_and_model_value_diagnostics": forecast,
        "external_historical_match_coverage": historical_coverage,
        "seven_day_shadow_history_readiness_counts": shadow.get("readiness_counts") or {},
        "seven_day_ready_for_shadow_model": shadow.get("ready_for_shadow_model_count"),
        "seven_day_shadows_modelled": (
            (provider.get("sportybet_shadow_model") or {}).get("modelled_fixture_count")
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD WAT")
    parser.add_argument(
        "--refresh-if-stale", action="store_true",
        help="Explicitly regenerate the staging-only prepared board if stale",
    )
    args = parser.parse_args()
    print(json.dumps(
        audit(args.date, refresh_if_stale=args.refresh_if_stale),
        sort_keys=True, default=str,
    ))
