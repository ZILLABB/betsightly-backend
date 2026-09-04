# ADR: Historical replay evidence remains isolated from production trust

**Status:** Accepted for Phase 2A  
**Date:** 2026-09-04

## Context

Live BetSightly settlement samples are too small for most Builder markets. Two
historical sources contain substantially more outcomes, but neither preserves
historical ELO snapshots and their provider identities overlap imperfectly.

## Decision

Replay the shared deterministic `leagues.predictor.predict` path using only
pre-match de-vigged odds and league results strictly before each fixture.
Process an entire date before updating history. Label rows `MARKET_REPLAY`,
`DERIVED_REPLAY`, or `INSUFFICIENT`; no row is `FULL_REPLAY` without honest
historical ELO/ML state. Persist aggregate evidence under `data/replay/` and
expose a read-only Python reader that explicitly reports
`production_active=False`.

Cross-source rows are merged only when normalized home, normalized away, date,
and final score agree. Both source row IDs remain in provenance. Competition
labels are not identity keys because one provider uses codes such as `E0`
where another uses display names such as `Premier League`.

## Consequences

- Phase 2A cannot change Builder eligibility or published probabilities.
- All recommendations remain provisional until Phase 2B reviews league,
  recency, bookmaker and live evidence together.
- Historical ML and ELO comparison remains unavailable without reconstructing
  their chronological states.

## Future unmatched-provider registry

Use an Alembic-managed table keyed by provider and provider event ID, holding
raw/normalized teams, raw/canonical competition, kickoff, squad type, matching
stage, bounded failure category, best candidate identity/evidence, first/last
seen timestamps, occurrence count and explicit resolution status. Candidate
matches must never automatically create aliases. Expose only aggregate counts
and sanitized candidates through an API-key-protected diagnostic endpoint.
