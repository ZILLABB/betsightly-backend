"""Read-only acceptance report for the original BetSightly V2 scope."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from leagues import builder_runs
from leagues import football_first_shadow_v2_observations as v2_shadow


REQUIRED_BUILDER_MODES = (
    "target_odds",
    "game_count",
    "strongest",
    "manual",
)


def _window(days: int) -> tuple[str, str]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(1, int(days)) - 1)
    return start.isoformat(), end.isoformat()


def report(
    *,
    days: int = 90,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Combine V2 Builder measurement with the frozen challenger review gate.

    This endpoint never mutates prediction policy and never promotes a model.
    A challenger can remain evidence-gated while the product V2 closeout is
    otherwise operationally complete.
    """
    if not start or not end:
        start, end = _window(days)

    requests = builder_runs.summary(
        start,
        end,
    )

    performance = builder_runs.performance(
        days=max(1, int(days))
    )

    shadow = v2_shadow.review_packet()
    gate = shadow.get("review_gate") or {}

    observed_modes = {
        str(item.get("mode"))
        for item in requests.get("by_mode") or []
        if item.get("mode")
    }

    return {
        "status": "success",
        "scope": "initial_v2_closeout",
        "window": {
            "start": start,
            "end": end,
            "days": max(1, int(days)),
        },
        "builder": {
            "required_modes": list(REQUIRED_BUILDER_MODES),
            "observed_modes": sorted(observed_modes),
            "request_analytics": requests,
            "settled_performance": performance,
            "measurement_contract_ready": all(
                key in requests
                for key in (
                    "by_mode",
                    "by_horizon",
                    "by_game_count",
                    "by_fill_strategy",
                    "by_requested_market",
                    "by_selected_market",
                )
            ),
        },
        "challenger": {
            "shadow_only": True,
            "review_gate": gate,
            "evidence": shadow.get("evidence"),
            "latest_review": shadow.get("latest_review"),
            "promotion_effective": False,
            "automatic_promotion": False,
        },
        "closeout": {
            "product_measurement_ready": True,
            "challenger_promotion_is_required_to_close_v2": False,
            "challenger_promotion_ready": bool(
                gate.get("eligible")
            ),
            "live_prediction_policy_changed": False,
        },
    }
