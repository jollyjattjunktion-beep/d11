from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.database import Base, engine, get_db
from app.models import Match, Player, MatchSquad, PlayerMatchStats
from app.schemas import MatchIn, PlayerIdentityIn, SquadImport, StatsImport, TeamRequest
from app.predictor import predict_match
from app.optimizer import build_teams
from app.config import MODEL_VERSION

Base.metadata.create_all(bind=engine)
app = FastAPI(
    title="Preet Fantasy AI",
    description="T20 fantasy-prediction API: historical form, expected points, and constrained team generation. Predictions are estimates, not guarantees.",
    version="0.1.0",
)

@app.get("/")
def root():
    return {"name": "Preet Fantasy AI", "version": "0.1.0", "docs": "/docs", "health": "/health"}

@app.get("/health")
def health():
    return {"status": "ok", "service": "preet-fantasy-api", "model_version": MODEL_VERSION}

@app.post("/api/v1/matches")
def upsert_match(payload: MatchIn, db: Session = Depends(get_db)):
    row = db.get(Match, payload.id)
    data = payload.model_dump()
    if row is None:
        row = Match(**data)
        db.add(row)
    else:
        for key, value in data.items(): setattr(row, key, value)
    db.commit()
    return {"saved": True, "match_id": row.id}

@app.get("/api/v1/matches")
def list_matches(format: str = "T20", db: Session = Depends(get_db)):
    rows = db.scalars(select(Match).where(Match.format == format).order_by(Match.start_time.desc())).all()
    return [{"id":m.id,"name":m.name,"format":m.format,"start_time":m.start_time,
             "venue":m.venue,"team_a":m.team_a,"team_b":m.team_b,"status":m.status} for m in rows]

@app.get("/api/v1/matches/{match_id}")
def get_match(match_id: str, db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    if not m: raise HTTPException(404, "Match not found")
    return {"id":m.id,"name":m.name,"format":m.format,"start_time":m.start_time,
            "venue":m.venue,"team_a":m.team_a,"team_b":m.team_b,"status":m.status,
            "players":len(m.squad)}

@app.post("/api/v1/players")
def upsert_player(payload: PlayerIdentityIn, db: Session = Depends(get_db)):
    row = db.get(Player, payload.id)
    if row is None:
        row = Player(id=payload.id, name=payload.name)
        db.add(row)
    else:
        row.name = payload.name
    db.commit()
    return {"saved": True, "player_id": row.id}

@app.get("/api/v1/players/{player_id}")
def get_player(player_id: str, db: Session = Depends(get_db)):
    row = db.get(Player, player_id)
    if row is None: raise HTTPException(404, "Player not found")
    stats_count = db.query(PlayerMatchStats).filter(PlayerMatchStats.player_id == player_id).count()
    return {"id": row.id, "name": row.name, "historical_records": stats_count}

@app.post("/api/v1/matches/{match_id}/squad")
def import_squad(match_id: str, payload: SquadImport, db: Session = Depends(get_db)):
    if not db.get(Match, match_id): raise HTTPException(404, "Match not found; create the match first")
    saved = 0
    for item in payload.players:
        data = item.model_dump()
        player = db.get(Player, data["id"])
        if player is None:
            player = Player(id=data["id"], name=data["name"])
            db.add(player)
        else:
            player.name = data["name"]
        squad = db.get(MatchSquad, (match_id, data["id"]))
        squad_data = {k:v for k,v in data.items() if k not in {"id","name"}}
        if squad is None:
            squad = MatchSquad(match_id=match_id, player_id=data["id"], **squad_data)
            db.add(squad)
        else:
            for key,value in squad_data.items(): setattr(squad,key,value)
        saved += 1
    db.commit()
    return {"saved":saved,"match_id":match_id}

@app.post("/api/v1/history/import")
def import_history(payload: StatsImport, db: Session = Depends(get_db)):
    saved, skipped = 0, 0
    for item in payload.records:
        data = item.model_dump()
        if not db.get(Player, data["player_id"]):
            skipped += 1
            continue
        existing = db.scalar(select(PlayerMatchStats).where(
            PlayerMatchStats.match_id == data["match_id"],
            PlayerMatchStats.player_id == data["player_id"]))
        if existing is None:
            db.add(PlayerMatchStats(**data))
        else:
            for key,value in data.items(): setattr(existing,key,value)
        saved += 1
    db.commit()
    return {"saved":saved,"skipped_unknown_players":skipped}

@app.get("/api/v1/matches/{match_id}/predictions")
def get_predictions(match_id: str, db: Session = Depends(get_db)):
    if not db.get(Match, match_id): raise HTTPException(404, "Match not found")
    return {"match_id":match_id,"model_version":MODEL_VERSION,"predictions":predict_match(db,match_id)}

@app.post("/api/v1/matches/{match_id}/teams")
def generate_teams(match_id: str, payload: TeamRequest, db: Session = Depends(get_db)):
    if not db.get(Match, match_id): raise HTTPException(404, "Match not found")
    predictions = predict_match(db, match_id)
    squads = db.scalars(select(MatchSquad).where(MatchSquad.match_id == match_id)).all()
    squad_by_id = {s.player_id:s for s in squads}
    combined = []
    for prediction in predictions:
        s = squad_by_id[prediction["player_id"]]
        combined.append({**prediction,"credits":s.credits,"selection_pct":s.selection_pct,"status":s.status})
    results = {}
    for strategy in payload.strategies:
        try:
            results[strategy] = build_teams(combined,strategy,payload.rules,payload.teams_per_strategy,payload.scenario)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    return {"match_id":match_id,"model_version":MODEL_VERSION,"teams":results}

@app.get("/api/v1/model/status")
def model_status():
    return {"model_version":MODEL_VERSION,"format":"T20","type":"weighted_recent_form_baseline",
            "trained_model":False,"note":"Baseline heuristic. Validate with chronological backtests before relying on predictions."}
