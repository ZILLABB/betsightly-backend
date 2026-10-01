"""Cache-only SportyBet-first shadow enrichment and comparison.

The production prepared board remains authoritative. This module reads already
prepared/cached data and produces diagnostics only. It never refreshes a
provider, publishes a pick, creates a booking, or writes a canonical mapping.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from leagues import canonical_identity, sportybet_inventory

FULL = "FULL"
PARTIAL = "PARTIAL"
SPORTYBET_ONLY = "SPORTYBET_ONLY"
STALE_FALLBACK = "STALE_FALLBACK"
AMBIGUOUS = "AMBIGUOUS"
UNSUPPORTED = "UNSUPPORTED"

STRONG = "STRONG"
ADEQUATE = "ADEQUATE"
THIN = "THIN"
VERY_THIN = "VERY_THIN"
NO_SUPPORT = "UNSUPPORTED"

MATCHED_STATES = {
    canonical_identity.EXACT_ID,
    canonical_identity.EXACT_ALIAS,
    canonical_identity.TEAM_KICKOFF,
    canonical_identity.FUZZY_VERIFIED,
}


def _iso_date(value) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def _prepared_candidates(fixtures: list[dict]) -> list[dict]:
    out = []
    for fixture in fixtures or []:
        home = (fixture.get("home") or {}).get("name") or fixture.get("home_team")
        away = (fixture.get("away") or {}).get("name") or fixture.get("away_team")
        kickoff = fixture.get("commence_time") or fixture.get("kickoff")
        fixture_id = (
            fixture.get("match_id")
            or fixture.get("event_id")
            or fixture.get("fixture_id")
        )
        if not home or not away or not kickoff or fixture_id in (None, ""):
            continue
        out.append({
            "id": f"prepared:{fixture_id}",
            "home_team": home,
            "away_team": away,
            "kickoff": kickoff,
            "competition": (
                fixture.get("league")
                or (fixture.get("competition") or {}).get("name")
                or fixture.get("competition_name")
                or ""
            ),
            "source_fixture": fixture,
        })
    return out


def _api_candidates(fixtures: list[dict]) -> list[dict]:
    out = []
    for fixture in fixtures or []:
        fixture_id = fixture.get("fixture_id")
        home = fixture.get("home_team")
        away = fixture.get("away_team")
        kickoff = fixture.get("date") or fixture.get("kickoff")
        if not fixture_id or not home or not away or not kickoff:
            continue
        out.append({
            "id": f"api_football:{fixture_id}",
            "home_team": home,
            "away_team": away,
            "kickoff": kickoff,
            "competition": fixture.get("league_name") or "",
            "country": fixture.get("country_name") or "",
            "source_fixture": fixture,
        })
    return out


def cached_apifootball_fixtures(dates: set[str]) -> list[dict]:
    """Read API-Football daily cache only; never call the network."""
    if not dates:
        return []

    try:
        from services.apifootball_service import APIFootballService
        service = APIFootballService(api_key="")
    except Exception:
        return []

    fixtures = []
    seen = set()
    for target_date in sorted(dates):
        try:
            payload = service._read_daily_cache(target_date)
        except Exception:
            payload = None
        if not payload:
            continue
        for raw in payload.get("response", []) or []:
            try:
                parsed = service._parse_fixture(raw)
            except Exception:
                parsed = None
            if not parsed:
                continue
            fixture_id = str(parsed.get("fixture_id") or "")
            if not fixture_id or fixture_id in seen:
                continue
            seen.add(fixture_id)
            fixtures.append(parsed)
    return fixtures


def _support_for(state: str, identity_state: str) -> str:
    if state == FULL:
        return STRONG
    if state == PARTIAL:
        return ADEQUATE
    if state == STALE_FALLBACK:
        return THIN
    if state == SPORTYBET_ONLY:
        return VERY_THIN
    if identity_state in {
        canonical_identity.AMBIGUOUS,
        canonical_identity.UNMATCHED,
    }:
        return NO_SUPPORT
    return NO_SUPPORT


def compare(
    inventory: dict,
    prepared_fixtures: list[dict],
    *,
    prepared_status: dict | None = None,
    api_fixtures: list[dict] | None = None,
) -> dict:
    """Compare shadow inventory to prepared/API-Football data without side effects."""
    prepared_status = prepared_status or {}
    api_fixtures = api_fixtures or []
    prepared = _prepared_candidates(prepared_fixtures)
    api = _api_candidates(api_fixtures)

    fixture_rows = []
    state_counts = Counter()
    identity_counts = Counter()
    support_counts = Counter()

    for fixture in inventory.get("fixtures") or []:
        event_id = str(fixture.get("sportybet_event_id") or "")
        if not event_id or not fixture.get("home_team") or not fixture.get("away_team"):
            identity = {
                "state": canonical_identity.UNMATCHED,
                "canonical_fixture_id": None,
                "confidence": 0.0,
                "method": "invalid_shadow_fixture",
                "candidates": [],
                "reason": "missing_required_identity_fields",
            }
            state = UNSUPPORTED
            api_identity = None
        else:
            identity = canonical_identity.resolve_fixture(fixture, prepared)
            api_identity = canonical_identity.resolve_fixture(fixture, api)

            if identity["state"] == canonical_identity.AMBIGUOUS:
                state = AMBIGUOUS
            elif identity["state"] in MATCHED_STATES:
                if prepared_status.get("stale"):
                    state = STALE_FALLBACK
                elif api_identity["state"] in MATCHED_STATES:
                    state = FULL
                else:
                    state = PARTIAL
            elif identity["state"] == canonical_identity.UNMATCHED:
                if api_identity["state"] == canonical_identity.AMBIGUOUS:
                    state = AMBIGUOUS
                elif api_identity["state"] in MATCHED_STATES:
                    # API-Football alone is useful corroboration, but until the
                    # production fixture identity also resolves this remains a
                    # SportyBet-only shadow candidate and cannot drive picks.
                    state = SPORTYBET_ONLY
                else:
                    state = SPORTYBET_ONLY
            else:
                state = UNSUPPORTED

        support = _support_for(state, identity["state"])
        state_counts[state] += 1
        identity_counts[identity["state"]] += 1
        support_counts[support] += 1

        fixture_rows.append({
            "sportybet_event_id": event_id or None,
            "home_team": fixture.get("home_team"),
            "away_team": fixture.get("away_team"),
            "kickoff": fixture.get("kickoff"),
            "competition": fixture.get("competition"),
            "identity_state": identity["state"],
            "identity_confidence": identity["confidence"],
            "prepared_fixture_id": identity.get("canonical_fixture_id"),
            "api_football_state": (
                api_identity.get("state") if api_identity else None
            ),
            "api_football_fixture_id": (
                api_identity.get("canonical_fixture_id")
                if api_identity else None
            ),
            "enrichment_state": state,
            "data_support": support,
        })

    total = len(fixture_rows)
    matched_prepared = sum(
        1 for row in fixture_rows
        if row["identity_state"] in MATCHED_STATES
    )
    api_supported = sum(
        1 for row in fixture_rows
        if row["api_football_state"] in MATCHED_STATES
    )
    return {
        "status": "success" if total else "unavailable",
        "source": "SPORTYBET_FIRST_SHADOW_BOARD",
        "shadow_only": True,
        "can_publish": False,
        "can_book": False,
        "authoritative_for_user_output": False,
        "sportybet_snapshot_id": inventory.get("snapshot_id"),
        "sportybet_complete": bool(inventory.get("complete")),
        "production_board_snapshot_id": prepared_status.get("board_snapshot_id"),
        "production_board_ready": bool(prepared_status.get("ready")),
        "production_board_stale": bool(prepared_status.get("stale")),
        "sportybet_fixture_count": total,
        "prepared_fixture_count": len(prepared),
        "api_football_cached_fixture_count": len(api),
        "prepared_match_count": matched_prepared,
        "api_football_support_count": api_supported,
        "prepared_match_rate": round(matched_prepared / total, 4) if total else 0.0,
        "api_football_support_rate": round(api_supported / total, 4) if total else 0.0,
        "enrichment_states": dict(state_counts),
        "identity_states": dict(identity_counts),
        "data_support": dict(support_counts),
        "fixtures": fixture_rows,
    }


def current_shadow_comparison() -> dict:
    """Read only current caches/prepared memory; never fan out to providers."""
    inventory = sportybet_inventory.cached_shadow_inventory()

    try:
        from leagues.engine import prepared_board_status, prepared_pipeline
        prepared_status = prepared_board_status(days_ahead=7)
        if prepared_status.get("ready"):
            _, prepared_fixtures = prepared_pipeline(days_ahead=7)
        else:
            prepared_fixtures = []
    except Exception:
        prepared_status = {"ready": False}
        prepared_fixtures = []

    dates = {
        date
        for fixture in inventory.get("fixtures") or []
        if (date := _iso_date(fixture.get("kickoff")))
    }
    api_fixtures = cached_apifootball_fixtures(dates)

    return compare(
        inventory,
        prepared_fixtures,
        prepared_status=prepared_status,
        api_fixtures=api_fixtures,
    )


def status() -> dict:
    """Return compact comparison metrics without the per-fixture payload."""
    result = current_shadow_comparison()
    return {
        key: value
        for key, value in result.items()
        if key != "fixtures"
    }
