# NBA cloud hosting boundary — BetSightly VPS Mega Batch 1

**Read-only inventory, 28 Oct 2026. No NBA migration or new background
scheduler is authorized or activated by the football VPS draft PR.**

## Existing separate assets

| Component | Observed place | Operational rule |
| --- | --- | --- |
| Production football API | Render `betsightly-api`, branch `devil` | Remains original production writer and router until cutover |
| Football staging | Render `betsightly-backend`, free instance | Not a reliable always-on production substitute |
| NBA stage backend | Render `betsightly-nba-research-stage-20261025`, branch `stage1/nba-private-research-20261024` | Independent staging only; its source is not the football VPS Compose |
| NBA research database | Isolated Supabase project `efhnyanzcqsdbqmyeuec` | Keep separate from football PostgreSQL |
| NBA schedule endpoint | Vercel project `betsightly-nba-stage-scheduler` | Existing deployment reported READY, which does not prove cron invocations |
| NBA backup endpoint | Vercel project `betsightly-nba-private-backup-v2` | Existing deployment reported READY, not proof of a successful backup readback |
| Laptop research job | Windows Task Scheduler / local private NBA lab | Unattended operation is not possible while the laptop is off |

The **football** `growth/basketball_scheduler.py` is a bookmaker settlement
tick, not the isolated NBA research forecast lifecycle. Do not assume
renaming or moving the football scheduler migrates the private NBA work.

## Evidence and blockers

The NBA source branch already contains `docs/NBA_RESEARCH_BATCH_ACCEPTANCE_20261027.md`
and `basketball/NBA_SAFE_BACKUP_MIGRATION_20261027.md`.
The former records an unresolved `NBA_MIGRATION_HTTP_404` for a signed
`compare` route, and explicitly forbids promoting a target without
source/target parity proof. The latter describes incomplete export
coverage and a requirement for a separate, clean target with hash readback.
Neither is fixed by the football VPS Docker build.

Some older NBA documentation describes *historical* readiness and should not
be treated as present live runtime proof. READY Vercel deployments are not
equivalent to proof that scheduled functions are firing with valid secrets.

## Gate sequence before optional NBA consolidation

1. Capture the currently deployed NBA stage commit and the Vercel cron and
   secret *configuration metadata* without exposing secret values.
2. Resolve the signed NBA migration compare 404 and prove source and target
   research counts, dates and hashes against an isolated staging database.
3. Prove exactly one before-tipoff forecast writer and one verified-final
   reconciliation scheduler through separate archival readbacks.
4. Verify actual private offsite NBA export, archive and audit log coverage,
   restored into an independent empty database without overwriting Supabase.
5. Run scheduled research and settlement from a continuously available
   service, with observation of failures and missed-run catchup over a soak
   period, before disabling any existing Vercel or laptop job.
6. Keep football and NBA secrets, schemas, worker identities and backup
   prefixes completely isolated. Any future shared hardware still requires
   separate Postgres credentials, volumes and failure alerts.

**Current decision: NOT READY TO MERGE NBA RESEARCH INTO FOOTBALL VPS.**
The VPS preparation PR must not connect to NBA production/staging Supabase
or modify its Vercel schedules.
