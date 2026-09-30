"""Match Context Layer.

Phase 1 is deliberately SHADOW ONLY.

Context may be collected, archived and displayed, but this module must not
change prediction confidence, selection probability, trust grade, market
policy, or SportyBet bookability until retrospective evidence proves that a
specific context signal improves out-of-sample decisions.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


CONTEXT_VERSION = "match_context_v1"
DEFAULT_KICKOFF_TOLERANCE_MINUTES = 120

# Context is intentionally collected only for fixtures that have at least one
# SportyBet-bookable candidate. Twenty-four fixtures normally cost only a
# handful of batched provider calls rather than one request per page visitor.
MAX_CONTEXT_FIXTURES = 24


def _fallback_team_key(value: Any) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)

    return " ".join(text.split())


def team_key(value: Any) -> str:
    """Reuse BetSightly's mature cross-book team normalization when possible."""
    try:
        from leagues.sportybet import _norm
        return str(_norm(str(value or "")) or "")
    except Exception:
        return _fallback_team_key(value)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(
                value.strip().replace("Z", "+00:00")
            )
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _source_fixture(value: dict) -> dict:
    return value.get("_fixture") or value


def _source_team(
    fixture: dict,
    side: str,
) -> str:
    value = fixture.get(side)

    if isinstance(value, dict):
        return str(value.get("name") or "")

    direct = fixture.get(f"{side}_team")

    if isinstance(direct, dict):
        return str(direct.get("name") or "")

    return str(direct or value or "")


def _source_kickoff(fixture: dict) -> datetime | None:
    return _parse_datetime(
        fixture.get("commence_time")
        or fixture.get("date")
        or fixture.get("kickoff")
    )


def match_provider_fixture(
    source: dict,
    provider_fixtures: list[dict],
    *,
    kickoff_tolerance_minutes: int = DEFAULT_KICKOFF_TOLERANCE_MINUTES,
) -> dict | None:
    """Strictly resolve an ESPN/prepared fixture to one API-Football fixture.

    Team identities must match in the same home/away orientation. When both
    sources have a kickoff timestamp, the difference must also remain inside
    the configured tolerance.

    Ambiguous matches fail closed.
    """
    fixture = _source_fixture(source)

    expected_home = team_key(
        _source_team(fixture, "home")
    )
    expected_away = team_key(
        _source_team(fixture, "away")
    )
    expected_kickoff = _source_kickoff(fixture)

    if not expected_home or not expected_away:
        return None

    matches = []

    for provider in provider_fixtures:
        provider_home = team_key(
            provider.get("home_team")
        )
        provider_away = team_key(
            provider.get("away_team")
        )

        if (
            provider_home != expected_home
            or provider_away != expected_away
        ):
            continue

        provider_kickoff = _parse_datetime(
            provider.get("date")
        )

        delta_seconds = 0.0

        if expected_kickoff is not None:
            if provider_kickoff is None:
                continue

            delta_seconds = abs(
                (
                    provider_kickoff
                    - expected_kickoff
                ).total_seconds()
            )

            if delta_seconds > (
                kickoff_tolerance_minutes * 60
            ):
                continue

        matches.append(
            (
                delta_seconds,
                str(
                    provider.get("fixture_id")
                    or ""
                ),
                provider,
            )
        )

    if not matches:
        return None

    matches.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    # Do not guess between two indistinguishable provider fixtures.
    if (
        len(matches) > 1
        and matches[0][0] == matches[1][0]
    ):
        return None

    return matches[0][2]


def _empty_section(
    reason: str,
) -> dict:
    return {
        "status": "UNKNOWN",
        "reason": reason,
    }


def empty_match_context(
    reason: str = "provider_fixture_not_resolved",
) -> dict:
    """Unknown context is neutral context, not negative evidence."""
    return {
        "version": CONTEXT_VERSION,
        "shadow_only": True,
        "provider": "api_football",
        "provider_fixture_id": None,
        "match_status": "UNMATCHED",
        "injuries": _empty_section(reason),
        "suspensions": _empty_section(reason),
        "lineups": _empty_section(reason),
        "rest": _empty_section(
            "not_collected_yet"
        ),
        "weather": _empty_section(
            "not_collected_yet"
        ),
        "venue": _empty_section(reason),
    }


def _lineup_summary(
    fixture_details: dict | None,
) -> dict:
    lineups = (
        fixture_details.get("lineups")
        if isinstance(fixture_details, dict)
        else None
    )

    if not isinstance(lineups, list) or not lineups:
        return _empty_section(
            "lineup_not_published_or_not_covered"
        )

    teams = []

    for lineup in lineups:
        team = lineup.get("team") or {}
        start_xi = lineup.get("startXI") or []

        teams.append({
            "team_id": team.get("id"),
            "team": team.get("name"),
            "formation": lineup.get("formation"),
            "starter_count": len(start_xi),
        })

    return {
        "status": "AVAILABLE",
        "confirmed": len(teams) >= 2,
        "teams": teams,
    }


def _availability_summary(
    injuries_payload: dict | None,
) -> tuple[dict, dict]:
    if injuries_payload is None:
        unknown = _empty_section(
            "injury_endpoint_not_queried"
        )
        return unknown, dict(unknown)

    if injuries_payload.get("errors"):
        unknown = _empty_section(
            "provider_error"
        )
        return unknown, dict(unknown)

    rows = injuries_payload.get("response") or []

    # An empty injury response is deliberately UNKNOWN until league-season
    # injury coverage is explicitly confirmed. We must not interpret missing
    # provider data as "everyone is available".
    if not rows:
        unknown = _empty_section(
            "no_rows_without_coverage_confirmation"
        )
        return unknown, dict(unknown)

    injuries = []
    suspensions = []

    for row in rows:
        player = row.get("player") or {}
        team = row.get("team") or {}

        item = {
            "player_id": player.get("id"),
            "player": player.get("name"),
            "team_id": team.get("id"),
            "team": team.get("name"),
            "type": row.get("type"),
            "reason": row.get("reason"),
        }

        if (
            str(row.get("type") or "")
            .strip()
            .casefold()
            == "suspension"
        ):
            suspensions.append(item)
        else:
            injuries.append(item)

    return (
        {
            "status": "AVAILABLE",
            "count": len(injuries),
            "players": injuries,
        },
        {
            "status": "AVAILABLE",
            "count": len(suspensions),
            "players": suspensions,
        },
    )


def build_shadow_context(
    provider_fixture: dict | None,
    *,
    fixture_details: dict | None = None,
    injuries_payload: dict | None = None,
) -> dict:
    """Build normalized context without changing any prediction values."""
    if not provider_fixture:
        return empty_match_context()

    injuries, suspensions = _availability_summary(
        injuries_payload
    )

    venue_name = provider_fixture.get(
        "venue_name"
    )
    venue_city = provider_fixture.get(
        "venue_city"
    )
    venue_id = provider_fixture.get(
        "venue_id"
    )

    if venue_name or venue_city or venue_id:
        venue = {
            "status": "AVAILABLE",
            "venue_id": venue_id,
            "name": venue_name,
            "city": venue_city,
        }
    else:
        venue = _empty_section(
            "venue_not_available"
        )

    return {
        "version": CONTEXT_VERSION,
        "shadow_only": True,
        "provider": "api_football",
        "provider_fixture_id": provider_fixture.get(
            "fixture_id"
        ),
        "match_status": "MATCHED",
        "injuries": injuries,
        "suspensions": suspensions,
        "lineups": _lineup_summary(
            fixture_details
        ),
        "rest": _empty_section(
            "not_collected_yet"
        ),
        "weather": _empty_section(
            "not_collected_yet"
        ),
        "venue": venue,
    }


def attach_shadow_context(
    source: dict,
    context: dict,
) -> dict:
    """Copy a fixture/pick and attach context without mutating its score."""
    out = dict(source)
    out["match_context"] = dict(context)
    return out



def _context_score(
    pick: dict,
) -> float:
    for key in (
        "selection_probability",
        "confidence",
        "raw_confidence",
    ):
        try:
            value = float(pick.get(key))

            if value > 0:
                return value

        except (TypeError, ValueError):
            continue

    return 0.0


def shortlist_context_fixtures(
    fixtures: list[dict],
    picks: list[dict],
    *,
    limit: int = MAX_CONTEXT_FIXTURES,
) -> list[dict]:
    """Strongest bookable fixture candidates, deterministic and bounded."""
    fixture_by_id = {
        str(fixture.get("match_id") or ""): fixture
        for fixture in fixtures
        if str(fixture.get("match_id") or "")
    }

    best_score = {}

    for pick in picks:
        if not pick.get("bookable"):
            continue

        fixture_id = str(
            pick.get("match_id") or ""
        )

        if fixture_id not in fixture_by_id:
            continue

        score = _context_score(pick)

        best_score[fixture_id] = max(
            score,
            best_score.get(fixture_id, 0.0),
        )

    ranked = sorted(
        best_score,
        key=lambda fixture_id: (
            -best_score[fixture_id],
            str(
                fixture_by_id[fixture_id].get(
                    "commence_time"
                ) or ""
            ),
            fixture_id,
        ),
    )

    return [
        fixture_by_id[fixture_id]
        for fixture_id in ranked[:max(0, int(limit))]
    ]


def _rest_summary(
    fixture: dict,
    history,
) -> dict:
    if history is None:
        return _empty_section(
            "team_history_not_available"
        )

    kickoff = fixture.get(
        "commence_time"
    )

    home = _source_team(
        fixture,
        "home",
    )

    away = _source_team(
        fixture,
        "away",
    )

    team_type = str(
        fixture.get("team_type")
        or "CLUB"
    )

    home_rest = history.rest_context(
        home,
        kickoff,
        team_type=team_type,
    )

    away_rest = history.rest_context(
        away,
        kickoff,
        team_type=team_type,
    )

    if (
        home_rest.get("status") != "AVAILABLE"
        and away_rest.get("status") != "AVAILABLE"
    ):
        return {
            "status": "UNKNOWN",
            "reason": "insufficient_team_history",
            "home": home_rest,
            "away": away_rest,
        }

    return {
        "status": "AVAILABLE",
        "home": home_rest,
        "away": away_rest,
    }


def _provider_collection_enabled() -> bool:
    explicit = str(
        os.getenv(
            "MATCH_CONTEXT_PROVIDER_ENABLED",
            "",
        )
    ).strip().casefold()

    if explicit in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    if explicit in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    return str(
        os.getenv(
            "ENVIRONMENT",
            "",
        )
    ).strip().casefold() in {
        "production",
        "staging",
    }


def _fixture_id_from_detail(
    detail: dict,
) -> str:
    return str(
        (
            detail.get("fixture") or {}
        ).get("id")
        or detail.get("fixture_id")
        or ""
    )


def _injury_fixture_id(
    row: dict,
) -> str:
    return str(
        (
            row.get("fixture") or {}
        ).get("id")
        or row.get("fixture_id")
        or ""
    )


def enrich_prepared_context(
    fixtures: list[dict],
    picks: list[dict],
    *,
    history=None,
    service=None,
    limit: int = MAX_CONTEXT_FIXTURES,
) -> dict:
    """Attach shadow context to a prepared board.

    Nothing in this function mutates confidence, probability, trust,
    quality_score, market eligibility or bookability.
    """
    fixture_by_id = {
        str(fixture.get("match_id") or ""): fixture
        for fixture in fixtures
        if str(fixture.get("match_id") or "")
    }

    # Rest/fatigue is local historical data, so collect it for every fixture.
    for fixture in fixtures:
        context = empty_match_context(
            "outside_provider_context_shortlist"
        )

        context["rest"] = _rest_summary(
            fixture,
            history,
        )

        fixture["match_context"] = context

    shortlisted = shortlist_context_fixtures(
        fixtures,
        picks,
        limit=limit,
    )

    summary = {
        "version": CONTEXT_VERSION,
        "shadow_only": True,
        "shortlisted_fixture_count": len(
            shortlisted
        ),
        "matched_fixture_count": 0,
        "lineup_available_count": 0,
        "injury_available_count": 0,
        "rest_available_count": sum(
            (
                fixture.get(
                    "match_context"
                ) or {}
            ).get(
                "rest",
                {},
            ).get("status")
            == "AVAILABLE"
            for fixture in fixtures
        ),
        "provider_enabled": False,
    }

    if not shortlisted:
        for pick in picks:
            match_id = str(
                pick.get("match_id") or ""
            )

            if match_id in fixture_by_id:
                pick["match_context"] = (
                    fixture_by_id[match_id].get(
                        "match_context"
                    )
                )

        return summary

    if service is None:
        if not _provider_collection_enabled():
            for pick in picks:
                match_id = str(
                    pick.get("match_id") or ""
                )

                if match_id in fixture_by_id:
                    pick["match_context"] = (
                        fixture_by_id[match_id].get(
                            "match_context"
                        )
                    )

            return summary

        try:
            from services.apifootball_service import (
                API_KEY,
                get_apifootball_service,
            )

            if not API_KEY:
                return summary

            service = get_apifootball_service()

        except Exception as exc:
            logger.warning(
                "Match-context provider unavailable: %s",
                exc,
            )

            return summary

    summary["provider_enabled"] = True

    provider_fixtures = []

    dates = sorted({
        kickoff.date().isoformat()
        for fixture in shortlisted
        if (
            kickoff := _source_kickoff(
                _source_fixture(fixture)
            )
        )
        is not None
    })

    for target_date in dates:
        try:
            provider_fixtures.extend(
                service.get_daily_fixtures(
                    target_date
                )
            )
        except Exception as exc:
            logger.warning(
                "Match-context fixture lookup failed for %s: %s",
                target_date,
                exc,
            )

    matched = {}

    for fixture in shortlisted:
        provider = match_provider_fixture(
            fixture,
            provider_fixtures,
        )

        if not provider:
            continue

        provider_id = str(
            provider.get("fixture_id")
            or ""
        )

        if not provider_id:
            continue

        matched[provider_id] = (
            fixture,
            provider,
        )

    summary["matched_fixture_count"] = len(
        matched
    )

    if matched:
        ids = [
            int(value)
            for value in matched
            if value.isdigit()
        ]

        try:
            details = service.get_fixture_details(
                ids
            )
        except Exception as exc:
            logger.warning(
                "Match-context detail batch failed: %s",
                exc,
            )
            details = []

        details_by_id = {
            _fixture_id_from_detail(detail): detail
            for detail in details
            if _fixture_id_from_detail(detail)
        }

        try:
            injuries_payload = (
                service.get_fixtures_injuries(
                    ids
                )
            )
        except Exception as exc:
            logger.warning(
                "Match-context injury batch failed: %s",
                exc,
            )
            injuries_payload = {
                "response": [],
                "errors": {
                    "request_failed": (
                        type(exc).__name__
                    ),
                },
            }

        injuries_by_fixture = defaultdict(
            list
        )

        for row in (
            injuries_payload.get(
                "response"
            ) or []
        ):
            provider_id = _injury_fixture_id(
                row
            )

            if provider_id:
                injuries_by_fixture[
                    provider_id
                ].append(row)

        injury_errors = (
            injuries_payload.get(
                "errors"
            ) or {}
        )

        for provider_id, (
            fixture,
            provider,
        ) in matched.items():
            context = build_shadow_context(
                provider,
                fixture_details=details_by_id.get(
                    provider_id
                ),
                injuries_payload={
                    "response": (
                        injuries_by_fixture.get(
                            provider_id,
                            [],
                        )
                    ),
                    "errors": injury_errors,
                },
            )

            # Preserve the free local rest calculation from before the
            # provider overlay.
            previous_rest = (
                fixture.get(
                    "match_context"
                ) or {}
            ).get("rest")

            if previous_rest:
                context["rest"] = previous_rest

            fixture["match_context"] = context

            if (
                context.get(
                    "lineups",
                    {},
                ).get("status")
                == "AVAILABLE"
            ):
                summary[
                    "lineup_available_count"
                ] += 1

            if (
                context.get(
                    "injuries",
                    {},
                ).get("status")
                == "AVAILABLE"
            ):
                summary[
                    "injury_available_count"
                ] += 1

    for pick in picks:
        match_id = str(
            pick.get("match_id") or ""
        )

        fixture = fixture_by_id.get(
            match_id
        )

        if fixture:
            pick["match_context"] = (
                fixture.get(
                    "match_context"
                )
            )

    return summary
