-- 2026-10-28: Permission-gated private historical basketball data.
-- No external provider records are imported by this migration.
CREATE TABLE IF NOT EXISTS nba_research.basketball_data_rights (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    league text NOT NULL CHECK (league IN ('wnba','ncaa_men','ncaa_women',
                                           'euroleague','eurocup','nbl_au')),
    provider text NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_]{2,50}$'),
    status text NOT NULL CHECK (status IN ('verified','revoked','expired')),
    evidence_sha256 text NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    licensed_storage boolean NOT NULL DEFAULT false,
    licensed_training boolean NOT NULL DEFAULT false,
    licensed_betting_use boolean NOT NULL DEFAULT false,
    licensed_redistribution boolean NOT NULL DEFAULT false,
    approved_at timestamptz NOT NULL,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (league,provider,evidence_sha256),
    CHECK (expires_at IS NULL OR expires_at > approved_at)
);
CREATE TABLE IF NOT EXISTS nba_research.basketball_licensed_imports (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rights_id bigint NOT NULL REFERENCES nba_research.basketball_data_rights(id),
    league text NOT NULL CHECK (league IN ('wnba','ncaa_men','ncaa_women',
                                          'euroleague','eurocup','nbl_au')),
    provider text NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_]{2,50}$'),
    season_code text NOT NULL CHECK (season_code ~ '^[0-9]{4}(-[0-9]{2,4})?$'),
    manifest_sha256 text NOT NULL UNIQUE CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    event_count integer NOT NULL CHECK (event_count BETWEEN 1 AND 1500),
    imported_at timestamptz NOT NULL DEFAULT now(),
    independent_score_agreement_verified boolean NOT NULL DEFAULT false,
    model_approved boolean NOT NULL DEFAULT false,
    public_publishing_enabled boolean NOT NULL DEFAULT false,
    CHECK (model_approved = false AND public_publishing_enabled = false)
);
CREATE TABLE IF NOT EXISTS nba_research.basketball_licensed_games (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    import_id bigint NOT NULL REFERENCES nba_research.basketball_licensed_imports(id),
    league text NOT NULL CHECK (league IN ('wnba','ncaa_men','ncaa_women',
                                          'euroleague','eurocup','nbl_au')),
    provider text NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_]{2,50}$'),
    provider_event_id text NOT NULL CHECK (length(provider_event_id) BETWEEN 1 AND 80),
    season_code text NOT NULL CHECK (season_code ~ '^[0-9]{4}(-[0-9]{2,4})?$'),
    tipoff_utc timestamptz NOT NULL,
    home_team_id text NOT NULL CHECK (length(home_team_id) BETWEEN 1 AND 80),
    away_team_id text NOT NULL CHECK (length(away_team_id) BETWEEN 1 AND 80),
    status text NOT NULL CHECK (status IN ('scheduled','final','canceled')),
    home_score integer CHECK (home_score BETWEEN 0 AND 400),
    away_score integer CHECK (away_score BETWEEN 0 AND 400),
    row_sha256 text NOT NULL CHECK (row_sha256 ~ '^[0-9a-f]{64}$'),
    inserted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (league,provider,provider_event_id),
    CHECK (home_team_id <> away_team_id),
    CHECK ((status='final' AND home_score IS NOT NULL AND away_score IS NOT NULL
            AND home_score <> away_score)
           OR (status<>'final' AND home_score IS NULL AND away_score IS NULL))
);
CREATE INDEX IF NOT EXISTS basketball_licensed_games_league_season_idx
ON nba_research.basketball_licensed_games (league,season_code,tipoff_utc);
CREATE INDEX IF NOT EXISTS basketball_licensed_imports_league_idx
ON nba_research.basketball_licensed_imports (league,imported_at DESC);
ALTER TABLE nba_research.basketball_data_rights ENABLE ROW LEVEL SECURITY;
ALTER TABLE nba_research.basketball_licensed_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE nba_research.basketball_licensed_games ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE nba_research.basketball_data_rights,
    nba_research.basketball_licensed_imports,
    nba_research.basketball_licensed_games FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE
    nba_research.basketball_data_rights_id_seq,
    nba_research.basketball_licensed_imports_id_seq,
    nba_research.basketball_licensed_games_id_seq FROM PUBLIC, anon, authenticated;
