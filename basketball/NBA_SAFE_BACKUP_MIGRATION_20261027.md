# NBA staging backup recovery and safe migration

The isolated NBA research PostgreSQL database expires 24 November 2026, 22:14 UTC (23:14 WAT). It is separate from football production. Do not reuse any football database or change a football environment variable.

## Existing evidence

The authenticated private export stores the latest verified research archive and up to 600 saved bookmaker market receipts. Its SHA-256 checks and isolated SQLite restore drill protect against corrupted or inconsistent exports. This proves restoreability of that export, not a full live database clone or successful cloud migration. Historical job-run audit rows are not included in the export.

## No-cost verification before any target is provisioned

1. Export the latest NBA full backup from the private research admin. Keep an offsite copy that can be opened and whose SHA matches the admin receipt.
2. Run: python -m basketball.research_safe_migrate --backup /path/to/export.json
3. Confirm the output is dry_run_ok, shows the expected archive digest and receipt count, and does not connect to a remote database.

## Explicitly authorized move to a separate target

1. Provision an independent and empty PostgreSQL database approved by the owner. A persistent tier may incur a charge; do not create or upgrade one without consent.
2. Store the new connection URL locally as environment variable NBA_RESTORE_TARGET_DATABASE_URL, never as DATABASE_URL or a GitHub secret.
3. Run: python -m basketball.research_safe_migrate --backup /path/to/export.json --execute --confirm-sha256 THE_EXACT_BACKUP_SHA256
4. The utility rejects malformed or oversized backups, the source database identity, and a destination already containing tables; it verifies the imported archive and each market-receipt hash before committing.
5. Compare admin readbacks and future new finals on the new staging service before changing its target database. Keep the original archive and source as rollback evidence until accepted.
6. Confirm another new offsite backup and restore drill from the replacement source.

## Safety gates

Never mix isolated NBA research with football publications, calibration or customer records. No bookmaker codes or wagers are created by this operation. Do not claim any migration complete before an independent database has been provisioned and a signed post-restore readback has succeeded.
