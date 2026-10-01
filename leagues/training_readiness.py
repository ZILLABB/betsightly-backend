"""Derive conservative BetSightly training-readiness decisions."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


READY = "READY"
CONDITIONAL = "CONDITIONAL"
BLOCKED = "BLOCKED"
NOT_NEEDED = "NOT_NEEDED"


@dataclass(frozen=True)
class ReadinessDecision:
    use_case: str
    status: str
    reason: str
    blockers: tuple[str, ...]
    next_action: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["blockers"] = list(self.blockers)
        return value


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def football_history_status(manifest: dict | None) -> dict:
    manifest = manifest or {}
    dedupe = manifest.get("deduplication") or {}
    coverage = manifest.get("coverage") or []

    covered_ids = sorted(
        {
            int(item["league_id"])
            for item in coverage
            if item.get("league_id") is not None and int(item.get("rows") or 0) > 0
        }
    )
    unique_matches = int(dedupe.get("unique_matches") or 0)
    conflicting = int(dedupe.get("conflicting_duplicates") or 0)

    validated = bool(
        manifest.get("dataset") == "football_history"
        and manifest.get("source_class") == "RESULTS_ONLY"
        and unique_matches > 0
        and conflicting == 0
        and covered_ids
        and manifest.get("market_training_eligible") is False
    )

    return {
        "validated": validated,
        "unique_matches": unique_matches,
        "covered_league_ids": covered_ids,
        "covered_competitions": len(covered_ids),
        "source_file_count": int(manifest.get("source_file_count") or 0),
        "historical_cutoff_date": manifest.get("historical_cutoff_date"),
        "conflicting_duplicates": conflicting,
        "market_training_eligible": manifest.get("market_training_eligible"),
        "output_sha256": manifest.get("output_sha256"),
    }


def derive(
    training_audit: dict,
    coverage_audit: dict,
    source_registry: dict,
    football_history: dict | None = None,
) -> dict:
    rows = training_audit["rows"]
    odds = training_audit["odds"]
    duplicates = training_audit["duplicates"]
    training_contract = training_audit["training_contract"]
    derived_split = training_contract.get("derived_split") or {}

    missing_live = list(
        coverage_audit.get("missing_live_target_ids")
        or training_audit.get("coverage", {}).get(
            "configured_live_ids_missing_from_dataset"
        )
        or []
    )

    current_samples = int(
        rows.get("derived_trainable_samples_after_5_game_warmup") or 0
    )
    meta_samples = int(training_contract.get("meta_n_samples") or 0)
    exact_provenance = int(
        source_registry.get("odds_backed_covered_count") or 0
    )
    results_sources = int(
        source_registry.get("results_history_covered_count") or 0
    )
    unresolved_sources = int(source_registry.get("unresolved_count") or 0)

    history = football_history_status(football_history)
    split_ready = bool(
        derived_split.get("strategy") == "whole_calendar_date"
        and not derived_split.get("train_calib_same_date_boundary")
        and not derived_split.get("calib_test_same_date_boundary")
    )

    baseline_reproducible = bool(
        current_samples
        and current_samples == meta_samples
        and int(duplicates.get("duplicate_keys") or 0) == 0
        and int(duplicates.get("conflicting_score_keys") or 0) == 0
        and not training_contract.get("direct_outcome_columns_in_features")
    )

    decisions: list[ReadinessDecision] = []

    decisions.append(ReadinessDecision(
        use_case="current_deployed_ensemble_baseline",
        status=READY if baseline_reproducible else BLOCKED,
        reason=(
            "The current 66,699-row corpus reproduces the deployed 64,218 "
            "trainable samples exactly and has no duplicate/conflicting fixture "
            "keys or direct outcome columns in the feature list."
            if baseline_reproducible
            else
            "The current corpus no longer reproduces the deployed model contract."
        ),
        blockers=tuple(
            [] if baseline_reproducible else ["baseline_reproducibility_failed"]
        ),
        next_action=(
            "Keep as the frozen benchmark; do not overwrite it while expanding data."
            if baseline_reproducible
            else
            "Resolve baseline drift before any model work."
        ),
    ))

    decisions.append(ReadinessDecision(
        use_case="immediate_same_corpus_retrain",
        status=NOT_NEEDED if baseline_reproducible else BLOCKED,
        reason=(
            "Retraining the same unchanged corpus would not address the identified "
            "coverage or provenance gaps."
            if baseline_reproducible
            else
            "Baseline integrity must be restored first."
        ),
        blockers=tuple(),
        next_action=(
            "Do not spend compute retraining the same 64,218 samples."
            if baseline_reproducible
            else
            "Repair the baseline."
        ),
    ))

    market_blockers = []
    if (
        training_audit.get("provenance", {}).get("fetcher_contract", {})
        .get("actual_source") == "football-data.co.uk"
        and not training_audit.get("provenance", {}).get("present_fields")
    ):
        market_blockers.append("legacy_rows_lack_exact_row_level_provenance")
    if float(odds.get("complete_ou25_pct") or 0.0) < 95.0:
        market_blockers.append("ou25_price_coverage_is_partial")
    if exact_provenance == 0:
        market_blockers.append("no_new_gap_source_has_verified_bookmaker_odds")
    if missing_live:
        market_blockers.append("live_competition_coverage_gap")

    decisions.append(ReadinessDecision(
        use_case="expanded_current_25_feature_market_ensemble",
        status=BLOCKED if market_blockers else READY,
        reason=(
            "The current ensemble depends on bookmaker-price features. The "
            "expanded competitions do not yet have verified odds-backed history, "
            "and the legacy corpus cannot prove row-level price timing/source."
            if market_blockers
            else
            "Expanded market-feature data satisfies provenance and coverage gates."
        ),
        blockers=tuple(market_blockers),
        next_action=(
            "Build an odds-backed market_training dataset with explicit source/"
            "snapshot provenance before any expanded retrain."
            if market_blockers
            else
            "Train an isolated challenger and compare on a chronological holdout."
        ),
    ))

    football_blockers = []
    if not history["validated"] and results_sources == 0:
        football_blockers.append("no_verified_results_history_sources")
    if unresolved_sources:
        football_blockers.append(
            f"{unresolved_sources}_live_competitions_still_unresolved"
        )

    if history["validated"]:
        football_reason = (
            f"The isolated football_history dataset is validated with "
            f"{history['unique_matches']:,} unique results across "
            f"{history['covered_competitions']} missing live competitions. "
            "It contains no bookmaker-odds claim and remains isolated from the "
            "production market-feature corpus."
        )
        football_next = (
            "Use football_history for form/Elo/replay experiments; keep the "
            "three unresolved competitions fail-closed until verified sources exist."
            if unresolved_sources
            else
            "Use football_history for form/Elo/replay experiments."
        )
    elif results_sources:
        football_reason = (
            f"Verified free results-history sources exist for {results_sources} "
            f"of {len(missing_live)} currently missing live competitions, but "
            "the normalized football_history dataset is not yet validated."
        )
        football_next = (
            "Ingest and validate the results-only sources into football_history."
        )
    else:
        football_reason = "No verified results-history expansion source is available."
        football_next = "Find and verify results-history sources."

    decisions.append(ReadinessDecision(
        use_case="football_history_expansion_for_form_elo_replay",
        status=(
            CONDITIONAL if history["validated"] or results_sources else BLOCKED
        ),
        reason=football_reason,
        blockers=tuple(football_blockers),
        next_action=football_next,
    ))

    challenger_blockers = []
    if not history["validated"]:
        challenger_blockers.append("results_sources_not_yet_ingested")
    if not split_ready:
        challenger_blockers.append("chronological_split_contract_pending")
    if unresolved_sources:
        challenger_blockers.append(f"{unresolved_sources}_competitions_unresolved")

    if history["validated"] and split_ready:
        challenger_reason = (
            "The results-only football_history dataset is validated and the "
            "evaluation split is aligned to whole calendar dates. An isolated "
            "football-first challenger experiment can now be prepared without "
            "overwriting production models."
        )
        challenger_next = (
            "Prepare the football-first challenger dataset and offline experiment; "
            "keep production frozen and compare only on chronological holdouts."
        )
    else:
        challenger_reason = (
            "A football-first challenger remains conditional until both the "
            "results-only history and whole-calendar-date evaluation contract "
            "are validated."
        )
        challenger_next = (
            "Finish the remaining data/split blockers before any challenger training."
        )

    decisions.append(ReadinessDecision(
        use_case="football_first_challenger_model",
        status=CONDITIONAL if results_sources or history["validated"] else BLOCKED,
        reason=challenger_reason,
        blockers=tuple(challenger_blockers),
        next_action=challenger_next,
    ))

    return {
        "schema": 2,
        "baseline": {
            "raw_rows": int(rows.get("raw") or 0),
            "valid_finished_rows": int(rows.get("valid_finished") or 0),
            "trainable_samples": current_samples,
            "model_meta_samples": meta_samples,
            "baseline_reproducible": baseline_reproducible,
            "complete_1x2_pct": float(odds.get("complete_1x2_pct") or 0.0),
            "complete_ou25_pct": float(odds.get("complete_ou25_pct") or 0.0),
            "duplicate_fixture_keys": int(duplicates.get("duplicate_keys") or 0),
            "conflicting_fixture_keys": int(
                duplicates.get("conflicting_score_keys") or 0
            ),
            "whole_date_split_ready": split_ready,
        },
        "football_history": history,
        "coverage": {
            "missing_live_target_ids": missing_live,
            "missing_live_target_count": len(missing_live),
            "verified_results_history_sources": results_sources,
            "verified_odds_backed_gap_sources": exact_provenance,
            "unresolved_gap_sources": unresolved_sources,
        },
        "decisions": [decision.as_dict() for decision in decisions],
    }


def overall_status(report: dict) -> str:
    market = next(
        item
        for item in report["decisions"]
        if item["use_case"] == "expanded_current_25_feature_market_ensemble"
    )
    football = next(
        item
        for item in report["decisions"]
        if item["use_case"] == "football_history_expansion_for_form_elo_replay"
    )
    if market["status"] == READY and football["status"] == READY:
        return READY
    if football["status"] in {READY, CONDITIONAL}:
        return CONDITIONAL
    return BLOCKED
