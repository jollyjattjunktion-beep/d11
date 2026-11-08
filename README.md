# Preet Fantasy AI — Match Intelligence API

FastAPI service for format-aware cricket fantasy estimates and constrained team generation. It supports manual squad corrections, match-condition intelligence and explainable player predictions.

## Current capabilities

- FastAPI API and Swagger UI at `/docs`
- SQLite locally; PostgreSQL through `DATABASE_URL`
- Match and squad import; player credits, role, selection percentage and playing status can be corrected
- Historical player-match imports, separated by format (T20, ODI, TEST)
- Match intelligence storage: pitch suitability, venue average, weather, rain, humidity, wind, dew, head-to-head and recent team form
- Player estimates include expected points, estimated floor/median/ceiling, confidence score, risk, sample size, reasons and warnings
- Safe, Balanced, Grand League and scenario team construction
- Step-by-step admin workspace at `/admin`: Team Generation URL import, Playing XI confirmation, pitch/strong-team/toss setup, venue-history suggestions, fixed players and team generation
- 100-credit default, 11-player default, max seven from one side, configurable role limits and exact team-A split (e.g. 6-5, 7-4, 5-6, 4-7)
- Manual controls: lock players, exclude players, captain/vice-captain pools and manually fixed captain/vice-captain

## Prediction integrity and current limitations

The current prediction path is an **explainable format-specific statistical baseline with conservative match-context adjustments**. It is not yet a trained CatBoost/LightGBM model. The API reports this accurately at `/api/v1/model/status`.

Predictions require imported historical fantasy-point records for the same format. With no history, expected points are returned as null and the optimizer will not invent a score or select that player. Pitch and weather adjustments are applied only when supplied; venue, head-to-head, matchup and player opportunity are stored as match context but are not yet fully modelled as learned effects. Do not treat illustrative weights or confidence scores as a probability of winning.

A true hybrid ML release still requires multi-source historical scorecards, verified fantasy scoring rules, feature engineering, chronological backtesting, calibration and model monitoring. No current endpoint silently scrapes or fabricates AI11 credits or historical data.

## Deploy

Build command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Configure a persistent PostgreSQL `DATABASE_URL` on Render. SQLite on an ephemeral filesystem can lose data after restart/redeploy.

## API workflow

### 1. Create match
```json
POST /api/v1/matches
{
  "id":"ind-nz-odi-2026-2",
  "name":"New Zealand vs India 2nd ODI",
  "format":"ODI",
  "team_a":"New Zealand",
  "team_b":"India",
  "venue":"Hnry Stadium, Wellington"
}
```

### 2. Import squad
```json
POST /api/v1/matches/ind-nz-odi-2026-2/squad
{
  "players":[
    {"id":"player-a","name":"Player A","team":"New Zealand","role":"BAT","credits":9.0,"selection_pct":72,"status":"confirmed"},
    {"id":"player-b","name":"Player B","team":"India","role":"BOWL","credits":8.5,"selection_pct":35,"status":"probable"}
  ]
}
```

### 3. Correct a player's match details
```json
PATCH /api/v1/matches/ind-nz-odi-2026-2/players/player-a
{"credits":9.5,"status":"confirmed","role":"BAT"}
```

### 4. Save sourced match intelligence
Use the `X-Admin-Token` header for this protected write endpoint.
```http
PUT /api/v1/matches/ind-nz-odi-2026-2/intelligence
X-Admin-Token: YOUR_SECRET
Content-Type: application/json
```
```json
{
  "pitch_type":"balanced",
  "batting_friendly":0.55,
  "pace_friendly":0.75,
  "spin_friendly":0.35,
  "average_first_innings":252,
  "rain_probability":20,
  "humidity":65,
  "wind_kmh":12,
  "dew_likely":false,
  "h2h_summary":"Source-backed summary",
  "source_urls":["https://example.com/source"]
}
```
Use verified source values only. Suitability fields are 0-1 inputs; do not guess them from prose without an explicit conversion process.

### 5. Import historical fantasy points
Register player identities with `POST /api/v1/players`, then:
```json
POST /api/v1/history/import
{
  "records":[
    {"match_id":"past-match-1","player_id":"player-a","format":"ODI","fantasy_points":64,"runs":42,"balls":51,"match_date":"2026-10-10","source":"verified-scorecard"}
  ]
}
```
History must use the exact contest scoring system and correct format.

### 6. Read player estimates
`GET /api/v1/matches/ind-nz-odi-2026-2/predictions`

### 7. Generate a balanced 6-5 team with manual locks
```json
POST /api/v1/matches/ind-nz-odi-2026-2/teams
{
  "strategies":["balanced"],
  "teams_per_strategy":5,
  "rules":{
    "team_size":11,
    "max_from_one_team":7,
    "max_credits":100,
    "team_a_count":6,
    "playing_xi_only":true,
    "min_role":{"WK":1,"BAT":3,"AR":1,"BOWL":3},
    "max_role":{"WK":4,"BAT":6,"AR":4,"BOWL":6}
  },
  "locked_player_ids":["player-a"],
  "excluded_player_ids":["player-b"],
  "captain_pool":["player-a","player-c","player-d"],
  "vice_captain_pool":["player-c","player-d","player-e"]
}
```
The team-A count is measured against the match's `team_a` value. Omit it for any legal split up to the maximum-per-side rule. For a fully manual XI, lock all 11 selected players and set the manual captain and vice-captain IDs.

### 8. Model status
`GET /api/v1/model/status`

## Important next milestones

1. AI11 analysis/fantasy URL importer with source attribution and verified credit extraction.
2. Additional permitted cricket-statistics source adapters and player alias matching.
3. Venue, matchup, batting-position and expected-overs features from historical scorecards.
4. Format-specific ML training (ODI, T20, Test separately) with chronological backtests.
5. Calibrated uncertainty and model monitoring before presenting ML confidence.
6. Manual visual team review/editor and additional provider adapters.

Respect each data provider's terms and access controls. This project does not guarantee fantasy contest results.


## AI11 and external historical-data import (v0.3)

### Enable protected admin imports

Set `ADMIN_TOKEN` in Render Environment to a long random secret. Do not put it in browser JavaScript or commit the real value to GitHub. The importer endpoints return 503 until this variable is configured and 401 for an invalid token.

### Import an AI11 match

`POST /api/v1/admin/import/ai11` with header `X-Admin-Token: YOUR_SECRET`:

```json
{
  "analysis_url": "https://www.ai11.in/cricket/series/india-in-new-zealand-odis-2026-27/match/new-zealand-vs-india-2nd-odi-2026",
  "fantasy_url": "https://www.ai11.in/fantasy/cricket/new-zealand-vs-india-2nd-odi-2026"
}
```

The importer:
- Accepts only HTTPS URLs hosted on `ai11.in` or `www.ai11.in`.
- Fetches the analysis and fantasy pages with bounded timeouts and response size.
- Imports match format, teams, player names, roles, selection percentage, lineup marker, available match context and source attribution.
- Saves AI11's player-row values as source profiles for later feature engineering.
- Extracts credits only when explicitly present in page HTML or embedded JSON. It leaves credits missing rather than guessing them. If the fantasy page renders player credits only in browser-side API calls, this server-side HTML importer will report that limitation; inspect the page's permitted public data interface before adding a supported adapter.

The parser is intentionally conservative and AI11 may change its markup. Review imported squads and credits in the admin workflow before team generation. It does not bypass login, anti-bot controls or access restrictions.

### Import independent historical scorecards

AI11 match pages provide current match context, career/series aggregates and selection trends. Those are not a substitute for match-by-match fantasy points. Import external scorecard-derived historical records through:

`POST /api/v1/admin/history/import` with header `X-Admin-Token: YOUR_SECRET`:

```json
{
  "source": "verified_scorecard_provider_and_scoring_rules_v1",
  "records": [
    {
      "match_id": "historic-odi-001",
      "player_id": "virat-kohli",
      "format": "ODI",
      "fantasy_points": 72,
      "runs": 74,
      "balls": 51,
      "fours": 13,
      "sixes": 1,
      "match_date": "2026-10-10"
    }
  ]
}
```

The importer upserts records by match/player. Player identities must exist first. Use the same exact fantasy scoring rules across the dataset; the API does not assume that raw runs/wickets can be converted correctly without the selected contest's scoring table.

Check dataset coverage with `GET /api/v1/admin/history/coverage` and source player profiles with `GET /api/v1/admin/matches/{match_id}/source-profiles`, both using the admin header.

### Important data distinction

- AI11 source profiles: player career/series summaries, selection%, C% and VC%.
- Historical scorecard records: one row per player per completed match, with format and correctly calculated fantasy points.
- Match intelligence: pitch, venue, weather, H2H and recent form.

Only the second category trains historical fantasy-point prediction. The first and third enrich pre-match features. Do not train on future match information or post-match facts when simulating a pre-match prediction.


### Cricbuzz venue statistics and global catalogue

The admin wizard's Step 3 accepts a Cricbuzz venue page URL such as:

`https://www.cricbuzz.com/cricket-series/12543/india-tour-of-new-zealand-2026/venues/42/hnry-stadium`

The protected endpoint `POST /api/v1/admin/matches/{match_id}/venue/import` saves the venue in the SQL `venues` table, preserving ODI, T20 and Test statistics separately. It extracts total matches, bat-first/bowl-first wins, first- and second-innings averages, highest/lowest totals, highest chase and lowest defended, plus venue profile/facts where exposed.

The automatic analysis uses only the fixture's format. It explains batting/bowling surface and toss preference from venue profile, innings averages and historical win splits. The stronger squad is assessed separately using format-matched player expected fantasy points; it is not a match-winner probability. When both sides lack adequate player data, it returns "insufficient evidence" rather than inventing a stronger team.

The Step 4 stadium catalogue can grow automatically:

- **Discover series & grounds** accepts the public Cricbuzz all-series schedule page (`https://www.cricbuzz.com/cricket-schedule/series/all`) or a year archive page (`https://www.cricbuzz.com/cricket-scorecard-archives/2026`). It discovers series, opens their Venues pages and stores linked stadium entries.
- **Enrich next 10 stadiums** fetches detailed venue profiles and format stats in small batches.
- A separate one-series import remains available for a direct `/cricket-series/{id}/{slug}/venues` URL.
- `GET /api/v1/admin/venues?q=...` searches the SQL catalogue.

Repeat discovery with different archive-year URLs to broaden historical and worldwide ground coverage. The catalogue is progressive, not a claim that every stadium in the world has been indexed. Venue player-history comparisons require historical match-by-match scorecards with venue names to have been imported separately. The fixed-player shortlist remains limited to 4–5 selected players with provider selection percentage of at least 80%.


### AI11 rate-limit protection

The AI11 importer caches successful page responses in the running application process for 10 minutes. A repeated import of the same URL during that window reuses the cached HTML rather than requesting AI11 again. Cache entries expire automatically; a Render restart clears this in-memory cache.

When AI11 responds with HTTP 429, the importer makes up to three bounded attempts, respects the provider's `Retry-After` header when present (with a 15-second per-wait cap), and then returns HTTP 429 with a `Retry-After` response header and a clear retry message. Other upstream fetch failures are returned as HTTP 502; invalid URLs remain HTTP 422. Avoid repeated manual retries while the provider is rate-limiting requests.


### Step-by-step admin workspace

Open `/admin` on your deployed service and enter the `ADMIN_TOKEN`. The token remains in page memory only; it is not written to local storage.

The Team Generation workflow is separated into five steps:

1. **Match import:** paste `https://teamgeneration.in/match/{match_id}` or browse upcoming fixtures. The server fetches both teams, roles, player images, credits and provider selection/C/VC trends.
2. **Playing XI:** provider-confirmed Playing XI flags are auto-selected. Before confirmation, provisional picks do not mark other squad members unavailable. Manual official confirmation requires exactly 11 players per side.
3. **Venue analysis:** import a Cricbuzz venue page. The system uses format-specific ODI/T20/Test records to assess ground conditions and toss tendencies; the stronger-team comparison is separate and needs sufficient player history.
4. **Fixed players:** choose up to five eligible locked players with provider selection percentage of at least 80%. Four or five are recommended, but fewer can be selected when fewer players qualify.
5. **Generate teams:** choose Team A:Team B splits of 6:5, 5:6, 7:4 or 4:7, then create Safe, Balanced, Grand League or combined strategies. Results render as cricket-ground preview cards with C/VC labels and Print / Save PDF.

Use **Refresh source / toss update** after the toss or official lineup announcement. The importer refreshes provider data; an admin-confirmed XI remains preserved while the provider still reports that lineups are unannounced. Once provider-confirmed Playing XI flags are available, they become the source of truth.

AI11 remains a separate provider import under **Other provider — AI11 import**. The two providers do not overwrite one another's source profiles. Missing player credits can be corrected in the Match Import step, with optional source URL evidence.

Venue recommendations require historical match rows with the same normalized venue name and non-null, verified fantasy points. Import accurate match-level scorecards and venue metadata before expecting stadium-specific suggestions.


### Dedicated Stadium Database Manager

Open `/admin/stadiums` independently of a match wizard. It accepts individual Cricbuzz venue pages, imports the three supplied venues (W.A.C.A. Ground, Tribhuvan University International Cricket Ground and Junction Oval), imports a competition's Venues page, discovers series from Cricbuzz schedule/archive pages in batches, and enriches pending venue profiles in batches of ten.

Protected endpoints:

- `POST /api/v1/admin/venues/import` — fetch and save one stadium.
- `POST /api/v1/admin/venues/import-featured` — fetch and save the three supplied stadiums.
- `POST /api/v1/admin/venues/import-series` — save grounds listed on one series Venues page.
- `POST /api/v1/admin/venues/discover-series` — discover series and grounds from an all-series or archive page. Supports `series_offset` and `max_series`.
- `POST /api/v1/admin/venues/enrich` — enrich up to twenty saved grounds with available format-specific data.
- `GET /api/v1/admin/venues?q=...` — search the SQL catalogue.

### Dream-team preview and team splits

The final wizard step now renders portrait cricket-ground cards for each generated team, including player photos, role groups, C/VC labels, credits, and a clear provisional-vs-estimated-points label. Use **Print / Save PDF** to export the cards. Exact Team A:Team B options are 6:5, 5:6, 7:4 and 4:7. The fixed-player step only locks eligible players with provider selection at least 80%; it does not block the wizard when fewer than four qualify.


### Public cricket fixture homepage

The root route `/` serves an SEO-friendly public cricket match centre. It uses the same authenticated Team Generation fixture endpoint already used by the admin importer.

- `app/public_feed.py` normalizes fixtures, detects ODI/T20/Test formats, derives live/upcoming/completed/cancelled state and applies format-aware stale-match cutoffs when the provider omits status.
- `app/main.py` upserts lightweight match rows into `matches` and stores series/team labels/logos/provider status in the `match_intelligence.data.public_feed` JSON object. It does not import full player squads from the public homepage.
- A background sync runs every five minutes while the web service is awake. The homepage, sitemap and public feed API also trigger a throttled sync, so the first visit after a cold start refreshes the database.
- Completed/cancelled fixtures are hidden immediately. If the provider omits an in-progress match from its upcoming-only list, the app retains it through a format-aware playing window (7 hours for T20, 12 for ODI and 6 days for Test) before hiding it. Match, squad, scorecard and player-history records are retained in SQL.
- `GET /api/v1/public/matches` returns the visible fixture feed and sync status.
- `POST /api/v1/admin/public-matches/sync` forces a manual sync and requires `X-Admin-Token`.
- `/robots.txt` and `/sitemap.xml` are served for search-engine discovery. Set `PUBLIC_SITE_URL` in Render when a custom canonical domain is configured; otherwise the request host is used.

The homepage is server-rendered from SQL, with canonical/meta description, Open Graph/Twitter metadata, SportsEvent/ItemList JSON-LD, mobile-responsive fixture cards and FAQ content. Fixture coverage and status are limited to what the connected Team Generation provider exposes. The service must have a valid `TG_API_TOKEN` and persistent PostgreSQL `DATABASE_URL` for reliable scheduled updates and long-term SQL retention.


### Public match detail pages

Each homepage fixture card links to `/match/{match_id}`. The first visit fetches the full Team Generation match detail through the server-side `TG_API_TOKEN`, using the existing Team Generation importer. Player identities, roles, images, credits, selection/C/VC trends and provider Playing XI status are written into the existing `players`, `match_squads`, `player_source_profiles` and `match_intelligence` tables. A successful detail import is refreshed after 15 minutes; a failed attempt has a five-minute retry cooldown.

The public detail page shows both squads, match metadata, venue/toss information where available, and match-specific scorecard records only when those records have been imported. It does not invent live scores, innings totals, fantasy points or scorecard values. Completed match pages remain accessible by their saved ID even after they leave the homepage feed.

- `GET /match/{match_id}` — SEO-friendly public HTML match detail page.
- `GET /api/v1/public/matches/{match_id}` — public match, squad, scorecard and limited lineup/venue data. Raw admin intelligence is not returned.


### Public match-page fantasy team builder

The public match detail page includes four team-generation modes, all calling `POST /api/v1/matches/{match_id}/teams` and respecting the configured 11-player, 100-credit, role and seven-per-side rules:

1. **Pitch based:** Balanced, Batting, Bowling or Spin. These map to the existing neutral, batting-friendly, bowling-friendly and spin-friendly scenario preferences.
2. **Score based:** First innings or second-innings chase. The user selects the batting-first/chasing team and enters a scenario score/target. This applies a small role-and-team selection multiplier (format-specific score bands); the entered score is a user assumption, not an AI score prediction or guaranteed fantasy-points forecast.
3. **Powerful combination:** Generates teams across selected Safe, Balanced and Grand League strategies.
4. **Smart selection:** Shows only squad players with provider selection percentage >=80%, preselects the top four eligible players, allows up to five, and locks the chosen players into generated teams. Confirmed-XI mode excludes players outside the provider-confirmed XI.

Team split controls remain available (automatic, 6:5, 5:6, 7:4, 4:7). AI estimate and provisional generation remain clearly distinguished; when format-matched fantasy history is unavailable, the API returns provisional selection-priority teams without claiming projected fantasy points.

## Automatic player collector (separate Render worker)

The player collector is an additive subsystem. It creates its own tables and does not
alter or delete the existing `players`, `matches`, `match_squads`, or fantasy
history tables. It discovers public player-profile and scorecard links from the
configured CREX/Cricbuzz match and discovery pages, saves source identities and
profile snapshots, and upserts scorecard rows by source + match + player. Discovered
players are also added to the existing `players` catalogue when no name match exists.

### Recommended deployment: GitHub Actions (no Render worker)

The collector supports a bounded one-shot mode for scheduled runners:
`python -m app.player_collector_worker --once --max-jobs 250`.
The workflow at `.github/workflows/player-data-collector.yml` runs every 6 hours
and can also be started manually from the GitHub Actions tab after the workflow
has been merged into the default branch.

In GitHub, open **Settings -> Secrets and variables -> Actions -> New repository
secret** and create `D11_DATABASE_URL`. Set its value to the PostgreSQL **External
Database URL** from Render (not the internal-only URL), with SSL enabled as required
by the database connection details. The secret is injected only into the runner;
never commit a database URL or password into this repository.

GitHub-hosted runners execute the Python collector; PostgreSQL remains the permanent
database. The existing Render web service continues to serve D11, but no Render
Background Worker is required. GitHub Actions scheduled runs can be delayed and
are not real-time; the default cadence is every 6 hours. GitHub Actions usage limits
depend on whether the repository is public or private.

The optional `render-worker.yaml` remains available for a future always-on worker,
but it is not needed for the recommended scheduled setup.

The initial test seeds are the supplied CREX India U19 vs Pakistan U19 match page
and Cricbuzz Perth Scorchers Women vs Melbourne Stars Women scorecard. The worker
then discovers linked player profiles and scorecards. Override them with
`PLAYER_COLLECTOR_SEED_URLS` (comma-separated HTTPS URLs) if needed.
`PLAYER_COLLECTOR_DISCOVERY_URLS` controls periodic discovery pages.

Optional environment variables:
- `COLLECTOR_POLL_SECONDS` (default 15)
- `COLLECTOR_REQUEST_GAP_SECONDS` (default 3; minimum 2 seconds between requests)
- `COLLECTOR_REFRESH_HOURS` (default 72; minimum 6)
- `COLLECTOR_MAX_ATTEMPTS` (default 5)

### Data and coverage

The first release collects player profile pages and conventional scorecard batting/
bowling tables when those tables are present in provider HTML. It stores source
provenance, raw table values, career table snapshots and match-level player rows.
It does **not** claim ball-by-ball coverage: powerplay/death splits and batter-vs-
bowler matchups remain unavailable until a permitted delivery feed is integrated.
Provider markup, robots/terms and access controls can change; the collector uses
ordinary HTTPS requests and does not bypass logins, CAPTCHAs, or anti-bot controls.
Failed pages are retried with backoff and eventually marked failed for inspection.

### Identity caution

The initial identity resolver normalizes player names and flags conflicting country
observations. It is a practical deduplication baseline, not perfect proof that two
same-named people are the same player. Review flagged conflicts before using those
profiles for predictions. All imported records remain source-attributed.
