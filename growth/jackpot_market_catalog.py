"""Full *mapped* SportyBet football market vocabulary and honest availability.

This is NOT SportyBet's entire fixture-specific bookmaker catalogue. Every
option here has an existing audited SportyBet (market ID, specifier, outcome ID)
mapping. A mapping alone is not a recommendation, price, or approved pick.
"""
from __future__ import annotations

import re

from leagues.market_registry import MARKETS

_MANUAL_ALIASES = {
    "1": "home_win", "home": "home_win", "home win": "home_win",
    "home to win": "home_win", "2": "away_win", "away": "away_win",
    "away win": "away_win", "away to win": "away_win",
    "x": "draw", "draw": "draw", "1x": "home_or_draw",
    "x2": "away_or_draw", "12": "home_or_away",
    "home or away": "home_or_away",
    "home or draw": "home_or_draw", "away or draw": "away_or_draw",
    "double chance 1x": "home_or_draw",
    "double chance x2": "away_or_draw",
    "double chance 12": "home_or_away",
    "dnb home": "dnb_home", "dnb away": "dnb_away",
    "draw no bet home": "dnb_home", "draw no bet away": "dnb_away",
    "btts yes": "btts_yes", "btts no": "btts_no",
    "gg": "btts_yes", "gg yes": "btts_yes",
    "ng": "btts_no", "gg no": "btts_no",
    "both teams to score yes": "btts_yes",
    "both teams to score no": "btts_no",
}
for key in MARKETS:
    _MANUAL_ALIASES[key.replace("_", " ")] = key
    _MANUAL_ALIASES[key] = key

for side in ("home", "away"):
    for line in ("0.5", "1.5"):
        key = f"{side}_over_{line.replace('.', '_')}"
        _MANUAL_ALIASES[f"{side} team over {line}"] = key
        _MANUAL_ALIASES[f"{side} to score over {line}"] = key
        key_under = f"{side}_under_{line.replace('.', '_')}"
        _MANUAL_ALIASES[f"{side} team under {line}"] = key_under

for line in ("0.5", "1.5", "2.5", "3.5", "4.5"):
    ident = line.replace(".", "_")
    _MANUAL_ALIASES[f"total over {line}"] = f"over_{ident}"
    _MANUAL_ALIASES[f"total under {line}"] = f"under_{ident}"
    _MANUAL_ALIASES[f"over {line}"] = f"over_{ident}"
    _MANUAL_ALIASES[f"under {line}"] = f"under_{ident}"
    # Accept common pasted labels while keeping the same audited market IDs.
    # A trailing @price is already stripped in resolve_market; it is never
    # trusted as a SportyBet quote or used for booking.
    _MANUAL_ALIASES[f"over {line} goals"] = f"over_{ident}"
    _MANUAL_ALIASES[f"under {line} goals"] = f"under_{ident}"
    _MANUAL_ALIASES[f"total over {line} goals"] = f"over_{ident}"
    _MANUAL_ALIASES[f"total under {line} goals"] = f"under_{ident}"
    _MANUAL_ALIASES[f"o{line}"] = f"over_{ident}"
    _MANUAL_ALIASES[f"u{line}"] = f"under_{ident}"

_PRICE = re.compile(r"\s*@\s*\d+(?:\.\d+)?\s*$")
_SPACE = re.compile(r"\s+")


def resolve_market(raw_label: str) -> str | None:
    """Resolve only canonical SportyBet-mapped outcomes; never guess synonyms."""
    value = _SPACE.sub(" ", _PRICE.sub("", raw_label.strip()).casefold()).strip()
    return _MANUAL_ALIASES.get(value)


def mapped_market_catalog(candidates: list[dict] | None = None) -> dict:
    """All registered mappings plus exact approval counts for current filters."""
    counts: dict[str, int] = {}
    fixture_sets: dict[str, set[str]] = {}
    for row in candidates or []:
        key = str(row.get("market") or "")
        if key in MARKETS:
            counts[key] = counts.get(key, 0) + 1
            fixture_sets.setdefault(key, set()).add(str(row.get("match_id") or ""))
    data = []
    for key, spec in MARKETS.items():
        if spec.sportybet is None:
            continue
        registered = spec.activation == "ACTIVE"
        approved = len(fixture_sets.get(key) or ())
        under = key.startswith("under_") or "_under_" in key
        data.append({
            "key": key,
            "label": spec.label.replace("{home}", "Home").replace("{away}", "Away"),
            "group": spec.group,
            "activation": spec.activation,
            "market_policy": spec.public_policy,
            "booking_mapped": True,
            "approved_fixture_count": approved,
            "approved_selection_count": counts.get(key, 0),
            "auto_selection_eligible": bool(approved and registered and not under),
            "default_excluded": under,
            "availability_status": (
                "AVAILABLE_AND_APPROVED" if approved and registered and not under else
                "MAPPED_BUT_DEFAULT_EXCLUDED" if under else
                "RESTRICTED_OR_INACTIVE" if not registered else
                "MAPPED_NOT_APPROVED_FOR_CURRENT_FILTERS"
            ),
        })
    return {
        "status": "success",
        "source": "BETSIGHTLY_AUDITED_MARKET_REGISTRY",
        "full_sportybet_catalog": False,
        "market_count": len(data),
        "approved_market_count": sum(1 for row in data if row["auto_selection_eligible"]),
        "markets": data,
        "note": (
            "This shows all audited BetSightly football mappings, not every "
            "market SportyBet offers. A mapping does not imply the event "
            "is priced, the model supports it, or the outcome is bookable. "
            "Unders remain excluded from automatic jackpot tickets."
        ),
    }


def market_catalog_request(payload: dict) -> dict:
    from growth.private_jackpot import candidate_board
    state = candidate_board(payload)
    if state.get("status") != "success":
        return {
            "status": state.get("status") or "unavailable",
            "reason": state.get("reason") or "Approved football candidates unavailable.",
            "market_count": len(MARKETS),
            "full_sportybet_catalog": False,
            "markets": [],
        }
    result = mapped_market_catalog(state.get("candidates") or [])
    return {
        **result,
        "approved_match_count": state.get("distinct_fixture_count"),
        "horizon": payload.get("horizon") or "today",
        "min_trust_grade": payload.get("min_trust_grade") or "B",
    }
