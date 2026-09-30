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

# Portfolio diversification never changes prediction probability or trust.
# It is only allowed to choose a less-exposed candidate when its conservative
# lower bound is effectively comparable with the strongest available option.
PORTFOLIO_COMPARABLE_LOWER_BOUND_DELTA = 0.005
PORTFOLIO_TEAM_WEIGHT = 3.0
PORTFOLIO_LEAGUE_WEIGHT = 1.0
PORTFOLIO_MARKET_WEIGHT = 0.5


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


def _recent_exposure(options: dict) -> dict:
    value = options.get("_recent_exposure") or {}
    return value if isinstance(value, dict) else {}


def _pick_team_names(pick: dict) -> set[str]:
    fixture = pick.get("_fixture") or {}
    values = {
        str(pick.get("home_team") or "").strip().casefold(),
        str(pick.get("away_team") or "").strip().casefold(),
    }

    for side in ("home", "away"):
        team = fixture.get(side) or {}
        values.add(str(team.get("name") or "").strip().casefold())

    return {value for value in values if value}


def _pick_league_names(pick: dict) -> set[str]:
    fixture = pick.get("_fixture") or {}
    values = {
        str(pick.get("league") or "").strip().casefold(),
        str(fixture.get("league") or "").strip().casefold(),
        str(fixture.get("league_slug") or "").strip().casefold(),
    }
    return {value for value in values if value}


def _portfolio_penalty(pick: dict, options: dict) -> float:
    """History exposure score, separate from football prediction quality."""
    if not options.get("_build_another"):
        return 0.0

    exposure = _recent_exposure(options)
    if not int(exposure.get("history_ticket_count") or 0):
        return 0.0

    team_counts = exposure.get("team_counts") or {}
    league_counts = exposure.get("league_counts") or {}
    market_counts = exposure.get("market_counts") or {}

    team_exposure = sum(
        int(team_counts.get(team, 0) or 0)
        for team in _pick_team_names(pick)
    )

    league_exposure = max(
        (
            int(league_counts.get(league, 0) or 0)
            for league in _pick_league_names(pick)
        ),
        default=0,
    )

    market = str(pick.get("market") or "").strip()
    market_exposure = int(
        market_counts.get(market, 0) or 0
    )

    return (
        team_exposure * PORTFOLIO_TEAM_WEIGHT
        + league_exposure * PORTFOLIO_LEAGUE_WEIGHT
        + market_exposure * PORTFOLIO_MARKET_WEIGHT
    )


def _annotate_portfolio_pool(
    pool: list[dict],
    options: dict,
) -> list[dict]:
    out = []

    for source in pool:
        pick = dict(source)
        pick["_portfolio_penalty"] = _portfolio_penalty(
            pick,
            options,
        )
        out.append(pick)

    return out


def _portfolio_order(
    pool: list[dict],
    options: dict,
) -> list[dict]:
    """Quality first, exposure second within a narrow comparable band."""
    ranked = sorted(pool, key=_rank_key)

    if (
        not options.get("_build_another")
        or not int(
            _recent_exposure(options).get(
                "history_ticket_count"
            ) or 0
        )
    ):
        return ranked

    remaining = list(ranked)
    ordered = []

    while remaining:
        strongest = remaining[0]
        strongest_grade = _trust_grade(strongest)
        minimum_comparable = (
            _lower_bound(strongest)
            - PORTFOLIO_COMPARABLE_LOWER_BOUND_DELTA
        )

        comparable = [
            pick
            for pick in remaining
            if (
                _trust_grade(pick) == strongest_grade
                and _lower_bound(pick) >= minimum_comparable
            )
        ]

        chosen = min(
            comparable,
            key=lambda pick: (
                _portfolio_penalty(pick, options),
                _rank_key(pick),
            ),
        )

        ordered.append(chosen)
        remaining.remove(chosen)

    return ordered


def _diversification_stage_names(options: dict) -> list[str]:
    """Fresh first; qualified repeats are a fallback, never a weaker gate."""
    if not options.get("_build_another"):
        return ["normal"]

    exposure = _recent_exposure(options)

    if not int(exposure.get("history_ticket_count") or 0):
        return ["no_history"]

    return [
        "fresh",
        "fixture_reuse",
        "qualified_repeat_fallback",
    ]


def _apply_diversification_stage(
    pool: list[dict],
    options: dict,
    stage: str,
) -> list[dict]:
    if stage in {"normal", "no_history", "qualified_repeat_fallback"}:
        return _annotate_portfolio_pool(
            list(pool),
            options,
        )

    exposure = _recent_exposure(options)

    exact = {
        str(value)
        for value in exposure.get("exact_selection_ids") or []
        if str(value)
    }

    fixtures = {
        str(value)
        for value in exposure.get("recent_fixture_ids") or []
        if str(value)
    }

    out = []

    for pick in pool:
        selection_id = str(pick.get("selection_id") or "")
        fixture_id = str(pick.get("match_id") or "")

        if selection_id and selection_id in exact:
            continue

        if stage == "fresh" and fixture_id and fixture_id in fixtures:
            continue

        out.append(pick)

    return _annotate_portfolio_pool(
        out,
        options,
    )


def _diversification_metadata(
    selected: list[dict],
    options: dict,
    stage: str,
) -> dict:
    build_another = bool(options.get("_build_another"))
    exposure = _recent_exposure(options)

    exact = {
        str(value)
        for value in exposure.get("exact_selection_ids") or []
        if str(value)
    }

    fixtures = {
        str(value)
        for value in exposure.get("recent_fixture_ids") or []
        if str(value)
    }

    repeated_selections = sum(
        1
        for item in selected
        if str(item.get("selection_id") or "") in exact
    )

    repeated_fixtures = sum(
        1
        for item in selected
        if str(item.get("match_id") or item.get("fixture_id") or "") in fixtures
    )

    delivered = len(selected)

    team_counts = exposure.get("team_counts") or {}
    league_counts = exposure.get("league_counts") or {}
    market_counts = exposure.get("market_counts") or {}

    repeated_teams = {
        team
        for item in selected
        for team in _pick_team_names(item)
        if int(team_counts.get(team, 0) or 0) > 0
    }

    repeated_leagues = {
        league
        for item in selected
        for league in _pick_league_names(item)
        if int(league_counts.get(league, 0) or 0) > 0
    }

    repeated_markets = {
        str(item.get("market") or "").strip()
        for item in selected
        if (
            str(item.get("market") or "").strip()
            and int(
                market_counts.get(
                    str(item.get("market") or "").strip(),
                    0,
                ) or 0
            ) > 0
        )
    }

    return {
        "applied": bool(
            build_another
            and int(exposure.get("history_ticket_count") or 0)
        ),
        "build_another": build_another,
        "history_ticket_count": int(
            exposure.get("history_ticket_count") or 0
        ),
        "strategy_used": stage,
        "fresh_selection_count": max(
            0,
            delivered - repeated_selections,
        ),
        "repeated_selection_count": repeated_selections,
        "repeated_fixture_count": repeated_fixtures,
        "repeated_team_count": len(repeated_teams),
        "repeated_league_count": len(repeated_leagues),
        "repeated_market_count": len(repeated_markets),
        # A repeated exact selection only appears in the final fallback.
        "unavoidable_reuse_count": repeated_selections,
        "quality_floor_preserved": True,
        "portfolio_quality_delta": (
            PORTFOLIO_COMPARABLE_LOWER_BOUND_DELTA
        ),
    }


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
        allow_pipeline_fallback=False,
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
        "staging_supplemental_counts": {
            "qualified_pool": int(
                timings.get("supplemental_qualified_count") or 0
            ),
            "prepared_bookable": sum(
                1
                for pick in raw
                if pick.get("_staging_supplemental")
            ),
            "after_user_raw_filters": sum(
                1
                for pick in filtered_raw
                if pick.get("_staging_supplemental")
            ),
            "after_trust_and_policy": sum(
                1
                for pick in approved
                if pick.get("_staging_supplemental")
            ),
            "approved": sum(
                1
                for pick in final
                if pick.get("_staging_supplemental")
            ),
        },
        "staging_supplemental_bookability_rejections": dict(
            timings.get("supplemental_bookability_rejections") or {}
        ),
        "effective_min_probability": effective_floor,
        "trust_rejection_reasons": dict(trust_rejections),
        "market_counts": {
            "after_user_raw_filters": dict(collections.Counter(
                str(pick.get("market") or "unknown")
                for pick in filtered_raw
            )),
            "after_trust_and_policy": dict(collections.Counter(
                str(pick.get("market") or "unknown")
                for pick in approved
            )),
            "approved": dict(collections.Counter(
                str(pick.get("market") or "unknown")
                for pick in final
            )),
        },
        "timing_ms": timings,
        "require_bookable_effective": True,
        "prepared_board_snapshot_id": prepared_state.get("board_snapshot_id"),
        "prepared_board_stale": bool(prepared_state.get("stale")),
    }
    return board, final, diagnostics



def _diagnostics_for_requested_markets(
    diagnostics: dict,
    requested_markets: list[str],
) -> dict:
    # Keep requested-market diagnostics truthful when broader fill uses
    # one all-eligible approved snapshot.
    markets: list[str] = []
    for value in requested_markets:
        market = str(value or "").strip()
        if market and market not in markets:
            markets.append(market)

    out = dict(diagnostics)
    stage_counts = diagnostics.get("market_counts") or {}
    filtered_counts: dict[str, dict[str, int]] = {}

    for stage in (
        "after_user_raw_filters",
        "after_trust_and_policy",
        "approved",
    ):
        counts = stage_counts.get(stage) or {}
        filtered_counts[stage] = {
            market: int(counts.get(market, 0) or 0)
            for market in markets
        }

    out["market_counts"] = filtered_counts
    out["after_user_raw_filters"] = sum(
        filtered_counts["after_user_raw_filters"].values()
    )
    out["after_trust_and_policy"] = sum(
        filtered_counts["after_trust_and_policy"].values()
    )
    out["broader_fill_approved_count"] = int(
        diagnostics.get("approved_count") or 0
    )
    out["approved_count"] = sum(filtered_counts["approved"].values())
    return out

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
            "board_stale": bool(prepared.get("stale")),
            "board_source": prepared.get("board_source"),
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


def _select_unique(
    pool: list[dict],
    limit: int,
    options: dict | None = None,
) -> list[dict]:
    selected = []
    seen_fixtures: set[str] = set()
    seen_teams: set[str] = set()

    for pick in _portfolio_order(
        pool,
        options or {},
    ):
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


def _select_market_balanced(
    pool: list[dict],
    limit: int,
    requested_markets: list[str] | None,
    fallback_pool: list[dict] | None = None,
    options: dict | None = None,
) -> tuple[list[dict], dict]:
    """Select Game Count picks while respecting the user's requested market mix.

    Every candidate has already passed BetSightly's quality, trust and exact
    SportyBet-bookability gates. When multiple markets are explicitly selected,
    Game Count mode tries to distribute slots evenly across them. If one market
    cannot supply its share, remaining slots are filled by the strongest
    qualifying picks from the other requested markets. Quality floors are never
    lowered to manufacture the requested mix.
    """
    markets: list[str] = []
    for value in requested_markets or []:
        market = str(value or "").strip()
        if market and market not in markets:
            markets.append(market)

    # No explicit multi-market request: preserve the mature quality-first path.
    if len(markets) <= 1 and not fallback_pool:
        selected = _select_unique(
            pool,
            limit,
            options,
        )
        delivered = collections.Counter(
            str(pick.get("market") or "unknown") for pick in selected
        )
        targets = {markets[0]: limit} if markets else {}
        shortfalls = {
            market: max(0, target - int(delivered.get(market, 0)))
            for market, target in targets.items()
            if target > int(delivered.get(market, 0))
        }
        return selected, {
            "applied": False,
            "requested_markets": markets,
            "target_distribution": targets,
            "delivered_distribution": dict(delivered),
            "shortfalls": shortfalls,
            "quality_floor_preserved": True,
            "strategy": "quality_first",
            "requested_market_leg_count": len(selected),
            "fallback_market_leg_count": 0,
            "fallback_market_distribution": {},
            "fallback_markets_used": [],
        }

    base, remainder = divmod(limit, len(markets))
    targets = {
        market: base + (1 if index < remainder else 0)
        for index, market in enumerate(markets)
    }

    ranked = _portfolio_order(
        pool,
        options or {},
    )
    buckets = {
        market: [
            pick for pick in ranked
            if str(pick.get("market") or "") == market
        ]
        for market in markets
    }
    positions = {market: 0 for market in markets}

    # A plentiful market must not consume the only fixture/team available to
    # a scarce requested market. Allocate the most supply-constrained markets
    # first, while preserving the same quality ranking inside each market.
    #
    # Example: if O1.5 has 30 candidates and Home Win has one candidate on a
    # fixture that also has O1.5, Home Win gets first access to that fixture
    # and O1.5 can use one of its many alternatives.
    market_position = {
        market: index
        for index, market in enumerate(markets)
    }
    market_order = sorted(
        markets,
        key=lambda market: (
            len(buckets[market]) / max(1, targets[market]),
            len(buckets[market]),
            market_position[market],
        ),
    )

    selected: list[dict] = []
    seen_fixtures: set[str] = set()
    seen_teams: set[str] = set()
    delivered: collections.Counter[str] = collections.Counter()

    def add_if_available(pick: dict) -> bool:
        fixture_id = str(pick.get("match_id") or "")
        teams = _fixture_teams(pick)

        if fixture_id in seen_fixtures:
            return False
        if teams and teams & seen_teams:
            return False

        selected.append(pick)
        seen_fixtures.add(fixture_id)
        seen_teams.update(teams)
        delivered[str(pick.get("market") or "unknown")] += 1
        return True

    # First pass: round-robin toward the requested even market allocation.
    while len(selected) < limit:
        progressed = False

        for market in market_order:
            if len(selected) >= limit:
                break
            if delivered[market] >= targets[market]:
                continue

            bucket = buckets[market]
            while positions[market] < len(bucket):
                pick = bucket[positions[market]]
                positions[market] += 1
                if add_if_available(pick):
                    progressed = True
                    break

        if not progressed:
            break

    # Second pass: if a market could not fill its requested share, backfill
    # with the strongest remaining candidate from the user's other markets.
    if len(selected) < limit:
        selected_ids = {
            str(pick.get("selection_id") or "") for pick in selected
        }

        for pick in ranked:
            if len(selected) >= limit:
                break
            selection_id = str(pick.get("selection_id") or "")
            if selection_id in selected_ids:
                continue
            if add_if_available(pick):
                selected_ids.add(selection_id)

    requested_count = len(selected)
    fallback_distribution: collections.Counter[str] = collections.Counter()
    # Explicitly opt-in broader fill only. These candidates have already gone
    # through the identical final Builder gates in _candidate_pool.
    if len(selected) < limit and fallback_pool:
        selected_ids = {str(pick.get("selection_id") or "") for pick in selected}
        for pick in _portfolio_order(
            fallback_pool,
            options or {},
        ):
            if len(selected) >= limit:
                break
            if str(pick.get("market") or "") in markets:
                continue
            selection_id = str(pick.get("selection_id") or "")
            if selection_id in selected_ids:
                continue
            if add_if_available(pick):
                selected_ids.add(selection_id)
                fallback_distribution[str(pick.get("market") or "unknown")] += 1

    selected.sort(key=_rank_key)

    shortfalls = {
        market: max(0, targets[market] - int(delivered.get(market, 0)))
        for market in markets
        if targets[market] > int(delivered.get(market, 0))
    }

    return selected, {
        "applied": True,
        "requested_markets": markets,
        "target_distribution": targets,
        "delivered_distribution": {
            market: int(delivered.get(market, 0))
            for market in markets
        },
        "shortfalls": shortfalls,
        "quality_floor_preserved": True,
        "strategy": "even_requested_markets_then_quality_backfill",
        "requested_market_leg_count": requested_count,
        "fallback_market_leg_count": sum(fallback_distribution.values()),
        "fallback_market_distribution": dict(fallback_distribution),
        "fallback_markets_used": sorted(fallback_distribution),
    }


def _market_availability(
    diagnostics: dict,
    market_balance: dict,
) -> dict[str, dict]:
    """Explain each requested Game Count market without weakening its gates."""
    stage_counts = diagnostics.get("market_counts") or {}
    raw_counts = stage_counts.get("after_user_raw_filters") or {}
    trusted_counts = stage_counts.get("after_trust_and_policy") or {}
    approved_counts = stage_counts.get("approved") or {}

    targets = market_balance.get("target_distribution") or {}
    delivered = market_balance.get("delivered_distribution") or {}

    out: dict[str, dict] = {}

    for market in market_balance.get("requested_markets") or []:
        target = int(targets.get(market, 0) or 0)
        raw = int(raw_counts.get(market, 0) or 0)
        after_trust = int(trusted_counts.get(market, 0) or 0)
        approved = int(approved_counts.get(market, 0) or 0)
        selected = int(delivered.get(market, 0) or 0)
        shortfall = max(0, target - selected)

        if shortfall == 0:
            reason = "TARGET_SHARE_FILLED"
        elif raw == 0:
            reason = "NO_RAW_CANDIDATES"
        elif after_trust == 0:
            reason = "TRUST_OR_MARKET_POLICY_REJECTED"
        elif approved == 0:
            reason = "BELOW_FINAL_BUILDER_GATES"
        elif selected < min(target, approved):
            reason = "FIXTURE_OR_TEAM_DIVERSITY"
        else:
            reason = "INSUFFICIENT_APPROVED_SELECTIONS"

        out[market] = {
            "target": target,
            "raw": raw,
            "after_trust_and_policy": after_trust,
            "approved": approved,
            "selected": selected,
            "shortfall": shortfall,
            "primary_reason": reason,
        }

    return out


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

    # Game Count with explicit markets is structure-driven:
    # the user chooses the allowed market mix while BetSightly still
    # enforces probability, trust, capability and exact bookability.
    #
    # Strongest remains canonical quality-first. But Game Count must see
    # every otherwise-approved candidate from the user's selected markets
    # before balancing, or canonical fixture ranking can silently remove
    # a valid secondary market.
    requested_markets = [
        str(value).strip()
        for value in (options.get("markets") or [])
        if str(value).strip()
    ]
    fill_strategy = str(options.get("fill_strategy") or "strict_selected_markets")
    if (
        mode == "game_count"
        and fill_strategy
        not in {"strict_selected_markets", "selected_first_then_eligible"}
    ):
        return {"status": "error", "mode": mode, "reason": "invalid fill_strategy"}

    use_all_eligible = (
        mode == "game_count"
        and bool(requested_markets)
    )
    broader_fill = bool(
        mode == "game_count"
        and requested_markets
        and fill_strategy == "selected_first_then_eligible"
    )
    fallback_pool: list[dict] | None = None

    try:
        if broader_fill:
            # Build the wider approved universe once so requested and fallback
            # legs come from the same prepared/SportyBet snapshot.
            broader_options = {**options, "markets": []}
            board, all_eligible_pool, broader_diagnostics = _candidate_pool(
                broader_options,
                include_all_eligible=True,
            )
            requested_set = set(requested_markets)
            pool = [
                pick
                for pick in all_eligible_pool
                if str(pick.get("market") or "") in requested_set
            ]
            diagnostics = _diagnostics_for_requested_markets(
                broader_diagnostics,
                requested_markets,
            )
            fallback_pool = all_eligible_pool
        else:
            board, pool, diagnostics = _candidate_pool(
                options,
                include_all_eligible=use_all_eligible,
            )
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
        built = None
        diversification_stage = "normal"

        stages = _diversification_stage_names(options)

        for index, stage in enumerate(stages):
            stage_pool = _apply_diversification_stage(
                pool,
                options,
                stage,
            )

            candidate = build_slip(
                target,
                pool=stage_pool,
                max_legs=MAX_LEGS,
                horizon=str(options.get("horizon") or "7_days"),
                require_bookable=True,
                preapproved_pool=True,
            )

            built = candidate
            diversification_stage = stage

            achieved = float(
                candidate.get("achieved_odds")
                or candidate.get("best_reachable")
                or 0.0
            )

            # Freshness wins when it can still satisfy the requested target
            # under the exact same quality/bookability policy.
            if candidate.get("ok") and achieved >= target:
                break

            # Otherwise progressively relax only the repeat preference.
            if index == len(stages) - 1:
                break

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
            "board": _board_context(board),
        })
        games = list(out.get("games") or [])
        probabilities = []

        for game in games:
            value = (
                game.get("selection_probability")
                if game.get("selection_probability") is not None
                else game.get("evidence_adjusted_probability")
                if game.get("evidence_adjusted_probability") is not None
                else game.get("confidence")
            )
            number = _number(value)
            if number is not None:
                probabilities.append(float(number))

        if probabilities:
            out.setdefault(
                "average_probability",
                round(
                    sum(probabilities)
                    / len(probabilities),
                    6,
                ),
            )
            out.setdefault(
                "lowest_probability",
                round(
                    min(probabilities),
                    6,
                ),
            )

        out["diversification"] = _diversification_metadata(
            games,
            options,
            diversification_stage,
        )
        return out

    if mode == "game_count":
        requested = int(options.get("game_count") or 0)
        if not (1 <= requested <= MAX_GAME_COUNT):
            return {
                "status": "error",
                "mode": mode,
                "reason": f"game_count must be between 1 and {MAX_GAME_COUNT}.",
            }

        selected = []
        market_balance = {}
        diversification_stage = "normal"

        stages = _diversification_stage_names(options)

        for index, stage in enumerate(stages):
            stage_pool = _apply_diversification_stage(
                pool,
                options,
                stage,
            )
            stage_fallback = (
                _apply_diversification_stage(
                    fallback_pool,
                    options,
                    stage,
                )
                if fallback_pool is not None
                else None
            )

            candidate_selected, candidate_balance = _select_market_balanced(
                stage_pool,
                requested,
                list(options.get("markets") or []),
                fallback_pool=stage_fallback,
                options=options,
            )

            selected = candidate_selected
            market_balance = candidate_balance
            diversification_stage = stage

            if len(candidate_selected) >= requested:
                break

            if index == len(stages) - 1:
                break

        result = _selected_response(
            mode,
            options,
            selected,
            board,
            diagnostics,
            requested,
        )
        result["market_balance"] = market_balance
        result["fill_strategy"] = fill_strategy
        result["requested_market_leg_count"] = int(
            market_balance.get("requested_market_leg_count") or 0
        )
        result["fallback_market_leg_count"] = int(
            market_balance.get("fallback_market_leg_count") or 0
        )
        result["fallback_market_distribution"] = dict(
            market_balance.get("fallback_market_distribution") or {}
        )
        result["fallback_markets_used"] = list(
            market_balance.get("fallback_markets_used") or []
        )
        result["market_availability"] = _market_availability(
            diagnostics,
            market_balance,
        )
        result["diversification"] = _diversification_metadata(
            selected,
            options,
            diversification_stage,
        )
        return result

    max_games = int(options.get("max_games") or 10)
    if not (1 <= max_games <= MAX_GAME_COUNT):
        return {
            "status": "error",
            "mode": mode,
            "reason": f"max_games must be between 1 and {MAX_GAME_COUNT}.",
        }
    selected = []
    diversification_stage = "normal"

    stages = _diversification_stage_names(options)

    for index, stage in enumerate(stages):
        stage_pool = _apply_diversification_stage(
            pool,
            options,
            stage,
        )

        candidate_selected = _select_unique(
            stage_pool,
            max_games,
            options,
        )

        selected = candidate_selected
        diversification_stage = stage

        if len(candidate_selected) >= max_games:
            break

        if index == len(stages) - 1:
            break

    result = _selected_response(
        mode,
        options,
        selected,
        board,
        diagnostics,
    )
    result["diversification"] = _diversification_metadata(
        selected,
        options,
        diversification_stage,
    )
    return result


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
        # Manual booking starts from the currently prepared/bookable snapshot.
        # Do not force a complete SportyBet catalogue crawl here: that can take
        # minutes and makes a user-facing "Generate Code" action time out.
        #
        # Exact safety is still enforced downstream by create_booking():
        # SportyBet creates the requested ticket and the returned code is read
        # back and checked for the exact event/market/outcome set, availability
        # and bookmaker-returned odds before any share code is exposed.
        board, pool, diagnostics = _candidate_pool(
            options,
            refresh_sportybet=False,
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
