from leagues.training_readiness import (
    BLOCKED,
    CONDITIONAL,
    NOT_NEEDED,
    READY,
    derive,
    overall_status,
)


def fixtures():
    training = {
        "rows": {
            "raw": 66699,
            "valid_finished": 66699,
            "derived_trainable_samples_after_5_game_warmup": 64218,
        },
        "odds": {
            "complete_1x2_pct": 99.94,
            "complete_ou25_pct": 58.06,
        },
        "duplicates": {
            "duplicate_keys": 0,
            "conflicting_score_keys": 0,
        },
        "coverage": {
            "configured_live_ids_missing_from_dataset": [
                1, 2, 3, 11, 13, 265, 292, 307, 848,
            ],
        },
        "provenance": {
            "present_fields": [],
            "fetcher_contract": {
                "actual_source": "football-data.co.uk",
            },
        },
        "training_contract": {
            "meta_n_samples": 64218,
            "direct_outcome_columns_in_features": [],
        },
    }
    coverage = {
        "missing_live_target_ids": [
            1, 2, 3, 11, 13, 265, 292, 307, 848,
        ],
    }
    sources = {
        "results_history_covered_count": 5,
        "odds_backed_covered_count": 0,
        "unresolved_count": 4,
    }
    return training, coverage, sources


def test_baseline_is_ready_but_same_corpus_retrain_is_not_needed():
    report = derive(*fixtures())
    by_name = {item["use_case"]: item for item in report["decisions"]}

    assert by_name["current_deployed_ensemble_baseline"]["status"] == READY
    assert by_name["immediate_same_corpus_retrain"]["status"] == NOT_NEEDED


def test_expanded_market_ensemble_fails_closed_without_odds_provenance():
    report = derive(*fixtures())
    by_name = {item["use_case"]: item for item in report["decisions"]}

    market = by_name["expanded_current_25_feature_market_ensemble"]
    assert market["status"] == BLOCKED
    assert "no_new_gap_source_has_verified_bookmaker_odds" in market["blockers"]


def test_results_history_can_move_forward_conditionally():
    report = derive(*fixtures())
    by_name = {item["use_case"]: item for item in report["decisions"]}

    football = by_name["football_history_expansion_for_form_elo_replay"]
    challenger = by_name["football_first_challenger_model"]
    assert football["status"] == CONDITIONAL
    assert challenger["status"] == CONDITIONAL
    assert overall_status(report) == CONDITIONAL


def test_ingested_history_and_whole_date_split_remove_stale_blockers():
    training, coverage, sources = fixtures()
    sources["results_history_covered_count"] = 6
    sources["unresolved_count"] = 3
    training["training_contract"]["derived_split"] = {
        "strategy": "whole_calendar_date",
        "train_calib_same_date_boundary": False,
        "calib_test_same_date_boundary": False,
    }
    manifest = {
        "dataset": "football_history",
        "source_class": "RESULTS_ONLY",
        "source_file_count": 65,
        "historical_cutoff_date": "2026-09-26",
        "market_training_eligible": False,
        "output_sha256": "abc123",
        "deduplication": {
            "unique_matches": 7775,
            "conflicting_duplicates": 0,
        },
        "coverage": [
            {"league_id": 1, "rows": 174},
            {"league_id": 2, "rows": 2022},
            {"league_id": 3, "rows": 935},
            {"league_id": 11, "rows": 1481},
            {"league_id": 13, "rows": 2150},
            {"league_id": 848, "rows": 1013},
        ],
    }

    report = derive(training, coverage, sources, manifest)
    by_name = {item["use_case"]: item for item in report["decisions"]}

    assert report["football_history"]["validated"] is True
    assert report["football_history"]["unique_matches"] == 7775
    assert report["baseline"]["whole_date_split_ready"] is True
    challenger = by_name["football_first_challenger_model"]
    assert "results_sources_not_yet_ingested" not in challenger["blockers"]
    assert "chronological_split_contract_pending" not in challenger["blockers"]
    assert "3_competitions_unresolved" in challenger["blockers"]
