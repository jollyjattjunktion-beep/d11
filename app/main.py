from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import select
import secrets
from app.database import Base, engine, get_db
from app.models import Match, Player, MatchSquad, PlayerMatchStats, MatchIntelligence, PlayerSourceProfile
from app.schemas import (MatchIn, PlayerIdentityIn, SquadImport, StatsImport,
                         TeamRequest, MatchIntelligenceIn, SquadPlayerEdit, AI11ImportRequest, HistoricalBatchImport)
from app.predictor import predict_match
from app.optimizer import build_teams
from app.config import MODEL_VERSION, ADMIN_TOKEN
from app.importers.ai11 import fetch_page, parse_analysis, parse_fantasy

Base.metadata.create_all(bind=engine)
app = FastAPI(
    title="Preet Fantasy AI",
    description="Format-specific cricket match intelligence, transparent player estimates and constrained fantasy team generation. Predictions are estimates, not guarantees.",
    version="0.2.0",
)

@app.get("/")
def root():
    return {"name":"Preet Fantasy AI","version":"0.2.0","docs":"/docs","health":"/health"}

@app.get("/health")
def health():
    return {"status":"ok","service":"preet-fantasy-api","model_version":MODEL_VERSION}

@app.post("/api/v1/matches")
def upsert_match(payload: MatchIn, db: Session = Depends(get_db)):
    row=db.get(Match,payload.id)
    data=payload.model_dump()
    if row is None:
        row=Match(**data); db.add(row)
    else:
        for key,value in data.items(): setattr(row,key,value)
    db.commit()
    return {"saved":True,"match_id":row.id}

@app.get("/api/v1/matches")
def list_matches(format: str | None = None, db: Session = Depends(get_db)):
    query=select(Match)
    if format: query=query.where(Match.format==format.upper())
    rows=db.scalars(query.order_by(Match.start_time.desc())).all()
    return [{"id":m.id,"name":m.name,"format":m.format,"start_time":m.start_time,
             "venue":m.venue,"team_a":m.team_a,"team_b":m.team_b,"status":m.status} for m in rows]

@app.get("/api/v1/matches/{match_id}")
def get_match(match_id: str, db: Session = Depends(get_db)):
    m=db.get(Match,match_id)
    if not m: raise HTTPException(404,"Match not found")
    return {"id":m.id,"name":m.name,"format":m.format,"start_time":m.start_time,
            "venue":m.venue,"team_a":m.team_a,"team_b":m.team_b,"status":m.status,
            "players":len(m.squad)}

@app.post("/api/v1/players")
def upsert_player(payload: PlayerIdentityIn, db: Session = Depends(get_db)):
    row=db.get(Player,payload.id)
    if row is None: row=Player(id=payload.id,name=payload.name); db.add(row)
    else: row.name=payload.name
    db.commit()
    return {"saved":True,"player_id":row.id}

@app.get("/api/v1/players/{player_id}")
def get_player(player_id: str, db: Session = Depends(get_db)):
    row=db.get(Player,player_id)
    if row is None: raise HTTPException(404,"Player not found")
    count=db.query(PlayerMatchStats).filter(PlayerMatchStats.player_id==player_id).count()
    return {"id":row.id,"name":row.name,"historical_records":count}

@app.post("/api/v1/matches/{match_id}/squad")
def import_squad(match_id: str, payload: SquadImport, db: Session = Depends(get_db)):
    if not db.get(Match,match_id): raise HTTPException(404,"Match not found; create the match first")
    saved=0
    for item in payload.players:
        data=item.model_dump()
        player=db.get(Player,data["id"])
        if player is None: db.add(Player(id=data["id"],name=data["name"]))
        else: player.name=data["name"]
        squad=db.get(MatchSquad,(match_id,data["id"]))
        squad_data={k:v for k,v in data.items() if k not in {"id","name"}}
        if squad is None:
            db.add(MatchSquad(match_id=match_id,player_id=data["id"],**squad_data))
        else:
            for key,value in squad_data.items(): setattr(squad,key,value)
        saved+=1
    db.commit()
    return {"saved":saved,"match_id":match_id}

@app.patch("/api/v1/matches/{match_id}/players/{player_id}")
def edit_match_player(match_id: str, player_id: str, payload: SquadPlayerEdit,
                      db: Session = Depends(get_db)):
    squad=db.get(MatchSquad,(match_id,player_id))
    if squad is None: raise HTTPException(404,"Player is not in this match squad")
    changes=payload.model_dump(exclude_unset=True)
    for key,value in changes.items(): setattr(squad,key,value)
    db.commit()
    return {"updated":True,"match_id":match_id,"player_id":player_id,
            "changes":changes,"note":"Predictions are recalculated on the next request."}

@app.put("/api/v1/matches/{match_id}/intelligence")
def save_match_intelligence(match_id: str, payload: MatchIntelligenceIn,
                             db: Session = Depends(get_db)):
    if not db.get(Match,match_id): raise HTTPException(404,"Match not found")
    row=db.get(MatchIntelligence,match_id)
    data=payload.model_dump()
    if row is None: db.add(MatchIntelligence(match_id=match_id,data=data))
    else: row.data=data
    db.commit()
    return {"saved":True,"match_id":match_id,"fields_received":list(data.keys()),
            "note":"Only supplied source-backed values should be entered; missing values are not inferred."}

@app.get("/api/v1/matches/{match_id}/intelligence")
def get_match_intelligence(match_id: str, db: Session = Depends(get_db)):
    if not db.get(Match,match_id): raise HTTPException(404,"Match not found")
    row=db.get(MatchIntelligence,match_id)
    return {"match_id":match_id,"intelligence":row.data if row else {}}

@app.post("/api/v1/history/import")
def import_history(payload: StatsImport, db: Session = Depends(get_db)):
    saved,skipped=0,0
    for item in payload.records:
        data=item.model_dump()
        if not db.get(Player,data["player_id"]): skipped+=1; continue
        existing=db.scalar(select(PlayerMatchStats).where(
            PlayerMatchStats.match_id==data["match_id"],
            PlayerMatchStats.player_id==data["player_id"]))
        if existing is None: db.add(PlayerMatchStats(**data))
        else:
            for key,value in data.items(): setattr(existing,key,value)
        saved+=1
    db.commit()
    return {"saved":saved,"skipped_unknown_players":skipped}

@app.get("/api/v1/matches/{match_id}/predictions")
def get_predictions(match_id: str, db: Session = Depends(get_db)):
    if not db.get(Match,match_id): raise HTTPException(404,"Match not found")
    predictions=predict_match(db,match_id)
    return {"match_id":match_id,"model_version":MODEL_VERSION,
            "prediction_status":"estimates" if any(p.get("expected_points") is not None for p in predictions) else "insufficient_history",
            "predictions":predictions}

@app.post("/api/v1/matches/{match_id}/teams")
def generate_teams(match_id: str, payload: TeamRequest, db: Session = Depends(get_db)):
    match=db.get(Match,match_id)
    if not match: raise HTTPException(404,"Match not found")
    predictions=predict_match(db,match_id)
    squads=db.scalars(select(MatchSquad).where(MatchSquad.match_id==match_id)).all()
    squad_by_id={s.player_id:s for s in squads}
    combined=[]
    for prediction in predictions:
        s=squad_by_id[prediction["player_id"]]
        combined.append({**prediction,"credits":s.credits,"selection_pct":s.selection_pct,"status":s.status})
    results={}
    for strategy in payload.strategies:
        try:
            results[strategy]=build_teams(
                combined,strategy,payload.rules,payload.teams_per_strategy,payload.scenario,
                team_a=match.team_a,locked_ids=payload.locked_player_ids,
                excluded_ids=payload.excluded_player_ids,captain_pool=payload.captain_pool,
                vice_captain_pool=payload.vice_captain_pool,
                manual_captain_id=payload.manual_captain_id,
                manual_vice_captain_id=payload.manual_vice_captain_id)
        except ValueError as exc:
            raise HTTPException(422,str(exc))
    return {"match_id":match_id,"model_version":MODEL_VERSION,
            "mode":payload.team_mode,"teams":results,
            "manual_controls":{"locked":payload.locked_player_ids,
                "excluded":payload.excluded_player_ids,
                "captain_pool":payload.captain_pool,"vice_captain_pool":payload.vice_captain_pool},
            "warning":"Projected points are model estimates, not guaranteed fantasy outcomes."}

@app.get("/api/v1/model/status")
def model_status(db: Session = Depends(get_db)):
    formats=db.query(PlayerMatchStats.format).distinct().all()
    counts={fmt:db.query(PlayerMatchStats).filter(PlayerMatchStats.format==fmt,
             PlayerMatchStats.fantasy_points.is_not(None)).count() for (fmt,) in formats}
    return {"model_version":MODEL_VERSION,"type":"hybrid_context_adjusted_statistical_baseline",
            "trained_machine_learning_model":False,"historical_records_by_format":counts,
            "note":"Current production path is an explainable statistical baseline with match-context adjustments. A trained ML model must be added only after sufficient clean historical records and chronological backtesting."}


def require_admin(x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Admin importer is disabled. Configure ADMIN_TOKEN in Render environment.")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(401, "Valid X-Admin-Token header required.")
    return True

@app.post("/api/v1/admin/import/ai11")
def import_ai11(payload: AI11ImportRequest, _admin: bool = Depends(require_admin),
                db: Session = Depends(get_db)):
    try:
        analysis_html=fetch_page(payload.analysis_url)
        parsed=parse_analysis(analysis_html)
        fantasy_data={"credits":{},"credits_found":0,"dynamic_content_may_require_browser":True}
        if payload.fantasy_url:
            fantasy_data=parse_fantasy(fetch_page(payload.fantasy_url))
    except Exception as exc:
        raise HTTPException(422, f"AI11 import failed: {str(exc)[:300]}")
    if not parsed["players"]:
        raise HTTPException(422, "No player rows were extracted from the AI11 analysis page. Page markup may have changed or content may require browser rendering.")
    match_id=parsed["match_id"]
    match=db.get(Match,match_id)
    match_values={"name":parsed["title"],"format":parsed["format"],
                  "venue":parsed.get("venue"),"team_a":parsed["team_a"],
                  "team_b":parsed["team_b"],"status":"upcoming",
                  "source":"AI11"}
    if match is None:
        match=Match(id=match_id,**match_values); db.add(match)
    else:
        for key,value in match_values.items(): setattr(match,key,value)
    saved,credits_saved=0,0
    for item in parsed["players"]:
        pid=item["id"]
        player=db.get(Player,pid)
        if player is None: db.add(Player(id=pid,name=item["name"]))
        else: player.name=item["name"]
        squad=db.get(MatchSquad,(match_id,pid))
        credit=fantasy_data["credits"].get(pid)
        values={"team":item["team"],"role":item["role"],
                "credits":credit if credit is not None else (squad.credits if squad else None),
                "selection_pct":item.get("selection_pct"),
                "status":item.get("status","unknown"),"source":"AI11"}
        if squad is None: db.add(MatchSquad(match_id=match_id,player_id=pid,**values))
        else:
            for key,value in values.items():
                if value is not None: setattr(squad,key,value)
        if credit is not None: credits_saved+=1
        profile=db.get(PlayerSourceProfile,(match_id,pid,"AI11"))
        profile_data=next((p for p in parsed["profiles"] if p["player_id"]==pid),{})
        if profile is None:
            db.add(PlayerSourceProfile(match_id=match_id,player_id=pid,source="AI11",data=profile_data))
        else: profile.data=profile_data
        saved+=1
    intel=db.get(MatchIntelligence,match_id)
    intel_data={**parsed.get("intelligence",{}),
                "source_urls":[payload.analysis_url]+([payload.fantasy_url] if payload.fantasy_url else []),
                "source":"AI11","imported_player_count":saved}
    if intel is None: db.add(MatchIntelligence(match_id=match_id,data=intel_data))
    else: intel.data={**(intel.data or {}),**intel_data}
    db.commit()
    missing=[p["name"] for p in parsed["players"] if p["id"] not in fantasy_data["credits"]]
    return {"imported":True,"match_id":match_id,"match":match_values,
            "players_imported":saved,"credits_imported":credits_saved,
            "credits_missing_count":len(missing),"credits_missing_players":missing,
            "fantasy_page_requires_browser":fantasy_data["dynamic_content_may_require_browser"],
            "profiles_saved":saved,
            "warning":"AI11 career/series aggregates and selection trends are source profiles, not per-match historical fantasy points. Import independent historical scorecards before training the prediction model."}

@app.get("/api/v1/admin/matches/{match_id}/source-profiles")
def get_source_profiles(match_id: str, _admin: bool = Depends(require_admin),
                        db: Session = Depends(get_db)):
    if not db.get(Match,match_id): raise HTTPException(404,"Match not found")
    rows=db.scalars(select(PlayerSourceProfile).where(PlayerSourceProfile.match_id==match_id)).all()
    return [{"player_id":r.player_id,"source":r.source,"data":r.data} for r in rows]

@app.post("/api/v1/admin/history/import")
def import_external_history(payload: HistoricalBatchImport,
                            _admin: bool = Depends(require_admin),
                            db: Session = Depends(get_db)):
    saved,skipped=0,0
    for item in payload.records:
        data=item.model_dump()
        data["source"]=payload.source
        if not db.get(Player,data["player_id"]):
            skipped+=1
            continue
        existing=db.scalar(select(PlayerMatchStats).where(
            PlayerMatchStats.match_id==data["match_id"],
            PlayerMatchStats.player_id==data["player_id"]))
        if existing is None: db.add(PlayerMatchStats(**data))
        else:
            for key,value in data.items(): setattr(existing,key,value)
        saved+=1
    db.commit()
    return {"saved":saved,"skipped_unknown_players":skipped,"source":payload.source,
            "note":"Use match-level records with format-correct fantasy_points calculated under the target contest's verified scoring rules."}

@app.get("/api/v1/admin/history/coverage")
def history_coverage(_admin: bool = Depends(require_admin), db: Session = Depends(get_db)):
    rows=db.scalars(select(PlayerMatchStats)).all()
    by_format={}
    for row in rows:
        entry=by_format.setdefault(row.format,{"records":0,"players":set(),"matches":set(),"scored_records":0})
        entry["records"]+=1
        entry["players"].add(row.player_id)
        entry["matches"].add(row.match_id)
        if row.fantasy_points is not None: entry["scored_records"]+=1
    return {"formats":{fmt:{"records":v["records"],"unique_players":len(v["players"]),
                            "matches":len(v["matches"]),"scored_records":v["scored_records"]}
                       for fmt,v in by_format.items()},
            "training_ready":False,
            "note":"Training readiness requires enough clean, chronological records and verified scoring rules; record count alone is not a quality guarantee."}
