-- D11 Cricbuzz competition and stable fixture identity migration.
-- Apply once to an existing PostgreSQL database before deploying this branch.
BEGIN;

CREATE TABLE IF NOT EXISTS competitions (
    id VARCHAR(120) PRIMARY KEY,
    provider VARCHAR(40) NOT NULL DEFAULT 'CRICBUZZ',
    provider_series_id VARCHAR(80) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    season VARCHAR(20),
    series_url VARCHAR(1000),
    matches_url VARCHAR(1000),
    metadata JSON NOT NULL DEFAULT '{}'::json
);

CREATE INDEX IF NOT EXISTS ix_competitions_provider ON competitions(provider);
CREATE INDEX IF NOT EXISTS ix_competitions_provider_series_id ON competitions(provider_series_id);

ALTER TABLE matches ADD COLUMN IF NOT EXISTS competition_id VARCHAR(120);
ALTER TABLE matches ADD COLUMN IF NOT EXISTS source_fixture_key VARCHAR(220);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_matches_competition_id'
    ) THEN
        ALTER TABLE matches
            ADD CONSTRAINT fk_matches_competition_id
            FOREIGN KEY (competition_id) REFERENCES competitions(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_matches_competition_id ON matches(competition_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_matches_source_fixture_key
    ON matches(source_fixture_key) WHERE source_fixture_key IS NOT NULL;

COMMIT;
