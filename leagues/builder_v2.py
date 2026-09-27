"""Builder V2 orchestration on top of the existing prepared/trusted Builder board.

This module deliberately does not create a second prediction engine. It reuses
the prepared Builder pool, Prompt-1 trust/repricing, canonical market policy,
and SportyBet booking validation while adding four user-facing construction
modes: target odds, game count, strongest, and manual selection.
"""
from __future__ import annotations

import collections
import math
from typing import Any

MAX_GAME_COUNT = 50
V2_HORIZONS = {"today", "3_days", "7_days"}
V2_MODES = {"target_odds", "game_count", "strongest", "manual"}
TRUST_ORDER = {"D": 0, "C": 1, "B": 2, "A": 3}


class BuilderV2BoardUnavailable(RuntimeError):
    def __init__(self, board: dict, refresh_started: bool):
        super().__init__("board_refreshing")
        self.board = dict(board or {})
        self.refresh_started = bool(refresh_started)

    def response(self, mode: str | None = None) -> dict:
        payload = {
            "status": "unavailable",
            "reason": "board_refreshing",
            "retryable": True,
            "refresh_started": self.refresh_started,
            "board": self.board,
        }
        if mode:
            payload["mode"] = mode
        return payload


def _require_prepared_board() -> dict:
    from leagues.engine import prepared_board_status, start_prepared_board_refresh

    state = prepared_board_status(days_ahead=7)
    if not state.get("ready"):
        raise BuilderV2BoardUnavailable(
            state,
            start_prepared_board_refresh(days_ahead=7, force=True),
        )
    if state.get("stale"):
        state = {
            **state,
            "refresh_started": start_prepared_board_refresh(
                days_ahead=7, force=True
            ),
        }
    return state


def _number(value: Any, fallback: float | None = None) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else fallback
    except (TypeError, ValueError):
        return fallback


def _selection_probability(pick: dict) -> float:
    from leagues.selection_quality import selection_probability
    return float(selection_probability(pick))


def _lower_bound(pick: dict) -> float:
    trust = pick.get("trust") or {}
    value = trust.get("lower_reliability_bound")
    if value is None:
        value = pick.get("lower_reliability_bound")
    return float(_number(value, _selection_probability(pick)) or 0.0)


def _trust_grade(pick: dict) -> str:
    return str((pick.get("trust") or {}).get("trust_grade") or "D").upper()


def _market_capability(pick: dict) -> str:
    from leagues.fixture_ranker import (
        DEVELOPING_MARKETS,
        DISABLED_PUBLIC_MARKETS,
        RESTRICTED_MARKETS,
        TRUSTED_MARKETS,
        EVIDENCE_ELIGIBLE_WINS,
    )
    market = str(pick.get("market") or "")
    explicit = str(pick.get("market_trust_state") or "").upper()
    if market in DISABLED_PUBLIC_MARKETS:
        return "DISABLED"
    if market in RESTRICTED_MARKETS:
        return "RESTRICTED"
    if explicit in {"TRUSTED", "DEVELOPING", "PROVISIONAL", "RESTRICTED", "DISABLED"}:
        return explicit
    if market in DEVELOPING_MARKETS:
        return "DEVELOPING"
    if market in TRUSTED_MARKETS or market in EVIDENCE_ELIGIBLE_WINS:
        return "TRUSTED"
    return "PROVISIONAL"


def _rank_key(pick: dict) -> tuple:
    trust = pick.get("trust") or {}
    return (
        -_lower_bound(pick),
        -_selection_probability(pick),
        -float(_number(trust.get("trust_score"), 0.0) or 0.0),
        -float(_number(pick.get("quality_score"), 0.0) or 0.0),
        -float(_number(pick.get("risk_adjusted_return"), 0.0) or 0.0),
        str(pick.get("match_id") or ""),
        str(pick.get("market") or ""),
    )


def _fixture_teams(pick: dict) -> set[str]:
    fixture = pick.get("_fixture") or {}
    values: set[str] = set()
    for side in ("home", "away"):
        team = fixture.get(side) or {}
        for value in (team.get("id"), team.get("name")):
            if value is not None and str(value).strip():
                values.add(str(value).strip().casefold())
    return values


def _league_keys(pick: dict) -> set[str]:
    fixture = pick.get("_fixture") or {}
    return {
        str(value).strip().casefold()
        for value in (fixture.get("league"), fixture.get("league_slug"), pick.get("league"))
        if value is not None and str(value).strip()
    }


def _normalised_set(values: list[str] | None) -> set[str]:
    return {str(value).strip().casefold() for value in (values or []) if str(value).strip()}


def _validate_filters(options: dict) -> str | None:
    horizon = str(options.get("horizon") or "7_days")
    if horizon not in V2_HORIZONS:
        return f"Horizon must be one of {sorted(V2_HORIZONS)}."
    grade = str(options.get("min_trust_grade") or "B").upper()
    if grade not in TRUST_ORDER:
        return "min_trust_grade must be A, B, C, or D."
    min_odds = _number(options.get("min_odds"))
    max_odds = _number(options.get("max_odds"))
    if min_odds is not None and min_odds <= 1:
        return "min_odds must be greater than 1."
    if max_odds is not None and max_odds <= 1:
        return "max_odds must be greater than 1."
    if min_odds is not None and max_odds is not None and min_odds > max_odds:
        return "min_odds cannot exceed max_odds."
    return None


def _raw_filter(pool: list[dict], options: dict) -> list[dict]:
    markets = {str(value) for value in (options.get("markets") or []) if str(value)}
    include_leagues = _normalised_set(options.get("include_leagues"))
    exclude_leagues = _normalised_set(options.get("exclude_leagues"))
    excluded_fixtures = {str(value) for value in (options.get("exclude_fixture_ids") or [])}
    excluded_teams = _normalised_set(options.get("exclude_team_ids"))
    min_odds = _number(options.get("min_odds"))
    max_odds = _number(options.get("max_odds"))

    out = []
    for pick in pool:
        if markets and str(pick.get("market")) not in markets:
            continue
        if str(pick.get("match_id")) in excluded_fixtures:
            continue
        leagues = _league_keys(pick)
        if include_leagues and not (leagues & include_leagues):
            continue
        if exclude_leagues and leagues & exclude_leagues:
            continue
        if excluded_teams and _fixture_teams(pick) & excluded_teams:
            continue
        odds = _number(pick.get("odds"), 0.0) or 0.0
        if min_odds is not None and odds < min_odds:
            continue
        if max_odds is not None and odds > max_odds:
            continue
        out.append(pick)
    return out


def _candidate_pool(
    options: dict, *, refresh_sportybet: bool = False,
    include_all_eligible: bool = False,
) -> tuple[dict, list[dict], dict]:
    from leagues.picks import MIN_PUBLISHABLE_CONFIDENCE
    from leagues.slip_builder import approved_builder_candidates, prepared_bookable_pool

    error = _validate_filters(options)
    if error:
        raise ValueError(error)

    prepared_state = _require_prepared_board()
    horizon = str(options.get("horizon") or "7_days")
    board, raw, timings = prepared_bookable_pool(
        horizon,
        force=False,
        refresh_sportybet=refresh_sportybet,
    )
    filtered_raw = _raw_filter(raw, options)
    approved, trust_rejections = approved_builder_candidates(
        filtered_raw,
        require_bookable=True,
        include_all_eligible=include_all_eligible,
    )

    requested_floor = _number(options.get("min_probability"), 0.0) or 0.0
    effective_floor = max(float(MIN_PUBLISHABLE_CONFIDENCE), requested_floor)
    minimum_grade = str(options.get("min_trust_grade") or "B").upper()

    final = []
    for pick in approved:
        capability = _market_capability(pick)
        if capability in {"DISABLED", "RESTRICTED"}:
            continue
        probability = _selection_probability(pick)
        if probability < effective_floor:
            continue
        if TRUST_ORDER.get(_trust_grade(pick), 0) < TRUST_ORDER[minimum_grade]:
            continue
        if not pick.get("bookable"):
            continue
        item = dict(pick)
        item["selection_probability"] = probability
        item["market_capability"] = capability
        final.append(item)

    final.sort(key=_rank_key)
    diagnostics = {
        "prepared_bookable_count": len(raw),
        "after_user_raw_filters": len(filtered_raw),
        "after_trust_and_policy": len(approved),
        "approved_count": len(final),
        "effective_min_probability": effective_floor,
        "trust_rejection_reasons": dict(trust_rejections),
        "timing_ms": timings,
        "require_bookable_effective": True,
        "prepared_board_snapshot_id": prepared_state.get("board_snapshot_id"),
        "prepared_board_stale": bool(prepared_state.get("stale")),
    }
    return board, final, diagnostics


def _board_context(board: dict) -> dict:
    out: dict[str, Any] = {}
    try:
        from leagues import sportybet
        meta = sportybet.board_metadata(board)
        out["sportybet_snapshot_id"] = meta.get("snapshot_id")
        out["sportybet_complete"] = bool(meta.get("is_complete"))
        out["sportybet_generated_at"] = meta.get("generated_at")
    except Exception:
        pass
    try:
        from leagues.engine import prepared_board_status
        prepared = prepared_board_status(days_ahead=7)
        out.update({
            "board_snapshot_id": prepared.get("board_snapshot_id"),
            "board_generated_at": prepared.get("generated_at"),
            "board_age_seconds": prepared.get("age_seconds"),
            "board_degraded": bool(prepared.get("degraded")),
            "board_complete": bool(prepared.get("complete")),
        })
    except Exception:
        pass
    return out


def _public_candidate(pick: dict, *, recommended: bool, board_context: dict) -> dict:
    from leagues.picks import to_game
    game = to_game(pick)
    # Selection IDs are sufficient for manual resolution. Keep raw SportyBet
    # mapping internals server-side.
    game.pop("sportybet_availability", None)
    game.pop("sportybet_event_id", None)
    game["market_capability"] = pick.get("market_capability") or _market_capability(pick)
    game["recommended_for_fixture"] = bool(recommended)
    game["selection_probability"] = _selection_probability(pick)
    game["lower_reliability_bound"] = _lower_bound(pick)
    game["trust_grade"] = _trust_grade(pick)
    game["trust_score"] = (pick.get("trust") or {}).get("trust_score")
    game["selection_reason_codes"] = list(pick.get("selection_reason_codes") or [])
    game.update({key: value for key, value in board_context.items() if key not in game})
    return game


def list_candidates(options: dict) -> dict:
    try:
        board, pool, diagnostics = _candidate_pool(
            options, include_all_eligible=True
        )
    except BuilderV2BoardUnavailable as exc:
        return {**exc.response("manual"), "candidates": []}
    except ValueError as exc:
        return {"status": "error", "reason": str(exc), "candidates": []}

    recommended: set[str] = set()
    seen_fixtures: set[str] = set()
    for pick in pool:
        fixture_id = str(pick.get("match_id") or "")
        if fixture_id and fixture_id not in seen_fixtures:
            recommended.add(str(pick.get("selection_id") or ""))
            seen_fixtures.add(fixture_id)

    context = _board_context(board)
    return {
        "status": "success",
        "mode": "manual",
        "origin": "USER_MANUAL",
        "horizon": str(options.get("horizon") or "7_days"),
        "markets_requested": list(options.get("markets") or []),
        "candidate_count": len(pool),
        "candidates": [
            _public_candidate(
                pick,
                recommended=str(pick.get("selection_id") or "") in recommended,
                board_context=context,
            )
            for pick in pool
        ],
        "selection_diagnostics": diagnostics,
        "board": context,
    }


def _select_unique(pool: list[dict], limit: int) -> list[dict]:
    selected = []
    seen_fixtures: set[str] = set()
    seen_teams: set[str] = set()
    for pick in sorted(pool, key=_rank_key):
        fixture_id = str(pick.get("match_id") or "")
        teams = _fixture_teams(pick)
        if fixture_id in seen_fixtures:
            continue
        # Match existing target-Builder diversification: a seven-day ticket
        # should not depend on the same club twice when alternatives exist.
        if teams and teams & seen_teams:
            continue
        selected.append(pick)
        seen_fixtures.add(fixture_id)
        seen_teams.update(teams)
        if len(selected) >= limit:
            break
    return selected


def _booking_is_exact(booking: dict) -> bool:
    return bool(
        booking.get("status") == "active"
        and booking.get("booking_status") in {"FULL", "REBUILT_FULL"}
        and str(booking.get("readback_validation") or "").upper() == "PASSED"
        and booking.get("share_code")
    )


def _booking_for(picks: list[dict], board: dict, odds: float) -> tuple[list[dict], dict]:
    from leagues.booking import create_booking
    from leagues.picks import to_game
    games = [to_game(pick) for pick in picks]
    booking = create_booking(
        games,
        board,
        booking_status="FULL",
        original_games=games,
        predicted_odds=odds,
    )
    if not _booking_is_exact(booking):
        booking = {
            **booking,
            "share_code": None,
            "share_url": None,
            "actionable": False,
        }
    return games, booking


def _selected_response(mode: str, options: dict, picks: list[dict], board: dict,
                       diagnostics: dict, requested_count: int | None = None) -> dict:
    if not picks:
        return {
            "status": "unavailable",
            "mode": mode,
            "origin": "BETSIGHTLY_AUTO",
            "horizon": str(options.get("horizon") or "7_days"),
            "requested_game_count": requested_count,
            "delivered_game_count": 0,
            "shortfall": requested_count or 0,
            "reason": "No selections satisfy the current quality, filter and SportyBet bookability gates.",
            "selection_diagnostics": diagnostics,
            "board": _board_context(board),
        }

    probabilities = [_selection_probability(pick) for pick in picks]
    odds = math.prod(float(pick.get("odds") or 1.0) for pick in picks)
    estimated_probability = math.prod(probabilities)
    expected_return = math.prod(
        max(0.0, float(_number(pick.get("risk_adjusted_return"), 0.0) or 0.0))
        for pick in picks
    )
    games, booking = _booking_for(picks, board, odds)
    market_distribution = dict(collections.Counter(str(pick.get("market") or "unknown") for pick in picks))
    grades = [_trust_grade(pick) for pick in picks]
    lowest_grade = min(grades, key=lambda value: TRUST_ORDER.get(value, -1)) if grades else None
    delivered = len(picks)
    shortfall = max(0, int(requested_count or delivered) - delivered) if requested_count is not None else 0
    context = _board_context(board)
    return {
        "status": "success",
        "mode": mode,
        "origin": "BETSIGHTLY_AUTO",
        "editing_supported": False,
        "horizon": str(options.get("horizon") or "7_days"),
        "requested_game_count": requested_count,
        "delivered_game_count": delivered,
        "shortfall": shortfall,
        "shortfall_reason": (
            f"Only {delivered} selections satisfied the current quality, filter and SportyBet bookability gates."
            if shortfall else None
        ),
        "odds": round(odds, 4),
        "achieved_odds": round(odds, 4),
        "legs": delivered,
        "games": games,
        "markets_requested": list(options.get("markets") or []),
        "markets_used": sorted(market_distribution),
        "market_distribution": market_distribution,
        "average_probability": round(sum(probabilities) / delivered, 6),
        "lowest_probability": round(min(probabilities), 6),
        "estimated_all_leg_probability": round(estimated_probability, 8),
        "probability_assumption": "approximate_independence",
        "estimated_expected_return": round(expected_return, 6),
        "lowest_trust_grade": lowest_grade,
        "booking": booking,
        "booking_status": booking.get("booking_status") or booking.get("status"),
        "readback_status": booking.get("readback_validation"),
        "selection_diagnostics": diagnostics,
        "board": context,
    }


def generate_v2(options: dict) -> dict:
    mode = str(options.get("mode") or "")
    if mode not in {"target_odds", "game_count", "strongest"}:
        return {"status": "error", "reason": "mode must be target_odds, game_count, or strongest."}

    try:
        board, pool, diagnostics = _candidate_pool(options)
    except BuilderV2BoardUnavailable as exc:
        return exc.response(mode)
    except ValueError as exc:
        return {"status": "error", "mode": mode, "reason": str(exc)}

    if mode == "target_odds":
        from leagues.slip_builder import (
            MAX_LEGS,
            MAX_TARGET,
            MIN_TARGET,
            _public_result_from_build,
            build_slip,
        )
        target = _number(options.get("target_odds"))
        if target is None or not (MIN_TARGET <= target <= MAX_TARGET):
            return {
                "status": "error",
                "mode": mode,
                "reason": f"Choose a target between {MIN_TARGET:g} and {MAX_TARGET:g}.",
            }
        built = build_slip(
            target,
            pool=pool,
            max_legs=MAX_LEGS,
            horizon=str(options.get("horizon") or "7_days"),
            require_bookable=True,
            preapproved_pool=True,
        )
        out = _public_result_from_build(
            target,
            str(options.get("horizon") or "7_days"),
            built,
            board,
        )
        out.update({
            "mode": mode,
            "origin": "BETSIGHTLY_AUTO",
            "editing_supported": True,
            "requested_target": target,
            "markets_requested": list(options.get("markets") or []),
            "probability_assumption": "approximate_independence",
            "selection_diagnostics_v2": diagnostics,
        })
        return out

    if mode == "game_count":
        requested = int(options.get("game_count") or 0)
        if not (1 <= requested <= MAX_GAME_COUNT):
            return {
                "status": "error",
                "mode": mode,
                "reason": f"game_count must be between 1 and {MAX_GAME_COUNT}.",
            }
        selected = _select_unique(pool, requested)
        return _selected_response(mode, options, selected, board, diagnostics, requested)

    max_games = int(options.get("max_games") or 10)
    if not (1 <= max_games <= MAX_GAME_COUNT):
        return {
            "status": "error",
            "mode": mode,
            "reason": f"max_games must be between 1 and {MAX_GAME_COUNT}.",
        }
    selected = _select_unique(pool, max_games)
    return _selected_response(mode, options, selected, board, diagnostics)


def manual_build(options: dict) -> dict:
    selection_ids = [str(value) for value in (options.get("selection_ids") or [])]
    if not selection_ids:
        return {"status": "error", "mode": "manual", "reason": "Choose at least one selection."}
    if len(selection_ids) > MAX_GAME_COUNT:
        return {
            "status": "error",
            "mode": "manual",
            "reason": f"Manual slips support at most {MAX_GAME_COUNT} selections.",
        }
    if len(set(selection_ids)) != len(selection_ids):
        return {
            "status": "SELECTIONS_CHANGED",
            "mode": "manual",
            "origin": "USER_MANUAL",
            "reason": "The same selection was included more than once.",
            "invalid_selections": [{"reason": "DUPLICATE_SELECTION"}],
        }

    try:
        board, pool, diagnostics = _candidate_pool(
            options,
            refresh_sportybet=True,
            include_all_eligible=True,
        )
    except BuilderV2BoardUnavailable as exc:
        return exc.response("manual")
    except ValueError as exc:
        return {"status": "error", "mode": "manual", "reason": str(exc)}

    by_id = {str(pick.get("selection_id") or ""): pick for pick in pool}
    missing = [selection for selection in selection_ids if selection not in by_id]
    if missing:
        return {
            "status": "SELECTIONS_CHANGED",
            "mode": "manual",
            "origin": "USER_MANUAL",
            "valid_count": len(selection_ids) - len(missing),
            "invalid_selections": [
                {
                    "selection_id": selection,
                    "reason": "STALE_OR_UNAVAILABLE_SELECTION",
                    "actions": ["REMOVE", "REPLACE", "SAFER_MARKET"],
                }
                for selection in missing
            ],
            "reason": "One or more selections are no longer approved and exactly bookable.",
            "selection_diagnostics": diagnostics,
        }

    picks = [by_id[selection] for selection in selection_ids]
    seen_fixtures: set[str] = set()
    duplicate_fixtures = []
    for pick in picks:
        fixture_id = str(pick.get("match_id") or "")
        if fixture_id in seen_fixtures:
            duplicate_fixtures.append(fixture_id)
        seen_fixtures.add(fixture_id)
    if duplicate_fixtures:
        return {
            "status": "SELECTIONS_CHANGED",
            "mode": "manual",
            "origin": "USER_MANUAL",
            "valid_count": len(picks),
            "invalid_selections": [
                {"fixture_id": fixture_id, "reason": "DUPLICATE_FIXTURE", "actions": ["REMOVE"]}
                for fixture_id in sorted(set(duplicate_fixtures))
            ],
            "reason": "Only one selection per fixture may be booked.",
        }

    probabilities = [_selection_probability(pick) for pick in picks]
    odds = math.prod(float(pick.get("odds") or 1.0) for pick in picks)
    games, booking = _booking_for(picks, board, odds)
    if not _booking_is_exact(booking):
        failure = str(booking.get("failure_category") or booking.get("reason") or "BOOKING_UNAVAILABLE")
        selection_change_failures = {
            "FIXTURE_STARTED", "KICKOFF_BUFFER", "FIXTURE_MAPPING_FAILED",
            "KICKOFF_MISMATCH", "MARKET_NOT_FOUND", "SELECTION_NOT_FOUND",
            "OUTCOME_SUSPENDED", "ODDS_UNAVAILABLE", "READBACK_MISMATCH",
        }
        status = "SELECTIONS_CHANGED" if failure in selection_change_failures else "BOOKING_UNAVAILABLE"
        return {
            "status": status,
            "mode": "manual",
            "origin": "USER_MANUAL",
            "valid_count": len(picks),
            "reason": booking.get("reason") or "The current SportyBet slip could not be validated exactly.",
            "booking": booking,
            "actions": ["REMOVE", "REPLACE", "SAFER_MARKET"] if status == "SELECTIONS_CHANGED" else [],
            "selection_diagnostics": diagnostics,
        }

    distribution = dict(collections.Counter(str(pick.get("market") or "unknown") for pick in picks))
    grades = [_trust_grade(pick) for pick in picks]
    return {
        "status": "success",
        "mode": "manual",
        "origin": "USER_MANUAL",
        "editing_supported": False,
        "horizon": str(options.get("horizon") or "7_days"),
        "games": games,
        "legs": len(games),
        "odds": round(odds, 4),
        "achieved_odds": round(odds, 4),
        "estimated_all_leg_probability": round(math.prod(probabilities), 8),
        "probability_assumption": "approximate_independence",
        "average_probability": round(sum(probabilities) / len(probabilities), 6),
        "lowest_probability": round(min(probabilities), 6),
        "lowest_trust_grade": min(grades, key=lambda value: TRUST_ORDER.get(value, -1)),
        "markets_used": sorted(distribution),
        "market_distribution": distribution,
        "booking": booking,
        "booking_status": booking.get("booking_status") or booking.get("status"),
        "readback_status": booking.get("readback_validation"),
        "selection_diagnostics": diagnostics,
        "board": _board_context(board),
    }
