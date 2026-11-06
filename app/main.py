from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, Response
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from sqlalchemy.orm import Session
from sqlalchemy import select
import secrets
import httpx
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from app.database import Base, engine, get_db, SessionLocal
from app.models import Match, Player, MatchSquad, PlayerMatchStats, MatchIntelligence, PlayerSourceProfile, Venue
from app.schemas import (MatchIn, PlayerIdentityIn, SquadImport, StatsImport,
                         TeamRequest, MatchIntelligenceIn, SquadPlayerEdit, AI11ImportRequest, HistoricalBatchImport, ManualCreditUpdate, PlayingXIUpdate, CricbuzzVenueImportRequest, CricbuzzSeriesImportRequest, CricbuzzSeriesIndexImportRequest, VenueEnrichRequest)
from app.predictor import predict_match
from app.optimizer import build_teams
from app.config import MODEL_VERSION, ADMIN_TOKEN, TG_API_TOKEN
from app.importers.ai11 import (fetch_page, parse_analysis, parse_fantasy, AI11RateLimitError)
from app.importers.crex import fetch_crex_page, parse_crex_venue_report
from app.importers.cricbuzz import (fetch_cricbuzz_venue_page, fetch_cricbuzz_series_page,
    fetch_cricbuzz_series_index, parse_cricbuzz_venue, parse_cricbuzz_series_venues,
    parse_cricbuzz_series_index)
from app.venue_analysis import analyse_venue, compare_squad_strength, analysis_context_fields
from app.public_feed import normalize_fixture, sort_fixture_key, classify_fixture_status
from app.public_page import render_home, render_sitemap
from app.match_page import render_match_detail

Base.metadata.create_all(bind=engine)
app = FastAPI(
    title="Preet Fantasy AI",
    description="Format-specific cricket match intelligence, transparent player estimates and constrained fantasy team generation. Predictions are estimates, not guarantees.",
    version="0.2.0",
)

_PUBLIC_SYNC_LOCK = threading.Lock()
_PUBLIC_SYNC_INTERVAL_SECONDS = 300
_last_public_sync_monotonic = 0.0
_last_public_sync_at: str | None = None
_last_public_sync_summary: dict = {"ok": False, "message": "First sync has not run yet."}
_public_sync_thread: threading.Thread | None = None


def _sync_public_match_feed(db: Session, force: bool = False) -> dict:
    global _last_public_sync_monotonic, _last_public_sync_at, _last_public_sync_summary
    now_mono = time.monotonic()
    if not force and now_mono - _last_public_sync_monotonic < _PUBLIC_SYNC_INTERVAL_SECONDS:
        return dict(_last_public_sync_summary)
    if not _PUBLIC_SYNC_LOCK.acquire(blocking=False):
        return dict(_last_public_sync_summary)
    try:
        now_mono = time.monotonic()
        if not force and now_mono - _last_public_sync_monotonic < _PUBLIC_SYNC_INTERVAL_SECONDS:
            return dict(_last_public_sync_summary)
        # Prevent every visitor from retrying the upstream request during an outage.
        _last_public_sync_monotonic = now_mono
        payload = _teamgeneration_request("https://v2.tgsoftware-api.online/matches?sport=cricket")
        if not isinstance(payload, list):
            raise ValueError("Team Generation fixture feed did not return a list.")

        synced_at = datetime.now(timezone.utc).isoformat()
        seen_ids: set[str] = set()
        created = updated = hidden = skipped = 0
        for item in payload:
            if not isinstance(item, dict):
                skipped += 1
                continue
            record = normalize_fixture(item)
            if not record:
                skipped += 1
                continue
            match_id = record["id"]
            seen_ids.add(match_id)
            match = db.get(Match, match_id)
            values = {
                "name": record["name"],
                "format": record["format"],
                "start_time": record["start_time"],
                "venue": record["venue"],
                "team_a": record["team_a"],
                "team_b": record["team_b"],
                "status": record["status"],
                "source": "Team Generation",
            }
            if match is None:
                match = Match(id=match_id, **values)
                db.add(match)
                created += 1
            else:
                for key, value in values.items():
                    if key == "venue" and value is None and match.venue:
                        continue
                    setattr(match, key, value)
                updated += 1

            db.flush()
            intel = db.get(MatchIntelligence, match_id)
            intel_data = dict(intel.data or {}) if intel and isinstance(intel.data, dict) else {}
            intel_data["public_feed"] = {
                "source": "Team Generation",
                "series": record["series"],
                "team_a_name": record["team_a_name"],
                "team_b_name": record["team_b_name"],
                "team_a_image": record["team_a_image"],
                "team_b_image": record["team_b_image"],
                "source_status": record["source_status"],
                "lineup_status": record["lineup_status"],
                "public_listed": bool(record["visible"]),
                "last_seen_at": synced_at,
                "synced_at": synced_at,
            }
            if intel is None:
                db.add(MatchIntelligence(match_id=match_id, data=intel_data))
            else:
                intel.data = intel_data
            if not record["visible"]:
                hidden += 1

        # Hide provider-omitted fixtures from the public list but keep their
        # Match, squad, scorecards and player-history rows in SQL.
        existing_rows = db.scalars(
            select(Match).where(Match.source == "Team Generation")
        ).all()
        for match in existing_rows:
            if match.id in seen_ids:
                continue
            intel = db.get(MatchIntelligence, match.id)
            intel_data = dict(intel.data or {}) if intel and isinstance(intel.data, dict) else {}
            public_feed = dict(intel_data.get("public_feed") or {})

            # Some fixture feeds list only upcoming games and drop a match as
            # soon as it starts. Keep an omitted match visible through a
            # format-aware playing window instead of removing it at kickoff.
            if match.status not in {"completed", "cancelled"}:
                time_status = classify_fixture_status("", match.start_time, match.format)
            else:
                time_status = match.status

            if time_status == "upcoming":
                match.status = "postponed" if match.status == "postponed" else "upcoming"
                public_feed["public_listed"] = True
                public_feed["visibility_basis"] = "scheduled_start_time"
                public_feed["source_status"] = public_feed.get("source_status") or "not_returned_in_latest_feed"
            elif time_status == "live":
                match.status = "live"
                public_feed["public_listed"] = True
                public_feed["visibility_basis"] = "format_playing_window"
                public_feed["source_status"] = public_feed.get("source_status") or "not_returned_in_latest_feed"
            else:
                if public_feed.get("public_listed") is not False:
                    hidden += 1
                match.status = "cancelled" if time_status == "cancelled" else "completed"
                public_feed["public_listed"] = False
                public_feed["removed_from_public_list_at"] = synced_at
                public_feed["visibility_basis"] = "provider_completion_or_expired_playing_window"

            public_feed["last_sync_check_at"] = synced_at
            intel_data["public_feed"] = public_feed
            if intel is None:
                db.add(MatchIntelligence(match_id=match.id, data=intel_data))
            else:
                intel.data = intel_data

        db.commit()
        summary = {
            "ok": True,
            "source": "Team Generation",
            "received": len(payload),
            "created": created,
            "updated": updated,
            "hidden": hidden,
            "skipped": skipped,
            "synced_at": synced_at,
        }
        _last_public_sync_at = synced_at
        _last_public_sync_summary = summary
        return dict(summary)
    except HTTPException as exc:
        db.rollback()
        summary = {"ok": False, "message": str(exc.detail)[:300], "synced_at": _last_public_sync_at}
        _last_public_sync_summary = summary
        return dict(summary)
    except Exception as exc:
        db.rollback()
        summary = {"ok": False, "message": "Fixture sync failed: " + type(exc).__name__, "synced_at": _last_public_sync_at}
        _last_public_sync_summary = summary
        return dict(summary)
    finally:
        _PUBLIC_SYNC_LOCK.release()


def _public_match_records(db: Session) -> list[dict]:
    rows = db.scalars(select(Match).where(Match.source == "Team Generation")).all()
    if not rows:
        return []
    ids = [row.id for row in rows]
    intelligence_rows = db.scalars(
        select(MatchIntelligence).where(MatchIntelligence.match_id.in_(ids))
    ).all()
    intelligence = {row.match_id: (row.data or {}) for row in intelligence_rows}
    records = []
    for match in rows:
        data = intelligence.get(match.id) or {}
        feed = data.get("public_feed") or {}
        if feed.get("public_listed") is False:
            continue
        if match.status not in {"upcoming", "live", "postponed"}:
            continue
        records.append({
            "id": match.id,
            "name": match.name,
            "format": match.format,
            "start_time": match.start_time,
            "venue": match.venue,
            "team_a": match.team_a,
            "team_b": match.team_b,
            "team_a_name": feed.get("team_a_name") or match.team_a,
            "team_b_name": feed.get("team_b_name") or match.team_b,
            "team_a_image": feed.get("team_a_image"),
            "team_b_image": feed.get("team_b_image"),
            "series": feed.get("series") or match.name,
            "status": match.status,
            "source_status": feed.get("source_status"),
        })
    return sorted(records, key=sort_fixture_key)


def _public_site_base(request: Request) -> str:
    configured = os.getenv("PUBLIC_SITE_URL", "").strip()
    return (configured or str(request.base_url)).rstrip("/")


def _public_sync_worker() -> None:
    # Give the ASGI server a moment to accept the first homepage request;
    # the request path can perform the initial sync itself.
    time.sleep(2)
    while True:
        try:
            with SessionLocal() as db:
                _sync_public_match_feed(db, force=True)
        except Exception:
            pass
        time.sleep(_PUBLIC_SYNC_INTERVAL_SECONDS)


@app.on_event("startup")
def start_public_fixture_sync():
    global _public_sync_thread
    if _public_sync_thread and _public_sync_thread.is_alive():
        return
    _public_sync_thread = threading.Thread(
        target=_public_sync_worker,
        name="preet-public-fixture-sync",
        daemon=True,
    )
    _public_sync_thread.start()


@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    _sync_public_match_feed(db, force=False)
    matches = _public_match_records(db)
    template_path = Path(__file__).with_name("home.html")
    if not template_path.is_file():
        raise HTTPException(500, "Public homepage template is missing.")
    base_url = _public_site_base(request)
    return HTMLResponse(
        render_home(template_path.read_text(encoding="utf-8"), matches, base_url, _last_public_sync_at),
        headers={"Cache-Control": "public, max-age=60"},
    )



def _load_public_match_detail(match_id: str, db: Session) -> dict:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(404, "Match not found.")

    intel_row = db.get(MatchIntelligence, match_id)
    intel = dict(intel_row.data or {}) if intel_row and isinstance(intel_row.data, dict) else {}
    existing_squads = db.scalars(
        select(MatchSquad).where(MatchSquad.match_id == match_id)
    ).all()
    last_detail_sync = parse_source_datetime(intel.get("public_detail_imported_at"))
    now = datetime.now(timezone.utc)
    detail_stale = last_detail_sync is None or (now - last_detail_sync) >= timedelta(minutes=15)
    import_note = "Squad data is loaded from the connected Team Generation match source."
    import_ok = True

    if match.source == "Team Generation" and (not existing_squads or detail_stale):
        try:
            # Reuse the already-tested importer so the detail page stores the
            # same player IDs, roles, photos, credits, XI flags and trends
            # used by the admin team builder.
            import_result = import_teamgeneration_match(match_id, _admin=True, db=db)
            source_status = (import_result.get("match") or {}).get("status")
            normalized_status = classify_fixture_status(source_status, match.start_time, match.format)
            if normalized_status in {"upcoming", "live", "completed", "cancelled", "postponed"}:
                match.status = normalized_status

            fresh_intel_row = db.get(MatchIntelligence, match_id)
            fresh_intel = dict(fresh_intel_row.data or {}) if fresh_intel_row and isinstance(fresh_intel_row.data, dict) else {}
            fresh_intel["public_detail_imported_at"] = now.isoformat()
            fresh_intel["public_detail_import_status"] = "success"
            fresh_intel["public_detail_imported_players"] = import_result.get("players_imported", 0)
            if fresh_intel_row is None:
                db.add(MatchIntelligence(match_id=match_id, data=fresh_intel))
            else:
                fresh_intel_row.data = fresh_intel
            db.commit()
            import_note = (
                f"Player squad refreshed from Team Generation: "
                f"{import_result.get('players_imported', 0)} players imported; "
                f"{import_result.get('credits_verified_count', 0)} credits verified."
            )
            intel = fresh_intel
        except HTTPException as exc:
            db.rollback()
            import_ok = False
            detail = exc.detail
            import_note = (
                str(detail) if isinstance(detail, str)
                else "The fixture is saved, but the source could not provide its full player data right now."
            )
        except Exception as exc:
            db.rollback()
            import_ok = False
            import_note = "The fixture is saved, but player details could not be refreshed (" + type(exc).__name__ + ")."

    # Refresh ORM state after the importer may have updated the fixture and squads.
    match = db.get(Match, match_id)
    intel_row = db.get(MatchIntelligence, match_id)
    intel = dict(intel_row.data or {}) if intel_row and isinstance(intel_row.data, dict) else {}
    squad_rows = db.scalars(
        select(MatchSquad).where(MatchSquad.match_id == match_id)
    ).all()

    profiles = db.scalars(
        select(PlayerSourceProfile).where(PlayerSourceProfile.match_id == match_id)
    ).all()
    profile_map: dict[str, dict] = {}
    for profile in profiles:
        profile_map.setdefault(profile.player_id, {}).update(profile.data or {})

    players = []
    for squad in squad_rows:
        player = db.get(Player, squad.player_id)
        profile = profile_map.get(squad.player_id, {})
        players.append({
            "player_id": squad.player_id,
            "player_name": player.name if player else squad.player_id,
            "team": squad.team,
            "role": squad.role,
            "credits": squad.credits,
            "selection_pct": squad.selection_pct,
            "status": squad.status,
            "image": profile.get("image"),
            "captain_pct": profile.get("captain_pct", profile.get("ai11_captain_pct")),
            "vice_captain_pct": profile.get("vice_captain_pct", profile.get("ai11_vice_captain_pct")),
        })

    stat_rows = db.scalars(
        select(PlayerMatchStats).where(PlayerMatchStats.match_id == match_id)
    ).all()
    scorecards = []
    for row in stat_rows:
        player = db.get(Player, row.player_id)
        squad = next((item for item in squad_rows if item.player_id == row.player_id), None)
        scorecards.append({
            "player_name": player.name if player else row.player_id,
            "team": squad.team if squad else None,
            "runs": row.runs,
            "balls": row.balls,
            "fours": row.fours,
            "sixes": row.sixes,
            "wickets": row.wickets,
            "fantasy_points": row.fantasy_points,
        })

    feed = intel.get("public_feed") or {}
    match_data = {
        "id": match.id,
        "name": match.name,
        "format": match.format,
        "start_time": match.start_time,
        "venue": match.venue,
        "team_a": match.team_a,
        "team_b": match.team_b,
        "status": match.status,
        "team_a_name": feed.get("team_a_name") or match.team_a,
        "team_b_name": feed.get("team_b_name") or match.team_b,
        "series": feed.get("series") or match.name,
    }
    if not players and import_ok:
        import_note = "The match fixture is saved, but the provider has not supplied a player squad for this match yet."
    return {
        "match": match_data,
        "intelligence": intel,
        "players": players,
        "scorecards": scorecards,
        "import_ok": import_ok,
        "import_note": import_note,
        "last_detail_sync": intel.get("public_detail_imported_at"),
    }


@app.get("/match/{match_id}", response_class=HTMLResponse)
def public_match_detail_page(match_id: str, request: Request, db: Session = Depends(get_db)):
    detail = _load_public_match_detail(match_id, db)
    template_path = Path(__file__).with_name("match.html")
    if not template_path.is_file():
        raise HTTPException(500, "Public match detail template is missing.")
    base_url = _public_site_base(request)
    return HTMLResponse(
        render_match_detail(
            template_path.read_text(encoding="utf-8"),
            detail["match"],
            detail["intelligence"],
            detail["players"],
            detail["scorecards"],
            base_url,
            detail["import_note"],
            detail["import_ok"],
        ),
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.get("/api/v1/public/matches/{match_id}")
def public_match_detail_api(match_id: str, db: Session = Depends(get_db)):
    detail = _load_public_match_detail(match_id, db)
    return detail


@app.get("/api/v1/public/matches")
def public_matches_api(db: Session = Depends(get_db)):
    sync = _sync_public_match_feed(db, force=False)
    matches = _public_match_records(db)
    return {
        "count": len(matches),
        "matches": matches,
        "last_sync": _last_public_sync_at,
        "sync": sync,
        "note": "Completed/cancelled fixtures are hidden immediately. Omitted fixtures remain visible during their format-aware playing window, then are hidden; SQL match and player-history records are retained."
    }


@app.get("/robots.txt", response_class=Response)
def robots_txt(request: Request):
    base_url = _public_site_base(request)
    return Response(
        "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/v1/admin/\nDisallow: /docs\nDisallow: /redoc\nSitemap: " + base_url + "/sitemap.xml\n",
        media_type="text/plain",
    )


@app.get("/sitemap.xml", response_class=Response)
def sitemap_xml(request: Request, db: Session = Depends(get_db)):
    _sync_public_match_feed(db, force=False)
    base_url = _public_site_base(request)
    return Response(
        render_sitemap(base_url, _public_match_records(db)),
        media_type="application/xml",
    )

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


@app.post("/api/v1/admin/public-matches/sync")
def admin_sync_public_matches(_admin: bool = Depends(require_admin),
                              db: Session = Depends(get_db)):
    result = _sync_public_match_feed(db, force=True)
    if not result.get("ok"):
        raise HTTPException(502, result.get("message") or "Fixture sync failed.")
    result["visible_matches"] = len(_public_match_records(db))
    return result

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
                             _admin: bool = Depends(require_admin),
                             db: Session = Depends(get_db)):
    if not db.get(Match,match_id): raise HTTPException(404,"Match not found")
    match = db.get(Match, match_id)
    row=db.get(MatchIntelligence,match_id)
    data=payload.model_dump(exclude_unset=True)
    if data.get("venue"):
        match.venue = data["venue"].strip()
    merged = dict(row.data or {}) if row and isinstance(row.data, dict) else {}
    merged.update(data)
    if row is None: db.add(MatchIntelligence(match_id=match_id,data=merged))
    else: row.data=merged
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
        "venue": (
            (match_data.get("venue") or match_data.get("ground") or {}).get("name")
            if isinstance(match_data.get("venue") or match_data.get("ground"), dict)
            else (match_data.get("venue") or match_data.get("ground") or match_data.get("venueName"))
        ),
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
        if not match_values.get("venue") and match.venue:
            match_values["venue"] = match.venue
        for key, value in match_values.items():
            setattr(match, key, value)

    role_map = {0: "WK", 1: "BAT", 2: "AR", 3: "BOWL"}
    lineup_status = str(detail.get("lineupStatus") or match_data.get("lineupStatus") or "unknown").lower()
    lineup_not_announced = any(marker in lineup_status for marker in ("not_announced", "not announced", "unannounced", "pending"))
    provider_playing_counts = {0: 0, 1: 0}
    for candidate in detail["players"]:
        if not isinstance(candidate, dict):
            continue
        try:
            is_playing = int(candidate.get("playing") or 0) == 1
            team_code = int(candidate.get("team"))
        except (TypeError, ValueError):
            continue
        if is_playing and team_code in provider_playing_counts:
            provider_playing_counts[team_code] += 1
    provider_xi_complete = provider_playing_counts[0] == 11 and provider_playing_counts[1] == 11
    lineup_confirmed = (
        (any(marker in lineup_status for marker in ("announc", "confirmed", "complete", "final"))
         and not lineup_not_announced)
        or provider_xi_complete
    )
    previous_intel = db.get(MatchIntelligence, match_id)
    previous_intel_data = dict(previous_intel.data or {}) if previous_intel and isinstance(previous_intel.data, dict) else {}
    admin_selected_ids = set(previous_intel_data.get("lineup_selected_player_ids") or [])
    preserve_admin_lineup = previous_intel_data.get("lineup_admin_source") == "admin_confirmed" and not lineup_confirmed
    imported_playing_ids = []
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
        if preserve_admin_lineup:
            player_status = "playing" if player_id in admin_selected_ids else "not_playing"
            if player_status == "playing":
                imported_playing_ids.append(player_id)
        elif playing_flag == 1 and lineup_confirmed:
            player_status = "playing"
            imported_playing_ids.append(player_id)
        elif not lineup_confirmed:
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
            "points": item.get("points", item.get("fantasyPoints")),
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
        "lineup_confirmed": lineup_confirmed,
        "lineup_selected_player_ids": imported_playing_ids,
        "toss": detail.get("toss"),
        "toss_completed": bool(detail.get("toss") or match_data.get("toss")),
        "imported_player_count": saved,
        "teamgeneration_updated_at": detail.get("updatedAt"),
        "team_images": {"left": left.get("image"), "right": right.get("image")},
    }
    if intel is None:
        db.add(MatchIntelligence(match_id=match_id, data=intel_data))
    else:
        # Keep admin-selected pitch/toss/fixed-player preferences when refreshing source data.
        existing_intel = dict(intel.data or {})
        for key in ("pitch_type", "pitch_notes", "batting_friendly", "pace_friendly",
                    "spin_friendly", "strong_team", "toss_completed", "toss_winner",
                    "toss_decision", "fixed_player_ids", "lineup_admin_source",
                    "lineup_admin_updated_at"):
            if key in existing_intel and key not in intel_data:
                intel_data[key] = existing_intel[key]
        # An explicit admin XI confirmation is preserved only if provider still says unannounced;
        # once provider announces the XI, provider flags become authoritative.
        if existing_intel.get("lineup_admin_source") == "admin_confirmed" and not lineup_confirmed:
            intel_data["lineup_confirmed"] = True
            intel_data["lineup_selected_player_ids"] = existing_intel.get("lineup_selected_player_ids", [])
        intel.data = {**existing_intel, **intel_data}
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



@app.get("/api/v1/admin/matches/{match_id}/wizard")
def get_match_wizard_data(match_id: str, _admin: bool = Depends(require_admin),
                          db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    intel_row = db.get(MatchIntelligence, match_id)
    intelligence = dict(intel_row.data or {}) if intel_row and isinstance(intel_row.data, dict) else {}
    profiles = db.scalars(select(PlayerSourceProfile).where(
        PlayerSourceProfile.match_id == match_id
    )).all()
    profile_map = {}
    for profile in profiles:
        profile_map.setdefault(profile.player_id, {})
        profile_map[profile.player_id].update(profile.data or {})
    squads = db.scalars(select(MatchSquad).where(
        MatchSquad.match_id == match_id
    )).all()
    players = []
    for squad in squads:
        player = db.get(Player, squad.player_id)
        profile = profile_map.get(squad.player_id, {})
        players.append({
            "player_id": squad.player_id,
            "player_name": player.name if player else squad.player_id,
            "team": squad.team,
            "role": squad.role,
            "credits": squad.credits,
            "selection_pct": squad.selection_pct,
            "status": squad.status,
            "image": profile.get("image"),
            "captain_pct": profile.get("captain_pct"),
            "vice_captain_pct": profile.get("vice_captain_pct"),
            "points": profile.get("points", profile.get("fantasy_points")),
            "batting_order": profile.get("batting_order"),
            "lineup_order": profile.get("lineup_order"),
            "dream11_id": (profile.get("fantasy_ids") or {}).get("dream11"),
        })
    lineup_status = str(intelligence.get("lineup_status") or "").lower()
    source_confirmed = (
        any(word in lineup_status for word in ("announc", "confirmed", "complete", "final"))
        and not any(word in lineup_status for word in ("not_announced", "not announced", "unannounced", "pending"))
    )
    lineup_confirmed = bool(intelligence.get("lineup_confirmed", source_confirmed))
    selected_ids = intelligence.get("lineup_selected_player_ids")
    if not isinstance(selected_ids, list):
        selected_ids = [p["player_id"] for p in players if p["status"] == "playing"]
    return {
        "match": {
            "id": match.id, "name": match.name, "format": match.format,
            "start_time": match.start_time, "venue": match.venue,
            "team_a": match.team_a, "team_b": match.team_b,
            "status": match.status, "source": match.source,
        },
        "players": players,
        "intelligence": intelligence,
        "lineup_confirmed": lineup_confirmed,
        "selected_player_ids": selected_ids,
        "credits_verified_count": sum(1 for p in players if p["credits"] is not None),
        "credits_missing_count": sum(1 for p in players if p["credits"] is None),
    }


@app.post("/api/v1/admin/matches/{match_id}/lineup")
def save_playing_xi(match_id: str, payload: PlayingXIUpdate,
                    _admin: bool = Depends(require_admin),
                    db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    squads = db.scalars(select(MatchSquad).where(MatchSquad.match_id == match_id)).all()
    by_id = {row.player_id: row for row in squads}
    selected = set(payload.selected_player_ids)
    if len(selected) != len(payload.selected_player_ids):
        raise HTTPException(422, "Duplicate player IDs are not allowed.")
    unknown = sorted(selected - set(by_id))
    if unknown:
        raise HTTPException(422, detail={"message": "Some selected players are not in this match squad.", "unknown_player_ids": unknown})
    if payload.confirmed:
        counts = {
            match.team_a: sum(1 for pid in selected if by_id[pid].team == match.team_a),
            match.team_b: sum(1 for pid in selected if by_id[pid].team == match.team_b),
        }
        if counts[match.team_a] != 11 or counts[match.team_b] != 11:
            raise HTTPException(422, detail={
                "message": "Official Playing XI confirmation requires exactly 11 players from each team.",
                "selected_by_team": counts,
                "action": "Select 11 players for each team, or save the list as provisional until official line-ups are announced."
            })
    for player_id, squad in by_id.items():
        if payload.confirmed:
            squad.status = "playing" if player_id in selected else "not_playing"
        else:
            # A provisional shortlist must not mark omitted squad members as unavailable.
            squad.status = "probable" if player_id in selected else "not_announced"
    intel = db.get(MatchIntelligence, match_id)
    data = dict(intel.data or {}) if intel and isinstance(intel.data, dict) else {}
    data["lineup_confirmed"] = bool(payload.confirmed)
    data["lineup_selected_player_ids"] = sorted(selected)
    data["lineup_admin_updated_at"] = datetime.now(timezone.utc).isoformat()
    data["lineup_admin_source"] = "admin_confirmed" if payload.confirmed else "admin_provisional"
    if intel:
        intel.data = data
    else:
        db.add(MatchIntelligence(match_id=match_id, data=data))
    db.commit()
    return {
        "saved": True, "match_id": match_id, "confirmed": payload.confirmed,
        "selected_count": len(selected),
        "selected_by_team": {
            match.team_a: sum(1 for pid in selected if by_id[pid].team == match.team_a),
            match.team_b: sum(1 for pid in selected if by_id[pid].team == match.team_b),
        },
        "note": "Unselected players remain available in provisional mode." if not payload.confirmed else "Official XI saved; unselected squad players are marked not_playing."
    }




def _save_cricbuzz_venue(db: Session, report: dict) -> Venue:
    provider_key = "CRICBUZZ:" + str(report["provider_venue_id"])
    row = db.get(Venue, provider_key)
    aliases = report.get("aliases") or []
    urls = [report["source_url"]] if report.get("source_url") else []
    profile = {
        "facts": report.get("facts") or {},
        "profile_text": report.get("profile_text"),
        "pitch_text": report.get("pitch_text"),
        "series_name": report.get("series_name"),
    }
    if row is None:
        row = Venue(
            provider_key=provider_key,
            name=report["name"],
            city_country=report.get("city_country"),
            aliases=aliases,
            provider="CRICBUZZ",
            provider_venue_id=str(report["provider_venue_id"]),
            facts=report.get("facts") or {},
            formats=report.get("formats") or {},
            profile=profile,
            source_urls=urls,
        )
        db.add(row)
    else:
        row.name = report["name"] or row.name
        row.city_country = report.get("city_country") or row.city_country
        row.aliases = sorted(set((row.aliases or []) + aliases))
        row.facts = {**(row.facts or {}), **(report.get("facts") or {})}
        row.formats = {**(row.formats or {}), **(report.get("formats") or {})}
        row.profile = {**(row.profile or {}), **profile}
        row.source_urls = sorted(set((row.source_urls or []) + urls))
    return row


def _venue_report_for_match(db: Session, match: Match):
    rows = db.scalars(select(Venue).where(Venue.provider == "CRICBUZZ")).all()
    normalize = lambda value: "".join(ch for ch in str(value or "").casefold() if ch.isalnum())
    wanted = normalize(match.venue)
    for venue in rows:
        names = [venue.name, venue.city_country] + list(venue.aliases or [])
        if any((normalize(name) == wanted or (wanted and (normalize(name) in wanted or wanted in normalize(name)))) for name in names if name):
            fmt = "T20" if match.format.upper() in {"T20", "T20I", "WT20", "WT20I"} else "ODI" if match.format.upper() in {"ODI", "WODI"} else "TEST"
            return venue, (venue.formats or {}).get(fmt)
    return None, None


@app.post("/api/v1/admin/matches/{match_id}/venue/import")
def import_cricbuzz_venue_report(match_id: str, payload: CricbuzzVenueImportRequest,
                                 _admin: bool = Depends(require_admin),
                                 db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    try:
        html = fetch_cricbuzz_venue_page(payload.url)
        report = parse_cricbuzz_venue(html, payload.url)
    except ValueError as exc:
        raise HTTPException(422, "Cricbuzz import rejected: " + str(exc)[:400])
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, detail={
            "message": "Cricbuzz refused the venue page request.",
            "upstream_status": exc.response.status_code,
            "action": "Open the Cricbuzz venue page in a browser and retry its HTTPS venue URL."
        })
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not fetch Cricbuzz venue page: " + type(exc).__name__)

    venue_row = _save_cricbuzz_venue(db, report)
    city = (report.get("city_country") or "").split(",")[0].strip()
    match.venue = report["name"] + (", " + city if city else "")
    venue_analysis = analyse_venue(report, match.format)
    intel_row = db.get(MatchIntelligence, match_id)
    data = dict(intel_row.data or {}) if intel_row and isinstance(intel_row.data, dict) else {}
    data["cricbuzz_venue_report"] = report
    data["venue_report_source_url"] = payload.url
    data["venue_provider"] = "CRICBUZZ"
    data["venue_id"] = venue_row.provider_key
    data["auto_venue_analysis"] = venue_analysis
    data.update(analysis_context_fields(venue_analysis))

    if intel_row is None:
        intel_row = MatchIntelligence(match_id=match_id, data=data)
        db.add(intel_row)
    else:
        intel_row.data = data
    # Persist format-specific ground adjustments before requesting player estimates.
    db.commit()

    # Team-strength recommendation is generated only when both sides have enough
    # format-matched historical player points. It is not a prediction of match winner.
    predictions = predict_match(db, match_id)
    strength = compare_squad_strength(match.team_a, match.team_b, predictions)
    data["team_strength_analysis"] = strength
    data["strong_team"] = strength.get("strong_team")
    intel_row = db.get(MatchIntelligence, match_id)
    intel_row.data = data
    db.commit()
    return {
        "imported": True,
        "match_id": match_id,
        "venue_id": venue_row.provider_key,
        "venue": report["name"],
        "format_used": venue_analysis.get("format"),
        "report": report,
        "venue_analysis": venue_analysis,
        "team_strength_analysis": strength,
        "note": "Venue and toss recommendations use format-specific Cricbuzz ground statistics. Strong-team comparison uses the current squads' format-matched player estimates; it is not a match-winner probability."
    }


@app.post("/api/v1/admin/venues/import-series")
def import_cricbuzz_series_venues(payload: CricbuzzSeriesImportRequest,
                                   _admin: bool = Depends(require_admin),
                                   db: Session = Depends(get_db)):
    try:
        html = fetch_cricbuzz_series_page(payload.url)
        venue_links = parse_cricbuzz_series_venues(html, payload.url)
    except ValueError as exc:
        raise HTTPException(422, "Cricbuzz series import rejected: " + str(exc)[:400])
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, detail={"message": "Cricbuzz series page request failed.", "upstream_status": exc.response.status_code})
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not fetch Cricbuzz series page: " + type(exc).__name__)

    imported, skipped, errors = [], [], []
    for item in venue_links[:60]:
        try:
            page = fetch_cricbuzz_venue_page(item["source_url"])
            report = parse_cricbuzz_venue(page, item["source_url"])
            _save_cricbuzz_venue(db, report)
            imported.append({"venue_id": "CRICBUZZ:" + str(report["provider_venue_id"]), "name": report["name"], "city_country": report.get("city_country"), "formats_available": sorted((report.get("formats") or {}).keys())})
        except Exception as exc:
            # Keep the stadium in the catalogue even when Cricbuzz has no
            # international format stats for this domestic/associate ground.
            basic_report = {
                "provider_venue_id": str(item["provider_venue_id"]),
                "name": item.get("name") or ("Venue " + str(item["provider_venue_id"])),
                "city_country": None,
                "aliases": [],
                "facts": {},
                "formats": {},
                "source_url": item["source_url"],
            }
            _save_cricbuzz_venue(db, basic_report)
            imported.append({"venue_id": "CRICBUZZ:" + str(item["provider_venue_id"]), "name": basic_report["name"], "city_country": None, "formats_available": [], "stats_pending": True})
            errors.append({"venue": basic_report["name"], "error": type(exc).__name__})
    db.commit()
    return {
        "provider": "CRICBUZZ",
        "series_url": payload.url,
        "series_venues_found": len(venue_links),
        "venues_imported": len(imported),
        "venues_skipped": len(skipped),
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:20],
        "note": "The venue catalogue grows as you import Cricbuzz series Venues pages from different countries and competitions. This does not claim to be a complete world-stadium census."
    }



@app.post("/api/v1/admin/venues/discover-series")
def discover_cricbuzz_series_and_venues(payload: CricbuzzSeriesIndexImportRequest,
                                        _admin: bool = Depends(require_admin),
                                        db: Session = Depends(get_db)):
    try:
        page = fetch_cricbuzz_series_index(payload.url)
        series = parse_cricbuzz_series_index(page, payload.url)
    except ValueError as exc:
        raise HTTPException(422, "Cricbuzz series discovery rejected: " + str(exc)[:400])
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, detail={"message": "Cricbuzz schedule/archive request failed.", "upstream_status": exc.response.status_code})
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not fetch Cricbuzz series index: " + type(exc).__name__)

    total_series = len(series)
    series = series[payload.series_offset:payload.series_offset + payload.max_series]
    discovered = []
    failures = []
    for series_item in series:
        try:
            venues_html = fetch_cricbuzz_series_page(series_item["venues_url"])
            venue_items = parse_cricbuzz_series_venues(venues_html, series_item["venues_url"])
            for item in venue_items:
                basic_report = {
                    "provider_venue_id": str(item["provider_venue_id"]),
                    "name": item.get("name") or ("Venue " + str(item["provider_venue_id"])),
                    "city_country": None,
                    "aliases": [],
                    "facts": {},
                    "formats": {},
                    "source_url": item["source_url"],
                }
                _save_cricbuzz_venue(db, basic_report)
                discovered.append({
                    "series": series_item["name"],
                    "venue_id": "CRICBUZZ:" + str(item["provider_venue_id"]),
                    "name": basic_report["name"],
                    "source_url": item["source_url"],
                    "stats_pending": True,
                })
        except Exception as exc:
            failures.append({"series": series_item["name"], "error": type(exc).__name__})
    db.commit()
    return {
        "provider": "CRICBUZZ",
        "index_url": payload.url,
        "series_total_available": total_series,
        "series_offset": payload.series_offset,
        "series_seen_this_batch": len(series),
        "next_series_offset": payload.series_offset + len(series),
        "has_more_series": payload.series_offset + len(series) < total_series,
        "series_with_venues_or_attempts": len(series) - len(failures),
        "venues_discovered": len(discovered),
        "venues_saved_or_updated": len(discovered),
        "venues": discovered,
        "failed_series": failures,
        "note": "Stadiums are saved to SQL as soon as they are discovered. This is a progressively growing catalogue from the series listed on the supplied schedule/archive page, not a guaranteed complete census of every ground worldwide."
    }


@app.post("/api/v1/admin/venues/enrich")
def enrich_pending_cricbuzz_venues(payload: VenueEnrichRequest,
                                   _admin: bool = Depends(require_admin),
                                   db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Venue)
        .where(Venue.provider == "CRICBUZZ")
        .order_by(Venue.updated_at.asc())
    ).all()
    pending = [row for row in rows if not (row.formats or {}) and row.source_urls]
    pending = pending[:payload.limit]
    enriched, pending_failed, errors = [], [], []
    for row in pending:
        source_url = (row.source_urls or [None])[0]
        if not source_url:
            continue
        try:
            page = fetch_cricbuzz_venue_page(source_url)
            report = parse_cricbuzz_venue(page, source_url)
            saved = _save_cricbuzz_venue(db, report)
            enriched.append({
                "venue_id": saved.provider_key,
                "name": saved.name,
                "city_country": saved.city_country,
                "formats_available": sorted((saved.formats or {}).keys()),
            })
        except Exception as exc:
            pending_failed.append(row.name)
            profile = dict(row.profile or {})
            profile["last_enrichment_attempt"] = datetime.now(timezone.utc).isoformat()
            profile["last_enrichment_error"] = type(exc).__name__
            row.profile = profile
            errors.append({"venue": row.name, "error": type(exc).__name__})
    db.commit()
    remaining = db.scalars(select(Venue).where(Venue.provider == "CRICBUZZ")).all()
    still_pending = sum(1 for row in remaining if not (row.formats or {}) and row.source_urls)
    return {
        "provider": "CRICBUZZ",
        "attempted": len(pending),
        "enriched": len(enriched),
        "failed_this_batch": len(pending_failed),
        "remaining_pending": still_pending,
        "enriched_venues": enriched,
        "errors": errors[:20],
        "note": "Enrichment is deliberately batched to limit upstream requests. Repeat until remaining_pending is zero or Cricbuzz has no extractable format statistics for the remaining grounds."
    }


@app.get("/api/v1/admin/venues")
def search_venue_catalogue(q: str | None = None, limit: int = 100,
                           _admin: bool = Depends(require_admin),
                           db: Session = Depends(get_db)):
    limit = max(1, min(limit, 300))
    query = select(Venue).order_by(Venue.name.asc())
    rows = db.scalars(query).all()
    if q:
        needle = "".join(ch for ch in q.casefold() if ch.isalnum())
        rows = [v for v in rows if any(
            needle in "".join(ch for ch in str(value or "").casefold() if ch.isalnum())
            for value in [v.name, v.city_country, *(v.aliases or [])]
        )]
    return {
        "count": len(rows[:limit]),
        "total_matches": len(rows),
        "venues": [{
            "venue_id": v.provider_key,
            "name": v.name,
            "city_country": v.city_country,
            "aliases": v.aliases or [],
            "formats_available": sorted((v.formats or {}).keys()),
            "source_urls": v.source_urls or [],
            "updated_at": v.updated_at.isoformat() if v.updated_at else None,
        } for v in rows[:limit]]
    }




@app.get("/api/v1/admin/matches/{match_id}/venue-suggestions")
def get_venue_suggestions(match_id: str, _admin: bool = Depends(require_admin),
                          db: Session = Depends(get_db)):
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(404, "Match not found")
    normalize = lambda value: "".join(ch for ch in str(value or "").casefold() if ch.isalnum())
    fmt = "T20" if match.format.upper() in {"T20", "T20I", "WT20", "WT20I"} else "ODI" if match.format.upper() in {"ODI", "WODI"} else "TEST"

    intel_row = db.get(MatchIntelligence, match_id)
    intel = dict(intel_row.data or {}) if intel_row and isinstance(intel_row.data, dict) else {}
    lineup_confirmed = bool(intel.get("lineup_confirmed"))
    confirmed_ids = set(intel.get("lineup_selected_player_ids") or [])

    squads_all = db.scalars(select(MatchSquad).where(MatchSquad.match_id == match_id)).all()
    squads = [
        row for row in squads_all
        if not lineup_confirmed or (
            row.status == "playing" and (not confirmed_ids or row.player_id in confirmed_ids)
        )
    ]
    squad_by_id = {row.player_id: row for row in squads}
    squad_player_ids_by_name = {}
    for squad in squads:
        current_player = db.get(Player, squad.player_id)
        if current_player:
            squad_player_ids_by_name.setdefault(normalize(current_player.name), squad.player_id)

    report = intel.get("cricbuzz_venue_report")
    venue_row = None
    if not report:
        venue_row, _ = _venue_report_for_match(db, match)
        if venue_row:
            report = {
                "provider": "CRICBUZZ",
                "provider_venue_id": venue_row.provider_venue_id,
                "name": venue_row.name,
                "city_country": venue_row.city_country,
                "aliases": venue_row.aliases or [],
                "formats": venue_row.formats or {},
                "facts": venue_row.facts or {},
                "profile_text": (venue_row.profile or {}).get("profile_text"),
                "pitch_text": (venue_row.profile or {}).get("pitch_text"),
                "source_urls": venue_row.source_urls or [],
            }

    venue_analysis = intel.get("auto_venue_analysis")
    if report and (not venue_analysis or venue_analysis.get("format") != fmt):
        venue_analysis = analyse_venue(report, match.format)
        # Persist catalogue-linked data so subsequent predictions and UI reads
        # use the same format-specific venue context.
        data = dict(intel)
        data["cricbuzz_venue_report"] = report
        data["auto_venue_analysis"] = venue_analysis
        data["venue_provider"] = "CRICBUZZ"
        if venue_row:
            data["venue_id"] = venue_row.provider_key
            if venue_row.source_urls:
                data["venue_report_source_url"] = venue_row.source_urls[0]
        data.update(analysis_context_fields(venue_analysis))
        if intel_row is None:
            intel_row = MatchIntelligence(match_id=match_id, data=data)
            db.add(intel_row)
        else:
            intel_row.data = data
        db.commit()
        intel = data

    history_rows = db.execute(
        select(PlayerMatchStats, Match)
        .join(Match, PlayerMatchStats.match_id == Match.id)
        .where(
            Match.venue.is_not(None),
            PlayerMatchStats.match_id != match_id,
            PlayerMatchStats.format == fmt,
        )
    ).all()
    target = normalize(match.venue)
    player_history = {}
    team_history = {
        match.team_a: {"players": set(), "matches": set(), "points": [], "runs": [], "wickets": []},
        match.team_b: {"players": set(), "matches": set(), "points": [], "runs": [], "wickets": []},
    }
    for stats, historical_match in history_rows:
        historical_venue = normalize(historical_match.venue)
        if not (historical_venue == target or (target and target in historical_venue) or (historical_venue and historical_venue in target)):
            continue
        player_id = stats.player_id
        if player_id not in squad_by_id:
            historical_player = db.get(Player, stats.player_id)
            player_id = squad_player_ids_by_name.get(normalize(historical_player.name)) if historical_player else None
        if player_id not in squad_by_id:
            continue
        squad = squad_by_id[player_id]
        entry = player_history.setdefault(player_id, {"matches": set(), "points": [], "runs": [], "wickets": []})
        entry["matches"].add(stats.match_id)
        if stats.fantasy_points is not None:
            entry["points"].append(float(stats.fantasy_points))
        entry["runs"].append(int(stats.runs or 0))
        entry["wickets"].append(int(stats.wickets or 0))
        team_entry = team_history.get(squad.team)
        if team_entry is not None:
            team_entry["players"].add(player_id)
            team_entry["matches"].add(stats.match_id)
            if stats.fantasy_points is not None:
                team_entry["points"].append(float(stats.fantasy_points))
            team_entry["runs"].append(int(stats.runs or 0))
            team_entry["wickets"].append(int(stats.wickets or 0))

    profiles = db.scalars(select(PlayerSourceProfile).where(
        PlayerSourceProfile.match_id == match_id
    )).all()
    profile_map = {}
    for profile in profiles:
        profile_map.setdefault(profile.player_id, {})
        profile_map[profile.player_id].update(profile.data or {})

    candidates = []
    for squad in squads:
        try:
            selection_pct = float(squad.selection_pct) if squad.selection_pct is not None else None
        except (TypeError, ValueError):
            selection_pct = None
        if selection_pct is None or selection_pct < 80:
            continue
        player = db.get(Player, squad.player_id)
        profile = profile_map.get(squad.player_id, {})
        history = player_history.get(squad.player_id, {})
        points = history.get("points", [])
        candidates.append({
            "player_id": squad.player_id,
            "player_name": player.name if player else squad.player_id,
            "team": squad.team,
            "role": squad.role,
            "credits": squad.credits,
            "image": profile.get("image"),
            "selection_pct": selection_pct,
            "captain_pct": profile.get("captain_pct", profile.get("ai11_captain_pct")),
            "vice_captain_pct": profile.get("vice_captain_pct", profile.get("ai11_vice_captain_pct")),
            "venue_matches": len(history.get("matches", set())),
            "scored_venue_matches": len(points),
            "avg_fantasy_points": round(sum(points) / len(points), 2) if points else None,
            "avg_runs": round(sum(history.get("runs", [])) / len(history.get("runs", [])), 1) if history.get("runs") else None,
            "total_venue_wickets": sum(history.get("wickets", [])),
            "selection_eligible": True,
        })
    candidates.sort(key=lambda p: (
        p["selection_pct"],
        p["avg_fantasy_points"] if p["avg_fantasy_points"] is not None else -1
    ), reverse=True)

    team_analysis = []
    for team_name in (match.team_a, match.team_b):
        item = team_history[team_name]
        players = []
        for player_id in item["players"]:
            player = db.get(Player, player_id)
            history = player_history[player_id]
            points = history["points"]
            players.append({
                "player_id": player_id,
                "player_name": player.name if player else player_id,
                "venue_matches": len(history["matches"]),
                "scored_venue_matches": len(points),
                "avg_fantasy_points": round(sum(points) / len(points), 2) if points else None,
                "avg_runs": round(sum(history["runs"]) / len(history["runs"]), 1) if history["runs"] else None,
                "wickets": sum(history["wickets"]),
            })
        players.sort(key=lambda p: (
            p["avg_fantasy_points"] if p["avg_fantasy_points"] is not None else -1,
            p["venue_matches"]
        ), reverse=True)
        points = item["points"]
        team_analysis.append({
            "team": team_name,
            "format": fmt,
            "squad_players_with_venue_records": len(item["players"]),
            "venue_matches_in_sample": len(item["matches"]),
            "player_match_records": len(item["runs"]),
            "average_fantasy_points_per_player_match": round(sum(points) / len(points), 2) if points else None,
            "average_runs_per_player_match": round(sum(item["runs"]) / len(item["runs"]), 1) if item["runs"] else None,
            "total_wickets_in_sample": sum(item["wickets"]),
            "top_players": players[:5],
            "sample_note": "Format-matched scorecards for the current XI/squad; this is not the team's venue win percentage."
        })

    predictions = predict_match(db, match_id)
    if lineup_confirmed:
        predictions = [p for p in predictions if p.get("status") in {"playing", "confirmed"}]
    strength = compare_squad_strength(match.team_a, match.team_b, predictions)
    if report:
        data = dict(intel)
        data["team_strength_analysis"] = strength
        data["strong_team"] = strength.get("strong_team")
        if intel_row is None:
            db.add(MatchIntelligence(match_id=match_id, data=data))
        else:
            intel_row.data = data
        db.commit()

    return {
        "available": bool(report or any(player_history.values())),
        "venue": match.venue,
        "format": fmt,
        "venue_report": report,
        "venue_analysis": venue_analysis,
        "team_strength_analysis": strength,
        "team_analysis": team_analysis,
        "suggestions": candidates[:5],
        "high_selection_recommendations": candidates[:5],
        "eligible_over_80_count": len(candidates),
        "recommended_fixed_count": min(5, len(candidates)),
        "fixed_selection_threshold_pct": 80,
        "reason": None if report else "No Cricbuzz venue page is linked to this ground yet. Paste its venue URL or import a series Venues page to populate the SQL stadium catalogue."
    }



FEATURED_CRICBUZZ_VENUES = [
    "https://www.cricbuzz.com/cricket-series/11876/england-tour-of-australia-2026/venues/38/waca-ground",
    "https://www.cricbuzz.com/cricket-series/13430/nepal-premier-league-2026/venues/458/tribhuvan-university-international-cricket-ground",
    "https://www.cricbuzz.com/cricket-series/12677/womens-big-bash-league-2026/venues/122/junction-oval",
]


@app.post("/api/v1/admin/venues/import")
def import_venue_into_catalogue(payload: CricbuzzVenueImportRequest,
                                _admin: bool = Depends(require_admin),
                                db: Session = Depends(get_db)):
    try:
        page = fetch_cricbuzz_venue_page(payload.url)
        report = parse_cricbuzz_venue(page, payload.url)
    except ValueError as exc:
        raise HTTPException(422, "Cricbuzz venue import rejected: " + str(exc)[:400])
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, detail={
            "message": "Cricbuzz refused the venue page request.",
            "upstream_status": exc.response.status_code,
            "action": "Open the venue URL in a browser and retry."
        })
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not fetch Cricbuzz venue page: " + type(exc).__name__)
    row = _save_cricbuzz_venue(db, report)
    db.commit()
    return {
        "imported": True,
        "venue_id": row.provider_key,
        "name": row.name,
        "city_country": row.city_country,
        "formats_available": sorted((row.formats or {}).keys()),
        "report": report,
        "note": "Venue saved to the SQL stadium catalogue."
    }


@app.post("/api/v1/admin/venues/import-featured")
def import_user_supplied_featured_venues(_admin: bool = Depends(require_admin),
                                         db: Session = Depends(get_db)):
    imported, failed = [], []
    for url in FEATURED_CRICBUZZ_VENUES:
        try:
            page = fetch_cricbuzz_venue_page(url)
            report = parse_cricbuzz_venue(page, url)
            row = _save_cricbuzz_venue(db, report)
            imported.append({
                "venue_id": row.provider_key,
                "name": row.name,
                "city_country": row.city_country,
                "formats_available": sorted((row.formats or {}).keys()),
                "source_url": url,
            })
        except Exception as exc:
            failed.append({
                "url": url,
                "error": type(exc).__name__,
                "message": str(exc)[:180],
            })
    db.commit()
    return {
        "requested": len(FEATURED_CRICBUZZ_VENUES),
        "imported": len(imported),
        "failed": len(failed),
        "venues": imported,
        "errors": failed,
        "note": "Successfully imported profiles are saved in the SQL venue catalogue and can be reused across matches."
    }


@app.get("/admin/stadiums", response_class=HTMLResponse)
def stadium_database_admin_page():
    stadiums_file = Path(__file__).with_name("stadiums.html")
    if not stadiums_file.is_file():
        raise HTTPException(500, "Stadium database interface is missing.")
    return HTMLResponse(stadiums_file.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    admin_file = Path(__file__).with_name("admin.html")
    if not admin_file.is_file():
        raise HTTPException(500, "Admin interface file is missing.")
    return HTMLResponse(admin_file.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

