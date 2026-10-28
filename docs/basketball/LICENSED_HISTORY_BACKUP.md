# Six-league licensed history: separate private recovery acceptance
28 October 2026 · NBA staging only

## What is included

The licensed-history backup is **not** the existing NBA V2 full research
backup. It uses a distinct private Blob key namespace,
`basketball-licensed-history-v1/`, and has an independent source-freshness
acknowledgement.

The saved envelope includes exactly these four source tables:

1. `nba_research.basketball_data_rights`: grant scopes, expiration and
   evidence **hashes** (not full licensing contracts).
2. `nba_research.basketball_licensed_imports`: immutable manifest and batch
   provenance.
3. `nba_research.basketball_licensed_games`: archived authorized finished
   games by provider and league.
4. `nba_research.nba_league_source_probes`: numeric-only candidate
   source-availability receipts.

Backup ACKs are stored in the fifth table
`nba_research.basketball_history_backup_receipts` and are not part of
the exported copy, because the acknowledgement happens only after the
uploaded data is read back. The next daily backup reflects any changes
to the other four tables. The existing NBA V2 backup continues its
separate signed snapshot/market/job archive and remains independently
required for recovery.

The current Vercel scheduled worker uses the existing cron and private
Blob token. It uploads and byte-for-byte reads back the NBA V2 archive,
ACKs that archive, then independently uploads and ACKs this four-table
history snapshot. A failure in the new copy reports failure but does
**not** erase or undo the previously saved NBA V2 object.

## Production restrictions

- The two export/ACK routes use the existing independent
  `NBA_BACKUP_JOB_TOKEN` with the research-only environment gate.
  No admin cookie can replace it.
- The admin-only backup health endpoint is
  `/api/growth/admin/nba-research/licensed-history-backup-health`.
- **Never** log Blob URLs, tokens, private grants, match scores, or raw
  JSON archives. The offsite object is private but not application-layer
  encrypted; use a storage encryption/key-management review before
  retaining highly confidential commercial agreements or personal data.
- SHA-256 plus schema validation detects corruption, accidental truncation
  and inconsistent records. Unkeyed SHA-256 is not a cryptographic
  proof of origin or an external rights approval.
- Source game rows are bounded to 75,000 per table and a maximum raw
  envelope size of 40 MB. Exceeding either **must fail closed** and
  trigger a documented retention/segmentation strategy.
- The worker creates one extra private Blob per run. Monitor storage and
  bandwidth against Vercel quotas; no deletion or paid-tier subscription
  is authorized by this release.

## Disaster recovery

The restore function `restore_licensed_history_empty_postgres` refuses
unknown active source DB identities, refuses targets on the same Postgres
host as either source, and refuses any destination that contains existing
`nba_research` tables. PostgreSQL transactionality and exact row readback
are tested on disposable PostgreSQL 18 with **synthetic** rights and matches.

The test does **not** prove that the confidential private Blob content
has been restored to a separate real production-like host. An independent
recovery drill with authorized credentials remains mandatory before
claiming the commercial historical data is recoverable end-to-end.

The database schema migration is deployed in isolated staging, but no
licensed datasets or commercial rights have been invented. No new
public betting models or bookmaker settlement are approved.
