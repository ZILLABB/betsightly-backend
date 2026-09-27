# BetSightly Training Readiness Report

Generated: `2026-09-27T11:15:34.270853+00:00`

Overall expansion status: **CONDITIONAL**

## Baseline

- Raw rows: **66,699**
- Valid finished rows: **66,699**
- Trainable samples: **64,218**
- Deployed model metadata samples: **64,218**
- Baseline reproducible: **True**
- Complete 1X2 odds coverage: **99.94%**
- Complete O/U 2.5 odds coverage: **58.06%**
- Duplicate fixture keys: **0**
- Conflicting fixture keys: **0**

## Expansion coverage

- Missing live competitions: **9**
- IDs: `[1, 2, 3, 11, 13, 265, 292, 307, 848]`
- Verified free results-history sources: **5**
- Verified odds-backed sources for those gaps: **0**
- Still unresolved: **4**

## Readiness by use case

### READY — current_deployed_ensemble_baseline

The current 66,699-row corpus reproduces the deployed 64,218 trainable samples exactly and has no duplicate/conflicting fixture keys or direct outcome columns in the feature list.

Next action: Keep as the frozen benchmark; do not overwrite it while expanding data.

### NOT_NEEDED — immediate_same_corpus_retrain

Retraining the same unchanged corpus would not address the identified coverage or provenance gaps.

Next action: Do not spend compute retraining the same 64,218 samples.

### BLOCKED — expanded_current_25_feature_market_ensemble

The current ensemble depends on bookmaker-price features. The expanded competitions do not yet have verified odds-backed history, and the legacy corpus cannot prove row-level price timing/source.

Blockers:
- `legacy_rows_lack_exact_row_level_provenance`
- `ou25_price_coverage_is_partial`
- `no_new_gap_source_has_verified_bookmaker_odds`
- `live_competition_coverage_gap`

Next action: Build an odds-backed market_training dataset with explicit source/snapshot provenance before any expanded retrain.

### CONDITIONAL — football_history_expansion_for_form_elo_replay

Verified free results-history sources exist for 5 of 9 currently missing live competitions. They can improve football history without pretending bookmaker odds exist.

Blockers:
- `4_live_competitions_still_unresolved`

Next action: Ingest the verified results-only sources into a separate football_history dataset and keep unresolved competitions fail-closed.

### CONDITIONAL — football_first_challenger_model

A football-first challenger can use verified results/form/ELO history without requiring bookmaker odds, but the new sources have not yet been ingested and validated.

Blockers:
- `results_sources_not_yet_ingested`
- `4_competitions_unresolved`

Next action: After results-only ingestion, train an isolated challenger with league-aware chronological evaluation; never overwrite production models.

## Decision

Do **not** retrain or overwrite the deployed 25-feature ensemble yet.

The current model remains the frozen benchmark. The next implementation phase should ingest verified results-only sources into a separate `football_history` dataset, while a separate `market_training` dataset remains restricted to rows with explicit bookmaker-price provenance.

Only after those datasets are validated should BetSightly train isolated challenger models and compare them against the current baseline on chronological holdouts and live shadow performance.
