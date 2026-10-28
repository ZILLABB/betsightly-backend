# BetSightly VPS migration — Mega Batch 1 candidate

**Status:** candidate only; no live VPS, traffic cutover, database move, or Render change.
**Source branch:** `devil`, baseline `e00b7d9` (2026-10-28).
This bundle uses role ownership already present in `main.py` and
`run_background.py` rather than creating a second scheduler system.

## Process layout

| Container | Role | Jobs |
| --- | --- | --- |
| api | web | ASGI routes only, no background jobs |
| publication | publication | Daily generation, growth, booking refresh, basketball booking-ledger tick |
| settlement | settlement | Football results/settlement checker |
| telegram (opt-in profile) | telegram | Telegram polling |
 
The compatibility roles `worker`, `scheduler`, and `all` retain their
existing semantics. `scheduler` currently **also owns settlement** for
backward compatibility; do not use it simultaneously with `settlement` on
the same database. **Exactly one** VPS publication and settlement role may run.

NBA research forecasting is **not** migrated by this compose file. The separate
Supabase and Vercel NBA research scheduler remain as-is pending a dedicated
inventory, consistency proof, and approved migration.

## Dry-run instructions (no production connection)

1. Make a disposable copy of `.env.vps.example` named `.env.vps`.
2. Run `docker compose --profile writers --profile telegram --env-file .env.vps -f compose.vps.yml config --format json > /tmp/betsightly-vps-compose.json`.
3. Run `python -m scripts.vps.validate_compose /tmp/betsightly-vps-compose.json`.
4. Run `python -m pytest tests/test_process_roles.py -q`.
5. Delete the example-derived `.env.vps`. Never deploy the example values.
6. Optionally build the image in an isolated test environment with
   `docker compose --env-file .env.vps -f compose.vps.yml build`.

Docker Compose is deliberately **not** auto-deployed from this PR.
The API binds to **127.0.0.1:8000**, and no database is deployed inside
the stack. TLS ingress and an approved secure remote PostgreSQL connection
must be configured separately. Never expose PostgreSQL or Redis to 0.0.0.0/0.

## Before any real start

- Provision a VPS, harden SSH/OS firewall, set TLS proxy with domain,
  set up off-server backups and prove restore in an isolated database.
- Supply production secrets via server-owned `.env.vps` or supported
  secret manager (file permissions 0600), and validate trusted origins.
- Confirm roles and image match the approved production commit, CI is green,
  and the production stateful artifacts and caches have been audited.
- Default `docker compose up` includes **API only**; writer profiles are opt-in.
- The process also refuses to start dedicated VPS writers without explicit
  `BETSIGHTLY_VPS_WRITER_ACTIVATION=render-fenced-and-approved`. This is
  a human authorization gate, not a technical proof of fencing.
- **Do not connect publication, settlement or Telegram to the existing
  production database while Render's corresponding roles are active.**
  For staging, use isolated PostgreSQL and disable external writes/notifications.
- Use `docker compose --env-file .env.vps -f compose.vps.yml up -d api`
  for API-only validation against a disposable database.
- The `telegram` service needs `--profile telegram` and must not be started
  until Render's polling owner is fenced and bot credentials are present.
- Before any activation, independently verify the legacy Render `all` role
  is stopped: the Render Gunicorn application does **not** publish heartbeats
  through `run_background.py`, so the new heartbeat monitor **cannot**
  reliably detect its presence or guarantee absence of dual-writers.
- On cutover, stop old writers or fence their leases, perform final sync,
  change API traffic only after health and integrity checks pass.

## Scope remaining in Mega Batch 1

This PR proves the role split/config skeleton **only**. Still required:
worker heartbeat freshness monitoring and alerting; recovery against
missed settlement intervals; E2E and load testing; off-site backup
automation and restore verification; full NBA research inventory;
source/VPS branch reconciliation; CI images and staged deployment
pipeline; application error budget validation. A green configuration
test is not production acceptance.

## Rollback principle

Do not run two writable scheduler/settlement stacks at once.
For a reversal: disable VPS writers and confirm they have stopped,
restore/read-reconcile DB authority, then re-enable the Render workers.
Switch API routing back independently and confirm score/booking
idempotency and worker freshness. Retain independent backups.

## Worker thread death supervision

For dedicated VPS roles only, the runner checks its expected background
thread after a 90-second startup grace period and every 30 seconds thereafter.
If the thread exits, it exits nonzero and Docker's restart policy restarts
that service. This does **not** detect a stuck-but-alive thread or guarantee
publication freshness; add external, database-backed age-of-last-success
alerts before production acceptance. The existing Render legacy roles
are intentionally unaffected by this new supervision behavior.

## Database heartbeat and ownership monitoring

The existing `runtime_process_heartbeats` table already records role and
capability ownership. A **separate**, read-only monitoring process can run:

`DATABASE_URL=... python -m scripts.vps.check_worker_freshness --stale-seconds 120`

Add `--require-telegram` only if the optional Telegram profile is enabled.
A healthy exit code is **0**; missing/duplicate/stale/overlapping ownership or
monitoring failure returns **2** and sanitized JSON. The check observes
**only reporting workers**; it cannot detect an uninstrumented legacy Render
API process that still runs a scheduler or the actual success of each job. Run this on a schedule
outside the application/worker containers and wire the nonzero exit to an alert.
It requires the proper application database and Python dependencies.
It refuses SQLite and does not create or modify tables. Never point this
at the Render production database alongside active VPS writers.
A fresh heartbeat only proves the worker loop is running; it does **not**
prove the last successful fixture update, publication or settlement.
End-to-end job-success freshness alerts remain a separate acceptance gate.

## Database backup preparation (no automatic production backup enabled)

`DATABASE_URL=... python -m scripts.vps.backup_postgres --output-dir /srv/betsightly-backups`

Requires PostgreSQL client tools `pg_dump` and `pg_restore`, and a suitable
`pg_dump` version (18+ for football PostgreSQL 18). Creates a private
custom-format dump and SHA-256 manifest; uses PostgreSQL connection variables
to keep the password out of process arguments. The connection defaults to TLS
`sslmode=require` unless `verify-ca` or `verify-full` is specified.
The manifest status `archive_verified_not_restore_tested` is deliberate:
`pg_restore --list` is **not** a full restore test. Verify the checksum,
copy to encrypted off-host storage, then restore to an independent
**empty disposable** database and compare row counts/check constraints before
trusting it. Do not use `--clean` against a production database. No automated
production cron, cloud backup upload or restore has been activated.

## Guarded database restore rehearsal

Provision an **existing, empty, isolated** PostgreSQL database named
`betsightly_restore_<8+ lowercase characters or digits>`, outside the
production application. Use a different database than `source_database`
in the manifest and set `RESTORE_DATABASE_URL` to this disposable target.
It must use TLS and a separate restricted credential.

`RESTORE_DATABASE_URL=... python -m scripts.vps.restore_drill --archive /srv/betsightly-backups/ARCHIVE.dump --manifest /srv/betsightly-backups/ARCHIVE.json`

The script checks the archive SHA-256, file length, manifest identity,
target database name and empty schema before it will restore.
It intentionally refuses database creation/deletion, `--clean`, and
existing user tables, and performs a single-transaction pg_restore.
A successful restore confirms that the archive can be loaded into the
disposable database; **it does not prove application-level row counts,
booking consistency or settlement correctness**. These must be compared
against source snapshots separately before production cutover.

## Optional encrypted off-site storage (NOT activated)

The `scripts.vps.backup_and_upload` command first creates a private
PostgreSQL archive using `pg_dump`, validates the local SHA-256 manifest,
then uploads both archive and manifest to an **operator-supplied**
S3-compatible bucket with `aws s3 cp --sse AES256`. It performs
remote `head-object` checks for size, metadata digest and SSE encryption.
It never deletes or prunes remote backups. A verified HEAD is not a
restore test and does not establish multi-region availability.

Only install `deploy/vps/betsightly-backup.service` and
`deploy/vps/betsightly-backup.timer` after provisioning. The VPS must
have the PostgreSQL 18 client, AWS CLI v2, Python app dependencies,
a restricted `betsightly` system user, an off-host private bucket with
versioning and lifecycle retention, and a locked-down
`/etc/betsightly/backup.env` (mode 0600). Required environment variables:
`DATABASE_URL`, `AWS_S3_BACKUP_BUCKET`, `AWS_S3_BACKUP_PREFIX`,
AWS CLI identity credentials and optional `AWS_S3_ENDPOINT_URL` (HTTPS
only, never userinfo). Only use backup credentials with write+head
permissions for the chosen bucket prefix; object deletion is not needed.

The timer is **only a template**, not enabled by CI. It schedules an
encrypted backup every night at 02:15 UTC (03:15 Lagos time), with up to
15 minutes randomized delay. Monitor service failures and verify recovery
from actual uploaded archives periodically before trusting the system.

## Daily publication result monitor (read-only)

The separate `scripts.vps.check_daily_publication` command checks the
persisted `daily_runs` row for the current **WAT** publishing day.
After the 08:00 WAT publication time plus a default 90-minute grace period,
it requires `status=complete`, a successful `card` step, and no failed
recorded steps. Before that deadline, it reports a neutral healthy state.
If incomplete after the deadline, it exits code 2 and prints only sanitized
JSON. The monitor cannot guarantee the number or quality of published
tiers and does **not** call prediction APIs or make database writes.

On a dedicated monitoring host:
`DATABASE_URL=... python -m scripts.vps.check_daily_publication --grace-minutes 90`

Run this separately from the publication process and connect exit code 2
to a configured alert recipient. Repeated failures should be deduplicated
by the alert delivery service. Confirm every calendar day is intended to
publish before enforcing this gate in production.
