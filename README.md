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
```json
PUT /api/v1/matches/ind-nz-odi-2026-2/intelligence
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
6. Authenticated admin UI and a manual visual team editor.

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


### AI11 rate-limit protection

The AI11 importer caches successful page responses in the running application process for 10 minutes. A repeated import of the same URL during that window reuses the cached HTML rather than requesting AI11 again. Cache entries expire automatically; a Render restart clears this in-memory cache.

When AI11 responds with HTTP 429, the importer makes up to three bounded attempts, respects the provider's `Retry-After` header when present (with a 15-second per-wait cap), and then returns HTTP 429 with a `Retry-After` response header and a clear retry message. Other upstream fetch failures are returned as HTTP 502; invalid URLs remain HTTP 422. Avoid repeated manual retries while the provider is rate-limiting requests.
