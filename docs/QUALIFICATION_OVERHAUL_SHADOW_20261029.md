# BetSightly consolidated prediction-qualification overhaul

**Status:** implementation and tests on an isolated research branch; not deployed, not a change to official publication or pricing policy.

## Existing merged foundations to preserve

- PR #251: precise 08:00 WAT generator boundary.
- PR #252: real rejection-reason counts.
- PR #253: detailed cup-supply visibility, including Copa del Rey.
- PR #254: explicitly evidence-qualified domestic-cup allowance for 5 Odds and 10 Odds; other products remain strict.
- Current official publication policy, real SportyBet quotes, one-fixture-per-slip, booking-code verification, and locked cards **remain unchanged**.

## Four coordinated workstreams

1. **Evidence and settlement.** The immutable `prediction_board_snapshots` table already captures pre-match candidate markets, including rejected candidates. Add a separate verified-final export and use `score_complete_forecast_pool` to label every uniquely identifiable candidate. Exact competition, fixture ID, regulation score, captured-before-kickoff, final-after-kickoff and kickoff identity are compulsory. Any conflicting finals or DNB pushes stay unscored. The preexisting manual review queue supplies source/competition diagnosis; do not mark 90 overdue manual records settled without verified evidence.
2. **Conservative filter calibration.** Run market-specific, date-separated Brier and log-loss comparisons of the original frozen conservative probability, a diagnostic half-reduced penalty, and original calibrated probability. The comparison is read-only. Do not tune on the holdout, retroactively rewrite probabilities, use publish-only outcomes, or promote a market with fewer than 100 held-out verified labels across 7 distinct kickoff days. After adequate samples, require independent forward validation and review before a separately approved versioned policy change.
3. **Accumulator allocation.** Take *independently qualified* Banker, 2 Odds, 5 Odds, 10 Odds, Over Goals and Rollover proposals; quantify fixture reuse at caps 1, 2, 3. The existing 4-order greedy comparison is not a full portfolio optimizer. The shadow report makes the cost visible but deliberately does not substitute unsafe fixtures or lift an official exposure cap. The subsequent integrated optimizer must work from the same real-price eligible pool, enforce one fixture per slip, exact booking, and evaluate every 6-product portfolio before publication.
4. **Cup and weekday coverage.** Keep the existing cup diagnostic from PR #253, and compare its fixture/price/identity/history attrition with *verified settled cup observations*. No competition name alone establishes a supported fixture; no postponed kickoff or cross-tournament ID can silently inherit another final.

## Offline runner

```bash
python -m scripts.audit_qualification_overhaul \
  --snapshots snapshots.json \
  --finals verified_regulation_finals.json \
  --portfolio independent_tiers.json \
  --review-queue review_queue.json \
  --output qualification_shadow_report.json

python -m pytest -q tests/test_qualification_overhaul_shadow.py
```

Required `snapshots.json` is an array of:
```json
[{
  "snapshot_id": "original SHA256",
  "generated_at": "2026-10-26T06:00:00Z",
  "candidates": [{
    "fixture_id": "source-aware canonical id",
    "league_slug": "esp.copa_del_rey",
    "kickoff": "2026-10-26T18:00:00Z",
    "market": "over_1_5",
    "calibrated_probability": 0.78,
    "conservative_probability": 0.65,
    "odds": 1.80,
    "odds_source": "SportyBet",
    "bookable": true
  }]
}]
```
For archive exports, `generated_at` MUST come from the immutable database row, not be inferred from the publication date. The existing compact archive can be expanded by a **new versioned schema** to store `competition_type` for direct cup segmentation; older compact rows report UNKNOWN until a verified registry join.

Required `verified_regulation_finals.json` is an array of rows with identical canonical `fixture_id`, `league_slug`, `kickoff`, `status: FINAL`, `period: REGULATION`, integer `home_score` / `away_score`, `verified: true`, `verified_at`, `source` and immutable `source_event_id`. These fields are **not** sufficient proof by themselves: validate with the existing licensed/permitted final-score reconciliation before export. Conflicting or ambiguous records are quarantined by the scorer.

`independent_tiers.json`: object mapping each of the six product names to proposed leg arrays containing `fixture_id`. This is a diagnostic, **not** new alternative selection or bookmaker confirmation.

`review_queue.json`: the existing read-only manual-settlement review API response, including `total_pending_legs`, `overdue_48h` and `legs`. A truncated queue cannot be presented as a complete settlement audit.

## Acceptance and blockers

- The Render football API and database were both reported `suspended` for billing at 2026-10-29 07:53 UTC; real settlement, export, live shadow comparison, and deployment acceptance cannot be claimed while unavailable.
- Re-run with actual independently verified finals and fresh source snapshots after restoration. Measure 5 Odds **3/15** and 10 Odds **4/15** as baselines, tracking true booking-code verification and subsequent settled accuracy, not publication count alone.
- **No automatic relaxation or release.** Any later live experiment requires versioned evidence, cohort review, rollback and same-day booked-ticket preservation.
