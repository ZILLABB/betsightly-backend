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
2. Run `docker compose --profile telegram --env-file .env.vps -f compose.vps.yml config --format json > /tmp/betsightly-vps-compose.json`.
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
- **Do not connect publication, settlement or Telegram to the existing
  production database while Render's corresponding roles are active.**
  For staging, use isolated PostgreSQL and disable external writes/notifications.
- Use `docker compose --env-file .env.vps -f compose.vps.yml up -d api`
  for API-only validation against a disposable database.
- The `telegram` service needs `--profile telegram` and must not be started
  until Render's polling owner is fenced and bot credentials are present.
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
