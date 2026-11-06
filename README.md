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
