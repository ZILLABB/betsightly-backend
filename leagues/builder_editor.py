"""Intent-only editing of a Builder slip against the prepared approved board."""
from __future__ import annotations

import time
from typing import Any

from leagues import builder_revisions
from leagues.slip_builder import (
    MAX_TARGET, MIN_TARGET, _leg_settlement_probabilities,
    _public_result_from_build, _selection_id, approved_builder_candidates,
    build_slip, prepared_bookable_pool,
)

ACTIONS = {
    "replace_selection", "safer_same_fixture", "exclude_fixture",
    "remove_selection", "lock_selection", "unlock_selection",
    "accept_best_reachable",
}
BOOKABILITY_FAILURES = {
    "FIXTURE_STARTED", "KICKOFF_BUFFER", "FIXTURE_MAPPING_FAILED",
    "KICKOFF_MISMATCH", "MARKET_NOT_FOUND", "SELECTION_NOT_FOUND",
    "OUTCOME_SUSPENDED", "ODDS_UNAVAILABLE", "READBACK_MISMATCH",
}
MAX_BOOKABILITY_RETRIES = 2


def _selected_game(result: dict, selection_id: str | None,
                   fixture_id: str | None) -> dict | None:
    games = result.get("games") or []
    for game in games:
        if selection_id and str(game.get("selection_id")) == selection_id:
            return game
        if fixture_id and fixture_id in {
            str(game.get("match_id")), str(game.get("fixture_id")),
        }:
            return game
    return None


def _survival(pick: dict) -> float:
    settlement = _leg_settlement_probabilities(pick)
    return (settlement[0] + settlement[1]) if settlement else 0.0


def _safer_candidate(current: dict, candidates: list[dict]) -> dict | None:
    current_id = str(current.get("selection_id") or "")
    current_pick = next(
        (pick for pick in candidates if _selection_id(pick) == current_id), None
    )
    if current_pick is None:
        return None
    current_survival = _survival(current_pick)
    trust = current_pick.get("trust") or {}
    lower = float(trust.get("lower_reliability_bound") or current_survival)
    # "Materially safer" scales with measured uncertainty. Two points is the
    # floor; half the current reliability interval is required on noisier legs.
    required_gain = max(.02, min(.08, (current_survival - lower) / 2))
    same_fixture = [
        pick for pick in candidates
        if str(pick.get("match_id")) == str(current_pick.get("match_id"))
        and _selection_id(pick) != current_id
        and _survival(pick) >= current_survival + required_gain
    ]
    if not same_fixture:
        return None
    return max(
        same_fixture,
        key=lambda pick: (_survival(pick), float(pick.get("quality_score") or 0)),
    )


def _change_summary(before: dict, after: dict, action: str) -> dict:
    old = {str(game.get("selection_id")): game
           for game in before.get("games") or []}
    new = {str(game.get("selection_id")): game
           for game in after.get("games") or []}
    removed = [game for key, game in old.items() if key not in new]
    added = [game for key, game in new.items() if key not in old]
    removed_fixture = str((removed[0] if removed else {}).get("match_id") or "")
    added_fixture = str((added[0] if added else {}).get("match_id") or "")
    return {
        "action": action,
        "removed": removed,
        "added": added,
        "old_odds": before.get("odds") or before.get("achieved_odds"),
        "new_odds": after.get("odds") or after.get("achieved_odds")
        or after.get("best_reachable"),
        "old_leg_count": len(before.get("games") or []),
        "new_leg_count": len(after.get("games") or []),
        "removed_fixture_id": removed_fixture or None,
        "added_fixture_id": added_fixture or None,
        "fixture_changed": bool(removed_fixture and added_fixture
                                and removed_fixture != added_fixture),
        "reason": (
            "The revised slip was rebuilt from the same approved conservative "
            "candidate board while preserving your locks and exclusions."
        ),
    }


def _no_replacement(before: dict, edit_token: str, timings: dict) -> dict:
    return {
        **before,
        "revision_status": "no_change",
        "action_error": (
            "No different BetSightly-approved, currently bookable fixture can "
            "replace this game without weakening the slip. Your original "
            "game has been kept."
        ),
        "timing_ms": timings,
    }


def _replace_fixture_locally(
    *, before: dict, current: dict, candidates: list[dict], target: float,
    horizon: str, board: dict, locked: set[str],
    excluded_fixtures: set[str], excluded_selections: set[str],
    timings: dict,
) -> tuple[dict | None, str | None]:
    """Return one exact N-for-N fixture swap, without rerolling other legs."""
    current_fixture = str(current.get("match_id") or current.get("fixture_id") or "")
    current_id = str(current.get("selection_id") or "")
    existing_games = list(before.get("games") or [])
    existing_ids = {str(game.get("selection_id") or "") for game in existing_games}
    existing_fixtures = {str(game.get("match_id") or game.get("fixture_id") or "")
                         for game in existing_games}
    by_id = {_selection_id(pick): pick for pick in candidates}
    unaffected = [game for game in existing_games
                  if str(game.get("selection_id") or "") != current_id]
    preserved = [by_id.get(str(game.get("selection_id") or "")) for game in unaffected]
    if any(pick is None for pick in preserved):
        return None, None

    alternatives = [
        pick for pick in candidates
        if str(pick.get("match_id")) != current_fixture
        and str(pick.get("match_id")) not in excluded_fixtures
        and str(pick.get("match_id")) not in existing_fixtures
        and _selection_id(pick) not in excluded_selections
        and _selection_id(pick) not in existing_ids
    ]
    alternatives.sort(key=lambda pick: (
        -_survival(pick), -float(pick.get("quality_score") or 0),
        abs(float(pick.get("odds") or 1) - float(current.get("odds") or 1)),
    ))
    search_started = time.perf_counter()
    viable: list[tuple[tuple, dict, dict]] = []
    for replacement in alternatives[:96]:
        fixed = [*preserved, replacement]
        required = {_selection_id(pick) for pick in fixed}
        built = build_slip(
            target, pool=fixed, max_legs=len(existing_games), horizon=horizon,
            require_bookable=True, locked_selection_ids=locked,
            excluded_fixture_ids=excluded_fixtures | {current_fixture},
            excluded_selection_ids=excluded_selections | {current_id},
            forced_selection_ids=required,
        )
        if not built.get("ok") or len(built.get("picks") or []) != len(existing_games):
            continue
        score = (
            float(built.get("hit_probability") or 0),
            float(built.get("expected_return") or 0),
            -abs(float(built.get("odds") or 0) - target),
            float(replacement.get("quality_score") or 0),
        )
        viable.append((score, built, replacement))
    timings["replacement_search"] = round(
        (time.perf_counter() - search_started) * 1000
    )
    if not viable:
        return None, None
    _, built, replacement = max(viable, key=lambda item: item[0])
    result = _public_result_from_build(
        target, horizon, built, board, timings, force_booking=True
    )
    booking = result.get("booking") or {}
    if not (result.get("status") == "success"
            and booking.get("status") == "active"
            and booking.get("share_code")
            and str(booking.get("readback_validation") or "").upper() == "PASSED"):
        return None, None
    # Preserve the user's visual leg order: only the requested slot changes.
    games_by_id = {str(game.get("selection_id")): game
                   for game in result.get("games") or []}
    replacement_id = _selection_id(replacement)
    result["games"] = [
        games_by_id.get(replacement_id) if str(game.get("selection_id")) == current_id
        else games_by_id.get(str(game.get("selection_id")), game)
        for game in existing_games
    ]
    return result, replacement_id


def revise(
    *, run_id: str, edit_token: str, revision: int, request_id: str,
    action: str, selection_id: str | None = None,
    fixture_id: str | None = None, target: float | None = None,
) -> dict:
    """Apply one revision atomically; client-supplied model facts are ignored."""
    if action not in ACTIONS:
        raise ValueError("unsupported_builder_action")
    replay = builder_revisions.idempotent_result(run_id, edit_token, request_id)
    if replay is not None:
        return replay
    state = builder_revisions.load_state(run_id, edit_token)
    if revision != state["latest_revision"]:
        raise builder_revisions.StaleBuilderRevision(state["latest_revision"])

    before = state["result"]
    current = _selected_game(before, selection_id, fixture_id)
    if action != "accept_best_reachable" and current is None:
        raise ValueError("selection_not_in_current_revision")

    locked = set(state["locked_selection_ids"])
    excluded_fixtures = set(state["excluded_fixture_ids"])
    excluded_selections = set(state["excluded_selection_ids"])
    forced: set[str] = set()
    action_target: dict[str, Any] = {
        "selection_id": selection_id, "fixture_id": fixture_id,
    }

    current_id = str((current or {}).get("selection_id") or selection_id or "")
    current_fixture = str((current or {}).get("match_id") or fixture_id or "")
    if action == "lock_selection":
        locked.add(current_id)
    elif action == "unlock_selection":
        locked.discard(current_id)
    elif action == "exclude_fixture":
        excluded_fixtures.add(current_fixture)
        locked = {value for value in locked if value != current_id}
    elif action == "remove_selection":
        excluded_selections.add(current_id)
        locked.discard(current_id)

    effective_target = float(before.get("target") or state["requested_target"])
    if action == "accept_best_reachable":
        requested = float(target or 0)
        best = float(before.get("best_reachable") or 0)
        if not (MIN_TARGET <= requested <= min(MAX_TARGET, best + .01)):
            raise ValueError("invalid_best_reachable_target")
        effective_target = requested

    started = time.perf_counter()
    board, bookable_pool, timings = prepared_bookable_pool(
        state["horizon"], force=False
    )
    timings["revision_board_lookup"] = round((time.perf_counter() - started) * 1000)
    from leagues.engine import prepared_board_status
    prepared_status = prepared_board_status(days_ahead=7)
    board_state = {
        "ready": bool(prepared_status.get("ready")),
        "degraded": bool(prepared_status.get("degraded")),
        "complete": bool(prepared_status.get("complete")),
    }

    if action == "replace_selection":
        canonical, _ = approved_builder_candidates(bookable_pool)
        result, replacement_id = _replace_fixture_locally(
            before=before, current=current or {}, candidates=canonical,
            target=effective_target, horizon=state["horizon"], board=board,
            locked=locked, excluded_fixtures=excluded_fixtures,
            excluded_selections=excluded_selections, timings=timings,
        )
        if result is None:
            unchanged = _no_replacement(before, edit_token, timings)
            unchanged["board"] = board_state
            return builder_revisions.persist_revision(
                run_id=run_id, edit_token=edit_token,
                expected_revision=revision, request_id=request_id,
                action=action, action_target=action_target,
                result=unchanged, locked_selection_ids=locked,
                excluded_fixture_ids=excluded_fixtures,
                excluded_selection_ids=excluded_selections,
            )
        excluded_fixtures.add(current_fixture)
        excluded_selections.add(current_id)
        locked.discard(current_id)
        action_target["replacement_selection_id"] = replacement_id
        action_target["replaced_fixture_id"] = current_fixture
        action_target["replacement_fixture_id"] = next(
            (str(game.get("match_id")) for game in result.get("games") or []
             if str(game.get("selection_id")) == replacement_id), None)
        result["timing_ms"] = timings
        result["change_summary"] = _change_summary(before, result, action)
        result["board"] = board_state
        return builder_revisions.persist_revision(
            run_id=run_id, edit_token=edit_token,
            expected_revision=revision, request_id=request_id, action=action,
            action_target=action_target, result=result,
            locked_selection_ids=locked,
            excluded_fixture_ids=excluded_fixtures,
            excluded_selection_ids=excluded_selections,
        )

    if action in {"lock_selection", "unlock_selection"}:
        if action == "lock_selection":
            canonical, _ = approved_builder_candidates(bookable_pool)
            if current_id not in {_selection_id(pick) for pick in canonical}:
                return {
                    **before,
                    "edit_token": edit_token,
                    "revision_status": "no_change",
                    "action_error": (
                        "This selection can no longer be locked because it is "
                        "not an approved, bookable option on the current board."
                    ),
                }
        result = dict(before)
        result["timing_ms"] = timings
        result["change_summary"] = _change_summary(before, result, action)
        result["board"] = board_state
        return builder_revisions.persist_revision(
            run_id=run_id, edit_token=edit_token,
            expected_revision=revision, request_id=request_id, action=action,
            action_target=action_target, result=result,
            locked_selection_ids=locked,
            excluded_fixture_ids=excluded_fixtures,
            excluded_selection_ids=excluded_selections,
        )

    if action == "safer_same_fixture":
        canonical, _ = approved_builder_candidates(bookable_pool)
        safer = _safer_candidate(current or {}, canonical)
        if safer is None:
            return {
                **before,
                "edit_token": edit_token,
                "revision_status": "no_change",
                "action_error": (
                    "No safer BetSightly-approved market is currently "
                    "available on this fixture."
                ),
            }
        safer_id = _selection_id(safer)
        excluded_selections.add(current_id)
        locked.discard(current_id)
        forced.add(safer_id)
        action_target["replacement_selection_id"] = safer_id

    def build_once(candidate_pool: list[dict], current_board: dict) -> dict:
        optimization_started = time.perf_counter()
        built = build_slip(
            effective_target, pool=candidate_pool, horizon=state["horizon"],
            require_bookable=True, locked_selection_ids=locked,
            excluded_fixture_ids=excluded_fixtures,
            excluded_selection_ids=excluded_selections,
            forced_selection_ids=forced,
        )
        timings["revision_optimization"] = round(
            (time.perf_counter() - optimization_started) * 1000
        )
        return _public_result_from_build(
            effective_target, state["horizon"], built, current_board, timings
        )

    result = build_once(bookable_pool, board)
    retries = 0
    while result.get("status") == "success" and retries < MAX_BOOKABILITY_RETRIES:
        booking = result.get("booking") or {}
        if booking.get("status") == "active" and booking.get("share_code"):
            break
        if booking.get("failure_category") not in BOOKABILITY_FAILURES:
            break
        retries += 1
        retry_board, retry_pool, retry_timings = prepared_bookable_pool(
            state["horizon"], force=False, refresh_sportybet=True
        )
        live_ids = {_selection_id(pick) for pick in retry_pool}
        vanished = {
            str(game.get("selection_id")) for game in result.get("games") or []
            if str(game.get("selection_id")) not in live_ids
        }
        if not vanished:
            break
        excluded_selections.update(vanished)
        forced.difference_update(vanished)
        timings.update({f"retry_{retries}_{key}": value
                        for key, value in retry_timings.items()})
        result = build_once(retry_pool, retry_board)
    timings["bookability_retries"] = retries
    timings["revision_total"] = round((time.perf_counter() - started) * 1000)
    result["timing_ms"] = timings
    result["change_summary"] = _change_summary(before, result, action)
    result["board"] = board_state
    return builder_revisions.persist_revision(
        run_id=run_id, edit_token=edit_token,
        expected_revision=revision, request_id=request_id, action=action,
        action_target=action_target, result=result,
        locked_selection_ids=locked, excluded_fixture_ids=excluded_fixtures,
        excluded_selection_ids=excluded_selections,
    )
