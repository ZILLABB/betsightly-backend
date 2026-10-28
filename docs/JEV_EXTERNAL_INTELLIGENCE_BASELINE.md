# Jev / External Intelligence — Batch 1 baseline (2026-10-28)

Master plan: [Issue #240](https://github.com/ZILLABB/betsightly-backend/issues/240). This note describes **observed code and unverified items**. It does not claim Jev has run in production.

## Existing football system (verified by source-code inspection on `devil`)

- `leagues/engine.py`: ESPN league fixtures, SportyBet board and prices, competition base rates, ELO, Poisson/predictor, model ensemble, calibration, isolated football-first shadow outputs, seven-day prepared pipeline cache.
- `leagues/publication_policy.py`: model return, safe-tier evidence, conservative probability, trust grade, real bookmaker prices, kickoff and market restrictions.
- `leagues/fixture_ranker.py`, `leagues/recommendation_board.py`: canonical market rankings and model recommendation classifications.
- `leagues/scheduler.py`: 08:00 WAT frozen daily publication and before-publication settlement/recalibration steps.
- `leagues/booking.py`, `leagues/sportybet.py`: independent real sportsbook selection identity, readback and code validation.
- `basketball/README.md`: documents an NBA data/model pipeline; documentation alone is **not proof of live, reconciled NBA/WNBA/NCAA/international model readiness**. Check the isolated private NBA research deployment before adapting.

## Jev provider feasibility

- Vercel announced pinned `typesafe-ai/jev-1.14.0` October 15, 2026 and documents the HTTP Gateway contract `POST https://ai-gateway.vercel.sh/v1/evaluate`, using `state` and typed questions.
- Jev is a **decision classifier/scorer**: it does not browse for injuries, fetch scores, or explain a full sports analysis. Model confidence is **not** a sports market probability.
- Provider-published reference price via AI Gateway: $0.04 per million input tokens; usage credits, team entitlements, quota and existing Jev history **have not been verified**. Budget must be capped before sending paid calls.
- Backend direct TypeSafe access versus Gateway is not chosen until a server-side credential and source policy are confirmed.
- Indexed code searches for Jev, TypeSafe and AI Gateway did not identify a current BetSightly integration. The connected Vercel frontend project lists no Jev or Gateway key. **This does not verify the private Render backend secrets or a separate TypeSafe account.**

## Evidence contract v1

`leagues/jev_evidence_contract.py` is safe to import from the existing Python backend without additional packages. It is currently **pure, disconnected and disabled by default**.

- `shadow_readiness()` reports a **status and booleans**, never credentials. Enabling is future work and must require an explicit server-only key.
- `evidence_envelope(pick, observations, sport, as_of)` accepts one selection at a time. Each observation must include `type`, `source_id`, HTTPS `source_url`, `observed_at`, and `claim`.
- No post-kickoff or post-as-of information may enter the state; no bookmaker/private fixture JSON is forwarded.
- Distinct third-party opinions are kept separately; repeats from the same source and claim are deduplicated; evidence is deterministically hashed for idempotency.
- No external network calls, scraper, background job, database mutation, Jev evaluations, publication replacements or score settlements are added in Batch 1.

## Baseline safety and next implementation gates

1. Verify live Render env **key presence only**, if a private Jev TypeSafe or Gateway account exists, without copying/decrypting secrets.
2. Enumerate selected external source endpoints and written usage policy; prioritize free APIs and official source feeds. Scrape only with permitted access, bounded rate/caching and source evidence URLs.
3. Build source-specific parsers and test cross-source fixture/team identity before any Jev calls.
4. Add Jev HTTP adapter with strict typed response parser, operation timeout, retry/backoff, budget/rate limit, no-key fallback and job-level idempotency; keep it shadow-only.
5. Require retrospective/prospective held-out validation against verified finals before enabling any prepublication hold action. Preserve current deterministic hard gates and official immutable score history.
