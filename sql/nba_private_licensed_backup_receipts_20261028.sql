CREATE TABLE IF NOT EXISTS nba_research.basketball_history_backup_receipts (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 tables_sha256 text NOT NULL CHECK (tables_sha256 ~ '^[0-9a-f]{64}$'),
 blob_sha256 text NOT NULL CHECK (blob_sha256 ~ '^[0-9a-f]{64}$'),
 rights_count integer NOT NULL CHECK (rights_count BETWEEN 0 AND 75000),
 imports_count integer NOT NULL CHECK (imports_count BETWEEN 0 AND 75000),
 games_count integer NOT NULL CHECK (games_count BETWEEN 0 AND 75000),
 probes_count integer NOT NULL CHECK (probes_count BETWEEN 0 AND 75000),
 verified_at timestamptz NOT NULL DEFAULT now(),
 source_changed_after_export boolean NOT NULL DEFAULT false,
 CONSTRAINT basketball_history_private_readback_only
 CHECK (source_changed_after_export = false)
);
CREATE INDEX IF NOT EXISTS basketball_history_backup_receipts_latest
 ON nba_research.basketball_history_backup_receipts(verified_at DESC);
ALTER TABLE nba_research.basketball_history_backup_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE nba_research.basketball_history_backup_receipts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE nba_research.basketball_history_backup_receipts_id_seq FROM PUBLIC, anon, authenticated;