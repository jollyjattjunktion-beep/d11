from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import create_engine

from app.db_migrations import apply_safe_schema_migrations


def test_safe_schema_migration_is_noop_for_sqlite():
    engine = create_engine("sqlite://")
    try:
        apply_safe_schema_migrations(engine)
    finally:
        engine.dispose()


def test_postgres_migration_adds_missing_columns_and_indexes_atomically():
    class Connection:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(str(statement))

    class Engine:
        dialect = SimpleNamespace(name="postgresql")

        def __init__(self):
            self.connection = Connection()
            self.transaction_open = False

        @contextmanager
        def begin(self):
            self.transaction_open = True
            try:
                yield self.connection
            finally:
                self.transaction_open = False

    engine = Engine()
    apply_safe_schema_migrations(engine)

    sql = "\n".join(engine.connection.statements)
    assert "ALTER TABLE matches ADD COLUMN IF NOT EXISTS competition_id" in sql
    assert "ALTER TABLE matches ADD COLUMN IF NOT EXISTS source_fixture_key" in sql
    assert "CREATE TABLE IF NOT EXISTS competitions" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ix_matches_source_fixture_key" in sql
    assert "FOREIGN KEY (competition_id) REFERENCES competitions(id)" in sql
    assert engine.transaction_open is False
