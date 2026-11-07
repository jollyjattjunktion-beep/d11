"""Copy an existing local SQLite database into an empty PostgreSQL database.

Set DATABASE_URL to the destination PostgreSQL connection string before running.
The target is deliberately required to be empty: this script never overwrites or
merges into an existing database.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import MetaData, create_engine, func, select, text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_file", help="Path to the source SQLite database file")
    args = parser.parse_args()

    source_path = Path(args.sqlite_file).expanduser().resolve()
    if not source_path.is_file():
        parser.error(f"SQLite source file does not exist: {source_path}")

    target_url = os.getenv("DATABASE_URL", "").strip()
    if not target_url:
        parser.error("Set DATABASE_URL to the destination PostgreSQL connection string.")
    if target_url.lower().startswith("sqlite"):
        parser.error("The destination DATABASE_URL must be PostgreSQL, not SQLite.")

    # Import app metadata only after DATABASE_URL is available, so the target
    # engine is created for PostgreSQL rather than the development SQLite file.
    from app.database import Base, engine as target_engine  # noqa: E402
    import app.models  # noqa: F401,E402

    if target_engine.dialect.name != "postgresql":
        parser.error("The destination database must use PostgreSQL.")

    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    known_tables = Base.metadata.sorted_tables

    try:
        # Confirm that the source has every application table expected by this
        # version before creating/writing anything in the destination.
        missing_tables = [
            table.name
            for table in Base.metadata.sorted_tables
            if table.name not in source_metadata.tables
        ]
        if missing_tables:
            raise RuntimeError(
                "Source SQLite is missing expected tables; no data was copied: "
                + ", ".join(missing_tables)
            )

        # Validate that every source table can be read and report source counts
        # before making any changes to the destination.
        source_counts = {}
        with source_engine.connect() as source:
            for target_table in Base.metadata.sorted_tables:
                source_table = source_metadata.tables[target_table.name]
                source_counts[target_table.name] = source.execute(
                    select(func.count()).select_from(source_table)
                ).scalar_one()

        # Create missing application tables, then refuse to write if the target
        # already contains data. This utility never merges or overwrites rows.
        Base.metadata.create_all(bind=target_engine)
        with target_engine.connect() as connection:
            populated = []
            for table in known_tables:
                count = connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()
                if count:
                    populated.append(table.name)
            if populated:
                raise RuntimeError(
                    "Destination is not empty; no data was copied. "
                    "Populated tables: " + ", ".join(populated)
                )

        copied: dict[str, int] = {}
        with source_engine.connect() as source, target_engine.begin() as target:
            for target_table in known_tables:
                source_table = source_metadata.tables.get(target_table.name)
                if source_table is None:
                    continue

                # Older SQLite files can have a slightly different
                # schema. Copy only columns known to the current ORM model;
                # omitted newer columns use their SQLAlchemy defaults.
                shared_columns = [
                    column.name
                    for column in target_table.columns
                    if column.name in source_table.c
                ]
                if not shared_columns:
                    continue
                source_statement = select(
                    *(source_table.c[name] for name in shared_columns)
                )
                result = source.execute(source_statement)
                total = 0
                while True:
                    batch = result.mappings().fetchmany(500)
                    if not batch:
                        break
                    target.execute(
                        target_table.insert(),
                        [
                            {name: row[name] for name in shared_columns}
                            for row in batch
                        ],
                    )
                    total += len(batch)
                if total:
                    copied[target_table.name] = total

            # Advance PostgreSQL ID sequences to the migrated maximum values.
            for table in known_tables:
                for column in table.primary_key.columns:
                    if column.autoincrement not in (True, "auto"):
                        continue
                    if not str(column.type).upper().startswith("INTEGER"):
                        continue
                    table_name = (
                        f"{table.schema}.{table.name}" if table.schema else table.name
                    )
                    sequence_name = target.execute(
                        text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                        {"table_name": table_name, "column_name": column.name},
                    ).scalar_one_or_none()
                    if not sequence_name:
                        continue
                    max_value = target.execute(
                        select(func.max(column))
                    ).scalar_one_or_none()
                    if max_value is not None:
                        target.execute(
                            text(
                                "SELECT setval(CAST(:sequence_name AS regclass), "
                                ":max_value, true)"
                            ),
                            {"sequence_name": sequence_name, "max_value": max_value},
                        )

        print("SQLite to PostgreSQL migration completed.")
        print("Rows copied by table:")
        for table_name, count in sorted(copied.items()):
            print(f"  {table_name}: {count}")
        print("No source rows were deleted.")
        return 0
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"Migration stopped safely: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
