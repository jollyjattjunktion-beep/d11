"""Idempotent, data-preserving PostgreSQL schema compatibility migrations.

These operations only create missing schema objects. They do not delete, rewrite,
or backfill existing match records. Keep this small runner aligned with SQL files
under migrations/ so an existing Render/RDP database can start on newer code.
"""

from sqlalchemy import Engine, text


def apply_safe_schema_migrations(engine: Engine) -> None:
    """Ensure the competition/fixture identity columns exist on PostgreSQL.

    SQLite and other local test databases are managed through SQLAlchemy
    metadata.create_all and are intentionally left unchanged here.
    """
    if engine.dialect.name != "postgresql":
        return

    statements = (
        """
        CREATE TABLE IF NOT EXISTS competitions (
            id VARCHAR(120) PRIMARY KEY,
            provider VARCHAR(40) NOT NULL DEFAULT 'CRICBUZZ',
            provider_series_id VARCHAR(80) NOT NULL UNIQUE,
            name VARCHAR(200) NOT NULL,
            season VARCHAR(20),
            series_url VARCHAR(1000),
            matches_url VARCHAR(1000),
            metadata JSON NOT NULL DEFAULT '{}'::json
        )
        """,
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS competition_id VARCHAR(120)",
        "ALTER TABLE matches ADD COLUMN IF NOT EXISTS source_fixture_key VARCHAR(220)",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_matches_competition_id'
            ) THEN
                ALTER TABLE matches
                    ADD CONSTRAINT fk_matches_competition_id
                    FOREIGN KEY (competition_id) REFERENCES competitions(id);
            END IF;
        END $$
        """,
        "CREATE INDEX IF NOT EXISTS ix_competitions_provider ON competitions(provider)",
        "CREATE INDEX IF NOT EXISTS ix_competitions_provider_series_id ON competitions(provider_series_id)",
        "CREATE INDEX IF NOT EXISTS ix_matches_competition_id ON matches(competition_id)",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_matches_source_fixture_key
        ON matches(source_fixture_key)
        WHERE source_fixture_key IS NOT NULL
        """,
    )

    # One transaction means the app cannot start with only half of this small
    # compatibility migration applied if the database rejects any statement.
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
