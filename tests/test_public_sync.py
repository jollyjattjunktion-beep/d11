from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import main
from app.models import Match, MatchIntelligence


def fixture(match_id="public-sync-1"):
    start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    return {
        "id": match_id,
        "series": "India tour of New Zealand ODI",
        "startTime": start,
        "status": "upcoming",
        "left": {"code": "NZ", "name": "New Zealand", "image": "https://img.example/nz.png"},
        "right": {"code": "IND", "name": "India", "image": "https://img.example/ind.png"},
    }


def test_public_fixture_sync_creates_then_hides_without_deleting_sql_history(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    try:
        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: [fixture()])
        created = main._sync_public_match_feed(db, force=True)
        assert created["ok"] is True
        assert created["created"] == 1

        match = db.get(Match, "public-sync-1")
        assert match is not None
        assert match.status == "upcoming"
        assert len(main._public_match_records(db)) == 1

        # Once the ODI's format-aware playing window has elapsed, an omitted
        # fixture is marked complete and removed from the public list.
        match.start_time = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        match.status = "upcoming"
        db.commit()
        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: [])
        hidden = main._sync_public_match_feed(db, force=True)
        assert hidden["ok"] is True
        assert hidden["hidden"] == 1

        retained = db.get(Match, "public-sync-1")
        assert retained is not None
        intelligence = db.get(MatchIntelligence, "public-sync-1")
        assert intelligence.data["public_feed"]["public_listed"] is False
        assert main._public_match_records(db) == []
    finally:
        db.close()
        engine.dispose()



def test_omitted_match_is_kept_live_during_playing_window(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    try:
        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: [fixture("public-live-2")])
        main._sync_public_match_feed(db, force=True)
        match = db.get(Match, "public-live-2")
        match.start_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        match.status = "upcoming"
        db.commit()

        monkeypatch.setattr(main, "_teamgeneration_request", lambda _url: [])
        main._sync_public_match_feed(db, force=True)

        retained = db.get(Match, "public-live-2")
        assert retained.status == "live"
        assert db.get(MatchIntelligence, "public-live-2").data["public_feed"]["public_listed"] is True
        assert len(main._public_match_records(db)) == 1
    finally:
        db.close()
        engine.dispose()
