# D11 PHP Cricket Platform — Importer foundation

This is a separate PHP + MySQL application. It does not modify the Python D11 app or production PostgreSQL database.

## Admin importer
After admin login, open `/admin/importer/`. It accepts provider-normalised JSON, validates a preview, then imports the supplied batch transactionally and records results in `import_logs`.

Sections: competitions, teams, venues, players, series, matches. The Source key is applied as `external_source`; each object must contain a unique `external_id`. Foreign-key values such as `competition_id`, `team_a_id`, `team_b_id`, `series_id` and `venue_id` must be local D11 MySQL integer IDs. Parent objects should be imported before dependent objects. Up to 500 records per section and 1 MB per request.

Example:
```json
{
  "competitions":[{"external_id":"cup-2026","name":"Example Cup","slug":"example-cup","format":"T20","season":"2026","gender":"men","status":"upcoming"}],
  "teams":[],
  "venues":[],
  "players":[],
  "series":[],
  "matches":[]
}
```

Matching source + external IDs update existing rows. Manually verified venues are preserved. The initial importer UI is a data-ingestion facility; it is not an automatic Cricbuzz or CREX scraper. Automatic feeds require a permitted API or licensed source adapter and should be added separately.

No SQL migration is executed by this feature. No existing installed database is reset. Back up MySQL before deploying any future schema additions.
