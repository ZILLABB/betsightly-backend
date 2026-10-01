"""Read-only SportyBet-first shadow prediction board.

This joins the existing prepared/current-engine candidates to the SportyBet-first
identity/enrichment view. It never runs a provider refresh, publishes a card,
books a slip, settles a result, or changes the production prepared board.
"""
from __future__ import annotations

from collections import Counter

from leagues import sportybet_inventory
from leagues import sportybet_shadow_compare as shadow_compare

READY_SUPPORT = {
    shadow_compare.STRONG,
    shadow_compare.ADEQUATE,
}


def _compact_pick(pick: dict) -> dict:
    trust = pick.get("trust") or {}
    fixture = pick.get("_fixture") or {}

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    probability = pick.get("selection_probability")
    if probability is None:
        probability = pick.get("evidence_adjusted_probability")
    if probability is None:
        probability = pick.get("confidence")

    return {
        "selection_id": str(
            pick.get("selection_id")
            or f"{pick.get('match_id')}:{pick.get('market')}"
        ),
        "fixture_id": str(pick.get("match_id") or ""),
        "market": pick.get("market"),
        "selection": pick.get("prediction"),
        "odds": number(pick.get("odds")),
        "selection_probability": number(probability),
        "lower_reliability_bound": number(
            trust.get("lower_reliability_bound")
            if trust.get("lower_reliability_bound") is not None
            else pick.get("lower_reliability_bound")
        ),
        "trust_grade": trust.get("trust_grade"),
        "trust_score": number(trust.get("trust_score")),
        "quality_score": number(pick.get("quality_score")),
        "risk_adjusted_return": number(pick.get("risk_adjusted_return")),
        "market_capability": pick.get("market_capability"),
        "league": fixture.get("league") or pick.get("league"),
    }


def _approved_prepared_candidates(picks: list[dict]) -> tuple[list[dict], dict]:
    """Apply existing trust/policy in memory; never ask a provider for data."""
    try:
        from leagues.slip_builder import approved_builder_candidates

        approved, rejections = approved_builder_candidates(
            list(picks or []),
            require_bookable=False,
            include_all_eligible=True,
        )
        return approved, dict(rejections)
    except Exception as exc:
        return [], {"shadow_policy_error": type(exc).__name__}


def build_shadow_prediction_board(
    inventory: dict,
    prepared_picks: list[dict],
    prepared_fixtures: list[dict],
    *,
    prepared_status: dict | None = None,
    api_fixtures: list[dict] | None = None,
) -> dict:
    """Build one diagnostic-only shadow board from already available inputs."""
    comparison = shadow_compare.compare(
        inventory,
        prepared_fixtures,
        prepared_status=prepared_status or {},
        api_fixtures=api_fixtures or [],
    )
    approved, rejections = _approved_prepared_candidates(prepared_picks)

    by_fixture: dict[str, list[dict]] = {}
    for pick in approved:
        fixture_id = str(pick.get("match_id") or "")
        if fixture_id:
            by_fixture.setdefault(fixture_id, []).append(pick)

    readiness = Counter()
    support_counts = Counter()
    fixtures = []

    for row in comparison.get("fixtures") or []:
        prepared_identity = str(row.get("prepared_fixture_id") or "")
        fixture_id = (
            prepared_identity.split("prepared:", 1)[1]
            if prepared_identity.startswith("prepared:")
            else ""
        )
        candidates = by_fixture.get(fixture_id, [])
        support = row.get("data_support") or shadow_compare.NO_SUPPORT
        identity_matched = row.get("identity_state") in shadow_compare.MATCHED_STATES
        prediction_ready = bool(
            identity_matched
            and support in READY_SUPPORT
            and candidates
        )
        readiness["READY" if prediction_ready else "NOT_READY"] += 1
        support_counts[support] += 1

        compact = [_compact_pick(pick) for pick in candidates]
        compact.sort(
            key=lambda item: (
                -(item.get("lower_reliability_bound") or 0.0),
                -(item.get("selection_probability") or 0.0),
                item.get("market") or "",
            )
        )

        fixtures.append({
            **row,
            "prediction_ready": prediction_ready,
            "prediction_readiness_reason": (
                "SUPPORTED_CURRENT_ENGINE_CANDIDATES"
                if prediction_ready
                else (
                    "NO_APPROVED_CURRENT_ENGINE_CANDIDATE"
                    if not candidates
                    else f"DATA_SUPPORT_{support}"
                )
            ),
            "candidate_count": len(compact),
            "candidates": compact,
        })

    total = len(fixtures)
    ready = readiness["READY"]
    return {
        "status": "success" if total else "unavailable",
        "source": "SPORTYBET_FIRST_SHADOW_BOARD",
        "shadow_only": True,
        "can_publish": False,
        "can_book": False,
        "can_settle": False,
        "authoritative_for_user_output": False,
        "production_board_snapshot_id": comparison.get(
            "production_board_snapshot_id"
        ),
        "sportybet_snapshot_id": comparison.get("sportybet_snapshot_id"),
        "sportybet_complete": comparison.get("sportybet_complete"),
        "fixture_count": total,
        "prediction_ready_count": ready,
        "prediction_not_ready_count": readiness["NOT_READY"],
        "prediction_ready_rate": round(ready / total, 4) if total else 0.0,
        "data_support": dict(support_counts),
        "enrichment_states": comparison.get("enrichment_states") or {},
        "identity_states": comparison.get("identity_states") or {},
        "policy_rejections": rejections,
        "fixtures": fixtures,
    }


def current_shadow_prediction_board() -> dict:
    """Read only existing caches and prepared memory; never fan out."""
    inventory = sportybet_inventory.cached_shadow_inventory()

    try:
        from leagues.engine import prepared_board_status, prepared_pipeline

        prepared_status = prepared_board_status(days_ahead=7)
        if prepared_status.get("ready"):
            prepared_picks, prepared_fixtures = prepared_pipeline(days_ahead=7)
        else:
            prepared_picks, prepared_fixtures = [], []
    except Exception:
        prepared_status = {"ready": False}
        prepared_picks, prepared_fixtures = [], []

    dates = {
        date
        for fixture in inventory.get("fixtures") or []
        if (date := shadow_compare._iso_date(fixture.get("kickoff")))
    }
    api_fixtures = shadow_compare.cached_apifootball_fixtures(dates)

    return build_shadow_prediction_board(
        inventory,
        prepared_picks,
        prepared_fixtures,
        prepared_status=prepared_status,
        api_fixtures=api_fixtures,
    )


def status() -> dict:
    """Compact admin/status payload without per-fixture candidate details."""
    result = current_shadow_prediction_board()
    return {
        key: value
        for key, value in result.items()
        if key != "fixtures"
    }
