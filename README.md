# Preet Fantasy AI — T20 Prediction API

Independent prediction service for the Crickfan / Dream11-style workflow. This repository is the first API milestone; it does not modify the existing Crickfan application.

## Current features

- FastAPI service with interactive docs at `/docs`
- SQLite for local development; PostgreSQL supported through `DATABASE_URL`
- Match and squad import endpoints
- Historical player-match fantasy-points import
- T20 recent-form baseline predictions (last 10 imported matches, recency weighted)
- Expected points, estimated floor/ceiling, consistency, upside and confidence
- Safe, Balanced, Grand League and Scenario team-generation modes
- Configurable team size, credit cap, role limits, team-player limit and playing-XI filter

## Important limitations

This is **version 0.1.0**, a transparent baseline, not a trained AI model and not a guarantee of winning. It currently predicts from imported historical fantasy points. It does not automatically fetch live cricket data, infer missing credits, verify playing XIs, or know the current official scoring rules of any fantasy platform.

The starter scoring table in `app/config.py` is illustrative and must be checked against the exact contest rules before using calculated fantasy points. The current history importer accepts already-calculated `fantasy_points`; raw scorecard fields are retained for future scoring/backtesting work.

## Run locally (Windows)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open:
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/docs

## Render deployment

1. Create a new Web Service from this GitHub repository.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add `DATABASE_URL` as a secret environment variable using a managed PostgreSQL connection string.
5. If using SQLite instead, attach a persistent disk and set the database path to the mounted disk, for example `sqlite:////var/data/preet_fantasy.db`. Ephemeral filesystem data can be lost on redeploy.

## API workflow

### 1. Create a match

```json
POST /api/v1/matches
{
  "id": "ind-nz-odi-2026-1",
  "name": "India vs New Zealand",
  "format": "T20",
  "team_a": "India",
  "team_b": "New Zealand",
  "status": "upcoming"
}
```

### 2. Import the match squad

```json
POST /api/v1/matches/ind-nz-odi-2026-1/squad
{
  "players": [
    {"id":"p1","name":"Player One","team":"India","role":"BAT","credits":9.0,"selection_pct":72,"status":"confirmed"},
    {"id":"p2","name":"Player Two","team":"New Zealand","role":"BOWL","credits":8.5,"selection_pct":35,"status":"probable"}
  ]
}
```

Allowed roles: `WK`, `BAT`, `AR`, `BOWL`. Use verified player IDs, credits and status. Unknown credits remain null and team generation will refuse to guess them.

### 3. Import historical records

```json
POST /api/v1/history/import
{
  "records": [
    {"match_id":"old-match-1","player_id":"p1","format":"T20","fantasy_points":64,"runs":42,"balls":28,"match_date":"2026-10-10"}
  ]
}
```

For the baseline predictor, provide historical `fantasy_points`. The raw statistics are also stored for later scoring and model development. Records for players not yet in the player table are skipped.

### 4. Get predictions

`GET /api/v1/matches/ind-nz-odi-2026-1/predictions`

### 5. Generate teams

```json
POST /api/v1/matches/ind-nz-odi-2026-1/teams
{
  "strategies": ["safe","balanced","grand_league","scenario"],
  "teams_per_strategy": 2,
  "scenario": "neutral",
  "rules": {
    "team_size": 11,
    "max_from_one_team": 7,
    "max_credits": 100,
    "playing_xi_only": false,
    "min_role": {"WK":1,"BAT":3,"AR":1,"BOWL":3},
    "max_role": {"WK":4,"BAT":6,"AR":4,"BOWL":6}
  }
}
```

These are example rules only. Supply the exact constraints for the contest being entered.

## Roadmap

1. Reliable multi-source ingestion adapters and player identity/alias matching.
2. Historical T20 scorecard collection and chronological backtesting.
3. Better role/opportunity, batting-position, expected-overs, venue and matchup features.
4. Calibrated statistical/ML models and prediction monitoring.
5. Admin dashboard and Crickfan integration after independent validation.

Never expose API keys in frontend code. Respect the terms and access rules of every cricket data provider.
