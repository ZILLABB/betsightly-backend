# NBA research: large-batch acceptance runbook (2026-10-27)

**Boundary:** staging basketball only. Football production untouched. Render source remains primary until signed acceptance evidence passes. Never place credentials or database URLs in issue comments, logs or artifacts.

## Batch 1 — Fix migration HTTP 404; establish source/target parity
1. GitHub Actions run `40573877411`, job `122435007659`, signed `compare` action failed `NBA_MIGRATION_HTTP_404`. Offline migration unit tests passed. This is a live HTTP failure, **not** proof of equal databases.
2. The source route is `POST /api/growth/internal/nba-research/github-oidc-migration`; route should mount in isolated staging with `ENVIRONMENT=staging` and `NBA_PRIVATE_DATABASE_ONLY=1`. The existing route-isolation test previously asserted the ordinary OIDC route but not migration; new regression assertion adds the missing contract.
3. Inspect Render staged deployment commit and its environment flags and startup logs; verify the public staging URL serves the **correct deployment**. Distinguish router-not-mounted 404 from intentionally concealed authorization 404 via private server logs; do not weaken authentication or expose diagnosis to unauthenticated callers.
4. Re-dispatch signed read-only `compare` on `dev` only after correct deployment; store sanitized acceptance receipt and row/date/digest watermarks. If it fails, **STOP**.
5. Keep the original `DATABASE_URL`, `NBA_USE_RESTORE_TARGET_AS_PRIMARY=0`. Never rerun restore into populated target unless target-state guard explicitly approves.

## Batch 2 — Private write/readback, scheduler and backup
- Pause new source writes, reconcile final archive and audit-history watermarks, then prove a single idempotent research write/readback to target with a rollback-safe transaction.
- Run one forecast and one independently verified final with source identifiers and event timestamps; prove no football routes/tables exist and no accidental public publishing.
- Independently export encrypted backup, verify digest and restore into disposable isolated DB. Preserve at least one off-provider copy and document retention.
- Exercise one-writer scheduler ownership and failback to Render in a staging-only drill. Do not assume Supabase Free includes ongoing backups or guaranteed uptime.

## Batch 3 — NBA intelligence and markets
- Chronological, pretipoff-only feature extraction: injuries, minutes, lineups, pace, rest, opponents and closing-line snapshots with provenance and missingness.
- Separate out-of-time scorecards by model and season (Brier/log loss/calibration, bootstrap confidence ranges).
- Explicit bookmaker market identity and price TTL, push/void/OT/period settlement semantics; fail-closed exact leg readback; no unsupported player prop auto-release.

## Batch 4 — Other leagues and operations
- WNBA/NCAA adapters remain independent read-only candidates until coverage, identity and finals validation; EuroLeague/EuroCup/NBL follow only with independent historical evidence and provider terms review.
- Dashboard: last run, source freshness, delayed verified finals, stale forecasts, backup age, per-league status and alert thresholds.
- Require continuous 7-day unattended private research soak, replay-safe jobs and a written go/no-go decision before public predictions.

**CI success ≠ deployment success ≠ statistically validated prediction engine.** No calibration claim based on the restored 16 finalized NBA games.
