"""Compact SportyBet-first shadow inventory.

This module does not fetch providers, publish predictions, create booking codes,
or alter the production prepared board. It only normalizes an already cached
SportyBet board into a small provider-first diagnostic snapshot.
"""
from __future__ import annotations

from datetime import datetime, timezone

from leagues import sportybet

SHADOW_SOURCE = "SPORTYBET_FIRST_SHADOW_BOARD"


def _iso_kickoff(kickoff_ms) -> str | None:
    try:
        if kickoff_ms in (None, ""):
            return None
        return datetime.fromtimestamp(
            float(kickoff_ms) / 1000.0,
            tz=timezone.utc,
        ).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _compact_selection(entry: dict, market: str) -> dict | None:
    mapping = sportybet.MARKET_TO_SPORTYBET.get(market)
    if not mapping:
        return None

    market_id, specifier, outcome_id = mapping
    market_ref = (
        (entry.get("market_refs") or {})
        .get(f"{market_id}|{specifier}", {})
    )
    outcome = (
        (market_ref.get("outcomes") or {})
        .get(outcome_id)
    ) or {}

    try:
        odds = float((entry.get("prices") or {}).get(market))
    except (TypeError, ValueError):
        return None

    if odds <= 1.0 or outcome.get("active") is False:
        return None

    return {
        "market": market,
        "odds": round(odds, 3),
        "market_id": market_id,
        "specifier": specifier,
        "outcome_id": outcome_id,
        "active": True,
        "margin": (entry.get("margins") or {}).get(market),
    }


def normalize_board(board: dict | None) -> dict:
    """Normalize one SportyBet board without retaining duplicate raw payloads."""
    board = board or {"__meta__": {}}
    meta = sportybet.board_metadata(board)

    fixtures = []
    selection_count = 0
    competitions: set[str] = set()

    for _, entry in sportybet._board_entries(board):
        event_id = str(entry.get("event_id") or "").strip()
        home = str(entry.get("home_team") or "").strip()
        away = str(entry.get("away_team") or "").strip()
        if not event_id or not home or not away:
            continue

        selections = []
        for market in sorted((entry.get("prices") or {}).keys()):
            selection = _compact_selection(entry, market)
            if selection:
                selections.append(selection)

        competition = str(entry.get("competition") or "").strip() or None
        if competition:
            competitions.add(competition)

        fixtures.append({
            "sportybet_event_id": event_id,
            "provider": "sportybet",
            "competition": competition,
            "home_team": home,
            "away_team": away,
            "home_squad": entry.get("home_squad") or "",
            "away_squad": entry.get("away_squad") or "",
            "kickoff": _iso_kickoff(entry.get("kickoff_ms")),
            "kickoff_ms": entry.get("kickoff_ms"),
            "supported_markets": [item["market"] for item in selections],
            "selections": selections,
        })
        selection_count += len(selections)

    fixtures.sort(
        key=lambda item: (
            item.get("kickoff") or "",
            item.get("sportybet_event_id") or "",
        )
    )

    generated_at = None
    if meta.get("fetched_at"):
        try:
            generated_at = datetime.fromtimestamp(
                float(meta["fetched_at"]),
                tz=timezone.utc,
            ).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            generated_at = None

    return {
        "status": "success" if fixtures else "unavailable",
        "source": SHADOW_SOURCE,
        "provider": "sportybet",
        "shadow_only": True,
        "can_publish": False,
        "can_book": False,
        "authoritative_for_user_output": False,
        "snapshot_id": meta.get("snapshot_id"),
        "generated_at": generated_at,
        "complete": bool(meta.get("is_complete")),
        "provider_error": meta.get("error"),
        "declared_total": int(meta.get("declared_total") or 0),
        "page_count": int(meta.get("page_count") or 0),
        "required_pages": int(meta.get("required_pages") or 0),
        "fixture_count": len(fixtures),
        "selection_count": selection_count,
        "competition_count": len(competitions),
        "fixtures": fixtures,
    }


def cached_shadow_inventory() -> dict:
    """Return only the existing cached SportyBet snapshot; never hit the network."""
    cached = sportybet._db_get(sportybet._CACHE_KEY)
    if not cached or not cached.get("fixtures"):
        return {
            "status": "unavailable",
            "reason": "sportybet_cache_empty",
            "source": SHADOW_SOURCE,
            "provider": "sportybet",
            "shadow_only": True,
            "can_publish": False,
            "can_book": False,
            "authoritative_for_user_output": False,
            "refresh_required": True,
            "snapshot_id": None,
            "complete": False,
            "fixture_count": 0,
            "selection_count": 0,
            "competition_count": 0,
            "fixtures": [],
        }

    board = sportybet._snapshot(
        cached.get("fixtures") or {},
        cached.get("metadata") or {},
    )
    result = normalize_board(board)
    result["refresh_required"] = not bool(result.get("complete"))
    return result


def status() -> dict:
    """Small read-only summary suitable for an admin diagnostic endpoint."""
    inventory = cached_shadow_inventory()
    keys = (
        "status",
        "reason",
        "source",
        "provider",
        "shadow_only",
        "can_publish",
        "can_book",
        "authoritative_for_user_output",
        "refresh_required",
        "snapshot_id",
        "generated_at",
        "complete",
        "provider_error",
        "declared_total",
        "page_count",
        "required_pages",
        "fixture_count",
        "selection_count",
        "competition_count",
    )
    return {key: inventory.get(key) for key in keys if key in inventory}
