# D11 PHP Complete Engine — parity plan

Target branch: `php/d11-complete-engine`  
Baseline: `php/cricket-importer`  
Reference implementation: Python D11 (kept unchanged).

## Non-negotiable safety rules

- This branch is a separate PHP implementation; it does not replace or edit the Python application.
- The PHP installer and migrations may only target a newly-created, isolated MySQL/MariaDB test database.
- Never point PHP at the production PostgreSQL database.
- No production database dump is required for the FreeHosting test.
- Schema changes are additive and versioned. Never DROP, TRUNCATE, or reset user data.
- TeamGeneration remains authoritative for fixture identity, squads, credits, roles, and Playing XI.
- AI11 enriches already-linked players. It must not silently add selectable squad players.
- Re-imports must be idempotent and preserve manually verified/locked fields.
- Keep source URL, external IDs, import timestamps, and provenance for imported records.

## Python feature inventory to port

| Python area | PHP target | Acceptance criteria |
|---|---|---|
| FastAPI routes and admin APIs | PHP controllers/actions | Every required operation has equivalent request/response behaviour |
| SQLAlchemy models | MySQL schema + repositories | All domain entities and uniqueness rules represented |
| TeamGeneration import | Provider adapter + import service | Existing fixture updated; stable fixture identity; TG squad fields preserved |
| AI11 import/linking | AI11 adapter + profile service | Match-scoped links to existing TG squad; unmatched players reported, not selected |
| CREX/Cricbuzz importers | Provider adapters | Validated URLs, provenance, bounded fetches, repeatable imports |
| Player historical stats | Stats service/repository | Format-specific records and recent form retained |
| Match intelligence | Match context service | Pitch, weather, H2H, venue and source URLs retained |
| Venue analysis | Venue intelligence service | Venue profile and format-specific facts retained |
| Prediction engine | Pure PHP domain service | Expected/floor/ceiling, consistency, upside, confidence and model version |
| Optimizer | Pure PHP domain service | Same role/team/credit constraints, strategy weights, scenarios and diagnostics |
| Captain/vice-captain | Selection service | Strategy/contest-aware C/VC recommendations with reasons |
| Player locking/rotation | Team generation service | Fixed-player locks and controlled rotation supported |
| Public match pages/feed | PHP page/feed handlers | Match pages, live/upcoming/completed states and SEO metadata |
| Player collector | Bounded scheduled job runner | Idempotent jobs, retries/backoff, source allowlists; no always-on worker assumption |
| Tests | PHPUnit or PHP test harness | Golden fixture parity against Python outputs |

## Data identity strategy

The existing PHP foundation uses numeric auto-increment IDs, while Python uses string provider IDs. Do not force a destructive ID conversion. Keep numeric local primary keys and map source IDs through `external_source + external_id` and `d11_player_identity_links`. Match identity must be stable across re-imports. Never match players by display name alone when a stable source identifier is available.

## Hosting profile

- PHP 8.3 with PDO MySQL and required extensions.
- MySQL/MariaDB isolated test database.
- No long-running process required.
- Imports and collection run in bounded HTTP/CLI batches where supported, with GitHub Actions scheduling as an optional external scheduler.
- Secrets and writable storage stay outside the public document root where the host permits.

## Delivery gates

1. Schema and installer: clean install, re-run lock, no destructive migration.
2. Data foundation: fixtures, teams, players, squads and idempotent imports.
3. Source parity: TeamGeneration first; AI11 enrichment second; CREX/Cricbuzz adapters after.
4. Intelligence parity: historical stats, venue/pitch/weather/H2H and player profiles.
5. Engine parity: predictions, optimizer strategies, team composition, C/VC, locking and diagnostics.
6. Product parity: admin pages, public match pages, SEO, feed and responsive UI.
7. Regression: golden tests compare PHP output to Python reference fixtures.
8. Free-host test: deploy only PHP tree to isolated test account/database.
9. Paid-host migration: move same PHP code and export/import MySQL data; no code rewrite.

## Current implementation status

This branch starts from the PHP importer foundation. The initial parity migration is additive and is not yet a complete schema port. No claim of feature parity should be made until every delivery gate and regression suite passes.


## Implemented PHP services (work in progress)

- app/Database/MigrationRunner.php: ordered SQL migrations, migration ledger, quoted-string-aware SQL splitting, and resumable duplicate-column handling for additive ALTER statements.
- app/Services/TeamGenerationSyncService.php: idempotent fixture/squad sync using TeamGeneration external IDs; preserves manually locked squad values.
- app/Services/Ai11ProfileService.php: match-scoped AI11 enrichment; exact normalized-name matching only when unique; unmatched/ambiguous players are reported and never added to squads.
- app/Services/PlayerPredictionService.php: PHP port of format-matched recent-form predictor, bounded pitch/weather adjustments, AI11 career/series supporting factor, provisional-vs-statistical distinction, and persisted model-versioned predictions.

## Current automated coverage

The PHP workflow runs PHP 8.3 syntax checks, migration parser/safety tests, and a MySQL 8 integration test covering migration repeatability, TeamGeneration re-import identity, manual squad lock preservation, AI11 linking/unmatched reporting, and historical prediction generation.

These services are the first vertical slice only. The optimizer, C/VC portfolio strategy, complete match-intelligence adapters, provider-specific ingestion, public pages/API parity, and remaining admin workflows are still outstanding. Do not deploy this branch as a complete D11 replacement until the full parity checklist passes.
