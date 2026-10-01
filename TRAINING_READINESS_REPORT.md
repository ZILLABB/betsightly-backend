# BetSightly Training Readiness Report

Generated: `2026-09-27T12:30:20.758867+00:00`

Overall expansion status: **CONDITIONAL**

## Baseline

- Raw rows: **66,699**
- Valid finished rows: **66,699**
- Trainable samples: **64,218**
- Deployed model metadata samples: **64,218**
- Baseline reproducible: **True**
- Whole-calendar-date split contract ready: **True**
- Complete 1X2 odds coverage: **99.94%**
- Complete O/U 2.5 odds coverage: **58.06%**
- Duplicate fixture keys: **0**
- Conflicting fixture keys: **0**

## Football-history ingestion

- Validated: **True**
- Unique matches: **7,775**
- Covered missing-live competitions: **6**
- League IDs: `[1, 2, 3, 11, 13, 848]`
- Source files: **65**
- Historical cutoff: **2026-09-26**
- Conflicting duplicates: **0**
- Market-training eligible: **False**
- Dataset SHA-256: `36831c08c34d0ebd53dd8de70979e5d54a810b3575f0c75b5b11f200e2c1d40f`

## Expansion coverage

- Missing live competitions: **9**
- IDs: `[1, 2, 3, 11, 13, 265, 292, 307, 848]`
- Verified free results-history sources: **6**
- Verified odds-backed sources for those gaps: **0**
- Still unresolved: **3**

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

The isolated football_history dataset is validated with 7,775 unique results across 6 missing live competitions. It contains no bookmaker-odds claim and remains isolated from the production market-feature corpus.

Blockers:
- `3_live_competitions_still_unresolved`

Next action: Use football_history for form/Elo/replay experiments; keep the three unresolved competitions fail-closed until verified sources exist.

### CONDITIONAL — football_first_challenger_model

The results-only football_history dataset is validated and the evaluation split is aligned to whole calendar dates. An isolated football-first challenger experiment can now be prepared without overwriting production models.

Blockers:
- `3_competitions_unresolved`

Next action: Prepare the football-first challenger dataset and offline experiment; keep production frozen and compare only on chronological holdouts.

## Decision

Do **not** retrain or overwrite the deployed 25-feature ensemble yet.

The current market-feature model remains the frozen benchmark. The results-only `football_history` dataset may be used only for isolated form/Elo/replay and football-first challenger experiments.

The expanded market-aware model remains blocked until bookmaker-price provenance and market coverage are independently verified.
