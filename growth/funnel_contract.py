"""Shared, product-scoped analytics funnel contract.

The local event store and PostHog are separate transports for the same human
journeys.  Keep stage meaning here so a healthy provider cannot reintroduce
cross-product booking activity into a product funnel.
"""

from __future__ import annotations

from dataclasses import dataclass


PREDICTION_PRODUCT_AREAS = frozenset({
    "PREDICTIONS", "BANKER", "TWO_ODDS", "FIVE_ODDS", "TEN_ODDS",
    "OVER_1_5", "FALLBACK",
})


@dataclass(frozen=True)
class FunnelStage:
    label: str
    event: str
    product_areas: frozenset[str]


FUNNEL_SPECS: dict[str, tuple[FunnelStage, ...]] = {
    # This is intentionally a product journey, not the all-site audience.
    "prediction": (
        FunnelStage("Predictions viewed", "prediction_viewed", PREDICTION_PRODUCT_AREAS),
        FunnelStage("Valid code displayed", "booking_code_viewed", PREDICTION_PRODUCT_AREAS),
        FunnelStage("Code copied", "booking_code_copied", PREDICTION_PRODUCT_AREAS),
        FunnelStage("SportyBet opened", "sportybet_opened", PREDICTION_PRODUCT_AREAS),
    ),
    # Target selection is mode-specific; every legitimate Builder mode can
    # instead progress through request -> generated -> booking actions.
    "builder": (
        FunnelStage("Builder opened", "builder_opened", frozenset({"BUILD_SLIP"})),
        FunnelStage("Valid code displayed", "booking_code_viewed", frozenset({"BUILD_SLIP"})),
        FunnelStage("Code copied", "booking_code_copied", frozenset({"BUILD_SLIP"})),
        FunnelStage("SportyBet opened", "sportybet_opened", frozenset({"BUILD_SLIP"})),
    ),
    "rollover": (
        FunnelStage("Rollover viewed", "rollover_viewed", frozenset({"ROLLOVER"})),
        FunnelStage("Valid code displayed", "booking_code_viewed", frozenset({"ROLLOVER"})),
        FunnelStage("Code copied", "booking_code_copied", frozenset({"ROLLOVER"})),
        FunnelStage("SportyBet opened", "sportybet_opened", frozenset({"ROLLOVER"})),
    ),
}


def assess_funnels(funnels: dict[str, list[dict]], schema_errors: int = 0) -> dict:
    """Return explicit integrity findings; never repair or hide bad counts."""
    issues: list[dict] = []

    checks: dict[str, bool] = {
        "FUNNEL_MONOTONICITY": True,
        "ZERO_ENTRY_DOWNSTREAM": True,
        "CONVERSION_RANGE": True,
        "PRODUCT_SCOPE_ISOLATION": True,
        "PROVIDER_SCHEMA_ERRORS": not bool(schema_errors),
    }

    # Prove the checked-in contract itself does not assign the same downstream
    # booking interaction/product area to more than one product funnel.
    owners: dict[tuple[str, str], str] = {}
    downstream_events = {
        "booking_code_viewed",
        "booking_code_copied",
        "sportybet_opened",
    }

    for funnel_name, spec in FUNNEL_SPECS.items():
        for stage in spec:
            if stage.event not in downstream_events:
                continue
            for area in stage.product_areas:
                key = (stage.event, area)
                previous_owner = owners.get(key)
                if previous_owner is not None and previous_owner != funnel_name:
                    checks["PRODUCT_SCOPE_ISOLATION"] = False
                    issues.append({
                        "code": "PRODUCT_SCOPE_ISOLATION",
                        "funnel": funnel_name,
                        "conflicts_with": previous_owner,
                        "event": stage.event,
                        "product_area": area,
                        "severity": "error",
                    })
                else:
                    owners[key] = funnel_name

    for name, stages in funnels.items():
        previous = None

        for index, stage in enumerate(stages):
            count = int(stage.get("count") or 0)

            if previous is not None and count > previous:
                checks["FUNNEL_MONOTONICITY"] = False
                issues.append({
                    "code": "FUNNEL_MONOTONICITY",
                    "funnel": name,
                    "stage": stage.get("label"),
                    "severity": "error",
                })

            if index and not (stages[0].get("count") or 0) and count:
                checks["ZERO_ENTRY_DOWNSTREAM"] = False
                issues.append({
                    "code": "ZERO_ENTRY_DOWNSTREAM",
                    "funnel": name,
                    "stage": stage.get("label"),
                    "severity": "error",
                })

            for rate_name in ("conversion", "dropoff"):
                rate = stage.get(rate_name)
                if rate is not None and not 0 <= float(rate) <= 1:
                    checks["CONVERSION_RANGE"] = False
                    issues.append({
                        "code": "CONVERSION_RANGE",
                        "funnel": name,
                        "stage": stage.get("label"),
                        "severity": "error",
                    })

            previous = count

    if schema_errors:
        issues.append({
            "code": "PROVIDER_SCHEMA_ERRORS",
            "severity": "warning",
            "count": int(schema_errors),
        })

    return {
        "status": (
            "error"
            if any(issue["severity"] == "error" for issue in issues)
            else "warning"
            if issues
            else "healthy"
        ),
        "issues": issues,
        "checks": checks,
    }
