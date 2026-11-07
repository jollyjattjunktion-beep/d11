# Durable SQL storage on Render

The production application must use a managed PostgreSQL database. Render web-service filesystems are ephemeral, so the local SQLite fallback is for development only.

## Render configuration

1. Create a PostgreSQL database whose data does not expire automatically. A Free Render Postgres database is not suitable for permanent storage because Render expires it after 30 days.
2. Keep the database in the same Render region as the web service when using Render's internal connection URL.
3. Open the `d11` web service in Render, add `DATABASE_URL` using the database's internal URL (or the provider's TLS-enabled URL if it is external), and save it as a secret.
4. Deploy only after `DATABASE_URL` is present. The application now refuses to start in production when this variable is missing or points to SQLite.
5. After deployment, check `/health`. It reports `database_backend: "postgresql"` and `durable_sql_storage: true` when the app is using PostgreSQL. It does not return credentials.

The repository's `render.yaml` keeps `DATABASE_URL` as `sync: false`; the secret must be entered in the Render service's environment settings. Do not put the connection string into GitHub.

## Migrating a local SQLite database

If you have a copy of the old `preet_fantasy.db` file, make a backup copy first. Set `DATABASE_URL` to the new empty PostgreSQL database, then run:

```powershell
$env:APP_ENV = "production"
$env:DATABASE_URL = Read-Host "Paste the PostgreSQL connection string"
python scripts/migrate_sqlite_to_postgres.py .\preet_fantasy.db
```

The migration utility creates missing application tables and copies rows in foreign-key order. It refuses to write if the destination already has rows, uses a single transaction for the copy, advances integer ID sequences, and never deletes the source SQLite file.

The current Render Free web service does not provide shell access to its runtime filesystem. If the only copy of the former SQLite database was on that service, it cannot be pulled out through this utility; use a backup/export if one exists.

## Venue behaviour

Admin-entered stadium names and catalogue selections are stored in `matches.venue` and `match_intelligence.data`. A manual venue lock prevents Team Generation fixture refreshes from replacing the selected venue. The admin editor includes a deliberate `Use live feed venue` option to release the lock and restore the latest provider venue.

The current fixture's upstream venue is also stored separately in `match_intelligence.data.public_feed.feed_venue`, so a manual edit does not destroy the provider value.
