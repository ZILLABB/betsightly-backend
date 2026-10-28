# Football VPS staging acceptance and protected production recovery

Updated 28 October 2026. This checklist distinguishes validated **synthetic
staging** from an unperformed **production-data restore**.

## Verified Render production source (read-only)

- PostgreSQL 18.4, database `betsightly_lik1`.
- 53 base tables in public; total DB size about 380 MiB on 28 October.
- Existing Render database is a writable primary on basic_256mb plan.
- Read-only SQL access here cannot produce a complete `pg_dump` archive.
- `pg_stat_user_tables.n_live_tup` counts are approximate and occasionally
  zero for nonempty tables: **never** use those estimates as restore parity.

No database credentials, customer data, raw ticket data, or extracts should
ever be committed or uploaded as GitHub Actions artifacts.

## What GitHub CI can test without production credentials

The `vps-staging-rehearsal.yml` workflow builds the actual backend Docker
image and starts a separate PostgreSQL 18 instance on an ephemeral Docker
network, with disposable fixture data only. It confirms:

1. API boots, responds on liveness and reports `web` role with no
   background jobs (no settlement/Telegram/daily workers started).
2. API can read the correct synthetic database and exactly three fixtures.
3. Container restart preserves DB data (process lifecycle recovery).
4. A stopped database rejects queries, restarts, and restores query access.
5. All test containers/networks are destroyed even when checks fail.

The test uses no production connection and no real NBA or football job
trigger. A GitHub hosted ephemeral runner is **not** a persistent staging VPS,
an availability SLO, or production-scale load benchmark.

## Protected production-data restore acceptance — NOT YET RUN

This requires a private connection to the source database from an
**owner-controlled** machine/host and an isolated encrypted offsite
destination. Do not send `DATABASE_URL` or access keys through chat/PRs.

1. Verify Render backup/download rights and source database version. Take a
   transactionally consistent PostgreSQL 18 `pg_dump --format=custom`
   using the approved least-privilege source role and encrypted connection.
2. Store checksum and size, archive and encrypted copy **outside Render**.
   Do not upload the private backup to this GitHub repository or ephemeral CI.
3. Provision a distinct empty PostgreSQL 18 database matching the
   `betsightly_restore_<unique_suffix>` guard with a different target URL.
   Confirm DB name and host *before* operating.
4. Run `scripts/vps/restore_drill.py` with `RESTORE_DATABASE_URL`; it
   refuses any existing user tables or a matching source target.
5. Compare exact per-table source/target row counts **at the same snapshot
   watermark**, schema identities and key unique constraints. Focus on
   published slips, manual bookmaker records, market decisions, final scores,
   daily runs and NBA booking settlement; never expose record contents in CI.
6. Test application read-only endpoints on the recovered DB in staging with
   all external side effects and writers disabled.
7. Verify restored archive from real offsite storage and a rollback drill.
   Require owner sign-off before DNS cutover, database writer fencing,
   turning on `writers` profile or deleting paid Render services.

## Still required

- Hardened real VPS host and TLS ingress
- Real S3-compatible private bucket, credentials with no delete rights,
  backup retention/alerts, remote re-download and **restore** verification
- Representative load test on selected VPS (GitHub CI is not representative)
- Production-data restore and exact source snapshot comparison
- Render legacy worker fencing (its heartbeat might not be instrumented)
- Private NBA research migration route and scheduler validation
