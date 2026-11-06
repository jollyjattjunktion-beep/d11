from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from sqlalchemy.orm import Session
from sqlalchemy import select
import secrets
import httpx
from datetime import datetime, timezone
from app.database import Base, engine, get_db
from app.models import Match, Player, MatchSquad, PlayerMatchStats, MatchIntelligence, PlayerSourceProfile
from app.schemas import (MatchIn, PlayerIdentityIn, SquadImport, StatsImport,
                         TeamRequest, MatchIntelligenceIn, SquadPlayerEdit, AI11ImportRequest, HistoricalBatchImport, ManualCreditUpdate)
from app.predictor import predict_match
from app.optimizer import build_teams
from app.config import MODEL_VERSION, ADMIN_TOKEN, TG_API_TOKEN
from app.importers.ai11 import (fetch_page, parse_analysis, parse_fantasy, AI11RateLimitError)

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

def require_admin(x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Admin importer is disabled. Configure ADMIN_TOKEN in Render environment.")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(401, "Valid X-Admin-Token header required.")
    return True

@app.patch("/api/v1/matches/{match_id}/players/{player_id}")
def edit_match_player(match_id: str, player_id: str, payload: SquadPlayerEdit,
                      _admin: bool = Depends(require_admin),
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
        player_name=data.pop("player_name",None)
        player=db.get(Player,data["player_id"])
        if player is None and player_name:
            player=Player(id=data["player_id"],name=player_name)
            db.add(player)
        if player is None: skipped+=1; continue
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
    squads=db.scalars(select(MatchSquad).where(MatchSquad.match_id==match_id)).all()
    if not squads: raise HTTPException(422,"No squad players are imported for this match.")
    missing_credit_players=[]
    for squad in squads:
        if squad.credits is None:
            player=db.get(Player,squad.player_id)
            missing_credit_players.append(player.name if player else squad.player_id)
    if missing_credit_players:
        raise HTTPException(422,detail={
            "message":"Team generation requires verified player credits.",
            "credits_missing_count":len(missing_credit_players),
            "credits_missing_players":missing_credit_players,
            "action":"Import verified credits or enter them manually. No credit values are guessed."
        })
    predictions=predict_match(db,match_id)
    squad_by_id={s.player_id:s for s in squads}
    combined=[]
    for prediction in predictions:
        s=squad_by_id[prediction["player_id"]]
        tg_profile=db.get(PlayerSourceProfile,(match_id,s.player_id,"TEAM_GENERATION"))
        ai11_profile=db.get(PlayerSourceProfile,(match_id,s.player_id,"AI11"))
        tg_data=tg_profile.data if tg_profile and isinstance(tg_profile.data,dict) else {}
        ai11_data=ai11_profile.data if ai11_profile and isinstance(ai11_profile.data,dict) else {}
        captain_pct=tg_data.get("captain_pct",ai11_data.get("captain_pct",ai11_data.get("captain")))
        vice_pct=tg_data.get("vice_captain_pct",ai11_data.get("vice_captain_pct",ai11_data.get("vice_captain")))
        combined.append({**prediction,"credits":s.credits,"selection_pct":s.selection_pct,"status":s.status,
                         "captain_pct":captain_pct,"vice_captain_pct":vice_pct,
                         "team_generation_image":tg_data.get("image"),
                         "team_generation_fantasy_ids":tg_data.get("fantasy_ids")})
    history_ready=bool(combined) and all(p.get("expected_points") is not None for p in combined)
    requested=payload.generation_mode
    modes=(["ai_prediction","provisional"] if requested=="both" else [requested])
    if "ai_prediction" in modes and not history_ready:
        if requested=="ai_prediction":
            raise HTTPException(422,detail={
                "message":"AI Prediction Mode requires format-matched historical fantasy-point records.",
                "prediction_status":"insufficient_history",
                "players_missing_history":[p["player_name"] for p in combined if p.get("expected_points") is None],
                "action":"Import verified match-by-match historical records for this format, then retry. Use Provisional Team Builder in the meantime."
            })
        modes.remove("ai_prediction")
    results={}
    for mode in modes:
        results[mode]={}
        for strategy in payload.strategies:
            try:
                results[mode][strategy]=build_teams(
                    combined,strategy,payload.rules,payload.teams_per_strategy,payload.scenario,
                    team_a=match.team_a,locked_ids=payload.locked_player_ids,
                    excluded_ids=payload.excluded_player_ids,captain_pool=payload.captain_pool,
                    vice_captain_pool=payload.vice_captain_pool,
                    manual_captain_id=payload.manual_captain_id,
                    manual_vice_captain_id=payload.manual_vice_captain_id,
                    mode=mode)
            except ValueError as exc:
                raise HTTPException(422,str(exc))
    return {
        "match_id":match_id,"model_version":MODEL_VERSION,
        "generation_mode_requested":requested,
        "history_status":"ready" if history_ready else "insufficient_history",
        "available_modes":(["ai_prediction","provisional"] if history_ready else ["provisional"]),
        "teams":results,
        "manual_controls":{"locked":payload.locked_player_ids,
            "excluded":payload.excluded_player_ids,
            "captain_pool":payload.captain_pool,"vice_captain_pool":payload.vice_captain_pool},
        "warnings":[
            "AI Prediction Mode uses format-matched historical statistical estimates; it is not a trained machine-learning model."
        ] + (["Provisional teams use imported source ownership and captain/vice-captain trends as weak selection signals only. Projected fantasy points are null and no points prediction is claimed."] if not history_ready or "provisional" in modes else [])
    }

@app.get("/api/v1/model/status")
def model_status(db: Session = Depends(get_db)):
    formats=db.query(PlayerMatchStats.format).distinct().all()
    counts={fmt:db.query(PlayerMatchStats).filter(PlayerMatchStats.format==fmt,
             PlayerMatchStats.fantasy_points.is_not(None)).count() for (fmt,) in formats}
    return {"model_version":MODEL_VERSION,"type":"hybrid_context_adjusted_statistical_baseline",
            "trained_machine_learning_model":False,"historical_records_by_format":counts,
            "note":"Current production path is an explainable statistical baseline with match-context adjustments. A trained ML model must be added only after sufficient clean historical records and chronological backtesting."}



@app.post("/api/v1/admin/import/ai11")
def import_ai11(payload: AI11ImportRequest, _admin: bool = Depends(require_admin),
                db: Session = Depends(get_db)):
    try:
        submitted_url = payload.analysis_url
        fantasy_url = payload.fantasy_url
        # Accept either AI11 URL in the one-field admin importer. A fantasy page
        # links to its matching analysis page through the "past performance" link.
        if urlparse(submitted_url).path.startswith("/fantasy/cricket/"):
            fantasy_url = fantasy_url or submitted_url
            fantasy_html = fetch_page(submitted_url)
            fantasy_soup = BeautifulSoup(fantasy_html, "html.parser")
            analysis_link = next(
                (a.get("href") for a in fantasy_soup.find_all("a", href=True)
                 if "/cricket/series/" in a.get("href", "") and "/match/" in a.get("href", "")),
                None,
            )
            if not analysis_link:
                raise ValueError("This AI11 fantasy page does not expose its matching analysis link. Paste the AI11 analysis URL instead.")
            analysis_url = urljoin("https://www.ai11.in", analysis_link)
        else:
            analysis_url = submitted_url

        analysis_html=fetch_page(analysis_url)
        parsed=parse_analysis(analysis_html)
        fantasy_data={"credits":{},"credits_found":0,"dynamic_content_may_require_browser":True}
        if not fantasy_url:
            parts = [part for part in urlparse(analysis_url).path.split("/") if part]
            if parts:
                fantasy_url = f"https://www.ai11.in/fantasy/cricket/{parts[-1]}"
        if fantasy_url:
            fantasy_data=parse_fantasy(fetch_page(fantasy_url))
    except AI11RateLimitError as exc:
        raise HTTPException(
            429,
            detail={"message": str(exc), "provider": "AI11", "retry_after_seconds": exc.retry_after,
                    "action": "Wait before retrying. Successful pages are cached for 10 minutes."},
            headers={"Retry-After": str(exc.retry_after)},
        )
    except ValueError as exc:
        raise HTTPException(422, f"AI11 import rejected: {str(exc)[:300]}")
    except Exception as exc:
        raise HTTPException(502, f"AI11 upstream fetch failed: {str(exc)[:300]}")
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
                "status":item.get("status","unknown"),
                "source":"AI11" if credit is not None or squad is None else (squad.source or "AI11")}
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
                "source_urls":[analysis_url]+([fantasy_url] if fantasy_url else []),
                "source":"AI11","imported_player_count":saved}
    if intel is None: db.add(MatchIntelligence(match_id=match_id,data=intel_data))
    else: intel.data={**(intel.data or {}),**intel_data}
    db.commit()
    # Readiness includes saved manual corrections, not only values in this AI11 response.
    squad_rows=db.scalars(select(MatchSquad).where(MatchSquad.match_id==match_id)).all()
    player_names={p["id"]:p["name"] for p in parsed["players"]}
    missing=[player_names.get(row.player_id,row.player_id) for row in squad_rows if row.credits is None]
    return {"imported":True,"match_id":match_id,"match":match_values,
            "players_imported":saved,"credits_imported":credits_saved,
            "credits_verified_count":sum(1 for row in squad_rows if row.credits is not None),
            "credits_missing_count":len(missing),"credits_missing_players":missing,
            "credits_status":fantasy_data.get("credits_status","not_present_in_fetched_html"),
            "credit_evidence":fantasy_data.get("credit_evidence",[]),
            "credits_ready_for_team_builder":bool(squad_rows) and len(missing)==0,
            "fantasy_page_requires_browser":fantasy_data["dynamic_content_may_require_browser"],
            "profiles_saved":saved,
            "warning":"AI11 career/series aggregates and selection trends are source profiles, not per-match historical fantasy points. Import independent historical scorecards before training the prediction model."}

@app.get("/api/v1/admin/matches/{match_id}/credits")
def get_match_credit_status(match_id: str, _admin: bool = Depends(require_admin),
                            db: Session = Depends(get_db)):
    match=db.get(Match,match_id)
    if not match:
        raise HTTPException(404,"Match not found")
    rows=db.scalars(select(MatchSquad).where(MatchSquad.match_id==match_id)).all()
    players=[]
    for row in rows:
        player=db.get(Player,row.player_id)
        players.append({"player_id":row.player_id,"player_name":player.name if player else row.player_id,
                        "team":row.team,"role":row.role,"credits":row.credits,
                        "credit_source":row.source})
    missing=[p for p in players if p["credits"] is None]
    return {"match_id":match_id,"match_name":match.name,"players":players,
            "credits_verified_count":len(players)-len(missing),
            "credits_missing_count":len(missing),"credits_missing_players":missing,
            "credits_ready_for_team_builder":bool(players) and not missing}


@app.post("/api/v1/admin/matches/{match_id}/credits")
def save_manual_match_credit(match_id: str, payload: ManualCreditUpdate,
                              _admin: bool = Depends(require_admin),
                              db: Session = Depends(get_db)):
    match=db.get(Match,match_id)
    if not match:
        raise HTTPException(404,"Match not found")
    squad=db.get(MatchSquad,(match_id,payload.player_id))
    if not squad:
        raise HTTPException(404,"Player is not in this match squad")
    source_url=payload.source_url.strip() if payload.source_url else None
    if source_url and not source_url.startswith("https://"):
        raise HTTPException(422,"Source URL must use HTTPS.")
    player=db.get(Player,payload.player_id)
    old_credit=squad.credits
    squad.credits=payload.credits
    squad.source="manual_verified"
    intel=db.get(MatchIntelligence,match_id)
    data=dict(intel.data or {}) if intel else {}
    audit=list(data.get("credit_audit",[]))
    audit.append({"player_id":payload.player_id,"player_name":player.name if player else payload.player_id,
                  "credits":payload.credits,"previous_credits":old_credit,
                  "source_label":payload.source_label.strip(),"source_url":source_url,
                  "verification":"admin_confirmed_manual_entry","updated_at":datetime.now(timezone.utc).isoformat()})
    data["credit_audit"]=audit
    if intel:
        intel.data=data
    else:
        db.add(MatchIntelligence(match_id=match_id,data=data))
    db.commit()
    rows=db.scalars(select(MatchSquad).where(MatchSquad.match_id==match_id)).all()
    missing=[]
    for row in rows:
        if row.credits is None:
            p=db.get(Player,row.player_id)
            missing.append(p.name if p else row.player_id)
    return {"saved":True,"match_id":match_id,"player_id":payload.player_id,
            "credits":squad.credits,"credit_source":"manual_verified",
            "credits_verified_count":len(rows)-len(missing),
            "credits_missing_count":len(missing),"credits_missing_players":missing,
            "credits_ready_for_team_builder":bool(rows) and not missing}


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
        player_name=data.pop("player_name",None)
        data["source"]=payload.source
        player=db.get(Player,data["player_id"])
        if player is None and player_name:
            player=Player(id=data["player_id"],name=player_name)
            db.add(player)
        if player is None:
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




def _teamgeneration_request(url: str):
    if not TG_API_TOKEN:
        raise HTTPException(503, "Team Generation importer is not configured. Add a fresh TG_API_TOKEN in Render.")
    try:
        response = httpx.get(
            url,
            headers={
                "Authorization": "Bearer " + TG_API_TOKEN,
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
            timeout=25.0,
            follow_redirects=False,
            trust_env=False,
        )
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not reach Team Generation API: " + type(exc).__name__)
    if response.status_code == 401:
        raise HTTPException(502, "Team Generation rejected TG_API_TOKEN (401). Sign in again and replace the expired or invalid token in Render.")
    if response.status_code == 304:
        raise HTTPException(502, "Team Generation returned 304 without a response body. Retry with browser cache disabled or refresh the source data.")
    if response.status_code >= 400:
        raise HTTPException(502, detail={
            "message": "Team Generation upstream request failed.",
            "upstream_status": response.status_code,
            "response": response.text[:2000],
        })
    try:
        return response.json()
    except ValueError:
        raise HTTPException(502, "Team Generation returned a non-JSON response.")


@app.get("/api/v1/admin/teamgeneration/fixtures")
def list_teamgeneration_fixtures(_admin: bool = Depends(require_admin)):
    payload = _teamgeneration_request("https://v2.tgsoftware-api.online/matches?sport=cricket")
    if not isinstance(payload, list):
        raise HTTPException(502, "Unexpected Team Generation fixture response; expected a JSON list.")
    matches = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        left = item.get("left") or {}
        right = item.get("right") or {}
        matches.append({
            "id": str(item.get("id") or ""),
            "series": item.get("series"),
            "startTime": item.get("startTime"),
            "status": item.get("status"),
            "lineupStatus": item.get("lineupStatus"),
            "left": {"name": left.get("name"), "code": left.get("code"), "image": left.get("image")},
            "right": {"name": right.get("name"), "code": right.get("code"), "image": right.get("image")},
            "transferTargets": item.get("transferTargets") or [],
        })
    return {"source": "Team Generation", "count": len(matches), "matches": matches}


@app.post("/api/v1/admin/import/teamgeneration/{match_id}")
def import_teamgeneration_match(match_id: str, _admin: bool = Depends(require_admin),
                                db: Session = Depends(get_db)):
    if not match_id or len(match_id) > 50 or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in match_id
    ):
        raise HTTPException(422, "Invalid Team Generation match ID.")
    payload = _teamgeneration_request("https://v2.tgsoftware-api.online/matches/" + match_id)
    match_data = payload.get("match") if isinstance(payload, dict) else None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(match_data, dict) or not isinstance(detail, dict) or not isinstance(detail.get("players"), list):
        raise HTTPException(422, "Team Generation response does not contain match details and a players list.")
    if str(match_data.get("id")) != match_id:
        raise HTTPException(422, "Team Generation returned a different match ID.")
    left = match_data.get("left") or {}
    right = match_data.get("right") or {}
    left_name = str(left.get("code") or left.get("name") or "TEAM_A")
    right_name = str(right.get("code") or right.get("name") or "TEAM_B")
    series = str(match_data.get("series") or "Cricket")
    match_format = "ODI" if "ODI" in series.upper() else ("TEST" if "TEST" in series.upper() else "T20")
    match_values = {
        "name": left_name + " vs " + right_name + " - " + series,
        "format": match_format,
        "start_time": match_data.get("startTime"),
        "venue": None,
        "team_a": left_name,
        "team_b": right_name,
        "status": str(match_data.get("status") or "upcoming"),
        "source": "Team Generation",
    }
    match = db.get(Match, match_id)
    if match is None:
        match = Match(id=match_id, **match_values)
        db.add(match)
    else:
        for key, value in match_values.items():
            setattr(match, key, value)

    role_map = {0: "WK", 1: "BAT", 2: "AR", 3: "BOWL"}
    lineup_status = str(detail.get("lineupStatus") or match_data.get("lineupStatus") or "unknown").lower()
    saved = 0
    credits_saved = 0
    missing_credits = []
    profile_source = "TEAM_GENERATION"

    for item in detail["players"]:
        if not isinstance(item, dict) or item.get("playerId") is None or not item.get("name"):
            continue
        source_player_id = str(item["playerId"])
        player_id = "TG-" + source_player_id
        name = str(item["name"]).strip()
        role_value = item.get("role")
        try:
            role_code = int(role_value)
        except (TypeError, ValueError):
            role_code = -1
        role = role_map.get(role_code, "BAT")

        team_value = item.get("team")
        try:
            team_code = int(team_value)
        except (TypeError, ValueError):
            team_code = -1
        team = left_name if team_code == 0 else right_name if team_code == 1 else "UNKNOWN"

        raw_credit = item.get("credits")
        try:
            credit = float(raw_credit) if raw_credit is not None else None
        except (TypeError, ValueError):
            credit = None
        if credit is not None and not (0 < credit <= 20):
            credit = None

        raw_ownership = item.get("ownership")
        try:
            selection_pct = float(raw_ownership) if raw_ownership is not None else None
        except (TypeError, ValueError):
            selection_pct = None
        if selection_pct is not None and not (0 <= selection_pct <= 100):
            selection_pct = None

        try:
            playing_flag = int(item.get("playing") or 0)
        except (TypeError, ValueError):
            playing_flag = 0
        if playing_flag == 1:
            player_status = "playing"
        elif "announc" in lineup_status:
            player_status = "not_announced"
        else:
            player_status = "not_playing"

        player = db.get(Player, player_id)
        if player is None:
            db.add(Player(id=player_id, name=name))
        else:
            player.name = name

        squad = db.get(MatchSquad, (match_id, player_id))
        # Preserve an admin-verified correction when this match is re-imported.
        final_credit = squad.credits if squad and squad.source == "manual_verified" else credit
        if final_credit is not None:
            credits_saved += 1
        else:
            missing_credits.append(name)
        squad_values = {
            "team": team,
            "role": role,
            "credits": final_credit,
            "selection_pct": selection_pct,
            "status": player_status,
            "source": "manual_verified" if squad and squad.source == "manual_verified" else profile_source,
        }
        if squad is None:
            db.add(MatchSquad(match_id=match_id, player_id=player_id, **squad_values))
        else:
            for key, value in squad_values.items():
                setattr(squad, key, value)

        profile_data = {
            "source_player_id": source_player_id,
            "image": item.get("image"),
            "role_code": role_code,
            "team_code": team_code,
            "player_type": item.get("playerType"),
            "batting_order": item.get("battingOrder"),
            "lineup_order": item.get("lineupOrder"),
            "playing": item.get("playing"),
            "last_play": item.get("lastPlay"),
            "in_dream_team": item.get("inDreamTeam"),
            "ownership": item.get("ownership"),
            "captain_pct": item.get("captainPct"),
            "vice_captain_pct": item.get("viceCaptainPct"),
            "fantasy_ids": item.get("fantasyIds") or {},
        }
        profile = db.get(PlayerSourceProfile, (match_id, player_id, profile_source))
        if profile is None:
            db.add(PlayerSourceProfile(match_id=match_id, player_id=player_id,
                                       source=profile_source, data=profile_data))
        else:
            profile.data = profile_data
        saved += 1

    if saved == 0:
        db.rollback()
        raise HTTPException(422, "No valid player records were found in the Team Generation response.")

    intel = db.get(MatchIntelligence, match_id)
    intel_data = {
        "source": "Team Generation",
        "source_match_id": match_id,
        "lineup_status": lineup_status,
        "toss": detail.get("toss"),
        "imported_player_count": saved,
        "teamgeneration_updated_at": detail.get("updatedAt"),
        "team_images": {"left": left.get("image"), "right": right.get("image")},
    }
    if intel is None:
        db.add(MatchIntelligence(match_id=match_id, data=intel_data))
    else:
        intel.data = {**(intel.data or {}), **intel_data}
    db.commit()

    rows = db.scalars(select(MatchSquad).where(MatchSquad.match_id == match_id)).all()
    missing = []
    for row in rows:
        if row.credits is None:
            player = db.get(Player, row.player_id)
            missing.append(player.name if player else row.player_id)
    return {
        "imported": True,
        "source": "Team Generation",
        "match_id": match_id,
        "match": match_values,
        "players_imported": saved,
        "credits_verified_count": len(rows) - len(missing),
        "credits_missing_count": len(missing),
        "credits_missing_players": missing,
        "credits_ready_for_team_builder": bool(rows) and not missing,
        "source_profiles_saved": saved,
        "team_mapping": {"0": left_name, "1": right_name},
        "role_mapping": {"0": "WK", "1": "BAT", "2": "AR", "3": "BOWL"},
        "note": "Lineup-not-announced players are not marked unavailable. Player IDs are namespaced with TG- to avoid collisions with other import sources.",
    }


@app.get("/api/v1/admin/teamgeneration/matches/{match_id}/inspect")
def inspect_teamgeneration_match(match_id: str, _admin: bool = Depends(require_admin)):
    """Fetch one Team Generation match using a server-side token; never return or log credentials."""
    if not TG_API_TOKEN:
        raise HTTPException(
            503,
            detail="Team Generation importer is not configured. Add TG_API_TOKEN to Render environment variables."
        )
    if not match_id or len(match_id) > 50 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in match_id):
        raise HTTPException(422, "Invalid Team Generation match ID.")
    url = f"https://v2.tgsoftware-api.online/matches/{match_id}"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=False, trust_env=False) as client:
            response = client.get(
                url,
                headers={"Authorization": f"Bearer {TG_API_TOKEN}", "Accept": "application/json"}
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {"response_text": response.text[:4000]}
        if response.status_code == 401:
            raise HTTPException(
                502,
                detail="Team Generation rejected TG_API_TOKEN (401). Check that the correct authorized access token is set in Render."
            )
        if response.status_code >= 400:
            raise HTTPException(
                502,
                detail={"message": "Team Generation upstream request failed.", "upstream_status": response.status_code, "response": payload}
            )
        return {
            "source": "Team Generation",
            "match_id": match_id,
            "upstream_status": response.status_code,
            "data": payload
        }
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Could not reach Team Generation API: {type(exc).__name__}")


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Preet Fantasy AI Import</title><style>body{font:16px system-ui;max-width:650px;margin:40px auto;padding:20px;background:#f5f7f8}input,button{width:100%;padding:14px;box-sizing:border-box;margin-top:12px}button{background:#16a878;color:white;border:0;border-radius:8px;font-weight:700}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#17212b;color:#e8fff4;padding:14px;border-radius:8px}</style></head>
    <body><h2>Preet Fantasy AI — Import Centre</h2>
    <section style="background:white;padding:16px;border-radius:12px;margin-bottom:18px">
      <h3>Source 1 — AI11</h3>
    <p>Paste one AI11 match URL (Fantasy or Analysis). The matching page is detected automatically.</p>
    <input id="url" type="url" placeholder="Paste AI11 match URL">
    <button id="go">Fetch match data</button><pre id="out">Ready.</pre>
    <section id="credits" hidden><h3>Missing player credits</h3>
      <p>Enter only a value checked against a reliable source. The source URL is saved with the correction.</p>
      <div id="creditRows"></div><pre id="creditStatus"></pre>
    </section>
    <script>
    let adminToken='', currentMatchId='';
    const headers=()=>({'Content-Type':'application/json','X-Admin-Token':adminToken});
    async function loadCredits(matchId){
      const r=await fetch('/api/v1/admin/matches/'+encodeURIComponent(matchId)+'/credits',{headers:headers()});
      const data=await r.json();
      const section=document.getElementById('credits'), rows=document.getElementById('creditRows');
      section.hidden=false; rows.innerHTML='';
      const missing=(data.credits_missing_players||[]);
      if(!missing.length){rows.textContent='All squad players have credits.';}
      missing.forEach(p=>{
        const card=document.createElement('div');
        card.style='background:white;border:1px solid #ccd3d8;border-radius:8px;padding:12px;margin:12px 0';
        const heading=document.createElement('strong'); heading.textContent=p.player_name+' ('+p.team+')';
        const credit=document.createElement('input'); credit.type='number';credit.min='0.1';credit.max='20';credit.step='0.5';credit.placeholder='Player credits';
        const save=document.createElement('button');save.textContent='Save credit';
        const msg=document.createElement('small');msg.style='display:block;margin-top:8px';
        save.onclick=async()=>{
          const value=Number(credit.value);
          if(!(value>0&&value<=20)){msg.textContent='Enter a credit greater than 0 and at most 20.';return;}
          save.disabled=true;msg.textContent='Saving…';
          try{
            const response=await fetch('/api/v1/admin/matches/'+encodeURIComponent(currentMatchId)+'/credits',{method:'POST',headers:headers(),body:JSON.stringify({player_id:p.player_id,credits:value})});
            const result=await response.json();msg.textContent=response.ok?'Saved. Missing: '+result.credits_missing_count:JSON.stringify(result);
            if(response.ok)await loadCredits(currentMatchId);
          }catch(e){msg.textContent='Request failed: '+e.message;}
          finally{save.disabled=false;}
        };
        card.append(heading,credit,save,msg);rows.append(card);
      });
      document.getElementById('creditStatus').textContent=JSON.stringify({credits_verified_count:data.credits_verified_count,credits_missing_count:data.credits_missing_count,credits_ready_for_team_builder:data.credits_ready_for_team_builder},null,2);
    }
    document.getElementById('go').onclick=async()=>{
      if(!adminToken)adminToken=prompt('Enter admin token once for this page session:')||'';
      if(!adminToken)return;
      const url=document.getElementById('url').value.trim();
      const out=document.getElementById('out');out.textContent='Fetching match data…';
      try{
        if(!url){out.textContent='Please paste an AI11 match URL first.';return;}
        const r=await fetch('/api/v1/admin/import/ai11',{method:'POST',headers:headers(),body:JSON.stringify({analysis_url:url})});
        const raw=await r.text();let data;
        try{data=JSON.parse(raw);}catch(_){data={message:'Server returned a non-JSON response',http_status:r.status,response:raw.slice(0,4000)};}
        out.textContent=JSON.stringify({http_status:r.status,...(data&&typeof data==='object'?data:{response:data})},null,2);
        if(r.ok&&data.match_id){currentMatchId=data.match_id;await loadCredits(currentMatchId);}
        if(r.status===401)adminToken='';
      }catch(e){out.textContent='Network/request error: '+e.message;}
    };
    async function ensureAdminToken(){if(!adminToken)adminToken=prompt('Enter Preet Fantasy AI admin token:')||'';return !!adminToken;}
    </script>
    </section>
    <section style="background:white;padding:16px;border-radius:12px;margin:18px 0">
      <h3>Source 2 — Team Generation</h3>
      <p>Uses the authorized Team Generation access token configured privately as TG_API_TOKEN in Render. No source token is entered into this page.</p>
      <button id="tgLoad">Load upcoming cricket matches</button>
      <div id="tgMatches"></div><pre id="tgOut">Ready.</pre>
    </section>
    <script>
    async function loadTgMatches(){
      if(!await ensureAdminToken())return;
      const box=document.getElementById('tgMatches'),out=document.getElementById('tgOut');
      box.textContent='Loading fixtures…';out.textContent='Connecting to Team Generation…';
      try{
        const r=await fetch('/api/v1/admin/teamgeneration/fixtures',{headers:headers()});
        const data=await r.json();
        if(!r.ok){box.textContent='Could not load fixtures.';out.textContent=JSON.stringify(data,null,2);if(r.status===401)adminToken='';return;}
        box.innerHTML='';
        (data.matches||[]).forEach(m=>{
          const card=document.createElement('div');
          card.style='border:1px solid #ccd3d8;border-radius:8px;padding:12px;margin:10px 0;background:#fafafa';
          const title=document.createElement('strong');
          title.textContent=(m.left.code||m.left.name)+' vs '+(m.right.code||m.right.name)+' — '+(m.series||'Cricket');
          const meta=document.createElement('small');meta.style='display:block;margin:6px 0';
          meta.textContent='ID: '+m.id+' | '+(m.startTime||'')+' | '+(m.lineupStatus||'lineup unknown');
          const btn=document.createElement('button');btn.textContent='Import players and credits';
          btn.onclick=async()=>{
            btn.disabled=true;out.textContent='Importing '+m.id+'…';
            try{
              const response=await fetch('/api/v1/admin/import/teamgeneration/'+encodeURIComponent(m.id),{method:'POST',headers:headers()});
              const result=await response.json();out.textContent=JSON.stringify({http_status:response.status,...result},null,2);
              if(response.ok&&result.match_id){currentMatchId=result.match_id;await loadCredits(currentMatchId);}
              if(response.status===401)adminToken='';
            }catch(e){out.textContent='Import failed: '+e.message;}
            finally{btn.disabled=false;}
          };
          card.append(title,meta,btn);box.append(card);
        });
        out.textContent='Loaded '+(data.count||0)+' fixtures.';
      }catch(e){box.textContent='Request failed.';out.textContent=e.message;}
    }
    document.getElementById('tgLoad').onclick=loadTgMatches;
    </script></body></html>"""
