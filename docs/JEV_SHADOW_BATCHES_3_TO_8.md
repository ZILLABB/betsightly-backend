# Jev External Intelligence: Batches 3–8 Implementation and Release Gates

Master tracker: [#240](https://github.com/ZILLABB/betsightly-backend/issues/240).
The code is **research-only**, and "merged" does not mean "provider-connected".

## Delivered in this change (source-tested, gated, NOT promoted)

| Batch | Implemented boundary | Acceptance still outstanding |
|---|---|---|
| 3 — Identity | Strict normalization + separate league maps (ESPN `ger.1`→OpenLigaDB `bl1`, `ger.2`→`bl2`), exact home and away, kickoff ±10 minutes, unique external ID, capture ≤12h and before kickoff. Ambiguous/unmatched evidence quarantined. | A live source/ESPN dual fixture match sample and source coverage report. Team aliases must be individually validated; unsupported competitions are intentionally blocked. |
| 4 — Jev adapter | Vercel AI Gateway `POST /v1/evaluate`; model `typesafe-ai/jev-1.14.0`; typed choice `supported/conflicted/insufficient` and Boolean probability `requires_human_review`; strict response and 16KiB state/64KiB reply/7s timeout. No prose decisions or sports probability replacement. | Real account/key/quota verification and one authorized staging API call. A process-local 24 call/day cap alone is **not** a distributed billing budget; use a one-worker stage and provider spending limit. |
| 5 — Idempotent shadow research | First-write-wins SQLAlchemy ledger. Claim is inserted before network request, unique hash combines model version and evidence fingerprint; status summary cannot reveal raw source text. Staging-only optional bounded worker, fixed-source matchday configuration and non-blocking daily scheduler hook. | An actually configured **cloud staging worker/cron** and DB migration/access acceptance; current staging job hook fires only when stage daily scheduler runs. No promise of 24/7 automatic checks until deployed and monitored. |
| 6 — Outcomes | Independent pure evaluation report on individually verified settled market outcomes, baseline Brier/log-loss, supported/withheld coverage, false-withhold winners and per-market results. No accuracy claim and no promotion for insufficient samples. | 300+ prospectively scored real settled cases, held-out performance and policy review. |
| 7 — Basketball | Separate private research adapter with original before-tipoff NBA forecasts, exact fixture identity, competition/market allowlist and evidence as-of gating. | Live private NBA deployment integration and independent trusted injury/lineup data; WNBA/NCAA/international leagues remain unaccepted. |
| 8 — Ops | Protected `GET /api/leagues/jev-shadow/status` with aggregate ledger + access posture, no keys/raw evidence; production runtime provider calls unconditionally disabled, publication authority always false. | Actual admin UI page, source health alert delivery, canary, verified rollback and any user-approved publication hold logic. |

## Flags and security boundaries

The flags below are **not set by this change**; the default is safe.

- `BETSIGHTLY_JEV_SHADOW_ENABLED=true` declares shadow readiness.
- `BETSIGHTLY_JEV_API_CALLS_ENABLED=true` is an additional explicit provider-traffic switch.
- `AI_GATEWAY_API_KEY` is a **server-only secret**; never place it in the Vite frontend, PRs or logs.
- `ENVIRONMENT=staging` is required by the scheduled worker; production blocks Jev traffic unconditionally.
- `BETSIGHTLY_JEV_WORKER_ENABLED=true` opts in to a detached staging tick after weekly board preparation.
- `BETSIGHTLY_EXTERNAL_FOOTBALL_ENABLED=true` allows the pre-existing OpenLigaDB keyless endpoint; no public request handler fetches it.
- `BETSIGHTLY_JEV_SOURCE_MATCHDAYS=bl1:2026:8;bl2:2026:8` configures a fixed allowlisted fixture group, season and matchday.
- `BETSIGHTLY_JEV_SOURCE_AUTODISCOVER=true` allows **opt-in** lookup of the current OpenLigaDB group for `bl1` and `bl2` when the explicit list is empty; the resulting fixtures must still independently match ESPN identity and kickoff. It requires all existing staging, source and Jev switches to be enabled.

The Jev decision output is **not** itself an authority to approve/reject picks, change publication gates, create SportyBet tickets or score a fixture. The existing authoritative `leagues/publication_policy.py` gates remain in place.

## Source rights and quality

Existing ESPN fixtures/BetSightly Elo/calibration/SportyBet provide the first-party model context. OpenLigaDB is community-maintained, ODbL-attributed evidence, never directly a verified full-time settlement. Official injuries/news, independent model articles, and bookmaker comparisons still require per-source rights assessment, timestamped snapshots, provenance and conflict/duplication tests before adapter implementation. Web scraping should be selective, permit-compliant and avoided when an authorized API/feed exists.

## Live validation attempts and provider access

The source API was not reachable from this execution environment during authoring. **Offline fixture normalization and tests are not a live production source-coverage measurement.** No Jev account or Gateway key was supplied; no paid calls were made and provider balances were not verified.

The external intelligence platform is technically prepared for staging experiments, but **is not closed out for live prediction-quality improvements**. The only sound go/no-go rule is prospectively measured improvement without unacceptable false withholding, validated on fixed settled labels and with rollback.
