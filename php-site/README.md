# D11 PHP Cricket Platform — importer foundation

This is the separate PHP + MySQL application. It does not modify the Python D11 application or its production PostgreSQL database.

## Admin importer

After admin login, open `/admin/importer/`. The importer accepts provider-normalised JSON, validates a preview, and imports a batch in a MySQL transaction. Results are recorded in `import_logs`.

Supported sections and processing order:
1. `countries`
2. `competitions`
3. `teams`
4. `venues`
5. `players`
6. `series`
7. `matches`

Each record requires `external_id`; the form's Source key is applied as `external_source`. Foreign-key fields such as `country_id`, `competition_id`, `team_a_id`, `team_b_id`, `series_id`, and `venue_id` must be local IDs in this D11 MySQL database. Import parent records before dependent records. Maximum 500 records per section and 1 MB per request.

Re-imports match rows by `external_source + external_id`. Manually verified venues (`venues.is_manually_verified=1`) are not overwritten. Manually assigned match venues (`matches.venue_manually_set=1`) are retained while other match fields may be refreshed.

The importer uses the existing schema; this update adds no migration and does not reset or alter existing records. Back up the MySQL database before any future schema change.

## Provider integration boundary

This importer is a normalised-data ingestion layer, not an automatic Cricbuzz scraper. Automatic discovery requires a separate provider adapter and a source/API whose access and republication terms permit automated collection. Keep provider-specific parsing outside the database upsert service.
